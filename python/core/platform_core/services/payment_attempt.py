"""Payment attempt service (Stage 9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceStateDenied, ValidationError
from platform_core.gates import assert_business_accepts_commerce, assert_business_mutable
from platform_core.models import PaymentAttempt
from platform_core.resolvers.booking_resolver import BookingResolver
from platform_core.resolvers.customer_resolver import CustomerResolver
from platform_core.resolvers.order_resolver import OrderResolver
from platform_core.resolvers.payment_resolver import PaymentResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService
from platform_core.validation.payment import assert_transition_allowed, validate_create_payment_payload


class PaymentAttemptService:
    @staticmethod
    def serialize(payment: PaymentAttempt) -> dict[str, Any]:
        return cast(dict[str, Any], PaymentResolver.serialize_attempt(payment))

    @staticmethod
    async def _validate_source(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        source_type: str,
        source_id: uuid.UUID,
        amount: Decimal,
        customer_contact_id: uuid.UUID | None,
    ) -> tuple[str, uuid.UUID | None]:
        if source_type == "order":
            order = await OrderResolver.resolve(
                session, business_id=business_id, order_id=source_id
            )
            if Decimal(str(order.total_amount)) < amount:
                raise ValidationError(
                    "Payment amount exceeds order total",
                    details={"order_total": float(order.total_amount), "amount": float(amount)},
                )
            return order.currency, order.customer_contact_id
        if source_type == "booking":
            booking = await BookingResolver.resolve(
                session, business_id=business_id, booking_id=source_id
            )
            return "INR", booking.customer_contact_id
        if source_type == "membership":
            from platform_core.resolvers.membership_resolver import MembershipResolver

            enrolment = await MembershipResolver.resolve_enrolment(
                session, business_id=business_id, enrolment_id=source_id
            )
            return "INR", enrolment.customer_contact_id
        raise ValidationError("Unsupported payment source")

    @staticmethod
    async def _sync_source_payment_status(
        session: AsyncSession,
        payment: PaymentAttempt,
    ) -> None:
        if payment.source_type == "order":
            order = await OrderResolver.resolve(
                session, business_id=payment.business_id, order_id=payment.source_id
            )
            if payment.status == "succeeded":
                from platform_core.services.payment_collect import PaymentCollectService

                order.payment_status = await PaymentCollectService.paid_status(
                    session, payment, Decimal(str(order.total_amount))) or "paid"
                if order.payment_status == "paid":
                    await PaymentCollectService.close_intents(session, payment)
            elif payment.status == "pending_offline" and order.payment_status not in {"paid", "partially_paid"}:
                order.payment_status = "pending_offline"
            elif payment.status in {"refunded", "partially_refunded"}:
                order.payment_status = await PaymentAttemptService._after_refund(session, payment,
                                                                                 order.payment_status)
            elif payment.status in {"failed", "cancelled"}:
                # A failed try never undoes money already taken (an advance stays paid).
                order.payment_status = await PaymentAttemptService._after_failure(
                    session, payment, Decimal(str(order.total_amount)))
            order.version += 1
        elif payment.source_type == "booking":
            booking = await BookingResolver.resolve(
                session, business_id=payment.business_id, booking_id=payment.source_id
            )
            if payment.status == "succeeded" and booking.total_amount is not None and payment.purpose:
                from platform_core.services.payment_collect import PaymentCollectService

                state = await PaymentCollectService.paid_status(session, payment, Decimal(str(booking.total_amount)))
                booking.payment_status = ("deposit_paid" if state == "partially_paid" and payment.purpose == "deposit"
                                          else state or booking.payment_status)
                if booking.payment_status == "paid":
                    await PaymentCollectService.close_intents(session, payment)
            elif payment.status == "succeeded":
                # Deposit attempts mark deposit_paid; full/remaining mark paid.
                meta = payment.provider_metadata or {}
                if meta.get("purpose") == "deposit" or (
                    booking.deposit_required
                    and float(payment.amount) <= float(booking.deposit_amount or 0)
                    and booking.payment_status != "paid"
                ):
                    booking.payment_status = "deposit_paid"
                else:
                    booking.payment_status = "paid"
            elif payment.status == "pending_offline" and booking.payment_status not in {
                    "paid", "partially_paid", "deposit_paid"}:
                booking.payment_status = "pending_offline"
            elif payment.status in {"refunded", "partially_refunded"}:
                booking.payment_status = await PaymentAttemptService._after_refund(session, payment,
                                                                                   booking.payment_status)
            elif payment.status in {"failed", "cancelled"}:
                if booking.payment_status not in {"paid", "partially_paid", "deposit_paid"}:
                    booking.payment_status = await PaymentAttemptService._after_failure(
                        session, payment,
                        Decimal(str(booking.total_amount)) if booking.total_amount is not None else None)
            booking.version += 1
        elif payment.source_type == "membership":
            from platform_core.resolvers.membership_resolver import MembershipResolver

            enrolment = await MembershipResolver.resolve_enrolment(
                session, business_id=payment.business_id, enrolment_id=payment.source_id
            )
            if payment.status == "succeeded":
                # Memberships decides what the money means: which period or
                # instalment it pays, once (a replay applies nothing).
                from platform_core.memberships.service import MembershipCore
                from platform_core.services.payment_collect import PaymentCollectService

                await MembershipCore.apply_payment(session, payment)
                if enrolment.payment_status == "paid":
                    await PaymentCollectService.close_intents(session, payment)
            elif payment.status == "pending_offline" and enrolment.payment_status not in {"paid", "partially_paid"}:
                enrolment.payment_status = "pending_offline"
            elif payment.status in {"refunded", "partially_refunded"}:
                enrolment.payment_status = await PaymentAttemptService._after_refund(session, payment,
                                                                                     enrolment.payment_status)
            elif payment.status in {"failed", "cancelled"}:
                from platform_core.memberships.service import MembershipCore

                charged = await MembershipCore.charged(session, enrolment)
                enrolment.payment_status = await PaymentAttemptService._after_failure(
                    session, payment, charged if charged > 0 else None)
            enrolment.version += 1

    @staticmethod
    async def _timeline(session: AsyncSession, payment: PaymentAttempt) -> None:
        """Verified money on the customer's page, next to the order it paid for."""
        if payment.customer_contact_id is None or payment.source_type not in ("order", "booking", "membership"):
            return
        from platform_core.services.customer_timeline import CustomerTimelineService
        from platform_core.services.payment_collect import PURPOSES, PaymentCollectService

        try:
            label = (await PaymentCollectService.source(session, payment.business_id, payment.source_type,
                                                        payment.source_id)).label
        except Exception:  # noqa: BLE001 - the label is decoration only
            label = payment.source_type
        await CustomerTimelineService.record_entry(
            session, business_id=payment.business_id, contact_id=payment.customer_contact_id,
            activity_type="payment.received", resource_type=payment.source_type, resource_id=payment.source_id,
            summary={"amount": float(payment.amount), "for": label,
                     "purpose_label": PURPOSES.get(str(payment.purpose or ""), None),
                     "method_label": PaymentCollectService._attempt_row(payment)["method_label"]})

    @staticmethod
    async def _after_failure(session: AsyncSession, payment: PaymentAttempt, total: Decimal | None) -> str:
        from platform_core.services.payment_collect import PaymentCollectService

        return await PaymentCollectService.paid_status(session, payment, total) or "pending"

    @staticmethod
    async def _after_refund(session: AsyncSession, payment: PaymentAttempt, current: str) -> str:
        """Refunded only when nothing is left after refunds; a part refund keeps
        the transaction's paid state (the money view shows "Part refunded")."""
        from platform_core.services.payment_collect import PaymentCollectService

        net = await PaymentCollectService.net_paid(session, payment.business_id, payment.source_type,
                                                   payment.source_id)
        return "refunded" if net <= 0 else current

    @staticmethod
    async def _publish_status(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        payment: PaymentAttempt,
        actor_id: uuid.UUID | None,
        correlation_id: str,
        event_type: str,
        audit_action: str,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any],
    ) -> None:
        payload: dict[str, Any] = {
            "business_id": str(business_id),
            "payment_id": str(payment.id),
            "source_type": payment.source_type,
            "source_id": str(payment.source_id),
            "amount": float(payment.amount),
            "status": payment.status,
            "after": after_state,
        }
        await OutboxService.publish(
            session,
            event_type=event_type,
            payload=payload,
            business_id=business_id,
            correlation_id=correlation_id,
        )
        if actor_id is not None:
            await AuditService.record(
                session,
                event_type=event_type,
                actor_identity_id=actor_id,
                actor_context="business",
                business_id=business_id,
                resource_type="payment",
                resource_id=payment.id,
                action=audit_action,
                before_state=before_state,
                after_state=after_state,
            )

    @staticmethod
    async def list_for_business(
        session: AsyncSession,
        business_id: uuid.UUID,
        *,
        status: str | None = None,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
        limit: int | None = None,
    ) -> list[PaymentAttempt]:
        query = select(PaymentAttempt).where(
            PaymentAttempt.business_id == business_id,
            PaymentAttempt.deleted_at.is_(None),
        )
        if status:
            query = query.where(PaymentAttempt.status == status)
        if source_type:
            query = query.where(PaymentAttempt.source_type == source_type)
        if source_id:
            query = query.where(PaymentAttempt.source_id == source_id)
        query = query.order_by(PaymentAttempt.created_at.desc())
        if limit:
            query = query.limit(limit)
        return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def _attach_online_provider(
        session: AsyncSession,
        payment: PaymentAttempt,
    ) -> PaymentAttempt:
        """Create a Razorpay Route order when this Business is on platform payments.

        Legacy merchant-key connections and missing connections stay on the
        existing stub/processing path. COD is never routed here.
        """
        from decimal import Decimal

        from platform_core.payments.razorpay import create_route_order, platform_credentials

        merchant = await PaymentResolver.resolve_merchant(
            session, business_id=payment.business_id, provider="razorpay"
        )
        if merchant is None or merchant.status != "active":
            return payment
        metadata = merchant.provider_metadata or {}
        if str(metadata.get("connection_mode") or "") != "platform_route":
            return payment
        linked = str(metadata.get("linked_account_id") or "").strip()
        if not linked:
            return payment

        creds = platform_credentials()
        result = await create_route_order(
            amount=Decimal(str(payment.amount)),
            currency=payment.currency,
            receipt=str(payment.id).replace("-", "")[:40],
            linked_account_id=linked,
            notes={
                "locah_payment_id": str(payment.id),
                "business_id": str(payment.business_id),
            },
        )
        payment.provider = "razorpay"
        if not result.ok:
            payment.status = "failed"
            payment.failure_code = "provider_unavailable"
            payment.failure_reason = result.detail
            payment.provider_metadata = {"connection_mode": "platform_route"}
            await session.flush()
            return payment
        payment.provider_reference = result.order_id
        payment.provider_metadata = {
            "connection_mode": "platform_route",
            "razorpay_order_id": result.order_id,
            "linked_account_id": linked,
            "checkout_key_id": creds.key_id if creds else None,
            "gross_amount": float(payment.amount),
            "platform_fee": result.platform_fee_paise / 100.0,
            "business_amount": result.transfer_paise / 100.0,
        }
        await session.flush()
        return payment

    @staticmethod
    async def create_attempt(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> PaymentAttempt:
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="create payment")
        # Doc 04 §6.1: a suspended Business cannot receive orders. Standing
        # (`status`) is a separate axis from lifecycle (`state`) — both apply.
        assert_business_accepts_commerce(business.status, action="create payment")
        validated = validate_create_payment_payload(payload)

        if validated["idempotency_key"]:
            existing = await session.execute(
                select(PaymentAttempt).where(
                    PaymentAttempt.business_id == business_id,
                    PaymentAttempt.idempotency_key == validated["idempotency_key"],
                    PaymentAttempt.deleted_at.is_(None),
                )
            )
            found = existing.scalars().first()
            if found:
                return found

        currency, source_customer_id = await PaymentAttemptService._validate_source(
            session,
            business_id=business_id,
            source_type=validated["source_type"],
            source_id=validated["source_id"],
            amount=validated["amount"],
            customer_contact_id=validated["customer_contact_id"],
        )
        customer_id = validated["customer_contact_id"] or source_customer_id
        if customer_id:
            await CustomerResolver.resolve(
                session, business_id=business_id, contact_id=customer_id
            )

        if validated["payment_method"] == "online":
            initial_status = "processing"
        else:
            initial_status = "pending_offline"

        payment = PaymentAttempt(
            business_id=business_id,
            customer_contact_id=customer_id,
            source_type=validated["source_type"],
            source_id=validated["source_id"],
            amount=float(validated["amount"]),
            currency=validated.get("currency") or currency,
            payment_method=validated["payment_method"],
            status=initial_status,
            provider="stub",
            idempotency_key=validated["idempotency_key"],
        )
        session.add(payment)
        await session.flush()
        if validated["payment_method"] == "online":
            payment = await PaymentAttemptService._attach_online_provider(
                session, payment
            )
        await PaymentAttemptService._sync_source_payment_status(session, payment)
        after = PaymentAttemptService.serialize(payment)
        await PaymentAttemptService._publish_status(
            session,
            business_id=business_id,
            payment=payment,
            actor_id=actor_id,
            correlation_id=correlation_id,
            event_type="payment.initiated",
            audit_action="initiated",
            before_state=None,
            after_state=after,
        )
        return payment

    @staticmethod
    async def apply_status(
        session: AsyncSession,
        *,
        payment: PaymentAttempt,
        target_status: str,
        correlation_id: str,
        actor_id: uuid.UUID | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        provider_reference: str | None = None,
    ) -> PaymentAttempt:
        if payment.status == target_status:
            # A replayed provider event or a second click: the state already is
            # this, so nothing moves twice (Founder refinement: Payments 15).
            return payment
        if payment.status in {"failed", "expired", "cancelled"} and payment.payment_method != "online":
            # Only a provider can report a late success; a written-off UPI or
            # counter payment stays written off.
            raise ResourceStateDenied("payment", payment.status, action="update payment status",
                                      allowed_states=[])
        assert_transition_allowed(payment.status, target_status, action="update payment status")
        before = PaymentAttemptService.serialize(payment)
        payment.status = target_status
        if failure_code:
            payment.failure_code = failure_code
        if failure_reason:
            payment.failure_reason = failure_reason
        if provider_reference:
            payment.provider_reference = provider_reference
        payment.version += 1
        if target_status == "succeeded" and payment.verified_at is None:
            payment.verified_at = datetime.now(timezone.utc)
        await session.flush()
        await PaymentAttemptService._sync_source_payment_status(session, payment)
        if target_status == "succeeded":
            from platform_core.services.payment_collect import PaymentCollectService

            await PaymentCollectService.settle(session, payment, actor_id)
            await PaymentAttemptService._timeline(session, payment)
        after = PaymentAttemptService.serialize(payment)
        event_map = {
            "succeeded": "payment.completed",
            "failed": "payment.failed",
            "pending_offline": "payment.initiated",
        }
        event_type = event_map.get(target_status, "payment.updated")
        await PaymentAttemptService._publish_status(
            session,
            business_id=payment.business_id,
            payment=payment,
            actor_id=actor_id,
            correlation_id=correlation_id,
            event_type=event_type,
            audit_action=target_status,
            before_state=before,
            after_state=after,
        )
        return payment

    @staticmethod
    async def record_offline_settlement(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        payment_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        expected_version: int | None = None,
    ) -> PaymentAttempt:
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="record payment settlement")
        payment = await PaymentResolver.resolve_attempt(
            session, business_id=business_id, payment_id=payment_id
        )
        if expected_version is not None and payment.version != expected_version:
            raise ConflictError(
                "Stale payment version",
                details={
                    "expected_version": expected_version,
                    "current_version": payment.version,
                },
            )
        if payment.status != "pending_offline":
            raise ValidationError(
                "Only offline payments awaiting settlement can be recorded",
                details={"status": payment.status},
            )
        if payment.source_type in ("order", "booking", "membership"):
            # Cash collected on delivery or at the counter settles what is still
            # due — an advance already paid by link is not taken twice (§10).
            from platform_core.services.payment_collect import PaymentCollectService

            view = await PaymentCollectService.money(session, business_id, payment.source_type, payment.source_id)
            if view["balance"] is not None:
                balance = Decimal(str(view["balance"]))
                if balance <= 0:
                    raise ValidationError("Nothing is left to collect — this is already paid",
                                          details={"code": "nothing_due"})
                if Decimal(str(payment.amount)) > balance:
                    await AuditService.record(
                        session, event_type="payment.amount_adjusted", actor_identity_id=actor_id,
                        actor_context="business", action="adjust", business_id=business_id,
                        resource_type="payment_attempt", resource_id=payment.id,
                        before_state={"amount": float(payment.amount)},
                        after_state={"amount": float(balance), "reason": "part already paid"})
                    payment.amount = float(balance)
        return await PaymentAttemptService.apply_status(
            session,
            payment=payment,
            target_status="succeeded",
            correlation_id=correlation_id,
            actor_id=actor_id,
        )

    @staticmethod
    async def export_payments(
        session: AsyncSession,
        business_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        payments = await PaymentAttemptService.list_for_business(session, business_id)
        return [PaymentAttemptService.serialize(p) for p in payments]
