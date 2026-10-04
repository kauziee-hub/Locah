"""Booking domain service (Stage 7 kernel + Stage 5 provider/deposit completion)."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ValidationError
from platform_core.gates import assert_business_accepts_commerce, assert_business_mutable
from platform_core.models import Booking, BookingStatusHistory, BookingsPolicy
from platform_core.resolvers.customer_resolver import CustomerResolver
from platform_core.resolvers.location_resolver import LocationResolver
from platform_core.resolvers.offering_resolver import OfferingResolver
from platform_core.resolvers.booking_resolver import BookingResolver
from platform_core.services.audit import AuditService
from platform_core.services.availability import AvailabilityService
from platform_core.services.booking_allocation import BookingAllocationService
from platform_core.services.business import BusinessService
from platform_core.services.consumer_activity import ConsumerActivityService
from platform_core.services.customer_timeline import CustomerTimelineService
from platform_core.services.outbox import OutboxService
from platform_core.services.payment_attempt import PaymentAttemptService
from platform_core.validation.booking import (
    RESERVABLE_OFFERING_TYPES,
    validate_create_payload,
    validate_patch_payload,
)


class BookingService:
    @staticmethod
    def serialize(booking: Booking) -> dict[str, Any]:
        return cast(dict[str, Any], BookingResolver.serialize_booking(booking))

    @staticmethod
    async def describe(session: AsyncSession, business_id: uuid.UUID,
                       bookings: list[Booking]) -> list[dict[str, Any]]:
        """Bookings as the Workspace shows them: who it is for (with a number to
        call), where, and with whom — through the customer and workforce
        modules' public batch reads, never per row."""
        from platform_core.models import BusinessLocation
        from platform_core.services.workforce import WorkforceService

        people = await CustomerResolver.summaries(
            session, business_id=business_id,
            contact_ids={b.customer_contact_id for b in bookings if b.customer_contact_id})
        places = {loc.id: loc.name for loc in (await session.execute(select(BusinessLocation).where(
            BusinessLocation.business_id == business_id,
            BusinessLocation.id.in_({b.location_id for b in bookings})))).scalars().all()} if bookings else {}
        staff = await WorkforceService.names(
            session, business_id=business_id, member_ids={b.provider_id for b in bookings if b.provider_id})
        return [BookingService.serialize(b) | {
            "customer": people.get(b.customer_contact_id) if b.customer_contact_id else None,
            "location_name": places.get(b.location_id),
            "provider_name": staff.get(b.provider_id) if b.provider_id else None,
        } for b in bookings]

    @staticmethod
    def _generate_booking_number() -> str:
        return f"BKG-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    async def list_for_business(
        session: AsyncSession,
        business_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        customer_contact_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        provider_id: uuid.UUID | None = None,
    ) -> list[Booking]:
        query = select(Booking).where(
            Booking.business_id == business_id,
            Booking.deleted_at.is_(None),
        )
        if status:
            query = query.where(Booking.status == status)
        if customer_contact_id:
            query = query.where(Booking.customer_contact_id == customer_contact_id)
        if location_id:
            query = query.where(Booking.location_id == location_id)
        if provider_id:
            query = query.where(Booking.provider_id == provider_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Booking.booking_number.ilike(pattern),
                    Booking.title.ilike(pattern),
                    Booking.internal_reference.ilike(pattern),
                )
            )
        query = query.order_by(Booking.starts_at.desc())
        return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def create_booking(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        allow_capacity_override: bool = True,
        assign_free_resource: bool = False,
        enforce_opening_hours: bool = False,
    ) -> Booking:
        """Create a booking and claim whatever it consumes.

        `allow_capacity_override` is False on the public path. Capacity is the
        limit availability is checked against, so letting an anonymous caller
        supply it makes the check decorative. Staff may still set it for a
        business that has configured no resources, where nothing else knows the
        number; once resources exist, or the class states its places, those win
        regardless.

        `assign_free_resource` is True where the customer is never asked which
        table or chair (website, WhatsApp): if the business allocates resources
        and none was named, a free one is held under lock, or the booking is
        refused - the check and the claim commit together.

        `enforce_opening_hours` holds guest bookings to the location's saved
        opening hours; the desk may still book outside them.
        """
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="create booking")
        # Doc 04 §6.1: a suspended Business cannot receive orders. Standing
        # (`status`) is a separate axis from lifecycle (`state`) — both apply.
        assert_business_accepts_commerce(business.status, action="create booking")
        validated = validate_create_payload(payload)

        if validated["idempotency_key"]:
            existing = await session.execute(
                select(Booking).where(
                    Booking.business_id == business_id,
                    Booking.idempotency_key == validated["idempotency_key"],
                    Booking.deleted_at.is_(None),
                )
            )
            found = existing.scalars().first()
            if found:
                return found

        await LocationResolver.resolve(
            session, business_id=business_id, location_id=validated["location_id"]
        )
        if validated["customer_contact_id"]:
            await CustomerResolver.resolve(
                session,
                business_id=business_id,
                contact_id=validated["customer_contact_id"],
            )

        title = validated["title"]
        offering_price: float | None = None
        fixed_price: Decimal | None = None

        # Resource configuration is authoritative for capacity. The request may
        # say which resources to consume; it may not say how many places they
        # hold. Previously `capacity` came straight off the payload and was then
        # used as the limit to check against, so a caller could send a large one
        # and the check could never fail.
        resources = await BookingAllocationService.load_many(
            session,
            business_id=business_id,
            resource_ids=validated["resource_ids"],
        )
        if validated["offering_id"]:
            offering = await OfferingResolver.resolve(
                session,
                business_id=business_id,
                offering_id=validated["offering_id"],
            )
            if offering.status != "active":
                raise ValidationError(
                    "Offering is not active",
                    details={"offering_id": str(offering.id)},
                )
            if offering.offering_type not in RESERVABLE_OFFERING_TYPES:
                raise ValidationError(
                    "Offering type is not reservable",
                    details={"offering_type": offering.offering_type},
                )
            title = title or offering.title
            if offering.price_amount is not None:
                offering_price = float(offering.price_amount)
                if getattr(offering, "price_type", "fixed") == "fixed" and offering.offering_type in {
                        "service", "accommodation", "class_session", "rental"}:
                    fixed_price = Decimal(str(offering.price_amount))

            # Stage 6 membership gate (Doc 11 §17.6): if this class/session
            # offering is mapped to one or more membership plans, the customer
            # must hold an active enrolment in one of them. Offerings with no
            # mapping keep the Stage 5 capacity-only path unchanged.
            if validated["reservation_mode"] == "class_session":
                from platform_core.resolvers.membership_resolver import MembershipResolver

                gating_plan_ids = await MembershipResolver.offering_requires_membership(
                    session, business_id=business_id, offering_id=offering.id
                )
                if gating_plan_ids:
                    if not validated["customer_contact_id"]:
                        raise ValidationError(
                            "This class requires an active membership",
                            details={
                                "code": "membership_required",
                                "offering_id": str(offering.id),
                            },
                        )
                    # Memberships answers (P2-02): covered at the class time, and a
                    # session pack still has a session — Bookings keeps no count.
                    from platform_core.memberships.service import MembershipCore

                    entitled = await MembershipCore.booking_entitlement(
                        session, business_id, validated["customer_contact_id"], gating_plan_ids,
                        at=validated["starts_at"],
                    )
                    if entitled is None:
                        raise ValidationError(
                            "This class requires an active membership or a session pack with sessions left",
                            details={
                                "code": "membership_required",
                                "offering_id": str(offering.id),
                                "eligible_plan_ids": [str(p) for p in gating_plan_ids],
                            },
                        )

        if not title:
            raise ValidationError(
                "Booking title is required",
                details={"field": "title"},
            )

        configured = await AvailabilityService.configured_capacity(
            session,
            business_id=business_id,
            offering_id=validated["offering_id"],
            reservation_mode=validated["reservation_mode"],
        )
        capacity = BookingAllocationService.effective_capacity(
            resources,
            fallback=configured
            if configured is not None
            else (validated["capacity"] if allow_capacity_override else None),
        )

        # The legacy path stays for bookings that name no resource: a business
        # that has not configured any still gets provider exclusivity and the
        # offering-level pool it has always had. Where resources exist they are
        # the authority, and allocating them below is what enforces supply.
        if enforce_opening_hours:
            await AvailabilityService.assert_open(
                session,
                location_id=validated["location_id"],
                reservation_mode=validated["reservation_mode"],
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
            )
        if resources and validated["provider_id"]:
            # The legacy check below does this for bookings without resources;
            # a chair plus a stylist must still get a stylist who is on duty.
            await AvailabilityService.assert_provider_can_take(
                session,
                business_id=business_id,
                provider_id=validated["provider_id"],
                location_id=validated["location_id"],
                offering_id=validated["offering_id"],
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
            )
        if not resources:
            await AvailabilityService.assert_available(
                session,
                business_id=business_id,
                location_id=validated["location_id"],
                provider_id=validated["provider_id"],
                offering_id=validated["offering_id"],
                reservation_mode=validated["reservation_mode"],
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
                party_size=validated["party_size"],
                capacity=capacity,
            )

        policy = await BookingService.get_or_create_policy(session, business_id)
        deposit_required = bool(policy.require_deposit)
        deposit_amount = Decimal("0")
        if deposit_required:
            deposit_amount = BookingService._compute_deposit_amount(
                policy, offering_price=offering_price
            )

        booking = Booking(
            business_id=business_id,
            location_id=validated["location_id"],
            customer_contact_id=validated["customer_contact_id"],
            offering_id=validated["offering_id"],
            provider_id=validated["provider_id"],
            booking_number=BookingService._generate_booking_number(),
            reservation_mode=validated["reservation_mode"],
            title=title,
            starts_at=validated["starts_at"],
            ends_at=validated["ends_at"],
            party_size=validated["party_size"],
            guest_count=validated["guest_count"],
            capacity=capacity,
            payment_method=validated["payment_method"],
            payment_status=(
                "pending_offline"
                if validated["payment_method"] in {"cod", "pay_at_business", "pay_later"}
                else "pending"
            ),
            deposit_required=deposit_required,
            total_amount=BookingService._total(fixed_price, validated),
            deposit_amount=float(deposit_amount),
            management_token=secrets.token_urlsafe(24),
            management_token_expires_at=datetime.now(timezone.utc) + timedelta(days=90),
            internal_reference=validated["internal_reference"],
            idempotency_key=validated["idempotency_key"],
            channel=payload.get("channel") if payload.get("channel") in ("web", "whatsapp", "phone", "workspace",
                                                                          "marketplace") else None,
        )
        session.add(booking)
        await session.flush()

        # Claim the subjects. Raises ConflictError if any is taken, which rolls
        # the whole request back - the booking row never survives without its
        # allocations, so a calendar entry cannot exist holding nothing.
        if not resources and assign_free_resource:
            held = await BookingAllocationService.allocate_first_free(
                session,
                business_id=business_id,
                booking_id=booking.id,
                location_id=validated["location_id"],
                provider_id=validated["provider_id"],
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
                party_size=validated["party_size"],
                mode=validated["reservation_mode"],
            )
            if held is not None:
                booking.capacity = BookingAllocationService.effective_capacity([held])
                await session.flush()
        else:
            await BookingAllocationService.allocate(
                session,
                business_id=business_id,
                booking_id=booking.id,
                requests=BookingAllocationService.requests_for(
                    resources=resources,
                    provider_id=validated["provider_id"],
                    party_size=validated["party_size"],
                ),
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
                party_size=validated["party_size"],
            )

        if validated["reservation_mode"] == "site_visit" and validated["customer_contact_id"]:
            booking.lead_id = await BookingService._site_visit_lead(
                session, business_id=business_id, actor_id=actor_id, correlation_id=correlation_id,
                booking=booking, contact_id=validated["customer_contact_id"],
            )
            await session.flush()

        history = BookingStatusHistory(
            business_id=business_id,
            booking_id=booking.id,
            from_status=None,
            to_status="pending",
            actor_identity_id=actor_id,
            reason="Booking created",
        )
        session.add(history)
        await session.flush()

        if deposit_required and deposit_amount > 0:
            payment = await PaymentAttemptService.create_attempt(
                session,
                business_id=business_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "source_type": "booking",
                    "source_id": str(booking.id),
                    "amount": float(deposit_amount),
                    "currency": "INR",
                    "payment_method": validated["payment_method"],
                    "customer_contact_id": (
                        str(validated["customer_contact_id"])
                        if validated["customer_contact_id"]
                        else None
                    ),
                    "idempotency_key": f"deposit-{validated['idempotency_key'] or booking.id}",
                },
            )
            payment.provider_metadata = {**(payment.provider_metadata or {}), "purpose": "deposit"}
            await session.flush()
            # Re-sync after purpose is stamped so later succeed paths mark deposit_paid.
            await PaymentAttemptService._sync_source_payment_status(session, payment)
            if payment.status == "succeeded":
                booking.payment_status = "deposit_paid"
            elif payment.status == "pending_offline":
                booking.payment_status = "pending_offline"
            await session.flush()
            await AuditService.record(
                session,
                event_type="booking.deposit_collected",
                actor_identity_id=actor_id,
                actor_context="business",
                business_id=business_id,
                resource_type="booking",
                resource_id=booking.id,
                action="deposit_collected",
                after_state={
                    "payment_id": str(payment.id),
                    "amount": float(deposit_amount),
                    "payment_status": booking.payment_status,
                },
            )
            await OutboxService.publish(
                session,
                event_type="booking.deposit_collected",
                payload={
                    "business_id": str(business_id),
                    "booking_id": str(booking.id),
                    "payment_id": str(payment.id),
                    "amount": float(deposit_amount),
                },
                business_id=business_id,
                correlation_id=correlation_id,
            )

        # Founder §17: a slot waiting on an online deposit is held, not kept for
        # ever - if the deposit is not paid within the owner's hold time the
        # slot is released (booking.hold ladder).
        if (
            deposit_required
            and deposit_amount > 0
            and validated["payment_method"] == "online"
            and booking.payment_status not in ("deposit_paid", "paid")
        ):
            from platform_core.automation import AutomationEngine

            booking.hold_expires_at = datetime.now(timezone.utc) + timedelta(minutes=policy.hold_minutes)
            await session.flush()
            await AutomationEngine.schedule(
                session, business_id, ladder_key="booking.hold", entity_id=booking.id,
                anchor=booking.hold_expires_at,
                period_key=booking.hold_expires_at.isoformat(timespec="seconds"),
            )

        after = BookingResolver.serialize_booking(booking)
        await OutboxService.publish(
            session,
            event_type="booking.created",
            payload={
                "business_id": str(business_id),
                "booking_id": str(booking.id),
                "booking_number": booking.booking_number,
                "customer_contact_id": (
                    str(booking.customer_contact_id) if booking.customer_contact_id else None
                ),
                "starts_at": booking.starts_at.isoformat(),
                "ends_at": booking.ends_at.isoformat(),
                "after": after,
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type="booking.created",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="booking",
            resource_id=booking.id,
            action="created",
            before_state=None,
            after_state=after,
        )
        if booking.customer_contact_id:
            await CustomerTimelineService.record_entry(
                session,
                business_id=business_id,
                contact_id=booking.customer_contact_id,
                activity_type="booking.created",
                resource_type="booking",
                resource_id=booking.id,
                location_id=booking.location_id,
                summary={
                    "booking_number": booking.booking_number,
                    "starts_at": booking.starts_at.isoformat(),
                    "status": booking.status,
                },
            )
            await ConsumerActivityService.record_for_customer_contact(
                session,
                business_id=business_id,
                customer_contact_id=booking.customer_contact_id,
                activity_type="booking.created",
                resource_type="booking",
                resource_id=booking.id,
                summary={
                    "booking_number": booking.booking_number,
                    "starts_at": booking.starts_at.isoformat(),
                    "status": booking.status,
                },
            )
        return booking

    @staticmethod
    async def _site_visit_lead(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        booking: Booking,
        contact_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Founder §13: a site visit is also a sales conversation. Booking owns
        the slot; Leads owns the relationship - through its own service, and
        only when the business uses Leads."""
        from platform_core.models import CustomerContact
        from platform_core.services.lead import LeadService
        from platform_core.services.module_readiness import module_states

        if (await module_states(session, business_id)).get("leads") not in {"enabled", "ready", "active"}:
            return None
        contact = await session.get(CustomerContact, contact_id)
        if contact is None:
            return None
        lead = await LeadService.create_lead(
            session, business_id=business_id, actor_id=actor_id, correlation_id=correlation_id,
            payload={"display_name": contact.display_name, "email": contact.email, "phone": contact.phone,
                     "source": "website_enquiry" if booking.channel in (None, "web") else "manual",
                     "offering_id": str(booking.offering_id) if booking.offering_id else None,
                     "message": f"Site visit booked: {booking.title} on "
                                f"{booking.starts_at.isoformat(timespec='minutes')} ({booking.booking_number})"},
            actor_context="guest_checkout",
        )
        return cast(uuid.UUID, lead.id)

    @staticmethod
    async def get_or_create_policy(session: AsyncSession, business_id: uuid.UUID) -> BookingsPolicy:
        policy = (
            (
                await session.execute(
                    select(BookingsPolicy).where(BookingsPolicy.business_id == business_id)
                )
            )
            .scalars()
            .first()
        )
        if policy is None:
            policy = BookingsPolicy(business_id=business_id)
            session.add(policy)
            await session.flush()
        return policy

    @staticmethod
    def _total(price: Decimal | None, validated: dict[str, Any]) -> Decimal | None:
        """What the booking costs at today's price: a room per night, a class
        per person, anything else once (P1-10D — so a deposit has a balance)."""
        if price is None:
            return None
        if validated["reservation_mode"] == "accommodation":
            nights: int = max((validated["ends_at"].date() - validated["starts_at"].date()).days, 1)
            return price * nights
        if validated["reservation_mode"] == "class_session":
            return price * max(int(validated.get("party_size") or 1), 1)
        return price

    @staticmethod
    def _compute_deposit_amount(policy: BookingsPolicy, *, offering_price: float | None) -> Decimal:
        if policy.deposit_amount is not None:
            return Decimal(str(policy.deposit_amount))
        if policy.deposit_percent is not None and offering_price is not None:
            return (
                Decimal(str(offering_price)) * Decimal(str(policy.deposit_percent)) / Decimal("100")
            ).quantize(Decimal("0.01"))
        if policy.deposit_amount is None and policy.deposit_percent is None:
            raise ValidationError(
                "Deposit is required but Business has no deposit amount configured",
                details={"field": "deposit"},
            )
        raise ValidationError(
            "Deposit percent requires a priced offering",
            details={"field": "deposit"},
        )

    @staticmethod
    async def update_policy(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> BookingsPolicy:
        policy = await BookingService.get_or_create_policy(session, business_id)
        if "require_deposit" in payload:
            policy.require_deposit = bool(payload["require_deposit"])
        if "deposit_amount" in payload:
            policy.deposit_amount = payload["deposit_amount"]
        if "deposit_percent" in payload:
            policy.deposit_percent = payload["deposit_percent"]
        if "cancel_window_hours" in payload:
            policy.cancel_window_hours = int(payload["cancel_window_hours"])
        if payload.get("hold_minutes") is not None:
            policy.hold_minutes = int(payload["hold_minutes"])
        if payload.get("waitlist_enabled") is not None:
            policy.waitlist_enabled = bool(payload["waitlist_enabled"])
        if payload.get("waitlist_offer_minutes") is not None:
            policy.waitlist_offer_minutes = int(payload["waitlist_offer_minutes"])
        policy.version += 1
        policy.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await AuditService.record(
            session,
            event_type="booking.policy_updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="bookings_policy",
            resource_id=business_id,
            action="updated",
            after_state={
                "require_deposit": policy.require_deposit,
                "deposit_amount": float(policy.deposit_amount)
                if policy.deposit_amount is not None
                else None,
                "cancel_window_hours": policy.cancel_window_hours,
                "hold_minutes": policy.hold_minutes,
                "waitlist_enabled": policy.waitlist_enabled,
                "waitlist_offer_minutes": policy.waitlist_offer_minutes,
            },
        )
        return policy

    @staticmethod
    def serialize_policy(policy: BookingsPolicy) -> dict[str, Any]:
        return {
            "require_deposit": policy.require_deposit,
            "deposit_amount": float(policy.deposit_amount) if policy.deposit_amount is not None else None,
            "deposit_percent": float(policy.deposit_percent) if policy.deposit_percent is not None else None,
            "cancel_window_hours": policy.cancel_window_hours,
            "hold_minutes": policy.hold_minutes,
            "waitlist_enabled": policy.waitlist_enabled,
            "waitlist_offer_minutes": policy.waitlist_offer_minutes,
            "version": policy.version,
        }

    @staticmethod
    async def patch_booking(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> Booking:
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="update booking")
        booking = await BookingResolver.resolve_mutable(
            session, business_id=business_id, booking_id=booking_id
        )
        if expected_version is not None and booking.version != expected_version:
            raise ConflictError(
                "Stale booking version",
                details={
                    "expected_version": expected_version,
                    "current_version": booking.version,
                },
            )
        before = BookingResolver.serialize_booking(booking)
        patch = validate_patch_payload(payload)
        for key, value in patch.items():
            setattr(booking, key, value)
        booking.version += 1
        await session.flush()
        after = BookingResolver.serialize_booking(booking)
        await OutboxService.publish(
            session,
            event_type="booking.updated",
            payload={
                "business_id": str(business_id),
                "booking_id": str(booking.id),
                "after": after,
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type="booking.updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="booking",
            resource_id=booking.id,
            action="updated",
            before_state=before,
            after_state=after,
        )
        return booking

    @staticmethod
    async def get_status_history(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> list[BookingStatusHistory]:
        await BookingResolver.resolve(session, business_id=business_id, booking_id=booking_id)
        return cast(
            "list[BookingStatusHistory]",
            await BookingResolver.load_status_history(session, booking_id=booking_id),
        )
