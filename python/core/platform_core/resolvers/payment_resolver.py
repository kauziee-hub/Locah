"""Payment lookup resolver (Stage 9)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ResourceNotFound
from platform_core.models import MerchantConnection, PaymentAttempt, PaymentRefund


class PaymentResolver:
    @staticmethod
    async def resolve_attempt(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        payment_id: uuid.UUID,
    ) -> PaymentAttempt:
        result = await session.execute(
            select(PaymentAttempt).where(
                PaymentAttempt.id == payment_id,
                PaymentAttempt.business_id == business_id,
                PaymentAttempt.deleted_at.is_(None),
            )
        )
        payment = result.scalars().first()
        if payment is None:
            raise ResourceNotFound("Payment")
        return payment

    @staticmethod
    async def resolve_merchant(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        provider: str,
    ) -> MerchantConnection | None:
        result = await session.execute(
            select(MerchantConnection).where(
                MerchantConnection.business_id == business_id,
                MerchantConnection.provider == provider,
            )
        )
        return result.scalars().first()

    @staticmethod
    def serialize_attempt(payment: PaymentAttempt) -> dict[str, Any]:
        refundable = max(float(payment.amount) - float(payment.refunded_amount), 0)
        meta = payment.provider_metadata or {}
        checkout = None
        settlement = None
        if meta.get("razorpay_order_id") and meta.get("checkout_key_id"):
            checkout = {
                "provider": "razorpay",
                "order_id": meta["razorpay_order_id"],
                "key_id": meta["checkout_key_id"],
                "amount": float(payment.amount),
                "currency": payment.currency,
            }
        if meta.get("gross_amount") is not None:
            settlement = {
                "gross_amount": meta.get("gross_amount"),
                "platform_fee": meta.get("platform_fee"),
                "business_amount": meta.get("business_amount"),
                "connection_mode": meta.get("connection_mode"),
            }
        return {
            "id": str(payment.id),
            "business_id": str(payment.business_id),
            "customer_contact_id": (
                str(payment.customer_contact_id) if payment.customer_contact_id else None
            ),
            "source_type": payment.source_type,
            "source_id": str(payment.source_id),
            "amount": float(payment.amount),
            "currency": payment.currency,
            "payment_method": payment.payment_method,
            "status": payment.status,
            "provider": payment.provider,
            "provider_reference": payment.provider_reference,
            "refunded_amount": float(payment.refunded_amount),
            "refundable_amount": refundable,
            "failure_code": payment.failure_code,
            "failure_reason": payment.failure_reason,
            "checkout": checkout,
            "settlement": settlement,
            "version": payment.version,
            "created_at": payment.created_at.isoformat(),
            "updated_at": payment.updated_at.isoformat(),
        }

    @staticmethod
    def serialize_refund(refund: PaymentRefund) -> dict[str, Any]:
        return {
            "id": str(refund.id),
            "payment_attempt_id": str(refund.payment_attempt_id),
            "amount": float(refund.amount),
            "status": refund.status,
            "reason": refund.reason,
            "provider_reference": refund.provider_reference,
            "failure_reason": refund.failure_reason,
            "kind": refund.kind,
            "completed_at": refund.completed_at.isoformat() if refund.completed_at else None,
            "version": refund.version,
            "created_at": refund.created_at.isoformat(),
            "updated_at": refund.updated_at.isoformat(),
        }

    @staticmethod
    def serialize_merchant(connection: MerchantConnection) -> dict[str, Any]:
        metadata = connection.provider_metadata or {}
        stored_mode = str(metadata.get("connection_mode") or "").strip()
        if stored_mode:
            connection_mode = stored_mode
        elif metadata.get("linked_account_id"):
            connection_mode = "platform_route"
        elif connection.encrypted_credentials or metadata.get("key_id"):
            connection_mode = "merchant_keys"
        else:
            connection_mode = "unlinked"
        # Never the secret. Platform Route uses LOCAH's key — do not show it as
        # if it belonged to the owner. Legacy merchant-key mode still shows Key ID.
        key_id = None if connection_mode == "platform_route" else metadata.get("key_id")
        return {
            "id": str(connection.id),
            "business_id": str(connection.business_id),
            "provider": connection.provider,
            "status": connection.status,
            "provider_metadata": metadata,
            "key_id": key_id,
            "has_credentials": connection.encrypted_credentials is not None,
            "connection_mode": connection_mode,
            "linked_account_id": metadata.get("linked_account_id"),
            "linked_account_status": metadata.get("linked_account_status"),
            "requires_merchant_keys": connection_mode == "merchant_keys",
            "external_dependency": bool(metadata.get("external_dependency")),
            "last_verified_at": (
                connection.last_verified_at.isoformat()
                if connection.last_verified_at
                else None
            ),
            "verification_error": connection.verification_error,
            "version": connection.version,
            "created_at": connection.created_at.isoformat(),
            "updated_at": connection.updated_at.isoformat(),
        }
