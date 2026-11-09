"""Shapes of the data Nonna's API sends and receives.

Numbers from the database (like cap amounts) are sent as strings, for example
"2000000", so exact values are never rounded by floating point math.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

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
    changes: dict[str, dict[str, Any]] | None = None


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
    agreed: PositionOut | None = None  # the current agreed term this would be compared to
    matches_agreed: bool | None = None  # None when there's nothing agreed yet to compare to


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class ReviewIn(BaseModel):
    """An attorney's decision about an extracted clause."""

    action: ReviewAction
    reviewer: str = Field(min_length=1)
    note: str | None = None
    # For "corrected": the fixed values, like {"cap_amount": "25000000"}
    corrections: dict[str, Any] | None = None
    # For "corrected": save it even though it differs from the agreed baseline
    as_change: bool = False

    @model_validator(mode="after")
    def check_note_and_corrections(self) -> "ReviewIn":
        has_note = bool(self.note and self.note.strip())
        if self.action == "approved_change" and not has_note:
            raise ValueError("A note is required when approving an intentional change.")
        if self.action == "corrected":
            if not self.corrections:
                raise ValueError("Say what the correct value is.")
            if not has_note:
                raise ValueError("Add a short note explaining the correction.")
        elif self.corrections:
            raise ValueError("Corrections can only be sent with the corrected action.")
        return self



# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """The conversation so far, oldest first, ending with the user's new message."""

    messages: list[ChatMessage] = Field(min_length=1)


CardType = Literal["profile", "clause", "section", "positions", "history", "contracts", "review_queue"]


class Card(BaseModel):
    """Something the app shows under Nonna's reply. The data comes from the database."""

    type: CardType
    title: str
    data: Any


class ChatResponse(BaseModel):
    reply: str
    status: str | None = None
    cards: list[Card]



# ---------------------------------------------------------------------------
# Verbatim clauses and the library view
# ---------------------------------------------------------------------------

class ClauseText(BaseModel):
    """One clause's exact text, where it came from, and whether it's the agreed version."""

    source: SourceContract
    clause: ClauseOut
    is_agreed: bool
    applies_to: list[str] | None = None


class ContractWithClauses(BaseModel):
    contract: ContractOut
    clauses: list[ClauseOut]


class SectionOut(BaseModel):
    """One section of a contract, filed under a clause category."""

    id: int
    contract_id: int
    category: str
    section_number: str | None
    heading: str | None
    full_text: str

class SectionText(BaseModel):
    """One section's exact text and the contract it came from. Not reviewed."""

    source: SourceContract
    section: SectionOut


class TopicOut(BaseModel):
    """A clause topic that shows up in a counterparty's contracts."""

    category: str
    contract_count: int

class CounterpartyLibrary(BaseModel):
    """Everything Nonna knows about one counterparty, for the library view."""

    counterparty: CounterpartyDetail
    contracts: list[ContractWithClauses]
    agreed_clause_ids: list[int]
    superseded_clause_ids: list[int]  # used to be agreed, replaced by a later version
    sections: list[SectionOut]  # every clause, as written
    category_order: list[str]  # the order to show clause categories in


class ContractText(BaseModel):
    """The full text of one contract, for reading it in the library."""

    id: int
    title: str
    contract_type: str
    effective_date: date
    full_text: str | None
    has_file: bool
   