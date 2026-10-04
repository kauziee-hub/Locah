"""Provider-backed refunds behind one interface (Stage 9 adapter layer).

`request_refund` asks the payment's own provider to send money back and
reports what the provider said — accepted (processing / already processed) or
refused, with the provider's words. It never claims money moved when the
provider did not accept it. The final outcome arrives as a refund webhook.

Providers:
* ``razorpay`` — Route payments, refunded from the platform account
  (payments/razorpay.py `create_refund`);
* ``stub`` — test mode: accepted as processing with a stub reference; its
  webhook (`refund_reference` + `refund_status`) completes or fails it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from platform_core.models import PaymentAttempt

ONLINE_PROVIDERS = frozenset({"razorpay", "stub"})


@dataclass(frozen=True)
class ProviderRefund:
    accepted: bool
    status: str  # processing | succeeded | failed
    reference: str | None
    detail: str


def refundable_by_provider(payment: PaymentAttempt) -> bool:
    """An online payment a provider collected — it can be refunded through it."""
    return (payment.payment_method == "online" and (payment.provider or "") in ONLINE_PROVIDERS
            and bool(payment.provider_reference))


async def request_refund(payment: PaymentAttempt, *, amount: Decimal, refund_id: uuid.UUID,
                         reason: str | None) -> ProviderRefund:
    if payment.provider == "razorpay":
        from platform_core.payments.razorpay import create_refund

        result = await create_refund(
            payment_reference=str(payment.provider_reference or ""), amount=amount,
            receipt=refund_id.hex[:40],
            notes={"locah_refund_id": str(refund_id), "locah_payment_id": str(payment.id),
                   "reason": (reason or "")[:200]})
        if not result.ok:
            return ProviderRefund(False, "failed", None, result.detail)
        return ProviderRefund(True, "succeeded" if result.status == "processed" else "processing",
                              result.refund_id, "Razorpay accepted the refund.")
    if payment.provider == "stub":
        return ProviderRefund(True, "processing", f"stub_rfnd_{refund_id.hex[:16]}", "Test provider accepted the refund.")
    return ProviderRefund(False, "failed", None, "This payment's provider cannot refund online.")
