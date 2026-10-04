"""Stage 7 — Bookings & Scheduling Kernel tests."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import jwt
import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.db import get_database_url
from platform_core.models import PlatformAuditEvent, PlatformOutboxEvent
from platform_testing.db_helpers import ensure_auth_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def _token(sub: uuid.UUID, email: str) -> str:
    return jwt.encode(
        {
            "sub": str(sub),
            "email": email,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _headers(user_id: uuid.UUID, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, email)}"}


def _seed(user_id: uuid.UUID, email: str) -> None:
    async def _run() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await ensure_auth_user(session, user_id, email)
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


@pytest.fixture
def owner(monkeypatch: Any) -> tuple[dict[str, str], uuid.UUID]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"
    _seed(user_id, email)
    return _headers(user_id, email), user_id


def _enable_booking_modules(
    client: TestClient, headers: dict[str, str], business_id: str
) -> None:
    for mid in ("workforce", "bookings", "offerings-catalog", "payments"):
        resp = client.post(f"/v1/b/{business_id}/modules/{mid}/enable", headers=headers)
        assert resp.status_code == 200, resp.text


def _create_business(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Bookings Co {uuid.uuid4().hex[:8]}", "business_type": "salon"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    business_id = cast(str, resp.json()["data"]["business"]["id"])
    # Gate [7] (Doc 12 SS8.9): optional-module operations require an active module.
    _enable_booking_modules(client, headers, business_id)
    return business_id


def _primary_location_id(client: TestClient, headers: dict[str, str], business_id: str) -> str:
    resp = client.get(f"/v1/platform/businesses/{business_id}/locations", headers=headers)
    assert resp.status_code == 200, resp.text
    for loc in resp.json()["data"]:
        if loc["is_primary"]:
            return cast(str, loc["id"])
    raise AssertionError("primary location missing")


def _slot(hours_ahead: int = 24, duration_hours: int = 1) -> tuple[str, str]:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    end = start + timedelta(hours=duration_hours)
    return start.isoformat(), end.isoformat()


def _create_service(
    client: TestClient, headers: dict[str, str], business_id: str
) -> str:
    resp = client.post(
        f"/v1/platform/businesses/{business_id}/products",
        json={
            "title": f"Consultation {uuid.uuid4().hex[:6]}",
            "offering_type": "service",
            "status": "active",
            "price_amount": 75.0,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return cast(str, resp.json()["data"]["id"])


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_booking_lifecycle(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    offering_id = _create_service(client, headers, business_id)
    starts_at, ends_at = _slot()

    create_resp = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "offering_id": offering_id,
            "reservation_mode": "appointment",
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    booking_id = create_resp.json()["data"]["id"]
    assert create_resp.json()["data"]["status"] == "pending"

    for status in ("confirmed", "checked_in", "completed"):
        resp = client.post(
            f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/status",
            json={"status": status},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    history_resp = client.get(
        f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/history",
        headers=headers,
    )
    assert history_resp.status_code == 200, history_resp.text
    assert history_resp.json()["meta"]["count"] >= 4


def _create_provider(
    client: TestClient,
    headers: dict[str, str],
    business_id: str,
    location_id: str,
    offering_id: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "display_name": f"Provider {uuid.uuid4().hex[:6]}",
        "location_ids": [location_id],
        "primary_location_id": location_id,
    }
    if offering_id:
        payload["offering_ids"] = [offering_id]
    resp = client.post(
        f"/v1/platform/businesses/{business_id}/workforce/members",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return cast(str, resp.json()["data"]["id"])


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_booking_provider_conflict_appointment(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """Appointment: WorkforceMember exclusivity — NOT a capacity/room pool."""
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_booking_modules(client, headers, business_id)
    location_id = _primary_location_id(client, headers, business_id)
    provider_id = _create_provider(client, headers, business_id, location_id)

    starts_at, ends_at = _slot(hours_ahead=48)
    first = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "provider_id": provider_id,
            "reservation_mode": "appointment",
            "title": "First slot",
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text

    overlap_start = (
        datetime.fromisoformat(starts_at.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat()
    overlap_end = (
        datetime.fromisoformat(ends_at.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat()
    second = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "provider_id": provider_id,
            "reservation_mode": "appointment",
            "title": "Overlap slot",
            "starts_at": overlap_start,
            "ends_at": overlap_end,
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_accommodation_date_range_capacity_not_stock(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """Accommodation: overlapping date-range capacity conflict — not inventory decrement."""
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_booking_modules(client, headers, business_id)
    location_id = _primary_location_id(client, headers, business_id)
    starts_at, ends_at = _slot(hours_ahead=24, duration_hours=48)

    first = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "accommodation",
            "title": "Room A",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 1,
            "capacity": 1,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "accommodation",
            "title": "Room B overlap",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 1,
            "capacity": 1,
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_table_capacity_conflict(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_booking_modules(client, headers, business_id)
    location_id = _primary_location_id(client, headers, business_id)
    starts_at, ends_at = _slot(hours_ahead=30)

    first = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "table",
            "title": "Table party 2",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 2,
            "capacity": 4,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "table",
            "title": "Table party 3",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 3,
            "capacity": 4,
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_class_session_capacity_only_no_membership_gate(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """class_session is capacity-only; membership gating is Stage 6."""
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_booking_modules(client, headers, business_id)
    location_id = _primary_location_id(client, headers, business_id)
    starts_at, ends_at = _slot(hours_ahead=36)

    ok = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "class_session",
            "title": "Yoga",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 1,
            "capacity": 2,
        },
        headers=headers,
    )
    assert ok.status_code == 200, ok.text

    ok2 = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "class_session",
            "title": "Yoga guest 2",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 1,
            "capacity": 2,
        },
        headers=headers,
    )
    assert ok2.status_code == 200, ok2.text

    full = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "class_session",
            "title": "Yoga overflow",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": 1,
            "capacity": 2,
        },
        headers=headers,
    )
    assert full.status_code == 409, full.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_concurrent_provider_booking_only_one_succeeds(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_booking_modules(client, headers, business_id)
    location_id = _primary_location_id(client, headers, business_id)
    provider_id = _create_provider(client, headers, business_id, location_id)
    starts_at, ends_at = _slot(hours_ahead=60)

    async def _race() -> list[int]:
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async def _one(i: int) -> int:
                resp = await ac.post(
                    f"/v1/platform/businesses/{business_id}/bookings",
                    json={
                        "location_id": location_id,
                        "provider_id": provider_id,
                        "reservation_mode": "appointment",
                        "title": f"Race {i}",
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "idempotency_key": f"race-{uuid.uuid4()}",
                    },
                    headers=headers,
                )
                return resp.status_code

            return list(await asyncio.gather(_one(1), _one(2)))

    codes = asyncio.run(_race())
    assert sorted(codes) == [200, 409], codes


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_booking_cancel_and_reschedule(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    starts_at, ends_at = _slot(hours_ahead=72)

    booking_id = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "appointment",
            "title": "Reschedule me",
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
        headers=headers,
    ).json()["data"]["id"]

    client.post(
        f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/status",
        json={"status": "confirmed"},
        headers=headers,
    )

    new_start, new_end = _slot(hours_ahead=96)
    reschedule_resp = client.post(
        f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/reschedule",
        json={"starts_at": new_start, "ends_at": new_end, "reason": "Customer request"},
        headers=headers,
    )
    assert reschedule_resp.status_code == 200, reschedule_resp.text
    assert reschedule_resp.json()["data"]["starts_at"] == new_start

    cancel_resp = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "appointment",
            "title": "To cancel",
            "starts_at": _slot(hours_ahead=120)[0],
            "ends_at": _slot(hours_ahead=120)[1],
        },
        headers=headers,
    )
    cancel_id = cancel_resp.json()["data"]["id"]
    cancelled = client.post(
        f"/v1/platform/businesses/{business_id}/bookings/{cancel_id}/cancel",
        json={"reason": "No longer needed"},
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_booking_business_isolation(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_a = _create_business(client, headers)
    business_b = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_a)
    starts_at, ends_at = _slot()

    booking_id = client.post(
        f"/v1/platform/businesses/{business_a}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "appointment",
            "title": "Private",
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
        headers=headers,
    ).json()["data"]["id"]

    denied = client.get(
        f"/v1/platform/businesses/{business_b}/bookings/{booking_id}",
        headers=headers,
    )
    assert denied.status_code == 404, denied.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_booking_audit_and_outbox(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    starts_at, ends_at = _slot(hours_ahead=144)

    booking_id = client.post(
        f"/v1/platform/businesses/{business_id}/bookings",
        json={
            "location_id": location_id,
            "reservation_mode": "appointment",
            "title": "Audit booking",
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
        headers=headers,
    ).json()["data"]["id"]

    note_resp = client.post(
        f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/notes",
        json={"body": "VIP client"},
        headers=headers,
    )
    assert note_resp.status_code == 200, note_resp.text

    async def _assert_events() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            outbox = await session.execute(
                select(PlatformOutboxEvent.event_type).where(
                    PlatformOutboxEvent.business_id == uuid.UUID(business_id),
                    PlatformOutboxEvent.event_type.in_(["booking.created", "booking.note.created"]),
                )
            )
            types = {row[0] for row in outbox.all()}
            assert "booking.created" in types
            assert "booking.note.created" in types
            audit = await session.execute(
                select(PlatformAuditEvent.action).where(
                    PlatformAuditEvent.business_id == uuid.UUID(business_id),
                    PlatformAuditEvent.resource_type == "booking",
                )
            )
            assert "created" in {row[0] for row in audit.all()}
        await engine.dispose()

    asyncio.run(_assert_events())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_bookings_say_who_where_and_with_whom_and_a_refusal_reads_as_words(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """The Workspace shows who a booking is for (and a number to call), where,
    and with whom — read through the customer and workforce modules — and a
    step the booking's state no longer allows is refused in plain words."""
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_booking_modules(client, headers, business_id)
    client.post(f"/v1/b/{business_id}/modules/customer-relationships/enable", headers=headers)
    location_id = _primary_location_id(client, headers, business_id)
    provider_id = _create_provider(client, headers, business_id, location_id)
    contact = client.post(f"/v1/platform/businesses/{business_id}/customers",
                          json={"display_name": "Meena", "phone": "+919840011223"}, headers=headers)
    assert contact.status_code == 200, contact.text
    starts_at, ends_at = _slot(hours_ahead=30)
    made = client.post(f"/v1/platform/businesses/{business_id}/bookings", json={
        "location_id": location_id, "provider_id": provider_id, "reservation_mode": "appointment",
        "title": "Haircut", "starts_at": starts_at, "ends_at": ends_at,
        "customer_contact_id": contact.json()["data"]["id"],
    }, headers=headers)
    assert made.status_code == 200, made.text
    booking_id = made.json()["data"]["id"]

    listed = client.get(f"/v1/platform/businesses/{business_id}/bookings", headers=headers).json()["data"]
    row = next(b for b in listed if b["id"] == booking_id)
    assert row["customer"]["name"] == "Meena" and row["customer"]["phone"] == "+919840011223"
    assert row["provider_name"].startswith("Provider ") and row["location_name"]
    one = client.get(f"/v1/platform/businesses/{business_id}/bookings/{booking_id}", headers=headers).json()["data"]
    assert one["customer"] == row["customer"] and one["provider_name"] == row["provider_name"]

    done = client.post(f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/status",
                       json={"status": "cancelled", "reason": "Cancelled by the business"}, headers=headers)
    assert done.status_code == 200, done.text
    again = client.post(f"/v1/platform/businesses/{business_id}/bookings/{booking_id}/status",
                        json={"status": "confirmed"}, headers=headers)
    assert again.status_code == 409
    message = again.json()["error"]["message"]
    assert message == "This booking is already cancelled — refresh to see where it stands.", message
