"""The top of Workspace Home: greeting, place, open state from saved hours
only, and quick actions limited to tools that are on and what the viewer may do."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from platform_core.services.home_header import greeting, open_state, place, quick_actions

IST = ZoneInfo("Asia/Kolkata")
WEEK = {d: [["09:00", "22:00"]] for d in ("mon", "tue", "wed", "thu", "fri")}
WEEKEND = {"sat": [["10:00", "23:00"]], "sun": [["10:00", "23:00"]]}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """2026-10-05 is a Monday; `day` 0..6 from there, local IST time, as UTC."""
    return datetime(2026, 10, 5 + day, hour, minute, tzinfo=IST).astimezone(timezone.utc)


def test_greeting_follows_local_time() -> None:
    assert greeting(datetime(2026, 10, 5, 8, tzinfo=IST)) == "Good morning"
    assert greeting(datetime(2026, 10, 5, 14, tzinfo=IST)) == "Good afternoon"
    assert greeting(datetime(2026, 10, 5, 19, tzinfo=IST)) == "Good evening"
    assert greeting(datetime(2026, 10, 5, 2, tzinfo=IST)) == "Good evening"


def test_place_prefers_the_area_and_skips_the_default_name() -> None:
    assert place("Primary Location", {"locality": "Anna Nagar", "city": "Chennai"}) == "Anna Nagar"
    assert place("Primary Location", {"country": "IN"}) == ""
    assert place("T. Nagar branch", None) == "T. Nagar branch"


def test_no_hours_saved_says_so_instead_of_guessing() -> None:
    assert open_state(None, "Asia/Kolkata", at(0, 12)) == {"state": "unknown", "text": "Opening hours not set"}
    assert open_state({"note": "by appointment"}, "Asia/Kolkata", at(0, 12))["state"] == "unknown"


def test_open_and_closed_with_weekend_hours() -> None:
    hours = {**WEEK, **WEEKEND}
    assert open_state(hours, "Asia/Kolkata", at(0, 12)) == {"state": "open", "text": "Open now · closes 10 pm"}
    assert open_state(hours, "Asia/Kolkata", at(0, 23)) == {"state": "closed", "text": "Closed · opens 9 am tomorrow"}
    assert open_state(hours, "Asia/Kolkata", at(0, 7, 30)) == {"state": "closed", "text": "Closed · opens 9 am"}
    # Friday night: Saturday opens later.
    assert open_state(hours, "Asia/Kolkata", at(4, 22, 30))["text"] == "Closed · opens 10 am tomorrow"
    assert open_state(hours, "Asia/Kolkata", at(5, 22))["text"] == "Open now · closes 11 pm"


def test_closed_days_and_overnight_and_split_spans() -> None:
    # Closed Sunday: Saturday night says the day it opens.
    hours = {"mon": [["09:00", "18:00"]], "sat": [["09:00", "18:00"]]}
    assert open_state(hours, "Asia/Kolkata", at(5, 20))["text"] == "Closed · opens 9 am Monday"
    # A bar open past midnight is still open at 1 am the next day.
    bar = {"fri": [["18:00", "02:00"]]}
    assert open_state(bar, "Asia/Kolkata", at(5, 1)) == {"state": "open", "text": "Open now · closes 2 am"}
    # Lunch break: closed between spans; back-to-back spans read as one.
    split = {"mon": [["09:00", "13:00"], ["14:00", "21:30"]]}
    assert open_state(split, "Asia/Kolkata", at(0, 13, 30))["text"] == "Closed · opens 2 pm"
    joined = {"mon": [["09:00", "12:00"], ["12:00", "21:30"]]}
    assert open_state(joined, "Asia/Kolkata", at(0, 10))["text"] == "Open now · closes 9:30 pm"
    # Midnight close.
    assert open_state({"mon": [["18:00", "00:00"]]}, "Asia/Kolkata", at(0, 19))["text"] == "Open now · closes midnight"


def test_quick_actions_need_the_tool_on_and_the_permission() -> None:
    owner = {"orders.create", "offerings.create", "website.edit", "invoices.issue", "leads.create"}
    on = {"orders", "offerings-catalog", "leads"}

    def can(perm: str, module: str | None = None) -> bool:
        return perm in owner and (module is None or module in on)

    labels = [a["label"] for a in quick_actions(can)]
    assert labels == ["New order", "Add an enquiry", "Add an item", "Edit your website"]  # Invoices is off
    assert quick_actions(lambda perm, module=None: False) == []
