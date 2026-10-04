"""Stage 4 — Order tracking token states (WEB-008)."""

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
from platform_core.models import FulfilmentJob
from platform_testing.db_helpers import ensure_auth_user
from sqlalchemy import update
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


def _place_pickup(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    business = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Track Co {uuid.uuid4().hex[:6]}", "business_type": "retail"},
        headers=headers,
    ).json()["data"]["business"]
    bid = business["id"]
    # A fresh Business defaults to visibility="private" (no public URL) —
    # promote to "unlisted" so the public checkout/tracking endpoints below
    # can actually resolve it.
    assert (
        client.post(
            f"/v1/b/{bid}/marketplace/visibility",
            json={"visibility": "unlisted"},
            headers=headers,
        ).status_code
        == 200
    )
    for mid in ("offerings-catalog", "orders", "inventory", "payments", "fulfilment"):
        client.post(f"/v1/b/{bid}/modules/{mid}/enable", headers=headers)
    client.patch(
        f"/v1/b/{bid}/fulfilment/settings",
        json={"pickup_enabled": True, "delivery_enabled": False},
        headers=headers,
    )
    product_id = client.post(
        f"/v1/platform/businesses/{bid}/products",
        json={
            "title": "Cup",
            "sku": f"C-{uuid.uuid4().hex[:6]}",
            "status": "active",
            "price_amount": 20,
            "visibility": "public",
        },
        headers=headers,
    ).json()["data"]["id"]
    checkout = client.post(
        f"/v1/public/websites/{business['slug']}/checkout",
        json={
            "items": [{"offering_id": product_id, "quantity": 1}],
            "fulfilment_mode": "pickup",
            "payment_method": "cod",
            "guest": {"name": "Tracker", "email": f"{uuid.uuid4()}@example.com"},
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert checkout.status_code == 200, checkout.text
    return cast(dict[str, Any], checkout.json()["data"])


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_valid_tracking_token(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    data = _place_pickup(client, headers)
    order_id = data["order"]["id"]
    token = data["tracking"]["token"]
    resp = client.get(f"/v1/public/orders/{order_id}/tracking?token={token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["state"] in {"ok", "delayed", "failed", "cancelled"}
    assert body["fulfilment"]["customer_status"]
    # The customer sees what they ordered and its total.
    assert body["items"] == [{"title": "Cup", "quantity": 1, "line_total": 20.0}]
    assert body["order"]["total_amount"] == 20.0


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_invalid_tracking_token(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    data = _place_pickup(client, headers)
    order_id = data["order"]["id"]
    resp = client.get(f"/v1/public/orders/{order_id}/tracking?token=not-a-real-token-value")
    assert resp.status_code == 404


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_expired_tracking_token(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    data = _place_pickup(client, headers)
    order_id = data["order"]["id"]
    token = data["tracking"]["token"]

    async def _expire() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                update(FulfilmentJob)
                .where(FulfilmentJob.order_id == uuid.UUID(order_id))
                .values(tracking_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_expire())
    resp = client.get(f"/v1/public/orders/{order_id}/tracking?token={token}")
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] == "expired"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_the_pickup_job_follows_the_order(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    """Marking the order Preparing, Ready and Completed moves its pickup job the same
    way — the owner never updates one order in two places — and never backwards."""
    from platform_testing.phase_b import drain_events, sql

    headers, _ = owner
    client = TestClient(app)
    data = _place_pickup(client, headers)
    order_id = data["order"]["id"]
    bid = sql("select cast(business_id as text) from orders_orders where id = cast(:o as uuid)", o=order_id)[0][0]
    base = f"/v1/platform/businesses/{bid}/orders/{order_id}/status"

    def job() -> str:
        drain_events(bid)
        return str(sql("select status from fulfilment_jobs where order_id = cast(:o as uuid)", o=order_id)[0][0])

    assert job() == "pending"
    for status, expected in (("accepted", "pending"), ("preparing", "preparing"), ("ready", "ready"),
                             ("completed", "delivered")):
        r = client.post(base, json={"status": status}, headers=headers)
        assert r.status_code == 200, r.text
        assert job() == expected, status
