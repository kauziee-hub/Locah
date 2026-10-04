"""Workforce APIs — operational providers (Doc 10 §4.8, Doc 11 §10.5).

identity_id linkage never grants Workspace access.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.permissions import (
    WORKFORCE_CREATE,
    WORKFORCE_DEACTIVATE,
    WORKFORCE_MANAGE_AVAILABILITY,
    WORKFORCE_READ,
    WORKFORCE_UPDATE,
)
from platform_core.services.workforce import WorkforceService

router = APIRouter(prefix="/v1/platform/businesses", tags=["workforce"])


class CreateMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    email: str | None = None
    phone: str | None = None
    designation: str | None = None
    identity_id: UUID | None = None
    status: str = "active"
    notes: str | None = None
    location_ids: list[UUID] = Field(default_factory=list)
    primary_location_id: UUID | None = None
    offering_ids: list[UUID] = Field(default_factory=list)


class PatchMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    designation: str | None = None
    identity_id: UUID | None = None
    status: str | None = None
    notes: str | None = None


class AssignLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: UUID
    is_primary: bool = False


class AssociateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_id: UUID


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: UUID | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    exception_date: str | None = None
    start_time: str
    end_time: str
    is_available: bool = True


@router.get("/{business_id}/workforce/members")
async def list_members(
    business_id: UUID,
    status: str | None = Query(default=None),
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_READ, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    members = await WorkforceService.list_members(session, business_id, status=status)
    return {
        "data": [WorkforceService.serialize_member(m) for m in members],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(members)},
    }


@router.post("/{business_id}/workforce/members")
async def create_member(
    business_id: UUID,
    body: CreateMemberRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_CREATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    payload = body.model_dump()
    location_ids = payload.pop("location_ids", [])
    primary_location_id = payload.pop("primary_location_id", None)
    offering_ids = payload.pop("offering_ids", [])
    member = await WorkforceService.create_member(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=payload,
    )
    for loc_id in location_ids:
        await WorkforceService.assign_location(
            session,
            business_id=business_id,
            member_id=member.id,
            location_id=loc_id,
            actor_id=actor.request.identity_id,
            is_primary=bool(primary_location_id and loc_id == primary_location_id),
        )
    for offering_id in offering_ids:
        await WorkforceService.associate_service(
            session,
            business_id=business_id,
            member_id=member.id,
            offering_id=offering_id,
            actor_id=actor.request.identity_id,
        )
    await session.commit()
    return {
        "data": WorkforceService.serialize_member(member),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/workforce/members/{member_id}")
async def get_member(
    business_id: UUID,
    member_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_READ, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    member = await WorkforceService.get_member(
        session, business_id=business_id, member_id=member_id
    )
    locations = await WorkforceService.list_locations(
        session, business_id=business_id, member_id=member_id
    )
    services = await WorkforceService.list_services(
        session, business_id=business_id, member_id=member_id
    )
    availability = await WorkforceService.list_availability(
        session, business_id=business_id, member_id=member_id
    )
    data = WorkforceService.serialize_member(member)
    data["locations"] = [
        {
            "location_id": str(a.location_id),
            "is_primary": a.is_primary,
        }
        for a in locations
    ]
    data["services"] = [{"offering_id": str(s.offering_id)} for s in services]
    data["availability"] = [
        {
            "id": str(a.id),
            "location_id": str(a.location_id) if a.location_id else None,
            "weekday": a.weekday,
            "exception_date": a.exception_date.isoformat() if a.exception_date else None,
            "start_time": a.start_time.isoformat() if a.start_time else None,
            "end_time": a.end_time.isoformat() if a.end_time else None,
            "is_available": a.is_available,
        }
        for a in availability
    ]
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/workforce/members/{member_id}")
async def patch_member(
    business_id: UUID,
    member_id: UUID,
    body: PatchMemberRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_UPDATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    payload.pop("version", None)
    member = await WorkforceService.update_member(
        session,
        business_id=business_id,
        member_id=member_id,
        actor_id=actor.request.identity_id,
        payload=payload,
    )
    await session.commit()
    return {
        "data": WorkforceService.serialize_member(member),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/workforce/members/{member_id}/deactivate")
async def deactivate_member(
    business_id: UUID,
    member_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_DEACTIVATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    member = await WorkforceService.deactivate_member(
        session,
        business_id=business_id,
        member_id=member_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    return {
        "data": WorkforceService.serialize_member(member),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/workforce/members/{member_id}/locations")
async def assign_location(
    business_id: UUID,
    member_id: UUID,
    body: AssignLocationRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_UPDATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await WorkforceService.assign_location(
        session,
        business_id=business_id,
        member_id=member_id,
        location_id=body.location_id,
        actor_id=actor.request.identity_id,
        is_primary=body.is_primary,
    )
    await session.commit()
    return {
        "data": {
            "member_id": str(member_id),
            "location_id": str(row.location_id),
            "is_primary": row.is_primary,
        },
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.delete("/{business_id}/workforce/members/{member_id}/locations/{location_id}")
async def unassign_location(
    business_id: UUID,
    member_id: UUID,
    location_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_UPDATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await WorkforceService.unassign_location(
        session,
        business_id=business_id,
        member_id=member_id,
        location_id=location_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    return {
        "data": {"ok": True},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.delete("/{business_id}/workforce/members/{member_id}/services/{offering_id}")
async def dissociate_service(
    business_id: UUID,
    member_id: UUID,
    offering_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_UPDATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await WorkforceService.dissociate_service(
        session,
        business_id=business_id,
        member_id=member_id,
        offering_id=offering_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    return {
        "data": {"ok": True},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/workforce/members/{member_id}/services")
async def associate_service(
    business_id: UUID,
    member_id: UUID,
    body: AssociateServiceRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WORKFORCE_UPDATE, "workforce")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await WorkforceService.associate_service(
        session,
        business_id=business_id,
        member_id=member_id,
        offering_id=body.offering_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    return {
        "data": {
            "member_id": str(member_id),
            "offering_id": str(row.offering_id),
        },
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/workforce/members/{member_id}/availability")
async def set_availability(
    business_id: UUID,
    member_id: UUID,
    body: AvailabilityRequest,
    actor: BusinessActorContext = Depends(
        require_business_actor(WORKFORCE_MANAGE_AVAILABILITY, "workforce")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await WorkforceService.set_availability(
        session,
        business_id=business_id,
        member_id=member_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": {"id": str(row.id), "member_id": str(member_id)},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.delete("/{business_id}/workforce/members/{member_id}/availability/{availability_id}")
async def remove_availability(
    business_id: UUID,
    member_id: UUID,
    availability_id: UUID,
    actor: BusinessActorContext = Depends(
        require_business_actor(WORKFORCE_MANAGE_AVAILABILITY, "workforce")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await WorkforceService.remove_availability(
        session,
        business_id=business_id,
        member_id=member_id,
        availability_id=availability_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {
        "data": {"id": str(availability_id), "removed": True},
        "meta": {"correlation_id": actor.request.correlation_id},
    }
