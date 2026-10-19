"""One engine, seven booking modes, as the website asks for them.

Appointment, table, class, stay, rental, site visit and event date: each is
offered through the same options / slots / range answers the commit path
agrees with, and the server - not the request - decides which mode an
offering is booked in.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from platform_testing.phase_b import sql

from test_booking_final_slot import _business, _guest, _offering, _provider, _resource, client, owner_headers

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
IST = ZoneInfo("Asia/Kolkata")
ALL_DAYS = {d: [["09:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    return cast(dict[str, str], owner_headers(monkeypatch))


def _day(days: int = 3) -> date:
    return datetime.now(IST).date() + timedelta(days=days)


def _open_all_week(owner: dict[str, str], bid: str, loc: str) -> None:
    r = client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}", json={"hours": ALL_DAYS}, headers=owner)
    assert r.status_code == 200, r.text


def _slots(slug: str, **body: Any) -> dict[str, Any]:
    r = client.post(f"/v1/public/websites/{slug}/booking/slots", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _range(slug: str, **body: Any) -> dict[str, Any]:
    r = client.post(f"/v1/public/websites/{slug}/booking/range", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _book(slug: str, **body: Any) -> Any:
    return client.post(f"/v1/public/websites/{slug}/bookings", json={"guest": _guest(7), **body})


def test_options_say_how_each_offering_is_booked(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    cut = _offering(owner, bid, "service", duration_minutes=45)
    yoga = _offering(owner, bid, "class_session", capacity=12, duration_minutes=60)
    room = _offering(owner, bid, "accommodation", max_guests=2)
    bike = _offering(owner, bid, "rental")
    hall = _offering(owner, bid, "rental", whole_day=True)
    villa = _offering(owner, bid, "property_project", project_status="Live", location="OMR")
    _resource(owner, bid, loc, resource_type="table", name="T1", allocation_mode="exclusive", capacity=1,
              max_party_size=4)
    _open_all_week(owner, bid, loc)
    data = client.get(f"/v1/public/websites/{slug}/booking/options").json()["data"]
    modes = {o["id"]: o["mode"] for o in data["offerings"]}
    assert modes == {cut: "appointment", yoga: "class_session", room: "accommodation", bike: "rental",
                     hall: "event_date", villa: "site_visit"}
    assert {o["id"]: o["minutes"] for o in data["offerings"]}[cut] == 45
    assert data["table"] == {"tables": 1, "max_party": 4}
    assert data["locations"][0]["hours_known"] is True


def test_slot_modes_list_only_times_the_commit_would_accept(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    _open_all_week(owner, bid, loc)
    day = _day()
    cut = _offering(owner, bid, "service", duration_minutes=60)
    priya = _provider(owner, bid, loc, cut)
    r = client.post(f"/v1/platform/businesses/{bid}/workforce/members/{priya}/availability",
                    json={"weekday": day.weekday(), "start_time": "10:00", "end_time": "13:00"}, headers=owner)
    assert r.status_code == 200, r.text
    labels = [s["label"] for s in _slots(slug, location_id=loc, offering_id=cut, provider_id=priya,
                                         date=day.isoformat())["slots"]]
    assert labels == ["10:00", "10:30", "11:00", "11:30", "12:00"], "only Priya's hours, whole service inside"
    anyone = [s["label"] for s in _slots(slug, location_id=loc, offering_id=cut, date=day.isoformat())["slots"]]
    # "Anyone available" offers only times someone who gives this service works
    # and is free — here only Priya does. (It used to offer the whole opening
    # day, 09:00-17:00, and a 09:00 booking with nobody there was accepted:
    # owner lab, salon.)
    assert anyone == labels, "any provider: the times someone who gives it is free"

    # A class shows places left, and a full time disappears.
    spin = _offering(owner, bid, "class_session", capacity=2, duration_minutes=60)
    first = _slots(slug, location_id=loc, offering_id=spin, date=day.isoformat())["slots"][0]
    assert first["places_left"] == 2
    for i in range(2):
        assert _book(slug, location_id=loc, offering_id=spin, reservation_mode="class_session",
                     starts_at=first["starts_at"], ends_at=first["ends_at"], guest=_guest(i)).status_code == 200
    after = {s["starts_at"]: s for s in _slots(slug, location_id=loc, offering_id=spin, date=day.isoformat())["slots"]}
    assert after[first["starts_at"]]["full"] is True and after[first["starts_at"]]["places_left"] == 0, \
        "a full class time is shown as full (for its waitlist), never as bookable"

    # The class cannot be booked as an "appointment" to slip past its places.
    spoof = _book(slug, location_id=loc, offering_id=spin, reservation_mode="appointment",
                  starts_at=first["starts_at"], ends_at=first["ends_at"])
    assert spoof.status_code == 409, spoof.text

    # Tables: a party only sees times a table that seats it is free.
    _resource(owner, bid, loc, resource_type="table", name="T4", allocation_mode="exclusive", capacity=1,
              max_party_size=4)
    assert _slots(slug, location_id=loc, mode="table", party_size=2, date=day.isoformat())["slots"]
    assert _slots(slug, location_id=loc, mode="table", party_size=6, date=day.isoformat())["slots"] == []

    closed = client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}",
                          json={"hours": {"mon": [["09:00", "18:00"]]}}, headers=owner)
    assert closed.status_code == 200
    sunday = day + timedelta(days=(6 - day.weekday()) % 7 or 7)
    assert _slots(slug, location_id=loc, offering_id=cut, date=sunday.isoformat())["closed"] is True


def test_stays_rentals_and_event_dates_are_checked_as_ranges(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    room_type = _offering(owner, bid, "accommodation", max_guests=2)
    _resource(owner, bid, loc, resource_type="room", name="Room 101", allocation_mode="exclusive", capacity=1,
              max_party_size=2)
    check_in, check_out = _day(5), _day(7)
    stay = _range(slug, location_id=loc, offering_id=room_type, check_in=check_in.isoformat(),
                  check_out=check_out.isoformat(), party_size=2)
    assert stay["available"] is True and [r["name"] for r in stay["resources"]] == ["Room 101"]
    starts = datetime.fromisoformat(stay["starts_at"]).astimezone(IST)
    assert (starts.date(), starts.time()) == (check_in, time(14, 0)), "check-in at 2 pm, local"
    booked = _book(slug, location_id=loc, offering_id=room_type, starts_at=stay["starts_at"],
                   ends_at=stay["ends_at"], party_size=2)
    assert booked.status_code == 200 and booked.json()["data"]["reservation_mode"] == "accommodation"
    assert sql("select total_amount from bookings_bookings where id = :i", i=booked.json()["data"]["id"]) == [
        (Decimal("600.00"),)], "two nights at 300"
    again = _range(slug, location_id=loc, offering_id=room_type, check_in=_day(6).isoformat(),
                   check_out=_day(8).isoformat(), party_size=1)
    assert again["available"] is False, "overlapping nights on the only room"

    hall = _offering(owner, bid, "rental", whole_day=True)
    wedding_day = _day(20)
    free = _range(slug, location_id=loc, offering_id=hall, date=wedding_day.isoformat())
    assert free["available"] is True
    first = _book(slug, location_id=loc, offering_id=hall, starts_at=f"{wedding_day}T10:00:00+05:30",
                  ends_at=f"{wedding_day}T12:00:00+05:30")
    assert first.status_code == 200, first.text
    stored = first.json()["data"]
    assert stored["reservation_mode"] == "event_date"
    assert sql("select count(*) from bookings_booking_allocations where booking_id = :b", b=stored["id"]) == [(0,)], \
        "a hall hire never quietly takes the hotel's room"
    assert _range(slug, location_id=loc, offering_id=room_type, check_in=wedding_day.isoformat(),
                  check_out=(wedding_day + timedelta(days=1)).isoformat())["available"] is True
    assert datetime.fromisoformat(stored["starts_at"]).astimezone(IST).time() == time(0, 0), "the whole day"
    evening = _book(slug, location_id=loc, offering_id=hall, starts_at=f"{wedding_day}T18:00:00+05:30",
                    ends_at=f"{wedding_day}T22:00:00+05:30")
    assert evening.status_code == 409, "one booking per date"
    assert _range(slug, location_id=loc, offering_id=hall, date=wedding_day.isoformat())["available"] is False
    assert _book(slug, location_id=loc, offering_id=hall, starts_at=f"{_day(21)}T10:00:00+05:30",
                 ends_at=f"{_day(21)}T12:00:00+05:30").status_code == 200


def test_a_site_visit_is_a_booking_and_a_lead(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    assert client.post(f"/v1/b/{bid}/modules/leads/enable", headers=owner).status_code == 200
    villa = _offering(owner, bid, "property_project", project_status="Live", location="OMR")
    _open_all_week(owner, bid, loc)
    slot = _slots(slug, location_id=loc, offering_id=villa, date=_day().isoformat())["slots"][0]
    r = _book(slug, location_id=loc, offering_id=villa, starts_at=slot["starts_at"], ends_at=slot["ends_at"],
              notes="Please bring the floor plans", guest={"name": "Kavya", "email": "kavya@example.com",
                                                           "phone": "+919876500301"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["reservation_mode"] == "site_visit" and data["lead_id"]
    leads = client.get(f"/v1/platform/businesses/{bid}/leads", headers=owner).json()["data"]
    lead = next(item for item in leads if item["id"] == data["lead_id"])
    assert lead["display_name"] == "Kavya" and "Site visit booked" in (lead["message"] or "")
    notes = client.get(f"/v1/platform/businesses/{bid}/bookings/{data['id']}/notes", headers=owner).json()["data"]
    assert [n["body"] for n in notes] == ["From the customer: Please bring the floor plans"]


def test_each_kind_of_resource_serves_its_own_kind_of_booking(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    _open_all_week(owner, bid, loc)
    chair = _resource(owner, bid, loc, resource_type="chair", name="Chair 1", allocation_mode="exclusive", capacity=1)
    _resource(owner, bid, loc, resource_type="hall", name="Wedding lawn", allocation_mode="exclusive", capacity=1,
              max_party_size=500)
    facial = _offering(owner, bid, "service", duration_minutes=60)
    slot = _slots(slug, location_id=loc, offering_id=facial, date=_day().isoformat())["slots"][0]
    first = _book(slug, location_id=loc, offering_id=facial, starts_at=slot["starts_at"], ends_at=slot["ends_at"])
    assert first.status_code == 200, first.text
    assert sql("select resource_id::text from bookings_booking_allocations where booking_id = :b",
               b=first.json()["data"]["id"]) == [(chair,)]
    second = _book(slug, location_id=loc, offering_id=facial, starts_at=slot["starts_at"], ends_at=slot["ends_at"],
                   guest=_guest(8))
    assert second.status_code == 409, "the chair is taken; an appointment never takes the wedding lawn"
