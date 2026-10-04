"""Classification, operating traits and module recommendations for one Business
(Capability Universe §4, §21, §24 #1–2; Founder §50).

Reading needs settings.read; changing what kind of business it is or how it
operates is a settings change (settings.update). Recommendations are what the
Modules page shows, so they need modules.read.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.gates import assert_business_mutable
from platform_core.permissions import MODULES_ENABLE, MODULES_READ, SETTINGS_READ, SETTINGS_UPDATE
from platform_core.services.business_classification import BusinessClassificationService

router = APIRouter(prefix="/v1/platform/businesses", tags=["classification"])


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_key: str | None = Field(default=None, max_length=60)
    subcategory_key: str | None = Field(default=None, max_length=60)
    org_shape: str | None = Field(default=None, max_length=30)


class TraitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traits: dict[str, bool] = Field(min_length=1, max_length=60)


def _meta(actor: BusinessActorContext) -> dict[str, Any]:
    return {"correlation_id": actor.request.correlation_id}


@router.get("/{business_id}/classification")
async def get_classification(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(SETTINGS_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await BusinessClassificationService.get(session, actor.business)
    return {"data": data, "meta": _meta(actor)}


@router.put("/{business_id}/classification")
async def put_classification(
    business_id: UUID,
    body: ClassificationRequest,
    actor: BusinessActorContext = Depends(require_business_actor(SETTINGS_UPDATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    assert_business_mutable(actor.business.state, action="classify")
    if body.category_key:
        await BusinessClassificationService.set_classification(
            session,
            actor.business,
            category_key=body.category_key,
            subcategory_key=body.subcategory_key,
            actor_id=actor.request.identity_id,
            correlation_id=actor.request.correlation_id,
        )
    if body.org_shape:
        await BusinessClassificationService.set_org_shape(
            session, actor.business, org_shape=body.org_shape, actor_id=actor.request.identity_id
        )
    await session.commit()
    data = await BusinessClassificationService.get(session, actor.business)
    return {"data": data, "meta": _meta(actor)}


@router.patch("/{business_id}/traits")
async def patch_traits(
    business_id: UUID,
    body: TraitsRequest,
    actor: BusinessActorContext = Depends(require_business_actor(SETTINGS_UPDATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    assert_business_mutable(actor.business.state, action="update traits")
    data = await BusinessClassificationService.set_traits(
        session,
        actor.business,
        changes=body.traits,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.get("/{business_id}/module-recommendations")
async def get_recommendations(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(MODULES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await BusinessClassificationService.recommendations(session, actor.business)
    return {"data": data, "meta": _meta(actor)}


@router.get("/{business_id}/module-recommendations/for-you")
async def get_recommended_for_you(
    business_id: UUID,
    limit: int | None = None,
    actor: BusinessActorContext = Depends(require_business_actor(MODULES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """"Recommended for your Business": ranked by evidence (what the owner said,
    their records, how they said they work, then businesses like theirs), each
    with its reason, value, setup and readiness. Recommends only."""
    from platform_core.services import module_recommendations

    data = await module_recommendations.for_you(session, actor.business,
                                                limit=max(1, min(limit, 20)) if limit else None)
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/module-recommendations/{module_id}/not-now")
async def put_off_recommendation(
    business_id: UUID,
    module_id: str,
    actor: BusinessActorContext = Depends(require_business_actor(MODULES_ENABLE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """"Not now": the suggestion leaves the list until a new reason for it appears."""
    from platform_core.services import module_recommendations

    await module_recommendations.put_off(session, actor.business, module_id, actor_id=actor.request.identity_id)
    await session.commit()
    return {"data": {"module_id": module_id, "put_off": True}, "meta": _meta(actor)}


@router.delete("/{business_id}/module-recommendations/{module_id}/not-now")
async def bring_back_recommendation(
    business_id: UUID,
    module_id: str,
    actor: BusinessActorContext = Depends(require_business_actor(MODULES_ENABLE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    from platform_core.services import module_recommendations

    await module_recommendations.bring_back(session, actor.business, module_id, actor_id=actor.request.identity_id)
    await session.commit()
    return {"data": {"module_id": module_id, "put_off": False}, "meta": _meta(actor)}
