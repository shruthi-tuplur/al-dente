"""Reviewing extracted clauses, and keeping each counterparty's agreed baseline up to date.

Rules:
- Approving a counterparty's first clause of a type sets the baseline.
- Approving a clause that matches the baseline keeps it.
- Approving a clause that differs from the baseline is refused, unless the attorney
  approves it as an intentional change with a note. That moves the baseline and
  keeps the old one as history.
- Rejecting never touches the baseline.

Everything happens in one transaction, so a decision and its baseline update
are saved together or not at all.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from nonna.lookups import STATUS_FOR_ACTION, NotFound, ReviewRejected, to_decision
from nonna.models import Clause, CounterpartyPosition, ReviewDecision
from nonna.schemas import DecisionOut, ReviewIn

__all__ = ["BaselineConflict", "NotFound", "ReviewOutcome", "ReviewRejected", "review_clause"]

# Which contract types share a baseline (an NDA never sets the MSA's cap, for example)
SCOPE_FOR_TYPE = {
    "MSA": ["MSA", "amendment"],
    "amendment": ["MSA", "amendment"],
    "SOW": ["SOW"],
    "change_order": ["SOW"],
    "NDA": ["NDA"],
}

CLAUSE_LABELS = {
    "liability_cap": "liability cap",
    "indemnification": "indemnification terms",
    "payment_terms": "payment terms",
    "governing_law": "governing law",
}


class BaselineConflict(Exception):
    """The clause differs from the agreed baseline and needs an intentional-change approval."""


class ReviewOutcome(BaseModel):
    decision: DecisionOut
    baseline: Literal["created", "moved", "unchanged", "none"]
    message: str


def _values(clause: Clause) -> dict[str, object]:
    return {t.term_key: t.value for t in clause.terms}


def _describe(clause: Clause) -> str:
    """Plain description of a clause's values, like 'cap amount 2,500,000 USD'."""
    parts = []
    for term in clause.terms:
        value = term.value
        if isinstance(value, Decimal):
            value = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,}"
        elif isinstance(value, bool):
            value = "yes" if value else "no"
        unit = f" {term.unit}" if term.unit else ""
        parts.append(f"{term.term_key.replace('_', ' ')} {value}{unit}")
    return ", ".join(parts) or "no values"


def review_clause(session: Session, clause_id: int, review: ReviewIn) -> ReviewOutcome:
    clause = session.get(Clause, clause_id)
    if clause is None:
        raise NotFound(f"No clause with id {clause_id}.")

    contract = clause.contract
    counterparty_name = contract.counterparty.name
    label = CLAUSE_LABELS.get(clause.clause_type, clause.clause_type)
    approving = review.action in ("approved", "approved_change")
    sets_baseline = approving and bool(clause.terms)

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
        and _values(current.baseline_clause) != _values(clause)
    )
    if differs and review.action == "approved":
        raise BaselineConflict(
            f"This doesn't match your agreed {label} with {counterparty_name}. "
            f"Agreed: {_describe(current.baseline_clause)} (from {current.baseline_clause.contract.title}). "
            f"This contract: {_describe(clause)}. "
            "Approve it as an intentional change with a note, or reject it."
        )

    # Record the decision and update the clause's status
    decision = ReviewDecision(
        clause_id=clause.id, action=review.action, note=review.note, reviewer=review.reviewer
    )
    session.add(decision)
    clause.review_status = STATUS_FOR_ACTION[review.action]
    session.flush()

    # Keep the counterparty's baseline up to date
    baseline: Literal["created", "moved", "unchanged", "none"] = "none"
    if sets_baseline:
        if current is None:
            baseline = "created"
        elif not differs:
            baseline = "unchanged"
        else:
            current.superseded_at = func.now()
            session.flush()
            baseline = "moved"

        if baseline in ("created", "moved"):
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
    messages = {
        "created": f"Approved. This is now your agreed {label} with {counterparty_name}.",
        "unchanged": f"Approved. It matches your agreed {label} with {counterparty_name}.",
        "moved": (
            f"Approved as a change. Your agreed {label} with {counterparty_name} is updated, "
            "and the old one stays in the history."
        ),
        "none": "Approved." if approving else "Rejected. It won't count as an agreed term.",
    }
    return ReviewOutcome(decision=to_decision(decision), baseline=baseline, message=messages[baseline])