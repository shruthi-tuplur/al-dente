"""SQLAlchemy models for Nonna.

These classes mirror the tables in db/schema.sql so Python code can work with
contracts and clauses as objects (contract.clauses, clause.terms) instead of
hand-written SQL.

schema.sql is the source of truth for the tables. These models never create
or change tables. Database-level rules (check constraints, the append-only
trigger, the baseline review check) are enforced by Postgres, so they apply
no matter what Python code does.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    """Base class for all Nonna models."""


class Counterparty(Base):
    """A business relationship, as the legal team thinks about it."""

    __tablename__ = "counterparties"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    entities: Mapped[list[CounterpartyEntity]] = relationship(back_populates="counterparty")
    contracts: Mapped[list[Contract]] = relationship(
        back_populates="counterparty", order_by="Contract.effective_date"
    )
    positions: Mapped[list[CounterpartyPosition]] = relationship(back_populates="counterparty")

    def __repr__(self) -> str:
        return f"<Counterparty {self.name!r}>"


class CounterpartyEntity(Base):
    """A specific legal entity that signs contracts for a counterparty."""

    __tablename__ = "counterparty_entities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("counterparties.id"))
    legal_name: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(Text)

    counterparty: Mapped[Counterparty] = relationship(back_populates="entities")
    contracts: Mapped[list[Contract]] = relationship(back_populates="entity")

    def __repr__(self) -> str:
        return f"<CounterpartyEntity {self.legal_name!r}>"


class Contract(Base):
    """An executed contract: NDA, MSA, SOW, amendment, or change order."""

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("counterparties.id"))
    # The database also checks that this entity belongs to the same counterparty
    # (a composite foreign key in schema.sql).
    entity_id: Mapped[int] = mapped_column(ForeignKey("counterparty_entities.id"))
    contract_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    parent_contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    amends_contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    file_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(Text, unique=True)
    # Full contract text can be long, so it is only loaded when actually used.
    full_text: Mapped[str | None] = mapped_column(Text, deferred=True)
    uploaded_by: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    counterparty: Mapped[Counterparty] = relationship(back_populates="contracts")
    entity: Mapped[CounterpartyEntity] = relationship(back_populates="contracts")
    clauses: Mapped[list[Clause]] = relationship(back_populates="contract")

    # Contract family tree: a SOW points to its MSA, an amendment points to what it amends
    parent: Mapped[Contract | None] = relationship(
        remote_side=[id], foreign_keys=[parent_contract_id], back_populates="children"
    )
    children: Mapped[list[Contract]] = relationship(
        foreign_keys=[parent_contract_id], back_populates="parent"
    )
    amends: Mapped[Contract | None] = relationship(
        remote_side=[id], foreign_keys=[amends_contract_id], back_populates="amendments"
    )
    amendments: Mapped[list[Contract]] = relationship(
        foreign_keys=[amends_contract_id], back_populates="amends"
    )

    def __repr__(self) -> str:
        return f"<Contract {self.contract_type} {self.title!r} ({self.effective_date})>"


class Clause(Base):
    """The full text of one clause type in one contract.

    No row means not extracted yet. presence="absent" means checked and not there.
    """

    __tablename__ = "clauses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    clause_type: Mapped[str] = mapped_column(Text)
    section_number: Mapped[str | None] = mapped_column(Text)
    heading: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    presence: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    review_status: Mapped[str] = mapped_column(Text, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    contract: Mapped[Contract] = relationship(back_populates="clauses")
    terms: Mapped[list[ClauseTerm]] = relationship(back_populates="clause")
    decisions: Mapped[list[ReviewDecision]] = relationship(
        back_populates="clause", order_by="ReviewDecision.created_at"
    )

    def term(self, term_key: str) -> ClauseTerm | None:
        """Return the term with this key, or None if the clause does not have it."""
        return next((t for t in self.terms if t.term_key == term_key), None)

    def __repr__(self) -> str:
        return f"<Clause {self.clause_type} in contract {self.contract_id} ({self.presence})>"


class ClauseTerm(Base):
    """One structured value extracted from a clause. Exactly one value column is set."""

    __tablename__ = "clause_terms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    clause_id: Mapped[int] = mapped_column(ForeignKey("clauses.id"))
    term_key: Mapped[str] = mapped_column(Text)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_date: Mapped[date | None] = mapped_column(Date)
    unit: Mapped[str | None] = mapped_column(Text)

    clause: Mapped[Clause] = relationship(back_populates="terms")

    @property
    def value(self) -> Decimal | str | bool | date | None:
        """Whichever value column is filled in."""
        for v in (self.value_numeric, self.value_text, self.value_bool, self.value_date):
            if v is not None:
                return v
        return None

    def __repr__(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return f"<ClauseTerm {self.term_key}={self.value}{unit}>"


class ReviewDecision(Base):
    """An attorney's decision about a clause. Append-only: never edited or deleted."""

    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    clause_id: Mapped[int] = mapped_column(ForeignKey("clauses.id"))
    action: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    # For corrections: {"cap_amount": {"from": "2500000", "to": "25000000"}}
    changes: Mapped[dict | None] = mapped_column(JSONB)

    clause: Mapped[Clause] = relationship(back_populates="decisions")

    def __repr__(self) -> str:
        return f"<ReviewDecision {self.action} by {self.reviewer} on clause {self.clause_id}>"


class CounterpartyPosition(Base):
    """The agreed baseline for a clause type with a counterparty.

    The current position has superseded_at = None. Older positions are kept as history.
    """

    __tablename__ = "counterparty_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("counterparties.id"))
    clause_type: Mapped[str] = mapped_column(Text)
    contract_type_scope: Mapped[list[str]] = mapped_column(ARRAY(Text))
    baseline_clause_id: Mapped[int] = mapped_column(ForeignKey("clauses.id"))
    set_by: Mapped[str] = mapped_column(Text)
    set_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
    superseded_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)

    counterparty: Mapped[Counterparty] = relationship(back_populates="positions")
    baseline_clause: Mapped[Clause] = relationship()

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None

    def __repr__(self) -> str:
        state = "current" if self.is_current else "superseded"
        return f"<CounterpartyPosition {self.clause_type} {self.contract_type_scope} ({state})>"




class ContractSection(Base):
    """One section of a contract, filed under a clause category. Verbatim, not reviewed."""

    __tablename__ = "contract_sections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(Text)
    section_number: Mapped[str | None] = mapped_column(Text)
    heading: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<ContractSection {self.category} §{self.section_number} in contract {self.contract_id}>"
