"""Payment provider adapter (Stage 9).

Stub HMAC remains for tests. Razorpay uses the same HMAC-SHA256 of the raw
body, with PAYMENT_WEBHOOK_SECRET (or RAZORPAY_WEBHOOK_SECRET).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from platform_core.secrets import resolve_signing_secret


def verify_webhook_signature(
    provider: str,
    raw_body: bytes,
    headers: dict[str, str],
) -> bool:
    # Same rule as the preview secret: a committed default would let anyone
    # forge a provider callback and move a payment into a paid state.
    if provider == "stub":
        secret = resolve_signing_secret("PAYMENT_WEBHOOK_SECRET", "test-payment-webhook-secret")
        signature = headers.get("x-payment-signature") or headers.get("X-Payment-Signature")
        if not signature:
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    if provider == "razorpay":
        secret = resolve_signing_secret(
            "PAYMENT_WEBHOOK_SECRET",
            "test-payment-webhook-secret",
            fallback_env="RAZORPAY_WEBHOOK_SECRET",
        )
        signature = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature")
        if not signature:
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    return False


def extract_event_id(provider: str, payload: dict[str, Any]) -> str:
    if provider_event_id := payload.get("event_id"):
        return str(provider_event_id)
    if provider == "razorpay" and payload.get("id"):
        return str(payload["id"])
    raise ValueError("Webhook payload missing event_id")


def parse_webhook_payload(raw_body: bytes) -> dict[str, Any]:
    parsed = json.loads(raw_body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Webhook payload must be a JSON object")
    return parsed


def normalize_payment_event(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Map a provider payload onto LOCAH payment_id / status / order_id."""
    if provider != "razorpay":
        return {
            "payment_id": payload.get("payment_id") or payload.get("payment_attempt_id"),
            "status": payload.get("status"),
            "order_id": payload.get("order_id"),
            "provider_reference": payload.get("provider_reference"),
            "failure_code": payload.get("failure_code"),
            "failure_reason": payload.get("failure_reason"),
            # A refund's outcome: the provider's refund reference and its final status.
            "refund_reference": payload.get("refund_reference"),
            "refund_status": payload.get("refund_status"),
        }

    event = str(payload.get("event") or "")
    if event.startswith("refund."):
        refund = ((payload.get("payload") or {}).get("refund") or {}).get("entity") or {}
        return {
            "refund_reference": refund.get("id"),
            "refund_status": {"refund.processed": "succeeded", "refund.failed": "failed"}.get(event),
            "failure_reason": refund.get("error_description") or (refund.get("notes") or {}).get("failure"),
        }
    payment_entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    order_entity = ((payload.get("payload") or {}).get("order") or {}).get("entity") or {}
    entity = payment_entity or order_entity
    status_map = {
        "payment.captured": "succeeded",
        "payment.failed": "failed",
        "order.paid": "succeeded",
    }
    return {
        "payment_id": (entity.get("notes") or {}).get("locah_payment_id")
        or payload.get("payment_id"),
        "status": status_map.get(event),
        "order_id": entity.get("order_id") or order_entity.get("id"),
        "provider_reference": entity.get("id"),
        "failure_code": entity.get("error_code"),
        "failure_reason": entity.get("error_description"),
    }
