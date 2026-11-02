"""Tests for Nonna's database layer.

These run against the real al_dente database with seed data loaded:
    psql al_dente -f nonna/db/schema.sql
    psql al_dente -f nonna/db/seed.sql
    uv run pytest

Every test rolls back at the end, so the database is never changed.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from nonna.database import SessionLocal
from nonna.models import (
    Clause,
    Contract,
    Counterparty,
    CounterpartyPosition,
    ReviewDecision,
)

CASTELLAN = "Castellan Bioprocessing"


@pytest.fixture
def session() -> Iterator[Session]:
    """A database session that always rolls back, so tests never change data."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def castellan(session: Session) -> Counterparty:
    return session.scalars(select(Counterparty).where(Counterparty.name == CASTELLAN)).one()


# ---------------------------------------------------------------------------
# Reading data
# ---------------------------------------------------------------------------

def test_seed_data_is_loaded(session: Session) -> None:
    names = set(session.scalars(select(Counterparty.name)))
    assert names == {"Castellan Bioprocessing", "Halvorsen Scientific"}


def test_counterparty_has_two_signing_entities(castellan: Counterparty) -> None:
    legal_names = {e.legal_name for e in castellan.entities}
    assert legal_names == {"Castellan Bioprocessing AG", "Castellan Bioprocessing US, Inc."}


def test_contract_family_tree(castellan: Counterparty) -> None:
    msa = next(c for c in castellan.contracts if c.contract_type == "MSA")

    sow_titles = sorted(c.title for c in msa.children)
    assert sow_titles == [
        "Statement of Work No. 1: Process Development",
        "Statement of Work No. 2: Tech Transfer",
    ]
    assert [a.title for a in msa.amendments] == ["Amendment No. 1 to Master Services Agreement"]
    assert all(sow.parent is msa for sow in msa.children)


def test_liability_cap_history_in_order(session: Session, castellan: Counterparty) -> None:
    rows = session.execute(
        select(Contract.contract_type, Clause.presence)
        .select_from(Clause)
        .join(Clause.contract)
        .where(Contract.counterparty_id == castellan.id, Clause.clause_type == "liability_cap")
        .order_by(Contract.effective_date)
    ).all()

    assert [tuple(r) for r in rows] == [
        ("NDA", "absent"),
        ("MSA", "present"),
        ("SOW", "incorporated_by_reference"),
        ("amendment", "present"),
        ("SOW", "incorporated_by_reference"),
    ]


def test_current_liability_cap_comes_from_the_amendment(
    session: Session, castellan: Counterparty
) -> None:
    position = session.scalars(
        select(CounterpartyPosition).where(
            CounterpartyPosition.counterparty_id == castellan.id,
            CounterpartyPosition.clause_type == "liability_cap",
            CounterpartyPosition.superseded_at.is_(None),
        )
    ).one()

    cap = position.baseline_clause.term("cap_amount")
    assert cap is not None
    assert cap.value == 2_000_000
    assert cap.unit == "USD"
    assert position.baseline_clause.contract.contract_type == "amendment"


def test_review_queue_has_sow_2_clauses(session: Session) -> None:
    pending = session.scalars(select(Clause).where(Clause.review_status == "pending")).all()

    assert len(pending) == 2
    assert {c.contract.title for c in pending} == {"Statement of Work No. 2: Tech Transfer"}


# ---------------------------------------------------------------------------
# Database guardrails (these must fail)
# ---------------------------------------------------------------------------

def test_review_decisions_cannot_be_edited(session: Session) -> None:
    decision = session.scalars(select(ReviewDecision).limit(1)).one()
    decision.note = "sneaky edit"

    with pytest.raises(DBAPIError, match="append-only"):
        session.flush()


def test_review_decisions_cannot_be_deleted(session: Session) -> None:
    decision = session.scalars(select(ReviewDecision).limit(1)).one()
    session.delete(decision)

    with pytest.raises(DBAPIError, match="append-only"):
        session.flush()


def test_approved_change_requires_a_note(session: Session) -> None:
    clause = session.scalars(select(Clause).limit(1)).one()
    session.add(ReviewDecision(clause_id=clause.id, action="approved_change", reviewer="pytest"))

    with pytest.raises(DBAPIError, match="review_decisions_check"):
        session.flush()


def test_unreviewed_clause_cannot_become_a_baseline(session: Session) -> None:
    pending = session.scalars(
        select(Clause).where(
            Clause.review_status == "pending", Clause.clause_type == "payment_terms"
        )
    ).one()
    session.add(
        CounterpartyPosition(
            counterparty_id=pending.contract.counterparty_id,
            clause_type="payment_terms",
            contract_type_scope=["SOW"],
            baseline_clause_id=pending.id,
            set_by="pytest",
        )
    )

    with pytest.raises(DBAPIError, match="Only reviewed clauses"):
        session.flush()
