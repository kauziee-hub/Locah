"""Stage 9 — Payments Kernel tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
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
from platform_core.models import PlatformAuditEvent, PlatformOutboxEvent
from platform_testing.db_helpers import ensure_auth_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
WEBHOOK_SECRET = "test-payment-webhook-secret"


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
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", WEBHOOK_SECRET)
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"
    _seed(user_id, email)
    return _headers(user_id, email), user_id


def _create_business(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Payments Co {uuid.uuid4().hex[:8]}", "business_type": "retail"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    business_id = cast(str, resp.json()["data"]["business"]["id"])
    # Gate [7] (Doc 12 SS8.9): optional-module operations require an active module.
    for module_id in ("offerings-catalog", "orders", "payments", "customer-relationships", "inventory",):
        enabled = client.post(
            f"/v1/b/{business_id}/modules/{module_id}/enable", headers=headers
        )
        assert enabled.status_code == 200, enabled.text
    return business_id


def _primary_location_id(client: TestClient, headers: dict[str, str], business_id: str) -> str:
    resp = client.get(f"/v1/platform/businesses/{business_id}/locations", headers=headers)
    assert resp.status_code == 200, resp.text
    for loc in resp.json()["data"]:
        if loc["is_primary"]:
            return cast(str, loc["id"])
    raise AssertionError("primary location missing")


def _create_customer(client: TestClient, headers: dict[str, str], business_id: str) -> str:
    resp = client.post(
        f"/v1/platform/businesses/{business_id}/customers",
        json={"display_name": "Payment Buyer", "email": f"{uuid.uuid4()}@example.com"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return cast(str, resp.json()["data"]["id"])


def _create_tracked_product(client: TestClient, headers: dict[str, str], business_id: str) -> str:
    product_id = client.post(
        f"/v1/platform/businesses/{business_id}/products",
        json={
            "title": f"Pay Widget {uuid.uuid4().hex[:6]}",
            "sku": f"PAY-{uuid.uuid4().hex[:8]}",
            "track_inventory": True,
            "status": "active",
            "price_amount": 100.0,
            "tax_rate": 10.0,
        },
        headers=headers,
    ).json()["data"]["id"]
    return cast(str, product_id)


def _stock_product(
    client: TestClient,
    headers: dict[str, str],
    business_id: str,
    product_id: str,
    location_id: str,
    quantity: int = 50,
) -> None:
    resp = client.post(
        f"/v1/platform/businesses/{business_id}/inventory/opening-stock",
        json={
            "offering_id": product_id,
            "location_id": location_id,
            "quantity": quantity,
            "reason": "Test stock",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _create_order(
    client: TestClient,
    headers: dict[str, str],
    business_id: str,
    location_id: str,
    product_id: str,
    customer_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "location_id": location_id,
        "payment_method": "cod",
        "items": [{"offering_id": product_id, "quantity": 2}],
    }
    if customer_id:
        payload["customer_contact_id"] = customer_id
    resp = client.post(
        f"/v1/platform/businesses/{business_id}/orders",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json()["data"])


def _webhook_signature(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_cod_payment_offline_settlement_and_order_sync(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    customer_id = _create_customer(client, headers, business_id)
    product_id = _create_tracked_product(client, headers, business_id)
    _stock_product(client, headers, business_id, product_id, location_id)
    order = _create_order(client, headers, business_id, location_id, product_id, customer_id)
    order_total = order["total_amount"]

    idempotency_key = str(uuid.uuid4())
    pay_resp = client.post(
        f"/v1/platform/businesses/{business_id}/payments",
        json={
            "source_type": "order",
            "source_id": order["id"],
            "amount": order_total,
            "payment_method": "cod",
            "idempotency_key": idempotency_key,
        },
        headers=headers,
    )
    assert pay_resp.status_code == 200, pay_resp.text
    payment = pay_resp.json()["data"]
    assert payment["status"] == "pending_offline"
    payment_id = payment["id"]

    dup_resp = client.post(
        f"/v1/platform/businesses/{business_id}/payments",
        json={
            "source_type": "order",
            "source_id": order["id"],
            "amount": order_total,
            "payment_method": "cod",
            "idempotency_key": idempotency_key,
        },
        headers=headers,
    )
    assert dup_resp.status_code == 200, dup_resp.text
    assert dup_resp.json()["data"]["id"] == payment_id

    order_resp = client.get(
        f"/v1/platform/businesses/{business_id}/orders/{order['id']}",
        headers=headers,
    )
    assert order_resp.json()["data"]["payment_status"] == "pending_offline"

    settle_resp = client.post(
        f"/v1/platform/businesses/{business_id}/payments/{payment_id}/record-settlement",
        json={"version": payment["version"]},
        headers=headers,
    )
    assert settle_resp.status_code == 200, settle_resp.text
    assert settle_resp.json()["data"]["status"] == "succeeded"

    order_resp = client.get(
        f"/v1/platform/businesses/{business_id}/orders/{order['id']}",
        headers=headers,
    )
    assert order_resp.json()["data"]["payment_status"] == "paid"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_online_payment_webhook_and_refund(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    product_id = _create_tracked_product(client, headers, business_id)
    _stock_product(client, headers, business_id, product_id, location_id)
    order = _create_order(client, headers, business_id, location_id, product_id)

    pay_resp = client.post(
        f"/v1/platform/businesses/{business_id}/payments",
        json={
            "source_type": "order",
            "source_id": order["id"],
            "amount": order["total_amount"],
            "payment_method": "online",
        },
        headers=headers,
    )
    assert pay_resp.status_code == 200, pay_resp.text
    payment = pay_resp.json()["data"]
    assert payment["status"] == "processing"
    payment_id = payment["id"]

    payload = {
        "event_id": str(uuid.uuid4()),
        "payment_id": payment_id,
        "status": "succeeded",
        "provider_reference": "stub-ref-001",
    }
    raw = json.dumps(payload).encode()
    sig = _webhook_signature(raw)
    webhook_resp = client.post(
        "/v1/webhooks/payments/stub",
        content=raw,
        headers={"Content-Type": "application/json", "x-payment-signature": sig},
    )
    assert webhook_resp.status_code == 200, webhook_resp.text
    assert webhook_resp.json()["data"]["status"] == "processed"

    get_resp = client.get(
        f"/v1/platform/businesses/{business_id}/payments/{payment_id}",
        headers=headers,
    )
    assert get_resp.json()["data"]["status"] == "succeeded"

    refund_resp = client.post(
        f"/v1/platform/businesses/{business_id}/payments/{payment_id}/refunds",
        json={"amount": order["total_amount"], "reason": "Customer return", "version": get_resp.json()["data"]["version"]},
        headers=headers,
    )
    assert refund_resp.status_code == 200, refund_resp.text
    assert refund_resp.json()["data"]["payment"]["status"] == "refunded"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_payment_webhook_rejects_invalid_signature(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    payload = {"event_id": str(uuid.uuid4()), "payment_id": str(uuid.uuid4()), "status": "succeeded"}
    raw = json.dumps(payload).encode()
    resp = client.post(
        "/v1/webhooks/payments/stub",
        content=raw,
        headers={"Content-Type": "application/json", "x-payment-signature": "bad-signature"},
    )
    assert resp.status_code == 422 or resp.status_code == 400


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_payment_business_isolation(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers_a, _ = owner
    client = TestClient(app)
    business_a = _create_business(client, headers_a)
    location_a = _primary_location_id(client, headers_a, business_a)
    product_a = _create_tracked_product(client, headers_a, business_a)
    _stock_product(client, headers_a, business_a, product_a, location_a)
    order_a = _create_order(client, headers_a, business_a, location_a, product_a)

    user_b = uuid.uuid4()
    email_b = f"{user_b}@example.com"
    _seed(user_b, email_b)
    headers_b = _headers(user_b, email_b)
    business_b = _create_business(client, headers_b)

    pay_a = client.post(
        f"/v1/platform/businesses/{business_a}/payments",
        json={
            "source_type": "order",
            "source_id": order_a["id"],
            "amount": order_a["total_amount"],
            "payment_method": "cod",
        },
        headers=headers_a,
    ).json()["data"]

    denied = client.get(
        f"/v1/platform/businesses/{business_b}/payments/{pay_a['id']}",
        headers=headers_b,
    )
    assert denied.status_code == 403 or denied.status_code == 404


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_payment_audit_and_outbox(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    product_id = _create_tracked_product(client, headers, business_id)
    _stock_product(client, headers, business_id, product_id, location_id)
    order = _create_order(client, headers, business_id, location_id, product_id)

    pay_resp = client.post(
        f"/v1/platform/businesses/{business_id}/payments",
        json={
            "source_type": "order",
            "source_id": order["id"],
            "amount": order["total_amount"],
            "payment_method": "cod",
        },
        headers=headers,
    )
    payment_id = pay_resp.json()["data"]["id"]

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
                    PlatformOutboxEvent.event_type == "payment.initiated",
                )
            )
            assert outbox.scalars().first() is not None
            audit = await session.execute(
                select(PlatformAuditEvent).where(
                    PlatformAuditEvent.business_id == uuid.UUID(business_id),
                    PlatformAuditEvent.resource_id == uuid.UUID(payment_id),
                )
            )
            assert audit.scalars().first() is not None
        await engine.dispose()

    asyncio.run(_check())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_merchant_connection_upsert(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)

    resp = client.put(
        f"/v1/platform/businesses/{business_id}/payments/merchant-connection",
        json={"provider": "stub", "status": "active", "provider_metadata": {"merchant_ref": "m-1"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "active"

    get_resp = client.get(
        f"/v1/platform/businesses/{business_id}/payments/merchant-connection?provider=stub",
        headers=headers,
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["data"]["provider_metadata"]["merchant_ref"] == "m-1"


# ---------------------------------------------------------------------------
# AUD-10 — payment-create permission is keyed to the SOURCE module, not a
# two-way order/booking branch that silently caught membership.
# ---------------------------------------------------------------------------
def _commerce_business(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Src Perm Co {uuid.uuid4().hex[:8]}", "business_type": "salon"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    bid = cast(str, resp.json()["data"]["business"]["id"])
    for module_id in (
        "offerings-catalog",
        "orders",
        "bookings",
        "memberships",
        "payments",
        "workforce",
        "customer-relationships",
        "inventory",
    ):
        enabled = client.post(f"/v1/b/{bid}/modules/{module_id}/enable", headers=headers)
        assert enabled.status_code == 200, enabled.text
    return bid


def _member_with_grants(
    client: TestClient,
    owner_headers: dict[str, str],
    business_id: str,
    permissions: list[str],
) -> dict[str, str]:
    member_id = uuid.uuid4()
    email = f"{member_id}@example.com"
    _seed(member_id, email)
    invite = client.post(
        f"/v1/b/{business_id}/team/invitations",
        json={"identity_id": str(member_id), "role": "member"},
        headers=owner_headers,
    )
    assert invite.status_code == 200, invite.text
    membership_id = invite.json()["data"]["id"]
    activate = client.post(
        f"/v1/b/{business_id}/team/members/{membership_id}/activate", headers=owner_headers
    )
    assert activate.status_code == 200, activate.text
    granted = client.post(
        f"/v1/b/{business_id}/team/members/{membership_id}/permissions",
        json={"permissions": permissions},
        headers=owner_headers,
    )
    assert granted.status_code == 200, granted.text
    return _headers(member_id, email)


def _membership_enrolment(
    client: TestClient, headers: dict[str, str], business_id: str
) -> str:
    plan_id = client.post(
        f"/v1/platform/businesses/{business_id}/membership-plans",
        json={
            "name": f"Plan {uuid.uuid4().hex[:6]}",
            "price_amount": 60,
            "duration_days": 30,
            "status": "active",
            "visibility": "public",
        },
        headers=headers,
    ).json()["data"]["id"]
    contact_id = _create_customer(client, headers, business_id)
    enrolment = client.post(
        f"/v1/platform/businesses/{business_id}/membership-enrolments",
        json={
            "plan_id": plan_id,
            "customer_contact_id": contact_id,
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert enrolment.status_code == 200, enrolment.text
    return cast(str, enrolment.json()["data"]["id"])


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_membership_payment_requires_memberships_permission_not_bookings(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """AUD-10: a membership payment needs memberships.manage_enrolment.

    Before the fix, the source->permission map was
    `ORDERS_UPDATE_STATUS if source_type == "order" else BOOKINGS_UPDATE`, so a
    membership payment was gated on a Bookings permission — wrong module both
    ways round.
    """
    headers, _ = owner
    client = TestClient(app)
    bid = _commerce_business(client, headers)
    enrolment_id = _membership_enrolment(client, headers, bid)

    # Holds payments.read + the Bookings permission that used to leak through.
    bookings_member = _member_with_grants(
        client, headers, bid, ["payments.read", "bookings.update"]
    )
    blocked = client.post(
        f"/v1/platform/businesses/{bid}/payments",
        json={
            "source_type": "membership",
            "source_id": enrolment_id,
            "amount": 60.0,
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=bookings_member,
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["details"]["permission"] == "memberships.manage_enrolment"

    # Holds payments.read + the correct module permission.
    memberships_member = _member_with_grants(
        client, headers, bid, ["payments.read", "memberships.manage_enrolment"]
    )
    allowed = client.post(
        f"/v1/platform/businesses/{bid}/payments",
        json={
            "source_type": "membership",
            "source_id": enrolment_id,
            "amount": 60.0,
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=memberships_member,
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["data"]["source_type"] == "membership"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_membership_permission_does_not_grant_order_payments(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """The other direction: memberships.manage_enrolment is not orders access."""
    headers, _ = owner
    client = TestClient(app)
    bid = _commerce_business(client, headers)
    location_id = _primary_location_id(client, headers, bid)
    product_id = _create_tracked_product(client, headers, bid)
    _stock_product(client, headers, bid, product_id, location_id)
    order = _create_order(client, headers, bid, location_id, product_id)

    memberships_member = _member_with_grants(
        client, headers, bid, ["payments.read", "memberships.manage_enrolment"]
    )
    blocked = client.post(
        f"/v1/platform/businesses/{bid}/payments",
        json={
            "source_type": "order",
            "source_id": order["id"],
            "amount": order["total_amount"],
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=memberships_member,
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["details"]["permission"] == "orders.update_status"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_unknown_payment_source_type_is_422_not_500(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """A garbage source_type is a clean 422, never a KeyError 500.

    The KeyError on the source->permission map is a developer tripwire for a
    member of SOURCE_TYPES with no mapping; it must not be reachable by a
    client sending an unrecognised value.
    """
    headers, _ = owner
    client = TestClient(app)
    bid = _commerce_business(client, headers)
    resp = client.post(
        f"/v1/platform/businesses/{bid}/payments",
        json={
            "source_type": "invoice",
            "source_id": str(uuid.uuid4()),
            "amount": 10.0,
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_two_refunds_at_once_never_refund_more_than_was_paid(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    """Two people refunding 60% of the same payment at the same moment: one wins,
    the other is refused — never 120% recorded against a 100% payment."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from platform_core.exceptions import ConflictError, ValidationError
    from platform_core.services.refund import RefundService
    from platform_testing.phase_b import db_url, sql

    headers, owner_id = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    product_id = _create_tracked_product(client, headers, business_id)
    _stock_product(client, headers, business_id, product_id, location_id)
    order = _create_order(client, headers, business_id, location_id, product_id)
    payment_id = client.post(f"/v1/platform/businesses/{business_id}/payments", json={
        "source_type": "order", "source_id": order["id"], "amount": order["total_amount"],
        "payment_method": "online"}, headers=headers).json()["data"]["id"]
    raw = json.dumps({"event_id": str(uuid.uuid4()), "payment_id": payment_id, "status": "succeeded",
                      "provider_reference": "stub-race"}).encode()
    assert client.post("/v1/webhooks/payments/stub", content=raw, headers={
        "Content-Type": "application/json", "x-payment-signature": _webhook_signature(raw)}).status_code == 200
    part = round(float(order["total_amount"]) * 0.6, 2)
    actor = sql("select primary_owner_identity_id from businesses where id = :b", b=business_id)[0][0]

    async def refund(gate: asyncio.Barrier) -> str:
        engine = create_async_engine(db_url(), poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await gate.wait()
                try:
                    await RefundService.create_refund(
                        session, business_id=uuid.UUID(business_id), payment_id=uuid.UUID(payment_id),
                        actor_id=actor, correlation_id=str(uuid.uuid4()),
                        payload={"amount": part, "reason": "Return"})
                    await asyncio.sleep(0.2)  # hold the transaction open while the other one tries
                    await session.commit()
                    return "refunded"
                except (ValidationError, ConflictError):
                    await session.rollback()
                    return "refused"
        finally:
            await engine.dispose()

    async def both() -> list[str]:
        gate = asyncio.Barrier(2)
        return list(await asyncio.gather(refund(gate), refund(gate)))

    assert sorted(asyncio.run(both())) == ["refunded", "refused"]
    rows = sql("select count(*), coalesce(sum(amount), 0) from payments_refunds where payment_attempt_id = :p",
               p=payment_id)
    refunded = sql("select refunded_amount from payments_payment_attempts where id = :p", p=payment_id)[0][0]
    assert rows[0][0] == 1 and float(rows[0][1]) == part and float(refunded) == part


def test_a_retried_refund_with_the_same_key_refunds_once(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    """A double-click or a retried request carries the same idempotency key: the
    first refund comes back, nothing is refunded twice, and the key cannot be
    reused for another amount. A new key is a new refund."""
    from platform_testing.phase_b import sql

    headers, _ = owner
    client = TestClient(app)
    business_id = _create_business(client, headers)
    location_id = _primary_location_id(client, headers, business_id)
    product_id = _create_tracked_product(client, headers, business_id)
    _stock_product(client, headers, business_id, product_id, location_id)
    order = _create_order(client, headers, business_id, location_id, product_id)
    payment_id = client.post(f"/v1/platform/businesses/{business_id}/payments", json={
        "source_type": "order", "source_id": order["id"], "amount": order["total_amount"],
        "payment_method": "online"}, headers=headers).json()["data"]["id"]
    raw = json.dumps({"event_id": str(uuid.uuid4()), "payment_id": payment_id, "status": "succeeded",
                      "provider_reference": "stub-retry"}).encode()
    assert client.post("/v1/webhooks/payments/stub", content=raw, headers={
        "Content-Type": "application/json", "x-payment-signature": _webhook_signature(raw)}).status_code == 200
    part = round(float(order["total_amount"]) * 0.3, 2)
    url = f"/v1/platform/businesses/{business_id}/payments/{payment_id}/refunds"
    body = {"amount": part, "reason": "Customer returned one", "idempotency_key": "refund-form-1"}

    first = client.post(url, json=body, headers=headers)
    again = client.post(url, json=body, headers=headers)
    assert first.status_code == 200 and again.status_code == 200, (first.text, again.text)
    assert again.json()["data"]["refund"]["id"] == first.json()["data"]["refund"]["id"]
    other = client.post(url, json={**body, "amount": round(part / 2, 2)}, headers=headers)
    assert other.status_code == 409 and other.json()["error"]["code"] == "CONFLICT"
    assert client.post(url, json={**body, "idempotency_key": "refund-form-2"}, headers=headers).status_code == 200
    rows = sql("select count(*) from payments_refunds where payment_attempt_id = cast(:p as uuid)", p=payment_id)
    refunded = sql("select refunded_amount from payments_payment_attempts where id = cast(:p as uuid)", p=payment_id)
    assert rows[0][0] == 2 and round(float(refunded[0][0]), 2) == round(part * 2, 2)
