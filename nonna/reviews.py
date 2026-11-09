"""Reviewing extracted clauses, and keeping each counterparty's agreed baseline up to date.

Rules:
- Approving a counterparty's first clause of a type sets the baseline.
- Approving a clause that matches the baseline keeps it.
- Approving a clause that differs from the baseline is refused, unless the attorney
  approves it as an intentional change with a note. That moves the baseline and
  keeps the old one as history.
- Rejecting never touches the baseline.
- Correcting fixes a value Nonna extracted wrong. The attorney always gets the last
  word, but the original value is kept in the decision log, and a correction still
  goes through the same baseline check as an approval.

Everything happens in one transaction, so a decision and its baseline update
are saved together or not at all.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from nonna.lookups import SCOPE_FOR_TYPE, STATUS_FOR_ACTION, NotFound, ReviewRejected, to_decision
from nonna.models import Clause, ClauseTerm, CounterpartyPosition, ReviewDecision
from nonna.schemas import DecisionOut, ReviewIn

__all__ = ["BaselineConflict", "NotFound", "ReviewOutcome", "ReviewRejected", "review_clause"]

# Which contract types share a baseline (an NDA never sets the MSA's cap, for example)

CLAUSE_LABELS = {
    "liability_cap": "liability cap",
    "indemnification": "indemnification terms",
    "payment_terms": "payment terms",
    "governing_law": "governing law",
}

# The values an attorney can correct for each clause type, and what kind of value each is
CORRECTABLE_TERMS: dict[str, dict[str, str]] = {
    "liability_cap": {"cap_amount": "amount"},
    "payment_terms": {"net_days": "days", "payment_structure": "structure"},
    "governing_law": {"jurisdiction": "text"},
    "indemnification": {"is_mutual": "yes_no", "covers_ip_infringement": "yes_no"},
}
DEFAULT_UNITS = {"cap_amount": "USD", "net_days": "days"}
PAYMENT_STRUCTURES = {"invoice", "milestone"}

Values = dict[str, Any]


class BaselineConflict(Exception):
    """The clause differs from the agreed baseline and needs an intentional-change approval."""


class ReviewOutcome(BaseModel):
    decision: DecisionOut
    baseline: Literal["created", "moved", "unchanged", "none"]
    message: str


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def _values(clause: Clause) -> Values:
    return {t.term_key: t.value for t in clause.terms}


def _units(clause: Clause) -> dict[str, str | None]:
    return {t.term_key: t.unit for t in clause.terms}


def _describe(values: Values, units: dict[str, str | None]) -> str:
    """Plain description of a clause's values, like 'cap amount 2,500,000 USD'."""
    parts = []
    for key, value in values.items():
        if isinstance(value, Decimal):
            value = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,}"
        elif isinstance(value, bool):
            value = "yes" if value else "no"
        unit = f" {units.get(key)}" if units.get(key) else ""
        parts.append(f"{key.replace('_', ' ')} {value}{unit}")
    return ", ".join(parts) or "no values"


def _as_json(value: Any) -> Any:
    """Store a value in the decision log without losing precision."""
    if isinstance(value, Decimal):
        return str(value.normalize()) if value != value.to_integral_value() else str(int(value))
    if isinstance(value, date):
        return value.isoformat()
    return value


def _parse_corrections(clause_type: str, corrections: dict[str, Any]) -> Values:
    """Check and convert the values an attorney typed in. Raises ReviewRejected with a plain reason."""
    allowed = CORRECTABLE_TERMS.get(clause_type, {})
    parsed: Values = {}
    for key, raw in corrections.items():
        kind = allowed.get(key)
        if kind is None:
            raise ReviewRejected(f"{key.replace('_', ' ').capitalize()} can't be corrected on this clause.")

        if kind == "amount":
            try:
                amount = Decimal(str(raw).replace(",", "").replace("$", "").strip())
            except InvalidOperation:
                raise ReviewRejected("The cap amount needs to be a number, like 3000000.") from None
            if amount <= 0:
                raise ReviewRejected("The cap amount needs to be more than zero.")
            parsed[key] = amount
        elif kind == "days":
            try:
                days = int(str(raw).strip())
            except ValueError:
                raise ReviewRejected("Payment days need to be a whole number, like 45.") from None
            if not 0 <= days <= 365:
                raise ReviewRejected("Payment days need to be between 0 and 365.")
            parsed[key] = Decimal(days)
        elif kind == "structure":
            if raw not in PAYMENT_STRUCTURES:
                raise ReviewRejected("Payment structure must be invoice or milestone.")
            parsed[key] = raw
        elif kind == "text":
            text = str(raw).strip()
            if not text or len(text) > 100:
                raise ReviewRejected("The jurisdiction needs to be filled in (100 characters at most).")
            parsed[key] = text
        elif kind == "yes_no":
            if not isinstance(raw, bool):
                raise ReviewRejected(f"{key.replace('_', ' ').capitalize()} must be yes or no.")
            parsed[key] = raw
    return parsed


def _apply_corrections(session: Session, clause: Clause, new_values: Values) -> None:
    """Replace the clause's stored values. The originals are kept in the decision log."""
    units = _units(clause)
    for term in [t for t in clause.terms if t.term_key in new_values]:
        clause.terms.remove(term)
        session.delete(term)
    session.flush()

    for key, value in new_values.items():
        term = ClauseTerm(term_key=key, unit=units.get(key) or DEFAULT_UNITS.get(key))
        if isinstance(value, bool):
            term.value_bool = value
        elif isinstance(value, Decimal):
            term.value_numeric = value
        else:
            term.value_text = str(value)
        clause.terms.append(term)


# ---------------------------------------------------------------------------
# Reviewing
# ---------------------------------------------------------------------------

def review_clause(session: Session, clause_id: int, review: ReviewIn) -> ReviewOutcome:
    clause = session.get(Clause, clause_id)
    if clause is None:
        raise NotFound(f"No clause with id {clause_id}.")

    contract = clause.contract
    counterparty_name = contract.counterparty.name
    label = CLAUSE_LABELS.get(clause.clause_type, clause.clause_type)
    correcting = review.action == "corrected"
    already_reviewed = clause.review_status in ("approved", "corrected")

    # Work out the values this decision would leave the clause with
    changes: dict[str, dict[str, Any]] | None = None
    new_values: Values = {}
    proposed = _values(clause)
    if correcting:
        if clause.presence != "present":
            raise ReviewRejected(
                "Nonna didn't find this clause written out in the contract, so there's no value to fix."
            )
        new_values = _parse_corrections(clause.clause_type, review.corrections or {})
        old = _values(clause)
        changes = {
            key: {"from": _as_json(old.get(key)), "to": _as_json(value)}
            for key, value in new_values.items()
            if old.get(key) != value
        }
        if not changes:
            raise ReviewRejected("Those are the values Nonna already has. Approve it instead.")
        proposed = {**old, **new_values}

    # Approving (or correcting something nobody approved yet) can set the baseline.
    # Fixing a clause that was already approved just corrects the record.
    approving = review.action in ("approved", "approved_change") or (correcting and not already_reviewed)
    sets_baseline = approving and bool(proposed)

    current = None
    if sets_baseline:
        current = session.scalar(
            select(CounterpartyPosition).where(
                CounterpartyPosition.counterparty_id == contract.counterparty_id,
                CounterpartyPosition.clause_type == clause.clause_type,
                CounterpartyPosition.contract_type_scope == SCOPE_FOR_TYPE[contract.contract_type],
                CounterpartyPosition.superseded_at.is_(None),
            )
        )

    differs = (
        current is not None
        and current.baseline_clause_id != clause.id
        and _values(current.baseline_clause) != proposed
    )

    # Fixing a clause that IS the agreed baseline changes the agreed term itself,
    # so it needs the same deliberate confirmation as approving a change.
    is_current_baseline = bool(
        session.scalar(
            select(CounterpartyPosition.id).where(
                CounterpartyPosition.baseline_clause_id == clause.id,
                CounterpartyPosition.superseded_at.is_(None),
            )
        )
    )
    if correcting and already_reviewed and is_current_baseline and not review.as_change:
        units = {**DEFAULT_UNITS, **_units(clause)}
        raise BaselineConflict(
            f"This is your agreed {label} with {counterparty_name} right now (from {contract.title}). "
            f"Agreed: {_describe(_values(clause), units)}. Your correction: {_describe(proposed, units)}. "
            "Save it as a change only if the contract really says this."
        )
    needs_change_approval = review.action == "approved" or (correcting and not review.as_change)
    if differs and needs_change_approval:
        baseline = current.baseline_clause
        units = {**DEFAULT_UNITS, **_units(baseline), **_units(clause)}
        next_step = (
            "Save it as an intentional change, or double-check the value."
            if correcting
            else "Approve it as an intentional change with a note, or reject it."
        )
        raise BaselineConflict(
            f"This doesn't match your agreed {label} with {counterparty_name}. "
            f"Agreed: {_describe(_values(baseline), units)} (from {baseline.contract.title}). "
            f"{'Your correction' if correcting else 'This contract'}: {_describe(proposed, units)}. "
            f"{next_step}"
        )

    # Record the decision, fix any values, and update the clause's status
    if correcting:
        _apply_corrections(session, clause, new_values)
    decision = ReviewDecision(
        clause_id=clause.id,
        action=review.action,
        note=review.note,
        reviewer=review.reviewer,
        changes=changes,
    )
    session.add(decision)
    clause.review_status = STATUS_FOR_ACTION[review.action]
    session.flush()

    # Keep the counterparty's baseline up to date
    baseline_result: Literal["created", "moved", "unchanged", "none"] = "none"
    if sets_baseline:
        if current is None:
            baseline_result = "created"
        elif not differs:
            baseline_result = "unchanged"
        else:
            current.superseded_at = func.now()
            session.flush()
            baseline_result = "moved"

        if baseline_result in ("created", "moved"):
            session.add(
                CounterpartyPosition(
                    counterparty_id=contract.counterparty_id,
                    clause_type=clause.clause_type,
                    contract_type_scope=SCOPE_FOR_TYPE[contract.contract_type],
                    baseline_clause_id=clause.id,
                    set_by=review.reviewer,
                    note=review.note or f"Set from {contract.title}.",
                )
            )

    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error

    session.refresh(decision)
    return ReviewOutcome(
        decision=to_decision(decision),
        baseline=baseline_result,
        message=_message(review.action, baseline_result, label, counterparty_name, is_current_baseline),
    )


def _message(action: str, baseline: str, label: str, counterparty: str, is_current_baseline: bool) -> str:
    if action == "corrected":
        if baseline == "none":
            if is_current_baseline:
                return (
                    f"Corrected. Your agreed {label} with {counterparty} now uses the fixed value, "
                    "and the original stays in the history."
                )
            return "Corrected. The fixed value is saved, and the original stays in the history."
        return {
            "created": f"Corrected and approved. This is now your agreed {label} with {counterparty}.",
            "unchanged": f"Corrected and approved. It matches your agreed {label} with {counterparty}.",
            "moved": (
                f"Corrected and approved as a change. Your agreed {label} with {counterparty} is "
                "updated, and the old one stays in the history."
            ),
        }[baseline]

    return {
        "created": f"Approved. This is now your agreed {label} with {counterparty}.",
        "unchanged": f"Approved. It matches your agreed {label} with {counterparty}.",
        "moved": (
            f"Approved as a change. Your agreed {label} with {counterparty} is updated, "
            "and the old one stays in the history."
        ),
        "none": "Approved." if action != "rejected" else "Rejected. It won't count as an agreed term.",
    }[baseline]