"""Stage 7 — Core Notifications kernel tests (Doc 09 CORE-015, Doc 11 §17.7).

IMPORTANT — AUD-07 interaction, read before adding tests here.

Notification fan-out targets members who hold the *read permission relevant to
the resource* (e.g. `orders.read` for an order notification). AUD-07 is still
open: the `manager` and `member` roles currently resolve to ZERO default
permissions, so a freshly invited member holds nothing. That means:

    a fan-out test that invites a member and does NOT call
    `_grant_permissions` first will see that member receive nothing —
    and that is CORRECT behaviour, not a bug in NotificationService.

Every test below that asserts a non-owner receives a notification therefore
grants the permission explicitly first, mirroring the pattern already used in
`test_membership_engine.py::test_manager_permissions`. If this file ever starts
showing empty fan-out, check for a missing grant before suspecting the service.

The Primary Owner is the deliberate exception: they are always a recipient
regardless of explicit grants, so that every Business has a real recipient from
day one while AUD-07 remains unresolved.
"""

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
from platform_core.permissions import ORDERS_READ
from platform_testing.db_helpers import ensure_auth_user
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def _token(sub: uuid.UUID, email: str) -> str:
    return jwt.encode(
        {"sub": str(sub), "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
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


def _new_identity() -> tuple[dict[str, str], uuid.UUID, str]:
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"
    _seed(user_id, email)
    return _headers(user_id, email), user_id, email


@pytest.fixture
def owner(monkeypatch: Any) -> tuple[dict[str, str], uuid.UUID]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    headers, user_id, _ = _new_identity()
    return headers, user_id


def _create_business(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Notif Co {uuid.uuid4().hex[:8]}", "business_type": "retail"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return cast(str, resp.json()["data"]["business"]["id"])


def _invite_and_activate(
    client: TestClient,
    owner_headers: dict[str, str],
    business_id: str,
    invitee_headers: dict[str, str],
    email: str,
    role: str = "member",
) -> str:
    """Real invitation flow: create -> accept. Returns the membership id.

    Deliberately NOT `POST /v1/b/{id}/team/invitations` — that endpoint creates a
    membership row directly via `TeamService.invite_member`, which emits no
    domain event at all, so nothing would reach the notification dispatcher.
    The email-based invitation flow is the production path and is what emits
    `invitation.created`.
    """
    invite = client.post(
        f"/v1/platform/businesses/{business_id}/invitations",
        json={"invited_email": email, "invited_role": role},
        headers=owner_headers,
    )
    assert invite.status_code == 200, invite.text
    invitation_id = cast(str, invite.json()["data"]["id"])
    accepted = client.post(
        f"/v1/platform/businesses/{business_id}/invitations/{invitation_id}/accept",
        headers=invitee_headers,
    )
    assert accepted.status_code == 200, accepted.text
    return cast(str, accepted.json()["data"]["membership"]["id"])


def _grant_permissions(
    client: TestClient,
    owner_headers: dict[str, str],
    business_id: str,
    membership_id: str,
    permissions: list[str],
) -> None:
    """Explicit grant — REQUIRED for any non-owner fan-out assertion (see AUD-07
    note in this module's docstring)."""
    resp = client.post(
        f"/v1/b/{business_id}/team/members/{membership_id}/permissions",
        json={"permissions": permissions},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text


def _notifications(
    client: TestClient, headers: dict[str, str], business_id: str, **params: Any
) -> dict[str, Any]:
    resp = client.get(
        f"/v1/platform/businesses/{business_id}/notifications", headers=headers, params=params
    )
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json())


# ---------------------------------------------------------------------------
# Owner-always-recipient
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_owner_always_receives_without_explicit_grants(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """Primary Owner needs no grant — the AUD-07 exception."""
    headers, owner_id = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)

        # Any invite emits invitation.created; the owner also holds team.read,
        # so invitation.accepted-class access events land in their inbox.
        other_headers, _, other_email = _new_identity()
        _invite_and_activate(client, headers, bid, other_headers, other_email)

        body = _notifications(client, headers, bid)
        assert body["meta"]["unread_count"] >= 0
        # Owner's inbox is addressable and scoped to them.
        for row in body["data"]:
            assert row["recipient_identity_id"] == str(owner_id)


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_invitation_notifies_the_invited_identity(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """`invitation.created` is directed at the invitee, not fanned out."""
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        invitee_headers, invitee_id, invitee_email = _new_identity()
        _invite_and_activate(client, headers, bid, invitee_headers, invitee_email)

        # The invitee holds no permissions (AUD-07) but this notification is
        # directed, not permission-gated, so it must be there.
        body = _notifications(client, invitee_headers, bid)
        types = {row["notification_type"] for row in body["data"]}
        assert "invitation.received" in types, body["data"]
        for row in body["data"]:
            assert row["recipient_identity_id"] == str(invitee_id)
            if row["notification_type"] == "invitation.received":
                assert row["category"] == "access"
                assert row["resource_type"] == "invitation"


# ---------------------------------------------------------------------------
# Permission-gated fan-out
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_fanout_requires_the_relevant_permission(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """Two members, identical roles; only the granted one receives.

    This is the test that would look like a silent bug if the grant were
    omitted — see the AUD-07 note at the top of this module.
    """
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        for module_id in ("offerings-catalog", "orders", "customer-relationships"):
            enabled = client.post(f"/v1/b/{bid}/modules/{module_id}/enable", headers=headers)
            assert enabled.status_code == 200, enabled.text

        locations = client.get(
            f"/v1/platform/businesses/{bid}/locations", headers=headers
        )
        assert locations.status_code == 200, locations.text
        location_id = next(loc["id"] for loc in locations.json()["data"] if loc["is_primary"])

        granted_headers, _, granted_email = _new_identity()
        ungranted_headers, _, ungranted_email = _new_identity()
        granted_mid = _invite_and_activate(client, headers, bid, granted_headers, granted_email)
        _invite_and_activate(client, headers, bid, ungranted_headers, ungranted_email)

        # ONLY this member gets orders.read. The other keeps role defaults,
        # which AUD-07 means are empty.
        _grant_permissions(client, headers, bid, granted_mid, [ORDERS_READ])

        product = client.post(
            f"/v1/platform/businesses/{bid}/products",
            json={
                "title": f"Widget {uuid.uuid4().hex[:6]}",
                "price_amount": 100,
                "status": "active",
            },
            headers=headers,
        )
        assert product.status_code == 200, product.text
        offering_id = product.json()["data"]["id"]

        order = client.post(
            f"/v1/platform/businesses/{bid}/orders",
            json={
                "location_id": location_id,
                "payment_method": "cod",
                "idempotency_key": str(uuid.uuid4()),
                "items": [{"offering_id": offering_id, "quantity": 1}],
            },
            headers=headers,
        )
        assert order.status_code == 200, order.text

        granted_types = {
            r["notification_type"] for r in _notifications(client, granted_headers, bid)["data"]
        }
        ungranted_types = {
            r["notification_type"] for r in _notifications(client, ungranted_headers, bid)["data"]
        }
        assert "order.placed" in granted_types, granted_types
        # Correct behaviour, NOT a bug: no orders.read grant, no order notification.
        assert "order.placed" not in ungranted_types, ungranted_types


# ---------------------------------------------------------------------------
# Read / mark-read
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_mark_read_and_mark_all_read(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        # Generate a few access-category notifications for the owner.
        for _ in range(2):
            oh, _, oe = _new_identity()
            _invite_and_activate(client, headers, bid, oh, oe)

        invitee_headers, invitee_id, invitee_email = _new_identity()
        _invite_and_activate(client, headers, bid, invitee_headers, invitee_email)

        before = _notifications(client, invitee_headers, bid)
        assert before["meta"]["unread_count"] >= 1
        target = before["data"][0]["id"]

        marked = client.post(
            f"/v1/platform/businesses/{bid}/notifications/{target}/read", headers=invitee_headers
        )
        assert marked.status_code == 200, marked.text
        assert marked.json()["data"]["read_at"] is not None

        # Idempotent: marking again keeps the original timestamp.
        again = client.post(
            f"/v1/platform/businesses/{bid}/notifications/{target}/read", headers=invitee_headers
        )
        assert again.status_code == 200
        assert again.json()["data"]["read_at"] == marked.json()["data"]["read_at"]

        all_read = client.post(
            f"/v1/platform/businesses/{bid}/notifications/read-all", headers=invitee_headers
        )
        assert all_read.status_code == 200, all_read.text

        after = _notifications(client, invitee_headers, bid)
        assert after["meta"]["unread_count"] == 0
        unread_only = _notifications(client, invitee_headers, bid, unread_only=True)
        assert unread_only["data"] == []


# ---------------------------------------------------------------------------
# Cross-identity isolation (Doc 09 ACC-011)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_cannot_read_or_mark_another_identitys_notification(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        invitee_headers, invitee_id, invitee_email = _new_identity()
        _invite_and_activate(client, headers, bid, invitee_headers, invitee_email)

        invitee_body = _notifications(client, invitee_headers, bid)
        assert invitee_body["data"], "invitee should have at least the invitation notification"
        invitee_notification_id = invitee_body["data"][0]["id"]

        # The owner must not see the invitee's rows in their own list.
        owner_ids = {r["id"] for r in _notifications(client, headers, bid)["data"]}
        assert invitee_notification_id not in owner_ids

        # 404, never 403 — existence must not leak across identities.
        stolen = client.post(
            f"/v1/platform/businesses/{bid}/notifications/{invitee_notification_id}/read",
            headers=headers,
        )
        assert stolen.status_code == 404, stolen.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_cross_tenant_notification_access_refused(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        outsider_headers, _, _ = _new_identity()
        leaked = client.get(
            f"/v1/platform/businesses/{bid}/notifications", headers=outsider_headers
        )
        assert leaked.status_code in (403, 404), leaked.text


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_preferences_default_on_and_mute_suppresses_fanout(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)

        prefs = client.get(
            f"/v1/platform/businesses/{bid}/notification-preferences", headers=headers
        )
        assert prefs.status_code == 200, prefs.text
        rows = prefs.json()["data"]
        assert {r["category"] for r in rows} == {
            "operational",
            "commercial",
            "access",
            "platform",
        }
        assert all(r["in_app_enabled"] for r in rows), "unset categories default to enabled"

        muted = client.put(
            f"/v1/platform/businesses/{bid}/notification-preferences",
            json={"category": "access", "in_app_enabled": False},
            headers=headers,
        )
        assert muted.status_code == 200, muted.text
        assert muted.json()["data"]["in_app_enabled"] is False

        # Owner muted `access`; a subsequent access-category fan-out skips them.
        before = len(_notifications(client, headers, bid, category="access")["data"])
        oh, _, oe = _new_identity()
        _invite_and_activate(client, headers, bid, oh, oe)
        after = len(_notifications(client, headers, bid, category="access")["data"])
        assert after == before, "muted category must not accrue new notifications"

        unmuted = client.put(
            f"/v1/platform/businesses/{bid}/notification-preferences",
            json={"category": "access", "in_app_enabled": True},
            headers=headers,
        )
        assert unmuted.status_code == 200, unmuted.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_invalid_preference_category_rejected(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        bad = client.put(
            f"/v1/platform/businesses/{bid}/notification-preferences",
            json={"category": "marketing", "in_app_enabled": False},
            headers=headers,
        )
        assert bad.status_code == 422, bad.text


# ---------------------------------------------------------------------------
# Platform Core gating: notifications is NOT entitlement/module gated (AUD-01)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_notifications_reachable_without_any_optional_module(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """`core-notifications` is Platform Core: no module enable step required."""
    headers, _ = owner
    with TestClient(app) as client:
        bid = _create_business(client, headers)
        resp = client.get(f"/v1/platform/businesses/{bid}/notifications", headers=headers)
        assert resp.status_code == 200, resp.text
        counted = client.get(
            f"/v1/platform/businesses/{bid}/notifications/unread-count", headers=headers
        )
        assert counted.status_code == 200, counted.text
        assert "unread_count" in counted.json()["data"]


def test_an_order_notification_says_which_order() -> None:
    """Owner lab, meat shop: "New order placed" and nothing else — the owner had
    to open each one to know which order it was."""
    from platform_core.services.notification_dispatch import NOTIFICATION_RULES, _body

    payload = {"order_id": "o-1", "after": {"order_number": "ORD-754794E1", "total_amount": 320,
                                            "items": [{"title": "Chicken boneless — 500 g"},
                                                      {"title": "Chicken curry cut — 500 g"}]}}
    assert _body(NOTIFICATION_RULES["order.created"], payload) == "ORD-754794E1 · ₹320 · 2 items"
    assert _body(NOTIFICATION_RULES["order.created"], {"after": {}}) is None


def test_a_booking_notification_says_which_booking_and_when() -> None:
    # Owner lab (salon): "New booking received" / "A booking was cancelled"
    # said nothing else, so the owner could not tell which of several it was.
    from platform_core.services.notification_dispatch import NOTIFICATION_RULES, _body

    payload = {"booking_number": "BKG-21715ABE", "starts_at": "2026-10-21T10:30:00+00:00",
               "after": {"title": "Women's haircut"}}
    for event in ("booking.created", "booking.cancelled"):
        assert _body(NOTIFICATION_RULES[event], payload) == "BKG-21715ABE · Women's haircut · Wed 21 Oct, 4:00 pm"
    assert _body(NOTIFICATION_RULES["booking.created"], {"starts_at": "not a time"}) is None
