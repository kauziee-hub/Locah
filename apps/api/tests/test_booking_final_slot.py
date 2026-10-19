"""The last place — genuinely concurrent customers, through the real booking path.

Every test here sends several requests for the one remaining place at the same
moment, each on its own connection, through the same API a website, WhatsApp
or the front desk uses. Exactly one may win; the others must be told the slot
is taken (409), never a 500 and never a second confirmed booking.

Covered separately because they are guarded by different mechanisms:

* an exclusive resource (a table) the guest did not choose — the booking is
  given a free one under lock, or refused;
* a provider (exclusion constraint on the provider's allocations);
* a pooled resource's last seat (advisory lock + sum);
* a class with no resource configured, whose places per session are set on the
  class itself (advisory lock + sum on the booking rows) — including a request
  that names the instructor racing one that does not.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import jwt
import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.db import get_database_url
from platform_testing.db_helpers import ensure_auth_user
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")

TEST_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
CONTENDERS = 4
client = TestClient(app)


def _url() -> str:
    url = get_database_url()
    assert url
    return str(url).replace("postgresql://", "postgresql+asyncpg://", 1)


def _sql(query: str, **params: Any) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_async_engine(_url(), poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return list((await conn.execute(text(query), params)).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    return owner_headers(monkeypatch)


def owner_headers(monkeypatch: Any) -> dict[str, str]:
    """A signed-in owner with no business yet (shared with test_booking_schedules)."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"

    async def seed() -> None:
        engine = create_async_engine(_url(), poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await ensure_auth_user(session, user_id, email)
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())
    token = jwt.encode({"sub": str(user_id), "email": email,
                        "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _business(owner: dict[str, str]) -> tuple[str, str, str]:
    """A business taking bookings from the public: (id, slug, primary location)."""
    r = client.post("/v1/platform/businesses", json={"display_name": f"Last place {uuid.uuid4().hex[:6]}",
                                                     "business_type": "salon"}, headers=owner)
    assert r.status_code == 200, r.text
    business = r.json()["data"]["business"]
    bid, slug = business["id"], business["slug"]
    for mid in ("workforce", "bookings", "offerings-catalog", "payments"):
        assert client.post(f"/v1/b/{bid}/modules/{mid}/enable", headers=owner).status_code == 200
    assert client.post(f"/v1/b/{bid}/marketplace/visibility", json={"visibility": "unlisted"},
                       headers=owner).status_code == 200
    locs = client.get(f"/v1/platform/businesses/{bid}/locations", headers=owner).json()["data"]
    return bid, slug, next(loc["id"] for loc in locs if loc["is_primary"])


def _offering(owner: dict[str, str], bid: str, kind: str, **attributes: Any) -> str:
    r = client.post(f"/v1/platform/businesses/{bid}/products",
                    json={"title": f"{kind} {uuid.uuid4().hex[:6]}", "offering_type": kind, "status": "active",
                          "visibility": "public", "price_amount": 300, "attributes": attributes},
                    headers=owner)
    assert r.status_code == 200, r.text
    return cast(str, r.json()["data"]["id"])


def _resource(owner: dict[str, str], bid: str, loc: str, **body: Any) -> str:
    r = client.post(f"/v1/platform/businesses/{bid}/bookings/resources",
                    json={"location_id": loc, **body}, headers=owner)
    assert r.status_code == 200, r.text
    return cast(str, r.json()["data"]["id"])


def _provider(owner: dict[str, str], bid: str, loc: str, *offerings: str) -> str:
    r = client.post(f"/v1/platform/businesses/{bid}/workforce/members",
                    json={"display_name": f"Priya {uuid.uuid4().hex[:4]}", "location_ids": [loc],
                          "primary_location_id": loc, "offering_ids": list(offerings)}, headers=owner)
    assert r.status_code == 200, r.text
    return cast(str, r.json()["data"]["id"])


def _slot(days: int, hours: int = 1) -> tuple[str, str]:
    start = (datetime.now(timezone.utc) + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(hours=hours)).isoformat()


def _race(requests: list[tuple[str, dict[str, Any], dict[str, str]]]) -> list[tuple[int, str]]:
    """Send every request at once, each on its own connection; (status, body) in order."""
    from httpx import ASGITransport, AsyncClient

    async def go() -> list[tuple[int, str]]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async def one(path: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, str]:
                r = await ac.post(path, json=body, headers=headers)
                return r.status_code, r.text

            return list(await asyncio.gather(*(one(p, b, h) for p, b, h in requests)))

    return asyncio.run(go())


def _guest(i: int) -> dict[str, Any]:
    return {"name": f"Guest {i}", "email": f"guest-{i}-{uuid.uuid4().hex[:6]}@example.com"}


def _one_winner(outcomes: list[tuple[int, str]]) -> None:
    codes = sorted(code for code, _ in outcomes)
    assert codes == [200] + [409] * (len(outcomes) - 1), outcomes


def _active(bid: str, **where: str) -> list[Any]:
    clause = " ".join(f"and {k} = :{k}" for k in where)
    return _sql("select id, party_size from bookings_bookings where business_id = :b "
                f"and status in ('pending', 'confirmed', 'checked_in') and deleted_at is null {clause}",
                b=bid, **where)


# ------------------------------------------------------------------ class seats


def test_the_last_class_place_goes_to_exactly_one_guest(owner: dict[str, str]) -> None:
    """A class with three places set on the class itself and no resource. Two
    are booked at the desk; four guests reach for the last one at once."""
    bid, slug, loc = _business(owner)
    yoga = _offering(owner, bid, "class_session", capacity=3, duration_minutes=60)
    starts, ends = _slot(days=3)
    for i in range(2):
        r = client.post(f"/v1/platform/businesses/{bid}/bookings",
                        json={"location_id": loc, "offering_id": yoga, "reservation_mode": "class_session",
                              "starts_at": starts, "ends_at": ends, "title": f"Desk {i}"}, headers=owner)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["capacity"] == 3, "the class's own places, not the request's"

    outcomes = _race([(f"/v1/public/websites/{slug}/bookings",
                       {"location_id": loc, "offering_id": yoga, "reservation_mode": "class_session",
                        "starts_at": starts, "ends_at": ends, "guest": _guest(i)}, {})
                      for i in range(CONTENDERS)])
    _one_winner(outcomes)
    assert sum(size for _, size in _active(bid, offering_id=yoga)) == 3, "never more people than places"
    assert all("Capacity exceeded" in body for code, body in outcomes if code == 409)

    # The website and WhatsApp see it full too — the same number, no capacity sent.
    avail = client.post(f"/v1/public/websites/{slug}/booking/availability",
                        json={"location_id": loc, "offering_id": yoga, "reservation_mode": "class_session",
                              "starts_at": starts, "ends_at": ends})
    assert avail.status_code == 200 and avail.json()["data"]["available"] is False, avail.text

    # The desk cannot lift the class's limit by sending a bigger one.
    over = client.post(f"/v1/platform/businesses/{bid}/bookings",
                       json={"location_id": loc, "offering_id": yoga, "reservation_mode": "class_session",
                             "starts_at": starts, "ends_at": ends, "title": "Squeeze in", "capacity": 10},
                       headers=owner)
    assert over.status_code == 409, over.text


def test_naming_the_instructor_does_not_open_a_second_queue_for_the_last_place(owner: dict[str, str]) -> None:
    """One request names the instructor, the other does not: they used to
    serialise on different locks, so both could see one place left."""
    bid, _, loc = _business(owner)
    spin = _offering(owner, bid, "class_session", capacity=1, duration_minutes=45)
    trainer = _provider(owner, bid, loc, spin)
    starts, ends = _slot(days=4)
    base = {"location_id": loc, "offering_id": spin, "reservation_mode": "class_session",
            "starts_at": starts, "ends_at": ends, "title": "Spin"}
    for _ in range(3):  # repeated so an unlucky interleaving has several chances to show
        outcomes = _race([(f"/v1/platform/businesses/{bid}/bookings", {**base, "provider_id": trainer}, owner),
                          (f"/v1/platform/businesses/{bid}/bookings", base, owner)])
        assert sorted(code for code, _ in outcomes) in ([200, 409], [409, 409]), outcomes
    assert len(_active(bid, offering_id=spin)) == 1


# ------------------------------------------------------------------ pooled seats


def test_the_last_pooled_seat_goes_to_exactly_one_guest(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    studio = _resource(owner, bid, loc, resource_type="studio", name="Studio", allocation_mode="pooled",
                       capacity=2)
    starts, ends = _slot(days=5)
    first = client.post(f"/v1/public/websites/{slug}/bookings",
                        json={"location_id": loc, "reservation_mode": "class_session", "title": "Pilates",
                              "starts_at": starts, "ends_at": ends, "resource_ids": [studio],
                              "guest": _guest(99)})
    assert first.status_code == 200, first.text

    outcomes = _race([(f"/v1/public/websites/{slug}/bookings",
                       {"location_id": loc, "reservation_mode": "class_session", "title": "Pilates",
                        "starts_at": starts, "ends_at": ends, "resource_ids": [studio], "guest": _guest(i)}, {})
                      for i in range(CONTENDERS)])
    _one_winner(outcomes)
    [(seats,)] = _sql("select coalesce(sum(quantity), 0) from bookings_booking_allocations "
                      "where resource_id = :r and released_at is null", r=studio)
    assert seats == 2


# ------------------------------------------------------------- exclusive table


def test_a_guest_who_names_no_table_is_given_a_free_one_or_refused(owner: dict[str, str]) -> None:
    """The website never asks which table. The booking must still hold one —
    otherwise every guest 'gets' the restaurant's only table."""
    bid, slug, loc = _business(owner)
    table = _resource(owner, bid, loc, resource_type="table", name="Table 1", allocation_mode="exclusive",
                      capacity=1, max_party_size=4)
    starts, ends = _slot(days=6, hours=2)
    body = {"location_id": loc, "reservation_mode": "table", "title": "Dinner", "starts_at": starts,
            "ends_at": ends, "party_size": 2}

    outcomes = _race([(f"/v1/public/websites/{slug}/bookings", {**body, "guest": _guest(i)}, {})
                      for i in range(CONTENDERS)])
    _one_winner(outcomes)
    winner = next(b for code, b in outcomes if code == 200)
    booking_id = json.loads(winner)["data"]["id"]
    assert _sql("select resource_id::text from bookings_booking_allocations where booking_id = :b "
                "and released_at is null", b=booking_id) == [(table,)], "the winner holds the table"
    assert len(_active(bid)) == 1

    # A party the only table cannot seat is refused, not squeezed in.
    too_big = client.post(f"/v1/public/websites/{slug}/bookings",
                          json={**body, "starts_at": _slot(days=7)[0], "ends_at": _slot(days=7, hours=2)[1],
                                "party_size": 6, "guest": _guest(7)})
    assert too_big.status_code == 409, too_big.text

    # Cancelling frees the table for the next guest.
    token = json.loads(winner)["data"]["management_token"]
    cancel = client.post(f"/v1/public/bookings/{booking_id}/cancel", json={"token": token, "reason": "Plans changed"})
    assert cancel.status_code == 200, cancel.text
    again = client.post(f"/v1/public/websites/{slug}/bookings", json={**body, "guest": _guest(8)})
    assert again.status_code == 200, again.text


# ---------------------------------------------------------------- provider


def test_the_providers_last_slot_goes_to_exactly_one_guest(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    stylist = _provider(owner, bid, loc)
    starts, ends = _slot(days=8)
    outcomes = _race([(f"/v1/public/websites/{slug}/bookings",
                       {"location_id": loc, "provider_id": stylist, "reservation_mode": "appointment",
                        "title": "Haircut", "starts_at": starts, "ends_at": ends, "guest": _guest(i)}, {})
                      for i in range(CONTENDERS)])
    _one_winner(outcomes)
    assert len(_active(bid, provider_id=stylist)) == 1


# ------------------------------------------------------------------ anyone available


def test_anyone_available_takes_the_only_free_stylist_and_then_refuses(owner: dict[str, str]) -> None:
    """Owner lab (salon): with one stylist for a haircut, "anyone available"
    was offered and booked at a time the stylist already had, and an
    unassigned booking never took anyone's time — two guests at one chair."""
    bid, slug, loc = _business(owner)
    cut = _offering(owner, bid, "service", duration_minutes=45)
    farhan = _provider(owner, bid, loc, cut)
    starts, ends = _slot(days=4)
    body = {"location_id": loc, "offering_id": cut, "reservation_mode": "appointment",
            "starts_at": starts, "ends_at": ends}

    first = client.post(f"/v1/public/websites/{slug}/bookings", json={**body, "guest": _guest(1)})
    assert first.status_code == 200, first.text
    # "Anyone available" went to the person who gives the service: it holds their time.
    assert _sql("select provider_id::text from bookings_bookings where id = cast(:i as uuid)",
                i=first.json()["data"]["id"])[0][0] == farhan

    avail = client.post(f"/v1/public/websites/{slug}/booking/availability", json=body)
    assert avail.status_code == 200 and avail.json()["data"]["available"] is False, avail.text
    second = client.post(f"/v1/public/websites/{slug}/bookings", json={**body, "guest": _guest(2)})
    assert second.status_code == 409, second.text
    named = client.post(f"/v1/public/websites/{slug}/bookings",
                        json={**body, "provider_id": farhan, "guest": _guest(3)})
    assert named.status_code == 409, named.text
    assert len(_active(bid, offering_id=cut)) == 1

    # A service nobody is named for is booked as before (no person to check).
    other = _offering(owner, bid, "service", duration_minutes=30)
    plain = {**body, "offering_id": other}
    assert client.post(f"/v1/public/websites/{slug}/bookings", json={**plain, "guest": _guest(4)}).status_code == 200


def test_anyone_available_races_for_the_last_stylist_one_wins(owner: dict[str, str]) -> None:
    bid, slug, loc = _business(owner)
    cut = _offering(owner, bid, "service", duration_minutes=45)
    _provider(owner, bid, loc, cut)
    starts, ends = _slot(days=5)
    outcomes = _race([(f"/v1/public/websites/{slug}/bookings",
                       {"location_id": loc, "offering_id": cut, "reservation_mode": "appointment",
                        "starts_at": starts, "ends_at": ends, "guest": _guest(i)}, {})
                      for i in range(CONTENDERS)])
    _one_winner(outcomes)
    assert len(_active(bid, offering_id=cut)) == 1
