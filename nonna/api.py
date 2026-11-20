"""Nonna's API.

Run it from the repo root:
    uv run uvicorn nonna.api:app --reload

Then open http://127.0.0.1:8000/docs to try every endpoint in the browser.
"""

from typing import Annotated

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload
from nonna import (
    amendments, chat, deadlines, drafting, explain, extraction, gc_exceptions, google_calendar, intake, lookups,
    notes, playbook, precedence, reviews, sections,
)
from nonna.database import get_session
from nonna.models import Clause, Contract
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
    PlaybookExceptionOut,
    PositionOut,
    ReviewIn,
    ReviewQueueItem,
    SourceContract,
    TermOut,
    ChatRequest,
    ChatResponse,
    CounterpartyLibrary,
    Deadlines,
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
        outcome = reviews.review_clause(session, clause_id, review)
    except reviews.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except reviews.BaselineConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except reviews.SignOffNeeded as error:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, str(error)) from error
    except reviews.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error

    # A reviewed term can move a renewal date, so keep Google Calendar in step (if it's connected)
    clause = session.get(Clause, clause_id)
    if clause is not None and clause.clause_type == "term_renewal":
        google_calendar.sync_quietly(session)
    return outcome


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



@app.get("/deadlines", response_model=Deadlines)
def get_deadlines(
    session: SessionDep, within_days: int | None = None, counterparty_id: int | None = None
) -> Deadlines:
    """Expirations, renewals, and notice deadlines for active contracts, soonest first."""
    return deadlines.get_deadlines(session, within_days, counterparty_id)



@app.get("/contracts/{contract_id}/as-amended", response_model=amendments.AmendedContract)
def get_contract_as_amended(contract_id: int, session: SessionDep) -> amendments.AmendedContract:
    """A contract as it reads today, with its amendments applied. Worked out fresh every time."""
    try:
        return amendments.as_amended(session, contract_id)
    except amendments.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error




@app.get("/playbook", response_model=playbook.PlaybookCheck)
def get_playbook(session: SessionDep, counterparty_id: int | None = None) -> playbook.PlaybookCheck:
    """Aurelia's playbook, and how every vendor's agreed terms measure up against it."""
    return playbook.check_vendors(session, counterparty_id)

@app.get("/counterparties/{counterparty_id}/notes", response_model=notes.NotesOut)
def get_relationship_notes(counterparty_id: int, session: SessionDep) -> notes.NotesOut:
    """The team's notes about a vendor: active ones first, then archived ones."""
    try:
        return notes.get_notes(session, counterparty_id)
    except notes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@app.post("/counterparties/{counterparty_id}/notes", response_model=notes.NoteOut, status_code=status.HTTP_201_CREATED)
def add_relationship_note(counterparty_id: int, note: notes.NoteIn, session: SessionDep) -> notes.NoteOut:
    try:
        return notes.add_note(session, counterparty_id, note)
    except notes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except notes.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


@app.post("/notes/{note_id}/archive", response_model=notes.NoteOut)
def archive_relationship_note(note_id: int, change: notes.ArchiveIn, session: SessionDep) -> notes.NoteOut:
    """Archive a note. It stays in the history, it just stops showing as current."""
    try:
        return notes.archive_note(session, note_id, change)
    except notes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except notes.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


@app.get("/counterparties/{counterparty_id}/precedence", response_model=precedence.PrecedenceReport)
def get_precedence(counterparty_id: int, session: SessionDep) -> precedence.PrecedenceReport:
    """Where a vendor's SOWs say something different from the MSA, with the pieces to decide which controls."""
    try:
        return precedence.get_conflicts(session, counterparty_id)
    except precedence.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@app.post(
    "/clauses/{clause_id}/precedence-call",
    response_model=precedence.ControlCall,
    status_code=status.HTTP_201_CREATED,
)
def record_precedence_call(clause_id: int, call: precedence.CallIn, session: SessionDep) -> precedence.ControlCall:
    """Save the attorney's call on which term controls for one SOW term. Append-only."""
    try:
        return precedence.record_call(session, clause_id, call)
    except precedence.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except precedence.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error

@app.post(
    "/clauses/{clause_id}/playbook-exception",
    response_model=PlaybookExceptionOut,
    status_code=status.HTTP_201_CREATED,
)
def record_playbook_exception(
    clause_id: int, change: gc_exceptions.ExceptionIn, session: SessionDep
) -> PlaybookExceptionOut:
    """Record the GC's sign-off on an off-playbook term in a signed contract."""
    try:
        return gc_exceptions.record_exception(session, clause_id, change)
    except gc_exceptions.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except gc_exceptions.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


@app.post("/playbook-exceptions/{exception_id}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_playbook_exception(exception_id: int, change: gc_exceptions.WithdrawIn, session: SessionDep) -> Response:
    """Withdraw a GC exception. It stays in the history, and the term is flagged again."""
    try:
        gc_exceptions.withdraw_exception(session, exception_id, change)
    except gc_exceptions.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except gc_exceptions.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.put("/playbook/{clause_type}", response_model=playbook.RuleOut)
def update_playbook_rule(clause_type: str, change: playbook.RuleIn, session: SessionDep) -> playbook.RuleOut:
    """Save a new version of one playbook rule. The old version is kept as history."""
    try:
        return playbook.update_rule(session, clause_type, change)
    except playbook.RuleRejected as error:
        raise HTTPException(422, str(error)) from error





@app.post("/counterparties/{counterparty_id}/drafts", response_model=drafting.Draft)
def make_draft(counterparty_id: int, change: drafting.DraftIn, session: SessionDep) -> drafting.Draft:
    """Start a new SOW from this vendor's last one and the attorney's brief. Nothing is saved."""
    try:
        return drafting.make_draft(session, counterparty_id, change)
    except drafting.DraftUnavailable as error:
        raise HTTPException(422, str(error)) from error


@app.post("/drafts/docx")
def download_draft(draft: drafting.Draft) -> Response:
    """The reviewed draft (with any edits) as a Word file."""
    filename = drafting.docx_name(draft)
    return Response(
        content=drafting.to_docx(draft),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )




# ---------------------------------------------------------------------------
# Google Calendar (optional)
# ---------------------------------------------------------------------------

@app.get("/google-calendar/status", response_model=google_calendar.CalendarStatus)
def calendar_status() -> google_calendar.CalendarStatus:
    return google_calendar.status()


@app.get("/google-calendar/connect")
def calendar_connect() -> RedirectResponse:
    """Opened in a popup: sends the browser to Google to sign in."""
    try:
        return RedirectResponse(google_calendar.sign_in_url())
    except google_calendar.CalendarUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


@app.get("/google-calendar/callback", response_class=HTMLResponse)
def calendar_callback(state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    """Google sends the popup back here. Nonna saves the sign-in and the popup closes itself."""
    if error or not code:
        return HTMLResponse(google_calendar.sign_in_page(False, "Google Calendar wasn't connected. You can close this window."))
    try:
        google_calendar.finish_sign_in(state, code)
    except Exception as problem:  # noqa: BLE001 - show the reason in the popup instead of a stack trace
        message = str(problem) if isinstance(problem, google_calendar.CalendarUnavailable) else "Google sign-in didn't work. Close this window and try again."
        return HTMLResponse(google_calendar.sign_in_page(False, message))
    return HTMLResponse(google_calendar.sign_in_page(True, "Google Calendar is connected to Nonna. This window will close."))


@app.post("/google-calendar/sync", response_model=google_calendar.SyncResult)
def calendar_sync(session: SessionDep) -> google_calendar.SyncResult:
    try:
        return google_calendar.sync(session)
    except google_calendar.CalendarUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


@app.post("/google-calendar/disconnect", response_model=google_calendar.CalendarStatus)
def calendar_disconnect() -> google_calendar.CalendarStatus:
    """Forget the Google sign-in. The Nonna deadlines calendar stays in Google until you delete it."""
    google_calendar.disconnect()
    return google_calendar.status()




@app.post("/explain", response_model=explain.Explanation)
def explain_phrase(request: explain.ExplainIn, session: SessionDep) -> explain.Explanation:
    """Explain a highlighted phrase in plain English, with the contract's own definitions quoted."""
    try:
        return explain.explain(session, request)
    except explain.ExplainUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error