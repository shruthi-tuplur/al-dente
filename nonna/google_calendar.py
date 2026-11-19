"""Optional Google Calendar sync for renewal and expiration deadlines.

Nonna works without this. When it's set up, Nonna keeps its own "Nonna deadlines"
calendar in your Google account up to date: one event per contract on the date someone
needs to act, with reminders 4 weeks, 1 week, and 1 day before.

Least access: Nonna asks only for the calendar.app.created scope, which lets it make
its own calendar and manage events on it. It can't see or change anything else in your
Google Calendar. Events carry only the vendor, the contract title, the date, and the
plain-English summary, never clause text.

Setup: add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env (see the README).
The sign-in token is saved in storage/, which is never committed.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nonna import deadlines

load_dotenv()
# The token Google returns may list scopes in a different order; that's fine
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = ["https://www.googleapis.com/auth/calendar.app.created"]
CALENDAR_NAME = "Nonna deadlines"
TOKEN_FILE = Path("storage/google_calendar.json")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/google-calendar/callback")
FRONTEND_URL = os.getenv("NONNA_FRONTEND_URL", "http://localhost:5173")
TIME_ZONE = os.getenv("NONNA_TIMEZONE", "America/Los_Angeles")
# Google allows reminders up to 4 weeks before an event
REMINDER_MINUTES = [28 * 24 * 60, 7 * 24 * 60, 24 * 60]

# Sign-ins in progress, by state. Nonna runs for one person locally, so memory is enough.
_pending: dict[str, Any] = {}


class CalendarUnavailable(Exception):
    """Google Calendar isn't set up or connected, or Google returned an error."""


class CalendarStatus(BaseModel):
    configured: bool  # the Google client ID and secret are in .env
    connected: bool  # someone has signed in with Google
    calendar_name: str = CALENDAR_NAME


class SyncResult(BaseModel):
    calendar_name: str
    created: int
    updated: int
    removed: int
    unchanged: int
    message: str


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def _client_config() -> dict[str, Any]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise CalendarUnavailable("Google Calendar isn't set up. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env.")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }


def _load() -> dict[str, Any]:
    if not TOKEN_FILE.is_file():
        return {}
    return json.loads(TOKEN_FILE.read_text())


def _save(data: dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    TOKEN_FILE.chmod(0o600)  # only you can read your Google sign-in


def status() -> CalendarStatus:
    configured = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
    return CalendarStatus(configured=configured, connected=configured and "token" in _load())


def sign_in_url() -> str:
    """Where to send the browser to sign in with Google."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _pending[state] = flow
    return url


def finish_sign_in(state: str, code: str) -> None:
    """Google sends the browser back here with a code to trade for a token."""
    flow = _pending.pop(state, None)
    if flow is None:
        raise CalendarUnavailable("That Google sign-in expired. Close this window and try connecting again.")
    flow.fetch_token(code=code)
    data = _load()
    data["token"] = json.loads(flow.credentials.to_json())
    _save(data)


def sign_in_page(ok: bool, message: str) -> str:
    """The little page the sign-in popup lands on. It tells Nonna and closes itself."""
    script = (
        f"<script>window.opener && window.opener.postMessage('nonna-calendar-connected', {json.dumps(FRONTEND_URL)});"
        "setTimeout(() => window.close(), 1200);</script>"
        if ok else ""
    )
    return (
        "<!doctype html><meta charset='utf-8'><title>Nonna</title>"
        "<body style=\"font-family: system-ui, sans-serif; background: #FAF8F5; color: #2B1D14; "
        "display: grid; place-items: center; height: 100vh; margin: 0\">"
        f"<p style='max-width: 32ch; text-align: center; line-height: 1.5'>{escape(message)}</p>{script}</body>"
    )


def disconnect() -> None:
    """Forget the Google sign-in. The Nonna deadlines calendar stays in Google until you delete it."""
    if TOKEN_FILE.is_file():
        TOKEN_FILE.unlink()


def _service(data: dict[str, Any]):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if "token" not in data:
        raise CalendarUnavailable("Google Calendar isn't connected yet.")
    creds = Credentials.from_authorized_user_info(data["token"], SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as error:  # noqa: BLE001 - usually an expired test-mode sign-in
            raise CalendarUnavailable("Your Google sign-in expired. Disconnect and connect again.") from error
        data["token"] = json.loads(creds.to_json())
        _save(data)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Syncing
# ---------------------------------------------------------------------------

def _event_body(row) -> dict[str, Any]:
    day = row.action_date
    title = (
        f"Last day to send non-renewal notice: {row.counterparty_name}"
        if row.notice_deadline and row.action_date == row.notice_deadline
        else f"Contract expires: {row.counterparty_name}"
    )
    description = "\n\n".join([
        row.source.title,
        row.summary,
        "Worked out by Nonna from the reviewed term. Confirm against the contract before acting.",
    ])
    return {
        "summary": title,
        "description": description,
        "start": {"date": day.isoformat()},
        "end": {"date": (day + timedelta(days=1)).isoformat()},
        "transparency": "transparent",  # shows as free, so it doesn't block meetings
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in REMINDER_MINUTES],
        },
        "extendedProperties": {"private": {"nonnaContractId": str(row.source.id)}},
    }


def sync(session: Session) -> SyncResult:
    """Make the Nonna deadlines calendar match Nonna's upcoming deadlines.

    One event per contract. Changed dates are updated in place, so nothing is duplicated,
    and events for deadlines that have passed or disappeared are removed.
    """
    from googleapiclient.errors import HttpError

    data = _load()
    service = _service(data)

    try:
        if not data.get("calendar_id"):
            calendar = service.calendars().insert(body={"summary": CALENDAR_NAME, "timeZone": TIME_ZONE}).execute()
            data["calendar_id"] = calendar["id"]
            data["events"] = {}
            _save(data)
        calendar_id = data["calendar_id"]
        events: dict[str, str] = data.setdefault("events", {})

        today = date.today()
        wanted = {
            str(row.source.id): row
            for row in deadlines.get_deadlines(session).rows
            if row.action_date and row.action_date >= today and row.status in ("upcoming", "notice_passed")
        }

        created = updated = removed = unchanged = 0
        for contract_id, row in wanted.items():
            body = _event_body(row)
            event_id = events.get(contract_id)
            if event_id:
                try:
                    current = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
                    if current.get("status") != "cancelled":
                        same = (
                            current.get("summary") == body["summary"]
                            and current.get("start", {}).get("date") == body["start"]["date"]
                            and current.get("description") == body["description"]
                        )
                        if same:
                            unchanged += 1
                        else:
                            service.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()
                            updated += 1
                        continue
                except HttpError as error:
                    if error.resp.status not in (404, 410):
                        raise
            # New, or someone deleted it in Google Calendar: make it again
            event = service.events().insert(calendarId=calendar_id, body=body).execute()
            events[contract_id] = event["id"]
            created += 1

        for contract_id in [c for c in events if c not in wanted]:
            try:
                service.events().delete(calendarId=calendar_id, eventId=events[contract_id]).execute()
            except HttpError as error:
                if error.resp.status not in (404, 410):
                    raise
            del events[contract_id]
            removed += 1
    except HttpError as error:
        if error.resp.status == 404 and data.get("calendar_id"):
            # The Nonna deadlines calendar was deleted in Google: start a fresh one next time
            data.pop("calendar_id", None)
            data["events"] = {}
            raise CalendarUnavailable("The Nonna deadlines calendar was deleted in Google. Sync again to make a new one.") from error
        raise CalendarUnavailable(f"Google Calendar returned an error ({error.resp.status}). Try again.") from error
    finally:
        _save(data)

    parts = [f"{n} {label}" for n, label in ((created, "added"), (updated, "updated"), (removed, "removed")) if n]
    message = (
        f"Your {CALENDAR_NAME} calendar is up to date: {', '.join(parts)}." if parts
        else f"Your {CALENDAR_NAME} calendar is already up to date."
    )
    return SyncResult(
        calendar_name=CALENDAR_NAME, created=created, updated=updated,
        removed=removed, unchanged=unchanged, message=message,
    )


def sync_quietly(session: Session) -> None:
    """Sync after a term is reviewed, if Google Calendar is connected. Never blocks the review."""
    if not status().connected:
        return
    try:
        sync(session)
    except Exception:  # noqa: BLE001 - a calendar hiccup must never undo an attorney's review
        pass