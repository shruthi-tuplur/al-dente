"""Nonna's API.

Run it from the repo root:
    uv run uvicorn nonna.api:app --reload

Then open http://127.0.0.1:8000/docs to try every endpoint in the browser.
"""

from typing import Annotated

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload
from nonna import chat, extraction, intake, lookups, reviews, sections
from nonna.database import get_session
from nonna.models import Contract
from nonna.models import (
    Clause,
    Contract,
    Counterparty,
    CounterpartyPosition,
    ReviewDecision,
)
from nonna.schemas import (
    ClauseOut,
    ClauseType,
    ContractText,
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
    ChatRequest,
    ChatResponse,
    CounterpartyLibrary,
)

app = FastAPI(
    title="Nonna",
    description="Counterparty clause library: remembers what was agreed with each counterparty.",
    version="0.1.0",
)

SessionDep = Annotated[Session, Depends(get_session)]

# What a review decision does to the clause's review status
STATUS_FOR_ACTION = {
    "approved": "approved",
    "approved_change": "approved",
    "corrected": "corrected",
    "rejected": "rejected",
}


# ---------------------------------------------------------------------------
# Helpers that turn database objects into API responses
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


def get_counterparty_or_404(session: Session, counterparty_id: int) -> Counterparty:
    counterparty = session.get(Counterparty, counterparty_id)
    if counterparty is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Counterparty not found.")
    return counterparty


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    """Check that the API can reach the database."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/counterparties", response_model=list[CounterpartySummary])
def list_counterparties(session: SessionDep) -> list[CounterpartySummary]:
    """All counterparties, with how many contracts each has."""
    rows = session.execute(
        select(Counterparty.id, Counterparty.name, func.count(Contract.id))
        .outerjoin(Contract, Contract.counterparty_id == Counterparty.id)
        .group_by(Counterparty.id)
        .order_by(Counterparty.name)
    ).all()
    return [CounterpartySummary(id=i, name=n, contract_count=c) for i, n, c in rows]


@app.get("/counterparties/{counterparty_id}", response_model=CounterpartyDetail)
def get_counterparty(counterparty_id: int, session: SessionDep) -> CounterpartyDetail:
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Counterparty not found.")

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


@app.get("/counterparties/{counterparty_id}/positions", response_model=list[PositionOut])
def get_positions(
    counterparty_id: int, session: SessionDep, include_superseded: bool = False
) -> list[PositionOut]:
    """The agreed baselines with a counterparty. Add ?include_superseded=true for past ones."""
    get_counterparty_or_404(session, counterparty_id)

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


@app.get(
    "/counterparties/{counterparty_id}/history/{clause_type}",
    response_model=list[HistoryEntry],
)
def get_clause_history(
    counterparty_id: int, clause_type: ClauseType, session: SessionDep
) -> list[HistoryEntry]:
    """How one clause type changed across a counterparty's contracts, oldest first."""
    get_counterparty_or_404(session, counterparty_id)

    clauses = session.scalars(
        select(Clause)
        .join(Clause.contract)
        .where(
            Contract.counterparty_id == counterparty_id,
            Clause.clause_type == clause_type.value,
        )
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


@app.get("/review-queue", response_model=list[ReviewQueueItem])
def get_review_queue(
    session: SessionDep, counterparty_id: int | None = None
) -> list[ReviewQueueItem]:
    """Extracted clauses waiting for an attorney. Filter with ?counterparty_id=."""
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


@app.post(
    "/clauses/{clause_id}/reviews",
    response_model=reviews.ReviewOutcome,
    status_code=status.HTTP_201_CREATED,
)
def review_clause(clause_id: int, review: ReviewIn, session: SessionDep) -> reviews.ReviewOutcome:
    """Record an attorney's decision about a clause and keep the counterparty's baseline up to date.

    Decisions are append-only. Approving a value that differs from the agreed baseline
    returns 409 unless it's approved as an intentional change with a note.
    """
    try:
        return reviews.review_clause(session, clause_id, review)
    except reviews.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except reviews.BaselineConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except reviews.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


@app.post("/chat", response_model=ChatResponse)
def chat_with_nonna(request: ChatRequest, session: SessionDep) -> ChatResponse:
    """Ask Nonna a question. She answers from the database and returns cards to show."""
    try:
        return chat.run_chat(session, request.messages)
    except chat.ChatUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error





@app.post("/contracts/intake", response_model=intake.IntakeProposal)
def contract_intake(file: UploadFile, session: SessionDep) -> intake.IntakeProposal:
    """Upload a contract. Nonna reads it and proposes its details. Nothing is saved to the database yet."""
    data = file.file.read(intake.MAX_UPLOAD_BYTES + 1)
    try:
        return intake.propose(session, file.filename or "upload", data)
    except intake.IntakeError as error:
        raise HTTPException(422, str(error)) from error




@app.post("/contracts", response_model=intake.SavedContract, status_code=status.HTTP_201_CREATED)
def save_contract(confirm: intake.IntakeConfirm, session: SessionDep) -> intake.SavedContract:
    """Save an uploaded contract after the attorney confirms its details."""
    try:
        return intake.save(session, confirm)
    except intake.IntakeError as error:
        raise HTTPException(422, str(error)) from error




@app.post("/contracts/{contract_id}/extract", response_model=extraction.ExtractionResult)
def extract_contract(contract_id: int, session: SessionDep) -> extraction.ExtractionResult:
    """Pull the key terms out of a saved contract. Everything is saved as pending review."""
    try:
        result = extraction.extract_contract(session, contract_id)
    except extraction.ExtractionError as error:
        raise HTTPException(422, str(error)) from error

    # Also file every section under a clause category for the library
    contract = session.get(Contract, contract_id)
    if contract is not None:
        sections.index_contract(session, contract)
    return result




@app.get("/counterparties/{counterparty_id}/library", response_model=CounterpartyLibrary)
def get_counterparty_library(counterparty_id: int, session: SessionDep) -> CounterpartyLibrary:
    """Every contract with a counterparty, each with all of its extracted clauses."""
    try:
        return lookups.get_counterparty_library(session, counterparty_id)
    except lookups.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error




@app.get("/contracts/{contract_id}/text", response_model=ContractText)
def get_contract_text(contract_id: int, session: SessionDep) -> ContractText:
    """The full text of a contract."""
    try:
        text, _ = lookups.get_contract_text(session, contract_id)
    except lookups.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return text


@app.get("/contracts/{contract_id}/file")
def get_contract_file(contract_id: int, session: SessionDep) -> FileResponse:
    """The original uploaded file, opened in the browser."""
    try:
        _, file_path = lookups.get_contract_text(session, contract_id)
    except lookups.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    # Only ever serve files from Nonna's own storage folder
    storage = intake.STORAGE_DIR.resolve()
    path = Path(file_path).resolve()
    if storage not in path.parents or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The original file isn't available.")

    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, media_type=media_type, content_disposition_type="inline")