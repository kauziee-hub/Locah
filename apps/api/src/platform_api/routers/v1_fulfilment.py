"""Business fulfilment APIs — Doc 11 §10.4 / §4.2."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.permissions import (
    FULFILMENT_MANAGE_CONFIG,
    FULFILMENT_READ,
    FULFILMENT_UPDATE_STATUS,
)
from platform_core.services.fulfilment import FulfilmentService

router = APIRouter(prefix="/v1/b", tags=["fulfilment"])


class ZoneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    match_type: str = "city"
    city: str | None = None
    postal_prefix: str | None = None
    center_lat: float | None = None
    center_lng: float | None = None
    radius_km: float | None = None
    charge_amount: float = 0
    currency: str = "INR"
    location_id: UUID | None = None
    is_active: bool = True


class SettingsUpdateRequest(BaseModel):
    """A PATCH: only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    pickup_enabled: bool | None = None
    delivery_enabled: bool | None = None
    # Paying on delivery / at pickup, for the website and WhatsApp alike.
    cod_allowed: bool | None = None
    first_order_cod_cap: float | None = Field(default=None, ge=0)


class JobStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str | None = None


@router.get("/{business_id}/fulfilment/settings")
async def get_settings(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_READ, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    settings = await FulfilmentService.ensure_settings(session, business_id)
    modes = await FulfilmentService.active_modes(session, business_id)
    return {
        "data": {
            **FulfilmentService.serialize_settings(settings),
            "active_modes": modes,
        },
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/fulfilment/settings")
async def update_settings(
    business_id: UUID,
    body: SettingsUpdateRequest,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_MANAGE_CONFIG, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    settings = await FulfilmentService.update_settings(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        payload=body.model_dump(exclude_unset=True),
    )
    await session.commit()
    return {
        "data": FulfilmentService.serialize_settings(settings),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/fulfilment/zones")
async def create_zone(
    business_id: UUID,
    body: ZoneCreateRequest,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_MANAGE_CONFIG, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    zone = await FulfilmentService.create_zone(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": FulfilmentService.serialize_zone(zone),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


class ZoneUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    charge_amount: float | None = None


@router.patch("/{business_id}/fulfilment/zones/{zone_id}")
async def update_zone(
    business_id: UUID,
    zone_id: UUID,
    body: ZoneUpdateRequest,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_MANAGE_CONFIG, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    zone = await FulfilmentService.update_zone(
        session, business_id=business_id, zone_id=zone_id, actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id, is_active=body.is_active, charge_amount=body.charge_amount)
    await session.commit()
    return {"data": FulfilmentService.serialize_zone(zone), "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/fulfilment/zones")
async def list_zones(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_READ, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    zones = await FulfilmentService.list_zones(session, business_id)
    return {
        "data": [FulfilmentService.serialize_zone(z) for z in zones],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(zones)},
    }


@router.get("/{business_id}/fulfilment/jobs")
async def list_jobs(
    business_id: UUID,
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_READ, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    jobs = await FulfilmentService.list_jobs(
        session, business_id, status=status, mode=mode
    )
    return {
        "data": await FulfilmentService.describe_jobs(session, business_id, jobs),
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(jobs)},
    }


@router.get("/{business_id}/fulfilment/jobs/{job_id}")
async def get_job(
    business_id: UUID,
    job_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_READ, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    job = await FulfilmentService.get_job(session, business_id=business_id, job_id=job_id)
    return {
        "data": (await FulfilmentService.describe_jobs(session, business_id, [job]))[0],
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/fulfilment/jobs/{job_id}/status")
async def update_job_status(
    business_id: UUID,
    job_id: UUID,
    body: JobStatusRequest,
    actor: BusinessActorContext = Depends(require_business_actor(FULFILMENT_UPDATE_STATUS, "fulfilment")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    job = await FulfilmentService.transition_status(
        session,
        business_id=business_id,
        job_id=job_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(exclude_unset=True),
    )
    await session.commit()
    return {
        "data": FulfilmentService.serialize_job(job),
        "meta": {"correlation_id": actor.request.correlation_id},
    }
