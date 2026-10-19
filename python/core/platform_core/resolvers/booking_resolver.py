"""Booking lookup resolver (Stage 7)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ResourceNotFound, ResourceStateDenied
from platform_core.models import Booking, BookingNote, BookingStatusHistory
from platform_core.validation.booking import TERMINAL_STATUSES


class BookingResolver:
    @staticmethod
    async def resolve(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> Booking:
        result = await session.execute(
            select(Booking).where(
                Booking.id == booking_id,
                Booking.business_id == business_id,
                Booking.deleted_at.is_(None),
            )
        )
        booking = result.scalars().first()
        if booking is None:
            raise ResourceNotFound("Booking")
        return booking

    @staticmethod
    def require_mutable(booking: Booking, *, action: str = "update") -> None:
        if booking.status in TERMINAL_STATUSES:
            raise ResourceStateDenied(
                "booking",
                booking.status,
                action=action,
                allowed_states=["pending", "confirmed", "checked_in"],
            )

    @staticmethod
    async def resolve_mutable(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        action: str = "update",
    ) -> Booking:
        booking = await BookingResolver.resolve(
            session, business_id=business_id, booking_id=booking_id
        )
        BookingResolver.require_mutable(booking, action=action)
        return booking

    @staticmethod
    async def load_status_history(
        session: AsyncSession,
        *,
        booking_id: uuid.UUID,
    ) -> list[BookingStatusHistory]:
        result = await session.execute(
            select(BookingStatusHistory)
            .where(BookingStatusHistory.booking_id == booking_id)
            .order_by(BookingStatusHistory.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    def serialize_booking(booking: Booking) -> dict[str, Any]:
        return {
            "id": str(booking.id),
            "business_id": str(booking.business_id),
            "location_id": str(booking.location_id),
            "customer_contact_id": (
                str(booking.customer_contact_id) if booking.customer_contact_id else None
            ),
            "offering_id": str(booking.offering_id) if booking.offering_id else None,
            "provider_id": str(booking.provider_id) if booking.provider_id else None,
            "booking_number": booking.booking_number,
            "channel": booking.channel,
            "reservation_mode": booking.reservation_mode,
            "status": booking.status,
            "title": booking.title,
            "starts_at": booking.starts_at.isoformat(),
            "ends_at": booking.ends_at.isoformat(),
            "party_size": booking.party_size,
            "guest_count": booking.guest_count,
            "capacity": booking.capacity,
            "payment_method": booking.payment_method,
            "payment_status": booking.payment_status,
            "deposit_required": booking.deposit_required,
            "deposit_amount": float(booking.deposit_amount or 0),
            # What the booking comes to (two nights at 9500: 19000); None when
            # the offering has no fixed price.
            "total_amount": float(booking.total_amount) if booking.total_amount is not None else None,
            "internal_reference": booking.internal_reference,
            "cancellation_reason": booking.cancellation_reason,
            "hold_expires_at": booking.hold_expires_at.isoformat() if booking.hold_expires_at else None,
            "series_id": str(booking.series_id) if booking.series_id else None,
            "occurrence_index": booking.occurrence_index,
            "lead_id": str(booking.lead_id) if booking.lead_id else None,
            "version": booking.version,
            "created_at": booking.created_at.isoformat(),
            "updated_at": booking.updated_at.isoformat(),
        }

    @staticmethod
    def serialize_status_history(entry: BookingStatusHistory) -> dict[str, Any]:
        return {
            "id": str(entry.id),
            "booking_id": str(entry.booking_id),
            "from_status": entry.from_status,
            "to_status": entry.to_status,
            "actor_identity_id": (
                str(entry.actor_identity_id) if entry.actor_identity_id else None
            ),
            "reason": entry.reason,
            "created_at": entry.created_at.isoformat(),
        }

    @staticmethod
    def serialize_note(note: BookingNote) -> dict[str, Any]:
        return {
            "id": str(note.id),
            "booking_id": str(note.booking_id),
            "body": note.body,
            "author_identity_id": str(note.author_identity_id),
            "version": note.version,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }
