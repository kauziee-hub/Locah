"""A guest's own cancel or move is the guest's, not the owner's.

Owner lab (salon): a guest cancelled from their booking link and the
booking's history named the owner as the person who did it, so the owner
read their customer's cancellation as their own action.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from test_booking_final_slot import _business, _guest, _offering, _sql, client, owner_headers
from test_booking_modes import _open_all_week, _slots

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    return cast(dict[str, str], owner_headers(monkeypatch))


def _last_history(booking_id: str) -> tuple[Any, ...]:
    rows = _sql("select to_status, actor_identity_id from bookings_booking_status_history "
                "where booking_id = :b order by created_at desc limit 1", b=booking_id)
    return tuple(rows[0])


def _audit_context(booking_id: str, action: str) -> list[Any]:
    return [r[0] for r in _sql("select actor_context from platform_audit_events where resource_type = 'booking' "
                               "and resource_id = :b and action = :a", b=booking_id, a=action)]


def test_a_guests_own_cancel_and_move_are_not_recorded_as_the_owners(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    _open_all_week(owner, bid, loc)
    cut = _offering(owner, bid, "service", duration_minutes=60)
    day = (datetime.now(IST) + timedelta(days=4)).date().isoformat()
    slots = _slots(slug, location_id=loc, offering_id=cut, date=day)["slots"]
    owner_id = _sql("select primary_owner_identity_id from businesses where id = :b", b=bid)[0][0]

    def book(slot: dict[str, Any], i: int) -> dict[str, Any]:
        r = client.post(f"/v1/public/websites/{slug}/bookings",
                        json={"location_id": loc, "offering_id": cut, "starts_at": slot["starts_at"],
                              "ends_at": slot["ends_at"], "guest": _guest(i)})
        assert r.status_code == 200, r.text
        return cast(dict[str, Any], r.json()["data"])

    first, second, third = book(slots[0], 1), book(slots[2], 2), book(slots[4], 3)

    cancel = client.post(f"/v1/public/bookings/{first['id']}/cancel",
                         json={"token": first["management_token"], "reason": "Plans changed"})
    assert cancel.status_code == 200, cancel.text
    status, actor = _last_history(first["id"])
    assert status == "cancelled" and actor is None, "a guest without an account: nobody named, never the owner"
    assert _sql("select cancelled_by from bookings_bookings where id = :b", b=first["id"]) == [(None,)]
    assert _audit_context(first["id"], "cancelled") == ["website_guest"]

    later = slots[6]
    moved = client.post(f"/v1/public/bookings/{second['id']}/reschedule",
                        json={"token": second["management_token"], "starts_at": later["starts_at"],
                              "ends_at": later["ends_at"]})
    assert moved.status_code == 200, moved.text
    assert _last_history(second["id"])[1] is None
    assert _audit_context(second["id"], "rescheduled") == ["website_guest"]

    # The owner's own cancellation still names the owner.
    mine = client.post(f"/v1/platform/businesses/{bid}/bookings/{third['id']}/status",
                       json={"status": "cancelled", "reason": "Stylist off sick"}, headers=owner)
    assert mine.status_code == 200, mine.text
    assert _last_history(third["id"]) == ("cancelled", owner_id)
    assert _audit_context(third["id"], "cancelled") == ["business"]

    # And the owner reads who did what in the booking's history.
    def by(booking_id: str) -> list[tuple[str, str]]:
        r = client.get(f"/v1/platform/businesses/{bid}/bookings/{booking_id}/history", headers=owner)
        assert r.status_code == 200, r.text
        return [(h["to_status"], h["by"]) for h in r.json()["data"] if h["from_status"]]

    assert by(first["id"]) == [("cancelled", "customer")]
    assert by(second["id"]) == [("pending", "customer")], "the guest moved it"
    assert by(third["id"]) == [("cancelled", "team")]
