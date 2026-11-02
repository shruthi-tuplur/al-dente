"""Shapes of the data Nonna's API sends and receives.

Numbers from the database (like cap amounts) are sent as strings, for example
"2000000", so exact values are never rounded by floating point math.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClauseType(str, Enum):
    liability_cap = "liability_cap"
    indemnification = "indemnification"
    payment_terms = "payment_terms"
    governing_law = "governing_law"


ReviewAction = Literal["approved", "rejected", "corrected", "approved_change"]


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

class TermOut(BaseModel):
    term_key: str
    value: Decimal | str | bool | date | None
    unit: str | None


class DecisionOut(BaseModel):
    id: int
    clause_id: int
    action: str
    note: str | None
    reviewer: str
    created_at: datetime


class ClauseOut(BaseModel):
    id: int
    clause_type: str
    section_number: str | None
    heading: str | None
    full_text: str | None
    presence: str
    extraction_method: str
    confidence: Decimal | None
    review_status: str
    terms: list[TermOut]


class SourceContract(BaseModel):
    """The contract a clause or position came from."""

    id: int
    contract_type: str
    title: str
    effective_date: date


# ---------------------------------------------------------------------------
# Counterparties
# ---------------------------------------------------------------------------

class CounterpartySummary(BaseModel):
    id: int
    name: str
    contract_count: int


class EntityOut(BaseModel):
    id: int
    legal_name: str
    jurisdiction: str | None


class ContractOut(BaseModel):
    id: int
    contract_type: str
    title: str
    effective_date: date
    expiration_date: date | None
    status: str
    signed_by_entity: str
    parent_contract_id: int | None
    amends_contract_id: int | None


class CounterpartyDetail(BaseModel):
    id: int
    name: str
    entities: list[EntityOut]
    contracts: list[ContractOut]


# ---------------------------------------------------------------------------
# Positions, history, review queue
# ---------------------------------------------------------------------------

class PositionOut(BaseModel):
    id: int
    clause_type: str
    applies_to: list[str]
    is_current: bool
    set_by: str
    set_at: datetime
    note: str | None
    source: SourceContract
    clause: ClauseOut


class HistoryEntry(BaseModel):
    source: SourceContract
    clause: ClauseOut
    decisions: list[DecisionOut]


class ReviewQueueItem(BaseModel):
    counterparty_id: int
    counterparty_name: str
    source: SourceContract
    clause: ClauseOut


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class ReviewIn(BaseModel):
    """An attorney's decision about an extracted clause."""

    action: ReviewAction
    reviewer: str = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def note_required_for_intentional_changes(self) -> "ReviewIn":
        if self.action == "approved_change" and not (self.note and self.note.strip()):
            raise ValueError("A note is required when approving an intentional change.")
        return self
