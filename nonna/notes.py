"""Relationship notes: what the team knows about a vendor that isn't in any contract.

"They always fight us on IP." "Business owner is in CMC." "Renegotiating in Q2."

These are the team's own notes, not contract terms, so Nonna never treats them as agreed.
Notes are never edited or deleted (Postgres blocks it). To retire one, archive it, and
add a new one if something changed. That way the history of what the team knew survives.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from nonna.lookups import NotFound, ReviewRejected
from nonna.models import Counterparty, RelationshipNote

__all__ = ["ArchiveIn", "NoteIn", "NoteOut", "NotFound", "NotesOut", "ReviewRejected", "add_note", "archive_note", "get_notes"]

Topic = Literal["negotiation", "people", "timing", "other"]
TOPIC_LABELS: dict[str, str] = {
    "negotiation": "How they negotiate",
    "people": "People",
    "timing": "Timing and plans",
    "other": "Other",
}
MAX_LENGTH = 1000


class NoteIn(BaseModel):
    topic: Topic = "other"
    body: str = Field(min_length=1, max_length=MAX_LENGTH)
    written_by: str = Field(min_length=1)

    @field_validator("body", "written_by")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Write something first.")
        return value


class ArchiveIn(BaseModel):
    archived_by: str = Field(min_length=1)


class NoteOut(BaseModel):
    id: int
    topic: Topic
    topic_label: str
    body: str
    written_by: str
    written_at: datetime
    archived_at: datetime | None
    archived_by: str | None


class NotesOut(BaseModel):
    counterparty_id: int
    counterparty_name: str
    notes: list[NoteOut]  # active notes, newest first
    archived: list[NoteOut]  # archived notes, newest first


def to_note(note: RelationshipNote) -> NoteOut:
    return NoteOut(
        id=note.id,
        topic=note.topic,
        topic_label=TOPIC_LABELS.get(note.topic, "Other"),
        body=note.body,
        written_by=note.written_by,
        written_at=note.written_at,
        archived_at=note.archived_at,
        archived_by=note.archived_by,
    )


def get_notes(session: Session, counterparty_id: int, include_archived: bool = True) -> NotesOut:
    vendor = session.get(Counterparty, counterparty_id)
    if vendor is None:
        raise NotFound(f"No counterparty with id {counterparty_id}.")
    rows = session.scalars(
        select(RelationshipNote)
        .where(RelationshipNote.counterparty_id == counterparty_id)
        .order_by(RelationshipNote.written_at.desc(), RelationshipNote.id.desc())
    ).all()
    return NotesOut(
        counterparty_id=vendor.id,
        counterparty_name=vendor.name,
        notes=[to_note(n) for n in rows if n.archived_at is None],
        archived=[to_note(n) for n in rows if n.archived_at is not None] if include_archived else [],
    )


def _commit(session: Session) -> None:
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error


def add_note(session: Session, counterparty_id: int, note: NoteIn) -> NoteOut:
    if session.get(Counterparty, counterparty_id) is None:
        raise NotFound(f"No counterparty with id {counterparty_id}.")
    row = RelationshipNote(
        counterparty_id=counterparty_id, topic=note.topic, body=note.body, written_by=note.written_by
    )
    session.add(row)
    _commit(session)
    session.refresh(row)
    return to_note(row)


def archive_note(session: Session, note_id: int, change: ArchiveIn) -> NoteOut:
    row = session.get(RelationshipNote, note_id)
    if row is None:
        raise NotFound(f"No note with id {note_id}.")
    if row.archived_at is not None:
        raise ReviewRejected("This note was already archived.")
    row.archived_at = func.now()
    row.archived_by = change.archived_by.strip()
    _commit(session)
    session.refresh(row)
    return to_note(row)