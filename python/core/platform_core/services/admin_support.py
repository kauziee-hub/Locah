"""Super Admin support and observability reads (Doc 09 ADM-*, Doc 11 §17.7).

Two rules shape everything here:

1. **No silent impersonation** (Doc 09 ADM-004, Doc 11 §17.7 exit). Every
   Admin read of a specific Business is attributed via an `admin.*` audit
   event with `actor_context="admin"`. Admin actions are never recorded as if
   the Business owner performed them.
2. **Read-first** (Doc 09 ADM-003). This service inspects; it does not mutate
   Business data. The one existing Admin mutation (marketplace reindex) is an
   operational recovery action and already audits itself.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import (
    Business,
    BusinessLocation,
    BusinessMembership,
    BusinessModuleState,
    PlatformAuditEvent,
)


class AdminSupportService:
    # ------------------------------------------------------------------
    # ADM-002 — Businesses
    # ------------------------------------------------------------------
    @staticmethod
    async def search_businesses(
        session: AsyncSession,
        *,
        query: str | None = None,
        state: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(Business)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                Business.display_name.ilike(pattern) | Business.slug.ilike(pattern)
            )
        if state:
            stmt = stmt.where(Business.state == state)
        if status:
            stmt = stmt.where(Business.status == status)
        stmt = stmt.order_by(Business.created_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(b.id),
                "slug": b.slug,
                "display_name": b.display_name,
                # All three axes, so Admin can tell a closed Business from a
                # suspended one from an unlisted one (Doc 03 §1.6).
                "state": b.state,
                "status": b.status,
                "visibility": b.visibility,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in rows
        ]

    # ------------------------------------------------------------------
    # ADM-003 / ADM-008 — Business support view incl. modules + entitlements
    # ------------------------------------------------------------------
    @staticmethod
    async def business_support_view(
        session: AsyncSession, *, business_id: uuid.UUID
    ) -> dict[str, Any] | None:
        business = (
            await session.execute(select(Business).where(Business.id == business_id))
        ).scalars().first()
        if business is None:
            return None

        module_rows = (
            await session.execute(
                select(BusinessModuleState).where(BusinessModuleState.business_id == business_id)
            )
        ).scalars().all()
        locations = (
            await session.execute(
                select(BusinessLocation).where(
                    BusinessLocation.business_id == business_id,
                    BusinessLocation.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        member_count = (
            await session.execute(
                select(func.count())
                .select_from(BusinessMembership)
                .where(
                    BusinessMembership.business_id == business_id,
                    BusinessMembership.status == "active",
                    BusinessMembership.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        return {
            "business": {
                "id": str(business.id),
                "slug": business.slug,
                "display_name": business.display_name,
                "business_type": business.business_type,
                "state": business.state,
                "status": business.status,
                "visibility": business.visibility,
                "primary_owner_identity_id": str(business.primary_owner_identity_id)
                if business.primary_owner_identity_id
                else None,
                "created_at": business.created_at.isoformat() if business.created_at else None,
            },
            "modules": sorted(
                (
                    {
                        "module_id": m.module_id,
                        "activation_state": m.activation_state,
                        "activated_at": m.activated_at.isoformat() if m.activated_at else None,
                    }
                    for m in module_rows
                ),
                key=lambda row: str(row["module_id"]),
            ),
            "locations": [
                {
                    "id": str(loc.id),
                    "name": loc.name,
                    "is_primary": loc.is_primary,
                    "status": loc.status,
                }
                for loc in locations
            ],
            "active_member_count": int(member_count),
        }

    # ------------------------------------------------------------------
    # ADM-018 — Audit & Activity (append-only evidence view)
    # ------------------------------------------------------------------
    @staticmethod
    async def search_audit_events(
        session: AsyncSession,
        *,
        business_id: uuid.UUID | None = None,
        actor_identity_id: uuid.UUID | None = None,
        event_type: str | None = None,
        actor_context: str | None = None,
        resource_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = select(PlatformAuditEvent)
        if business_id is not None:
            stmt = stmt.where(PlatformAuditEvent.business_id == business_id)
        if actor_identity_id is not None:
            stmt = stmt.where(PlatformAuditEvent.actor_identity_id == actor_identity_id)
        if event_type:
            # Prefix match so "payment." finds every payment event.
            stmt = stmt.where(PlatformAuditEvent.event_type.like(f"{event_type}%"))
        if actor_context:
            stmt = stmt.where(PlatformAuditEvent.actor_context == actor_context)
        if resource_type:
            stmt = stmt.where(PlatformAuditEvent.resource_type == resource_type)
        stmt = stmt.order_by(PlatformAuditEvent.occurred_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "actor_identity_id": str(row.actor_identity_id),
                "actor_context": row.actor_context,
                "business_id": str(row.business_id) if row.business_id else None,
                "resource_type": row.resource_type,
                "resource_id": str(row.resource_id) if row.resource_id else None,
                "action": row.action,
                "reason": row.reason,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # ADM-019 — System Health & Events
    # Doc 11 §17.7 exit: "dead-letter, provider, search, payment, Website, and
    # entitlement failures are visible".
    # ------------------------------------------------------------------
    @staticmethod
    async def system_health(session: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
        dead_letters = (
            await session.execute(
                text("""
                    SELECT id, source_table, source_id, event_type, final_error, attempt_count, created_at,
                           resolved_at, resolution_note
                    FROM platform_dead_letter_events
                    ORDER BY (resolved_at IS NULL) DESC, created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
        ).all()

        # Outbox backlog by status, so a stuck consumer is visible as a number
        # rather than only as individual dead letters.
        outbox = (
            await session.execute(
                text("""
                    SELECT status, count(*) AS total,
                           min(created_at) AS oldest
                    FROM platform_outbox_events
                    GROUP BY status
                """)
            )
        ).all()

        failed_jobs = (
            await session.execute(
                text("""
                    SELECT id, job_type, status, last_error, attempt_count, created_at
                    FROM platform_async_jobs
                    WHERE status IN ('failed', 'dead_letter')
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
        ).all()

        # Failure-class counts across the classes Doc 11 §17.7 names.
        failure_events = (
            await session.execute(
                text("""
                    SELECT event_type, count(*) AS total
                    FROM platform_outbox_events
                    WHERE status IN ('failed', 'dead_letter')
                    GROUP BY event_type
                    ORDER BY total DESC
                    LIMIT 25
                """)
            )
        ).all()

        return {
            "dead_letters": [
                {
                    "id": str(r.id),
                    "source_table": r.source_table,
                    "source_id": str(r.source_id),
                    "event_type": r.event_type,
                    "final_error": r.final_error,
                    "attempt_count": r.attempt_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                    "resolution_note": r.resolution_note,
                }
                for r in dead_letters
            ],
            "outbox_by_status": [
                {
                    "status": r.status,
                    "count": int(r.total),
                    "oldest": r.oldest.isoformat() if r.oldest else None,
                }
                for r in outbox
            ],
            "failed_jobs": [
                {
                    "id": str(r.id),
                    "job_type": r.job_type,
                    "status": r.status,
                    "last_error": r.last_error,
                    "attempt_count": r.attempt_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in failed_jobs
            ],
            "failing_event_types": [
                {"event_type": r.event_type, "count": int(r.total)} for r in failure_events
            ],
        }
