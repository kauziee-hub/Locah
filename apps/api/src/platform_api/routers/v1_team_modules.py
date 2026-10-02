from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import require_permission
from platform_core.context import RequestContext
from platform_core.exceptions import ResourceNotFound
from platform_core.permissions import (
    COMMERCIAL_READ,
    MODULES_DEACTIVATE,
    MODULES_ENABLE,
    MODULES_READ,
    TEAM_INVITE,
    TEAM_READ,
    TEAM_UPDATE_ROLE,
)
from platform_core.services.entitlement import EntitlementService, ModuleService
from platform_core.services.team import TeamService

router = APIRouter(prefix="/v1/b", tags=["team", "modules", "entitlements"])


class InviteRequest(BaseModel):
    identity_id: UUID
    role: str = "member"


class GrantPermissionsRequest(BaseModel):
    permissions: list[str]


class EnableModuleRequest(BaseModel):
    module_id: str


@router.get("/{business_id}/team/members")
async def list_team(
    business_id: UUID,
    ctx: RequestContext = Depends(require_permission(TEAM_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    members = await TeamService.list_members(session, business_id)
    return {
        "data": [
            {
                "id": str(m.id),
                "identity_id": str(m.identity_id),
                "role": m.role,
                "status": m.status,
            }
            for m in members
        ],
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.post("/{business_id}/team/invitations")
async def invite_member(
    business_id: UUID,
    body: InviteRequest,
    ctx: RequestContext = Depends(require_permission(TEAM_INVITE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    membership = await TeamService.invite_member(
        session,
        business_id=business_id,
        identity_id=body.identity_id,
        role=body.role,
        invited_by=ctx.identity_id,
        correlation_id=ctx.correlation_id,
    )
    await session.commit()
    return {
        "data": {"id": str(membership.id), "status": membership.status},
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.post("/{business_id}/team/members/{membership_id}/activate")
async def activate_member(
    business_id: UUID,
    membership_id: UUID,
    ctx: RequestContext = Depends(require_permission(TEAM_UPDATE_ROLE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    members = await TeamService.list_members(session, business_id)
    target = next((m for m in members if m.id == membership_id), None)
    if not target:
        raise ResourceNotFound("Membership")
    await TeamService.activate_membership(session, target)
    await session.commit()
    return {
        "data": {"id": str(target.id), "status": target.status},
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.post("/{business_id}/team/members/{membership_id}/permissions")
async def grant_permissions(
    business_id: UUID,
    membership_id: UUID,
    body: GrantPermissionsRequest,
    ctx: RequestContext = Depends(require_permission(TEAM_UPDATE_ROLE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    members = await TeamService.list_members(session, business_id)
    target = next((m for m in members if m.id == membership_id), None)
    if not target:
        raise ResourceNotFound("Membership")
    is_owner = ctx.membership is not None and ctx.membership.role == "primary_owner"
    await TeamService.grant_permissions(
        session,
        membership=target,
        permissions=set(body.permissions),
        granted_by=ctx.identity_id,
        actor_permissions=ctx.effective_permissions,
        is_primary_owner=is_owner,
    )
    await session.commit()
    return {"data": {"granted": body.permissions}, "meta": {"correlation_id": ctx.correlation_id}}


@router.get("/{business_id}/entitlements")
async def list_entitlements(
    business_id: UUID,
    ctx: RequestContext = Depends(require_permission(COMMERCIAL_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    ent = await EntitlementService.get_effective(session, business_id)
    return {
        "data": {"modules": sorted(ent.modules)},
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.get("/{business_id}/entitlements/effective")
async def effective_entitlements(
    business_id: UUID,
    ctx: RequestContext = Depends(require_permission(COMMERCIAL_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    ent = await EntitlementService.get_effective(session, business_id)
    return {
        "data": {"modules": sorted(ent.modules)},
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.get("/{business_id}/modules")
async def list_modules(
    business_id: UUID,
    ctx: RequestContext = Depends(require_permission(MODULES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    states = await ModuleService.get_states(session, business_id)
    return {
        "data": [
            {"module_id": mid, "activation_state": s.activation_state} for mid, s in states.items()
        ],
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.post("/{business_id}/modules/{module_id}/enable")
async def enable_module(
    business_id: UUID,
    module_id: str,
    ctx: RequestContext = Depends(require_permission(MODULES_ENABLE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    state = await ModuleService.enable_module(
        session,
        business_id=business_id,
        module_id=module_id,
        actor_id=ctx.identity_id,
        entitlements=ctx.effective_entitlements,
        correlation_id=ctx.correlation_id,
    )
    await session.commit()
    return {
        "data": {"module_id": module_id, "activation_state": state.activation_state},
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.post("/{business_id}/modules/{module_id}/deactivate")
async def deactivate_module(
    business_id: UUID,
    module_id: str,
    ctx: RequestContext = Depends(require_permission(MODULES_DEACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if ctx.business_id != business_id:
        raise ResourceNotFound("Business")
    state = await ModuleService.deactivate_module(
        session,
        business_id=business_id,
        module_id=module_id,
        actor_id=ctx.identity_id,
        correlation_id=ctx.correlation_id,
    )
    await session.commit()
    return {
        "data": {"module_id": module_id, "activation_state": state.activation_state},
        "meta": {"correlation_id": ctx.correlation_id},
    }
