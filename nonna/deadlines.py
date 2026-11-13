"""Expirations and renewal deadlines, worked out in code.

Every date comes from two things: the contract's effective date, and its term and renewal
clause after an attorney has reviewed it. The model never calculates a date.

Conventions (shown to the attorney as an estimate to confirm against the contract):
- A term of N months that starts on the effective date ends the day before the
  N-month anniversary (a 3 year term starting Mar 1, 2025 ends Feb 29, 2028).
- An auto-renewing term rolls forward by its renewal period until it covers today.
- The non-renewal notice deadline is the term's last day minus the notice period.

Run this to pull the term from contracts uploaded before Nonna tracked it:
    uv run python -m nonna.deadlines
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nonna.models import Clause, Contract
from nonna.schemas import DeadlineRow, Deadlines, SourceContract

REVIEWED = ("approved", "corrected")
# Only these contracts have a term worth tracking on their own. SOWs and change orders
# usually run until their work is done, and amendments change their parent's term.
TRACKED_TYPES = ("MSA", "NDA", "SOW", "change_order")


def add_months(start: date, months: int) -> date:
    """The same day of the month, `months` later (clamped to the end of shorter months)."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _period(months: int) -> str:
    if months % 12 == 0:
        years = months // 12
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{months} month{'s' if months != 1 else ''}"


@dataclass
class Schedule:
    status: str
    term_end: date | None
    notice_deadline: date | None
    action_date: date | None
    summary: str


def work_out(effective: date, values: dict[str, Any], today: date) -> Schedule:
    """The current term end, the notice deadline, and what needs doing next. Pure, so it's easy to test."""
    if values.get("ends_on_event"):
        return Schedule("ends_on_event", None, None, None,
                        "Ends when its work is done, not on a date, so there's no deadline to track.")

    def num(key: str) -> int | None:
        v = values.get(key)
        return int(v) if isinstance(v, (int, Decimal)) and not isinstance(v, bool) else None

    initial, renewal, notice = num("initial_term_months"), num("renewal_term_months"), num("notice_days")
    auto = values.get("auto_renews") is True

    if isinstance(values.get("end_date"), date):
        end = values["end_date"]
    elif initial:
        end = add_months(effective, initial) - timedelta(days=1)
    else:
        return Schedule("unknown", None, None, None,
                        "The term length isn't on file, so Nonna can't work out the dates.")

    if not auto:
        if end < today:
            return Schedule("expired", end, None, end, f"Expired on {_fmt(end)}. It doesn't renew on its own.")
        return Schedule("upcoming", end, None, end,
                        f"Expires on {_fmt(end)}. It doesn't renew on its own.")

    if not renewal:
        return Schedule("unknown", end, None, None,
                        f"Renews automatically, but the renewal period isn't on file. Current term ends {_fmt(end)}.")

    # Roll forward through renewals until the current term covers today
    while end < today:
        end = add_months(end + timedelta(days=1), renewal) - timedelta(days=1)

    if not notice:
        return Schedule("upcoming", end, None, end,
                        f"Renews for {_period(renewal)} after {_fmt(end)}. No notice period is on file.")

    deadline = end - timedelta(days=notice)
    renews_on = end + timedelta(days=1)
    if deadline < today:
        next_end = add_months(renews_on, renewal) - timedelta(days=1)
        next_deadline = next_end - timedelta(days=notice)
        return Schedule(
            "notice_passed", end, next_deadline, next_deadline,
            f"The notice window for this term closed on {_fmt(deadline)}, so it renews on {_fmt(renews_on)} "
            f"for {_period(renewal)}. To stop the renewal after that, send notice by {_fmt(next_deadline)}.",
        )
    return Schedule(
        "upcoming", end, deadline, deadline,
        f"Renews on {_fmt(renews_on)} for {_period(renewal)} unless notice of non-renewal is sent by "
        f"{_fmt(deadline)} ({notice} days before the term ends).",
    )


def _source(contract: Contract) -> SourceContract:
    return SourceContract(
        id=contract.id, contract_type=contract.contract_type,
        title=contract.title, effective_date=contract.effective_date,
    )


def get_deadlines(
    session: Session,
    within_days: int | None = None,
    counterparty_id: int | None = None,
    today: date | None = None,
) -> Deadlines:
    """Every active contract's next deadline, soonest first."""
    today = today or date.today()
    query = (
        select(Contract)
        .where(Contract.status == "active", Contract.contract_type.in_(TRACKED_TYPES))
        .options(
            selectinload(Contract.counterparty),
            selectinload(Contract.clauses).selectinload(Clause.terms),
            selectinload(Contract.amendments).selectinload(Contract.clauses).selectinload(Clause.terms),
        )
        .order_by(Contract.effective_date)
    )
    if counterparty_id is not None:
        query = query.where(Contract.counterparty_id == counterparty_id)

    rows: list[DeadlineRow] = []
    needs_review: list[str] = []
    no_term: list[str] = []
    for contract in session.scalars(query):
        label = f"{contract.counterparty.name}: {contract.title}"

        # An amendment that changes the term wins over the original, newest first
        candidates = [
            (c, owner)
            for owner in sorted(contract.amendments, key=lambda a: a.effective_date, reverse=True) + [contract]
            for c in owner.clauses
            if c.clause_type == "term_renewal" and c.presence == "present"
        ]
        reviewed = next(((c, o) for c, o in candidates if c.review_status in REVIEWED), None)
        if reviewed is None:
            if any(c.review_status == "pending" for c, _ in candidates):
                needs_review.append(label)
            elif contract.contract_type in ("MSA", "NDA"):
                no_term.append(label)
            continue

        clause, owner = reviewed
        values = {t.term_key: t.value for t in clause.terms}
        schedule = work_out(contract.effective_date, values, today)
        if schedule.status == "ends_on_event" and contract.contract_type in ("SOW", "change_order"):
            continue  # normal for project work; listing every SOW would bury the real deadlines
        days = (schedule.action_date - today).days if schedule.action_date else None
        if within_days is not None and (days is None or days > within_days):
            continue
        rows.append(DeadlineRow(
            counterparty_id=contract.counterparty_id,
            counterparty_name=contract.counterparty.name,
            source=_source(contract),
            term_source=_source(owner),
            clause_id=clause.id,
            status=schedule.status,
            term_end=schedule.term_end,
            notice_deadline=schedule.notice_deadline,
            action_date=schedule.action_date,
            days_until=days,
            auto_renews=values.get("auto_renews") if isinstance(values.get("auto_renews"), bool) else None,
            summary=schedule.summary,
        ))

    rows.sort(key=lambda r: (r.action_date is None, r.action_date or date.max))
    return Deadlines(
        as_of=today, within_days=within_days, rows=rows,
        needs_review=needs_review, no_term_on_file=no_term,
    )


if __name__ == "__main__":
    from nonna.database import SessionLocal
    from nonna.extraction import add_term_renewal

    with SessionLocal() as session:
        added = 0
        for contract in session.scalars(select(Contract).order_by(Contract.id)):
            if add_term_renewal(session, contract):
                added += 1
                print(f"Pulled the term from {contract.title} (waiting for review)")
        print(f"{added} contract(s) updated. Review them in the Review tab.")