"""Allocating bookable subjects — resources and providers — to a time interval.

This is the half of booking that can collide. Everything about which business
type is being served lives elsewhere; here there are only subjects, intervals
and two allocation modes.

Why exclusive and pooled are enforced differently
-------------------------------------------------
An exclusive subject is guarded by a Postgres exclusion constraint, so two
requests that both read availability before either commits cannot both win —
the loser's INSERT is rejected by the database rather than by whichever process
happened to look second.

A pooled subject cannot be guarded that way. "Seats sold across overlapping
allocations must not exceed capacity" is a sum, and an exclusion constraint
compares pairs. Those go through an advisory lock keyed on the resource plus a
sum inside the same transaction, which is correct but is a genuinely weaker
mechanism: it holds because every writer takes the same lock, not because the
database would refuse a bad row on its own.
"""

from __future__ import annotations

import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, NoReturn

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceNotFound, ValidationError
from platform_core.models import BookingAllocation, BookingResource

# The exclusion constraints, by name, so a violation can be reported as the
# domain conflict it is rather than as an opaque integrity error.
_RESOURCE_CONFLICT = "bookings_allocation_resource_no_overlap"
_PROVIDER_CONFLICT = "bookings_allocation_provider_no_overlap"


# Which resources a kind of booking may be given when the guest names none.
# Each known kind of resource serves its own kind of booking - tables seat
# table bookings, rooms house stays, halls take event dates, studios classes,
# vehicles and equipment rentals, chairs and courts appointments - so a hall
# hire never quietly takes a hotel room and an appointment never takes the
# wedding lawn. A resource type LOCAH does not know stays open to any booking.
ROOM_TYPES = frozenset({"room", "suite", "cottage", "villa", "dorm", "bed", "tent"})
MODE_TYPES: dict[str, frozenset[str]] = {
    "table": frozenset({"table"}),
    "accommodation": ROOM_TYPES,
    "event_date": frozenset({"hall", "lawn"}),
    "class_session": frozenset({"studio"}),
    "rental": frozenset({"vehicle", "equipment"}),
    "appointment": frozenset({"chair", "court"}),
    "site_visit": frozenset(),
}
KNOWN_TYPES = frozenset().union(*MODE_TYPES.values())


def serves(resource: BookingResource, offering_id: uuid.UUID | str | None) -> bool:
    """Whether this resource may be given to a booking of this offering.

    A hotel's rooms are of a room type: "Cottage 2" is a Valley-view cottage
    and must never be handed to a guest who booked the Pool villa (owner lab,
    hotel: with no tie between rooms and room types, any free room took any
    stay, and the villa could be sold as often as there were rooms). A resource
    names the offerings it is (``metadata.offering_ids``); one that names none
    serves every booking of its kind, as before.
    """
    named = (resource.resource_metadata or {}).get("offering_ids") or []
    if not named or offering_id is None:
        return True
    return str(offering_id) in {str(x) for x in named}


def _filter_types(query: Any, mode: str | None) -> Any:
    if mode is None:
        return query
    allowed = MODE_TYPES.get(mode, frozenset())
    return query.where(or_(BookingResource.resource_type.in_(sorted(allowed) or [""]),
                           BookingResource.resource_type.notin_(sorted(KNOWN_TYPES))))


@dataclass(frozen=True)
class AllocationRequest:
    """A subject to claim. Exactly one of resource_id / provider_id is set."""

    resource_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = None
    quantity: int = 1


class BookingAllocationService:
    @staticmethod
    async def load_resource(
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
    def occupancy_window(
        resource: BookingResource | None, starts_at: datetime, ends_at: datetime
    ) -> tuple[datetime, datetime]:
        """Widen the guest-facing window by the resource's turnaround.

        Putting buffers in the stored range is what lets the exclusion
        constraint enforce them: a chair with ten minutes of cleanup simply
        occupies ten more minutes, and nothing on the booking path has to know.
        """
        if resource is None:
            return starts_at, ends_at
        return (
            starts_at - timedelta(minutes=resource.buffer_before_minutes),
            ends_at + timedelta(minutes=resource.buffer_after_minutes),
        )

    @staticmethod
    def assert_party_fits(resource: BookingResource, party_size: int) -> None:
        """A four-top cannot seat six.

        Fit is separate from supply: it constrains which resource may be used,
        not how many are left.
        """
        if resource.max_party_size is not None and party_size > resource.max_party_size:
            raise ValidationError(
                f"{resource.name} seats at most {resource.max_party_size}",
                details={"resource_id": str(resource.id), "party_size": party_size},
            )
        if resource.min_party_size is not None and party_size < resource.min_party_size:
            raise ValidationError(
                f"{resource.name} requires at least {resource.min_party_size}",
                details={"resource_id": str(resource.id), "party_size": party_size},
            )

    @staticmethod
    async def _lock_subject(session: AsyncSession, subject_id: uuid.UUID) -> None:
        """Serialise writers to one subject for the rest of the transaction.

        Taken for exclusive subjects as well as pooled ones, even though an
        exclusion constraint already guards those. Without it the constraint is
        the primary mechanism, and losing to it costs the whole request: a
        failed flush puts the session into a pending-rollback state, so nothing
        afterwards can run on it, not even reporting the conflict, let alone
        trying the next table along.

        With the lock held the check below is authoritative and the flush
        succeeds, so a caller offering three tables in turn gets three clean
        answers. The constraint stays as the backstop that keeps the invariant
        true even if some future code path forgets to take the lock.
        """
        lock_id = zlib.crc32(f"subject:{subject_id}".encode()) & 0x7FFFFFFF
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_id})

    @staticmethod
    async def _exclusive_conflict(
        session: AsyncSession,
        *,
        subject_column: Any,
        subject_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        exclude_booking_id: uuid.UUID | None,
    ) -> bool:
        query = select(BookingAllocation.id).where(
            subject_column == subject_id,
            BookingAllocation.released_at.is_(None),
            BookingAllocation.is_exclusive.is_(True),
            func.upper(BookingAllocation.occupies) > starts_at,
            func.lower(BookingAllocation.occupies) < ends_at,
        )
        if exclude_booking_id is not None:
            query = query.where(
                (BookingAllocation.booking_id.is_(None))
                | (BookingAllocation.booking_id != exclude_booking_id)
            )
        return (await session.execute(query.limit(1))).scalars().first() is not None

    @staticmethod
    async def pooled_usage(
        session: AsyncSession,
        *,
        resource_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        exclude_booking_id: uuid.UUID | None = None,
    ) -> int:
        query = select(func.coalesce(func.sum(BookingAllocation.quantity), 0)).where(
            BookingAllocation.resource_id == resource_id,
            BookingAllocation.released_at.is_(None),
            func.upper(BookingAllocation.occupies) > starts_at,
            func.lower(BookingAllocation.occupies) < ends_at,
        )
        if exclude_booking_id is not None:
            query = query.where(
                (BookingAllocation.booking_id.is_(None))
                | (BookingAllocation.booking_id != exclude_booking_id)
            )
        return int((await session.execute(query)).scalar_one())

    @staticmethod
    async def allocate(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID | None,
        requests: list[AllocationRequest],
        starts_at: datetime,
        ends_at: datetime,
        party_size: int = 1,
        kind: str = "booking",
        exclude_booking_id: uuid.UUID | None = None,
    ) -> list[BookingAllocation]:
        """Claim every subject for the interval, or raise and claim none.

        Ordering matters: subjects are claimed in a stable order so two bookings
        wanting the same pair cannot deadlock by taking them in opposite orders.
        """
        if ends_at <= starts_at:
            raise ValidationError("Booking must end after it starts")

        created: list[BookingAllocation] = []
        ordered = sorted(
            requests,
            key=lambda r: (str(r.resource_id or ""), str(r.provider_id or "")),
        )

        for request in ordered:
            if (request.resource_id is None) == (request.provider_id is None):
                raise ValidationError("An allocation needs exactly one subject")

            resource: BookingResource | None = None
            is_exclusive = True

            if request.resource_id is not None:
                resource = await BookingAllocationService.load_resource(
                    session, business_id=business_id, resource_id=request.resource_id
                )
                if not resource.is_active:
                    raise ValidationError(
                        f"{resource.name} is not currently bookable",
                        details={"resource_id": str(resource.id)},
                    )
                BookingAllocationService.assert_party_fits(resource, party_size)
                is_exclusive = resource.allocation_mode == "exclusive"

            window_start, window_end = BookingAllocationService.occupancy_window(
                resource, starts_at, ends_at
            )

            subject_id = request.resource_id or request.provider_id
            assert subject_id is not None
            # Lock before reading. Checking first and locking afterwards leaves
            # exactly the race the lock exists to close.
            await BookingAllocationService._lock_subject(session, subject_id)

            if is_exclusive:
                subject_column = (
                    BookingAllocation.resource_id
                    if request.resource_id is not None
                    else BookingAllocation.provider_id
                )
                if await BookingAllocationService._exclusive_conflict(
                    session,
                    subject_column=subject_column,
                    subject_id=subject_id,
                    starts_at=window_start,
                    ends_at=window_end,
                    exclude_booking_id=exclude_booking_id,
                ):
                    label = resource.name if resource is not None else "That provider"
                    key = "resource_id" if request.resource_id else "provider_id"
                    raise ConflictError(
                        f"{label} is already booked for this time",
                        details={key: str(subject_id)},
                    )
            else:
                # Pooled: "seats sold must not exceed capacity" is a sum, which
                # an exclusion constraint cannot express, so the lock is the
                # only thing holding this invariant.
                assert resource is not None
                used = await BookingAllocationService.pooled_usage(
                    session,
                    resource_id=resource.id,
                    starts_at=window_start,
                    ends_at=window_end,
                    exclude_booking_id=exclude_booking_id,
                )
                if used + request.quantity > resource.capacity:
                    raise ConflictError(
                        f"{resource.name} has {max(resource.capacity - used, 0)} place(s) left",
                        details={
                            "resource_id": str(resource.id),
                            "capacity": resource.capacity,
                            "used": used,
                            "requested": request.quantity,
                        },
                    )

            allocation = BookingAllocation(
                business_id=business_id,
                kind=kind,
                booking_id=booking_id,
                resource_id=request.resource_id,
                provider_id=request.provider_id,
                quantity=request.quantity,
                is_exclusive=is_exclusive,
                occupies=func.tstzrange(window_start, window_end),
            )
            session.add(allocation)
            try:
                await session.flush()
            except IntegrityError as exc:
                # Reaching here means the constraint caught something the lock
                # and the check above did not, so the session is already
                # unusable and this request is finished either way. Translate it
                # so the caller still sees a conflict rather than an opaque
                # integrity error.
                BookingAllocationService._raise_conflict(exc, resource, request)
            created.append(allocation)

        return created

    @staticmethod
    def _raise_conflict(
        exc: IntegrityError, resource: BookingResource | None, request: AllocationRequest
    ) -> NoReturn:
        """Report an exclusion violation as the domain conflict it is.

        The constraint firing is the expected outcome of losing a race, not an
        internal error, so the caller should see "already booked" rather than a
        500 from an integrity error it cannot interpret.
        """
        message = str(getattr(exc, "orig", exc))
        if _RESOURCE_CONFLICT in message:
            label = resource.name if resource else "That resource"
            raise ConflictError(
                f"{label} is already booked for this time",
                details={"resource_id": str(request.resource_id)},
            ) from exc
        if _PROVIDER_CONFLICT in message:
            raise ConflictError(
                "That provider is already booked for this time",
                details={"provider_id": str(request.provider_id)},
            ) from exc
        raise exc

    @staticmethod
    async def load_many(
        session: AsyncSession, *, business_id: uuid.UUID, resource_ids: list[uuid.UUID]
    ) -> list[BookingResource]:
        """Load every requested resource in one query, preserving request order.

        One round trip rather than one per resource: a booking that consumes a
        room and its equipment should not cost two lookups, and the availability
        read path below asks for many at once.
        """
        if not resource_ids:
            return []
        result = await session.execute(
            select(BookingResource).where(
                BookingResource.id.in_(resource_ids),
                BookingResource.business_id == business_id,
                BookingResource.deleted_at.is_(None),
            )
        )
        found = {r.id: r for r in result.scalars().all()}
        missing = [rid for rid in resource_ids if rid not in found]
        if missing:
            # Naming them would confirm which ids exist in other tenants.
            raise ResourceNotFound("Bookable resource")
        return [found[rid] for rid in resource_ids]

    @staticmethod
    def effective_capacity(
        resources: list[BookingResource], *, fallback: int | None = None
    ) -> int | None:
        """The capacity to record against a booking.

        Taken from configuration whenever any resource is involved, never from
        the request. With several pooled resources the smallest is the binding
        one, since that is what runs out first.
        """
        pooled = [int(r.capacity) for r in resources if r.allocation_mode == "pooled"]
        if pooled:
            return min(pooled)
        if resources:
            return 1
        return fallback

    @staticmethod
    def requests_for(
        *,
        resources: list[BookingResource],
        provider_id: uuid.UUID | None,
        party_size: int = 1,
    ) -> list[AllocationRequest]:
        """Turn a booking's subjects into allocation requests.

        A pooled resource consumes one place per person; an exclusive one is
        taken whole however many people arrive.
        """
        requests = [
            AllocationRequest(
                resource_id=resource.id,
                quantity=party_size if resource.allocation_mode == "pooled" else 1,
            )
            for resource in resources
        ]
        if provider_id is not None:
            requests.append(AllocationRequest(provider_id=provider_id))
        return requests

    @staticmethod
    async def reallocate_for_booking(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        party_size: int = 1,
    ) -> list[BookingAllocation]:
        """Move a booking's existing claims to a new interval.

        Releasing first is what makes a reschedule into an overlapping slot work
        — a booking moved from 10:00 to 10:30 would otherwise collide with
        itself. The release is inside the same transaction, so a conflict on the
        new interval rolls the old claim back rather than losing it.
        """
        existing = (
            (
                await session.execute(
                    select(BookingAllocation).where(
                        BookingAllocation.business_id == business_id,
                        BookingAllocation.booking_id == booking_id,
                        BookingAllocation.released_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        subjects = [
            AllocationRequest(
                resource_id=a.resource_id, provider_id=a.provider_id, quantity=a.quantity
            )
            for a in existing
        ]
        if not subjects:
            return []

        for allocation in existing:
            allocation.released_at = datetime.now(timezone.utc)
        await session.flush()

        return await BookingAllocationService.allocate(
            session,
            business_id=business_id,
            booking_id=booking_id,
            requests=subjects,
            starts_at=starts_at,
            ends_at=ends_at,
            party_size=party_size,
        )

    @staticmethod
    async def release_for_booking(
        session: AsyncSession, *, business_id: uuid.UUID, booking_id: uuid.UUID
    ) -> int:
        """Free a booking's subjects without losing the record of who held them.

        Released rows fall out of the exclusion constraint's partial index, so
        the slot reopens immediately while the history stays queryable.
        """
        result = await session.execute(
            select(BookingAllocation).where(
                BookingAllocation.business_id == business_id,
                BookingAllocation.booking_id == booking_id,
                BookingAllocation.released_at.is_(None),
            )
        )
        allocations = list(result.scalars().all())
        for allocation in allocations:
            allocation.released_at = datetime.now(timezone.utc)
        await session.flush()
        return len(allocations)

    @staticmethod
    async def allocate_first_free(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        booking_id: uuid.UUID,
        location_id: uuid.UUID,
        provider_id: uuid.UUID | None,
        starts_at: datetime,
        ends_at: datetime,
        party_size: int = 1,
        mode: str | None = None,
        offering_id: uuid.UUID | None = None,
    ) -> BookingResource | None:
        """Hold a free resource for a guest who did not choose one.

        A website or WhatsApp guest is never asked which table or chair; the
        business may move them later. The booking must still hold one, or every
        guest "gets" the only table. Candidates are the same ones the public
        availability answer offers (every active resource at the location that
        fits the party), tried tightest fit first, each under its subject lock
        inside a savepoint - a candidate taken since the read is skipped
        cleanly and the next one tried. Returns None when the business
        allocates no resources at all (the provider, if any, is still claimed).
        """
        provider_only = BookingAllocationService.requests_for(
            resources=[], provider_id=provider_id, party_size=party_size
        )
        if not await BookingAllocationService.has_resources(
            session, business_id=business_id, location_id=location_id, mode=mode
        ):
            await BookingAllocationService.allocate(
                session, business_id=business_id, booking_id=booking_id, requests=provider_only,
                starts_at=starts_at, ends_at=ends_at, party_size=party_size,
            )
            return None

        free = await BookingAllocationService.free_resources(
            session, business_id=business_id, location_id=location_id, resource_type=None,
            starts_at=starts_at, ends_at=ends_at, party_size=party_size, mode=mode,
            offering_id=offering_id,
        )
        candidates = await BookingAllocationService.load_many(
            session, business_id=business_id,
            resource_ids=[uuid.UUID(str(r["resource_id"])) for r in free],
        )
        candidates.sort(key=lambda r: (
            r.max_party_size is None, r.max_party_size or 0, r.allocation_mode != "exclusive",
            r.capacity, r.name,
        ))
        for resource in candidates:
            try:
                async with session.begin_nested():
                    await BookingAllocationService.allocate(
                        session, business_id=business_id, booking_id=booking_id,
                        requests=BookingAllocationService.requests_for(
                            resources=[resource], provider_id=provider_id, party_size=party_size
                        ),
                        starts_at=starts_at, ends_at=ends_at, party_size=party_size,
                    )
                return resource
            except ConflictError as exc:
                details = exc.detail.get("details", {}) if isinstance(exc.detail, dict) else {}
                if "provider_id" in details:
                    raise  # the provider is taken; another table will not change that
        raise ConflictError(
            "Nothing is free for this time",
            details={"code": "no_resource_free", "party_size": party_size},
        )

    @staticmethod
    async def has_resources(
        session: AsyncSession, *, business_id: uuid.UUID, location_id: uuid.UUID | None = None,
        mode: str | None = None,
    ) -> bool:
        """Whether this business sells time on anything at all.

        Distinguishes "nothing is free" from "nothing is configured", which
        read very differently to a guest: the first means try another slot, the
        second means this business simply does not allocate resources.
        """
        query = select(BookingResource.id).where(
            BookingResource.business_id == business_id,
            BookingResource.deleted_at.is_(None),
            BookingResource.is_active.is_(True),
        )
        if location_id is not None:
            query = query.where(BookingResource.location_id == location_id)
        query = _filter_types(query, mode)
        return (await session.execute(query.limit(1))).scalars().first() is not None

    @staticmethod
    async def free_resources(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID | None,
        resource_type: str | None,
        starts_at: datetime,
        ends_at: datetime,
        party_size: int = 1,
        exclude_booking_id: uuid.UUID | None = None,
        mode: str | None = None,
        offering_id: uuid.UUID | str | None = None,
    ) -> list[dict[str, Any]]:
        """Which resources can take this booking, answered in two queries.

        ``offering_id``: only the resources that are that offering (a room of
        that room type) or name no offering at all - see ``serves``.

        The obvious shape - list the resources, then ask about each one - is the
        N+1 that made Marketplace search take ten seconds. Instead: one query
        for the candidates, one aggregate for what is already committed against
        all of them, then the arithmetic in Python. Query count does not grow
        with the number of rooms a hotel has.

        Buffers are applied per resource, so a chair with fifteen minutes of
        cleanup is judged on the window it really occupies. The answer is
        advisory: it can go stale between being read and being acted on, which
        is exactly why allocation re-checks under a lock rather than trusting it.
        """
        if ends_at <= starts_at:
            raise ValidationError("Booking must end after it starts")

        candidates = select(BookingResource).where(
            BookingResource.business_id == business_id,
            BookingResource.deleted_at.is_(None),
            BookingResource.is_active.is_(True),
        )
        if location_id is not None:
            candidates = candidates.where(BookingResource.location_id == location_id)
        if resource_type:
            candidates = candidates.where(
                BookingResource.resource_type == resource_type.strip().lower()
            )
        candidates = _filter_types(candidates, mode)
        resources = [r for r in (await session.execute(candidates)).scalars().all() if serves(r, offering_id)]
        if not resources:
            return []

        # Widen the probe window to the largest buffer in play, so one aggregate
        # can answer for resources with different turnarounds.
        widest_before = max((r.buffer_before_minutes for r in resources), default=0)
        widest_after = max((r.buffer_after_minutes for r in resources), default=0)
        probe_start = starts_at - timedelta(minutes=widest_before)
        probe_end = ends_at + timedelta(minutes=widest_after)

        usage_query = (
            select(
                BookingAllocation.resource_id,
                func.sum(BookingAllocation.quantity).label("committed"),
                func.bool_or(BookingAllocation.is_exclusive).label("has_exclusive"),
                func.min(func.lower(BookingAllocation.occupies)).label("first_start"),
                func.max(func.upper(BookingAllocation.occupies)).label("last_end"),
            )
            .where(
                BookingAllocation.resource_id.in_([r.id for r in resources]),
                BookingAllocation.released_at.is_(None),
                func.upper(BookingAllocation.occupies) > probe_start,
                func.lower(BookingAllocation.occupies) < probe_end,
            )
            .group_by(BookingAllocation.resource_id)
        )
        if exclude_booking_id is not None:
            usage_query = usage_query.where(
                (BookingAllocation.booking_id.is_(None))
                | (BookingAllocation.booking_id != exclude_booking_id)
            )
        usage = {row[0]: row for row in (await session.execute(usage_query)).all()}

        free: list[dict[str, Any]] = []
        for resource in resources:
            window_start, window_end = BookingAllocationService.occupancy_window(
                resource, starts_at, ends_at
            )
            row = usage.get(resource.id)
            # The aggregate used the widest window, so re-check that anything
            # found actually lands inside this resource's own one.
            touches = bool(
                row is not None and row.last_end > window_start and row.first_start < window_end
            )

            if resource.max_party_size is not None and party_size > resource.max_party_size:
                continue
            if resource.min_party_size is not None and party_size < resource.min_party_size:
                continue

            if resource.allocation_mode == "exclusive":
                if touches:
                    continue
                remaining = 1
            else:
                committed = int(row.committed) if touches and row is not None else 0
                remaining = max(resource.capacity - committed, 0)
                if remaining < party_size:
                    continue

            free.append(
                {
                    "resource_id": str(resource.id),
                    "name": resource.name,
                    "code": resource.code,
                    "resource_type": resource.resource_type,
                    "allocation_mode": resource.allocation_mode,
                    "capacity": resource.capacity,
                    "remaining": remaining,
                }
            )
        return free

    @staticmethod
    async def list_for_booking(
        session: AsyncSession, *, business_id: uuid.UUID, booking_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        result = await session.execute(
            select(BookingAllocation).where(
                BookingAllocation.business_id == business_id,
                BookingAllocation.booking_id == booking_id,
            )
        )
        return [
            {
                "id": str(a.id),
                "resource_id": str(a.resource_id) if a.resource_id else None,
                "provider_id": str(a.provider_id) if a.provider_id else None,
                "quantity": a.quantity,
                "released_at": a.released_at.isoformat() if a.released_at else None,
            }
            for a in result.scalars().all()
        ]
