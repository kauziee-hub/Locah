"""Event → notification dispatch (Stage 7 — Doc 09 CORE-015, Doc 11 §17.7).

Every domain event in this codebase already flows through `OutboxService.publish`,
so notification fan-out hooks in there once rather than being duplicated across
the ~15 services that emit notification-worthy events. Events with no rule below
produce no notification — the map is the whole policy.

Recipient rule per event is either:
  * `required_permission` — fan out to active members holding that permission
    (Primary Owner always included; see NotificationService.resolve_recipients); or
  * `direct_recipient_key` — notify exactly the identity named at that payload
    path, used where the event is *about* one person (lead assignment); or
  * `direct_recipient_email_key` — resolve an existing Platform Identity by the
    email at that payload path (invitation received). If no identity exists yet,
    nothing is created: the invitee is not a platform user, and inventing an
    out-of-band delivery channel is Post-MVP (Messaging is Conditional MVP).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core import permissions as perm
from platform_core.models import PlatformIdentity
from platform_core.services.notification import NotificationService


@dataclass(frozen=True)
class NotificationRule:
    notification_type: str
    title: str
    category: str = "operational"
    severity: str = "info"
    required_permission: str | None = None
    direct_recipient_key: str | None = None
    direct_recipient_email_key: str | None = None
    resource_type: str | None = None
    resource_id_key: str | None = None
    location_id_key: str | None = None
    body_keys: tuple[str, ...] = field(default_factory=tuple)


# Doc 11 §17.7 Stage 7 scope: the launch set of notification-worthy events.
NOTIFICATION_RULES: dict[str, NotificationRule] = {
    # --- Access (Team & Invitations) -----------------------------------
    "invitation.created": NotificationRule(
        notification_type="invitation.received",
        title="You have been invited to join a business",
        category="access",
        direct_recipient_email_key="invited_email",
        resource_type="invitation",
        resource_id_key="invitation_id",
    ),
    "invitation.accepted": NotificationRule(
        notification_type="invitation.accepted",
        title="An invitation was accepted",
        category="access",
        required_permission=perm.TEAM_READ,
        resource_type="invitation",
        resource_id_key="invitation_id",
    ),
    # --- Orders ---------------------------------------------------------
    "order.created": NotificationRule(
        notification_type="order.placed",
        title="New order placed",
        required_permission=perm.ORDERS_READ,
        resource_type="order",
        resource_id_key="order_id",
        location_id_key="location_id",
        body_keys=("after.order_number", "after.total_amount", "after.items"),
    ),
    "order.cancelled": NotificationRule(
        notification_type="order.cancelled",
        title="An order was cancelled",
        severity="warning",
        required_permission=perm.ORDERS_READ,
        resource_type="order",
        resource_id_key="order_id",
        location_id_key="location_id",
        body_keys=("after.order_number", "after.total_amount", "after.items"),
    ),
    "order.completed": NotificationRule(
        notification_type="order.completed",
        title="An order was completed",
        required_permission=perm.ORDERS_READ,
        resource_type="order",
        resource_id_key="order_id",
        location_id_key="location_id",
        body_keys=("after.order_number", "after.total_amount", "after.items"),
    ),
    # --- Bookings -------------------------------------------------------
    "booking.created": NotificationRule(
        notification_type="booking.created",
        title="New booking received",
        required_permission=perm.BOOKINGS_READ,
        resource_type="booking",
        resource_id_key="booking_id",
        location_id_key="location_id",
    ),
    "booking.cancelled": NotificationRule(
        notification_type="booking.cancelled",
        title="A booking was cancelled",
        severity="warning",
        required_permission=perm.BOOKINGS_READ,
        resource_type="booking",
        resource_id_key="booking_id",
        location_id_key="location_id",
    ),
    # --- Leads ----------------------------------------------------------
    "lead.assigned": NotificationRule(
        notification_type="lead.assigned",
        title="A lead was assigned to you",
        direct_recipient_key="after.assignee_identity_id",
        resource_type="lead",
        resource_id_key="lead_id",
    ),
    # --- Memberships ----------------------------------------------------
    "membership.enrolment.expired": NotificationRule(
        notification_type="membership.expired",
        title="A membership has expired",
        severity="warning",
        required_permission=perm.MEMBERSHIPS_READ,
        resource_type="membership_enrolment",
        resource_id_key="enrolment_id",
    ),
    # --- Modules & Entitlements (platform) ------------------------------
    "module.enabled": NotificationRule(
        notification_type="module.enabled",
        title="A module was activated",
        category="platform",
        required_permission=perm.MODULES_READ,
        resource_type="module",
    ),
    "module.deactivated": NotificationRule(
        notification_type="module.deactivated",
        title="A module was deactivated",
        category="platform",
        severity="warning",
        required_permission=perm.MODULES_READ,
        resource_type="module",
    ),
    "entitlement.updated": NotificationRule(
        notification_type="entitlement.updated",
        title="Business entitlements changed",
        category="commercial",
        required_permission=perm.COMMERCIAL_READ,
        resource_type="entitlement",
    ),
    "business.suspended": NotificationRule(
        notification_type="business.suspended",
        title="This business has been suspended",
        category="commercial",
        severity="critical",
        required_permission=perm.COMMERCIAL_READ,
        resource_type="business",
    ),
    # --- Payments -------------------------------------------------------
    "payment.confirmation_requested": NotificationRule(
        notification_type="payment.confirmation_requested",
        title="A customer says they paid by UPI — check it arrived",
        category="commercial",
        severity="warning",
        required_permission=perm.PAYMENTS_COLLECT,
        resource_type="payment",
        resource_id_key="payment_id",
    ),
    "payment.paid_twice": NotificationRule(
        notification_type="payment.paid_twice",
        title="A payment link was paid twice — a refund is due",
        category="commercial",
        severity="warning",
        required_permission=perm.PAYMENTS_READ,
        resource_type="payment",
        resource_id_key="payment_id",
    ),
    "payment.failed": NotificationRule(
        notification_type="payment.failed",
        title="A payment failed",
        category="commercial",
        severity="warning",
        required_permission=perm.PAYMENTS_READ,
        resource_type="payment",
        resource_id_key="payment_id",
    ),
}


def _dig(payload: dict[str, Any], path: str) -> Any:
    """Read a dotted path out of an event payload, tolerating missing branches."""
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _body(rule: NotificationRule, payload: dict[str, Any]) -> str | None:
    """The line under the title that says which one: "ORD-754794E1 · ₹320 ·
    2 items" — read from the event (a "New order placed" with nothing else
    made the owner open each to find out)."""
    parts: list[str] = []
    for key in rule.body_keys:
        value = _dig(payload, key)
        if value in (None, "", []):
            continue
        if key.endswith("_amount"):
            try:
                parts.append(f"₹{float(value):,.0f}")
            except (TypeError, ValueError):
                continue
        elif isinstance(value, list):
            parts.append(f"{len(value)} item{'' if len(value) == 1 else 's'}")
        else:
            parts.append(str(value))
    return " · ".join(parts)[:300] or None


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str) and value:
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


class NotificationDispatcher:
    @staticmethod
    async def _identity_by_email(
        session: AsyncSession, email: str
    ) -> PlatformIdentity | None:
        result = await session.execute(
            select(PlatformIdentity).where(
                func.lower(PlatformIdentity.email) == email.strip().lower()
            )
        )
        return result.scalars().first()

    @staticmethod
    async def dispatch(
        session: AsyncSession,
        *,
        event_type: str,
        payload: dict[str, Any],
        business_id: uuid.UUID | None,
        correlation_id: str | None,
    ) -> int:
        """Create notifications for one published event. Returns the count."""
        rule = NOTIFICATION_RULES.get(event_type)
        if rule is None or business_id is None:
            return 0

        resource_id = (
            _as_uuid(_dig(payload, rule.resource_id_key)) if rule.resource_id_key else None
        )
        location_id = (
            _as_uuid(_dig(payload, rule.location_id_key)) if rule.location_id_key else None
        )
        if location_id is None and rule.location_id_key:
            location_id = _as_uuid(_dig(payload, f"after.{rule.location_id_key}"))

        common: dict[str, Any] = {
            "business_id": business_id,
            "notification_type": rule.notification_type,
            "title": rule.title,
            "body": _body(rule, payload),
            "category": rule.category,
            "severity": rule.severity,
            "resource_type": rule.resource_type,
            "resource_id": resource_id,
            "location_id": location_id,
            "payload": payload,
            "correlation_id": correlation_id,
        }

        # 1. Directed at one identity named in the payload.
        if rule.direct_recipient_key is not None:
            identity_id = _as_uuid(_dig(payload, rule.direct_recipient_key))
            if identity_id is None:
                return 0
            await NotificationService.create(
                session, recipient_identity_id=identity_id, **common
            )
            return 1

        # 2. Directed at an existing Platform Identity resolved by email.
        if rule.direct_recipient_email_key is not None:
            email = _dig(payload, rule.direct_recipient_email_key)
            if not isinstance(email, str) or not email:
                return 0
            identity = await NotificationDispatcher._identity_by_email(session, email)
            if identity is None:
                return 0
            await NotificationService.create(
                session, recipient_identity_id=identity.id, **common
            )
            return 1

        # 3. Fan out by permission.
        created = await NotificationService.fan_out(
            session, required_permission=rule.required_permission, **common
        )
        return len(created)
