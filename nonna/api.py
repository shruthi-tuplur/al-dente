"""Nonna's API.

Run it from the repo root:
    uv run uvicorn nonna.api:app --reload

Then open http://127.0.0.1:8000/docs to try every endpoint in the browser.
The actual data work lives in lookups.py, so these endpoints stay thin.
"""

from typing import Annotated

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from nonna import (
    access, amendments, chat, contract_fixes, deadlines, drafting, explain, extraction, gc_exceptions, google_calendar,
    history, intake, lookups, notes, playbook, precedence, reviews, sections,
)
from nonna.database import get_session
from nonna.models import Clause, Contract
from nonna.schemas import (
    ChatRequest,
    ChatResponse,
    ClauseType,
    ContractText,
    CounterpartyLibrary,
    CounterpartyDetail,
    CounterpartySummary,
    Deadlines,
    DecisionOut,
    HistoryEntry,
    PlaybookExceptionOut,
    PositionOut,
    ReviewIn,
    ReviewQueueItem,
)

app = FastAPI(
    title="Nonna",
    description="Counterparty clause library: remembers what was agreed with each counterparty.",
    version="0.2.0",
)

SessionDep = Annotated[Session, Depends(get_session)]


def not_found(error: lookups.NotFound) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(error))


@app.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    """Check that the API can reach the database."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/counterparties", response_model=list[CounterpartySummary])
def list_counterparties(session: SessionDep) -> list[CounterpartySummary]:
    """All counterparties, with how many contracts each has."""
    return lookups.list_counterparties(session)


@app.get("/counterparties/{counterparty_id}", response_model=CounterpartyDetail)
def get_counterparty(counterparty_id: int, session: SessionDep) -> CounterpartyDetail:
    """One counterparty's signing entities and contracts, oldest first."""
    try:
        return lookups.get_counterparty_detail(session, counterparty_id)
    except lookups.NotFound as error:
        raise not_found(error) from error


@app.get("/counterparties/{counterparty_id}/positions", response_model=list[PositionOut])
def get_positions(
    counterparty_id: int, session: SessionDep, include_superseded: bool = False
) -> list[PositionOut]:
    """The agreed baselines with a counterparty. Add ?include_superseded=true for past ones."""
    try:
        return lookups.get_positions(session, counterparty_id, include_superseded)
    except lookups.NotFound as error:
        raise not_found(error) from error


@app.get(
    "/counterparties/{counterparty_id}/history/{clause_type}",
    response_model=list[HistoryEntry],
)
def get_clause_history(
    counterparty_id: int, clause_type: ClauseType, session: SessionDep
) -> list[HistoryEntry]:
    """How one clause type changed across a counterparty's contracts, oldest first."""
    try:
        return lookups.get_clause_history(session, counterparty_id, clause_type.value)
    except lookups.NotFound as error:
        raise not_found(error) from error


@app.get("/review-queue", response_model=list[ReviewQueueItem])
def get_review_queue(
    session: SessionDep, counterparty_id: int | None = None
) -> list[ReviewQueueItem]:
    """Extracted clauses waiting for an attorney. Filter with ?counterparty_id=."""
    return lookups.get_review_queue(session, counterparty_id)


@app.post(
    "/clauses/{clause_id}/reviews",
    response_model=reviews.ReviewOutcome,
    status_code=status.HTTP_201_CREATED,
    dependencies=access.AttorneyOnly,
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
def chat_with_nonna(request: ChatRequest, session: SessionDep, role: access.RoleDep) -> ChatResponse:
    """Ask Nonna a question. She answers from the database and returns cards to show.

    Anyone can chat. Read-only users get the lookup tools only (no drafting).
    """
    try:
        return chat.run_chat(session, request.messages, role)
    except chat.ChatUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


@app.post("/contracts/intake", response_model=intake.IntakeProposal, dependencies=access.AttorneyOnly)
def contract_intake(file: UploadFile, session: SessionDep) -> intake.IntakeProposal:
    """Upload a contract. Nonna reads it and proposes its details. Nothing is saved to the database yet."""
    data = file.file.read(intake.MAX_UPLOAD_BYTES + 1)
    try:
        return intake.propose(session, file.filename or "upload", data)
    except intake.IntakeError as error:
        raise HTTPException(422, str(error)) from error


@app.post(
    "/contracts",
    response_model=intake.SavedContract,
    status_code=status.HTTP_201_CREATED,
    dependencies=access.AttorneyOnly,
)
def save_contract(confirm: intake.IntakeConfirm, session: SessionDep) -> intake.SavedContract:
    """Save an uploaded contract after the attorney confirms its details."""
    try:
        return intake.save(session, confirm)
    except intake.IntakeError as error:
        raise HTTPException(422, str(error)) from error


@app.post(
    "/contracts/{contract_id}/extract",
    response_model=extraction.ExtractionResult,
    dependencies=access.AttorneyOnly,
)
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


@app.put(
    "/contracts/{contract_id}",
    response_model=contract_fixes.FixOutcome,
    dependencies=access.AttorneyOnly,
)
def fix_contract(contract_id: int, fix: contract_fixes.FixIn, session: SessionDep) -> contract_fixes.FixOutcome:
    """Fix an upload's details: title, type, date, vendor, or what it falls under. Needs a note."""
    try:
        return contract_fixes.fix_contract(session, contract_id, fix)
    except contract_fixes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except contract_fixes.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


@app.post(
    "/contracts/{contract_id}/delete",
    response_model=contract_fixes.FixOutcome,
    dependencies=access.AttorneyOnly,
)
def delete_contract(contract_id: int, change: contract_fixes.DeleteIn, session: SessionDep) -> contract_fixes.FixOutcome:
    """Delete an upload that was a mistake. Only before anything from it was reviewed."""
    try:
        return contract_fixes.delete_contract(session, contract_id, change)
    except contract_fixes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except contract_fixes.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


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


@app.get("/counterparties/{counterparty_id}/decisions", response_model=history.DecisionHistory)
def get_decision_history(counterparty_id: int, session: SessionDep) -> history.DecisionHistory:
    """Everything anyone decided about a vendor, newest first. Read-only."""
    try:
        return history.get_history(session, counterparty_id)
    except history.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@app.get("/counterparties/{counterparty_id}/notes", response_model=notes.NotesOut)
def get_relationship_notes(counterparty_id: int, session: SessionDep) -> notes.NotesOut:
    """The team's notes about a vendor: active ones first, then archived ones."""
    try:
        return notes.get_notes(session, counterparty_id)
    except notes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@app.post(
    "/counterparties/{counterparty_id}/notes",
    response_model=notes.NoteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=access.AttorneyOnly,
)
def add_relationship_note(counterparty_id: int, note: notes.NoteIn, session: SessionDep) -> notes.NoteOut:
    try:
        return notes.add_note(session, counterparty_id, note)
    except notes.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except notes.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error


@app.post("/notes/{note_id}/archive", response_model=notes.NoteOut, dependencies=access.AttorneyOnly)
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
    dependencies=access.AttorneyOnly,
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
    dependencies=access.AttorneyOnly,
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


@app.post(
    "/playbook-exceptions/{exception_id}/withdraw",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=access.AttorneyOnly,
)
def withdraw_playbook_exception(exception_id: int, change: gc_exceptions.WithdrawIn, session: SessionDep) -> Response:
    """Withdraw a GC exception. It stays in the history, and the term is flagged again."""
    try:
        gc_exceptions.withdraw_exception(session, exception_id, change)
    except gc_exceptions.NotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except gc_exceptions.ReviewRejected as error:
        raise HTTPException(422, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put("/playbook/{clause_type}", response_model=playbook.RuleOut, dependencies=access.AttorneyOnly)
def update_playbook_rule(clause_type: str, change: playbook.RuleIn, session: SessionDep) -> playbook.RuleOut:
    """Save a new version of one playbook rule. The old version is kept as history."""
    try:
        return playbook.update_rule(session, clause_type, change)
    except playbook.RuleRejected as error:
        raise HTTPException(422, str(error)) from error


@app.post(
    "/counterparties/{counterparty_id}/drafts",
    response_model=drafting.Draft,
    dependencies=access.AttorneyOnly,
)
def make_draft(counterparty_id: int, change: drafting.DraftIn, session: SessionDep) -> drafting.Draft:
    """Start a new SOW from this vendor's last one and the attorney's brief. Nothing is saved."""
    try:
        return drafting.make_draft(session, counterparty_id, change)
    except drafting.DraftUnavailable as error:
        raise HTTPException(422, str(error)) from error


@app.post("/drafts/docx", dependencies=access.AttorneyOnly)
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


@app.post(
    "/google-calendar/sync",
    response_model=google_calendar.SyncResult,
    dependencies=access.AttorneyOnly,
)
def calendar_sync(session: SessionDep) -> google_calendar.SyncResult:
    try:
        return google_calendar.sync(session)
    except google_calendar.CalendarUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


@app.post(
    "/google-calendar/disconnect",
    response_model=google_calendar.CalendarStatus,
    dependencies=access.AttorneyOnly,
)
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