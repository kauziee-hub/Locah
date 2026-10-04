"""Platform bookings APIs (Stage 7)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.permissions import (
    BOOKINGS_CANCEL,
    BOOKINGS_CREATE,
    BOOKINGS_MANAGE_AVAILABILITY,
    BOOKINGS_READ,
    BOOKINGS_UPDATE,
)
from platform_core.resolvers.booking_resolver import BookingResolver
from platform_core.services.availability import AvailabilityService
from platform_core.services.booking import BookingService
from platform_core.services.booking_lifecycle import BookingLifecycleService
from platform_core.services.booking_note import BookingNoteService
from platform_core.models import Business
from platform_core.services.booking_series import BookingSeriesService
from platform_core.services.booking_waitlist import BookingWaitlistService
from platform_core.validation.booking import parse_datetime, validate_availability_query

router = APIRouter(prefix="/v1/platform/businesses", tags=["bookings"])


class VersionedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)


class CreateBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: UUID
    customer_contact_id: UUID | None = None
    offering_id: UUID | None = None
    provider_id: UUID | None = None
    employee_id: UUID | None = None  # legacy alias → provider_id
    reservation_mode: str = "appointment"
    title: str | None = None
    starts_at: str
    ends_at: str
    party_size: int = Field(default=1, ge=1)
    guest_count: int | None = None
    # Accepted from staff only, and only for a business with no resources
    # configured. Once resources exist their capacity wins; see
    # BookingService.create_booking.
    capacity: int | None = Field(default=None, ge=1)
    resource_ids: list[UUID] = Field(default_factory=list, max_length=8)
    payment_method: str = "cod"
    internal_reference: str | None = None
    idempotency_key: str | None = None


class PatchBookingRequest(VersionedBody):
    internal_reference: str | None = None
    payment_status: str | None = None


class StatusTransitionRequest(VersionedBody):
    status: str
    reason: str | None = None


class RescheduleRequest(VersionedBody):
    starts_at: str
    ends_at: str
    reason: str | None = None


class CancelBookingRequest(VersionedBody):
    reason: str


class CreateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


class BookingsPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_deposit: bool | None = None
    deposit_amount: float | None = None
    deposit_percent: float | None = None
    cancel_window_hours: int | None = Field(default=None, ge=0)
    hold_minutes: int | None = Field(default=None, ge=5, le=1440)
    waitlist_enabled: bool | None = None
    waitlist_offer_minutes: int | None = Field(default=None, ge=5, le=2880)


class WaitlistJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_contact_id: UUID
    location_id: UUID
    offering_id: UUID | None = None
    provider_id: UUID | None = None
    reservation_mode: str = "appointment"
    starts_at: str
    ends_at: str
    party_size: int = Field(default=1, ge=1)


class RepeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_weeks: int = Field(default=1, ge=1, le=4)
    occurrences: int = Field(ge=2, le=52)


class SeriesChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_booking_id: UUID
    starts_at: str
    ends_at: str


class SeriesEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_booking_id: UUID


class AvailabilityCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: UUID
    provider_id: UUID | None = None
    employee_id: UUID | None = None  # legacy alias → provider_id
    offering_id: UUID | None = None
    reservation_mode: str = "appointment"
    starts_at: str
    ends_at: str
    party_size: int = Field(default=1, ge=1)
    capacity: int | None = Field(default=None, ge=1)
    exclude_booking_id: UUID | None = None


def _patch_payload(body: BaseModel) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    return {"payload": data, "version": version}


@router.get("/{business_id}/bookings")
async def list_bookings(
    business_id: UUID,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    customer_contact_id: UUID | None = Query(default=None),
    location_id: UUID | None = Query(default=None),
    provider_id: UUID | None = Query(default=None),
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    bookings = await BookingService.list_for_business(
        session,
        business_id,
        status=status,
        search=search,
        customer_contact_id=customer_contact_id,
        location_id=location_id,
        provider_id=provider_id,
    )
    return {
        "data": await BookingService.describe(session, business_id, list(bookings)),
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(bookings)},
    }


@router.post("/{business_id}/bookings")
async def create_booking(
    business_id: UUID,
    body: CreateBookingRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_CREATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    booking = await BookingService.create_booking(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(),
    )
    await session.commit()
    return {
        "data": BookingService.serialize(booking),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/bookings/{booking_id}")
async def get_booking(
    business_id: UUID,
    booking_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    booking = await BookingResolver.resolve(session, business_id=business_id, booking_id=booking_id)
    return {
        "data": (await BookingService.describe(session, business_id, [booking]))[0],
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/bookings/{booking_id}")
async def patch_booking(
    business_id: UUID,
    booking_id: UUID,
    body: PatchBookingRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_UPDATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    parsed = _patch_payload(body)
    booking = await BookingService.patch_booking(
        session,
        business_id=business_id,
        booking_id=booking_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=parsed["payload"],
        expected_version=parsed["version"],
    )
    await session.commit()
    return {
        "data": BookingService.serialize(booking),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/bookings/{booking_id}/status")
async def transition_booking_status(
    business_id: UUID,
    booking_id: UUID,
    body: StatusTransitionRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_UPDATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    booking = await BookingLifecycleService.transition_status(
        session,
        business_id=business_id,
        booking_id=booking_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(exclude={"version"}),
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": BookingService.serialize(booking),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/bookings/{booking_id}/cancel")
async def cancel_booking(
    business_id: UUID,
    booking_id: UUID,
    body: CancelBookingRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_CANCEL, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    booking = await BookingLifecycleService.transition_status(
        session,
        business_id=business_id,
        booking_id=booking_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload={"status": "cancelled", "reason": body.reason},
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": BookingService.serialize(booking),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/bookings/{booking_id}/reschedule")
async def reschedule_booking(
    business_id: UUID,
    booking_id: UUID,
    body: RescheduleRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_UPDATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    booking = await BookingLifecycleService.reschedule(
        session,
        business_id=business_id,
        booking_id=booking_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        payload=body.model_dump(exclude={"version"}),
        expected_version=body.version,
    )
    await session.commit()
    return {
        "data": BookingService.serialize(booking),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/bookings/{booking_id}/history")
async def get_booking_history(
    business_id: UUID,
    booking_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    history = await BookingService.get_status_history(
        session, business_id=business_id, booking_id=booking_id
    )
    return {
        "data": [BookingResolver.serialize_status_history(h) for h in history],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(history)},
    }


@router.get("/{business_id}/bookings/{booking_id}/notes")
async def list_booking_notes(
    business_id: UUID,
    booking_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    notes = await BookingNoteService.list_for_booking(
        session, business_id=business_id, booking_id=booking_id
    )
    return {
        "data": [BookingNoteService.serialize(n) for n in notes],
        "meta": {"correlation_id": actor.request.correlation_id, "count": len(notes)},
    }


@router.post("/{business_id}/bookings/{booking_id}/notes")
async def create_booking_note(
    business_id: UUID,
    booking_id: UUID,
    body: CreateNoteRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_UPDATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    note = await BookingNoteService.create_note(
        session,
        business_id=business_id,
        booking_id=booking_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        body=body.body,
    )
    await session.commit()
    return {
        "data": BookingNoteService.serialize(note),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/bookings/check-availability")
async def check_booking_availability(
    business_id: UUID,
    body: AvailabilityCheckRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_MANAGE_AVAILABILITY, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    params = validate_availability_query(body.model_dump())
    result = await AvailabilityService.check_availability(
        session, business_id=business_id, params=params
    )
    return {
        "data": result,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/bookings-policy")
async def get_bookings_policy(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    policy = await BookingService.get_or_create_policy(session, business_id)
    await session.commit()
    return {
        "data": BookingService.serialize_policy(policy),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/bookings-policy")
async def patch_bookings_policy(
    business_id: UUID,
    body: BookingsPolicyRequest,
    # The business-wide deposit and cancellation rules are the manager's, not
    # every person who moves a booking along (a provider holds bookings.update
    # for their own appointments only — P2-01).
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_MANAGE_AVAILABILITY, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    policy = await BookingService.update_policy(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        payload=body.model_dump(exclude_unset=True),
    )
    await session.commit()
    return {
        "data": BookingService.serialize_policy(policy),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


# ------------------------------------------------------------------ waitlist


@router.get("/{business_id}/bookings-waitlist")
async def list_waitlist(
    business_id: UUID,
    status: str | None = Query(default=None),
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    business = await session.get(Business, business_id)
    assert business is not None
    entries = await BookingWaitlistService.list_entries(session, business_id, status)
    return {
        "data": [BookingWaitlistService.serialize(e, with_link=BookingWaitlistService.offer_link(business, e))
                 for e in entries],
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/bookings-waitlist")
async def join_waitlist(
    business_id: UUID,
    body: WaitlistJoinRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_CREATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = body.model_dump(mode="json")
    entry = await BookingWaitlistService.join(
        session, business_id=business_id, customer_contact_id=body.customer_contact_id,
        payload={k: v for k, v in data.items() if k != "customer_contact_id"},
        actor_id=actor.request.identity_id, correlation_id=actor.request.correlation_id, channel="workspace")
    await session.commit()
    return {"data": BookingWaitlistService.serialize(entry), "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/bookings-waitlist/{entry_id}/withdraw")
async def withdraw_waitlist(
    business_id: UUID,
    entry_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_UPDATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    entry = await BookingWaitlistService.withdraw(session, business_id, entry_id, actor.request.identity_id)
    await session.commit()
    return {"data": BookingWaitlistService.serialize(entry), "meta": {"correlation_id": actor.request.correlation_id}}


# ------------------------------------------------------------------ series


@router.post("/{business_id}/bookings/{booking_id}/repeat")
async def repeat_booking(
    business_id: UUID,
    booking_id: UUID,
    body: RepeatRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_CREATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await BookingSeriesService.repeat(
        session, business_id=business_id, booking_id=booking_id, actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id, interval_weeks=body.interval_weeks,
        occurrences=body.occurrences)
    await session.commit()
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.get("/{business_id}/bookings-series/{series_id}")
async def get_series(
    business_id: UUID,
    series_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_READ, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    series = await BookingSeriesService.get(session, business_id, series_id)
    return {"data": await BookingSeriesService.serialize(session, series),
            "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/bookings-series/{series_id}/change-future")
async def change_series_future(
    business_id: UUID,
    series_id: UUID,
    body: SeriesChangeRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_UPDATE, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await BookingSeriesService.change_future(
        session, business_id=business_id, series_id=series_id, from_booking_id=body.from_booking_id,
        starts_at=parse_datetime(body.starts_at, field="starts_at"),
        ends_at=parse_datetime(body.ends_at, field="ends_at"),
        actor_id=actor.request.identity_id, correlation_id=actor.request.correlation_id)
    await session.commit()
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/bookings-series/{series_id}/end")
async def end_series(
    business_id: UUID,
    series_id: UUID,
    body: SeriesEndRequest,
    actor: BusinessActorContext = Depends(require_business_actor(BOOKINGS_CANCEL, "bookings")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await BookingSeriesService.end(
        session, business_id=business_id, series_id=series_id, from_booking_id=body.from_booking_id,
        actor_id=actor.request.identity_id, correlation_id=actor.request.correlation_id)
    await session.commit()
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}
