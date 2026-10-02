"""Membership plan service (Stage 6 — Doc 11 §9.5).

Business-defined plan creation, public presentation, and the class/session
access mapping that gates Stage 6 membership-linked bookings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceNotFound
from platform_core.gates import assert_business_mutable
from platform_core.models import MembershipPlan, MembershipPlanOfferingAccess
from platform_core.resolvers.membership_resolver import MembershipResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService
from platform_core.validation.membership import (
    validate_plan_create_payload,
    validate_plan_patch_payload,
)


def _delivery(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """A subscription plan's default schedule, cleaned the same way a subscriber's is."""
    if not raw:
        return None
    from platform_core.memberships.service import MembershipCore

    cleaned: dict[str, Any] | None = MembershipCore._clean_delivery(raw)
    return cleaned


class MembershipPlanService:
    @staticmethod
    def _check_version(plan: MembershipPlan, expected_version: int | None) -> None:
        if expected_version is not None and plan.version != expected_version:
            raise ConflictError(
                "Stale membership plan version",
                details={
                    "expected_version": expected_version,
                    "current_version": plan.version,
                },
            )

    @staticmethod
    async def _sync_offering_access(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        plan_id: uuid.UUID,
        offering_ids: list[uuid.UUID],
    ) -> None:
        await session.execute(
            delete(MembershipPlanOfferingAccess).where(
                MembershipPlanOfferingAccess.plan_id == plan_id
            )
        )
        for offering_id in dict.fromkeys(offering_ids):
            session.add(
                MembershipPlanOfferingAccess(
                    business_id=business_id, plan_id=plan_id, offering_id=offering_id
                )
            )
        await session.flush()

    @staticmethod
    async def _publish(
        session: AsyncSession,
        *,
        event_type: str,
        audit_action: str,
        business_id: uuid.UUID,
        plan: MembershipPlan,
        actor_id: uuid.UUID,
        correlation_id: str,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any],
    ) -> None:
        await OutboxService.publish(
            session,
            event_type=event_type,
            payload={
                "business_id": str(business_id),
                "plan_id": str(plan.id),
                "after": after_state,
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type=event_type,
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="membership_plan",
            resource_id=plan.id,
            action=audit_action,
            before_state=before_state,
            after_state=after_state,
        )

    @staticmethod
    async def create_plan(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> MembershipPlan:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="create membership plan")
        validated = validate_plan_create_payload(payload)

        plan = MembershipPlan(
            business_id=business_id,
            name=validated["name"],
            description=validated["description"],
            offering_id=validated["offering_id"],
            price_amount=validated["price_amount"],
            currency=validated["currency"],
            billing_model=validated["billing_model"],
            duration_days=validated["duration_days"],
            status=validated["status"],
            visibility=validated["visibility"],
            plan_kind=validated["plan_kind"],
            billing_timing=validated["billing_timing"],
            grace_days=validated["grace_days"],
            grace_allows_entry=validated["grace_allows_entry"],
            freeze_allowed=validated["freeze_allowed"],
            max_freeze_days=validated["max_freeze_days"],
            sessions_included=validated["sessions_included"],
            consume_on=validated["consume_on"],
            no_show_consumes=validated["no_show_consumes"],
            delivery=_delivery(validated.get("delivery")),
            instalment_template=validated["instalment_template"],
            visits_included=validated["visits_included"],
            visit_every_days=validated["visit_every_days"],
            created_by=actor_id,
        )
        session.add(plan)
        await session.flush()
        await MembershipPlanService._sync_offering_access(
            session,
            business_id=business_id,
            plan_id=plan.id,
            offering_ids=validated["offering_access"],
        )

        after = MembershipResolver.serialize_plan(
            plan, offering_access=validated["offering_access"]
        )
        await MembershipPlanService._publish(
            session,
            event_type="membership.plan.created",
            audit_action="create",
            business_id=business_id,
            plan=plan,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=None,
            after_state=after,
        )
        return plan

    @staticmethod
    async def list_plans(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        status: str | None = None,
        visibility: str | None = None,
    ) -> list[MembershipPlan]:
        query = select(MembershipPlan).where(
            MembershipPlan.business_id == business_id,
            MembershipPlan.deleted_at.is_(None),
        )
        if status:
            query = query.where(MembershipPlan.status == status)
        if visibility:
            query = query.where(MembershipPlan.visibility == visibility)
        query = query.order_by(MembershipPlan.created_at.desc())
        return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def patch_plan(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        plan_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> MembershipPlan:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="update membership plan")
        plan = await MembershipResolver.resolve_plan(
            session, business_id=business_id, plan_id=plan_id
        )
        MembershipPlanService._check_version(plan, expected_version)
        MembershipResolver.require_plan_operable(plan, action="update membership plan")
        validated = validate_plan_patch_payload(payload)

        access_before = [
            a.offering_id
            for a in await MembershipResolver.load_plan_offering_access(
                session, business_id=business_id, plan_id=plan_id
            )
        ]
        before = MembershipResolver.serialize_plan(plan, offering_access=access_before)

        offering_access = validated.pop("offering_access", None)
        if "delivery" in validated:
            validated["delivery"] = _delivery(validated["delivery"])
        for field, value in validated.items():
            setattr(plan, field, value)
        plan.version += 1
        await session.flush()
        if offering_access is not None:
            await MembershipPlanService._sync_offering_access(
                session,
                business_id=business_id,
                plan_id=plan.id,
                offering_ids=offering_access,
            )

        access_after = [
            a.offering_id
            for a in await MembershipResolver.load_plan_offering_access(
                session, business_id=business_id, plan_id=plan_id
            )
        ]
        after = MembershipResolver.serialize_plan(plan, offering_access=access_after)
        await MembershipPlanService._publish(
            session,
            event_type="membership.plan.updated",
            audit_action="update",
            business_id=business_id,
            plan=plan,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
        )
        return plan

    @staticmethod
    async def archive_plan(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        plan_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
    ) -> MembershipPlan:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="archive membership plan")
        plan = await MembershipResolver.resolve_plan(
            session, business_id=business_id, plan_id=plan_id
        )
        before = MembershipResolver.serialize_plan(plan)
        plan.status = "archived"
        plan.deleted_at = datetime.now(timezone.utc)
        plan.version += 1
        await session.flush()
        after = MembershipResolver.serialize_plan(plan)
        await MembershipPlanService._publish(
            session,
            event_type="membership.plan.archived",
            audit_action="archive",
            business_id=business_id,
            plan=plan,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
        )
        return plan


async def public_plans(session: AsyncSession, *, slug: str) -> list[dict[str, Any]]:
    """The plans a visitor can see on the business's website: active and
    public only, cheapest first — what "Plans" on the site is filled from."""
    from platform_core.services.checkout import CheckoutService
    from platform_core.services.module_readiness import module_ready

    business = await CheckoutService._resolve_business(session, slug)
    # Memberships' public read contract: no plans to join while the module is
    # not ready (switched off, not entitled, or nothing published). The plans
    # and every member's record are kept.
    if not await module_ready(session, business.id, "memberships"):
        return []
    plans = await MembershipPlanService.list_plans(session, business_id=business.id, status="active",
                                                   visibility="public")
    plans.sort(key=lambda p: (float(p.price_amount or 0), p.name))
    return [{"id": str(p.id), "title": p.name, "description": p.description,
             "price_amount": str(p.price_amount), "currency": p.currency, "billing_model": p.billing_model,
             "duration_days": p.duration_days} for p in plans]
