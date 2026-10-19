"""A hotel's rooms are of a room type, and a stay gets a room of the type booked.

Owner lab (hotel): rooms were not tied to room types, so a Pool villa stay
could be given the Valley-view cottage, and the one villa could be sold as
often as the estate had free rooms of any kind.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from test_booking_final_slot import _business, _guest, _offering, _resource, _sql, client, owner_headers
from test_booking_modes import _range

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    return cast(dict[str, str], owner_headers(monkeypatch))


def _day(days: int) -> str:
    return (datetime.now(IST).date() + timedelta(days=days)).isoformat()


def test_a_stay_gets_a_room_of_the_type_booked_and_never_another(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    cottage = _offering(owner, bid, "accommodation", max_guests=2)
    villa = _offering(owner, bid, "accommodation", max_guests=2)
    cottage_1 = _resource(owner, bid, loc, resource_type="cottage", name="Cottage 1", allocation_mode="exclusive",
                          capacity=1, max_party_size=2, metadata={"offering_ids": [cottage]})
    villa_1 = _resource(owner, bid, loc, resource_type="villa", name="Villa 1", allocation_mode="exclusive",
                        capacity=1, max_party_size=2, metadata={"offering_ids": [villa]})
    nights = {"check_in": _day(10), "check_out": _day(12), "party_size": 2}

    # Each room type offers only its own rooms.
    v = _range(slug, location_id=loc, offering_id=villa, **nights)
    assert v["available"] is True and [r["name"] for r in v["resources"]] == ["Villa 1"]
    c = _range(slug, location_id=loc, offering_id=cottage, **nights)
    assert [r["name"] for r in c["resources"]] == ["Cottage 1"]

    def book(offering: str, i: int, **extra: Any) -> Any:
        return client.post(f"/v1/public/websites/{slug}/bookings",
                           json={"location_id": loc, "offering_id": offering, "starts_at": v["starts_at"],
                                 "ends_at": v["ends_at"], "party_size": 2, "guest": _guest(i), **extra})

    first = book(villa, 1)
    assert first.status_code == 200, first.text
    assert _sql("select resource_id::text from bookings_booking_allocations where booking_id = :b "
                "and released_at is null", b=first.json()["data"]["id"]) == [(villa_1,)]
    # The owner sees which room the guest is in, and what the stay comes to.
    seen = client.get(f"/v1/platform/businesses/{bid}/bookings/{first.json()['data']['id']}", headers=owner).json()["data"]
    assert seen["resource_names"] == ["Villa 1"] and seen["total_amount"] == 600.0, "two nights at 300"

    # The only villa is taken: a second villa stay is refused, though a cottage is free.
    again = _range(slug, location_id=loc, offering_id=villa, **nights)
    assert again["available"] is False
    second = book(villa, 2)
    assert second.status_code == 409, second.text
    assert _range(slug, location_id=loc, offering_id=cottage, **nights)["available"] is True

    # A guest cannot pick the cottage for a villa stay either.
    picked = book(villa, 3, resource_ids=[cottage_1])
    assert picked.status_code in (400, 422), picked.text

    # The cottage is still the cottage's.
    third = book(cottage, 4)
    assert third.status_code == 200, third.text
    assert _sql("select resource_id::text from bookings_booking_allocations where booking_id = :b "
                "and released_at is null", b=third.json()["data"]["id"]) == [(cottage_1,)]


def test_a_room_that_names_no_room_type_still_takes_any_stay(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    room_type = _offering(owner, bid, "accommodation", max_guests=2)
    _resource(owner, bid, loc, resource_type="room", name="Room 101", allocation_mode="exclusive", capacity=1,
              max_party_size=2)
    stay = _range(slug, location_id=loc, offering_id=room_type, check_in=_day(15), check_out=_day(16))
    assert [r["name"] for r in stay["resources"]] == ["Room 101"]


def _next(weekday: int, after_days: int = 7) -> datetime:
    d = datetime.now(IST).date() + timedelta(days=after_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=IST)


def test_a_stay_keeps_the_room_types_check_in_and_weekend_minimum(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    villa = _offering(owner, bid, "accommodation", max_guests=2, check_in="13:00", check_out="11:00",
                      weekend_min_nights=2)
    _resource(owner, bid, loc, resource_type="villa", name="Villa 1", allocation_mode="exclusive", capacity=1,
              max_party_size=2, metadata={"offering_ids": [villa]})
    sat, mon = _next(5), _next(0)

    one = _range(slug, location_id=loc, offering_id=villa, check_in=sat.date().isoformat(),
                 check_out=(sat + timedelta(days=1)).date().isoformat())
    assert one["available"] is False and one["reason"] == "A stay over a Friday or Saturday night is at least 2 nights"
    two = _range(slug, location_id=loc, offering_id=villa, check_in=sat.date().isoformat(),
                 check_out=(sat + timedelta(days=2)).date().isoformat())
    assert two["available"] is True
    assert datetime.fromisoformat(two["starts_at"]).astimezone(IST).hour == 13, "check-in from 1 pm, as the owner said"

    # Asked for anyway: one Saturday night is refused, in the guest's words.
    r = client.post(f"/v1/public/websites/{slug}/bookings",
                    json={"location_id": loc, "offering_id": villa, "starts_at": (sat + timedelta(hours=13)).isoformat(),
                          "ends_at": (sat + timedelta(days=1, hours=11)).isoformat(), "guest": _guest(1)})
    assert r.status_code in (400, 422), r.text
    assert "at least 2 nights" in r.text

    # A weekday night is fine, and a crafted 6 am "check-in" becomes the room's 1 pm.
    ok = client.post(f"/v1/public/websites/{slug}/bookings",
                     json={"location_id": loc, "offering_id": villa, "starts_at": (mon + timedelta(hours=6)).isoformat(),
                           "ends_at": (mon + timedelta(days=1, hours=6)).isoformat(), "guest": _guest(2)})
    assert ok.status_code == 200, ok.text
    data = ok.json()["data"]
    assert datetime.fromisoformat(data["starts_at"]).astimezone(IST).hour == 13
    assert datetime.fromisoformat(data["ends_at"]).astimezone(IST).hour == 11


def test_a_room_type_list_must_be_offering_ids(owner: dict[str, str]) -> None:
    bid, _, loc = _business(owner)
    r = client.post(f"/v1/platform/businesses/{bid}/bookings/resources",
                    json={"location_id": loc, "resource_type": "room", "name": "Room 9", "allocation_mode": "exclusive",
                          "capacity": 1, "metadata": {"offering_ids": ["pool villa"]}}, headers=owner)
    assert r.status_code in (400, 422), r.text
