"""Workforce module — operational providers (Doc 10 §4.8, Doc 11 §10.5).

identity_id linkage is optional and NEVER grants Workspace access.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import (
    ConflictError,
    ModuleNotActive,
    ResourceNotFound,
    ValidationError,
)
from platform_core.gates import assert_business_mutable
from platform_core.models import (
    BusinessModuleState,
    Offering,
    WorkforceAvailability,
    WorkforceLocationAssignment,
    WorkforceMember,
    WorkforceServiceAssociation,
)
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService

ACTIVE_MODULE_STATES = frozenset({"enabled", "ready", "active"})


class WorkforceService:
    @staticmethod
    async def assert_module_active(session: AsyncSession, business_id: uuid.UUID) -> None:
        state = (
            await session.execute(
                select(BusinessModuleState).where(
                    BusinessModuleState.business_id == business_id,
                    BusinessModuleState.module_id == "workforce",
                )
            )
        ).scalars().first()
        if state is None or state.activation_state not in ACTIVE_MODULE_STATES:
            raise ModuleNotActive("workforce")

    @staticmethod
    def serialize_member(member: WorkforceMember) -> dict[str, Any]:
        return {
            "id": str(member.id),
            "business_id": str(member.business_id),
            "display_name": member.display_name,
            "email": member.email,
            "phone": member.phone,
            "designation": member.designation,
            "identity_id": str(member.identity_id) if member.identity_id else None,
            "status": member.status,
            "notes": member.notes,
            "version": member.version,
            # Explicit: linkage is not a membership grant
            "grants_workspace_access": False,
        }

    @staticmethod
    async def list_members(
        session: AsyncSession, business_id: uuid.UUID, *, status: str | None = None
    ) -> list[WorkforceMember]:
        query = select(WorkforceMember).where(
            WorkforceMember.business_id == business_id,
            WorkforceMember.deleted_at.is_(None),
        )
        if status:
            query = query.where(WorkforceMember.status == status)
        query = query.order_by(WorkforceMember.display_name.asc())
        return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def names(
        session: AsyncSession, *, business_id: uuid.UUID, member_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Workforce's public batch read for other modules' pages: id -> name.
        Kept even for someone who has since left, so old bookings still say who."""
        if not member_ids:
            return {}
        rows = (await session.execute(select(WorkforceMember.id, WorkforceMember.display_name).where(
            WorkforceMember.business_id == business_id, WorkforceMember.id.in_(member_ids),
        ))).all()
        return {row[0]: str(row[1]) for row in rows}

    @staticmethod
    async def get_member(
        session: AsyncSession, *, business_id: uuid.UUID, member_id: uuid.UUID
    ) -> WorkforceMember:
        member = (
            await session.execute(
                select(WorkforceMember).where(
                    WorkforceMember.business_id == business_id,
                    WorkforceMember.id == member_id,
                    WorkforceMember.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if member is None:
            raise ResourceNotFound("WorkforceMember")
        return member

    @staticmethod
    async def create_member(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> WorkforceMember:
        await WorkforceService.assert_module_active(session, business_id)
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="create_workforce_member")
        name = str(payload.get("display_name") or "").strip()
        if not name:
            raise ValidationError("display_name is required")
        identity_id = payload.get("identity_id")
        member = WorkforceMember(
            business_id=business_id,
            display_name=name,
            email=(str(payload["email"]).strip() if payload.get("email") else None),
            phone=(str(payload["phone"]).strip() if payload.get("phone") else None),
            designation=(str(payload["designation"]).strip() if payload.get("designation") else None),
            identity_id=uuid.UUID(str(identity_id)) if identity_id else None,
            status=str(payload.get("status") or "active"),
            notes=payload.get("notes"),
        )
        session.add(member)
        await session.flush()
        after = WorkforceService.serialize_member(member)
        await AuditService.record(
            session,
            event_type="workforce.member_created",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member.id,
            action="created",
            after_state=after,
        )
        await OutboxService.publish(
            session,
            event_type="workforce.member_created",
            payload={"business_id": str(business_id), "member": after},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return member

    @staticmethod
    async def update_member(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        actor_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> WorkforceMember:
        await WorkforceService.assert_module_active(session, business_id)
        member = await WorkforceService.get_member(
            session, business_id=business_id, member_id=member_id
        )
        before = WorkforceService.serialize_member(member)
        for key in ("display_name", "email", "phone", "designation", "notes", "status"):
            if key in payload and payload[key] is not None:
                setattr(member, key, payload[key])
        if "identity_id" in payload:
            raw = payload["identity_id"]
            member.identity_id = uuid.UUID(str(raw)) if raw else None
        member.version += 1
        member.updated_at = datetime.now(timezone.utc)
        await session.flush()
        after = WorkforceService.serialize_member(member)
        await AuditService.record(
            session,
            event_type="workforce.member_updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member.id,
            action="updated",
            before_state=before,
            after_state=after,
        )
        return member

    @staticmethod
    async def deactivate_member(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> WorkforceMember:
        return await WorkforceService.update_member(
            session,
            business_id=business_id,
            member_id=member_id,
            actor_id=actor_id,
            payload={"status": "inactive"},
        )

    @staticmethod
    async def assign_location(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        location_id: uuid.UUID,
        actor_id: uuid.UUID,
        is_primary: bool = False,
    ) -> WorkforceLocationAssignment:
        await WorkforceService.get_member(session, business_id=business_id, member_id=member_id)
        existing = (
            await session.execute(
                select(WorkforceLocationAssignment).where(
                    WorkforceLocationAssignment.member_id == member_id,
                    WorkforceLocationAssignment.location_id == location_id,
                )
            )
        ).scalars().first()
        if existing:
            return existing
        row = WorkforceLocationAssignment(
            business_id=business_id,
            member_id=member_id,
            location_id=location_id,
            is_primary=is_primary,
            assigned_by=actor_id,
        )
        session.add(row)
        await session.flush()
        await AuditService.record(
            session,
            event_type="workforce.location_assigned",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member_id,
            action="location_assigned",
            after_state={"location_id": str(location_id), "is_primary": is_primary},
        )
        return row

    @staticmethod
    async def unassign_location(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        location_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        row = (
            await session.execute(
                select(WorkforceLocationAssignment).where(
                    WorkforceLocationAssignment.business_id == business_id,
                    WorkforceLocationAssignment.member_id == member_id,
                    WorkforceLocationAssignment.location_id == location_id,
                )
            )
        ).scalars().first()
        if row is None:
            raise ResourceNotFound("WorkforceLocationAssignment")
        await session.delete(row)
        await session.flush()
        await AuditService.record(
            session,
            event_type="workforce.location_unassigned",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member_id,
            action="location_unassigned",
            after_state={"location_id": str(location_id)},
        )

    @staticmethod
    async def list_locations(
        session: AsyncSession, *, business_id: uuid.UUID, member_id: uuid.UUID
    ) -> list[WorkforceLocationAssignment]:
        return list(
            (
                await session.execute(
                    select(WorkforceLocationAssignment).where(
                        WorkforceLocationAssignment.business_id == business_id,
                        WorkforceLocationAssignment.member_id == member_id,
                    )
                )
            ).scalars().all()
        )

    @staticmethod
    async def associate_service(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        offering_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> WorkforceServiceAssociation:
        await WorkforceService.get_member(session, business_id=business_id, member_id=member_id)
        offering = (
            await session.execute(
                select(Offering).where(
                    Offering.id == offering_id,
                    Offering.business_id == business_id,
                    Offering.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if offering is None:
            raise ResourceNotFound("Offering")
        existing = (
            await session.execute(
                select(WorkforceServiceAssociation).where(
                    WorkforceServiceAssociation.member_id == member_id,
                    WorkforceServiceAssociation.offering_id == offering_id,
                )
            )
        ).scalars().first()
        if existing:
            return existing
        row = WorkforceServiceAssociation(
            business_id=business_id,
            member_id=member_id,
            offering_id=offering_id,
            created_by=actor_id,
        )
        session.add(row)
        await session.flush()
        await AuditService.record(
            session,
            event_type="workforce.service_associated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member_id,
            action="service_associated",
            after_state={"offering_id": str(offering_id)},
        )
        return row

    @staticmethod
    async def list_services(
        session: AsyncSession, *, business_id: uuid.UUID, member_id: uuid.UUID
    ) -> list[WorkforceServiceAssociation]:
        return list(
            (
                await session.execute(
                    select(WorkforceServiceAssociation).where(
                        WorkforceServiceAssociation.business_id == business_id,
                        WorkforceServiceAssociation.member_id == member_id,
                    )
                )
            ).scalars().all()
        )

    @staticmethod
    async def set_availability(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> WorkforceAvailability:
        await WorkforceService.get_member(session, business_id=business_id, member_id=member_id)
        start = payload.get("start_time")
        end = payload.get("end_time")
        try:
            if isinstance(start, str):
                parts = [int(p) for p in start.split(":")[:2]]
                start = time(parts[0], parts[1])
            if isinstance(end, str):
                parts = [int(p) for p in end.split(":")[:2]]
                end = time(parts[0], parts[1])
        except (ValueError, IndexError) as exc:
            raise ValidationError("Times look like 09:00", details={"field": "start_time"}) from exc
        if not isinstance(start, time) or not isinstance(end, time) or end <= start:
            raise ValidationError("A span must start before it ends", details={"field": "end_time"})
        weekday = payload.get("weekday")
        on = payload.get("exception_date")
        if isinstance(on, str):
            try:
                on = date.fromisoformat(on)
            except ValueError as exc:
                raise ValidationError("Dates look like 2026-10-05", details={"field": "exception_date"}) from exc
        # Weekly hours name a weekday (0 = Monday, as Python counts); a leave,
        # a day off or one-off hours name a date. Exactly one of the two.
        if (weekday is None) == (on is None):
            raise ValidationError("Give either a weekday or a date", details={"field": "weekday"})
        row = WorkforceAvailability(
            business_id=business_id,
            member_id=member_id,
            location_id=payload.get("location_id"),
            weekday=weekday,
            exception_date=on,
            start_time=start,
            end_time=end,
            is_available=bool(payload.get("is_available", True)),
        )
        session.add(row)
        await session.flush()
        await OutboxService.publish(
            session,
            event_type="workforce.availability_updated",
            payload={
                "business_id": str(business_id),
                "member_id": str(member_id),
                "availability_id": str(row.id),
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type="workforce.availability_updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member_id,
            action="availability_updated",
            after_state={"availability_id": str(row.id)},
        )
        return row

    @staticmethod
    async def list_availability(
        session: AsyncSession, *, business_id: uuid.UUID, member_id: uuid.UUID
    ) -> list[WorkforceAvailability]:
        return list(
            (
                await session.execute(
                    select(WorkforceAvailability).where(
                        WorkforceAvailability.business_id == business_id,
                        WorkforceAvailability.member_id == member_id,
                    )
                )
            ).scalars().all()
        )

    @staticmethod
    async def remove_availability(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member_id: uuid.UUID,
        availability_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        row = (
            await session.execute(
                select(WorkforceAvailability).where(
                    WorkforceAvailability.id == availability_id,
                    WorkforceAvailability.business_id == business_id,
                    WorkforceAvailability.member_id == member_id,
                )
            )
        ).scalars().first()
        if row is None:
            raise ResourceNotFound("Availability")
        before = {
            "weekday": row.weekday,
            "exception_date": row.exception_date.isoformat() if row.exception_date else None,
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat(),
            "is_available": row.is_available,
        }
        await session.delete(row)
        await session.flush()
        await OutboxService.publish(
            session,
            event_type="workforce.availability_updated",
            payload={"business_id": str(business_id), "member_id": str(member_id),
                     "availability_id": str(availability_id), "removed": True},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type="workforce.availability_updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="workforce_member",
            resource_id=member_id,
            action="availability_removed",
            before_state=before,
        )

    @staticmethod
    def _on_duty_problem(
        rows: list[WorkforceAvailability],
        *,
        location_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        zone: str,
    ) -> str | None:
        """Why this person cannot take [starts_at, ends_at), or None.

        No schedule at all means none was set - nothing to enforce, and nothing
        is invented. Once any hours exist they are the truth: a dated entry for
        the day (one-off hours, or leave when is_available is false) outranks
        the weekly pattern, blocks (is_available false) are never bookable, and
        the booking must sit inside one working span. Rows tied to another
        location do not count here.
        """
        rows = [r for r in rows if r.location_id is None or r.location_id == location_id]
        if not rows:
            return None
        tz = ZoneInfo(zone)
        local_start, local_end = starts_at.astimezone(tz), ends_at.astimezone(tz)
        day = local_start.date()
        ends_at_midnight = local_end.date() == day + timedelta(days=1) and local_end.time() == time(0, 0)
        if local_end.date() != day and not ends_at_midnight:
            return None  # overnight/multi-day stays are not provider slots
        begin = local_start.time()
        finish = time(23, 59, 59) if ends_at_midnight else local_end.time()
        dated = [r for r in rows if r.exception_date == day]
        weekly = [r for r in rows if r.exception_date is None and r.weekday == day.weekday()]
        for block in [r for r in dated + weekly if not r.is_available]:
            if block.start_time < finish and block.end_time > begin:
                return "away"
        working = [r for r in dated if r.is_available] or [r for r in weekly if r.is_available]
        if not any(r.start_time <= begin and r.end_time >= finish for r in working):
            return "off_duty"
        return None

    @staticmethod
    async def assert_on_duty(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        member: WorkforceMember,
        location_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        zone: str,
    ) -> None:
        """Bookings asks; Workforce answers from the person's own schedule."""
        rows = await WorkforceService.list_availability(
            session, business_id=business_id, member_id=member.id
        )
        problem = WorkforceService._on_duty_problem(
            rows, location_id=location_id, starts_at=starts_at, ends_at=ends_at, zone=zone
        )
        if problem == "away":
            raise ConflictError(
                f"{member.display_name} is away then",
                details={"code": "provider_away", "provider_id": str(member.id)},
            )
        if problem == "off_duty":
            raise ConflictError(
                f"{member.display_name} is not working then",
                details={"code": "provider_off_duty", "provider_id": str(member.id)},
            )

    @staticmethod
    async def assert_provider_eligible(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        provider_id: uuid.UUID,
        location_id: uuid.UUID,
        offering_id: uuid.UUID | None,
    ) -> WorkforceMember:
        member = await WorkforceService.get_member(
            session, business_id=business_id, member_id=provider_id
        )
        if member.status != "active":
            raise ValidationError(
                "Provider is not active",
                details={"provider_id": str(provider_id)},
            )
        assignment = (
            await session.execute(
                select(WorkforceLocationAssignment.id).where(
                    WorkforceLocationAssignment.business_id == business_id,
                    WorkforceLocationAssignment.member_id == provider_id,
                    WorkforceLocationAssignment.location_id == location_id,
                )
            )
        ).scalars().first()
        if assignment is None:
            raise ValidationError(
                "Provider is not assigned to this location",
                details={"provider_id": str(provider_id), "location_id": str(location_id)},
            )
        if offering_id is not None:
            assoc = (
                await session.execute(
                    select(WorkforceServiceAssociation.id).where(
                        WorkforceServiceAssociation.business_id == business_id,
                        WorkforceServiceAssociation.member_id == provider_id,
                        WorkforceServiceAssociation.offering_id == offering_id,
                    )
                )
            ).scalars().first()
            if assoc is None:
                raise ValidationError(
                    "Provider is not associated with this service",
                    details={"provider_id": str(provider_id), "offering_id": str(offering_id)},
                )
        return member
