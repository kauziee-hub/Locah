"""Stage 4 — CRM & Customer Management Kernel tests."""

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
from platform_core.permissions import CUSTOMERS_READ, CUSTOMERS_UPDATE
from platform_core.authorization.resolver import AuthorizationService
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
        json={"display_name": f"CRM Co {uuid.uuid4().hex[:8]}", "business_type": "retail"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    business_id = cast(str, resp.json()["data"]["business"]["id"])
    # Gate [7] (Doc 12 SS8.9): optional-module operations require an active module.
    for module_id in ("customer-relationships",):
        enabled = client.post(
            f"/v1/b/{business_id}/modules/{module_id}/enable", headers=headers
        )
        assert enabled.status_code == 200, enabled.text
    return business_id


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_customer_crud_search_archive_restore(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)

    create_resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers",
        json={
            "display_name": "Jane Shopper",
            "phone": "+15550001111",
            "email": "jane@example.com",
            "tags": ["vip", "retail"],
        },
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    customer_id = create_resp.json()["data"]["id"]
    assert create_resp.json()["data"]["status"] == "active"
    assert "vip" in create_resp.json()["data"]["tags"]

    search_resp = client.get(
        f"/v1/platform/businesses/{business_id}/customers?search=Jane",
        headers=headers,
    )
    assert search_resp.status_code == 200, search_resp.text
    assert search_resp.json()["meta"]["count"] >= 1

    dup_resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers",
        json={"display_name": "Duplicate", "phone": "+15550001111"},
        headers=headers,
    )
    assert dup_resp.status_code == 409, dup_resp.text

    archive_resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers/{customer_id}/archive",
        json={},
        headers=headers,
    )
    assert archive_resp.status_code == 200, archive_resp.text
    assert archive_resp.json()["data"]["status"] == "archived"

    restore_resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers/{customer_id}/restore",
        json={},
        headers=headers,
    )
    assert restore_resp.status_code == 200, restore_resp.text
    assert restore_resp.json()["data"]["status"] == "active"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_customer_notes_and_timeline(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)

    customer_id = client.post(
        f"/v1/platform/businesses/{business_id}/customers",
        json={"display_name": "Timeline User", "email": f"{uuid.uuid4()}@example.com"},
        headers=headers,
    ).json()["data"]["id"]

    note_resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers/{customer_id}/notes",
        json={"body": "Prefers morning appointments"},
        headers=headers,
    )
    assert note_resp.status_code == 200, note_resp.text

    timeline_resp = client.get(
        f"/v1/platform/businesses/{business_id}/customers/{customer_id}/timeline",
        headers=headers,
    )
    assert timeline_resp.status_code == 200, timeline_resp.text
    assert timeline_resp.json()["meta"]["count"] >= 1


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_customer_outbox_on_create(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)

    resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers",
        json={"display_name": "Audit Customer", "phone": "+15550002222"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    customer_id = uuid.UUID(resp.json()["data"]["id"])

    async def _check() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            outbox = await session.execute(
                select(PlatformOutboxEvent).where(
                    PlatformOutboxEvent.business_id == uuid.UUID(business_id),
                    PlatformOutboxEvent.event_type == "customer.created",
                )
            )
            assert outbox.scalars().first() is not None
            audit = await session.execute(
                select(PlatformAuditEvent).where(
                    PlatformAuditEvent.business_id == uuid.UUID(business_id),
                    PlatformAuditEvent.resource_type == "customer",
                    PlatformAuditEvent.resource_id == customer_id,
                )
            )
            assert audit.scalars().first() is not None
        await engine.dispose()

    asyncio.run(_check())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_customer_business_isolation(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_a = _create_business(client, headers)
    business_b = _create_business(client, headers)

    customer_id = client.post(
        f"/v1/platform/businesses/{business_a}/customers",
        json={"display_name": "Isolated", "email": f"{uuid.uuid4()}@example.com"},
        headers=headers,
    ).json()["data"]["id"]

    cross = client.get(
        f"/v1/platform/businesses/{business_b}/customers/{customer_id}",
        headers=headers,
    )
    assert cross.status_code == 404


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_owner_has_customer_permissions(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, owner_id = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)

    async def _check() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            perms = await AuthorizationService.effective_permissions(
                session, uuid.UUID(business_id), owner_id
            )
            assert CUSTOMERS_READ in perms
            assert CUSTOMERS_UPDATE in perms
        await engine.dispose()

    asyncio.run(_check())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_a_blocked_customer_can_be_unblocked(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    base = f"/v1/platform/businesses/{business_id}/customers"
    customer_id = client.post(base, json={"display_name": "Divya", "phone": "+919840022334"},
                              headers=headers).json()["data"]["id"]
    # The Workspace sends an empty body to these steps.
    blocked = client.post(f"{base}/{customer_id}/block", json={}, headers=headers)
    assert blocked.status_code == 200 and blocked.json()["data"]["status"] == "blocked", blocked.text
    back = client.post(f"{base}/{customer_id}/restore", json={}, headers=headers)
    assert back.status_code == 200 and back.json()["data"]["status"] == "active", back.text
    again = client.post(f"{base}/{customer_id}/restore", json={}, headers=headers)
    assert again.status_code == 409

