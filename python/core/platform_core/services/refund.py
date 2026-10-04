"""Refund service (Stage 9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError
from platform_core.gates import assert_business_mutable
from platform_core.models import PaymentAttempt, PaymentRefund
from platform_core.payments.refunds import refundable_by_provider, request_refund
from platform_core.resolvers.payment_resolver import PaymentResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService
from platform_core.services.payment_attempt import PaymentAttemptService
from platform_core.validation.payment import REFUNDABLE_STATUSES, validate_refund_payload


class RefundService:
    @staticmethod
    def serialize(refund: PaymentRefund) -> dict[str, Any]:
        return cast(dict[str, Any], PaymentResolver.serialize_refund(refund))

    @staticmethod
    async def list_for_payment(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        payment_id: uuid.UUID,
    ) -> list[PaymentRefund]:
        await PaymentResolver.resolve_attempt(
            session, business_id=business_id, payment_id=payment_id
        )
        result = await session.execute(
            select(PaymentRefund).where(
                PaymentRefund.business_id == business_id,
                PaymentRefund.payment_attempt_id == payment_id,
            ).order_by(PaymentRefund.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_refund(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        payment_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> tuple[PaymentRefund, PaymentAttempt]:
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="refund payment")
        payment = await PaymentResolver.resolve_attempt(
            session, business_id=business_id, payment_id=payment_id
        )
        # Lock the payment before working out what is left to refund: two refunds
        # at the same moment must not both see the full amount (120% of a payment
        # was recordable). The second waits, then sees the first.
        payment = (
            await session.execute(
                select(PaymentAttempt)
                .where(PaymentAttempt.id == payment.id, PaymentAttempt.business_id == business_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars().one()
        key = str(payload.get("idempotency_key") or "").strip()[:80] or None
        if key is not None:
            # A retried or double-clicked request: the refund it already made.
            # Checked before the version, which the first attempt moved on.
            done = (await session.execute(select(PaymentRefund).where(
                PaymentRefund.business_id == business_id, PaymentRefund.payment_attempt_id == payment.id,
                PaymentRefund.idempotency_key == key))).scalars().first()
            if done is not None:
                cent = Decimal("0.01")
                if Decimal(str(done.amount)).quantize(cent) != Decimal(str(payload.get("amount"))).quantize(cent):
                    raise ConflictError("This refund request was already used for a different amount",
                                        details={"refund_id": str(done.id)})
                return done, payment
        if expected_version is not None and payment.version != expected_version:
            raise ConflictError(
                "Stale payment version",
                details={
                    "expected_version": expected_version,
                    "current_version": payment.version,
                },
            )
        if payment.status not in REFUNDABLE_STATUSES:
            raise ConflictError(
                "Payment is not refundable",
                details={"status": payment.status},
            )
        max_refundable = Decimal(str(payment.amount)) - Decimal(str(payment.refunded_amount))
        validated = validate_refund_payload(payload, max_amount=max_refundable)
        before_payment = PaymentAttemptService.serialize(payment)
        # An online payment a provider collected is refunded THROUGH the provider
        # (unless the owner says they gave it back themselves); anything else is
        # money the owner handed back, recorded here.
        through_provider = refundable_by_provider(payment) and not bool(payload.get("manual"))
        refund = PaymentRefund(
            business_id=business_id,
            payment_attempt_id=payment.id,
            amount=float(validated["amount"]),
            status="requested" if through_provider else "succeeded",
            kind="provider" if through_provider else "recorded",
            reason=validated["reason"],
            idempotency_key=key,
            completed_at=None if through_provider else datetime.now(timezone.utc),
        )
        session.add(refund)
        await session.flush()
        if through_provider:
            asked = await request_refund(payment, amount=validated["amount"], refund_id=refund.id,
                                         reason=validated["reason"])
            refund.provider_reference = asked.reference
            if not asked.accepted:
                # Nothing moved: the provider refused. Kept with its words; no amount reserved.
                refund.status = "failed"
                refund.failure_reason = asked.detail
                refund.completed_at = datetime.now(timezone.utc)
                await session.flush()
                await AuditService.record(
                    session, event_type="payment.refund_failed", actor_identity_id=actor_id,
                    actor_context="business", business_id=business_id, resource_type="payment_refund",
                    resource_id=refund.id, action="refund_refused",
                    before_state={"payment": before_payment},
                    after_state={"refund": RefundService.serialize(refund)})
                return refund, payment
            refund.status = asked.status
            if asked.status == "succeeded":
                refund.completed_at = datetime.now(timezone.utc)
        # The amount is spoken for from the moment the provider accepts the refund,
        # so a second refund can never exceed what was paid; a failure releases it.
        payment.refunded_amount = float(
            Decimal(str(payment.refunded_amount)) + validated["amount"]
        )
        new_refunded = Decimal(str(payment.refunded_amount))
        if new_refunded >= Decimal(str(payment.amount)):
            payment.status = "refunded"
            if payment.attention == "refund_due":
                payment.attention = None  # the cancelled order's money is back with the customer
        else:
            payment.status = "partially_refunded"
        payment.version += 1
        await session.flush()
        await PaymentAttemptService._sync_source_payment_status(session, payment)
        after_payment = PaymentAttemptService.serialize(payment)
        done = refund.status == "succeeded"
        refund_payload = {
            "business_id": str(business_id),
            "payment_id": str(payment.id),
            "refund_id": str(refund.id),
            "amount": float(refund.amount),
            "payment_status": payment.status,
            "kind": refund.kind,
        }
        await OutboxService.publish(
            session,
            event_type="payment.refunded" if done else "payment.refund_requested",
            payload=refund_payload,
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type="payment.refunded" if done else "payment.refund_requested",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="payment_refund",
            resource_id=refund.id,
            action="refunded" if done else "refund_requested",
            before_state={"payment": before_payment},
            after_state={"payment": after_payment, "refund": RefundService.serialize(refund)},
        )
        return refund, payment

    @staticmethod
    async def settle_provider_refund(
        session: AsyncSession,
        *,
        refund: PaymentRefund,
        outcome: str,
        failure_reason: str | None,
        correlation_id: str,
    ) -> str:
        """The provider's final word on a refund it accepted (a refund webhook).
        Idempotent: a refund already settled is left as it is."""
        if refund.status in ("succeeded", "failed"):
            return str(refund.status)
        payment = (await session.execute(
            select(PaymentAttempt).where(PaymentAttempt.id == refund.payment_attempt_id).with_for_update()
            .execution_options(populate_existing=True))).scalars().one()
        business = await BusinessService.get_by_id(session, payment.business_id)
        before = RefundService.serialize(refund)
        refund.completed_at = datetime.now(timezone.utc)
        if outcome == "succeeded":
            refund.status = "succeeded"
            event = "payment.refunded"
        else:
            refund.status = "failed"
            refund.failure_reason = (failure_reason or "The provider could not complete the refund")[:500]
            # Release the amount it had reserved; the owner is told on Payments.
            payment.refunded_amount = max(
                float(Decimal(str(payment.refunded_amount)) - Decimal(str(refund.amount))), 0.0)
            payment.status = "partially_refunded" if payment.refunded_amount > 0 else "succeeded"
            payment.attention = "refund_failed"
            payment.version += 1
            event = "payment.refund_failed"
        await session.flush()
        await PaymentAttemptService._sync_source_payment_status(session, payment)
        await OutboxService.publish(
            session, event_type=event,
            payload={"business_id": str(payment.business_id), "payment_id": str(payment.id),
                     "refund_id": str(refund.id), "amount": float(refund.amount),
                     "payment_status": payment.status, "kind": refund.kind},
            business_id=payment.business_id, correlation_id=correlation_id)
        await AuditService.record(
            session, event_type=event, actor_identity_id=business.primary_owner_identity_id,
            actor_context="system", business_id=payment.business_id, resource_type="payment_refund",
            resource_id=refund.id, action="provider_settled", before_state={"refund": before},
            after_state={"refund": RefundService.serialize(refund), "payment_status": payment.status})
        return str(refund.status)
