"""Which term controls: when an SOW and its MSA say different things about the same term.

Example: Lucca's MSA §4.3 says net 45, SOW No. 2 says net 60, and MSA §2.3 (Order of
Precedence) decides which one wins. Nonna lines up the pieces, in code:
- the two terms side by side, with their sections (the MSA as amended)
- the MSA's order-of-precedence clause, word for word
- whether the SOW names the MSA section and says it supersedes it, with the SOW's own sentence

Nonna never decides which term controls. That's a legal call, so the attorney makes it and
says why. Calls are append-only: changing your mind adds a new call, and the old one stays
in the history. A call only covers the exact two values it was made for. If either term is
later corrected, Nonna asks again.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from nonna import amendments, playbook
from nonna.lookups import NotFound, ReviewRejected, to_source
from nonna.models import Clause, Contract, Counterparty, CounterpartyPosition, PrecedenceDecision
from nonna.schemas import SourceContract

__all__ = [
    "CallIn", "NotFound", "PrecedenceReport", "ReviewRejected", "TermConflict",
    "check_supersede", "find_rule", "get_conflicts", "record_call", "terms_differ",
]

Controls = Literal["msa", "sow"]

# The values that matter when comparing each term. Billing style (milestone vs invoice) isn't
# compared: MSAs usually leave that to each SOW, so it's not a conflict.
COMPARED_KEYS: dict[str, list[str]] = {
    "payment_terms": ["net_days"],
    "liability_cap": ["cap_amount"],
    "governing_law": ["jurisdiction"],
    "indemnification": ["is_mutual", "covers_ip_infringement"],
    "termination_convenience": ["notice_days", "who_may_terminate"],
    "confidentiality": ["survival_years", "perpetual"],
    "insurance": ["general_liability_per_occurrence", "general_liability_aggregate"],
}
LABELS = {
    "payment_terms": "Payment terms",
    "liability_cap": "Liability cap",
    "governing_law": "Governing law",
    "indemnification": "Indemnification",
    "termination_convenience": "Termination for convenience",
    "confidentiality": "Confidentiality period",
    "insurance": "Insurance minimums",
}
# Contracts that sit under an MSA
UNDER_MSA = ("SOW", "change_order")


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class TermSide(BaseModel):
    clause_id: int
    value: str  # in plain English, like "Net 45"
    section_number: str | None
    source: SourceContract
    amended_by: SourceContract | None = None  # set when an amendment changed the MSA's term
    review_status: str


class PrecedenceRule(BaseModel):
    """The MSA's order-of-precedence clause, word for word (as amended)."""

    section_number: str
    heading: str
    text: str
    source: SourceContract
    amended: bool  # an amendment changed or added this section


class SupersedeCheck(BaseModel):
    """What the SOW says about the MSA section, checked in code."""

    msa_section: str | None  # the MSA section the SOW would need to name, like "4.3"
    names_section: bool  # the SOW mentions that section
    says_supersedes: bool  # in the same sentence, it says it supersedes, replaces, or overrides it
    quote: str | None  # the SOW's own sentence, so the attorney can read it
    quote_source: str | None  # "SOW §5.3", for citing it


class ControlCall(BaseModel):
    id: int
    controls: Controls
    note: str
    decided_by: str
    decided_at: datetime


class TermConflict(BaseModel):
    clause_type: str
    label: str
    msa: TermSide
    sow: TermSide
    rule: PrecedenceRule | None  # None: Nonna couldn't find one in the MSA
    check: SupersedeCheck
    call: ControlCall | None  # the attorney's call, if it still matches both values


class PrecedenceReport(BaseModel):
    counterparty_id: int
    counterparty_name: str
    conflicts: list[TermConflict]
    open_count: int  # conflicts with no attorney call yet


class CallIn(BaseModel):
    controls: Controls
    note: str = Field(min_length=1, max_length=2000)  # why, in the attorney's words
    decided_by: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Pure checks (easy to test without a database)
# ---------------------------------------------------------------------------

def _norm_law(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b(the\s+)?(state|commonwealth)\s+of\s+", "", text)
    return re.sub(r"[^a-z ]", "", text).strip()


def terms_differ(clause_type: str, msa_values: dict[str, Any], sow_values: dict[str, Any]) -> bool:
    """True when the SOW's term says something different from the MSA's.

    A value the SOW doesn't state isn't a conflict: the SOW is just silent on it.
    """
    for key in COMPARED_KEYS.get(clause_type, []):
        sow_value = sow_values.get(key)
        msa_value = msa_values.get(key)
        if sow_value is None or msa_value is None:
            continue
        if clause_type == "governing_law":
            if _norm_law(sow_value) != _norm_law(msa_value):
                return True
        elif str(sow_value) != str(msa_value) and not _same_number(sow_value, msa_value):
            return True
    return False


def _same_number(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


RULE_HEADING = re.compile(r"precedence|conflict|inconsisten", re.IGNORECASE)
RULE_TEXT = re.compile(r"(conflict|inconsistenc\w*)\s+between", re.IGNORECASE)
MENTIONS_SOW = re.compile(r"\bSOWs?\b|statements?\s+of\s+work", re.IGNORECASE)
RULE_MAX = 1500


def find_rule(sections: list[tuple[str, str, str]]) -> tuple[str, str, str] | None:
    """The order-of-precedence section among (number, heading, text), or None.

    A heading like "Order of Precedence" wins. Otherwise, a section that talks about a
    conflict between the agreement and an SOW.
    """
    for number, heading, text in sections:
        if RULE_HEADING.search(heading) and MENTIONS_SOW.search(text):
            return number, heading, text
    for number, heading, text in sections:
        if RULE_TEXT.search(text) and MENTIONS_SOW.search(text):
            return number, heading, text
    return None


SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z(\"“])")
SAYS_SUPERSEDES = re.compile(
    r"supersed|in lieu of|notwithstanding|replac|instead of|overrid|prevail|shall not apply|controls?\b",
    re.IGNORECASE,
)


def _mentions(number: str) -> re.Pattern[str]:
    # "Section 4.3" or "§4.3", but not 4.31 or 4.3.1
    return re.compile(rf"(?:Section|§)\s*{re.escape(number)}(?![\d]|\.\d)", re.IGNORECASE)


def check_supersede(msa_section: str | None, places: list[tuple[str, str]]) -> SupersedeCheck:
    """Does the SOW name the MSA section, and say it supersedes it?

    places are (label, text) to search, best first: the SOW's own clause, then the whole SOW.
    Returns the first sentence that names the section, preferring one that also says it
    supersedes it.
    """
    if not msa_section:
        return SupersedeCheck(msa_section=None, names_section=False, says_supersedes=False, quote=None, quote_source=None)
    pattern = _mentions(msa_section)
    named: tuple[str, str] | None = None
    for label, text in places:
        flat = re.sub(r"\s+", " ", text or "").strip()
        for sentence in SENTENCE.split(flat):
            if not pattern.search(sentence):
                continue
            if SAYS_SUPERSEDES.search(sentence):
                return SupersedeCheck(
                    msa_section=msa_section, names_section=True, says_supersedes=True,
                    quote=sentence[:600], quote_source=label,
                )
            named = named or (label, sentence)
    if named:
        return SupersedeCheck(
            msa_section=msa_section, names_section=True, says_supersedes=False,
            quote=named[1][:600], quote_source=named[0],
        )
    return SupersedeCheck(msa_section=msa_section, names_section=False, says_supersedes=False, quote=None, quote_source=None)


# ---------------------------------------------------------------------------
# Reading the database
# ---------------------------------------------------------------------------

def _values(clause: Clause) -> dict[str, Any]:
    return {t.term_key: t.value for t in clause.terms}


def _describe(clause: Clause) -> str:
    unit = next((t.unit for t in clause.terms if t.term_key == "cap_amount"), None)
    return playbook.describe_value(clause.clause_type, _values(clause), unit)


def _usable(clause: Clause) -> bool:
    return clause.presence == "present" and clause.review_status != "rejected" and bool(clause.terms)


def _msa_for(contract: Contract, msas: list[Contract]) -> Contract | None:
    """The MSA an SOW or change order sits under."""
    seen = set()
    current = contract.parent
    while current is not None and current.id not in seen:
        if current.contract_type == "MSA":
            return current
        seen.add(current.id)
        current = current.parent
    return msas[0] if len(msas) == 1 else None


def _side(clause: Clause, section: str | None = None, amended_by: Contract | None = None) -> TermSide:
    return TermSide(
        clause_id=clause.id,
        value=_describe(clause),
        section_number=section if section is not None else clause.section_number,
        source=to_source(clause.contract),
        amended_by=to_source(amended_by) if amended_by is not None else None,
        review_status=clause.review_status,
    )


def _latest_calls(session: Session, sow_clause_ids: list[int]) -> dict[int, PrecedenceDecision]:
    if not sow_clause_ids:
        return {}
    calls = session.scalars(
        select(PrecedenceDecision)
        .where(PrecedenceDecision.sow_clause_id.in_(sow_clause_ids))
        .order_by(PrecedenceDecision.decided_at, PrecedenceDecision.id)
    )
    return {c.sow_clause_id: c for c in calls}  # later calls overwrite earlier ones


def get_conflicts(session: Session, counterparty_id: int) -> PrecedenceReport:
    """Every term where an SOW (or change order) says something different from its MSA."""
    vendor = session.get(
        Counterparty, counterparty_id,
        options=[selectinload(Counterparty.contracts).selectinload(Contract.clauses).selectinload(Clause.terms)],
    )
    if vendor is None:
        raise NotFound(f"No counterparty with id {counterparty_id}.")

    msas = [c for c in vendor.contracts if c.contract_type == "MSA"]
    positions = session.scalars(
        select(CounterpartyPosition).where(
            CounterpartyPosition.counterparty_id == counterparty_id,
            CounterpartyPosition.superseded_at.is_(None),
        )
    ).all()
    agreed = {p.clause_type: p.baseline_clause for p in positions if "MSA" in p.contract_type_scope}

    rules: dict[int, PrecedenceRule | None] = {}
    conflicts: list[tuple[TermConflict, Clause]] = []

    for contract in vendor.contracts:
        if contract.contract_type not in UNDER_MSA:
            continue
        msa = _msa_for(contract, msas)
        if msa is None:
            continue
        family = {msa.id} | {a.id for a in msa.amendments}

        for sow_clause in contract.clauses:
            if sow_clause.clause_type not in COMPARED_KEYS or not _usable(sow_clause):
                continue
            own = next((c for c in msa.clauses if c.clause_type == sow_clause.clause_type and _usable(c)), None)
            baseline = agreed.get(sow_clause.clause_type)
            # The MSA's term as amended: the agreed baseline when it belongs to this MSA's family
            msa_clause = baseline if baseline is not None and baseline.contract_id in family else own
            if msa_clause is None or not terms_differ(sow_clause.clause_type, _values(msa_clause), _values(sow_clause)):
                continue

            section = own.section_number if own is not None else msa_clause.section_number
            amended_by = msa_clause.contract if msa_clause.contract_id != msa.id else None
            if msa.id not in rules:
                rules[msa.id] = _rule_for(session, msa)

            conflict = TermConflict(
                clause_type=sow_clause.clause_type,
                label=LABELS[sow_clause.clause_type],
                msa=_side(msa_clause, section, amended_by),
                sow=_side(sow_clause),
                rule=rules[msa.id],
                check=check_supersede(section, [
                    (_cite(contract, sow_clause.section_number), sow_clause.full_text or ""),
                    (_cite(contract, None), contract.full_text or ""),
                ]),
                call=None,
            )
            conflicts.append((conflict, msa_clause))

    calls = _latest_calls(session, [c.sow.clause_id for c, _ in conflicts])
    for conflict, _ in conflicts:
        call = calls.get(conflict.sow.clause_id)
        # A call only covers the two values it was made for
        if call is not None and call.sow_value == conflict.sow.value and call.msa_value == conflict.msa.value:
            conflict.call = ControlCall(
                id=call.id, controls=call.controls, note=call.note,
                decided_by=call.decided_by, decided_at=call.decided_at,
            )

    found = [c for c, _ in conflicts]
    return PrecedenceReport(
        counterparty_id=vendor.id,
        counterparty_name=vendor.name,
        conflicts=found,
        open_count=sum(1 for c in found if c.call is None),
    )


def _cite(contract: Contract, section: str | None) -> str:
    short = "SOW" if contract.contract_type == "SOW" else "Change order"
    match = re.search(r"No\.\s*(\d+)", contract.title, re.IGNORECASE)
    name = f"{short} No. {match.group(1)}" if match else contract.title
    return f"{name} §{section}" if section else name


def _rule_for(session: Session, msa: Contract) -> PrecedenceRule | None:
    try:
        amended = amendments.as_amended(session, msa.id)
    except amendments.NotFound:
        return None
    live = [s for s in amended.sections if s.status != "deleted"]
    found = find_rule([(s.number, s.heading, s.text) for s in live])
    if found is None:
        return None
    number, heading, text = found
    section = next(s for s in live if s.number == number)
    text = re.sub(r"\s+", " ", text).strip()  # PDF line breaks aren't meaningful
    return PrecedenceRule(
        section_number=number,
        heading=heading,
        text=text if len(text) <= RULE_MAX else text[:RULE_MAX].rsplit(" ", 1)[0] + " …",
        source=to_source(msa),
        amended=section.status != "original",
    )


# ---------------------------------------------------------------------------
# Recording the attorney's call
# ---------------------------------------------------------------------------

def record_call(session: Session, sow_clause_id: int, call: CallIn) -> ControlCall:
    """Save the attorney's call on which term controls. Append-only."""
    clause = session.get(Clause, sow_clause_id)
    if clause is None:
        raise NotFound(f"No clause with id {sow_clause_id}.")
    report = get_conflicts(session, clause.contract.counterparty_id)
    conflict = next((c for c in report.conflicts if c.sow.clause_id == sow_clause_id), None)
    if conflict is None:
        raise ReviewRejected("This term doesn't conflict with the MSA anymore, so there's nothing to decide.")
    note = call.note.strip()
    if not note:
        raise ReviewRejected("Say why this term controls.")

    decision = PrecedenceDecision(
        sow_clause_id=sow_clause_id,
        msa_clause_id=conflict.msa.clause_id,
        controls=call.controls,
        sow_value=conflict.sow.value,
        msa_value=conflict.msa.value,
        note=note,
        decided_by=call.decided_by.strip(),
    )
    session.add(decision)
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error
    session.refresh(decision)
    return ControlCall(
        id=decision.id, controls=decision.controls, note=decision.note,
        decided_by=decision.decided_by, decided_at=decision.decided_at,
    )