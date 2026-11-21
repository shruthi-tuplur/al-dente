"""Fixing upload mistakes without resetting the database.

Two things an attorney can do after an upload:
- Fix its details: title, type, effective date, which vendor it belongs to, and the contract
  it falls under (for an SOW or change order) or amends (for an amendment).
- Delete an upload that was a mistake (the wrong file, or a duplicate under another name).

The rules keep Nonna's record trustworthy:
- Once any term from a contract has been reviewed (or used in a GC exception or a
  which-term-controls call), its type and vendor are part of the record and can't change,
  and it can't be deleted. The title, date, and link can still be fixed.
- A contract with SOWs or amendments under it can't move to another vendor or be deleted
  on its own. Move or delete those first.
- When the type, vendor, or link changes before anything was reviewed, Nonna re-reads the
  contract, because those decide how its terms are pulled out.
- Every fix needs a note and goes in an append-only log (contract_fixes), which shows up in
  the vendor's decision history. A deleted upload keeps its log entry.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from nonna.intake import STORAGE_DIR, ContractType
from nonna.lookups import NotFound, ReviewRejected
from nonna.models import (
    Clause, Contract, ContractFix, Counterparty, CounterpartyEntity, PlaybookException, PrecedenceDecision,
    ReviewDecision,
)

__all__ = ["DeleteIn", "FixIn", "FixOutcome", "NotFound", "ReviewRejected", "delete_contract", "fix_contract"]

log = logging.getLogger(__name__)

TYPE_NAMES = {"MSA": "MSA", "SOW": "SOW", "amendment": "Amendment", "change_order": "Change order", "NDA": "NDA"}


class FixIn(BaseModel):
    """The contract's details as they should be. Anything unchanged is left alone."""

    title: str = Field(min_length=1, max_length=300)
    contract_type: ContractType
    effective_date: date
    counterparty_id: int
    linked_contract_id: int | None = None  # the MSA an SOW falls under, or what an amendment amends
    note: str = Field(min_length=1, max_length=2000)  # why, in the attorney's words
    changed_by: str = Field(min_length=1)

    @field_validator("title", "note", "changed_by")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This can't be blank.")
        return value


class DeleteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    changed_by: str = Field(min_length=1)


class FixOutcome(BaseModel):
    contract_id: int | None  # None after a delete
    counterparty_id: int  # where the contract lives now (or lived, after a delete)
    message: str
    reread: bool = False  # Nonna pulled the terms out again


def _locked_reason(session: Session, contract: Contract) -> str | None:
    """Why the contract's type and vendor can't change anymore, or None if they still can."""
    clause_ids = [c.id for c in contract.clauses]
    if not clause_ids:
        return None
    if session.scalar(select(ReviewDecision.id).where(ReviewDecision.clause_id.in_(clause_ids)).limit(1)):
        return "Terms from this contract were already reviewed"
    if session.scalar(select(PlaybookException.id).where(PlaybookException.clause_id.in_(clause_ids)).limit(1)):
        return "A GC exception was recorded on this contract"
    if session.scalar(select(PrecedenceDecision.id).where(or_(
        PrecedenceDecision.sow_clause_id.in_(clause_ids), PrecedenceDecision.msa_clause_id.in_(clause_ids),
    )).limit(1)):
        return "A which-term-controls call uses this contract"
    return None


def _children(session: Session, contract: Contract) -> list[Contract]:
    return list(session.scalars(select(Contract).where(or_(
        Contract.parent_contract_id == contract.id, Contract.amends_contract_id == contract.id,
    )).order_by(Contract.effective_date)))


def _entity_for(session: Session, vendor: Counterparty, legal_name: str) -> CounterpartyEntity:
    """The signing entity under the new vendor, made if it isn't there yet."""
    entity = session.scalar(select(CounterpartyEntity).where(
        CounterpartyEntity.counterparty_id == vendor.id,
        func.lower(CounterpartyEntity.legal_name) == legal_name.lower(),
    ))
    if entity is None:
        entity = CounterpartyEntity(counterparty_id=vendor.id, legal_name=legal_name)
        session.add(entity)
        session.flush()
    return entity


def _check_link(session: Session, contract: Contract, fix: FixIn) -> Contract | None:
    if fix.linked_contract_id is None:
        return None
    if fix.contract_type not in ("SOW", "change_order", "amendment"):
        raise ReviewRejected(f"An {TYPE_NAMES[fix.contract_type]} doesn't fall under or amend another contract.")
    if fix.linked_contract_id == contract.id:
        raise ReviewRejected("A contract can't fall under or amend itself.")
    linked = session.get(Contract, fix.linked_contract_id)
    if linked is None or linked.counterparty_id != fix.counterparty_id:
        raise ReviewRejected("That contract doesn't belong to the same vendor.")
    if fix.contract_type == "SOW" and linked.contract_type != "MSA":
        raise ReviewRejected("An SOW falls under an MSA.")
    if fix.contract_type == "change_order" and linked.contract_type not in ("MSA", "SOW"):
        raise ReviewRejected("A change order falls under an MSA or an SOW.")
    return linked


def _commit(session: Session) -> None:
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error


def _reread(session: Session, contract_id: int) -> str | None:
    """Pull the terms out again. Returns a problem to show, or None if it worked."""
    from nonna import extraction  # imported here: extraction is heavy and only needed sometimes

    try:
        extraction.extract_contract(session, contract_id)
        return None
    except Exception as error:  # noqa: BLE001 (the fix is already saved, so never fail it here)
        session.rollback()
        log.warning("Re-reading contract %s failed: %s", contract_id, error)
        return f"Nonna couldn't re-read it ({error}). Upload it again or try later."


def fix_contract(session: Session, contract_id: int, fix: FixIn) -> FixOutcome:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise NotFound(f"No contract with id {contract_id}.")
    vendor = session.get(Counterparty, fix.counterparty_id)
    if vendor is None:
        raise NotFound("That vendor doesn't exist in Nonna.")
    old_vendor = contract.counterparty
    linked = _check_link(session, contract, fix)
    old_linked_id = contract.parent_contract_id or contract.amends_contract_id

    changes: dict[str, dict[str, Any]] = {}

    def record(label: str, before: Any, after: Any) -> None:
        if before != after:
            changes[label] = {"from": before, "to": after}

    record("Title", contract.title, fix.title)
    record("Type", TYPE_NAMES[contract.contract_type], TYPE_NAMES[fix.contract_type])
    record("Effective date", contract.effective_date.isoformat(), fix.effective_date.isoformat())
    record("Vendor", old_vendor.name, vendor.name)
    old_link_title = session.get(Contract, old_linked_id).title if old_linked_id else "None"
    record("Falls under or amends", old_link_title, linked.title if linked else "None")
    if not changes:
        raise ReviewRejected("Nothing changed. Edit a detail first.")

    structural = {"Type", "Vendor", "Falls under or amends"} & changes.keys()
    reason = _locked_reason(session, contract)
    if reason and {"Type", "Vendor"} & changes.keys():
        raise ReviewRejected(
            f"{reason}, so its type and vendor are part of the record. You can still fix the title, "
            "date, and what it falls under."
        )
    moving = vendor.id != old_vendor.id
    if moving:
        children = _children(session, contract)
        if children:
            names = ", ".join(c.title for c in children)
            raise ReviewRejected(f"These contracts sit under it: {names}. Move them first, then this one.")

    # Apply the fix
    contract.title = fix.title
    contract.contract_type = fix.contract_type
    contract.effective_date = fix.effective_date
    contract.parent_contract_id = linked.id if linked and fix.contract_type in ("SOW", "change_order") else None
    contract.amends_contract_id = linked.id if linked and fix.contract_type == "amendment" else None
    if moving:
        contract.entity_id = _entity_for(session, vendor, contract.entity.legal_name).id
        contract.counterparty_id = vendor.id

    # Log it under the vendor it's in now, and under the one it left
    session.add(ContractFix(
        counterparty_id=vendor.id, contract_id=contract.id, contract_title=fix.title,
        action="moved_in" if moving else "edited", changes=changes, note=fix.note, changed_by=fix.changed_by,
    ))
    if moving:
        session.add(ContractFix(
            counterparty_id=old_vendor.id, contract_id=contract.id, contract_title=fix.title,
            action="moved_out", changes=changes, note=fix.note, changed_by=fix.changed_by,
        ))

    # Nothing reviewed yet, and the type, vendor, or link changed: throw out the old pending
    # terms, so Nonna can pull them out again the right way
    reread = bool(structural) and reason is None and bool(contract.clauses)
    if reread:
        # Straight SQL, so Postgres removes their values too (ON DELETE CASCADE)
        session.execute(
            delete(Clause).where(Clause.contract_id == contract.id).execution_options(synchronize_session=False)
        )
        session.expire(contract, ["clauses"])
    _commit(session)

    problem = _reread(session, contract.id) if reread else None
    if "Effective date" in changes:
        _sync_calendar(session)

    parts = [f"Saved. {len(changes)} {'detail' if len(changes) == 1 else 'details'} fixed."]
    if moving:
        parts.append(f"It's under {vendor.name} now.")
    if reread and problem is None:
        parts.append("Nonna re-read it, so check its terms in Review.")
    if problem:
        parts.append(problem)
    return FixOutcome(contract_id=contract.id, counterparty_id=vendor.id, message=" ".join(parts),
                      reread=reread and problem is None)


def delete_contract(session: Session, contract_id: int, change: DeleteIn) -> FixOutcome:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise NotFound(f"No contract with id {contract_id}.")
    note = change.note.strip()
    if not note:
        raise ReviewRejected("Say why this upload is being deleted.")
    reason = _locked_reason(session, contract)
    if reason:
        raise ReviewRejected(f"{reason}, so it's part of the record and can't be deleted. Fix its details instead.")
    children = _children(session, contract)
    if children:
        names = ", ".join(c.title for c in children)
        raise ReviewRejected(f"These contracts sit under it: {names}. Delete or move them first.")

    vendor_id, title, file_path = contract.counterparty_id, contract.title, contract.file_path
    session.add(ContractFix(
        counterparty_id=vendor_id, contract_id=contract.id, contract_title=title, action="deleted",
        changes=None, note=note, changed_by=change.changed_by.strip(),
    ))
    # Straight SQL, so Postgres removes its pending terms and filed sections too (ON DELETE CASCADE)
    session.execute(delete(Contract).where(Contract.id == contract.id).execution_options(synchronize_session=False))
    _commit(session)

    # The uploaded file too, so the same file can be uploaded again. Only inside Nonna's storage.
    stored = Path(file_path)
    try:
        if stored.resolve().parent == STORAGE_DIR.resolve() and stored.exists():
            stored.unlink()
    except OSError as error:
        log.warning("Couldn't remove %s: %s", stored, error)

    _sync_calendar(session)
    return FixOutcome(contract_id=None, counterparty_id=vendor_id, message=f"Deleted {title}. The log keeps a record of it.")


def _sync_calendar(session: Session) -> None:
    try:
        from nonna import google_calendar

        google_calendar.sync_quietly(session)
    except Exception as error:  # noqa: BLE001 (a calendar problem never blocks a fix)
        log.warning("Calendar sync after a fix failed: %s", error)