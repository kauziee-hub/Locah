"""Platform payments APIs (Stage 9)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.authorization.resolver import AuthorizationService
from platform_core.exceptions import PermissionDenied, ValidationError
from platform_core.permissions import (
    BOOKINGS_UPDATE,
    MEMBERSHIPS_MANAGE_ENROLMENT,
    ORDERS_UPDATE_STATUS,
    PAYMENTS_EXPORT,
    PAYMENTS_MANAGE_CONNECTION,
    PAYMENTS_READ,
    PAYMENTS_REFUND,
)
from platform_core.resolvers.payment_resolver import PaymentResolver
from platform_core.services.merchant import MerchantService
from platform_core.services.payment_attempt import PaymentAttemptService
from platform_core.services.payment_collect import PaymentCollectService
from platform_core.services.refund import RefundService
from platform_core.validation.payment import SOURCE_TYPES

router = APIRouter(prefix="/v1/platform/businesses", tags=["payments"])


class VersionedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)


class CreatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_id: UUID
    amount: float = Field(gt=0)
    currency: str = "INR"
    payment_method: str = "online"
    customer_contact_id: UUID | None = None
    idempotency_key: str | None = None


class RefundPaymentRequest(VersionedBody):
    amount: float = Field(gt=0)
    reason: str
    # Send the same key again (a retry, a double-click) and get the same refund back.
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=80)


class MerchantConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "stub"
    status: str = "pending"
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


# A payment attempt requires the permission for the SOURCE module, not a
# blanket payments permission — creating a payment against an order is an order
# operation. Keyed by every member of `SOURCE_TYPES`; an unmapped source type
# raises KeyError here rather than silently inheriting the wrong module's
# permission. That is how AUD-10 happened: `membership` was added to
# `SOURCE_TYPES` in Stage 6 while this mapping was a two-way `if/else` that
# defaulted membership to the Bookings permission.
_SOURCE_TYPE_PERMISSION: dict[str, str] = {
    "order": ORDERS_UPDATE_STATUS,
    "booking": BOOKINGS_UPDATE,
    "membership": MEMBERSHIPS_MANAGE_ENROLMENT,
}


async def _require_payment_create_permission(
    actor: BusinessActorContext,
    session: AsyncSession,
    source_type: str,
) -> None:
    if source_type not in SOURCE_TYPES:
        # Client-supplied garbage — a clean 422, same as the payload validator.
        raise ValidationError(
            "Unsupported source_type",
            details={"errors": [{"field": "source_type", "message": "Unsupported source"}]},
        )
    # A source type that IS valid but has no permission mapping is a developer
    # error (SOURCE_TYPES gained a member without a mapping here) — let it raise.
    permission = _SOURCE_TYPE_PERMISSION[source_type]
    decision = await AuthorizationService.authorize(
        session,
        business_id=actor.business.id,
        identity_id=actor.request.identity_id,
        permission=permission,
    )
    if not decision.allowed:
        raise PermissionDenied(permission)


@router.get("/{business_id}/payments")
async def list_payments(
    business_id: UUID,
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_READ, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    payments = await PaymentAttemptService.list_for_business(
        session,
        business_id,
        status=status,
        source_type=source_type,
        source_id=source_id,
        limit=limit,
    )
    return {
        "data": await PaymentCollectService.describe(session, business_id, payments),
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(payments)},
    }


@router.get("/{business_id}/payments/export")
async def export_payments(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_EXPORT, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    rows = await PaymentAttemptService.export_payments(session, business_id)
    return {
        "data": rows,
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(rows)},
    }


@router.get("/{business_id}/payments/merchant-connection")
async def get_merchant_connection(
    business_id: UUID,
    provider: str = Query(default="stub"),
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_READ, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    connection = await MerchantService.get_connection(
        session, business_id=business_id, provider=provider
    )
    return {
        "data": MerchantService.serialize(connection) if connection else None,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.put("/{business_id}/payments/merchant-connection")
async def upsert_merchant_connection(
    business_id: UUID,
    body: MerchantConnectionRequest,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_MANAGE_CONNECTION, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    connection = await MerchantService.upsert_connection(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": MerchantService.serialize(connection),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


class RazorpayConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(min_length=1, max_length=200)
    key_secret: str = Field(min_length=1, max_length=200)


@router.post("/{business_id}/payments/razorpay/connect")
async def connect_razorpay(
    business_id: UUID,
    body: RazorpayConnectRequest,
    actor: BusinessActorContext = Depends(
        require_business_actor(PAYMENTS_MANAGE_CONNECTION, "payments")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Store the owner's Razorpay Key ID / Key Secret (secret encrypted at
    rest), then immediately verify them with one live Razorpay call."""
    await MerchantService.connect_razorpay(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        key_id=body.key_id,
        key_secret=body.key_secret,
    )
    connection = await MerchantService.verify_connection(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {
        "data": MerchantService.serialize(connection),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/payments/razorpay/verify")
async def verify_razorpay(
    business_id: UUID,
    actor: BusinessActorContext = Depends(
        require_business_actor(PAYMENTS_MANAGE_CONNECTION, "payments")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Re-run the live credential check against the already-stored keys."""
    connection = await MerchantService.verify_connection(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {
        "data": MerchantService.serialize(connection),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/payments/razorpay/enable")
async def enable_platform_payments(
    business_id: UUID,
    actor: BusinessActorContext = Depends(
        require_business_actor(PAYMENTS_MANAGE_CONNECTION, "payments")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Onboard this Business as a Razorpay Route linked account.

    Owners never paste API keys. If Route is not enabled on the LOCAH
    Razorpay account, the response is honest and cash still works.
    """
    connection = await MerchantService.enable_platform_payments(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {
        "data": MerchantService.serialize(connection),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/payments")
async def create_payment(
    business_id: UUID,
    body: CreatePaymentRequest,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_READ, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await _require_payment_create_permission(actor, session, body.source_type)
    payment = await PaymentAttemptService.create_attempt(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": PaymentAttemptService.serialize(payment),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


class UpiBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upi_vpa: str | None = Field(default=None, max_length=320)
    upi_payee_name: str | None = Field(default=None, max_length=100)


@router.get("/{business_id}/payments/upi")
async def get_upi(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_READ, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """The UPI ID customers pay on payment links (the same one the counter uses)."""
    from platform_core.models import PosSettings

    row = await session.get(PosSettings, business_id)
    return {"data": {"upi_vpa": row.upi_vpa if row else None, "upi_payee_name": row.upi_payee_name if row else None},
            "meta": {"correlation_id": actor.request.correlation_id}}


@router.put("/{business_id}/payments/upi")
async def put_upi(
    business_id: UUID,
    body: UpiBody,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_MANAGE_CONNECTION, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    from platform_core.services.pos import PosService

    row = await PosService.set_upi(session, business_id, actor.request.identity_id, upi_vpa=body.upi_vpa,
                                   upi_payee_name=body.upi_payee_name)
    await session.commit()
    return {"data": {"upi_vpa": row.upi_vpa, "upi_payee_name": row.upi_payee_name},
            "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/payments/{payment_id}")
async def get_payment(
    business_id: UUID,
    payment_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_READ, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    payment = await PaymentResolver.resolve_attempt(
        session, business_id=business_id, payment_id=payment_id
    )
    return {
        "data": (await PaymentCollectService.describe(session, business_id, [payment]))[0],
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/payments/{payment_id}/record-settlement")
async def record_offline_settlement(
    business_id: UUID,
    payment_id: UUID,
    body: VersionedBody,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_UPDATE_STATUS, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    payment = await PaymentAttemptService.record_offline_settlement(
        session,
        business_id=business_id,
        payment_id=payment_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": PaymentAttemptService.serialize(payment),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/payments/{payment_id}/refunds")
async def create_refund(
    business_id: UUID,
    payment_id: UUID,
    body: RefundPaymentRequest,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_REFUND, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    refund, payment = await RefundService.create_refund(
        session,
        business_id=business_id,
        payment_id=payment_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload={"amount": body.amount, "reason": body.reason, "idempotency_key": body.idempotency_key},
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": {
            "refund": RefundService.serialize(refund),
            "payment": PaymentAttemptService.serialize(payment),
        },
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/payments/{payment_id}/refunds")
async def list_refunds(
    business_id: UUID,
    payment_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(PAYMENTS_READ, "payments")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    refunds = await RefundService.list_for_payment(
        session, business_id=business_id, payment_id=payment_id
    )
    return {
        "data": [RefundService.serialize(r) for r in refunds],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(refunds)},
    }
