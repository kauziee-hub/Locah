"""Booking lifecycle and status transitions (Stage 7)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError
from platform_core.gates import assert_business_mutable
from platform_core.models import Booking, BookingStatusHistory
from platform_core.resolvers.booking_resolver import BookingResolver
from platform_core.services.audit import AuditService
from platform_core.services.availability import AvailabilityService
from platform_core.services.booking_allocation import BookingAllocationService
from platform_core.services.business import BusinessService
from platform_core.services.consumer_activity import ConsumerActivityService
from platform_core.services.customer_timeline import CustomerTimelineService
from platform_core.services.outbox import OutboxService
from platform_core.validation.booking import (
    STATUS_EVENT_MAP,
    TERMINAL_STATUSES,
    validate_reschedule_payload,
    validate_status_transition_payload,
)


class BookingLifecycleService:
    @staticmethod
    def _check_version(booking: Booking, expected_version: int | None) -> None:
        if expected_version is None:
            return
        if booking.version != expected_version:
            raise ConflictError(
                "Stale booking version",
                details={
                    "expected_version": expected_version,
                    "current_version": booking.version,
                },
            )

    @staticmethod
    def _context(by_customer: bool, customer_identity_id: uuid.UUID | None) -> str:
        """Who the audit row says acted: the business, a signed-in customer, or
        a guest from their booking link."""
        if not by_customer:
            return "business"
        return "customer" if customer_identity_id else "website_guest"

    @staticmethod
    async def _record_history(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        from_status: str | None,
        to_status: str,
        actor_id: uuid.UUID | None,
        reason: str | None,
    ) -> BookingStatusHistory:
        entry = BookingStatusHistory(
            business_id=business_id,
            booking_id=booking_id,
            from_status=from_status,
            to_status=to_status,
            actor_identity_id=actor_id,
            reason=reason,
        )
        session.add(entry)
        await session.flush()
        return entry

    @staticmethod
    async def _publish_change(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking: Booking,
        actor_id: uuid.UUID,
        correlation_id: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
        event_type: str,
        audit_action: str,
        reason: str | None = None,
        extra: dict[str, Any] | None = None,
        actor_context: str = "business",
    ) -> None:
        payload: dict[str, Any] = {
            "business_id": str(business_id),
            "booking_id": str(booking.id),
            "booking_number": booking.booking_number,
            "status": booking.status,
            "customer_contact_id": (
                str(booking.customer_contact_id) if booking.customer_contact_id else None
            ),
            "starts_at": booking.starts_at.isoformat(),
            "ends_at": booking.ends_at.isoformat(),
            "after": after_state,
        }
        if reason:
            payload["reason"] = reason
        if extra:
            payload.update(extra)
        await OutboxService.publish(
            session,
            event_type=event_type,
            payload=payload,
            business_id=business_id,
            correlation_id=correlation_id,
        )
        if event_type != "booking.updated":
            await OutboxService.publish(
                session,
                event_type="booking.updated",
                payload=payload,
                business_id=business_id,
                correlation_id=correlation_id,
            )
        await AuditService.record(
            session,
            event_type=event_type,
            actor_identity_id=actor_id,
            actor_context=actor_context,
            business_id=business_id,
            resource_type="booking",
            resource_id=booking.id,
            action=audit_action,
            before_state=before_state,
            after_state=after_state,
        )
        if booking.customer_contact_id:
            await CustomerTimelineService.record_entry(
                session,
                business_id=business_id,
                contact_id=booking.customer_contact_id,
                activity_type=event_type,
                resource_type="booking",
                resource_id=booking.id,
                location_id=booking.location_id,
                summary={
                    "booking_number": booking.booking_number,
                    "status": booking.status,
                    "starts_at": booking.starts_at.isoformat(),
                },
            )
            if event_type in {
                "booking.created",
                "booking.confirmed",
                "booking.cancelled",
                "booking.completed",
            }:
                await ConsumerActivityService.record_for_customer_contact(
                    session,
                    business_id=business_id,
                    customer_contact_id=booking.customer_contact_id,
                    activity_type=event_type,
                    resource_type="booking",
                    resource_id=booking.id,
                    summary={
                        "booking_number": booking.booking_number,
                        "status": booking.status,
                        "starts_at": booking.starts_at.isoformat(),
                    },
                )

    @staticmethod
    async def transition_status(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
        by_customer: bool = False,
        customer_identity_id: uuid.UUID | None = None,
    ) -> Booking:
        """``by_customer``: the guest did it from their booking link. The
        history and ``cancelled_by`` then name the customer's own identity (or
        nobody, for a guest without an account) - never the owner, whose
        identity ``actor_id`` only lends the audit row (owner lab, salon: a
        guest's cancellation read as the owner's own action)."""
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="update booking status")
        who = customer_identity_id if by_customer else actor_id
        booking = await BookingResolver.resolve(
            session, business_id=business_id, booking_id=booking_id
        )
        BookingLifecycleService._check_version(booking, expected_version)
        validated = validate_status_transition_payload(payload, current_status=booking.status)
        target = validated["status"]
        reason = validated["reason"]
        before = BookingResolver.serialize_booking(booking)
        from_status = booking.status

        if target in {"cancelled", "rejected", "no_show"}:
            booking.cancellation_reason = reason
            booking.cancelled_by = who

        if target == "confirmed" and booking.payment_method in {
            "cod",
            "pay_at_business",
            "pay_later",
        }:
            if booking.payment_status == "pending":
                booking.payment_status = "pending_offline"

        booking.status = target
        booking.version += 1
        await session.flush()

        # A booking that is no longer going to happen must stop holding its
        # room, table or stylist. Released rows leave the exclusion
        # constraint's partial index, so the slot reopens at once while the
        # record of who held it survives for the calendar history.
        if target in TERMINAL_STATUSES:
            await BookingAllocationService.release_for_booking(
                session, business_id=business_id, booking_id=booking.id
            )

        await BookingLifecycleService._record_history(
            session,
            business_id=business_id,
            booking_id=booking.id,
            from_status=from_status,
            to_status=target,
            actor_id=who,
            reason=reason,
        )
        after = BookingResolver.serialize_booking(booking)
        event_type = STATUS_EVENT_MAP.get(target, "booking.updated")
        await BookingLifecycleService._publish_change(
            session,
            business_id=business_id,
            booking=booking,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
            event_type=event_type,
            audit_action=target,
            reason=reason,
            actor_context=BookingLifecycleService._context(by_customer, customer_identity_id),
        )
        return booking

    @staticmethod
    async def reschedule(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
        enforce_opening_hours: bool = False,
        by_customer: bool = False,
        customer_identity_id: uuid.UUID | None = None,
    ) -> Booking:
        """``by_customer``: as in ``transition_status``."""
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="reschedule booking")
        who = customer_identity_id if by_customer else actor_id
        booking = await BookingResolver.resolve(
            session, business_id=business_id, booking_id=booking_id
        )
        BookingLifecycleService._check_version(booking, expected_version)
        validated = validate_reschedule_payload(payload, current_status=booking.status)
        before = BookingResolver.serialize_booking(booking)
        old_starts = booking.starts_at.isoformat()
        old_ends = booking.ends_at.isoformat()
        if enforce_opening_hours:
            await AvailabilityService.assert_open(
                session,
                location_id=booking.location_id,
                reservation_mode=booking.reservation_mode,
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
            )

        # Move the claims first. reallocate_for_booking releases the old
        # interval before taking the new one, which is what lets a booking slide
        # from 10:00 to 10:30 without colliding with itself, and it runs in this
        # transaction so a conflict on the new slot puts the old one back.
        moved = await BookingAllocationService.reallocate_for_booking(
            session,
            business_id=business_id,
            booking_id=booking.id,
            starts_at=validated["starts_at"],
            ends_at=validated["ends_at"],
            party_size=booking.party_size,
        )
        if moved and booking.provider_id:
            await AvailabilityService.assert_provider_can_take(
                session,
                business_id=business_id,
                provider_id=booking.provider_id,
                location_id=booking.location_id,
                offering_id=booking.offering_id,
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
            )
        if not moved:
            # Nothing allocated: a booking from before resources existed, or one
            # that names neither a resource nor a provider. The legacy check is
            # still the only thing guarding it.
            await AvailabilityService.assert_available(
                session,
                business_id=business_id,
                location_id=booking.location_id,
                provider_id=booking.provider_id,
                offering_id=booking.offering_id,
                reservation_mode=booking.reservation_mode,
                starts_at=validated["starts_at"],
                ends_at=validated["ends_at"],
                party_size=booking.party_size,
                capacity=booking.capacity,
                exclude_booking_id=booking.id,
            )

        booking.starts_at = validated["starts_at"]
        booking.ends_at = validated["ends_at"]
        booking.version += 1
        await session.flush()
        await BookingLifecycleService._record_history(
            session,
            business_id=business_id,
            booking_id=booking.id,
            from_status=booking.status,
            to_status=booking.status,
            actor_id=who,
            reason=validated["reason"] or "Rescheduled",
        )
        after = BookingResolver.serialize_booking(booking)
        await BookingLifecycleService._publish_change(
            session,
            business_id=business_id,
            booking=booking,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
            event_type="booking.rescheduled",
            audit_action="rescheduled",
            reason=validated["reason"],
            extra={"old_starts_at": old_starts, "old_ends_at": old_ends},
            actor_context=BookingLifecycleService._context(by_customer, customer_identity_id),
        )
        return booking
