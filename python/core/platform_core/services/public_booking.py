"""Public consumer booking orchestration (WEB-009 / WEB-010).

Doc 11 §4.1 WEB-009/WEB-010 · Doc 09 required states · Stage 5 only.
My Activity UI is Stage 7 (Doc 11 §17.7) — not built here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.context_resolver import bind_booking_management_token, bind_public_context
from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.models import (
    Booking,
    Business,
    Offering,
    WorkforceLocationAssignment,
    WorkforceMember,
    WorkforceServiceAssociation,
)
from platform_core.resolvers.booking_resolver import BookingResolver
from platform_core.services.availability import AvailabilityService
from platform_core.services.booking import BookingService
from platform_core.services.booking_lifecycle import BookingLifecycleService
from platform_core.services.business import BusinessService
from platform_core.services.customer import CustomerService
from platform_core.services.location import LocationService
from platform_core.services.booking_allocation import BookingAllocationService
from platform_core.validation.booking import validate_availability_query

class PublicBookingService:
    @staticmethod
    async def _resolve_business(session: AsyncSession, slug: str) -> Business:
        business = await BusinessService.get_by_slug(session, slug)
        if business is None or business.deleted_at is not None:
            raise ResourceNotFound("Business")
        await bind_public_context(session, business.id)
        return business

    @staticmethod
    async def _bookings_active(session: AsyncSession, business_id: uuid.UUID) -> bool:
        """Public booking is a customer action: Bookings must be *ready* — switched
        on, entitled and with something real to book — the same answer that
        decides whether the website offers "Book" at all (module_readiness)."""
        from platform_core.services.module_readiness import module_ready

        return bool(await module_ready(session, business_id, "bookings"))

    @staticmethod
    async def _require_bookings(session: AsyncSession, business_id: uuid.UUID) -> None:
        if not await PublicBookingService._bookings_active(session, business_id):
            raise ValidationError("Bookings are not enabled for this Business", details={"code": "bookings_disabled"})

    @staticmethod
    async def _public_offering(session: AsyncSession, business: Business, offering_id: Any) -> Offering:
        """An offering a visitor may book: this business's, live and public. An
        archived, draft or private one is not found — never bookable by its id."""
        offering = await session.get(Offering, uuid.UUID(str(offering_id)))
        if (offering is None or offering.business_id != business.id or offering.deleted_at is not None
                or offering.status != "active" or offering.visibility != "public"):
            raise ResourceNotFound("Offering")
        return offering

    @staticmethod
    async def booking_options(session: AsyncSession, *, slug: str) -> dict[str, Any]:
        business = await PublicBookingService._resolve_business(session, slug)
        if not await PublicBookingService._bookings_active(session, business.id):
            raise ValidationError(
                "Bookings are not enabled for this Business",
                details={"code": "bookings_disabled"},
            )
        locations = await LocationService.list_for_business(session, business.id, status="active")
        offerings = (
            (
                await session.execute(
                    select(Offering)
                    .where(
                        Offering.business_id == business.id,
                        Offering.deleted_at.is_(None),
                        Offering.status == "active",
                        Offering.visibility == "public",
                        Offering.offering_type.in_(("service", "experience", "class_session", "accommodation",
                                                    "rental", "property_project", "property_unit")),
                    )
                    .order_by(Offering.title.asc())
                )
            )
            .scalars()
            .all()
        )
        members = (
            (
                await session.execute(
                    select(WorkforceMember)
                    .where(
                        WorkforceMember.business_id == business.id,
                        WorkforceMember.deleted_at.is_(None),
                        WorkforceMember.status == "active",
                    )
                    .order_by(WorkforceMember.display_name.asc())
                )
            )
            .scalars()
            .all()
        )
        assignments = (
            (
                await session.execute(
                    select(WorkforceLocationAssignment).where(
                        WorkforceLocationAssignment.business_id == business.id
                    )
                )
            )
            .scalars()
            .all()
        )
        associations = (
            (
                await session.execute(
                    select(WorkforceServiceAssociation).where(
                        WorkforceServiceAssociation.business_id == business.id
                    )
                )
            )
            .scalars()
            .all()
        )
        loc_map: dict[str, list[str]] = {}
        for a in assignments:
            loc_map.setdefault(str(a.member_id), []).append(str(a.location_id))
        svc_map: dict[str, list[str]] = {}
        for a in associations:
            svc_map.setdefault(str(a.member_id), []).append(str(a.offering_id))
        policy = await BookingService.get_or_create_policy(session, business.id)
        from platform_core.services.booking_slots import BookingSlotService, minutes_for, mode_for

        def attr(o: Offering, key: str) -> Any:
            return (o.attributes or {}).get(key)

        return {
            "table": await BookingSlotService.table_booking(session, business.id),
            "offerings": [
                {"id": str(o.id), "title": o.title, "description": o.description, "offering_type": o.offering_type,
                 "mode": mode_for(o), "minutes": minutes_for(o, mode_for(o)),
                 "price_amount": float(o.price_amount) if o.price_amount is not None else None,
                 "currency": o.currency, "capacity": attr(o, "capacity"), "max_guests": attr(o, "max_guests")}
                for o in offerings
            ],
            "business": {
                "id": str(business.id),
                "slug": business.slug,
                "display_name": business.display_name,
            },
            "locations": [
                {
                    "id": str(loc.id),
                    "name": loc.name,
                    "is_primary": loc.is_primary,
                    "status": loc.status,
                    "address": loc.address,
                    "timezone": loc.timezone,
                    "hours_known": bool(loc.hours),
                }
                for loc in locations
            ],
            "services": [
                {
                    "id": str(o.id),
                    "title": o.title,
                    "description": o.description,
                    "offering_type": o.offering_type,
                    "price_amount": float(o.price_amount) if o.price_amount is not None else None,
                    "currency": o.currency,
                }
                for o in offerings
            ],
            "providers": [
                {
                    "id": str(m.id),
                    "display_name": m.display_name,
                    "designation": m.designation,
                    "location_ids": loc_map.get(str(m.id), []),
                    "offering_ids": svc_map.get(str(m.id), []),
                }
                for m in members
            ],
            "policy": {
                "require_deposit": policy.require_deposit,
                "deposit_amount": float(policy.deposit_amount)
                if policy.deposit_amount is not None
                else None,
                "deposit_percent": float(policy.deposit_percent)
                if policy.deposit_percent is not None
                else None,
                "cancel_window_hours": policy.cancel_window_hours,
                "waitlist_enabled": policy.waitlist_enabled,
            },
            "payment_methods": ["cod", "pay_at_business"],
        }

    @staticmethod
    async def check_availability(
        session: AsyncSession, *, slug: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        business = await PublicBookingService._resolve_business(session, slug)
        await PublicBookingService._require_bookings(session, business.id)
        params = validate_availability_query(payload)
        location = await LocationService.get_by_id(session, business.id, params["location_id"])
        if location is None or location.status != "active":
            return {
                "available": False,
                "reason": "Location is closed or inactive",
                "code": "location_closed",
            }
        closed = AvailabilityService.closed_reason(
            location, params["reservation_mode"], params["starts_at"], params["ends_at"]
        )
        if closed:
            return {"available": False, "reason": closed, "code": "closed", "resources": []}
        result = await AvailabilityService.check_availability(
            session, business_id=business.id, params=params
        )
        if not result["available"]:
            result["code"] = "slot_conflict"

        # Which specific resources a guest could pick. Same service the staff
        # endpoint and booking creation use, so a table offered here is one the
        # allocator will accept. Only the fields a guest may see - capacity and
        # remaining are the business's operational detail, not the public's.
        free = await BookingAllocationService.free_resources(
            session,
            business_id=business.id,
            location_id=params["location_id"],
            resource_type=None,
            starts_at=params["starts_at"],
            ends_at=params["ends_at"],
            party_size=params["party_size"],
            exclude_booking_id=params.get("exclude_booking_id"),
            mode=params["reservation_mode"],
        )
        result["resources"] = [
            {
                "resource_id": r["resource_id"],
                "name": r["name"],
                "resource_type": r["resource_type"],
            }
            for r in free
        ]
        # If the business allocates resources and none is free, the slot is not
        # available however the legacy check read it - that check only knows
        # about providers and the offering-level pool.
        if result["available"] and not free:
            if await BookingAllocationService.has_resources(
                session, business_id=business.id, location_id=params["location_id"],
                mode=params["reservation_mode"],
            ):
                result["available"] = False
                result["code"] = "slot_conflict"
                result["reason"] = "No resource is free for this time"
        return dict(result)

    @staticmethod
    async def _guest_contact(
        session: AsyncSession, business: Business, payload: dict[str, Any], *,
        identity_id: uuid.UUID | None, correlation_id: str,
    ) -> Any:
        guest = payload.get("guest") or {}
        display_name = str(guest.get("name") or "").strip()
        email = str(guest.get("email") or "").strip().lower()
        phone = (str(guest.get("phone")).strip() if guest.get("phone") else None) or None
        if identity_id is None and (not display_name or not email):
            raise ValidationError(
                "Guest name and email are required",
                details={"field": "guest", "code": "policy_restriction"},
            )

        # Doc 05 Part 7.1: a guest booking is bounded to the transaction and
        # never becomes a Platform Identity. Customer attribution is the
        # business-scoped CustomerContact; audit/actor attribution is the
        # storefront owner acting in a guest-checkout context.
        actor_id = business.primary_owner_identity_id
        if identity_id is not None:
            from platform_core.services.customer_account import CustomerAccountService

            return await CustomerAccountService.contact_for_identity(
                session, business_id=business.id, identity_id=identity_id, display_name=display_name,
                phone=phone, actor_id=actor_id, correlation_id=correlation_id)
        return await CustomerService.find_or_create_contact(
            session,
            business_id=business.id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            actor_context="guest_checkout",
            display_name=display_name,
            email=email,
            phone=phone,
        )

    @staticmethod
    async def join_waitlist(
        session: AsyncSession, *, slug: str, correlation_id: str, payload: dict[str, Any],
        identity_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """A guest asks to be told if a full slot opens up (only when it is full)."""
        from platform_core.services.booking_waitlist import BookingWaitlistService

        business = await PublicBookingService._resolve_business(session, slug)
        if not await PublicBookingService._bookings_active(session, business.id):
            raise ValidationError("Bookings are not enabled for this Business", details={"code": "bookings_disabled"})
        contact = await PublicBookingService._guest_contact(
            session, business, payload, identity_id=identity_id, correlation_id=correlation_id)
        entry = await BookingWaitlistService.join(
            session, business_id=business.id, customer_contact_id=contact.id,
            payload={k: v for k, v in payload.items() if k != "guest"},
            actor_id=business.primary_owner_identity_id, correlation_id=correlation_id, channel="web")
        data: dict[str, Any] = dict(BookingWaitlistService.serialize(entry))
        data.pop("customer_contact_id", None)
        return data

    @staticmethod
    async def waitlist_offer(
        session: AsyncSession, *, slug: str, entry_id: uuid.UUID, token: str
    ) -> dict[str, Any]:
        """What the offer link shows: the slot, and whether it can still be taken."""
        from platform_core.services.booking_waitlist import BookingWaitlistService

        business = await PublicBookingService._resolve_business(session, slug)
        entry = await BookingWaitlistService.resolve_offer(session, business.id, entry_id, token)
        offering = await session.get(Offering, entry.offering_id) if entry.offering_id else None
        now = datetime.now(timezone.utc)
        return {
            "business": {"display_name": business.display_name, "slug": business.slug},
            "title": offering.title if offering is not None else "Booking",
            "starts_at": entry.starts_at.isoformat(), "ends_at": entry.ends_at.isoformat(),
            "party_size": entry.party_size, "status": entry.status,
            "offer_expires_at": entry.offer_expires_at.isoformat() if entry.offer_expires_at else None,
            "can_take": entry.status == "offered" and entry.offer_expires_at is not None
            and entry.offer_expires_at > now,
        }

    @staticmethod
    async def claim_waitlist(
        session: AsyncSession, *, slug: str, entry_id: uuid.UUID, token: str, correlation_id: str
    ) -> dict[str, Any]:
        from platform_core.services.booking_waitlist import BookingWaitlistService

        business = await PublicBookingService._resolve_business(session, slug)
        booking = await BookingWaitlistService.claim(
            session, business=business, entry_id=entry_id, token=token, correlation_id=correlation_id)
        data = BookingResolver.serialize_booking(booking)
        data["management_token"] = booking.management_token
        return dict(data)

    @staticmethod
    async def _mode_and_window(
        session: AsyncSession, business: Business, location: Any, payload: dict[str, Any]
    ) -> tuple[str, str, str]:
        """The offering decides the mode, not the request: a class booked as an
        'appointment' would otherwise skip its places limit. An event date is
        the whole local day, whatever times were sent."""
        from platform_core.services.booking_slots import day_window, mode_for, zone
        from platform_core.validation.booking import parse_datetime

        mode = str(payload.get("reservation_mode") or "appointment")
        if payload.get("offering_id"):
            offering = await PublicBookingService._public_offering(session, business, payload["offering_id"])
            mode = mode_for(offering)
        elif mode not in ("table", "appointment", "accommodation", "rental", "event_date"):
            mode = "appointment"  # a class or site visit is always booked against its offering
        starts, ends = str(payload["starts_at"]), str(payload["ends_at"])
        if mode == "event_date":
            first = parse_datetime(starts, field="starts_at").astimezone(zone(location)).date()
            a, b = day_window(location, first)
            starts, ends = a.isoformat(), b.isoformat()
        return mode, starts, ends

    @staticmethod
    async def slots(session: AsyncSession, *, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Times a customer can pick on one day (appointment, table, class, site visit)."""
        from platform_core.services.booking_slots import BookingSlotService, mode_for, parse_day

        business = await PublicBookingService._resolve_business(session, slug)
        await PublicBookingService._require_bookings(session, business.id)
        location = await LocationService.get_by_id(session, business.id, uuid.UUID(str(payload["location_id"])))
        if location is None or location.status != "active":
            raise ValidationError("Location is closed or inactive", details={"code": "location_closed"})
        offering = None
        mode = str(payload.get("mode") or "appointment")
        if payload.get("offering_id"):
            offering = await PublicBookingService._public_offering(session, business, payload["offering_id"])
            mode = mode_for(offering)
        provider = uuid.UUID(str(payload["provider_id"])) if payload.get("provider_id") else None
        return dict(await BookingSlotService.day_slots(
            session, business_id=business.id, location=location, mode=mode, offering=offering,
            provider_id=provider, party_size=max(int(payload.get("party_size") or 1), 1),
            day=parse_day(payload.get("date"))))

    @staticmethod
    async def range_check(session: AsyncSession, *, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Stay (check-in/check-out dates), rental (start/end) or event date (a day)."""
        from platform_core.services.booking_slots import (
            BookingSlotService, day_window, mode_for, parse_day, stay_window,
        )
        from platform_core.validation.booking import parse_datetime

        business = await PublicBookingService._resolve_business(session, slug)
        await PublicBookingService._require_bookings(session, business.id)
        location = await LocationService.get_by_id(session, business.id, uuid.UUID(str(payload["location_id"])))
        if location is None or location.status != "active":
            raise ValidationError("Location is closed or inactive", details={"code": "location_closed"})
        offering = None
        mode = str(payload.get("mode") or "rental")
        if payload.get("offering_id"):
            offering = await PublicBookingService._public_offering(session, business, payload["offering_id"])
            mode = mode_for(offering)
        if mode == "accommodation":
            starts, ends = stay_window(location, offering, parse_day(payload.get("check_in")),
                                       parse_day(payload.get("check_out")))
        elif mode == "event_date":
            starts, ends = day_window(location, parse_day(payload.get("date")))
        elif mode == "rental":
            starts = parse_datetime(payload.get("starts_at"), field="starts_at")
            ends = parse_datetime(payload.get("ends_at"), field="ends_at")
        else:
            raise ValidationError("This kind of booking is picked by time slots", details={"field": "mode"})
        return dict(await BookingSlotService.range_check(
            session, business_id=business.id, location=location, mode=mode, offering=offering,
            party_size=max(int(payload.get("party_size") or 1), 1), starts_at=starts, ends_at=ends))

    @staticmethod
    async def create_public_booking(
        session: AsyncSession,
        *,
        slug: str,
        correlation_id: str,
        payload: dict[str, Any],
        identity_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        business = await PublicBookingService._resolve_business(session, slug)
        if not await PublicBookingService._bookings_active(session, business.id):
            raise ValidationError(
                "Bookings are not enabled for this Business",
                details={"code": "bookings_disabled"},
            )
        location_id = uuid.UUID(str(payload["location_id"]))
        location = await LocationService.get_by_id(session, business.id, location_id)
        if location is None or location.status != "active":
            raise ValidationError(
                "Location is closed or inactive",
                details={"code": "location_closed", "field": "location_id"},
            )

        contact = await PublicBookingService._guest_contact(
            session, business, payload, identity_id=identity_id, correlation_id=correlation_id)
        actor_id = business.primary_owner_identity_id
        mode, starts_at, ends_at = await PublicBookingService._mode_and_window(session, business, location, payload)

        booking = await BookingService.create_booking(
            session,
            business_id=business.id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            payload={
                "location_id": str(location_id),
                "customer_contact_id": str(contact.id),
                "offering_id": payload.get("offering_id"),
                "provider_id": payload.get("provider_id"),
                "reservation_mode": mode,
                "title": payload.get("title"),
                "starts_at": starts_at,
                "ends_at": ends_at,
                "party_size": payload.get("party_size") or 1,
                "guest_count": payload.get("guest_count"),
                # Deliberately not payload.get("capacity"). Capacity is the
                # limit availability is checked against; taking it from an
                # anonymous request made the check decorative.
                "resource_ids": payload.get("resource_ids"),
                "payment_method": payload.get("payment_method") or "cod",
                "idempotency_key": payload.get("idempotency_key"),
            },
            allow_capacity_override=False,
            assign_free_resource=True,
            enforce_opening_hours=True,
        )
        note = str(payload.get("notes") or "").strip()
        if note:
            from platform_core.services.booking_note import BookingNoteService

            await BookingNoteService.create_note(
                session, business_id=business.id, booking_id=booking.id, actor_id=actor_id,
                correlation_id=correlation_id, body=f"From the customer: {note[:1000]}")
        data = BookingResolver.serialize_booking(booking)
        data["management_token"] = booking.management_token
        data["management_token_expires_at"] = (
            booking.management_token_expires_at.isoformat()
            if booking.management_token_expires_at
            else None
        )
        return dict(data)

    @staticmethod
    async def _resolve_by_token(
        session: AsyncSession, *, booking_id: uuid.UUID, token: str
    ) -> Booking:
        # The token is the credential, and RLS needs it bound before the row it
        # points at becomes visible — there is no business context yet to bind,
        # because the token is what determines the tenant.
        await bind_booking_management_token(session, token)
        booking = (
            (
                await session.execute(
                    select(Booking).where(
                        Booking.id == booking_id,
                        Booking.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if booking is None:
            raise ResourceNotFound("Booking")
        if not booking.management_token or booking.management_token != token:
            raise ResourceNotFound("Booking")
        if (
            booking.management_token_expires_at is not None
            and booking.management_token_expires_at < datetime.now(timezone.utc)
        ):
            raise ValidationError(
                "Management link has expired",
                details={"code": "expired_link"},
            )
        # Now that the tenant is known, bind it so everything the caller reads or
        # writes next (policy, customer contact, the update itself) passes its
        # own policies the ordinary way.
        await bind_public_context(session, booking.business_id)
        return booking

    @staticmethod
    async def get_by_token(
        session: AsyncSession, *, booking_id: uuid.UUID, token: str
    ) -> dict[str, Any]:
        booking = await PublicBookingService._resolve_by_token(
            session, booking_id=booking_id, token=token
        )
        data = BookingResolver.serialize_booking(booking)
        data["contact"] = {
            "business_id": str(booking.business_id),
            "location_id": str(booking.location_id),
        }
        return dict(data)

    @staticmethod
    async def cancel_by_token(
        session: AsyncSession,
        *,
        booking_id: uuid.UUID,
        token: str,
        reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        booking = await PublicBookingService._resolve_by_token(
            session, booking_id=booking_id, token=token
        )
        policy = await BookingService.get_or_create_policy(session, booking.business_id)
        deadline = booking.starts_at - timedelta(hours=policy.cancel_window_hours)
        if datetime.now(timezone.utc) > deadline:
            raise ValidationError(
                "Cancellation window has closed",
                details={"code": "cancellation_window_closed"},
            )
        business = await BusinessService.get_by_id(session, booking.business_id)
        guest_actor = booking.cancelled_by or business.primary_owner_identity_id
        # Prefer linked customer identity for audit when present
        if booking.customer_contact_id:
            from platform_core.models import CustomerContact

            contact = (
                (
                    await session.execute(
                        select(CustomerContact).where(
                            CustomerContact.id == booking.customer_contact_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if contact and contact.identity_id:
                guest_actor = contact.identity_id
        updated = await BookingLifecycleService.transition_status(
            session,
            business_id=booking.business_id,
            booking_id=booking.id,
            actor_id=guest_actor,
            correlation_id=correlation_id,
            payload={"status": "cancelled", "reason": reason or "Customer cancelled"},
        )
        return dict(BookingResolver.serialize_booking(updated))

    @staticmethod
    async def reschedule_by_token(
        session: AsyncSession,
        *,
        booking_id: uuid.UUID,
        token: str,
        starts_at: str,
        ends_at: str,
        correlation_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        booking = await PublicBookingService._resolve_by_token(
            session, booking_id=booking_id, token=token
        )
        policy = await BookingService.get_or_create_policy(session, booking.business_id)
        deadline = booking.starts_at - timedelta(hours=policy.cancel_window_hours)
        if datetime.now(timezone.utc) > deadline:
            raise ValidationError(
                "Reschedule window has closed",
                details={"code": "cancellation_window_closed"},
            )
        business = await BusinessService.get_by_id(session, booking.business_id)
        actor_id = business.primary_owner_identity_id
        if booking.customer_contact_id:
            from platform_core.models import CustomerContact

            contact = (
                (
                    await session.execute(
                        select(CustomerContact).where(
                            CustomerContact.id == booking.customer_contact_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if contact and contact.identity_id:
                actor_id = contact.identity_id
        updated = await BookingLifecycleService.reschedule(
            session,
            business_id=booking.business_id,
            booking_id=booking.id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            payload={"starts_at": starts_at, "ends_at": ends_at, "reason": reason},
            enforce_opening_hours=True,
        )
        return dict(BookingResolver.serialize_booking(updated))
