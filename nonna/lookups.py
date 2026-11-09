"""Nonna's lookups: the one place that reads and writes contract data.

Both the REST API (api.py) and Nonna's chat tools (chat.py) call these
functions, so an answer in the chat always matches what the API returns.
"""
from decimal import Decimal
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from nonna.models import (
    Clause,
    Contract,
    ContractSection,
    Counterparty,
    CounterpartyEntity,
    CounterpartyPosition,
    ReviewDecision,
)
from nonna.sections import CATEGORY_ORDER
from nonna.schemas import (
    ClauseOut,
    ClauseText,
    ContractText,
    ContractWithClauses,
    CounterpartyLibrary,
    SectionOut,
    SectionText,
    TopicOut,
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
    VendorComparison,
    VendorFilter,
    VendorRow,
)

# Which contract types share a baseline (an NDA never sets the MSA's cap, for example)
SCOPE_FOR_TYPE = {
    "MSA": ["MSA", "amendment"],
    "amendment": ["MSA", "amendment"],
    "SOW": ["SOW"],
    "change_order": ["SOW"],
    "NDA": ["NDA"],
}

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
        changes=decision.changes,
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

        positions: dict[int, list[PositionOut]] = {}  # per counterparty, so each is loaded once
    items = []
    for c in session.scalars(query):
        counterparty_id = c.contract.counterparty_id
        if counterparty_id not in positions:
            positions[counterparty_id] = get_positions(session, counterparty_id)
        scope = SCOPE_FOR_TYPE.get(c.contract.contract_type, [])
        agreed = next(
            (p for p in positions[counterparty_id] if p.clause_type == c.clause_type and p.applies_to == scope),
            None,
        )
        clause = to_clause(c)
        matches = None
        if agreed is not None and clause.terms:
            matches = {t.term_key: t.value for t in agreed.clause.terms} == {
                t.term_key: t.value for t in clause.terms
            }
        items.append(
            ReviewQueueItem(
                counterparty_id=counterparty_id,
                counterparty_name=c.contract.counterparty.name,
                source=to_source(c.contract),
                clause=clause,
                agreed=agreed,
                matches_agreed=matches,
            )
        )
    return items

# ---------------------------------------------------------------------------
# Comparing one term across every vendor
# ---------------------------------------------------------------------------

# Which filters make sense for which clause type
FILTERS_FOR_TYPE = {
    "liability_cap": {"cap_below", "cap_at_least"},
    "payment_terms": {"net_days_min", "net_days_max", "payment_structure"},
    "governing_law": {"jurisdiction"},
    "indemnification": {"is_mutual", "covers_ip_infringement"},
}


def _money(amount: Decimal) -> str:
    return f"${amount:,.0f}"


def describe_filters(clause_type: str, f: VendorFilter) -> str:
    """The filters in plain English, so the card says exactly what was checked."""
    parts = []
    if f.cap_below is not None:
        parts.append(f"cap below {_money(f.cap_below)}")
    if f.cap_at_least is not None:
        parts.append(f"cap of at least {_money(f.cap_at_least)}")
    if f.net_days_min is not None and f.net_days_max is not None:
        parts.append(
            f"net {f.net_days_min}" if f.net_days_min == f.net_days_max
            else f"net {f.net_days_min} to {f.net_days_max} days"
        )
    elif f.net_days_min is not None:
        parts.append(f"net {f.net_days_min} days or longer")
    elif f.net_days_max is not None:
        parts.append(f"net {f.net_days_max} days or shorter")
    if f.payment_structure:
        parts.append(f"{f.payment_structure} billing")
    if f.jurisdiction:
        parts.append(f"{f.jurisdiction} law")
    if f.is_mutual is not None:
        parts.append("mutual" if f.is_mutual else "one-way")
    if f.covers_ip_infringement is not None:
        parts.append("covers IP infringement" if f.covers_ip_infringement else "doesn't cover IP infringement")
    if f.applies_to:
        parts.append(f"{f.applies_to}s only")
    return ", ".join(parts) or "every vendor"


def _matches(values: dict, unit: str | None, f: VendorFilter) -> bool | None:
    """True or False for a match. None when a USD cap filter can't apply (another currency)."""
    cap = values.get("cap_amount")
    if f.cap_below is not None or f.cap_at_least is not None:
        if cap is None:
            return False
        if (unit or "USD") != "USD":
            return None
        if f.cap_below is not None and not cap < f.cap_below:
            return False
        if f.cap_at_least is not None and not cap >= f.cap_at_least:
            return False

    days = values.get("net_days")
    if f.net_days_min is not None and (days is None or days < f.net_days_min):
        return False
    if f.net_days_max is not None and (days is None or days > f.net_days_max):
        return False
    if f.payment_structure and values.get("payment_structure") != f.payment_structure:
        return False

    if f.jurisdiction:
        law = str(values.get("jurisdiction") or "").lower()
        wanted = f.jurisdiction.strip().lower()
        if not law or (wanted not in law and law not in wanted):
            return False

    if f.is_mutual is not None and values.get("is_mutual") is not f.is_mutual:
        return False
    if f.covers_ip_infringement is not None and values.get("covers_ip_infringement") is not f.covers_ip_infringement:
        return False
    return True


def compare_vendors(session: Session, clause_type: str, f: VendorFilter) -> VendorComparison:
    """One agreed term across every vendor, filtered exactly in code."""
    if clause_type not in FILTERS_FOR_TYPE:
        raise ValueError(f"Nonna doesn't compare {clause_type} across vendors.")
    used = {k for k, v in f.model_dump(exclude={"applies_to"}).items() if v is not None}
    wrong = used - FILTERS_FOR_TYPE[clause_type]
    if wrong:
        raise ValueError(f"{', '.join(sorted(wrong))} can't be used with {clause_type}.")

    scope = SCOPE_FOR_TYPE.get(f.applies_to) if f.applies_to else None
    positions = session.scalars(
        select(CounterpartyPosition)
        .where(
            CounterpartyPosition.clause_type == clause_type,
            CounterpartyPosition.superseded_at.is_(None),
        )
        .options(
            selectinload(CounterpartyPosition.counterparty),
            selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.terms),
            selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.contract),
        )
    ).all()
    if scope is not None:
        positions = [p for p in positions if p.contract_type_scope == scope]

    matches: list[VendorRow] = []
    not_comparable: set[str] = set()
    other_agreed: set[int] = set()
    with_position: set[int] = set()
    for p in positions:
        with_position.add(p.counterparty_id)
        clause = p.baseline_clause
        values = {t.term_key: t.value for t in clause.terms}
        unit = next((t.unit for t in clause.terms if t.term_key == "cap_amount"), None)
        result = _matches(values, unit, f)
        if result is None:
            not_comparable.add(p.counterparty.name)
        elif result:
            matches.append(
                VendorRow(
                    counterparty_id=p.counterparty_id,
                    counterparty_name=p.counterparty.name,
                    applies_to=p.contract_type_scope,
                    source=to_source(clause.contract),
                    clause=to_clause(clause),
                )
            )
        else:
            other_agreed.add(p.counterparty_id)
    other_agreed -= {m.counterparty_id for m in matches}

    # Vendors with nothing agreed: either confirmed absent by an attorney, or simply no record
    # NDAs normally have no cap or payment terms, so they only count when asked about directly
    contract_types = scope or ["MSA", "amendment", "SOW", "change_order"]
    absent_conditions = [
        Clause.clause_type == clause_type,
        Clause.presence == "absent",
        Clause.review_status.in_(("approved", "corrected")),
        Contract.contract_type.in_(contract_types),
    ]
    if with_position:
        absent_conditions.append(Counterparty.id.notin_(sorted(with_position)))
    confirmed_absent = set(session.scalars(
        select(Counterparty.name)
        .join(Contract, Contract.counterparty_id == Counterparty.id)
        .join(Clause, Clause.contract_id == Contract.id)
        .where(*absent_conditions)
    ))
    everyone = session.execute(select(Counterparty.id, Counterparty.name)).all()
    no_record = sorted(
        name for cid, name in everyone if cid not in with_position and name not in confirmed_absent
    )
    pending = sorted(set(session.scalars(
        select(Counterparty.name)
        .join(Contract, Contract.counterparty_id == Counterparty.id)
        .join(Clause, Clause.contract_id == Contract.id)
        .where(
            Clause.clause_type == clause_type,
            Clause.review_status == "pending",
            Clause.presence == "present",
            Contract.contract_type.in_(contract_types),
        )
    )))

    matches.sort(key=lambda r: (r.counterparty_name, r.applies_to))
    return VendorComparison(
        clause_type=clause_type,
        filters=describe_filters(clause_type, f),
        matches=matches,
        other_agreed=len(other_agreed),
        not_comparable=sorted(not_comparable),
        confirmed_absent=sorted(confirmed_absent),
        no_record=no_record,
        pending=pending,
    )
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




# ---------------------------------------------------------------------------
# Verbatim clauses and the library view
# ---------------------------------------------------------------------------

def _agreed_clause_ids(session: Session, counterparty_id: int) -> set[int]:
    return set(
        session.scalars(
            select(CounterpartyPosition.baseline_clause_id).where(
                CounterpartyPosition.counterparty_id == counterparty_id,
                CounterpartyPosition.superseded_at.is_(None),
            )
        )
    )

def _superseded_clause_ids(session: Session, counterparty_id: int) -> set[int]:
    replaced = set(
        session.scalars(
            select(CounterpartyPosition.baseline_clause_id).where(
                CounterpartyPosition.counterparty_id == counterparty_id,
                CounterpartyPosition.superseded_at.is_not(None),
            )
        )
    )
    return replaced - _agreed_clause_ids(session, counterparty_id)

def get_clause_texts(
    session: Session, counterparty_id: int, clause_type: str, contract_id: int | None = None
) -> list[ClauseText]:
    """The exact text of a clause: from one contract, or the currently agreed version(s)."""
    _require_counterparty(session, counterparty_id)

    if contract_id is None:
        return [
            ClauseText(source=p.source, clause=p.clause, is_agreed=True, applies_to=p.applies_to)
            for p in get_positions(session, counterparty_id, clause_type=clause_type)
        ]

    clause = session.scalars(
        select(Clause)
        .join(Clause.contract)
        .where(
            Clause.contract_id == contract_id,
            Clause.clause_type == clause_type,
            Contract.counterparty_id == counterparty_id,
        )
        .options(selectinload(Clause.terms), selectinload(Clause.contract))
    ).one_or_none()
    if clause is None:
        return []
    return [
        ClauseText(
            source=to_source(clause.contract),
            clause=to_clause(clause),
            is_agreed=clause.id in _agreed_clause_ids(session, counterparty_id),
        )
    ]

def _to_section(section: ContractSection) -> SectionOut:
    return SectionOut(
        id=section.id, contract_id=section.contract_id, category=section.category,
        section_number=section.section_number, heading=section.heading, full_text=section.full_text,
    )


def list_topics(session: Session, counterparty_id: int) -> list[TopicOut]:
    """Every clause topic in a counterparty's contracts, with how many contracts have it."""
    _require_counterparty(session, counterparty_id)
    rows = session.execute(
        select(ContractSection.category, func.count(func.distinct(ContractSection.contract_id)))
        .join(Contract, Contract.id == ContractSection.contract_id)
        .where(Contract.counterparty_id == counterparty_id)
        .group_by(ContractSection.category)
    ).all()
    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    rows = sorted(rows, key=lambda r: (rank.get(r[0], len(rank)), r[0]))
    return [TopicOut(category=category, contract_count=count) for category, count in rows]


def get_section_texts(
    session: Session,
    counterparty_id: int,
    category: str | None = None,
    search: str | None = None,
    contract_id: int | None = None,
) -> list[SectionText]:
    """The exact text of sections with a counterparty, by topic and/or a word or phrase, oldest first."""
    _require_counterparty(session, counterparty_id)
    query = (
        select(ContractSection, Contract)
        .join(Contract, Contract.id == ContractSection.contract_id)
        .where(Contract.counterparty_id == counterparty_id)
        .order_by(Contract.effective_date, ContractSection.position)
    )
    if category:
        query = query.where(func.lower(ContractSection.category) == category.strip().lower())
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(ContractSection.heading.ilike(pattern), ContractSection.full_text.ilike(pattern)))
    if contract_id is not None:
        query = query.where(ContractSection.contract_id == contract_id)
    return [
        SectionText(source=to_source(contract), section=_to_section(section))
        for section, contract in session.execute(query.limit(12)).all()
    ]

def get_counterparty_library(session: Session, counterparty_id: int) -> CounterpartyLibrary:
    """Every contract with a counterparty, each with all of its extracted clauses."""
    detail = get_counterparty_detail(session, counterparty_id)
    clauses = session.scalars(
        select(Clause)
        .join(Clause.contract)
        .where(Contract.counterparty_id == counterparty_id)
        .options(selectinload(Clause.terms))
        .order_by(Clause.clause_type)
    ).all()

    by_contract: dict[int, list[ClauseOut]] = {}
    for clause in clauses:
        by_contract.setdefault(clause.contract_id, []).append(to_clause(clause))

    return CounterpartyLibrary(
        counterparty=detail,
        contracts=[
            ContractWithClauses(contract=c, clauses=by_contract.get(c.id, []))
            for c in detail.contracts
        ],
        agreed_clause_ids=sorted(_agreed_clause_ids(session, counterparty_id)),
        superseded_clause_ids=sorted(_superseded_clause_ids(session, counterparty_id)),
        sections=[
            SectionOut(
                id=s.id, contract_id=s.contract_id, category=s.category,
                section_number=s.section_number, heading=s.heading, full_text=s.full_text,
            )
            for s in session.scalars(
                select(ContractSection)
                .join(Contract, Contract.id == ContractSection.contract_id)
                .where(Contract.counterparty_id == counterparty_id)
                .order_by(Contract.effective_date, ContractSection.position)
            )
        ],
        category_order=CATEGORY_ORDER,
    )



def get_contract_text(session: Session, contract_id: int) -> tuple[ContractText, str]:
    """A contract's full text, plus where its original file is stored."""
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise NotFound(f"No contract with id {contract_id}.")
    return (
        ContractText(
            id=contract.id,
            title=contract.title,
            contract_type=contract.contract_type,
            effective_date=contract.effective_date,
            full_text=contract.full_text,
            has_file=bool(contract.file_path),
        ),
        contract.file_path,
    )