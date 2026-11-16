"""Aurelia's playbook: our standard positions, the fallbacks we'll accept, and what needs escalating.

Every vendor's terms are checked against it in code, never by the model:
- Standard: what we ask for and usually get.
- Fallback: not our first ask, but an attorney can agree to it without escalating.
- Outside: needs sign-off from the GC before we agree.
- Can't compare: Nonna doesn't have what it needs (a cap in another currency, a missing
  notice period), so a person has to check.

Rules are versioned like baselines: editing one keeps the old version as history, and every
edit needs a note saying why.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from nonna.models import Clause, Contract, Counterparty, CounterpartyPosition, PlaybookRule
from nonna.schemas import PlaybookAssessment as Assessment
from nonna.schemas import SourceContract

CLAUSE_TYPES = ["liability_cap", "payment_terms", "governing_law", "indemnification", "term_renewal"]
LABELS = {
    "liability_cap": "Liability cap",
    "payment_terms": "Payment terms",
    "governing_law": "Governing law",
    "indemnification": "Indemnification",
    "term_renewal": "Term and renewal",
}

# What each rule may contain, and what kind of value each setting is
RULE_FIELDS: dict[str, dict[str, str]] = {
    "liability_cap": {"min_cap": "amount"},
    "payment_terms": {"min_net_days": "days"},
    "governing_law": {"jurisdictions": "list"},
    "indemnification": {"mutual": "yes_no", "covers_ip": "yes_no"},
    "term_renewal": {"max_notice_days": "days", "max_renewal_months": "months"},
}


class RuleOut(BaseModel):
    clause_type: str
    label: str
    standard: dict[str, Any]
    fallback: dict[str, Any]
    standard_text: str  # the rule in plain English
    fallback_text: str
    guidance: str
    note: str | None
    set_by: str
    set_at: datetime
    version: int


class RuleIn(BaseModel):
    standard: dict[str, Any]
    fallback: dict[str, Any]
    guidance: str = Field(min_length=1)
    note: str = Field(min_length=1)  # why the playbook changed
    set_by: str = Field(min_length=1)


class Cell(Assessment):
    source: SourceContract


class PlaybookRow(BaseModel):
    counterparty_id: int
    counterparty_name: str
    cells: dict[str, Cell | None]  # by clause type; None means nothing agreed on file


class PlaybookCheck(BaseModel):
    rules: list[RuleOut]
    rows: list[PlaybookRow]
    outside_count: int


class RuleRejected(Exception):
    pass


# ---------------------------------------------------------------------------
# Describing values and rules in plain English
# ---------------------------------------------------------------------------

def _money(amount: Any, unit: str | None = "USD") -> str:
    amount = Decimal(str(amount))
    if (unit or "USD") == "USD":
        return f"${amount:,.0f}"
    return f"{unit} {amount:,.0f}"


def _period(months: int) -> str:
    if months % 12 == 0:
        years = months // 12
        return "1 year" if years == 1 else f"{years} years"
    return "1 month" if months == 1 else f"{months} months"


def describe_value(clause_type: str, values: dict[str, Any], unit: str | None = None) -> str:
    if clause_type == "liability_cap":
        cap = values.get("cap_amount")
        return _money(cap, unit) if cap is not None else "No cap"
    if clause_type == "payment_terms":
        days = values.get("net_days")
        text = f"Net {int(days)}" if days is not None else "Payment terms"
        return text + (", milestone" if values.get("payment_structure") == "milestone" else "")
    if clause_type == "governing_law":
        return str(values.get("jurisdiction") or "Not stated")
    if clause_type == "indemnification":
        mutual = values.get("is_mutual")
        text = "Mutual" if mutual else "One-way" if mutual is False else "Indemnification"
        return text + (", covers IP" if values.get("covers_ip_infringement") else "")
    if clause_type == "term_renewal":
        if values.get("ends_on_event"):
            return "Ends when the work is done"
        months = values.get("initial_term_months")
        text = _period(int(months)) if months else "Term"
        if values.get("auto_renews"):
            renewal = values.get("renewal_term_months")
            text += f", renews every {_period(int(renewal))}" if renewal else ", renews automatically"
            notice = values.get("notice_days")
            if notice is not None:
                text += f", {int(notice)} days' notice"
        elif values.get("auto_renews") is False:
            text += ", no auto-renewal"
        return text
    return ""


def describe_rule(clause_type: str, rule: dict[str, Any]) -> str:
    """Starts lowercase (unless it's a place name) so it reads well mid-sentence."""
    if clause_type == "liability_cap":
        return f"a cap of at least {_money(rule['min_cap'])}"
    if clause_type == "payment_terms":
        return f"net {rule['min_net_days']} or longer"
    if clause_type == "governing_law":
        places = rule["jurisdictions"]
        listed = places[0] if len(places) == 1 else ", ".join(places[:-1]) + " or " + places[-1]
        return listed + " law"
    if clause_type == "indemnification":
        text = "mutual" if rule.get("mutual") else "mutual or one-way"
        return text + (", covering IP infringement" if rule.get("covers_ip") else "")
    if clause_type == "term_renewal":
        return (
            f"renewals of {_period(rule['max_renewal_months'])} or less, "
            f"with {rule['max_notice_days']} days' notice or less to stop them"
        )
    return ""


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------------------
# Checking a term against the playbook (pure, so it's easy to test)
# ---------------------------------------------------------------------------

def _meets(clause_type: str, rule: dict[str, Any], values: dict[str, Any]) -> bool:
    if clause_type == "liability_cap":
        cap = values.get("cap_amount")
        return cap is not None and Decimal(str(cap)) >= Decimal(str(rule["min_cap"]))
    if clause_type == "payment_terms":
        days = values.get("net_days")
        return days is not None and int(days) >= int(rule["min_net_days"])
    if clause_type == "governing_law":
        law = str(values.get("jurisdiction") or "").lower()
        return bool(law) and any(j.lower() in law or law in j.lower() for j in rule["jurisdictions"])
    if clause_type == "indemnification":
        if rule.get("mutual") and values.get("is_mutual") is not True:
            return False
        if rule.get("covers_ip") and values.get("covers_ip_infringement") is not True:
            return False
        return True
    if clause_type == "term_renewal":
        if values.get("ends_on_event") or values.get("auto_renews") is not True:
            return True  # nothing to get stuck in
        notice, renewal = values.get("notice_days"), values.get("renewal_term_months")
        return (
            notice is not None and int(notice) <= int(rule["max_notice_days"])
            and (renewal is None or int(renewal) <= int(rule["max_renewal_months"]))
        )
    return False


def assess(
    clause_type: str,
    standard: dict[str, Any],
    fallback: dict[str, Any],
    values: dict[str, Any],
    unit: str | None = None,
    presence: str = "present",
    pending: bool = False,
) -> Assessment | None:
    """Where one term lands in the playbook. None when there's nothing of its own to check.

    pending means the term is still waiting for review, so an off-playbook term needs the GC
    before anyone approves it. A signed term can't change now, so it's something to raise at renewal.
    """
    result = _assess(clause_type, standard, fallback, values, unit, presence)
    if result is None:
        return None
    result.value = describe_value(clause_type, values, unit)
    if result.tier == "outside" and pending:
        result.needs_sign_off = True
        result.reason += " Get GC sign-off before approving it."
    return result


def _assess(
    clause_type: str,
    standard: dict[str, Any],
    fallback: dict[str, Any],
    values: dict[str, Any],
    unit: str | None,
    presence: str,
) -> Assessment | None:
    if presence == "incorporated_by_reference":
        return None  # it follows the MSA, which is checked on its own
    value = describe_value(clause_type, values, unit)

    if clause_type == "liability_cap":
        if presence == "absent":
            return Assessment(tier="outside", reason=(
                f"No cap at all. Our standard is {describe_rule(clause_type, standard)}, "
                "and unlimited liability cuts both ways."
            ))
        if values.get("cap_amount") is None:
            return Assessment(tier="not_comparable", reason="The cap amount isn't on file, so check it by hand.")
        if (unit or "USD") != "USD":
            return Assessment(tier="not_comparable", reason=(
                f"The cap is {value}. The playbook is in US dollars, and Nonna doesn't convert currencies."
            ))
    elif presence != "present":
        return None
    if clause_type == "term_renewal" and values.get("auto_renews") is True and values.get("notice_days") is None:
        return Assessment(tier="not_comparable", reason="It renews automatically, but the notice period isn't on file.")
    if not values:
        return Assessment(tier="not_comparable", reason="Nothing was extracted to compare, so check it by hand.")

    if clause_type == "term_renewal" and (values.get("ends_on_event") or values.get("auto_renews") is False):
        return Assessment(tier="standard", reason=f"{value}. Nothing renews on its own, so there's nothing to get stuck in.")
    if _meets(clause_type, standard, values):
        return Assessment(tier="standard", reason=f"{value} meets our standard ({describe_rule(clause_type, standard)}).")
    if _meets(clause_type, fallback, values):
        return Assessment(tier="fallback", reason=(
            f"{value} is below our standard ({describe_rule(clause_type, standard)}) "
            f"but within our fallback ({describe_rule(clause_type, fallback)})."
        ))
    return Assessment(tier="outside", reason=(
        f"{value} is off our playbook. Even our fallback is {describe_rule(clause_type, fallback)}."
    ))


def check_rule(clause_type: str, rule: dict[str, Any]) -> dict[str, Any]:
    """Make sure an edited rule has exactly the settings its clause type needs."""
    fields = RULE_FIELDS.get(clause_type)
    if fields is None:
        raise RuleRejected(f"Nonna's playbook doesn't cover {clause_type}.")
    clean: dict[str, Any] = {}
    for key, kind in fields.items():
        raw = rule.get(key)
        if kind == "yes_no":
            clean[key] = bool(raw)
            continue
        if raw is None or raw == "" or raw == []:
            raise RuleRejected(f"Fill in {key.replace('_', ' ')}.")
        if kind == "list":
            items = raw if isinstance(raw, list) else str(raw).split(",")
            items = [str(i).strip() for i in items if str(i).strip()]
            if not items:
                raise RuleRejected("List at least one jurisdiction.")
            clean[key] = items
        else:
            try:
                number = int(Decimal(str(raw).replace(",", "").replace("$", "")))
            except Exception:
                raise RuleRejected(f"{key.replace('_', ' ').capitalize()} needs to be a number.") from None
            if number < 0:
                raise RuleRejected(f"{key.replace('_', ' ').capitalize()} can't be negative.")
            clean[key] = number
    return clean


def check_fallback(clause_type: str, standard: dict[str, Any], fallback: dict[str, Any]) -> None:
    """The fallback is what we accept when we can't get the standard, so it can't ask for more.

    For governing law, every standard jurisdiction is also acceptable as a fallback.
    """
    stricter = {
        "liability_cap": fallback.get("min_cap", 0) > standard.get("min_cap", 0),
        "payment_terms": fallback.get("min_net_days", 0) > standard.get("min_net_days", 0),
        "indemnification": (fallback.get("mutual") and not standard.get("mutual"))
        or (fallback.get("covers_ip") and not standard.get("covers_ip")),
        "term_renewal": fallback.get("max_notice_days", 0) < standard.get("max_notice_days", 0)
        or fallback.get("max_renewal_months", 0) < standard.get("max_renewal_months", 0),
    }.get(clause_type, False)
    if stricter:
        raise RuleRejected("The fallback can't ask for more than the standard. It's what we accept when we can't get the standard.")
    if clause_type == "governing_law":
        extra = [j for j in fallback["jurisdictions"] if j.lower() not in {s.lower() for s in standard["jurisdictions"]}]
        fallback["jurisdictions"] = standard["jurisdictions"] + extra


# ---------------------------------------------------------------------------
# Reading and editing the playbook
# ---------------------------------------------------------------------------

def _versions(session: Session) -> dict[str, int]:
    return dict(session.execute(
        select(PlaybookRule.clause_type, func.count()).group_by(PlaybookRule.clause_type)
    ).all())


def current_rules(session: Session) -> dict[str, PlaybookRule]:
    rules = session.scalars(select(PlaybookRule).where(PlaybookRule.superseded_at.is_(None)))
    return {r.clause_type: r for r in rules}


def to_rule(rule: PlaybookRule, version: int) -> RuleOut:
    return RuleOut(
        clause_type=rule.clause_type, label=LABELS[rule.clause_type],
        standard=rule.standard, fallback=rule.fallback,
        standard_text=_sentence(describe_rule(rule.clause_type, rule.standard)),
        fallback_text=_sentence(describe_rule(rule.clause_type, rule.fallback)),
        guidance=rule.guidance, note=rule.note, set_by=rule.set_by, set_at=rule.set_at, version=version,
    )


def get_rules(session: Session) -> list[RuleOut]:
    rules, versions = current_rules(session), _versions(session)
    return [to_rule(rules[t], versions.get(t, 1)) for t in CLAUSE_TYPES if t in rules]


def update_rule(session: Session, clause_type: str, change: RuleIn) -> RuleOut:
    """Save a new version of one rule. The old version is kept as history."""
    standard = check_rule(clause_type, change.standard)
    fallback = check_rule(clause_type, change.fallback)
    check_fallback(clause_type, standard, fallback)
    current = current_rules(session).get(clause_type)
    if current is not None:
        current.superseded_at = func.now()
        session.flush()
    rule = PlaybookRule(
        clause_type=clause_type, standard=standard, fallback=fallback,
        guidance=change.guidance.strip(), note=change.note.strip(), set_by=change.set_by,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return to_rule(rule, _versions(session).get(clause_type, 1))


def assess_clause(rules: dict[str, PlaybookRule], clause: Clause) -> Assessment | None:
    rule = rules.get(clause.clause_type)
    if rule is None:
        return None
    values = {t.term_key: t.value for t in clause.terms}
    unit = next((t.unit for t in clause.terms if t.term_key == "cap_amount"), None)
    result = assess(
        clause.clause_type, rule.standard, rule.fallback, values, unit, clause.presence,
        pending=clause.review_status == "pending",
    )
    if result is not None:
        result.guidance = rule.guidance
    return result


def _source(contract: Contract) -> SourceContract:
    return SourceContract(
        id=contract.id, contract_type=contract.contract_type,
        title=contract.title, effective_date=contract.effective_date,
    )


def check_vendors(session: Session, counterparty_id: int | None = None) -> PlaybookCheck:
    """Every vendor's agreed master-agreement terms, checked against the playbook."""
    rules = current_rules(session)
    vendors = session.scalars(
        select(Counterparty).order_by(Counterparty.name)
        .options(selectinload(Counterparty.contracts).selectinload(Contract.clauses).selectinload(Clause.terms))
    ).all()
    if counterparty_id is not None:
        vendors = [v for v in vendors if v.id == counterparty_id]

    positions = session.scalars(
        select(CounterpartyPosition)
        .where(CounterpartyPosition.superseded_at.is_(None))
        .options(selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.terms),
                 selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.contract))
    ).all()
    # The playbook is about the master agreement, so use the MSA-level baseline
    agreed = {
        (p.counterparty_id, p.clause_type): p.baseline_clause
        for p in positions if "MSA" in p.contract_type_scope
    }

    rows: list[PlaybookRow] = []
    outside = 0
    for vendor in vendors:
        cells: dict[str, Cell | None] = {}
        msas = [c for c in vendor.contracts if c.contract_type == "MSA"]
        for clause_type in CLAUSE_TYPES:
            clause = agreed.get((vendor.id, clause_type))
            if clause is None:
                # No baseline: the term clause (never a baseline) or a cap confirmed absent
                reviewed = [
                    cl for msa in msas for cl in msa.clauses
                    if cl.clause_type == clause_type and cl.review_status in ("approved", "corrected")
                ]
                clause = reviewed[-1] if reviewed else None
            if clause is None:
                cells[clause_type] = None
                continue
            result = assess_clause(rules, clause)
            if result is None:
                cells[clause_type] = None
                continue
            outside += result.tier == "outside"
            cells[clause_type] = Cell(**result.model_dump(), source=_source(clause.contract))
        rows.append(PlaybookRow(counterparty_id=vendor.id, counterparty_name=vendor.name, cells=cells))
    return PlaybookCheck(rules=get_rules(session), rows=rows, outside_count=outside)