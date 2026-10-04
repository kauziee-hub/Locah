"""Platform orders APIs (Stage 6)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.exceptions import PlatformError
from platform_core.permissions import (
    ORDERS_CANCEL,
    ORDERS_CREATE,
    ORDERS_READ,
    ORDERS_UPDATE_STATUS,
)
from platform_core.resolvers.order_resolver import OrderResolver
from platform_core.services.order import OrderService
from platform_core.services.order_lifecycle import OrderLifecycleService
from platform_core.services.order_note import OrderNoteService

router = APIRouter(prefix="/v1/platform/businesses", tags=["orders"])


class VersionedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)


class OrderLineItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(ge=1)
    unit_price: float | None = Field(default=None, ge=0)
    options: dict[str, Any] | None = None


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: UUID
    customer_contact_id: UUID | None = None
    payment_method: str = "cod"
    currency: str = "INR"
    discount_amount: float = Field(default=0, ge=0)
    internal_reference: str | None = None
    idempotency_key: str | None = None
    # GST place of supply (two-digit state code) when the buyer's state is
    # known and differs from the shop's (Capability Universe §14.4).
    place_of_supply: str | None = Field(default=None, min_length=2, max_length=2)
    # Taken in the Workspace: over the phone or in person (Capability Universe §6.1 channel).
    channel: Literal["phone", "workspace"] = "workspace"
    # When it is wanted (dated pre-orders, P1-10D2): ISO time, checked against the items' rules.
    due_at: str | None = None
    items: list[OrderLineItemInput] = Field(min_length=1)


class PatchOrderRequest(VersionedBody):
    internal_reference: str | None = None
    payment_status: str | None = None


class StatusTransitionRequest(VersionedBody):
    status: str
    reason: str | None = None


class CancelOrderRequest(VersionedBody):
    reason: str


class CreateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


def _patch_payload(body: BaseModel) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    return {"payload": data, "version": version}


@router.get("/{business_id}/orders")
async def list_orders(
    business_id: UUID,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    customer_contact_id: UUID | None = Query(default=None),
    location_id: UUID | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=20),
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_READ, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    orders = await OrderService.list_for_business(
        session,
        business_id,
        status=status,
        search=search,
        customer_contact_id=customer_contact_id,
        location_id=location_id,
        channel=channel,
    )
    return {
        "data": [OrderService.serialize_order(o) for o in orders],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(orders)},
    }


@router.get("/{business_id}/orders/board")
async def preorder_board(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_READ, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Dated orders by when they are wanted: overdue, prepare now, today, tomorrow, later (P1-10D2)."""
    from platform_core.orders.board import board

    return {"data": await board(session, business_id), "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/orders/production")
async def production_list(
    business_id: UUID,
    day: date | None = Query(default=None, alias="date"),
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_READ, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """What to make for one day, added up, with each written message (P1-10D2)."""
    from platform_core.orders.board import _zone, production

    if day is None:
        day = datetime.now(timezone.utc).astimezone(await _zone(session, business_id)).date()
    return {"data": await production(session, business_id, day),
            "meta": {"correlation_id": actor.request.correlation_id}}


# ---------------------------------------------------------------- phone orders and changes (P1-10E5; FR-OR-13, FR-OR-18)
class PhoneOrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: dict[str, Any] = Field(default_factory=dict)
    items: list[dict[str, Any]]
    fulfilment_mode: str = "pickup"
    delivery_address: dict[str, Any] | None = None
    payment_method: str = "cod"
    due: dict[str, Any] | None = None
    location_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)


class PhonePriceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    fulfilment_mode: str | None = None
    delivery_address: dict[str, Any] | None = None
    due: dict[str, Any] | None = None


class ChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[dict[str, Any]]
    reason: str | None = Field(default=None, max_length=300)
    customer_agreed: bool = False
    version: int | None = Field(default=None, ge=1)


@router.post("/{business_id}/orders/phone/price")
async def price_phone_order(
    business_id: UUID,
    body: PhonePriceBody,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_CREATE, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """What the caller will pay, priced by the server exactly as the website would."""
    from platform_core.orders.phone import price

    data = await price(session, actor.business, body.model_dump(exclude_none=True))
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/orders/phone")
async def place_phone_order(
    business_id: UUID,
    body: PhoneOrderBody,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_CREATE, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """A phone order taken by staff: the same order path as the website (FR-OR-13)."""
    from platform_core.orders.phone import place

    payload = body.model_dump(exclude_none=True)
    if body.location_id:
        payload["location_id"] = str(body.location_id)
    data = await place(session, actor.business, actor_id=actor.request.identity_id,
                       correlation_id=actor.request.correlation_id, payload=payload)
    await session.commit()
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/orders/{order_id}/change")
async def change_order(
    business_id: UUID,
    order_id: UUID,
    body: ChangeBody,
    preview: bool = Query(default=False),
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_CREATE, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Change an open order's items; ?preview=true shows the result without saving (FR-OR-18)."""
    from platform_core.orders.edit import change

    data = await change(session, business_id=business_id, order_id=order_id, actor_id=actor.request.identity_id,
                        correlation_id=actor.request.correlation_id, lines=body.lines, reason=body.reason,
                        customer_agreed=body.customer_agreed, expected_version=body.version, preview=preview)
    if not preview:
        await session.commit()
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/orders")
async def create_order(
    business_id: UUID,
    body: CreateOrderRequest,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_CREATE, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    order = await OrderService.create_order(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    data = await OrderService.serialize_order_with_items(session, order)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/orders/{order_id}")
async def get_order(
    business_id: UUID,
    order_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_READ, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    order = await OrderResolver.resolve(session, business_id=business_id, order_id=order_id)
    data = await OrderService.serialize_order_with_items(session, order)
    # Who it is for and how it reaches them — the order page shows both.
    from platform_core.resolvers.customer_resolver import CustomerResolver
    from platform_core.services.fulfilment import FulfilmentService

    data["customer"] = None
    if order.customer_contact_id:
        try:
            contact = await CustomerResolver.resolve(session, business_id=business_id,
                                                     contact_id=order.customer_contact_id)
            data["customer"] = {"id": str(contact.id), "name": contact.display_name, "phone": contact.phone}
        except PlatformError:
            data["customer"] = None
    data["fulfilment"] = await FulfilmentService.for_order(session, business_id, order.id)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/orders/{order_id}")
async def patch_order(
    business_id: UUID,
    order_id: UUID,
    body: PatchOrderRequest,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_UPDATE_STATUS, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    parsed = _patch_payload(body)
    order = await OrderService.patch_order(
        session,
        business_id=business_id,
        order_id=order_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=parsed["payload"],
        expected_version=parsed["version"],
    )
    await session.commit()
    data = await OrderService.serialize_order_with_items(session, order)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/orders/{order_id}/status")
async def transition_order_status(
    business_id: UUID,
    order_id: UUID,
    body: StatusTransitionRequest,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_UPDATE_STATUS, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    order = await OrderLifecycleService.transition_status(
        session,
        business_id=business_id,
        order_id=order_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(exclude={"version"}),
        expected_version=body.version,
    )
    await session.commit()
    data = await OrderService.serialize_order_with_items(session, order)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/orders/{order_id}/cancel")
async def cancel_order(
    business_id: UUID,
    order_id: UUID,
    body: CancelOrderRequest,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_CANCEL, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    order = await OrderLifecycleService.transition_status(
        session,
        business_id=business_id,
        order_id=order_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload={"status": "cancelled", "reason": body.reason},
        expected_version=body.version,
    )
    await session.commit()
    data = await OrderService.serialize_order_with_items(session, order)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/orders/{order_id}/complete")
async def complete_order(
    business_id: UUID,
    order_id: UUID,
    body: VersionedBody,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_UPDATE_STATUS, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    order = await OrderLifecycleService.transition_status(
        session,
        business_id=business_id,
        order_id=order_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload={"status": "completed"},
        expected_version=body.version,
    )
    await session.commit()
    data = await OrderService.serialize_order_with_items(session, order)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/orders/{order_id}/history")
async def get_order_history(
    business_id: UUID,
    order_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_READ, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    history = await OrderService.get_status_history(
        session, business_id=business_id, order_id=order_id
    )
    return {
        "data": [OrderResolver.serialize_status_history(h) for h in history],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(history)},
    }


@router.get("/{business_id}/orders/{order_id}/notes")
async def list_order_notes(
    business_id: UUID,
    order_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_READ, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    notes = await OrderNoteService.list_for_order(
        session, business_id=business_id, order_id=order_id
    )
    return {
        "data": [OrderNoteService.serialize(n) for n in notes],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(notes)},
    }


@router.post("/{business_id}/orders/{order_id}/notes")
async def create_order_note(
    business_id: UUID,
    order_id: UUID,
    body: CreateNoteRequest,
    actor: BusinessActorContext = Depends(require_business_actor(ORDERS_UPDATE_STATUS, "orders")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    note = await OrderNoteService.create_note(
        session,
        business_id=business_id,
        order_id=order_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        body=body.body,
    )
    await session.commit()
    return {
        "data": OrderNoteService.serialize(note),
        "meta": {"correlation_id": actor.request.correlation_id},
    }
