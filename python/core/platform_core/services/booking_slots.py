"""What a customer can pick, per booking mode, from the one engine.

The website shows a different flow per mode (Founder refinement — Bookings
§5–§14, §28) but every answer here comes from the same checks the booking
path makes at commit: opening hours, the provider's schedule, capacity and
the class's own places, free resources and their buffers. Nothing is shown
that the commit would refuse; the commit still re-checks under its lock.

Modes: appointment, table, class_session, accommodation (stay), rental,
site_visit, event_date.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.business_types import DEFAULT_TIMEZONE
from platform_core.exceptions import ValidationError
from platform_core.models import BookingResource, BusinessLocation, Offering
from platform_core.services.availability import AvailabilityService
from platform_core.services.booking_allocation import BookingAllocationService

MODE_BY_KIND = {
    "service": "appointment", "class_session": "class_session", "accommodation": "accommodation",
    "rental": "rental", "property_project": "site_visit", "property_unit": "site_visit",
}
DEFAULT_MINUTES = {"appointment": 60, "class_session": 60, "table": 90, "site_visit": 60}
SLOT_MODES = frozenset({"appointment", "table", "class_session", "site_visit"})
# Stays run from check-in to check-out; an offering can say otherwise
# (attributes check_in / check_out as "HH:MM").
CHECK_IN, CHECK_OUT = time(14, 0), time(11, 0)
MAX_SLOTS = 32
EARLIEST = timedelta(minutes=30)


def mode_for(offering: Offering) -> str:
    attrs = offering.attributes or {}
    if attrs.get("whole_day") and offering.offering_type in ("service", "rental"):
        return "event_date"
    return MODE_BY_KIND.get(offering.offering_type, "appointment")


def minutes_for(offering: Offering | None, mode: str) -> int:
    try:
        value = int(((offering.attributes or {}) if offering else {}).get("duration_minutes") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_MINUTES.get(mode, 60)


def _clock(value: Any, default: time) -> time:
    try:
        return time.fromisoformat(str(value)) if value else default
    except ValueError:
        return default


async def stay_times(session: AsyncSession, business_id: uuid.UUID) -> tuple[time, time] | None:
    """A stay's check-in and check-out (its first live room type's), or None
    when the business takes no stays. The bookings module's public read: the
    Workspace home says these instead of asking a hotel for opening hours."""
    room = (await session.execute(select(Offering).where(
        Offering.business_id == business_id, Offering.deleted_at.is_(None), Offering.status == "active",
        Offering.offering_type == "accommodation",
    ).order_by(Offering.created_at).limit(1))).scalars().first()
    if room is None:
        return None
    attrs = room.attributes or {}
    return _clock(attrs.get("check_in"), CHECK_IN), _clock(attrs.get("check_out"), CHECK_OUT)


def zone(location: BusinessLocation) -> ZoneInfo:
    return ZoneInfo(location.timezone or DEFAULT_TIMEZONE)


def stay_window(location: BusinessLocation, offering: Offering | None, check_in: date,
                check_out: date) -> tuple[datetime, datetime]:
    if check_out <= check_in:
        raise ValidationError("Check-out must be after check-in", details={"field": "check_out"})
    attrs = (offering.attributes or {}) if offering else {}
    tz = zone(location)
    return (datetime.combine(check_in, _clock(attrs.get("check_in"), CHECK_IN), tz),
            datetime.combine(check_out, _clock(attrs.get("check_out"), CHECK_OUT), tz))


def stay_rule_broken(offering: Offering | None, location: BusinessLocation, starts_at: datetime,
                     ends_at: datetime) -> str | None:
    """The owner's shortest-stay rule this stay breaks, in the guest's words;
    None when it keeps them. "2-night minimum on weekends" is a stay over a
    Friday or Saturday night (owner lab, hotel: the rule was "noted" in the
    chat and a one-night Saturday was taken anyway)."""
    attrs = (offering.attributes or {}) if offering else {}
    tz = zone(location)
    first, last = starts_at.astimezone(tz).date(), ends_at.astimezone(tz).date()
    nights = (last - first).days
    try:
        least, weekend = int(attrs.get("min_nights") or 0), int(attrs.get("weekend_min_nights") or 0)
    except (TypeError, ValueError):
        return None
    over_weekend = any((first + timedelta(days=i)).weekday() in (4, 5) for i in range(max(nights, 0)))
    if weekend > least and over_weekend and nights < weekend:
        return f"A stay over a Friday or Saturday night is at least {weekend} nights"
    if least > 1 and nights < least:
        return f"A stay here is at least {least} nights"
    return None


def day_window(location: BusinessLocation, day: date) -> tuple[datetime, datetime]:
    tz = zone(location)
    start = datetime.combine(day, time(0, 0), tz)
    return start, start + timedelta(days=1)


class BookingSlotService:
    @staticmethod
    async def is_open(session: AsyncSession, business_id: uuid.UUID, params: dict[str, Any]) -> tuple[bool, str | None]:
        """The commit path's answer for one window: provider, capacity and the
        class's places, and - when the business allocates resources - a free one."""
        result = await AvailabilityService.check_availability(session, business_id=business_id, params=params)
        if not result["available"]:
            return False, result.get("reason")
        if await BookingAllocationService.has_resources(session, business_id=business_id,
                                                        location_id=params["location_id"],
                                                        mode=params["reservation_mode"]):
            free = await BookingAllocationService.free_resources(
                session, business_id=business_id, location_id=params["location_id"], resource_type=None,
                starts_at=params["starts_at"], ends_at=params["ends_at"], party_size=params["party_size"],
                mode=params["reservation_mode"], offering_id=params.get("offering_id"))
            if not free:
                return False, "Nothing is free for this time"
        return True, None

    @staticmethod
    async def day_slots(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location: BusinessLocation,
        mode: str,
        offering: Offering | None,
        provider_id: uuid.UUID | None,
        party_size: int,
        day: date,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Start times on one day for slot modes, each open at commit."""
        if mode not in SLOT_MODES:
            raise ValidationError("This kind of booking is not picked by time slots", details={"field": "mode"})
        tz = zone(location)
        hours = location.hours or {}
        spans: list[tuple[time, time]] = []
        for span in hours.get(day.strftime("%a").lower()[:3]) or []:
            try:
                spans.append((time.fromisoformat(span[0]), time.fromisoformat(span[1])))
            except (ValueError, TypeError, IndexError):
                continue
        if not hours:
            return {"hours_known": False, "closed": False, "slots": []}
        if not spans:
            return {"hours_known": True, "closed": True, "slots": []}
        minutes = minutes_for(offering, mode)
        step = timedelta(minutes=30 if minutes <= 60 else 60)
        length = timedelta(minutes=minutes)
        earliest = (now or datetime.now(timezone.utc)) + EARLIEST
        slots: list[dict[str, Any]] = []
        for open_at, close_at in spans:
            at = datetime.combine(day, open_at, tz)
            end = datetime.combine(day, close_at, tz)
            while at + length <= end and len(slots) < MAX_SLOTS:
                if at >= earliest:
                    params = {"location_id": location.id, "provider_id": provider_id,
                              "offering_id": offering.id if offering else None, "reservation_mode": mode,
                              "starts_at": at, "ends_at": at + length, "party_size": party_size,
                              "capacity": None, "exclude_booking_id": None}
                    open_, _ = await BookingSlotService.is_open(session, business_id, params)
                    places = await AvailabilityService.places_left(
                        session, business_id=business_id, location_id=location.id,
                        offering_id=offering.id if offering else None, reservation_mode=mode,
                        starts_at=at, ends_at=at + length) if mode == "class_session" else None
                    # A class that is full is still shown, as full - the guest may join its waitlist.
                    if open_ or places == 0:
                        slot: dict[str, Any] = {"starts_at": at.astimezone(timezone.utc).isoformat(),
                                                "ends_at": (at + length).astimezone(timezone.utc).isoformat(),
                                                "label": at.strftime("%H:%M"), "full": not open_}
                        if places is not None:
                            slot["places_left"] = places
                        slots.append(slot)
                at += step
        return {"hours_known": True, "closed": False, "slots": slots}

    @staticmethod
    async def range_check(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location: BusinessLocation,
        mode: str,
        offering: Offering | None,
        party_size: int,
        starts_at: datetime,
        ends_at: datetime,
    ) -> dict[str, Any]:
        """Stays, rentals and event dates: is this range free, and which
        rooms / items / halls could take it (the guest may pick one)."""
        if ends_at <= starts_at:
            raise ValidationError("The end must be after the start", details={"field": "ends_at"})
        if starts_at <= datetime.now(timezone.utc):
            return {"available": False, "reason": "That time has passed", "resources": []}
        if mode == "accommodation":
            broken = stay_rule_broken(offering, location, starts_at, ends_at)
            if broken:
                return {"available": False, "reason": broken, "code": "minimum_stay", "resources": [],
                        "starts_at": starts_at.astimezone(timezone.utc).isoformat(),
                        "ends_at": ends_at.astimezone(timezone.utc).isoformat()}
        params = {"location_id": location.id, "provider_id": None,
                  "offering_id": offering.id if offering else None, "reservation_mode": mode,
                  "starts_at": starts_at, "ends_at": ends_at, "party_size": party_size, "capacity": None,
                  "exclude_booking_id": None}
        open_, reason = await BookingSlotService.is_open(session, business_id, params)
        free = await BookingAllocationService.free_resources(
            session, business_id=business_id, location_id=location.id, resource_type=None, starts_at=starts_at,
            ends_at=ends_at, party_size=party_size, mode=mode,
            offering_id=offering.id if offering else None) if open_ else []
        return {"available": open_, "reason": reason,
                "starts_at": starts_at.astimezone(timezone.utc).isoformat(),
                "ends_at": ends_at.astimezone(timezone.utc).isoformat(),
                "resources": [{"resource_id": r["resource_id"], "name": r["name"],
                               "resource_type": r["resource_type"]} for r in free]}

    @staticmethod
    async def table_booking(session: AsyncSession, business_id: uuid.UUID) -> dict[str, Any] | None:
        """A restaurant takes table bookings when it has tables set up."""
        rows = list((await session.execute(select(BookingResource).where(
            BookingResource.business_id == business_id, BookingResource.deleted_at.is_(None),
            BookingResource.is_active.is_(True), BookingResource.resource_type == "table"))).scalars())
        if not rows:
            return None
        biggest = max((r.max_party_size or r.capacity or 1) for r in rows)
        return {"tables": len(rows), "max_party": int(biggest)}


def parse_day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError("Dates look like 2026-10-05", details={"field": "date"}) from exc

