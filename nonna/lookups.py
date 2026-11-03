"""Nonna's lookups: the one place that reads and writes contract data.

Both the REST API (api.py) and Nonna's chat tools (chat.py) call these
functions, so an answer in the chat always matches what the API returns.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from nonna.models import (
    Clause,
    Contract,
    Counterparty,
    CounterpartyEntity,
    CounterpartyPosition,
    ReviewDecision,
)
from nonna.schemas import (
    ClauseOut,
    ContractOut,
    CounterpartyDetail,
    CounterpartySummary,
    DecisionOut,
    EntityOut,
    HistoryEntry,
    PositionOut,
    ReviewIn,
    ReviewQueueItem,
    SourceContract,
    TermOut,
)

# What a review decision does to the clause's review status
STATUS_FOR_ACTION = {
    "approved": "approved",
    "approved_change": "approved",
    "corrected": "corrected",
    "rejected": "rejected",
}


class NotFound(Exception):
    """The counterparty or clause does not exist."""


class ReviewRejected(Exception):
    """The database refused a review decision (one of its rules)."""


# ---------------------------------------------------------------------------
# Turning database objects into response shapes
# ---------------------------------------------------------------------------

def to_source(contract: Contract) -> SourceContract:
    return SourceContract(
        id=contract.id,
        contract_type=contract.contract_type,
        title=contract.title,
        effective_date=contract.effective_date,
    )


def to_clause(clause: Clause) -> ClauseOut:
    return ClauseOut(
        id=clause.id,
        clause_type=clause.clause_type,
        section_number=clause.section_number,
        heading=clause.heading,
        full_text=clause.full_text,
        presence=clause.presence,
        extraction_method=clause.extraction_method,
        confidence=clause.confidence,
        review_status=clause.review_status,
        terms=[TermOut(term_key=t.term_key, value=t.value, unit=t.unit) for t in clause.terms],
    )


def to_decision(decision: ReviewDecision) -> DecisionOut:
    return DecisionOut(
        id=decision.id,
        clause_id=decision.clause_id,
        action=decision.action,
        note=decision.note,
        reviewer=decision.reviewer,
        created_at=decision.created_at,
    )


def _require_counterparty(session: Session, counterparty_id: int) -> Counterparty:
    counterparty = session.get(Counterparty, counterparty_id)
    if counterparty is None:
        raise NotFound(f"No counterparty with id {counterparty_id}.")
    return counterparty


def _summaries(session: Session, where_clause=None) -> list[CounterpartySummary]:
    query = (
        select(Counterparty.id, Counterparty.name, func.count(Contract.id))
        .outerjoin(Contract, Contract.counterparty_id == Counterparty.id)
        .group_by(Counterparty.id)
        .order_by(Counterparty.name)
    )
    if where_clause is not None:
        query = query.where(where_clause)
    return [
        CounterpartySummary(id=i, name=n, contract_count=c)
        for i, n, c in session.execute(query).all()
    ]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def list_counterparties(session: Session) -> list[CounterpartySummary]:
    """All counterparties, with how many contracts each has."""
    return _summaries(session)


def find_counterparties(session: Session, name: str) -> list[CounterpartySummary]:
    """Counterparties whose name, or whose signing entity's legal name, contains `name`."""
    pattern = f"%{name.strip()}%"
    matching_ids = (
        select(Counterparty.id)
        .outerjoin(Counterparty.entities)
        .where(
            or_(
                Counterparty.name.ilike(pattern),
                CounterpartyEntity.legal_name.ilike(pattern),
            )
        )
    )
    return _summaries(session, Counterparty.id.in_(matching_ids))


def get_counterparty_detail(session: Session, counterparty_id: int) -> CounterpartyDetail:
    """One counterparty's signing entities and contracts, oldest first."""
    counterparty = session.scalars(
        select(Counterparty)
        .where(Counterparty.id == counterparty_id)
        .options(
            selectinload(Counterparty.entities),
            selectinload(Counterparty.contracts).selectinload(Contract.entity),
        )
    ).one_or_none()
    if counterparty is None:
        raise NotFound(f"No counterparty with id {counterparty_id}.")

    return CounterpartyDetail(
        id=counterparty.id,
        name=counterparty.name,
        entities=[
            EntityOut(id=e.id, legal_name=e.legal_name, jurisdiction=e.jurisdiction)
            for e in counterparty.entities
        ],
        contracts=[
            ContractOut(
                id=c.id,
                contract_type=c.contract_type,
                title=c.title,
                effective_date=c.effective_date,
                expiration_date=c.expiration_date,
                status=c.status,
                signed_by_entity=c.entity.legal_name,
                parent_contract_id=c.parent_contract_id,
                amends_contract_id=c.amends_contract_id,
            )
            for c in counterparty.contracts
        ],
    )


def get_positions(
    session: Session,
    counterparty_id: int,
    include_superseded: bool = False,
    clause_type: str | None = None,
) -> list[PositionOut]:
    """The agreed baselines with a counterparty."""
    _require_counterparty(session, counterparty_id)

    query = (
        select(CounterpartyPosition)
        .where(CounterpartyPosition.counterparty_id == counterparty_id)
        .options(
            selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.terms),
            selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.contract),
        )
        .order_by(CounterpartyPosition.clause_type, CounterpartyPosition.set_at)
    )
    if not include_superseded:
        query = query.where(CounterpartyPosition.superseded_at.is_(None))
    if clause_type is not None:
        query = query.where(CounterpartyPosition.clause_type == clause_type)

    return [
        PositionOut(
            id=p.id,
            clause_type=p.clause_type,
            applies_to=p.contract_type_scope,
            is_current=p.is_current,
            set_by=p.set_by,
            set_at=p.set_at,
            note=p.note,
            source=to_source(p.baseline_clause.contract),
            clause=to_clause(p.baseline_clause),
        )
        for p in session.scalars(query)
    ]


def get_clause_history(
    session: Session, counterparty_id: int, clause_type: str
) -> list[HistoryEntry]:
    """How one clause type changed across a counterparty's contracts, oldest first."""
    _require_counterparty(session, counterparty_id)

    clauses = session.scalars(
        select(Clause)
        .join(Clause.contract)
        .where(Contract.counterparty_id == counterparty_id, Clause.clause_type == clause_type)
        .options(
            selectinload(Clause.terms),
            selectinload(Clause.decisions),
            selectinload(Clause.contract),
        )
        .order_by(Contract.effective_date, Contract.id)
    )
    return [
        HistoryEntry(
            source=to_source(c.contract),
            clause=to_clause(c),
            decisions=[to_decision(d) for d in c.decisions],
        )
        for c in clauses
    ]


def get_review_queue(session: Session, counterparty_id: int | None = None) -> list[ReviewQueueItem]:
    """Extracted clauses waiting for an attorney."""
    query = (
        select(Clause)
        .join(Clause.contract)
        .where(Clause.review_status == "pending")
        .options(
            selectinload(Clause.terms),
            selectinload(Clause.contract).selectinload(Contract.counterparty),
        )
        .order_by(Contract.uploaded_at, Clause.id)
    )
    if counterparty_id is not None:
        query = query.where(Contract.counterparty_id == counterparty_id)

    return [
        ReviewQueueItem(
            counterparty_id=c.contract.counterparty_id,
            counterparty_name=c.contract.counterparty.name,
            source=to_source(c.contract),
            clause=to_clause(c),
        )
        for c in session.scalars(query)
    ]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def record_review(session: Session, clause_id: int, review: ReviewIn) -> DecisionOut:
    """Save an attorney's decision and update the clause's review status together."""
    clause = session.get(Clause, clause_id)
    if clause is None:
        raise NotFound(f"No clause with id {clause_id}.")

    decision = ReviewDecision(
        clause_id=clause.id,
        action=review.action,
        note=review.note,
        reviewer=review.reviewer,
    )
    session.add(decision)
    clause.review_status = STATUS_FOR_ACTION[review.action]

    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise ReviewRejected(str(error.orig).splitlines()[0]) from error

    session.refresh(decision)
    return to_decision(decision)