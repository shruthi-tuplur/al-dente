"""GC exceptions: the GC's sign-off on a term that's off Aurelia's playbook.

Two ways an exception gets recorded:
- In Review: approving a new term that's off the playbook needs the GC's sign-off first.
  The sign-off is saved in the same transaction as the approval, or neither is saved.
- On the Playbook page: a signed contract can't be approved again, but the GC may decide an
  off-playbook term is fine (a small vendor, a one-off deal). Recording that stops Nonna
  from flagging it every time.

An exception covers the exact term the GC approved (like "$500,000"). If the term is later
corrected to something else, Nonna flags it again.

Exceptions are a permanent record. Postgres blocks edits and deletes; the only change allowed
is withdrawing one, once, with who and why.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from nonna import playbook
from nonna.lookups import NotFound, ReviewRejected
from nonna.models import Clause, PlaybookException
from nonna.schemas import GcSignOffIn, PlaybookAssessment, PlaybookExceptionOut

__all__ = [
    "ExceptionIn", "NotFound", "ReviewRejected", "SignOffNeeded", "WithdrawIn",
    "needs_sign_off", "record_exception", "save_sign_off", "withdraw_exception",
]


class SignOffNeeded(Exception):
    """Approving this term needs the GC's sign-off first."""


class ExceptionIn(GcSignOffIn):
    recorded_by: str = Field(min_length=1)  # the attorney entering it in Nonna


class WithdrawIn(BaseModel):
    withdrawn_by: str = Field(min_length=1)
    note: str = Field(min_length=1, max_length=2000)  # why it no longer applies


def needs_sign_off(session: Session, clause: Clause, values: dict[str, Any]) -> PlaybookAssessment | None:
    """The playbook result when approving these values needs the GC, otherwise None.

    values are what the clause will say once this decision is saved, so a correction
    is checked against what the attorney typed, not what Nonna first extracted.
    """
    rule = playbook.current_rules(session).get(clause.clause_type)
    if rule is None:
        return None
    unit = next((t.unit for t in clause.terms if t.term_key == "cap_amount"), None)
    result = playbook.assess(
        clause.clause_type, rule.standard, rule.fallback, values, unit, clause.presence, pending=True
    )
    if result is None or result.tier != "outside":
        return None
    result.guidance = rule.guidance
    return result


def save_sign_off(
    session: Session,
    clause: Clause,
    assessment: PlaybookAssessment,
    sign_off: GcSignOffIn,
    recorded_by: str,
    review_decision_id: int | None = None,
) -> PlaybookException:
    """Add the exception to the session. The caller commits, so it's saved with the approval."""
    exception = PlaybookException(
        clause_id=clause.id,
        approved_value=assessment.value,
        approved_by=sign_off.approved_by,
        approved_on=sign_off.approved_on,
        note=sign_off.note,
        recorded_by=recorded_by,
        review_decision_id=review_decision_id,
    )
    session.add(exception)
    return exception


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if "playbook_exceptions_active" in str(error.orig):
            raise ReviewRejected("This term already has a GC exception.") from error
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error
    except DBAPIError as error:
        session.rollback()
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error


def record_exception(session: Session, clause_id: int, change: ExceptionIn) -> PlaybookExceptionOut:
    """Record the GC's sign-off on an off-playbook term in a contract that's already reviewed."""
    clause = session.get(Clause, clause_id)
    if clause is None:
        raise NotFound(f"No clause with id {clause_id}.")
    if clause.review_status == "pending":
        raise ReviewRejected(
            "This term is still waiting for review. Approve it in Review and record the GC's sign-off there."
        )
    if clause.review_status == "rejected":
        raise ReviewRejected("This term was rejected, so it doesn't count as agreed and needs no exception.")

    rules = playbook.current_rules(session)
    existing = playbook.active_exceptions(session, [clause.id]).get(clause.id)
    result = playbook.assess_clause(rules, clause, existing)
    if result is None or result.tier != "outside":
        raise ReviewRejected("This term isn't off the playbook, so it doesn't need a GC exception.")
    if result.exception is not None:
        raise ReviewRejected("This term already has a GC exception.")
    if existing is not None:
        # An old sign-off for a value the term no longer says. Close it out (it stays in the
        # history) before recording the new one, so there's only ever one active exception.
        existing.withdrawn_at = func.now()
        existing.withdrawn_by = change.recorded_by.strip()
        existing.withdraw_note = f"Replaced by a new sign-off. The term now says {result.value}."
        session.flush()

    exception = save_sign_off(session, clause, result, change, change.recorded_by.strip())
    _commit(session)
    session.refresh(exception)
    return playbook.to_exception(exception)


def withdraw_exception(session: Session, exception_id: int, change: WithdrawIn) -> None:
    """Withdraw a GC exception. It stays in the history, and the term is flagged again."""
    exception = session.get(PlaybookException, exception_id)
    if exception is None:
        raise NotFound(f"No GC exception with id {exception_id}.")
    if exception.withdrawn_at is not None:
        raise ReviewRejected("This exception was already withdrawn.")
    note = change.note.strip()
    if not note:
        raise ReviewRejected("Say why the exception no longer applies.")

    exception.withdrawn_at = func.now()
    exception.withdrawn_by = change.withdrawn_by.strip()
    exception.withdraw_note = note
    _commit(session)