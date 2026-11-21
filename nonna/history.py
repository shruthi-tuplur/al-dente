"""Decision history: everything anyone decided about a vendor, in one timeline.

Nonna already keeps every decision as a permanent record, in five places:
- contracts (who uploaded what, and when)
- review_decisions (approvals, intentional changes, corrections, rejections)
- playbook_exceptions (GC sign-offs, and withdrawals)
- precedence_decisions (which term controls when an SOW and the MSA disagree)
- relationship_notes (notes added, and archived)

This module only reads them and lines them up, newest first. Nothing here writes, and no AI
is involved: it's an audit trail, so every line comes straight from the database.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nonna import playbook
from nonna.lookups import NotFound, to_source
from nonna.models import (
    Clause, Contract, Counterparty, PlaybookException, PrecedenceDecision, RelationshipNote, ReviewDecision,
)
from nonna.notes import TOPIC_LABELS
from nonna.reviews import CLAUSE_LABELS, CORRECTABLE_TERMS
from nonna.schemas import SourceContract

__all__ = ["DecisionHistory", "HistoryEvent", "NotFound", "get_history"]

Group = Literal["contracts", "reviews", "gc", "precedence", "notes"]
Kind = Literal[
    "uploaded", "approved", "approved_change", "corrected", "rejected",
    "gc_exception", "gc_exception_withdrawn", "precedence_call", "note_added", "note_archived",
]

# Plain-English names for the values a correction can change
TERM_NAMES = {
    "cap_amount": "Cap amount", "cap_type": "Cap type", "is_mutual": "Mutual", "covers_ip_infringement": "Covers IP",
    "net_days": "Payment days", "payment_structure": "Billing", "jurisdiction": "Governing law",
    "initial_term_months": "Initial term", "end_date": "End date", "auto_renews": "Auto-renews",
    "renewal_term_months": "Renewal term", "notice_days": "Notice", "who_may_terminate": "Who can terminate",
    "survival_years": "Years after it ends", "perpetual": "Lasts forever",
    "trade_secrets_indefinite": "Trade secret carve-out",
    "general_liability_per_occurrence": "General liability per occurrence",
    "general_liability_aggregate": "General liability aggregate",
    "products_liability_limit": "Products liability", "professional_liability_limit": "Professional liability",
    "years_after_term": "Coverage after it ends",
}
PARTY_NAMES = {"either": "Either side", "aurelia": "Only us", "vendor": "Only the vendor"}


class Change(BaseModel):
    label: str
    before: str
    after: str


class HistoryEvent(BaseModel):
    id: str  # unique across kinds, like "review-12"
    kind: Kind
    group: Group
    at: datetime
    by: str
    title: str  # what happened, like "Approved liability cap"
    clause_type: str | None = None
    value: str | None = None  # the term in plain English, when it helps
    detail: str | None = None  # a second line, like who the GC was
    changes: list[Change] = []  # for corrections: what changed
    note: str | None = None  # why, in the person's own words
    source: SourceContract | None = None
    section: str | None = None


class DecisionHistory(BaseModel):
    counterparty_id: int
    counterparty_name: str
    events: list[HistoryEvent]  # newest first
    counts: dict[str, int]  # events per group, for the filter chips


def _label(clause_type: str) -> str:
    label = CLAUSE_LABELS.get(clause_type, clause_type.replace("_", " "))
    return label[:1].upper() + label[1:]


def _describe(clause: Clause) -> str | None:
    values = {t.term_key: t.value for t in clause.terms}
    unit = next((t.unit for t in clause.terms if t.term_key == "cap_amount"), None)
    return playbook.describe_value(clause.clause_type, values, unit) or None


def _show(clause_type: str, key: str, raw: Any) -> str:
    """One corrected value, in plain English."""
    if raw is None or raw == "":
        return "blank"
    kind = CORRECTABLE_TERMS.get(clause_type, {}).get(key)
    if kind == "yes_no" or isinstance(raw, bool):
        return "Yes" if raw in (True, "true", "True") else "No"
    if kind == "party":
        return PARTY_NAMES.get(str(raw), str(raw))
    if kind == "date":
        try:
            return date.fromisoformat(str(raw)).strftime("%b %-d, %Y")
        except ValueError:
            return str(raw)
    try:
        number = Decimal(str(raw))
    except InvalidOperation:
        return str(raw)
    if kind == "amount":
        return f"${number:,.0f}"
    units = {"days": "days", "notice": "days", "months": "months", "years": "years"}
    if kind in units:
        return f"{number:,.0f} {units[kind]}"
    return f"{number:,.0f}" if number == number.to_integral() else str(number)


def get_history(session: Session, counterparty_id: int) -> DecisionHistory:
    vendor = session.get(
        Counterparty, counterparty_id,
        options=[selectinload(Counterparty.contracts).selectinload(Contract.clauses).selectinload(Clause.terms)],
    )
    if vendor is None:
        raise NotFound(f"No counterparty with id {counterparty_id}.")

    clauses = {c.id: c for contract in vendor.contracts for c in contract.clauses}
    events: list[HistoryEvent] = []

    # Uploads
    for contract in vendor.contracts:
        events.append(HistoryEvent(
            id=f"contract-{contract.id}", kind="uploaded", group="contracts", at=contract.uploaded_at,
            by=contract.uploaded_by, title=f"Uploaded {contract.title}", source=to_source(contract),
        ))

    # Review decisions
    decisions = session.scalars(
        select(ReviewDecision).where(ReviewDecision.clause_id.in_(list(clauses))).order_by(ReviewDecision.created_at)
    ).all() if clauses else []
    corrected_later: dict[int, datetime] = {}  # clause id -> when it was last corrected
    for d in decisions:
        if d.action == "corrected":
            corrected_later[d.clause_id] = d.created_at
    titles = {
        "approved": "Approved", "approved_change": "Approved as an intentional change",
        "corrected": "Corrected", "rejected": "Rejected",
    }
    for d in decisions:
        clause = clauses[d.clause_id]
        changes = [
            Change(
                label=TERM_NAMES.get(str(key)) or str(key).replace("_", " ").capitalize(),
                before=_show(clause.clause_type, key, change.get("from")),
                after=_show(clause.clause_type, key, change.get("to")),
            )
            for key, change in (d.changes or {}).items()
        ]
        # The value as it stands now, unless a later correction changed it since this decision
        last_fix = corrected_later.get(clause.id)
        current = last_fix is None or last_fix <= d.created_at
        events.append(HistoryEvent(
            id=f"review-{d.id}", kind=d.action, group="reviews", at=d.created_at, by=d.reviewer,
            title=f"{titles.get(d.action, d.action)}: {_label(clause.clause_type)}",
            clause_type=clause.clause_type,
            value=_describe(clause) if current and d.action != "rejected" and clause.presence == "present" else None,
            detail=None if current or d.action == "rejected" else "The value was corrected after this.",
            changes=changes, note=d.note, source=to_source(clause.contract), section=clause.section_number,
        ))

    # GC exceptions
    exceptions = session.scalars(
        select(PlaybookException).where(PlaybookException.clause_id.in_(list(clauses)))
    ).all() if clauses else []
    for e in exceptions:
        clause = clauses[e.clause_id]
        events.append(HistoryEvent(
            id=f"exception-{e.id}", kind="gc_exception", group="gc", at=e.recorded_at, by=e.recorded_by,
            title=f"GC exception: {_label(clause.clause_type)}", clause_type=clause.clause_type,
            value=e.approved_value,
            detail=f"{e.approved_by} signed off on {e.approved_on.strftime('%b %-d, %Y')}",
            note=e.note, source=to_source(clause.contract), section=clause.section_number,
        ))
        if e.withdrawn_at is not None:
            events.append(HistoryEvent(
                id=f"exception-{e.id}-withdrawn", kind="gc_exception_withdrawn", group="gc", at=e.withdrawn_at,
                by=e.withdrawn_by or "", title=f"Withdrew GC exception: {_label(clause.clause_type)}",
                clause_type=clause.clause_type, value=e.approved_value, note=e.withdraw_note,
                source=to_source(clause.contract), section=clause.section_number,
            ))

    # Which term controls
    calls = session.scalars(
        select(PrecedenceDecision).where(PrecedenceDecision.sow_clause_id.in_(list(clauses)))
    ).all() if clauses else []
    for c in calls:
        sow = clauses[c.sow_clause_id]
        msa = clauses.get(c.msa_clause_id)
        winner = (
            f"The SOW's term controls ({c.sow_value})" if c.controls == "sow"
            else f"The MSA's term controls ({c.msa_value})"
        )
        events.append(HistoryEvent(
            id=f"precedence-{c.id}", kind="precedence_call", group="precedence", at=c.decided_at, by=c.decided_by,
            title=f"Which term controls: {_label(sow.clause_type)}", clause_type=sow.clause_type, value=winner,
            detail=f"{sow.contract.title}: {c.sow_value}. "
                   + f"{msa.contract.title if msa is not None else 'The MSA'}: {c.msa_value}.",
            note=c.note, source=to_source(sow.contract), section=sow.section_number,
        ))

    # Relationship notes
    notes = session.scalars(
        select(RelationshipNote).where(RelationshipNote.counterparty_id == vendor.id)
    ).all()
    for n in notes:
        topic = TOPIC_LABELS.get(n.topic, "Other")
        events.append(HistoryEvent(
            id=f"note-{n.id}", kind="note_added", group="notes", at=n.written_at, by=n.written_by,
            title=f"Added a note: {topic}", value=n.body,
        ))
        if n.archived_at is not None:
            events.append(HistoryEvent(
                id=f"note-{n.id}-archived", kind="note_archived", group="notes", at=n.archived_at,
                by=n.archived_by or "", title=f"Archived a note: {topic}", value=n.body,
            ))

    events.sort(key=lambda e: (e.at, e.id), reverse=True)
    counts: dict[str, int] = {}
    for e in events:
        counts[e.group] = counts.get(e.group, 0) + 1
    return DecisionHistory(
        counterparty_id=vendor.id, counterparty_name=vendor.name, events=events, counts=counts,
    )