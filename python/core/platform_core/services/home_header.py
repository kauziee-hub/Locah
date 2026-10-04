"""The top of Workspace Home: who it is for, where, whether the place is open,
and the few things this person most often starts from here.

Pure functions over what the API already loaded: the Business, its primary
location, the viewer's permissions and the tools that are on. The open state
comes only from saved opening hours — with none saved it says so instead of
guessing.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_AREA_KEYS = ("locality", "area", "neighbourhood", "city")

# (permission, tool or None when always included, Workspace path, label) — in
# the order a busy owner reaches for them. Only tools that are on and actions
# the viewer may take are shown.
QUICK_ACTIONS: tuple[tuple[str, str | None, str, str], ...] = (
    ("orders.create", "orders", "/orders/new", "New order"),
    ("pos.use", "pos", "/pos/shifts", "Open the counter"),
    ("invoices.issue", "invoicing", "/invoices/new", "New bill"),
    ("quotes.create", "quotes", "/quotes/new", "New quotation"),
    ("leads.create", "leads", "/leads#add", "Add an enquiry"),
    ("offerings.create", "offerings-catalog", "/offerings/new", "Add an item"),
    ("customers.update", "customer-relationships", "/customers#add", "Add a customer"),
    ("website.edit", None, "/website", "Edit your website"),
)
MAX_ACTIONS = 4


def greeting(local: datetime) -> str:
    h = local.hour
    return "Good morning" if 4 <= h < 12 else "Good afternoon" if 12 <= h < 17 else "Good evening"


def place(location_name: str | None, address: dict[str, Any] | None) -> str:
    """"Anna Nagar" from the address when there is one; the location's own name
    only when the owner gave it one (not the default "Primary Location")."""
    area = next((str(address[k]).strip() for k in _AREA_KEYS
                 if address and isinstance(address.get(k), str) and address[k].strip()), "")
    if area:
        return area
    name = (location_name or "").strip()
    return "" if name.lower() in ("", "primary location", "main") else name


def _clock(t: time) -> str:
    """09:00 -> "9 am", 22:30 -> "10:30 pm", 00:00 -> "midnight", 12:00 -> "noon"."""
    if t.hour == 0 and t.minute == 0:
        return "midnight"
    if t.hour == 12 and t.minute == 0:
        return "noon"
    h = t.hour % 12 or 12
    return f"{h}{f':{t.minute:02d}' if t.minute else ''} {'am' if t.hour < 12 else 'pm'}"


def _spans(hours: dict[str, Any], day: str) -> list[tuple[time, time]]:
    out = []
    for span in hours.get(day) or []:
        try:
            a, b = (time.fromisoformat(str(x)) for x in span)
        except (TypeError, ValueError):
            continue
        out.append((a, b))
    return sorted(out)


def open_state(hours: dict[str, Any] | None, tz: str | None, now: datetime) -> dict[str, str]:
    """{"state": open|closed|unknown, "text": owner-facing}. Spans are
    {"mon": [["09:00", "22:00"]], ...}; a span that ends before it starts runs
    past midnight."""
    if not hours or not any(hours.get(d) for d in DAYS):
        return {"state": "unknown", "text": "Opening hours not set"}
    try:
        zone = ZoneInfo(tz or "Asia/Kolkata")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Asia/Kolkata")
    local = now.astimezone(zone)
    today = local.date()
    # Every opening from yesterday (an overnight span still running) to a week ahead.
    windows: list[tuple[datetime, datetime]] = []
    for offset in range(-1, 8):
        day = today + timedelta(days=offset)
        for a, b in _spans(hours, DAYS[day.weekday()]):
            start = datetime.combine(day, a, tzinfo=zone)
            end = datetime.combine(day + timedelta(days=1) if b <= a else day, b, tzinfo=zone)
            windows.append((start, end))
    windows.sort()
    for start, end in windows:
        if start <= local < end:
            # Back-to-back spans (lunch break excluded) read as one closing time.
            close = end
            for s2, e2 in windows:
                if s2 == close:
                    close = e2
            return {"state": "open", "text": f"Open now · closes {_clock(close.time())}"}
    upcoming = next((s for s, _ in windows if s > local), None)
    if upcoming is None:
        return {"state": "closed", "text": "Closed"}
    when = upcoming.date()
    day_word = ("" if when == today else " tomorrow" if when == today + timedelta(days=1)
                else f" {upcoming.strftime('%A')}")
    return {"state": "closed", "text": f"Closed · opens {_clock(upcoming.time())}{day_word}"}


def quick_actions(can: Any) -> list[dict[str, str]]:
    """What this person most often starts from Home, given what is on and what they may do."""
    out = [{"label": label, "href": href} for perm, module, href, label in QUICK_ACTIONS if can(perm, module)]
    return out[:MAX_ACTIONS]
