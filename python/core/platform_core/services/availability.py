"""Booking availability and conflict prevention.

Overlap/capacity engine unchanged architecturally (Doc 11 §17.5).
Provider reference cut over from BusinessEmployee → WorkforceMember (Doc 10 §4.8).
"""

from __future__ import annotations

import uuid
import zlib
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ValidationError
from platform_core.business_types import DEFAULT_TIMEZONE
from platform_core.models import Booking, BusinessLocation, Offering
from platform_core.services.workforce import WorkforceService
from platform_core.validation.booking import RESERVATION_MODES

ACTIVE_STATUSES = ("pending", "confirmed", "checked_in")


class AvailabilityService:
    @staticmethod
    async def _acquire_slot_lock(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID,
        reservation_mode: str,
    ) -> None:
        """Serialise every capacity check for one mode at one location.

        The key used to include the provider and the offering, so a request
        naming the instructor and one that did not queued on different locks
        and could both see the last place free. The pool being summed is the
        location's bookings of this mode (narrowed by offering when there is
        one), so that is what the lock covers. Held to the end of the
        transaction: the check and the insert commit together. Provider
        exclusivity does not rely on it - that is the allocation's exclusion
        constraint.
        """
        key = f"{business_id}:{location_id}:{reservation_mode}"
        lock_id = zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_id})

    @staticmethod
    async def configured_capacity(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        offering_id: uuid.UUID | None,
        reservation_mode: str,
    ) -> int | None:
        """A class's places per session, as the owner set them on the class.

        Configuration outranks the request: a caller must not be able to lift
        the limit by sending a bigger number, and a guest - who sends none -
        must still meet it.
        """
        if reservation_mode not in ("class_session", "event_date") or offering_id is None:
            return None
        attributes = (
            await session.execute(
                select(Offering.attributes).where(
                    Offering.id == offering_id, Offering.business_id == business_id
                )
            )
        ).scalar_one_or_none()
        try:
            places = int((attributes or {}).get("capacity") or 0)
        except (TypeError, ValueError):
            return None
        if reservation_mode == "event_date":
            # The date is what is scarce: one booking per date unless the owner
            # says the offering takes more (a caterer doing two events a day).
            return places if places > 0 else 1
        return places if places > 0 else None

    @staticmethod
    async def assert_provider_can_take(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        provider_id: uuid.UUID,
        location_id: uuid.UUID,
        offering_id: uuid.UUID | None,
        starts_at: datetime,
        ends_at: datetime,
    ) -> None:
        """Works here, does this service, and is on duty then (Workforce's own
        schedule: weekly hours, dated leave or one-off hours, blocks)."""
        member = await WorkforceService.assert_provider_eligible(
            session,
            business_id=business_id,
            provider_id=provider_id,
            location_id=location_id,
            offering_id=offering_id,
        )
        location = await session.get(BusinessLocation, location_id)
        await WorkforceService.assert_on_duty(
            session,
            business_id=business_id,
            member=member,
            location_id=location_id,
            starts_at=starts_at,
            ends_at=ends_at,
            zone=(location.timezone if location is not None else None) or DEFAULT_TIMEZONE,
        )

    @staticmethod
    async def free_provider(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID,
        offering_id: uuid.UUID | None,
        starts_at: datetime,
        ends_at: datetime,
        exclude_booking_id: uuid.UUID | None = None,
    ) -> tuple[bool, uuid.UUID | None]:
        """For a booking with no person chosen: (whether named people give this
        service, the first of them who works here then and is free). (False,
        None) when nobody is named for it — the business does not book it by
        person, and nothing changes for it."""
        from platform_core.models import WorkforceMember, WorkforceServiceAssociation

        if offering_id is None:
            return False, None
        members = (await session.execute(
            select(WorkforceMember.id)
            .join(WorkforceServiceAssociation, WorkforceServiceAssociation.member_id == WorkforceMember.id)
            .where(
                WorkforceServiceAssociation.business_id == business_id,
                WorkforceServiceAssociation.offering_id == offering_id,
                WorkforceMember.business_id == business_id,
                WorkforceMember.deleted_at.is_(None),
                WorkforceMember.status == "active",
            )
            .order_by(WorkforceMember.display_name.asc(), WorkforceMember.id.asc())
        )).scalars().all()
        if not members:
            return False, None
        for member_id in dict.fromkeys(members):
            try:
                await AvailabilityService.assert_provider_can_take(
                    session, business_id=business_id, provider_id=member_id, location_id=location_id,
                    offering_id=offering_id, starts_at=starts_at, ends_at=ends_at)
            except (ValidationError, ConflictError):
                continue
            if await AvailabilityService._provider_conflict(
                session, business_id=business_id, provider_id=member_id, starts_at=starts_at,
                ends_at=ends_at, exclude_booking_id=exclude_booking_id,
            ):
                continue
            return True, member_id
        return True, None

    @staticmethod
    def closed_reason(
        location: BusinessLocation, reservation_mode: str, starts_at: datetime, ends_at: datetime
    ) -> str | None:
        """Why a guest cannot book this time at this location, from the opening
        hours the owner saved ({"mon": [["09:00", "18:00"]], ...}); None if open.

        No hours saved means none are known, and none are invented. Stays and
        rentals run across days and are not held to a day's opening spans.
        """
        hours = location.hours or {}
        if not hours or reservation_mode not in {"appointment", "table", "class_session", "site_visit"}:
            return None
        tz = ZoneInfo(location.timezone or DEFAULT_TIMEZONE)
        local_start, local_end = starts_at.astimezone(tz), ends_at.astimezone(tz)
        day = local_start.date()
        ends_at_midnight = local_end.date() == day + timedelta(days=1) and local_end.time() == time(0, 0)
        if local_end.date() != day and not ends_at_midnight:
            return "That runs past closing time"
        begin, finish = local_start.time(), (time(23, 59, 59) if ends_at_midnight else local_end.time())
        spans = []
        for span in hours.get(day.strftime("%a").lower()[:3]) or []:
            try:
                spans.append((time.fromisoformat(span[0]), time.fromisoformat(span[1])))
            except (ValueError, TypeError, IndexError):
                continue
        if not spans:
            return "Closed that day"
        if not any(open_at <= begin and close_at >= finish for open_at, close_at in spans):
            return "Outside opening hours"
        return None

    @staticmethod
    async def assert_open(
        session: AsyncSession,
        *,
        location_id: uuid.UUID,
        reservation_mode: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> None:
        location = await session.get(BusinessLocation, location_id)
        if location is None:
            return
        reason = AvailabilityService.closed_reason(location, reservation_mode, starts_at, ends_at)
        if reason:
            raise ConflictError(reason, details={"code": "closed", "location_id": str(location_id)})

    @staticmethod
    async def _provider_conflict(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        provider_id: uuid.UUID,
        starts_at: Any,
        ends_at: Any,
        exclude_booking_id: uuid.UUID | None,
    ) -> bool:
        query = select(Booking.id).where(
            Booking.business_id == business_id,
            Booking.provider_id == provider_id,
            Booking.deleted_at.is_(None),
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.starts_at < ends_at,
            Booking.ends_at > starts_at,
        )
        if exclude_booking_id:
            query = query.where(Booking.id != exclude_booking_id)
        return (await session.execute(query.limit(1))).scalars().first() is not None

    @staticmethod
    async def places_left(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID,
        offering_id: uuid.UUID | None,
        reservation_mode: str,
        starts_at: Any,
        ends_at: Any,
    ) -> int | None:
        """How many places a class (or event date) still has, from its own
        configured places; None when it states none."""
        capacity = await AvailabilityService.configured_capacity(
            session, business_id=business_id, offering_id=offering_id, reservation_mode=reservation_mode
        )
        if capacity is None:
            return None
        used = await AvailabilityService._capacity_usage(
            session, business_id=business_id, location_id=location_id, offering_id=offering_id,
            reservation_mode=reservation_mode, starts_at=starts_at, ends_at=ends_at, exclude_booking_id=None,
        )
        return max(capacity - used, 0)

    @staticmethod
    async def _capacity_usage(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID,
        offering_id: uuid.UUID | None,
        reservation_mode: str,
        starts_at: Any,
        ends_at: Any,
        exclude_booking_id: uuid.UUID | None,
    ) -> int:
        query = select(func.coalesce(func.sum(Booking.party_size), 0)).where(
            Booking.business_id == business_id,
            Booking.location_id == location_id,
            Booking.reservation_mode == reservation_mode,
            Booking.deleted_at.is_(None),
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.starts_at < ends_at,
            Booking.ends_at > starts_at,
        )
        if offering_id:
            query = query.where(Booking.offering_id == offering_id)
        if exclude_booking_id:
            query = query.where(Booking.id != exclude_booking_id)
        result = await session.execute(query)
        return int(result.scalar_one())

    @staticmethod
    async def assert_available(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID,
        provider_id: uuid.UUID | None,
        offering_id: uuid.UUID | None,
        reservation_mode: str,
        starts_at: Any,
        ends_at: Any,
        party_size: int,
        capacity: int | None,
        exclude_booking_id: uuid.UUID | None = None,
    ) -> None:
        if reservation_mode not in RESERVATION_MODES:
            raise ValidationError("Invalid reservation mode")

        await AvailabilityService._acquire_slot_lock(
            session,
            business_id=business_id,
            location_id=location_id,
            reservation_mode=reservation_mode,
        )
        configured = await AvailabilityService.configured_capacity(
            session,
            business_id=business_id,
            offering_id=offering_id,
            reservation_mode=reservation_mode,
        )
        if configured is not None:
            capacity = configured

        # Appointment: provider exclusivity — NOT a capacity/room pool (Doc 11 §17.5).
        if provider_id:
            await AvailabilityService.assert_provider_can_take(
                session,
                business_id=business_id,
                provider_id=provider_id,
                location_id=location_id,
                offering_id=offering_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if await AvailabilityService._provider_conflict(
                session,
                business_id=business_id,
                provider_id=provider_id,
                starts_at=starts_at,
                ends_at=ends_at,
                exclude_booking_id=exclude_booking_id,
            ):
                raise ConflictError(
                    "Provider is not available for this time slot",
                    details={"provider_id": str(provider_id)},
                )
        elif reservation_mode == "appointment":
            # "Anyone available": where named people give this service, one of
            # them must work then and be free (owner lab, salon: 16:00 was
            # offered and taken twice with the only stylist already booked).
            scheduled, free = await AvailabilityService.free_provider(
                session, business_id=business_id, location_id=location_id, offering_id=offering_id,
                starts_at=starts_at, ends_at=ends_at, exclude_booking_id=exclude_booking_id)
            if scheduled and free is None:
                raise ConflictError(
                    "Nobody who gives this service is free then",
                    details={"code": "no_provider_free"},
                )

        # Capacity modes: date-range / slot capacity — NOT inventory stock decrement.
        if reservation_mode in {"table", "class_session", "rental", "accommodation", "event_date"} and capacity:
            used = await AvailabilityService._capacity_usage(
                session,
                business_id=business_id,
                location_id=location_id,
                offering_id=offering_id,
                reservation_mode=reservation_mode,
                starts_at=starts_at,
                ends_at=ends_at,
                exclude_booking_id=exclude_booking_id,
            )
            if used + party_size > capacity:
                raise ConflictError(
                    "Capacity exceeded for this time slot",
                    details={
                        "capacity": capacity,
                        "used": used,
                        "requested": party_size,
                    },
                )

    @staticmethod
    async def check_availability(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            await AvailabilityService.assert_available(
                session,
                business_id=business_id,
                location_id=params["location_id"],
                provider_id=params.get("provider_id"),
                offering_id=params.get("offering_id"),
                reservation_mode=params["reservation_mode"],
                starts_at=params["starts_at"],
                ends_at=params["ends_at"],
                party_size=params["party_size"],
                capacity=params.get("capacity"),
                exclude_booking_id=params.get("exclude_booking_id"),
            )
            available = True
            reason = None
        except ConflictError as exc:
            available = False
            reason = str(getattr(exc, "detail", exc))
            if isinstance(exc.detail, dict):
                reason = str(exc.detail.get("message", reason))
        except ValidationError as exc:
            available = False
            reason = str(getattr(exc, "detail", exc))
            if isinstance(exc.detail, dict):
                reason = str(exc.detail.get("message", reason))
        return {"available": available, "reason": reason}
