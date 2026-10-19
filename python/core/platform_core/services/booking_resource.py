"""Configuring bookable resources — the supply side of the booking engine.

A business describes what it has (four treatment rooms, twelve tables, a
yoga studio that seats twenty) and the allocation layer enforces it. Nothing
here knows what industry the business is in; `resource_type` is free text and
the business-type profile supplies the vocabulary.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceNotFound, ValidationError
from platform_core.gates import assert_business_mutable
from platform_core.models import BookingAllocation, BookingResource
from platform_core.resolvers.location_resolver import LocationResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService

ALLOCATION_MODES = frozenset({"exclusive", "pooled"})
GRANULARITIES = frozenset({"slot", "date_range"})
NAME_MAX = 120
TYPE_MAX = 60
CODE_MAX = 40


def _validate(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def present(key: str) -> bool:
        return key in payload and payload[key] is not None

    if not partial or present("resource_type"):
        value = str(payload.get("resource_type") or "").strip().lower()
        if not value or len(value) > TYPE_MAX:
            raise ValidationError("Resource type is required")
        out["resource_type"] = value

    if not partial or present("name"):
        value = str(payload.get("name") or "").strip()
        if not value or len(value) > NAME_MAX:
            raise ValidationError("Resource name is required")
        out["name"] = value

    if "code" in payload:
        code = payload.get("code")
        code = str(code).strip() if code is not None else None
        if code and len(code) > CODE_MAX:
            raise ValidationError("Resource code is too long")
        out["code"] = code or None

    mode = payload.get("allocation_mode")
    if mode is not None:
        mode = str(mode).strip().lower()
        if mode not in ALLOCATION_MODES:
            raise ValidationError("allocation_mode must be exclusive or pooled")
        out["allocation_mode"] = mode

    if present("granularity"):
        granularity = str(payload["granularity"]).strip().lower()
        if granularity not in GRANULARITIES:
            raise ValidationError("granularity must be slot or date_range")
        out["granularity"] = granularity

    for key in ("capacity", "min_party_size", "max_party_size"):
        if present(key):
            number = int(payload[key])
            if number < 1:
                raise ValidationError(f"{key} must be at least 1")
            out[key] = number
    if "min_party_size" in payload and payload["min_party_size"] is None:
        out["min_party_size"] = None
    if "max_party_size" in payload and payload["max_party_size"] is None:
        out["max_party_size"] = None

    for key in ("buffer_before_minutes", "buffer_after_minutes"):
        if present(key):
            minutes = int(payload[key])
            if minutes < 0 or minutes > 24 * 60:
                raise ValidationError(f"{key} must be between 0 and 1440")
            out[key] = minutes

    if present("is_active"):
        out["is_active"] = bool(payload["is_active"])

    if present("metadata"):
        if not isinstance(payload["metadata"], dict):
            raise ValidationError("metadata must be an object")
        meta = dict(payload["metadata"])
        # The room types (offerings) this room is - see booking_allocation.serves.
        if "offering_ids" in meta:
            ids = meta["offering_ids"] or []
            if not isinstance(ids, list):
                raise ValidationError("offering_ids must be a list", details={"field": "offering_ids"})
            try:
                meta["offering_ids"] = list(dict.fromkeys(str(uuid.UUID(str(i))) for i in ids))
            except ValueError as exc:
                raise ValidationError("offering_ids must be offering ids", details={"field": "offering_ids"}) from exc
        out["resource_metadata"] = meta

    return out


def _assert_coherent(resource: BookingResource) -> None:
    """Catch the combinations the table rejects, with a usable message.

    The CHECK constraints are the real boundary; these exist so a misconfigured
    resource comes back as a field error rather than a database error.
    """
    if resource.allocation_mode == "exclusive" and resource.capacity != 1:
        raise ValidationError(
            "An exclusive resource holds one booking at a time, so its capacity is 1. "
            "Use allocation_mode 'pooled' to sell several places in the same slot."
        )
    if (
        resource.min_party_size is not None
        and resource.max_party_size is not None
        and resource.max_party_size < resource.min_party_size
    ):
        raise ValidationError("max_party_size cannot be below min_party_size")


class BookingResourceService:
    @staticmethod
    def serialize(resource: BookingResource) -> dict[str, Any]:
        return {
            "id": str(resource.id),
            "location_id": str(resource.location_id),
            "resource_type": resource.resource_type,
            "name": resource.name,
            "code": resource.code,
            "allocation_mode": resource.allocation_mode,
            "capacity": resource.capacity,
            "min_party_size": resource.min_party_size,
            "max_party_size": resource.max_party_size,
            "buffer_before_minutes": resource.buffer_before_minutes,
            "buffer_after_minutes": resource.buffer_after_minutes,
            "granularity": resource.granularity,
            "is_active": resource.is_active,
            "metadata": resource.resource_metadata or {},
            "version": resource.version,
        }

    @staticmethod
    async def list_resources(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        query = select(BookingResource).where(
            BookingResource.business_id == business_id,
            BookingResource.deleted_at.is_(None),
        )
        if location_id is not None:
            query = query.where(BookingResource.location_id == location_id)
        if resource_type:
            query = query.where(BookingResource.resource_type == resource_type.strip().lower())
        if not include_inactive:
            query = query.where(BookingResource.is_active.is_(True))
        query = query.order_by(BookingResource.resource_type, BookingResource.name)
        result = await session.execute(query)
        return [BookingResourceService.serialize(r) for r in result.scalars().all()]

    @staticmethod
    async def resolve(
        session: AsyncSession, *, business_id: uuid.UUID, resource_id: uuid.UUID
    ) -> BookingResource:
        result = await session.execute(
            select(BookingResource).where(
                BookingResource.id == resource_id,
                BookingResource.business_id == business_id,
                BookingResource.deleted_at.is_(None),
            )
        )
        resource = result.scalars().first()
        if resource is None:
            raise ResourceNotFound("Bookable resource")
        return resource

    @staticmethod
    async def create(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> BookingResource:
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="configure bookable resource")

        location_id = payload.get("location_id")
        if not location_id:
            raise ValidationError("location_id is required")
        location = await LocationResolver.resolve(
            session, business_id=business_id, location_id=uuid.UUID(str(location_id))
        )

        fields = _validate(payload)
        resource = BookingResource(business_id=business_id, location_id=location.id, **fields)
        # Defaults the table would apply, needed here so coherence can be
        # checked before the row is sent.
        if resource.allocation_mode is None:
            resource.allocation_mode = "exclusive"
        if resource.capacity is None:
            resource.capacity = 1
        _assert_coherent(resource)

        session.add(resource)
        await session.flush()

        await AuditService.record(
            session,
            event_type="bookings.resource.created",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="bookings_resource",
            resource_id=resource.id,
            action="created",
            after_state=BookingResourceService.serialize(resource),
        )
        await OutboxService.publish(
            session,
            event_type="bookings.resource.created",
            payload={
                "business_id": str(business_id),
                "resource_id": str(resource.id),
                "resource_type": resource.resource_type,
                "allocation_mode": resource.allocation_mode,
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return resource

    @staticmethod
    async def update(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        resource_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> BookingResource:
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="configure bookable resource")
        resource = await BookingResourceService.resolve(
            session, business_id=business_id, resource_id=resource_id
        )
        if expected_version is not None and resource.version != expected_version:
            raise ConflictError(
                "This resource was changed by someone else",
                details={"expected": expected_version, "actual": resource.version},
            )

        before = BookingResourceService.serialize(resource)
        for key, value in _validate(payload, partial=True).items():
            setattr(resource, key, value)
        _assert_coherent(resource)

        # Shrinking a pool below what is already sold would leave overbooked
        # sessions that nothing would ever flag, so refuse rather than let the
        # calendar disagree with itself. Existing bookings are not cancelled to
        # make room; the business decides what to do about them.
        if resource.allocation_mode == "pooled":
            peak = await BookingResourceService._peak_committed(session, resource.id)
            if peak > resource.capacity:
                raise ConflictError(
                    f"{peak} place(s) are already booked in a single slot, "
                    f"so capacity cannot drop to {resource.capacity}",
                    details={"resource_id": str(resource.id), "committed": peak},
                )

        resource.version += 1
        await session.flush()

        await AuditService.record(
            session,
            event_type="bookings.resource.updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="bookings_resource",
            resource_id=resource.id,
            action="updated",
            before_state=before,
            after_state=BookingResourceService.serialize(resource),
        )
        await OutboxService.publish(
            session,
            event_type="bookings.resource.updated",
            payload={"business_id": str(business_id), "resource_id": str(resource.id)},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return resource

    @staticmethod
    async def _peak_committed(session: AsyncSession, resource_id: uuid.UUID) -> int:
        """The most places held at once across live allocations.

        A sum over everything would count a nine o'clock class and a six o'clock
        one together; what matters is the busiest single overlap.
        """
        result = await session.execute(
            select(BookingAllocation.occupies, BookingAllocation.quantity).where(
                BookingAllocation.resource_id == resource_id,
                BookingAllocation.released_at.is_(None),
            )
        )
        rows = list(result.all())
        peak = 0
        for base, _ in rows:
            overlapping = sum(
                qty for other, qty in rows if other.upper > base.lower and other.lower < base.upper
            )
            peak = max(peak, overlapping)
        return peak

    @staticmethod
    async def archive(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        resource_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
    ) -> BookingResource:
        """Retire a resource, refusing while it still has bookings ahead of it.

        Soft delete rather than removal: past bookings reference it, and a
        calendar that cannot say which room someone stayed in is not a record.
        """
        from datetime import datetime, timezone

        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="archive bookable resource")
        resource = await BookingResourceService.resolve(
            session, business_id=business_id, resource_id=resource_id
        )

        upcoming = (
            (
                await session.execute(
                    select(BookingAllocation.id)
                    .where(
                        BookingAllocation.resource_id == resource.id,
                        BookingAllocation.released_at.is_(None),
                        BookingAllocation.occupies.op("&&")(func_tstzrange_from_now()),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if upcoming is not None:
            raise ConflictError(
                f"{resource.name} still has upcoming bookings. "
                "Move or cancel them before retiring it.",
                details={"resource_id": str(resource.id)},
            )

        before = BookingResourceService.serialize(resource)
        resource.deleted_at = datetime.now(timezone.utc)
        resource.is_active = False
        resource.version += 1
        await session.flush()

        await AuditService.record(
            session,
            event_type="bookings.resource.archived",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="bookings_resource",
            resource_id=resource.id,
            action="archived",
            before_state=before,
            after_state=BookingResourceService.serialize(resource),
        )
        await OutboxService.publish(
            session,
            event_type="bookings.resource.archived",
            payload={"business_id": str(business_id), "resource_id": str(resource.id)},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return resource


def func_tstzrange_from_now() -> Any:
    """`[now, infinity)` — everything still ahead of us."""
    from sqlalchemy import func, literal_column

    return func.tstzrange(func.now(), literal_column("'infinity'::timestamptz"))
