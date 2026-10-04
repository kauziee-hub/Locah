"""Super Admin APIs — includes Marketplace indexing health (Doc 11 §17.3)."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_service_db_session
from platform_api.dependencies import require_super_admin
from platform_core.context import RequestContext
from platform_core.exceptions import ResourceNotFound
from platform_core.models import MarketplaceIndexHealth
from platform_core.services.admin_support import AdminSupportService
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.marketplace_indexing import MarketplaceIndexingService

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/businesses/{business_id}")
async def admin_get_business(
    business_id: UUID,
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    business = await BusinessService.get_by_id(session, business_id)
    if not business:
        raise ResourceNotFound("Business")

    await AuditService.record(
        session,
        event_type="admin.business.inspected",
        actor_identity_id=ctx.identity_id,
        actor_context="admin",
        business_id=business_id,
        resource_type="business",
        resource_id=business_id,
        action="inspect",
        after_state={"display_name": business.display_name, "state": business.state},
    )
    await session.commit()

    return {
        "data": {
            "id": str(business.id),
            "slug": business.slug,
            "display_name": business.display_name,
            "state": business.state,
            "visibility": business.visibility,
        },
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.get("/marketplace/indexing")
async def admin_list_indexing_health(
    status: str | None = Query(default=None),
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    query = select(MarketplaceIndexHealth).order_by(
        MarketplaceIndexHealth.last_attempt_at.desc().nullslast()
    )
    if status:
        query = query.where(MarketplaceIndexHealth.last_status == status)
    rows = (await session.execute(query.limit(200))).scalars().all()

    dead_letters = await session.execute(
        text("""
            SELECT id, event_type, final_error, attempt_count, created_at
            FROM platform_dead_letter_events
            WHERE event_type LIKE 'marketplace.%'
               OR (payload::text LIKE '%marketplace%' AND source_table = 'platform_async_jobs')
            ORDER BY created_at DESC
            LIMIT 50
        """)
    )
    dl_rows = [
        {
            "id": str(r.id),
            "event_type": r.event_type,
            "final_error": r.final_error,
            "attempt_count": r.attempt_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in dead_letters
    ]
    return {
        "data": {
            "health": [MarketplaceIndexingService.serialize_health(h) for h in rows],
            "dead_letters": dl_rows,
        },
        "meta": {"correlation_id": ctx.correlation_id, "count": len(rows)},
    }


@router.get("/marketplace/indexing/{business_id}")
async def admin_get_indexing_health(
    business_id: UUID,
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    business = await BusinessService.get_by_id(session, business_id)
    if not business:
        raise ResourceNotFound("Business")
    health = (
        await session.execute(
            select(MarketplaceIndexHealth).where(
                MarketplaceIndexHealth.business_id == business_id
            )
        )
    ).scalars().first()
    return {
        "data": {
            "business": {
                "id": str(business.id),
                "slug": business.slug,
                "visibility": business.visibility,
                "state": business.state,
            },
            "health": MarketplaceIndexingService.serialize_health(health) if health else None,
        },
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.post("/marketplace/indexing/{business_id}/reindex")
async def admin_reindex_business(
    business_id: UUID,
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    business = await BusinessService.get_by_id(session, business_id)
    if not business:
        raise ResourceNotFound("Business")
    result = await MarketplaceIndexingService.reindex_business(
        session,
        business_id=business_id,
        correlation_id=ctx.correlation_id or str(uuid.uuid4()),
        actor_id=ctx.identity_id,
        trigger="admin_manual",
    )
    await AuditService.record(
        session,
        event_type="marketplace.reindex_triggered",
        actor_identity_id=ctx.identity_id,
        actor_context="admin",
        business_id=business_id,
        resource_type="marketplace_projection",
        resource_id=business_id,
        action="manual_reindex",
        after_state=result,
    )
    await session.commit()
    return {"data": result, "meta": {"correlation_id": ctx.correlation_id}}


# ---------------------------------------------------------------------------
# ADM-002 / ADM-003 / ADM-008 / ADM-018 / ADM-019
#
# Doc 11 §17.7 exit: "Admin can inspect and support without silent
# impersonation". Every route below that reads one identified Business writes
# an `admin.*` audit event with actor_context="admin" BEFORE returning, so an
# Admin cannot look at a Business without leaving a trace, and the trace is
# never attributed to the Business owner.
# ---------------------------------------------------------------------------
@router.get("/businesses")
async def admin_search_businesses(
    query: str | None = Query(default=None, min_length=1, max_length=120),
    state: str | None = Query(default=None),
    business_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    """ADM-002 — search across all Businesses.

    Not audited per-Business: this is a list view over metadata the Admin is
    entitled to see, and auditing every keystroke of a search box produces
    noise that buries the inspections that matter.
    """
    results = await AdminSupportService.search_businesses(
        session, query=query, state=state, status=business_status, limit=limit
    )
    return {
        "data": results,
        "meta": {"correlation_id": ctx.correlation_id, "count": len(results)},
    }


@router.get("/businesses/{business_id}/support")
async def admin_business_support_view(
    business_id: UUID,
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    """ADM-003 + ADM-008 — the support hub for one Business, attributed."""
    view = await AdminSupportService.business_support_view(session, business_id=business_id)
    if view is None:
        raise ResourceNotFound("Business")

    await AuditService.record(
        session,
        event_type="admin.business.support_viewed",
        actor_identity_id=ctx.identity_id,
        actor_context="admin",
        business_id=business_id,
        resource_type="business",
        resource_id=business_id,
        action="support_view",
        after_state={"modules": len(view["modules"]), "locations": len(view["locations"])},
    )
    await session.commit()
    return {"data": view, "meta": {"correlation_id": ctx.correlation_id}}


@router.get("/audit")
async def admin_search_audit(
    business_id: UUID | None = Query(default=None),
    actor_identity_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None, max_length=120),
    actor_context: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    """ADM-018 — append-only evidence view over platform audit events.

    Read-only by construction: there is no write or delete path to
    `platform_audit_events` anywhere in the API, which is what makes this an
    evidence view rather than an editable log.
    """
    events = await AdminSupportService.search_audit_events(
        session,
        business_id=business_id,
        actor_identity_id=actor_identity_id,
        event_type=event_type,
        actor_context=actor_context,
        resource_type=resource_type,
        limit=limit,
    )
    return {
        "data": events,
        "meta": {"correlation_id": ctx.correlation_id, "count": len(events)},
    }


@router.get("/system/health")
async def admin_system_health(
    limit: int = Query(default=50, ge=1, le=200),
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    """ADM-019 — dead letters, outbox backlog, failed jobs, failing event types.

    Covers the Doc 11 §17.7 exit requirement that "dead-letter, provider,
    search, payment, Website, and entitlement failures are visible": each of
    those classes surfaces here as a dead-letter row or a failing event type,
    since every one of them flows through the outbox or the async job table.
    """
    health = await AdminSupportService.system_health(session, limit=limit)
    return {"data": health, "meta": {"correlation_id": ctx.correlation_id}}


@router.post("/payment-webhooks/{receipt_id}/retry")
async def admin_retry_payment_webhook(
    receipt_id: UUID,
    ctx: RequestContext = Depends(require_super_admin()),
    session: AsyncSession = Depends(get_service_db_session),
) -> dict[str, Any]:
    """Put a dead-lettered payment webhook back into the retry lane (audited)."""
    from platform_core.services.payment_webhook import PaymentWebhookService

    result = await PaymentWebhookService.requeue(session, receipt_id, actor_id=ctx.identity_id)
    await AuditService.record(
        session,
        event_type="payment.webhook_requeued",
        actor_identity_id=ctx.identity_id,
        actor_context="admin",
        resource_type="payment_webhook",
        resource_id=receipt_id,
        action="requeue",
        after_state=result,
    )
    await session.commit()
    return {"data": result, "meta": {"correlation_id": ctx.correlation_id}}
