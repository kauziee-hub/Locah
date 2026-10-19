"""The recurring relationship's state, computed — never stored by hand.

Founder refinement — Memberships §3–§5: PENDING_PAYMENT, ACTIVE, PAUSED, GRACE,
EXPIRED, CANCELLED (plus COMPLETED for a finished course), recalculated from
what actually happened: which periods are paid, which freezes cover today,
which instalments are open, how many sessions are left. "Expiring soon" is a
derived condition, not a state.

Pure: no database, no clock. The service feeds it rows and `now`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

KINDS = ("access", "session_pack", "recurring_delivery", "service_contract", "fee_plan", "member_dues")
COVERED = ("paid", "waived")
EXPIRING_SOON_DAYS = 7


@dataclass(frozen=True)
class PeriodRow:
    id: str
    seq: int
    starts_at: datetime
    ends_at: datetime
    amount: Decimal
    paid_amount: Decimal
    payment_state: str
    sessions_included: int | None = None


@dataclass(frozen=True)
class FreezeRow:
    starts_on: date
    ends_on: date
    kind: str = "freeze"
    status: str = "confirmed"


@dataclass(frozen=True)
class InstalmentRow:
    seq: int
    amount: Decimal
    paid_amount: Decimal
    due_on: date
    status: str


@dataclass(frozen=True)
class State:
    status: str
    reason: str
    valid_until: datetime | None = None
    grace_until: datetime | None = None
    current_period_id: str | None = None
    days_remaining: int | None = None
    expiring_soon: bool = False
    next_due_on: date | None = None
    sessions_remaining: int | None = None
    charged: Decimal = Decimal("0")
    paid: Decimal = Decimal("0")
    outstanding: Decimal = Decimal("0")
    overdue: bool = False
    good_standing: bool | None = None
    starts_later: bool = False
    renewed_ahead: bool = False
    extra: dict[str, object] = field(default_factory=dict)
    # The last day the member is covered, in the business's own days: a 30-day
    # plan from 19 Oct runs through 17 Nov (valid_until is the instant it ends,
    # midnight of 18 Nov — owner lab: the desk said "valid until 18 Nov" and
    # would have turned the member away that morning).
    last_day: date | None = None


def _today(now: datetime, tz: str) -> date:
    return now.astimezone(ZoneInfo(tz)).date()


def paused_on(freezes: list[FreezeRow], day: date) -> FreezeRow | None:
    return next((f for f in freezes if f.status == "confirmed" and f.starts_on <= day <= f.ends_on), None)


def _st(status: str, reason: str, **fields: Any) -> State:
    """A State from computed fields (keeps compute() readable)."""
    return State(status, reason, **fields)


def compute(kind: str, *, now: datetime, tz: str = "Asia/Kolkata", **given: Any) -> State:
    """What this relationship is right now, and why (owner words), with the
    last day it covers."""
    state = _compute(kind, now=now, tz=tz, **given)
    if state.valid_until is None:
        return state
    last = (state.valid_until - timedelta(microseconds=1)).astimezone(ZoneInfo(tz)).date()
    return replace(state, last_day=last)


def _compute(
    kind: str,
    *,
    now: datetime,
    tz: str = "Asia/Kolkata",
    stored_status: str,
    starts_at: datetime,
    ends_at: datetime | None,
    grace_days: int = 0,
    billing_timing: str = "prepaid",
    periods: list[PeriodRow] | None = None,
    freezes: list[FreezeRow] | None = None,
    instalments: list[InstalmentRow] | None = None,
    sessions_used: dict[str, int] | None = None,
) -> State:
    """What this relationship is right now, and why (owner words)."""
    periods = sorted(periods or [], key=lambda p: p.seq)
    freezes = freezes or []
    instalments = sorted(instalments or [], key=lambda i: i.seq)
    used = sessions_used or {}
    today = _today(now, tz)
    live_periods = [p for p in periods if p.payment_state != "cancelled"]
    live_instalments = [i for i in instalments if i.status not in ("cancelled", "waived")]
    charged = sum((p.amount for p in live_periods), Decimal("0")) + sum(
        (i.amount for i in live_instalments), Decimal("0"))
    paid = sum((p.paid_amount for p in live_periods), Decimal("0")) + sum(
        (i.paid_amount for i in live_instalments), Decimal("0"))
    money = {"charged": charged, "paid": paid, "outstanding": max(charged - paid, Decimal("0"))}

    if stored_status in ("cancelled", "completed"):
        return _st(stored_status, "Cancelled" if stored_status == "cancelled" else "Completed", **money)

    # ---------------------------------------------------------------- fee plans
    if kind == "fee_plan":
        open_items = [i for i in live_instalments if i.paid_amount < i.amount]
        next_due = open_items[0].due_on if open_items else None
        overdue = any(i.due_on < today for i in open_items)
        if ends_at is not None and now >= ends_at:
            return _st("completed", "The term has ended", valid_until=ends_at, next_due_on=next_due,
                         overdue=overdue, **money)
        if live_instalments and paid <= 0:
            return _st("pending", "Waiting for the first instalment", valid_until=ends_at, next_due_on=next_due,
                         overdue=overdue, **money)
        # An overdue instalment never removes a student by itself (§16): it is
        # shown and reminded, and the owner decides.
        return _st("active", "Fees overdue" if overdue else "Enrolled", valid_until=ends_at,
                     days_remaining=(ends_at.astimezone(ZoneInfo(tz)).date() - today).days if ends_at else None,
                     next_due_on=next_due, overdue=overdue, **money)

    # ---------------------------------------------------------------- postpaid subscriptions
    if kind == "recurring_delivery" and billing_timing == "postpaid":
        if ends_at is not None and now >= ends_at:
            return _st("expired", "The subscription end date has passed", valid_until=ends_at, **money)
        pause = paused_on(freezes, today)
        if pause is not None:
            return _st("paused", f"Paused until {pause.ends_on.isoformat()}", valid_until=ends_at,
                         starts_later=now < starts_at, **money)
        return _st("active", "Delivering; billed at month end", valid_until=ends_at,
                     starts_later=now < starts_at, **money)

    # ---------------------------------------------------------------- periods of paid cover
    covered = [p for p in live_periods if p.payment_state in COVERED]
    if not covered:
        waiting = next((p for p in live_periods), None)
        return _st("pending", "Waiting for payment", next_due_on=waiting.starts_at.date() if waiting else None,
                     **money)
    valid_until = max(p.ends_at for p in covered)
    current = next((p for p in covered if p.starts_at <= now < p.ends_at), None)
    renewed_ahead = current is not None and any(p.starts_at >= current.ends_at - timedelta(seconds=1)
                                                for p in covered if p.id != current.id)
    grace_until = valid_until + timedelta(days=grace_days) if grace_days else None
    days_remaining = (valid_until.astimezone(ZoneInfo(tz)).date() - today).days
    sessions_remaining = None
    if kind == "session_pack":
        sessions_remaining = sum(max((p.sessions_included or 0) - used.get(p.id, 0), 0)
                                 for p in covered if p.ends_at > now)
    unpaid_next = next((p for p in live_periods if p.payment_state not in COVERED and p.ends_at > now), None)
    next_due = unpaid_next.starts_at.astimezone(ZoneInfo(tz)).date() if unpaid_next else \
        valid_until.astimezone(ZoneInfo(tz)).date()
    base = dict(valid_until=valid_until, grace_until=grace_until, current_period_id=current.id if current else None,
                sessions_remaining=sessions_remaining, next_due_on=next_due, renewed_ahead=renewed_ahead, **money)

    if now < valid_until:
        pause = paused_on(freezes, today)
        if pause is not None:
            return _st("paused", f"Frozen until {pause.ends_on.isoformat()}", days_remaining=days_remaining,
                         good_standing=kind == "member_dues" or None, **base)
        if kind == "session_pack" and sessions_remaining == 0:
            return _st("expired", "All sessions used", days_remaining=days_remaining, **base)
        starts_later = current is None and all(p.starts_at > now for p in covered)
        return _st("active", "Starts later" if starts_later else "Active", days_remaining=days_remaining,
                     expiring_soon=0 <= days_remaining <= EXPIRING_SOON_DAYS and not renewed_ahead,
                     starts_later=starts_later, good_standing=True if kind == "member_dues" else None, **base)
    if grace_until is not None and now < grace_until:
        return _st("grace", f"Ended {valid_until.date().isoformat()}; grace until {grace_until.date().isoformat()}",
                     days_remaining=days_remaining, good_standing=False if kind == "member_dues" else None, **base)
    return _st("expired", "Not renewed" if kind != "member_dues" else "Dues not paid",
                 days_remaining=days_remaining, good_standing=False if kind == "member_dues" else None, **base)


def next_period_window(*, now: datetime, periods: list[PeriodRow], duration_days: int) -> tuple[datetime, datetime]:
    """Where a renewal's period goes (§21): straight after the last period that
    is paid or waiting to be paid — never on top of time already bought."""
    live = [p for p in periods if p.payment_state != "cancelled"]
    start = max([now] + [p.ends_at for p in live])
    return start, start + timedelta(days=duration_days)


def visit_dates(start: date, end: date, *, count: int | None, every_days: int | None) -> list[date]:
    """Preventive visits inside one covered period: every N days, or `count`
    spread evenly (the first a step into the period, never on day one)."""
    span = (end - start).days
    if span <= 0:
        return []
    if every_days:
        out: list[date] = []
        d = start + timedelta(days=every_days)
        while d < end and (count is None or len(out) < count):
            out.append(d)
            d += timedelta(days=every_days)
        return out
    if count:
        step = span / (count + 1)
        return [start + timedelta(days=round(step * (i + 1))) for i in range(count)]
    return []
