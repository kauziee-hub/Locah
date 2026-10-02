"""Platform offerings catalog APIs (Stage 5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.exceptions import ResourceNotFound
from platform_core.permissions import (
    OFFERINGS_ARCHIVE,
    OFFERINGS_CREATE,
    OFFERINGS_READ,
    OFFERINGS_UPDATE,
)
from platform_core.resolvers.offering_resolver import OfferingResolver
from platform_core.services.category import CategoryService
from platform_core.services.media import MediaService
from platform_core.services.offering import OfferingService

router = APIRouter(prefix="/v1/platform/businesses", tags=["offerings"])


class VersionedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)


class CreateCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str | None = None
    parent_id: UUID | None = None
    sort_order: int = 0


class PatchCategoryRequest(VersionedBody):
    name: str | None = None
    slug: str | None = None
    parent_id: UUID | None = None
    sort_order: int | None = None
    status: str | None = None


class CreateProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    offering_type: str = "product"
    description: str | None = None
    category_id: UUID | None = None
    sku: str | None = None
    barcode: str | None = None
    status: str = "draft"
    price_type: str = "fixed"
    price_amount: float | None = None
    currency: str = "INR"
    unit_of_measure: str | None = None
    tax_rate: float | None = None
    track_inventory: bool = False
    low_stock_threshold: int | None = None
    visibility: str = "public"
    image_asset_ids: list[UUID] = Field(default_factory=list)
    # Capability Universe §6.1/§6.3 kind fields.
    hsn_sac: str | None = None
    stock_unit: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    option_groups: list[dict[str, Any]] = Field(default_factory=list)
    sell_units: list[dict[str, Any]] = Field(default_factory=list)
    variant_options: list[dict[str, Any]] = Field(default_factory=list)
    # Dated pre-orders (P1-10D2): needs a date or may take one, notice, cutoff, window, limit, advance.
    preorder: dict[str, Any] | None = None
    # Formula pricing (P1-10D2b, OK-15): today's rate × quantity + making + extras.
    price_formula: dict[str, Any] | None = None


class PatchProductRequest(VersionedBody):
    title: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    sku: str | None = None
    barcode: str | None = None
    status: str | None = None
    price_type: str | None = None
    price_amount: float | None = None
    currency: str | None = None
    unit_of_measure: str | None = None
    tax_rate: float | None = None
    track_inventory: bool | None = None
    low_stock_threshold: int | None = None
    visibility: str | None = None
    image_asset_ids: list[UUID] | None = None
    hsn_sac: str | None = None
    stock_unit: str | None = None
    attributes: dict[str, Any] | None = None
    option_groups: list[dict[str, Any]] | None = None
    sell_units: list[dict[str, Any]] | None = None
    variant_options: list[dict[str, Any]] | None = None
    preorder: dict[str, Any] | None = None
    price_formula: dict[str, Any] | None = None


class CreateVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    sku: str | None = None
    barcode: str | None = None
    price_amount: float | None = None
    sort_order: int = 0
    attributes: dict[str, str] = Field(default_factory=dict)


def _patch_payload(body: BaseModel) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    return {"payload": data, "version": version}


@router.get("/{business_id}/product-categories")
async def list_categories(
    business_id: UUID,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    categories = await CategoryService.list_for_business(
        session, business_id, status=status, search=search
    )
    return {
        "data": [CategoryService.serialize(c) for c in categories],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(categories)},
    }


@router.post("/{business_id}/product-categories")
async def create_category(
    business_id: UUID,
    body: CreateCategoryRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_CREATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    category = await CategoryService.create_category(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": CategoryService.serialize(category),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/product-categories/{category_id}")
async def get_category(
    business_id: UUID,
    category_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    category = await OfferingResolver.resolve_category(
        session, business_id=business_id, category_id=category_id
    )
    return {
        "data": CategoryService.serialize(category),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/product-categories/{category_id}")
async def patch_category(
    business_id: UUID,
    category_id: UUID,
    body: PatchCategoryRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    parsed = _patch_payload(body)
    category = await CategoryService.patch_category(
        session,
        business_id=business_id,
        category_id=category_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=parsed["payload"],
        expected_version=parsed["version"],
    )
    await session.commit()
    return {
        "data": CategoryService.serialize(category),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/product-categories/{category_id}/archive")
async def archive_category(
    business_id: UUID,
    category_id: UUID,
    body: VersionedBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_ARCHIVE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    category = await CategoryService.archive_category(
        session,
        business_id=business_id,
        category_id=category_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": CategoryService.serialize(category),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/products")
async def list_products(
    business_id: UUID,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    category_id: UUID | None = Query(default=None),
    track_inventory: bool | None = Query(default=None),
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    offerings = await OfferingService.list_for_business(
        session,
        business_id,
        status=status,
        search=search,
        category_id=category_id,
        track_inventory=track_inventory,
    )
    return {
        "data": [OfferingService.serialize(o) for o in offerings],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(offerings)},
    }


@router.post("/{business_id}/products")
async def create_product(
    business_id: UUID,
    body: CreateProductRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_CREATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    offering = await OfferingService.create_offering(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": OfferingService.serialize(offering),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/products/{product_id}")
async def get_product(
    business_id: UUID,
    product_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    offering = await OfferingResolver.resolve(
        session, business_id=business_id, offering_id=product_id
    )
    images = await MediaService.resolve_many(
        session, business_id=business_id, asset_ids=list(offering.image_asset_ids or [])
    )
    return {
        "data": {**OfferingService.serialize(offering), "images": images},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/products/{product_id}/generate-image")
async def generate_product_image(
    business_id: UUID,
    product_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Draw an illustrative picture of this offering (a draft the owner can keep
    or replace). Where only a real photo is honest, says so instead."""
    from platform_core.services.website_images import WebsiteImageService

    result = await WebsiteImageService.generate_offering_image(
        session, business_id=business_id, actor_id=actor.request.identity_id, offering_id=product_id,
        correlation_id=actor.request.correlation_id)
    if result.get("reason") == "offering_missing":
        raise ResourceNotFound("Offering")
    await session.commit()
    return {"data": result, "meta": {"correlation_id": actor.request.correlation_id}}


@router.patch("/{business_id}/products/{product_id}")
async def patch_product(
    business_id: UUID,
    product_id: UUID,
    body: PatchProductRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    parsed = _patch_payload(body)
    offering = await OfferingService.patch_offering(
        session,
        business_id=business_id,
        offering_id=product_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=parsed["payload"],
        expected_version=parsed["version"],
    )
    await session.commit()
    return {
        "data": OfferingService.serialize(offering),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/products/{product_id}/archive")
async def archive_product(
    business_id: UUID,
    product_id: UUID,
    body: VersionedBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_ARCHIVE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    offering = await OfferingService.archive_offering(
        session,
        business_id=business_id,
        offering_id=product_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": OfferingService.serialize(offering),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/products/{product_id}/restore")
async def restore_product(
    business_id: UUID,
    product_id: UUID,
    body: VersionedBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    offering = await OfferingService.restore_offering(
        session,
        business_id=business_id,
        offering_id=product_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": OfferingService.serialize(offering),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/products/{product_id}/variants")
async def list_variants(
    business_id: UUID,
    product_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    variants = await OfferingService.list_variants(
        session, business_id=business_id, offering_id=product_id
    )
    return {
        "data": [OfferingService.serialize_variant(v) for v in variants],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(variants)},
    }


@router.post("/{business_id}/products/{product_id}/variants")
async def create_variant(
    business_id: UUID,
    product_id: UUID,
    body: CreateVariantRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    variant = await OfferingService.create_variant(
        session,
        business_id=business_id,
        offering_id=product_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": OfferingService.serialize_variant(variant),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/products/{product_id}/variants/matrix")
async def generate_variant_matrix(
    business_id: UUID,
    product_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """One variant per combination of the product's options (size × colour)."""
    created = await OfferingService.generate_variant_matrix(
        session, business_id=business_id, offering_id=product_id, actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {"data": [OfferingService.serialize_variant(v) for v in created],
            "meta": {"correlation_id": actor.request.correlation_id, "created": len(created)}}



# ---------------------------------------------------------------- rate board
# Formula pricing (P1-10D2b, OK-15; MD §21.2): the rates the owner enters each
# day (22K gold per g, silver per g, …) and the items priced from them.


class CreateRateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60)
    unit: str = "g"
    value: float | None = Field(default=None, gt=0)


class RateValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=200)


@router.get("/{business_id}/pricing/rates")
async def list_rates(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    from platform_core.pricing.formula import RateService

    return {"data": await RateService.board(session, business_id),
            "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/pricing/rates")
async def create_rate(
    business_id: UUID,
    body: CreateRateRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    from platform_core.pricing.formula import RateService

    rate = await RateService.create(session, business_id, actor.request.identity_id, label=body.label,
                                    unit=body.unit)
    data = RateService.serialize(rate, None)
    if body.value is not None:
        data = (await RateService.set_value(session, business_id, actor.request.identity_id, rate.id,
                                            value=body.value, note=None,
                                            correlation_id=actor.request.correlation_id))["rate"]
    await session.commit()
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/pricing/rates/{rate_id}/values")
async def set_rate_value(
    business_id: UUID,
    rate_id: UUID,
    body: RateValueRequest,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, "offerings-catalog")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    from platform_core.pricing.formula import RateService

    result = await RateService.set_value(session, business_id, actor.request.identity_id, rate_id,
                                         value=body.value, note=body.note,
                                         correlation_id=actor.request.correlation_id)
    await session.commit()
    return {"data": result, "meta": {"correlation_id": actor.request.correlation_id}}
