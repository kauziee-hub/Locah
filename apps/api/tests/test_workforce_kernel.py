"""Stage 5 — Workforce kernel tests (Doc 10 §4.8 / Doc 11 §10.5)."""

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


def _create_business(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Workforce Co {uuid.uuid4().hex[:8]}", "business_type": "salon"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return cast(str, resp.json()["data"]["business"]["id"])


def _enable_workforce(client: TestClient, headers: dict[str, str], business_id: str) -> None:
    for mid in ("workforce", "bookings", "offerings-catalog"):
        resp = client.post(f"/v1/b/{business_id}/modules/{mid}/enable", headers=headers)
        assert resp.status_code == 200, resp.text


def _primary_location(client: TestClient, headers: dict[str, str], business_id: str) -> str:
    locs = client.get(
        f"/v1/platform/businesses/{business_id}/locations", headers=headers
    ).json()["data"]
    return cast(str, next(loc["id"] for loc in locs if loc["is_primary"]))


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_workforce_crud_location_service_availability(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_workforce(client, headers, business_id)
    location_id = _primary_location(client, headers, business_id)

    offering_id = client.post(
        f"/v1/platform/businesses/{business_id}/products",
        json={
            "title": "Cut",
            "offering_type": "service",
            "status": "active",
            "price_amount": 40,
        },
        headers=headers,
    ).json()["data"]["id"]

    create = client.post(
        f"/v1/platform/businesses/{business_id}/workforce/members",
        json={
            "display_name": "Alex Provider",
            "location_ids": [location_id],
            "primary_location_id": location_id,
            "offering_ids": [offering_id],
        },
        headers=headers,
    )
    assert create.status_code == 200, create.text
    member = create.json()["data"]
    assert member["grants_workspace_access"] is False
    member_id = member["id"]

    detail = client.get(
        f"/v1/platform/businesses/{business_id}/workforce/members/{member_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["data"]["locations"]) == 1
    assert len(detail.json()["data"]["services"]) == 1

    avail = client.post(
        f"/v1/platform/businesses/{business_id}/workforce/members/{member_id}/availability",
        json={"weekday": 1, "start_time": "09:00", "end_time": "17:00"},
        headers=headers,
    )
    assert avail.status_code == 200, avail.text

    deactivated = client.post(
        f"/v1/platform/businesses/{business_id}/workforce/members/{member_id}/deactivate",
        headers=headers,
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["data"]["status"] == "inactive"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_workforce_identity_linkage_does_not_grant_workspace(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, owner_id = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_workforce(client, headers, business_id)

    # Link to the owner's Platform Identity — still must NOT create membership/access.
    create = client.post(
        f"/v1/platform/businesses/{business_id}/workforce/members",
        json={
            "display_name": "Linked Only",
            "identity_id": str(owner_id),
        },
        headers=headers,
    )
    assert create.status_code == 200, create.text
    assert create.json()["data"]["grants_workspace_access"] is False
    assert create.json()["data"]["identity_id"] == str(owner_id)

    # Creating a second business actor from linkage alone is not how auth works —
    # serialize explicitly documents no Workspace grant (Doc 11 §10.5).
    detail = client.get(
        f"/v1/platform/businesses/{business_id}/workforce/members/{create.json()['data']['id']}",
        headers=headers,
    )
    assert detail.json()["data"]["grants_workspace_access"] is False


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_workforce_business_isolation(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    a = _create_business(client, headers)
    b = _create_business(client, headers)
    _enable_workforce(client, headers, a)
    _enable_workforce(client, headers, b)
    member_id = client.post(
        f"/v1/platform/businesses/{a}/workforce/members",
        json={"display_name": "Only A"},
        headers=headers,
    ).json()["data"]["id"]
    denied = client.get(
        f"/v1/platform/businesses/{b}/workforce/members/{member_id}",
        headers=headers,
    )
    assert denied.status_code == 404, denied.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_workforce_audit_and_outbox(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_workforce(client, headers, business_id)
    client.post(
        f"/v1/platform/businesses/{business_id}/workforce/members",
        json={"display_name": "Audited"},
        headers=headers,
    )

    async def _assert() -> None:
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
                    PlatformOutboxEvent.event_type == "workforce.member_created",
                )
            )
            assert outbox.first() is not None
            audit = await session.execute(
                select(PlatformAuditEvent.event_type).where(
                    PlatformAuditEvent.business_id == uuid.UUID(business_id),
                    PlatformAuditEvent.event_type == "workforce.member_created",
                )
            )
            assert audit.first() is not None
        await engine.dispose()

    asyncio.run(_assert())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_a_service_can_be_taken_off_someone_and_they_can_come_back(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    _enable_workforce(client, headers, business_id)
    location_id = _primary_location(client, headers, business_id)
    base = f"/v1/platform/businesses/{business_id}/workforce/members"
    offering_id = client.post(f"/v1/platform/businesses/{business_id}/products", json={
        "title": "Facial", "offering_type": "service", "status": "active", "price_amount": 900}, headers=headers,
    ).json()["data"]["id"]
    member_id = client.post(base, json={"display_name": "Priya", "location_ids": [location_id],
                                        "primary_location_id": location_id, "offering_ids": [offering_id]},
                            headers=headers).json()["data"]["id"]

    gone = client.delete(f"{base}/{member_id}/services/{offering_id}", headers=headers)
    assert gone.status_code == 200, gone.text
    assert client.get(f"{base}/{member_id}", headers=headers).json()["data"]["services"] == []
    assert client.delete(f"{base}/{member_id}/services/{offering_id}", headers=headers).status_code == 404

    # Deactivated, then back: only the two real statuses are accepted.
    assert client.post(f"{base}/{member_id}/deactivate", headers=headers).status_code == 200
    back = client.patch(f"{base}/{member_id}", json={"status": "active"}, headers=headers)
    assert back.status_code == 200 and back.json()["data"]["status"] == "active"
    assert client.patch(f"{base}/{member_id}", json={"status": "on_holiday"}, headers=headers).status_code == 422
    assert client.patch(f"{base}/{member_id}", json={"display_name": "  "}, headers=headers).status_code == 422
