"""Bookings follow Workforce's schedules and the location's opening hours.

Workforce owns when a person works (weekly hours, dated leave or one-off hours,
blocks such as lunch); Bookings asks it at commit time on every path, including
a booking that also holds a chair. Guests are held to the opening hours the
owner saved; the desk may still book outside them. A person or a location with
nothing saved is not restricted - nothing is invented.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from test_booking_final_slot import (
    _business,
    _guest,
    _offering,
    _provider,
    _resource,
    client,
    owner_headers,
)

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    return cast(dict[str, str], owner_headers(monkeypatch))


def _next(weekday: int, weeks_ahead: int = 1) -> date:
    today = datetime.now(IST).date()
    return today + timedelta(days=(weekday - today.weekday()) % 7 + 7 * weeks_ahead)


def _at(day: date, hh: int, mm: int = 0, minutes: int = 30) -> tuple[str, str]:
    start = datetime.combine(day, time(hh, mm), IST)
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


def _book(owner: dict[str, str], bid: str, body: dict[str, Any]) -> Any:
    return client.post(f"/v1/platform/businesses/{bid}/bookings", json=body, headers=owner)


def _hours(owner: dict[str, str], bid: str, member: str, **body: Any) -> str:
    r = client.post(f"/v1/platform/businesses/{bid}/workforce/members/{member}/availability", json=body,
                    headers=owner)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["id"])


def _code(response: Any) -> str:
    return str(response.json()["error"]["details"].get("code"))


def test_bookings_take_a_provider_only_when_their_schedule_says_they_work(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    cut = _offering(owner, bid, "service", duration_minutes=30)
    priya = _provider(owner, bid, loc, cut)
    monday, tuesday, sunday = _next(0), _next(1), _next(6)
    _hours(owner, bid, priya, weekday=0, start_time="09:00", end_time="17:00")
    lunch = _hours(owner, bid, priya, weekday=0, start_time="13:00", end_time="14:00", is_available=False)
    base = {"location_id": loc, "offering_id": cut, "provider_id": priya, "reservation_mode": "appointment"}

    def at(day: date, hh: int, mm: int = 0) -> dict[str, Any]:
        starts, ends = _at(day, hh, mm)
        return {**base, "starts_at": starts, "ends_at": ends}

    assert _book(owner, bid, at(monday, 10)).status_code == 200
    late = _book(owner, bid, at(monday, 17, 30))
    assert late.status_code == 409 and _code(late) == "provider_off_duty", late.text
    assert "is not working then" in late.json()["error"]["message"]
    at_lunch = _book(owner, bid, at(monday, 13, 15))
    assert at_lunch.status_code == 409 and _code(at_lunch) == "provider_away", at_lunch.text
    day_off = _book(owner, bid, at(tuesday, 10))
    assert day_off.status_code == 409 and _code(day_off) == "provider_off_duty", day_off.text

    # Leave on one Monday outranks the weekly hours; one-off Sunday hours open a Sunday.
    leave_day = _next(0, weeks_ahead=2)
    _hours(owner, bid, priya, exception_date=leave_day.isoformat(), start_time="00:00", end_time="23:59",
           is_available=False)
    on_leave = _book(owner, bid, at(leave_day, 10))
    assert on_leave.status_code == 409 and _code(on_leave) == "provider_away", on_leave.text
    _hours(owner, bid, priya, exception_date=sunday.isoformat(), start_time="10:00", end_time="12:00")
    assert _book(owner, bid, at(sunday, 10, 30)).status_code == 200

    # The chair path used to skip the provider entirely.
    chair = _resource(owner, bid, loc, resource_type="chair", name="Chair 1", allocation_mode="exclusive",
                      capacity=1)
    with_chair = _book(owner, bid, {**at(monday, 17, 30), "resource_ids": [chair]})
    assert with_chair.status_code == 409 and _code(with_chair) == "provider_off_duty", with_chair.text

    # The website asks the same question.
    starts, ends = _at(monday, 17, 30)
    avail = client.post(f"/v1/public/websites/{slug}/booking/availability",
                        json={"location_id": loc, "offering_id": cut, "provider_id": priya,
                              "reservation_mode": "appointment", "starts_at": starts, "ends_at": ends})
    assert avail.status_code == 200 and avail.json()["data"]["available"] is False, avail.text
    assert "not working" in avail.json()["data"]["reason"]

    # Moving a booking into lunch is refused; taking the block away opens it.
    first = _book(owner, bid, at(monday, 11))
    assert first.status_code == 200, first.text
    starts, ends = _at(monday, 13, 15)
    moved = client.post(f"/v1/platform/businesses/{bid}/bookings/{first.json()['data']['id']}/reschedule",
                        json={"starts_at": starts, "ends_at": ends}, headers=owner)
    assert moved.status_code == 409 and _code(moved) == "provider_away", moved.text
    gone = client.delete(f"/v1/platform/businesses/{bid}/workforce/members/{priya}/availability/{lunch}",
                         headers=owner)
    assert gone.status_code == 200, gone.text
    assert _book(owner, bid, at(monday, 13, 15)).status_code == 200

    # Someone with no hours saved is not restricted.
    free_agent = _provider(owner, bid, loc, cut)
    assert _book(owner, bid, {**at(tuesday, 20), "provider_id": free_agent}).status_code == 200


def test_a_schedule_entry_is_a_weekday_or_a_date_and_starts_before_it_ends(owner: dict[str, str]) -> None:
    bid, _, loc = _business(owner)
    priya = _provider(owner, bid, loc)
    path = f"/v1/platform/businesses/{bid}/workforce/members/{priya}/availability"
    both = client.post(path, json={"weekday": 0, "exception_date": _next(0).isoformat(),
                                   "start_time": "09:00", "end_time": "17:00"}, headers=owner)
    neither = client.post(path, json={"start_time": "09:00", "end_time": "17:00"}, headers=owner)
    backwards = client.post(path, json={"weekday": 0, "start_time": "17:00", "end_time": "09:00"}, headers=owner)
    assert (both.status_code, neither.status_code, backwards.status_code) == (422, 422, 422)


def test_guests_book_inside_opening_hours_and_the_desk_may_book_outside(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    # Public booking needs something real to book (module readiness): here, a
    # person on the rota. With nothing bookable the website offers no "Book"
    # and the public endpoint refuses (test_module_projection).
    _provider(owner, bid, loc)
    r = client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}", json={"hours": {"mon": [["09:00", "18:00"]]}},
                     headers=owner)
    assert r.status_code == 200, r.text
    monday, tuesday = _next(0), _next(1)
    body = {"location_id": loc, "reservation_mode": "appointment", "title": "Consultation"}

    def guest(day: date, hh: int) -> Any:
        starts, ends = _at(day, hh)
        return client.post(f"/v1/public/websites/{slug}/bookings",
                           json={**body, "starts_at": starts, "ends_at": ends, "guest": _guest(hh)})

    ok = guest(monday, 10)
    assert ok.status_code == 200, ok.text
    evening, closed_day = guest(monday, 19), guest(tuesday, 10)
    assert evening.status_code == 409 and _code(evening) == "closed", evening.text
    assert evening.json()["error"]["message"] == "Outside opening hours"
    assert closed_day.status_code == 409 and closed_day.json()["error"]["message"] == "Closed that day"

    starts, ends = _at(monday, 19)
    avail = client.post(f"/v1/public/websites/{slug}/booking/availability",
                        json={"location_id": loc, "reservation_mode": "appointment", "starts_at": starts,
                              "ends_at": ends})
    assert avail.json()["data"] == {"available": False, "reason": "Outside opening hours", "code": "closed",
                                    "resources": []}

    # The guest's own reschedule link is held to the same hours.
    data = ok.json()["data"]
    moved = client.post(f"/v1/public/bookings/{data['id']}/reschedule",
                        json={"token": data["management_token"], "starts_at": starts, "ends_at": ends})
    assert moved.status_code == 409 and _code(moved) == "closed", moved.text

    desk = _book(owner, bid, {**body, "starts_at": starts, "ends_at": ends})
    assert desk.status_code == 200, "the desk can still book after hours"
