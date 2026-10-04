"""Inbound payment webhook ingestion (Stage 9, Doc 12 §18.6).

The verified receipt is committed before its effect is applied, so nothing a
provider sends is lost: if applying it fails, the worker retries it with backoff
and finally dead-letters it (services/payment_webhook.py). The provider gets
200 once the receipt is safe — LOCAH owns the retries from there.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_service_db_session
from platform_core.exceptions import ConflictError
from platform_core.services.payment_webhook import PaymentWebhookService

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/payments/{provider}")
async def ingest_payment_webhook(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_service_db_session),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> dict[str, Any]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    raw_body = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    receipt_id, event_id, duplicate = await PaymentWebhookService.receive(
        session, provider=provider, raw_body=raw_body, headers=headers, correlation_id=correlation_id)
    await session.commit()  # kept before anything else can fail
    if duplicate:
        return {"data": {"status": "duplicate", "event_id": event_id}, "meta": {"correlation_id": correlation_id}}
    result = await PaymentWebhookService.apply_receipt(session, receipt_id, correlation_id=correlation_id)
    await session.commit()
    if result.get("status") == "refused":
        # Recorded, and refused for good (e.g. a written-off UPI claim).
        raise ConflictError(str(result.get("reason") or "This payment update is not allowed"),
                            details={"event_id": event_id})
    return {"data": result, "meta": {"correlation_id": correlation_id}}
