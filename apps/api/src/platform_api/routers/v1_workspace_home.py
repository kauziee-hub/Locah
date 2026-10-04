"""The Workspace home for whoever is signed in (Business OS Guide §3; Capability
Universe §7.2): the bands that answer their role's question, from real data
within their permissions and location scope."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_member
from platform_core.services.module_readiness import module_states
from platform_core.services.role_home import RoleHomeService

router = APIRouter(prefix="/v1/platform/businesses", tags=["workspace-home"])


@router.get("/{business_id}/home")
async def home(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_member()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    from platform_core.authorization.resolver import AuthorizationService

    permissions = frozenset(await AuthorizationService.effective_permissions(
        session, business_id=business_id, identity_id=actor.request.identity_id))
    live = {k for k, v in (await module_states(session, business_id)).items() if v in ("enabled", "ready", "active")}
    data = await RoleHomeService.compose(session, actor.business, actor.actor_membership, permissions, live)
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/insights")
async def insights(
    business_id: UUID,
    period: str = Query(default="today", pattern="^(today|7d|month)$"),
    actor: BusinessActorContext = Depends(require_business_member()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Basic insights from real data only (IS-01; First Launch §12.1): sales,
    orders, bookings and money received for a period, within what this person
    may see."""
    from platform_core.authorization.location_scope import scoped_locations
    from platform_core.authorization.resolver import AuthorizationService
    from platform_core.insights.basic import summary

    permissions = frozenset(await AuthorizationService.effective_permissions(
        session, business_id=business_id, identity_id=actor.request.identity_id))
    live = {k for k, v in (await module_states(session, business_id)).items() if v in ("enabled", "ready", "active")}
    data = await summary(
        session, business_id, period=period,
        can=lambda perm, module: perm in permissions and module in live,
        has=lambda module: module in live,
        business_wide=scoped_locations(actor.actor_membership) is None)
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/calendar")
async def one_calendar(
    business_id: UUID,
    days: int = Query(default=7, ge=1, le=31),
    actor: BusinessActorContext = Depends(require_business_member()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """One calendar (OM-21, MD §22): bookings, orders wanted, follow-ups,
    memberships ending and licences due for the days ahead, within what this
    person may see."""
    from platform_core.authorization.resolver import AuthorizationService
    from platform_core.services.one_calendar import agenda

    permissions = frozenset(await AuthorizationService.effective_permissions(
        session, business_id=business_id, identity_id=actor.request.identity_id))
    live = {k for k, v in (await module_states(session, business_id)).items() if v in ("enabled", "ready", "active")}
    data = await agenda(session, business_id, days=days,
                        can=lambda perm, module: perm in permissions and module in live)
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/empty-states")
async def empty_states(
    business_id: UUID,
    lang: str = Query(default="en", pattern="^(en|ta|hi)$"),
    actor: BusinessActorContext = Depends(require_business_member()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """What each empty list should say for THIS Business: its own items, whether
    its website can bring the first one in yet, and what to do now."""
    from platform_core.services.empty_states import empty_states as compose

    data = await compose(session, actor.business, lang=lang)
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}
