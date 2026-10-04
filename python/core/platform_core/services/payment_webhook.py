"""Payment webhooks: verified, kept, applied — and retried until they are.

1. **Receive.** The signature is checked first (an invalid one is refused and
   nothing is stored). The receipt is committed before anything else happens,
   and a provider's replay of the same event is answered "duplicate".
2. **Apply.** One attempt, inside a savepoint, moves the payment and through it
   the order, booking or membership. The outcome is one of:
   * ``processed`` — done;
   * ``ignored`` — nothing to apply (no payment reference, a status we do not
     act on); kept for the record, never retried;
   * ``refused`` — the payment's own rules forbid it (a written-off UPI claim
     cannot be revived); kept with the reason, never retried;
   * ``retrying`` — it could not be applied yet (the payment is not there yet
     — events can arrive before the attempt is saved — or a transient error):
     tried again with backoff by the worker;
   * ``dead_letter`` — still failing after ``max_attempts``: recorded in
     ``platform_dead_letter_events`` (the admin System page) and, when the
     payment is known, flagged for the owner on Payments.
3. **Retry lane.** The worker applies due receipts (``FOR UPDATE SKIP LOCKED``,
   so two workers never apply one receipt). Applying is idempotent: a replayed
   success pays once.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import PlatformError, ValidationError
from platform_core.logging import get_logger
from platform_core.models import PaymentAttempt, PaymentWebhookReceipt
from platform_core.payments.provider_adapter import (
    extract_event_id,
    normalize_payment_event,
    parse_webhook_payload,
    verify_webhook_signature,
)
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService
from platform_core.services.payment_attempt import PaymentAttemptService

logger = get_logger("platform_core.payment_webhook")

APPLIED_STATUSES = frozenset({"succeeded", "failed"})
# The inline attempt in the request owns a fresh receipt for this long; after
# that the retry lane may take it (a crash between the two commits is covered).
INLINE_GRACE = timedelta(minutes=2)


def backoff(attempt: int) -> timedelta:
    """The outbox's backoff: 1, 2, 4, 8 … minutes, at most an hour."""
    return timedelta(seconds=min(2**attempt * 30, 3600))


class NotYet(Exception):
    """The payment this event is about is not in LOCAH yet — try again later."""


class PaymentWebhookService:
    # ------------------------------------------------------------------ receive
    @staticmethod
    async def receive(
        session: AsyncSession,
        *,
        provider: str,
        raw_body: bytes,
        headers: dict[str, str],
        correlation_id: str,
    ) -> tuple[uuid.UUID, str, bool]:
        """(receipt id, provider event id, duplicate). The caller commits."""
        if not verify_webhook_signature(provider, raw_body, headers):
            # AUD-11: signature rejections are a security event. The redaction
            # processor scrubs any signature/secret values before this ships.
            logger.warning(
                "payment_webhook.signature_rejected",
                provider=provider,
                correlation_id=correlation_id,
                body_bytes=len(raw_body),
            )
            raise ValidationError("Invalid webhook signature", details={"provider": provider})
        payload = parse_webhook_payload(raw_body)
        event_id = extract_event_id(provider, payload)
        existing = (await session.execute(select(PaymentWebhookReceipt).where(
            PaymentWebhookReceipt.provider == provider,
            PaymentWebhookReceipt.provider_event_id == event_id,
        ))).scalars().first()
        if existing is not None:
            return existing.id, event_id, True
        receipt = PaymentWebhookReceipt(
            provider=provider, provider_event_id=event_id, raw_payload=payload, status="received",
            next_attempt_at=datetime.now(timezone.utc) + INLINE_GRACE,
        )
        session.add(receipt)
        await session.flush()
        return receipt.id, event_id, False

    # ------------------------------------------------------------------ apply
    @staticmethod
    async def apply_receipt(session: AsyncSession, receipt_id: uuid.UUID, *, correlation_id: str) -> dict[str, Any]:
        """Lock the receipt and make one attempt. The caller commits."""
        receipt = (await session.execute(
            select(PaymentWebhookReceipt).where(PaymentWebhookReceipt.id == receipt_id).with_for_update()
        )).scalars().first()
        if receipt is None:
            return {"status": "missing"}
        if receipt.status not in ("received", "retrying"):
            return {"status": receipt.status, "event_id": receipt.provider_event_id,
                    "reason": receipt.failure_reason}
        return await PaymentWebhookService._attempt(session, receipt, correlation_id=correlation_id)

    @staticmethod
    async def _attempt(session: AsyncSession, receipt: PaymentWebhookReceipt, *, correlation_id: str) -> dict[str, Any]:
        provider, event_id = receipt.provider, receipt.provider_event_id
        receipt.attempt_count = int(receipt.attempt_count or 0) + 1
        receipt.updated_at = datetime.now(timezone.utc)
        await session.flush()  # the attempt counts even if what follows rolls back
        payload = dict(receipt.raw_payload or {})
        event = normalize_payment_event(provider, payload)
        if event.get("refund_reference"):
            return await PaymentWebhookService._attempt_refund(session, receipt, event, correlation_id=correlation_id)
        target = str(event.get("status") or "").lower()
        if not (event.get("payment_id") or event.get("order_id")) or not target:
            return await PaymentWebhookService._close(receipt, "ignored", "Missing payment_id/order_id or status")
        if target not in APPLIED_STATUSES:
            return await PaymentWebhookService._close(receipt, "ignored", f"Unsupported status: {target}")
        try:
            async with session.begin_nested():
                payment = await PaymentWebhookService._find_payment(session, event)
                if payment is None:
                    raise NotYet("Payment not found yet")
                payment_id = payment.id
                await PaymentWebhookService._apply(session, receipt, payment, payload, event, target,
                                                   correlation_id=correlation_id)
        except NotYet as exc:
            return await PaymentWebhookService._retry(session, receipt, str(exc), payment_id=None)
        except PlatformError as exc:
            # The payment's own rules refuse this: retrying would refuse again.
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            reason = str(detail.get("message") or exc)
            logger.warning("payment_webhook.refused", provider=provider, event_id=event_id, reason=reason,
                           correlation_id=correlation_id)
            return await PaymentWebhookService._close(receipt, "failed", reason, refused=True)
        except Exception as exc:  # noqa: BLE001 — anything else is worth another try
            logger.error("payment_webhook.processing_failed", provider=provider, event_id=event_id,
                         correlation_id=correlation_id, exc_info=exc)
            payment = await PaymentWebhookService._find_payment(session, event)
            return await PaymentWebhookService._retry(session, receipt, f"{type(exc).__name__}: {exc}",
                                                      payment_id=payment.id if payment else None)
        receipt.status = "processed"
        receipt.processed_at = datetime.now(timezone.utc)
        receipt.payment_attempt_id = payment_id
        receipt.next_attempt_at = None
        receipt.last_error = None
        await session.flush()
        return {"status": "processed", "event_id": event_id, "payment_id": str(payment_id)}

    @staticmethod
    async def _attempt_refund(session: AsyncSession, receipt: PaymentWebhookReceipt, event: dict[str, Any], *,
                              correlation_id: str) -> dict[str, Any]:
        """The provider's outcome for a refund LOCAH asked it to make."""
        from platform_core.models import PaymentRefund
        from platform_core.services.refund import RefundService

        outcome = {"succeeded": "succeeded", "processed": "succeeded", "failed": "failed"}.get(
            str(event.get("refund_status") or "").lower())
        if outcome is None:
            return await PaymentWebhookService._close(receipt, "ignored", "Refund event without a final status")
        reference = str(event["refund_reference"])
        try:
            async with session.begin_nested():
                refund = (await session.execute(select(PaymentRefund).where(
                    PaymentRefund.provider_reference == reference))).scalars().first()
                if refund is None:
                    raise NotYet("Refund not found yet")
                payment_id = refund.payment_attempt_id
                settled = await RefundService.settle_provider_refund(
                    session, refund=refund, outcome=outcome, failure_reason=event.get("failure_reason"),
                    correlation_id=correlation_id)
        except NotYet as exc:
            return await PaymentWebhookService._retry(session, receipt, str(exc), payment_id=None)
        except PlatformError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            return await PaymentWebhookService._close(receipt, "failed", str(detail.get("message") or exc),
                                                      refused=True)
        except Exception as exc:  # noqa: BLE001 — anything else is worth another try
            logger.error("payment_webhook.refund_processing_failed", provider=receipt.provider,
                         event_id=receipt.provider_event_id, correlation_id=correlation_id, exc_info=exc)
            return await PaymentWebhookService._retry(session, receipt, f"{type(exc).__name__}: {exc}", payment_id=None)
        receipt.status = "processed"
        receipt.processed_at = datetime.now(timezone.utc)
        receipt.payment_attempt_id = payment_id
        receipt.next_attempt_at = None
        receipt.last_error = None
        await session.flush()
        return {"status": "processed", "event_id": receipt.provider_event_id, "refund": settled}

    @staticmethod
    async def _find_payment(session: AsyncSession, event: dict[str, Any]) -> PaymentAttempt | None:
        raw, order_ref = event.get("payment_id"), event.get("order_id")
        if raw:
            try:
                found = (await session.execute(select(PaymentAttempt).where(
                    PaymentAttempt.id == uuid.UUID(str(raw)), PaymentAttempt.deleted_at.is_(None),
                ))).scalars().first()
                if found is not None:
                    return found
            except ValueError:
                pass
        if order_ref:
            return (await session.execute(select(PaymentAttempt).where(
                PaymentAttempt.provider_reference == str(order_ref), PaymentAttempt.deleted_at.is_(None),
            ))).scalars().first()
        return None

    @staticmethod
    async def _apply(
        session: AsyncSession, receipt: PaymentWebhookReceipt, payment: PaymentAttempt, payload: dict[str, Any],
        event: dict[str, Any], target: str, *, correlation_id: str,
    ) -> None:
        business = await BusinessService.get_by_id(session, payment.business_id)
        await PaymentAttemptService.apply_status(
            session,
            payment=payment,
            target_status=target,
            correlation_id=correlation_id,
            actor_id=business.primary_owner_identity_id,
            failure_code=event.get("failure_code") or payload.get("failure_code"),
            failure_reason=event.get("failure_reason") or payload.get("failure_reason"),
            provider_reference=event.get("provider_reference") or payload.get("provider_reference"),
        )
        if target == "failed":
            logger.warning("payment.failed", provider=receipt.provider, payment_id=str(payment.id),
                           business_id=str(payment.business_id), failure_code=payload.get("failure_code"),
                           correlation_id=correlation_id)
        await OutboxService.publish(
            session,
            event_type="payment.webhook_processed",
            payload={"provider": receipt.provider, "event_id": receipt.provider_event_id,
                     "payment_id": str(payment.id), "business_id": str(payment.business_id)},
            business_id=payment.business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type="payment.webhook_processed",
            actor_identity_id=business.primary_owner_identity_id,
            actor_context="system",
            business_id=payment.business_id,
            resource_type="payment_webhook",
            resource_id=receipt.id,
            action="processed",
            before_state=None,
            after_state={"event_id": receipt.provider_event_id, "payment_id": str(payment.id),
                         "attempt": receipt.attempt_count},
        )

    @staticmethod
    async def _close(receipt: PaymentWebhookReceipt, status: str, reason: str, *,
                     refused: bool = False) -> dict[str, Any]:
        receipt.status = status
        receipt.failure_reason = reason
        receipt.processed_at = datetime.now(timezone.utc)
        receipt.next_attempt_at = None
        out = "refused" if refused else status
        return {"status": out, "event_id": receipt.provider_event_id, "reason": reason}

    @staticmethod
    async def _retry(session: AsyncSession, receipt: PaymentWebhookReceipt, error: str, *,
                     payment_id: uuid.UUID | None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        receipt.last_error = error[:2000]
        if receipt.attempt_count < int(receipt.max_attempts or 8):
            receipt.status = "retrying"
            receipt.next_attempt_at = now + backoff(receipt.attempt_count)
            logger.warning("payment_webhook.retry_scheduled", provider=receipt.provider,
                           event_id=receipt.provider_event_id, attempt=receipt.attempt_count,
                           next_attempt_at=receipt.next_attempt_at.isoformat(), error=error[:300])
            await session.flush()
            return {"status": "retrying", "event_id": receipt.provider_event_id,
                    "next_attempt_at": receipt.next_attempt_at.isoformat()}
        # Gave up: recorded where an operator looks, and on the owner's Payments.
        receipt.status = "dead_letter"
        receipt.dead_lettered_at = now
        receipt.next_attempt_at = None
        receipt.failure_reason = error[:2000]
        if payment_id is not None:
            receipt.payment_attempt_id = payment_id
        await session.flush()
        await session.execute(text(
            "INSERT INTO platform_dead_letter_events (source_table, source_id, event_type, payload, final_error, "
            "attempt_count) VALUES ('payments_webhook_receipts', :id, :event_type, CAST(:payload AS jsonb), "
            ":error, :attempts)"),
            {"id": receipt.id, "event_type": f"payment.webhook.{receipt.provider}",
             "payload": json.dumps(receipt.raw_payload or {}), "error": error[:2000],
             "attempts": receipt.attempt_count})
        if payment_id is not None:
            await session.execute(text(
                "UPDATE payments_payment_attempts SET attention = 'provider_update_failed' "
                "WHERE id = :id AND attention IS NULL"), {"id": payment_id})
        logger.error("payment_webhook.dead_lettered", provider=receipt.provider, event_id=receipt.provider_event_id,
                     attempts=receipt.attempt_count, error=error[:300])
        return {"status": "dead_letter", "event_id": receipt.provider_event_id}

    # ------------------------------------------------------------------ operator
    @staticmethod
    async def requeue(session: AsyncSession, receipt_id: uuid.UUID, *, actor_id: uuid.UUID) -> dict[str, Any]:
        """A dead-lettered receipt goes back into the retry lane (three more tries),
        once whatever made it fail is fixed. Its dead letter is marked resolved."""
        from platform_core.exceptions import ConflictError, ResourceNotFound

        receipt = (await session.execute(
            select(PaymentWebhookReceipt).where(PaymentWebhookReceipt.id == receipt_id).with_for_update()
        )).scalars().first()
        if receipt is None:
            raise ResourceNotFound("Payment webhook")
        if receipt.status != "dead_letter":
            raise ConflictError("Only a dead-lettered payment webhook can be retried",
                                details={"status": receipt.status})
        receipt.status = "retrying"
        receipt.max_attempts = int(receipt.attempt_count or 0) + 3
        receipt.next_attempt_at = datetime.now(timezone.utc)
        receipt.dead_lettered_at = None
        receipt.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await session.execute(text(
            "UPDATE platform_dead_letter_events SET resolved_at = now(), resolved_by = :actor, "
            "resolution_note = 'Requeued for retry' WHERE source_table = 'payments_webhook_receipts' "
            "AND source_id = :id AND resolved_at IS NULL"), {"actor": actor_id, "id": receipt.id})
        return {"id": str(receipt.id), "status": receipt.status, "max_attempts": receipt.max_attempts}

    # ------------------------------------------------------------------ retry lane
    @staticmethod
    async def run_due(session: AsyncSession, worker_id: str, *, limit: int = 20,
                      only: list[uuid.UUID] | None = None) -> int:
        """Apply receipts whose next try is due. Each is locked (SKIP LOCKED) and
        committed on its own, so one failure never undoes another's success.
        `only` narrows the lane to given receipts (operators, tests)."""
        done = 0
        for _ in range(limit):
            query = select(PaymentWebhookReceipt).where(
                PaymentWebhookReceipt.status.in_(("received", "retrying")),
                PaymentWebhookReceipt.next_attempt_at <= datetime.now(timezone.utc),
            )
            if only is not None:
                query = query.where(PaymentWebhookReceipt.id.in_(only))
            receipt = (await session.execute(
                query.order_by(PaymentWebhookReceipt.next_attempt_at).limit(1).with_for_update(skip_locked=True)
            )).scalars().first()
            if receipt is None:
                break
            # A fresh correlation id per retry (audit and outbox expect a UUID).
            await PaymentWebhookService._attempt(session, receipt, correlation_id=str(uuid.uuid4()))
            await session.commit()
            done += 1
        return done
