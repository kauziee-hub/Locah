"""Waitlist for full slots (Founder refinement — Bookings §9, §16, §20).

A waitlist entry is a request, never a booking. When a place opens up (a
booking cancelled, moved away, released unpaid, or a no-show before it
started) the first person waiting is offered it - one offer at a time per
slot - on WhatsApp through Messaging, with a link. Nobody is booked silently:
the place becomes theirs only when they take the offer, through the same
booking path and its capacity checks. An offer runs out after the owner's
offer time and goes to the next person.

The business switches the waitlist on (bookings_policies.waitlist_enabled).
A guest may join only when the slot is genuinely full.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, PlatformError, ResourceNotFound, ValidationError
from platform_core.business_types import DEFAULT_TIMEZONE
from platform_core.models import Booking, BookingWaitlistEntry, Business, BusinessLocation
from platform_core.services.audit import AuditService
from platform_core.services.availability import AvailabilityService
from platform_core.services.booking import BookingService
from platform_core.services.booking_allocation import BookingAllocationService
from platform_core.services.outbox import OutboxService
from platform_core.validation.booking import validate_availability_query

OPEN = ("waiting", "offered")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BookingWaitlistService:
    @staticmethod
    def serialize(entry: BookingWaitlistEntry, *, with_link: str | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": str(entry.id),
            "location_id": str(entry.location_id),
            "offering_id": str(entry.offering_id) if entry.offering_id else None,
            "provider_id": str(entry.provider_id) if entry.provider_id else None,
            "reservation_mode": entry.reservation_mode,
            "starts_at": entry.starts_at.isoformat(),
            "ends_at": entry.ends_at.isoformat(),
            "party_size": entry.party_size,
            "customer_contact_id": str(entry.customer_contact_id),
            "channel": entry.channel,
            "status": entry.status,
            "offered_at": entry.offered_at.isoformat() if entry.offered_at else None,
            "offer_expires_at": entry.offer_expires_at.isoformat() if entry.offer_expires_at else None,
            "booking_id": str(entry.booking_id) if entry.booking_id else None,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        if with_link:
            data["offer_link"] = with_link
        return data

    @staticmethod
    def offer_link(business: Business, entry: BookingWaitlistEntry) -> str | None:
        from platform_core.site_urls import business_site_url

        if entry.status != "offered" or not entry.claim_token:
            return None
        return str(business_site_url(business.slug, f"/waitlist/{entry.id}?t={entry.claim_token}"))

    # ------------------------------------------------------------------ join
    @staticmethod
    async def slot_is_full(session: AsyncSession, business_id: uuid.UUID, params: dict[str, Any]) -> bool:
        """The same answer the booking path would give: no free capacity or
        provider, or resources configured and none free."""
        result = await AvailabilityService.check_availability(session, business_id=business_id, params=params)
        if not result["available"]:
            return True
        if await BookingAllocationService.has_resources(
            session, business_id=business_id, location_id=params["location_id"], mode=params["reservation_mode"]
        ):
            free = await BookingAllocationService.free_resources(
                session, business_id=business_id, location_id=params["location_id"], resource_type=None,
                starts_at=params["starts_at"], ends_at=params["ends_at"], party_size=params["party_size"],
                mode=params["reservation_mode"], offering_id=params.get("offering_id"),
            )
            return not free
        return False

    @staticmethod
    async def join(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        customer_contact_id: uuid.UUID,
        payload: dict[str, Any],
        actor_id: uuid.UUID,
        correlation_id: str,
        channel: str | None,
    ) -> BookingWaitlistEntry:
        policy = await BookingService.get_or_create_policy(session, business_id)
        if not policy.waitlist_enabled:
            raise ValidationError("This business does not keep a waitlist",
                                  details={"code": "waitlist_disabled"})
        params = validate_availability_query({**payload, "capacity": None, "exclude_booking_id": None})
        if params["starts_at"] <= _now():
            raise ValidationError("That time has already passed", details={"code": "slot_past"})
        if not await BookingWaitlistService.slot_is_full(session, business_id, params):
            raise ValidationError("There is a place free at that time - book it instead",
                                  details={"code": "slot_available"})
        row = (await session.execute(pg_insert(BookingWaitlistEntry).values(
            id=uuid.uuid4(), business_id=business_id, location_id=params["location_id"],
            offering_id=params["offering_id"], provider_id=params["provider_id"],
            reservation_mode=params["reservation_mode"], starts_at=params["starts_at"],
            ends_at=params["ends_at"], party_size=params["party_size"],
            customer_contact_id=customer_contact_id, channel=channel, status="waiting",
        ).on_conflict_do_nothing().returning(BookingWaitlistEntry.id))).first()
        if row is None:  # already waiting for this slot
            existing = (await session.execute(select(BookingWaitlistEntry).where(
                BookingWaitlistEntry.business_id == business_id,
                BookingWaitlistEntry.customer_contact_id == customer_contact_id,
                BookingWaitlistEntry.location_id == params["location_id"],
                BookingWaitlistEntry.reservation_mode == params["reservation_mode"],
                BookingWaitlistEntry.starts_at == params["starts_at"],
                BookingWaitlistEntry.status.in_(OPEN),
            ))).scalars().first()
            assert existing is not None
            return existing
        entry = await session.get(BookingWaitlistEntry, row[0])
        assert entry is not None
        await OutboxService.publish(session, event_type="booking.waitlist_joined", business_id=business_id,
                                    correlation_id=correlation_id,
                                    payload={"business_id": str(business_id), "entry_id": str(entry.id),
                                             "starts_at": entry.starts_at.isoformat()})
        await AuditService.record(session, event_type="booking.waitlist_joined", actor_identity_id=actor_id,
                                  actor_context="business", business_id=business_id,
                                  resource_type="booking_waitlist_entry", resource_id=entry.id,
                                  action="joined", after_state=BookingWaitlistService.serialize(entry))
        return entry

    # ------------------------------------------------------------------ a place opens
    @staticmethod
    async def place_opened(
        session: AsyncSession, business_id: uuid.UUID, *, location_id: uuid.UUID, reservation_mode: str,
        starts_at: datetime, ends_at: datetime, offering_id: uuid.UUID | None,
    ) -> BookingWaitlistEntry | None:
        """Queue an offer to the first person waiting for an overlapping slot -
        unless the slot has passed, the waitlist is off, or an offer for it is
        already out (one at a time). Returns the entry to be offered."""
        from platform_core.automation import AutomationEngine

        if starts_at <= _now():
            return None
        policy = await BookingService.get_or_create_policy(session, business_id)
        if not policy.waitlist_enabled:
            return None
        overlapping = [
            BookingWaitlistEntry.business_id == business_id,
            BookingWaitlistEntry.location_id == location_id,
            BookingWaitlistEntry.reservation_mode == reservation_mode,
            BookingWaitlistEntry.starts_at < ends_at,
            BookingWaitlistEntry.ends_at > starts_at,
        ]
        if offering_id is not None:
            overlapping.append((BookingWaitlistEntry.offering_id == offering_id)
                               | BookingWaitlistEntry.offering_id.is_(None))
        outstanding = (await session.execute(select(BookingWaitlistEntry.id).where(
            *overlapping, BookingWaitlistEntry.status == "offered").limit(1))).first()
        if outstanding is not None:
            return None
        first = (await session.execute(select(BookingWaitlistEntry).where(
            *overlapping, BookingWaitlistEntry.status == "waiting",
        ).order_by(BookingWaitlistEntry.created_at).limit(1))).scalars().first()
        if first is None:
            return None
        await AutomationEngine.schedule(session, business_id, ladder_key="booking.waitlist", entity_id=first.id,
                                        anchor=_now(), period_key=_now().isoformat(timespec="seconds"))
        return first

    @staticmethod
    async def offer(session: AsyncSession, entry: BookingWaitlistEntry) -> tuple[bool, str]:
        """Make the offer if the place is still free. (made?, owner words)."""
        from platform_core.automation import AutomationEngine
        from platform_core.services.messaging import MessagingService, NotSent

        if entry.status != "waiting":
            return False, f"No longer waiting ({entry.status})"
        if entry.starts_at <= _now():
            entry.status = "expired"
            await session.flush()
            return False, "The time has passed"
        params = validate_availability_query({
            "location_id": str(entry.location_id), "offering_id": str(entry.offering_id) if entry.offering_id else None,
            "provider_id": str(entry.provider_id) if entry.provider_id else None,
            "reservation_mode": entry.reservation_mode, "starts_at": entry.starts_at.isoformat(),
            "ends_at": entry.ends_at.isoformat(), "party_size": entry.party_size})
        if await BookingWaitlistService.slot_is_full(session, entry.business_id, params):
            return False, "The place was taken again before it could be offered"
        policy = await BookingService.get_or_create_policy(session, entry.business_id)
        now = _now()
        entry.status, entry.offered_at = "offered", now
        entry.offer_expires_at = min(now + timedelta(minutes=policy.waitlist_offer_minutes), entry.starts_at)
        entry.claim_token = secrets.token_urlsafe(24)
        entry.version += 1
        await session.flush()
        await OutboxService.publish(session, event_type="booking.waitlist_offered", business_id=entry.business_id,
                                    correlation_id=str(uuid.uuid4()),
                                    payload={"business_id": str(entry.business_id), "entry_id": str(entry.id),
                                             "offer_expires_at": entry.offer_expires_at.isoformat()})
        await AutomationEngine.schedule(session, entry.business_id, ladder_key="booking.waitlist_expiry",
                                        entity_id=entry.id, anchor=entry.offer_expires_at,
                                        period_key=now.isoformat(timespec="seconds"))
        business = await session.get(Business, entry.business_id)
        assert business is not None
        link = BookingWaitlistService.offer_link(business, entry) or ""
        from platform_core.models import CustomerContact, Offering

        contact = await session.get(CustomerContact, entry.customer_contact_id)
        offering = await session.get(Offering, entry.offering_id) if entry.offering_id else None
        what = offering.title if offering is not None else "your booking"
        minutes = int((entry.offer_expires_at - now).total_seconds() // 60)
        location = await session.get(BusinessLocation, entry.location_id)
        local = entry.starts_at.astimezone(ZoneInfo((location.timezone if location else None) or DEFAULT_TIMEZONE))
        when = local.strftime("%a %d %b, %I:%M %p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
        if contact is None or not contact.phone:
            return True, "Offered; no phone number - share the link from Bookings"
        try:
            msg = await MessagingService.send_template(
                session, entry.business_id, to=contact.phone, key="booking_waitlist_opening", contact_id=contact.id,
                params=[business.display_name, what, when, link, str(minutes)],
                idempotency_key=f"waitlist_offer:{entry.id}:{now.isoformat(timespec='seconds')}")
        except NotSent as exc:
            return True, f"Offered; not sent on WhatsApp ({exc}) - share the link from Bookings"
        if msg.status != "sent":
            return True, f"Offered; WhatsApp did not send it ({msg.error or msg.status}) - share the link"
        return True, "Offered on WhatsApp"

    @staticmethod
    async def expire(session: AsyncSession, entry: BookingWaitlistEntry, period_key: str) -> tuple[bool, str]:
        if entry.status != "offered" or entry.offered_at is None:
            return False, f"Nothing to withdraw ({entry.status})"
        if entry.offered_at.isoformat(timespec="seconds") != period_key:
            return False, "A later offer replaced this one"
        entry.status, entry.claim_token = "expired", None
        entry.version += 1
        await session.flush()
        await OutboxService.publish(session, event_type="booking.waitlist_expired", business_id=entry.business_id,
                                    correlation_id=str(uuid.uuid4()),
                                    payload={"business_id": str(entry.business_id), "entry_id": str(entry.id)})
        nxt = await BookingWaitlistService.place_opened(
            session, entry.business_id, location_id=entry.location_id, reservation_mode=entry.reservation_mode,
            starts_at=entry.starts_at, ends_at=entry.ends_at, offering_id=entry.offering_id)
        return True, "Offer ran out" + ("; offered to the next person" if nxt else "")

    # ------------------------------------------------------------------ take the offer
    @staticmethod
    async def resolve_offer(session: AsyncSession, business_id: uuid.UUID, entry_id: uuid.UUID,
                            token: str) -> BookingWaitlistEntry:
        entry = (await session.execute(select(BookingWaitlistEntry).where(
            BookingWaitlistEntry.id == entry_id, BookingWaitlistEntry.business_id == business_id,
        ))).scalars().first()
        if entry is None or not entry.claim_token or not secrets.compare_digest(entry.claim_token, token or ""):
            raise ResourceNotFound("Offer")
        return entry

    @staticmethod
    async def claim(
        session: AsyncSession, *, business: Business, entry_id: uuid.UUID, token: str, correlation_id: str,
    ) -> Booking:
        entry = await BookingWaitlistService.resolve_offer(session, business.id, entry_id, token)
        if entry.status == "booked" and entry.booking_id:
            booking = await session.get(Booking, entry.booking_id)
            assert booking is not None
            return booking
        if entry.status != "offered" or entry.offer_expires_at is None or entry.offer_expires_at <= _now():
            raise ConflictError("This offer has run out", details={"code": "offer_expired"})
        from platform_core.automation import AutomationEngine

        try:
            booking = await BookingService.create_booking(
                session, business_id=business.id, actor_id=business.primary_owner_identity_id,
                correlation_id=correlation_id,
                payload={"location_id": str(entry.location_id), "customer_contact_id": str(entry.customer_contact_id),
                         "offering_id": str(entry.offering_id) if entry.offering_id else None,
                         "provider_id": str(entry.provider_id) if entry.provider_id else None,
                         "reservation_mode": entry.reservation_mode, "starts_at": entry.starts_at.isoformat(),
                         "ends_at": entry.ends_at.isoformat(), "party_size": entry.party_size,
                         "channel": entry.channel if entry.channel in ("web", "whatsapp") else "web",
                         "payment_method": "pay_at_business", "idempotency_key": f"waitlist-{entry.id}"},
                allow_capacity_override=False, assign_free_resource=True)
        except PlatformError as exc:
            if isinstance(exc, ConflictError):
                raise ConflictError("Sorry - that place has just been taken",
                                    details={"code": "slot_conflict"}) from exc
            raise
        entry.status, entry.booking_id, entry.claim_token = "booked", booking.id, None
        entry.version += 1
        await session.flush()
        await AutomationEngine.cancel(session, business.id, ladder_key="booking.waitlist_expiry", entity_id=entry.id,
                                      reason="The customer took the place")
        await OutboxService.publish(session, event_type="booking.waitlist_claimed", business_id=business.id,
                                    correlation_id=correlation_id,
                                    payload={"business_id": str(business.id), "entry_id": str(entry.id),
                                             "booking_id": str(booking.id)})
        return booking

    # ------------------------------------------------------------------ staff
    @staticmethod
    async def list_entries(session: AsyncSession, business_id: uuid.UUID,
                           status: str | None = None) -> list[BookingWaitlistEntry]:
        q = select(BookingWaitlistEntry).where(BookingWaitlistEntry.business_id == business_id)
        q = q.where(BookingWaitlistEntry.status == status) if status else q.where(
            BookingWaitlistEntry.status.in_(OPEN))
        return list((await session.execute(q.order_by(BookingWaitlistEntry.starts_at,
                                                      BookingWaitlistEntry.created_at))).scalars().all())

    @staticmethod
    async def withdraw(session: AsyncSession, business_id: uuid.UUID, entry_id: uuid.UUID,
                       actor_id: uuid.UUID) -> BookingWaitlistEntry:
        entry = (await session.execute(select(BookingWaitlistEntry).where(
            BookingWaitlistEntry.id == entry_id, BookingWaitlistEntry.business_id == business_id,
        ).with_for_update())).scalars().first()
        if entry is None:
            raise ResourceNotFound("Waitlist entry")
        if entry.status not in OPEN:
            raise ConflictError(f"This request is already {entry.status}")
        was_offered = entry.status == "offered"
        entry.status, entry.claim_token = "withdrawn", None
        entry.version += 1
        await session.flush()
        await AuditService.record(session, event_type="booking.waitlist_withdrawn", actor_identity_id=actor_id,
                                  actor_context="business", business_id=business_id,
                                  resource_type="booking_waitlist_entry", resource_id=entry.id, action="withdrawn")
        if was_offered:
            await BookingWaitlistService.place_opened(
                session, business_id, location_id=entry.location_id, reservation_mode=entry.reservation_mode,
                starts_at=entry.starts_at, ends_at=entry.ends_at, offering_id=entry.offering_id)
        return entry
