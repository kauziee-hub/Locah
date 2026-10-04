"""Fulfilment module service (Doc 11 §10.4) — consumes Orders; does not mutate Order internals."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.context_resolver import bind_public_context
from platform_core.exceptions import ModuleNotActive, ResourceNotFound, ValidationError
from platform_core.gates import assert_business_mutable
from platform_core.models import (
    BusinessLocation,
    BusinessModuleState,
    FulfilmentJob,
    FulfilmentSettings,
    FulfilmentZone,
    Offering,
    SalesOrder,
)
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.outbox import OutboxService
from platform_core.validation.fulfilment import (
    CUSTOMER_FACING_STATUS,
    FULFILMENT_MODES,
    haversine_km,
    validate_job_status_payload,
    validate_payment_rules,
    validate_settings_payload,
    validate_zone_payload,
)

TRACKING_TTL_DAYS = 30
ACTIVE_MODULE_STATES = frozenset({"enabled", "ready", "active"})


class FulfilmentService:
    @staticmethod
    def serialize_settings(settings: FulfilmentSettings) -> dict[str, Any]:
        return {
            "business_id": str(settings.business_id),
            "pickup_enabled": settings.pickup_enabled,
            "delivery_enabled": settings.delivery_enabled,
            "delivery_fee_offering_id": (
                str(settings.delivery_fee_offering_id)
                if settings.delivery_fee_offering_id
                else None
            ),
            "cod_allowed": settings.cod_allowed,
            "first_order_cod_cap": float(settings.first_order_cod_cap)
            if settings.first_order_cod_cap is not None else None,
            "version": settings.version,
        }

    @staticmethod
    def serialize_zone(zone: FulfilmentZone) -> dict[str, Any]:
        return {
            "id": str(zone.id),
            "business_id": str(zone.business_id),
            "location_id": str(zone.location_id) if zone.location_id else None,
            "name": zone.name,
            "match_type": zone.match_type,
            "city": zone.city,
            "postal_prefix": zone.postal_prefix,
            "center_lat": float(zone.center_lat) if zone.center_lat is not None else None,
            "center_lng": float(zone.center_lng) if zone.center_lng is not None else None,
            "radius_km": float(zone.radius_km) if zone.radius_km is not None else None,
            "charge_amount": float(zone.charge_amount),
            "currency": zone.currency,
            "is_active": zone.is_active,
            "version": zone.version,
        }

    @staticmethod
    def serialize_job(job: FulfilmentJob, *, public: bool = False) -> dict[str, Any]:
        base = {
            "id": str(job.id),
            "order_id": str(job.order_id),
            "mode": job.mode,
            "status": job.status,
            "customer_status": CUSTOMER_FACING_STATUS.get(job.status, job.status),
            "delivery_charge": float(job.delivery_charge),
            "currency": job.currency,
            "delivery_address": job.delivery_address,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }
        if public:
            return base
        return {
            **base,
            "business_id": str(job.business_id),
            "location_id": str(job.location_id),
            "zone_id": str(job.zone_id) if job.zone_id else None,
            "tracking_token": job.tracking_token,
            "tracking_expires_at": job.tracking_expires_at.isoformat(),
            "outcome_reason": job.outcome_reason,
            "version": job.version,
        }

    @staticmethod
    async def assert_module_active(session: AsyncSession, business_id: uuid.UUID) -> None:
        state = (
            (
                await session.execute(
                    select(BusinessModuleState).where(
                        BusinessModuleState.business_id == business_id,
                        BusinessModuleState.module_id == "fulfilment",
                    )
                )
            )
            .scalars()
            .first()
        )
        if state is None or state.activation_state not in ACTIVE_MODULE_STATES:
            raise ModuleNotActive("fulfilment")

    @staticmethod
    async def ensure_settings(session: AsyncSession, business_id: uuid.UUID) -> FulfilmentSettings:
        settings = (
            (
                await session.execute(
                    select(FulfilmentSettings).where(FulfilmentSettings.business_id == business_id)
                )
            )
            .scalars()
            .first()
        )
        if settings is None:
            settings = FulfilmentSettings(business_id=business_id)
            session.add(settings)
            await session.flush()
        return settings

    @staticmethod
    async def payment_rules(session: AsyncSession, business_id: uuid.UUID) -> dict[str, Any]:
        """Paying on delivery / at pickup as the owner set it — read by the website
        checkout and WhatsApp journeys alike. A visitor never creates the row."""
        row = (await session.execute(select(FulfilmentSettings).where(
            FulfilmentSettings.business_id == business_id))).scalars().first()
        return {"on_delivery": True if row is None else bool(row.cod_allowed),
                "first_order_cap": float(row.first_order_cod_cap)
                if row is not None and row.first_order_cod_cap is not None else None}

    @staticmethod
    async def set_payment_rules(session: AsyncSession, *, business_id: uuid.UUID, actor_id: uuid.UUID,
                                payload: dict[str, Any]) -> FulfilmentSettings:
        """Change only the paying-on-delivery rules (the WhatsApp page and the
        Deliveries & pickup page both land here)."""
        settings = await FulfilmentService.ensure_settings(session, business_id)
        validated = validate_payment_rules(payload)
        if not validated:
            return settings
        before = FulfilmentService.serialize_settings(settings)
        for key, value in validated.items():
            setattr(settings, key, value)
        settings.version += 1
        settings.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await AuditService.record(
            session, event_type="fulfilment.payment_rules_updated", actor_identity_id=actor_id,
            actor_context="business", business_id=business_id, resource_type="fulfilment_settings",
            resource_id=business_id, action="settings_updated", before_state=before,
            after_state=FulfilmentService.serialize_settings(settings))
        return settings

    @staticmethod
    async def update_settings(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> FulfilmentSettings:
        await FulfilmentService.assert_module_active(session, business_id)
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="configure_fulfilment")
        settings = await FulfilmentService.ensure_settings(session, business_id)
        validated = validate_settings_payload(payload, current=settings)
        before = FulfilmentService.serialize_settings(settings)
        for key, value in validated.items():
            setattr(settings, key, value)
        settings.version += 1
        settings.updated_at = datetime.now(timezone.utc)
        await session.flush()
        after = FulfilmentService.serialize_settings(settings)
        await AuditService.record(
            session,
            event_type="fulfilment.settings_updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="fulfilment_settings",
            resource_id=business_id,
            action="settings_updated",
            before_state=before,
            after_state=after,
        )
        return settings

    @staticmethod
    async def _ensure_delivery_fee_offering(
        session: AsyncSession, *, business_id: uuid.UUID
    ) -> uuid.UUID:
        settings = await FulfilmentService.ensure_settings(session, business_id)
        if settings.delivery_fee_offering_id:
            return cast(uuid.UUID, settings.delivery_fee_offering_id)
        offering = Offering(
            business_id=business_id,
            title="Delivery fee",
            offering_type="product",
            status="active",
            visibility="private",
            track_inventory=False,
            price_amount=0,
            currency="INR",
            sku=f"FULFIL-DELIVERY-{uuid.uuid4().hex[:8].upper()}",
        )
        session.add(offering)
        await session.flush()
        settings.delivery_fee_offering_id = offering.id
        settings.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return cast(uuid.UUID, offering.id)

    @staticmethod
    async def create_zone(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> FulfilmentZone:
        await FulfilmentService.assert_module_active(session, business_id)
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="configure_fulfilment_zone")
        validated = validate_zone_payload(payload)
        await FulfilmentService._ensure_delivery_fee_offering(session, business_id=business_id)
        settings = await FulfilmentService.ensure_settings(session, business_id)
        if not settings.delivery_enabled:
            settings.delivery_enabled = True
            settings.version += 1
        zone = FulfilmentZone(
            business_id=business_id,
            location_id=validated["location_id"],
            name=validated["name"],
            match_type=validated["match_type"],
            city=validated["city"],
            postal_prefix=validated["postal_prefix"],
            center_lat=validated["center_lat"],
            center_lng=validated["center_lng"],
            radius_km=validated["radius_km"],
            charge_amount=float(validated["charge_amount"]),
            currency=validated["currency"],
            is_active=validated["is_active"],
        )
        session.add(zone)
        await session.flush()
        after = FulfilmentService.serialize_zone(zone)
        await AuditService.record(
            session,
            event_type="fulfilment.zone_configured",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="fulfilment_zone",
            resource_id=zone.id,
            action="created",
            after_state=after,
        )
        await OutboxService.publish(
            session,
            event_type="fulfilment.zone_configured",
            payload={"business_id": str(business_id), "zone": after},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return zone

    @staticmethod
    async def update_zone(
        session: AsyncSession, *, business_id: uuid.UUID, zone_id: uuid.UUID, actor_id: uuid.UUID,
        correlation_id: str, is_active: bool | None = None, charge_amount: float | None = None,
    ) -> FulfilmentZone:
        """Switch a delivery zone off or on, or change its charge."""
        await FulfilmentService.assert_module_active(session, business_id)
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="configure_fulfilment_zone")
        zone = (await session.execute(select(FulfilmentZone).where(
            FulfilmentZone.business_id == business_id, FulfilmentZone.id == zone_id,
            FulfilmentZone.deleted_at.is_(None)))).scalars().first()
        if zone is None:
            raise ResourceNotFound("Delivery zone")
        before = FulfilmentService.serialize_zone(zone)
        if is_active is not None:
            zone.is_active = bool(is_active)
        if charge_amount is not None:
            if charge_amount < 0 or charge_amount > 100000:
                raise ValidationError("A delivery charge is between ₹0 and ₹1,00,000",
                                      details={"field": "charge_amount"})
            zone.charge_amount = float(charge_amount)
        zone.version += 1
        zone.updated_at = datetime.now(timezone.utc)
        await session.flush()
        after = FulfilmentService.serialize_zone(zone)
        await AuditService.record(
            session, event_type="fulfilment.zone_configured", actor_identity_id=actor_id, actor_context="business",
            business_id=business_id, resource_type="fulfilment_zone", resource_id=zone.id, action="updated",
            before_state=before, after_state=after)
        await OutboxService.publish(
            session, event_type="fulfilment.zone_configured", payload={"business_id": str(business_id), "zone": after},
            business_id=business_id, correlation_id=correlation_id)
        return zone

    @staticmethod
    async def list_zones(
        session: AsyncSession, business_id: uuid.UUID, *, active_only: bool = False
    ) -> list[FulfilmentZone]:
        query = select(FulfilmentZone).where(
            FulfilmentZone.business_id == business_id,
            FulfilmentZone.deleted_at.is_(None),
        )
        if active_only:
            query = query.where(FulfilmentZone.is_active.is_(True))
        query = query.order_by(FulfilmentZone.name.asc())
        return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def match_zone(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        address: dict[str, Any],
    ) -> tuple[FulfilmentZone | None, Decimal]:
        zones = await FulfilmentService.list_zones(session, business_id, active_only=True)
        city = str(address.get("city") or "").strip().lower()
        postal = str(address.get("postal_code") or address.get("postal") or "").strip()
        lat = address.get("lat") or address.get("latitude")
        lng = address.get("lng") or address.get("longitude")
        for zone in zones:
            if (
                zone.match_type == "city"
                and city
                and zone.city
                and zone.city.strip().lower() == city
            ):
                return zone, Decimal(str(zone.charge_amount))
            if (
                zone.match_type == "postal_prefix"
                and postal
                and zone.postal_prefix
                and postal.startswith(zone.postal_prefix)
            ):
                return zone, Decimal(str(zone.charge_amount))
            if (
                zone.match_type == "radius"
                and lat is not None
                and lng is not None
                and zone.center_lat is not None
                and zone.center_lng is not None
                and zone.radius_km is not None
            ):
                dist = haversine_km(
                    float(lat), float(lng), float(zone.center_lat), float(zone.center_lng)
                )
                if dist <= float(zone.radius_km):
                    return zone, Decimal(str(zone.charge_amount))
        return None, Decimal("0")

    @staticmethod
    async def active_modes(session: AsyncSession, business_id: uuid.UUID) -> list[str]:
        try:
            await FulfilmentService.assert_module_active(session, business_id)
        except ValidationError:
            return []
        settings = await FulfilmentService.ensure_settings(session, business_id)
        modes: list[str] = []
        if settings.pickup_enabled:
            modes.append("pickup")
        if settings.delivery_enabled:
            zones = await FulfilmentService.list_zones(session, business_id, active_only=True)
            if zones:
                modes.append("delivery")
        return modes

    @staticmethod
    async def create_job_for_order(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        order: SalesOrder,
        actor_id: uuid.UUID | None,
        correlation_id: str,
        mode: str,
        delivery_address: dict[str, Any] | None = None,
    ) -> FulfilmentJob:
        await FulfilmentService.assert_module_active(session, business_id)
        if mode not in FULFILMENT_MODES:
            raise ValidationError("Unsupported fulfilment mode")
        modes = await FulfilmentService.active_modes(session, business_id)
        if mode not in modes:
            raise ValidationError(
                "Fulfilment mode is not enabled for this Business",
                details={"mode": mode, "active_modes": modes},
            )
        existing = (
            (await session.execute(select(FulfilmentJob).where(FulfilmentJob.order_id == order.id)))
            .scalars()
            .first()
        )
        if existing is not None:
            return existing

        zone = None
        charge = Decimal("0")
        if mode == "delivery":
            if not delivery_address:
                raise ValidationError("Delivery address is required")
            zone, charge = await FulfilmentService.match_zone(
                session, business_id=business_id, address=delivery_address
            )
            if zone is None:
                raise ValidationError(
                    "Address is outside configured delivery zones",
                    details={"field": "delivery_address"},
                )

        token = secrets.token_urlsafe(24)
        job = FulfilmentJob(
            business_id=business_id,
            order_id=order.id,
            location_id=order.location_id,
            mode=mode,
            status="pending",
            zone_id=zone.id if zone else None,
            delivery_address=delivery_address,
            delivery_charge=float(charge),
            currency=order.currency,
            tracking_token=token,
            tracking_expires_at=datetime.now(timezone.utc) + timedelta(days=TRACKING_TTL_DAYS),
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(job)
        await session.flush()
        after = FulfilmentService.serialize_job(job)
        if actor_id is not None:
            await AuditService.record(
                session,
                event_type="fulfilment.job_created",
                actor_identity_id=actor_id,
                actor_context="business",
                business_id=business_id,
                resource_type="fulfilment_job",
                resource_id=job.id,
                action="created",
                after_state=after,
            )
        await OutboxService.publish(
            session,
            event_type="fulfilment.job_created",
            payload={
                "business_id": str(business_id),
                "job_id": str(job.id),
                "order_id": str(order.id),
                "mode": mode,
                "status": job.status,
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return job

    @staticmethod
    async def list_jobs(
        session: AsyncSession,
        business_id: uuid.UUID,
        *,
        status: str | None = None,
        mode: str | None = None,
    ) -> list[FulfilmentJob]:
        query = select(FulfilmentJob).where(FulfilmentJob.business_id == business_id)
        if status:
            query = query.where(FulfilmentJob.status == status)
        if mode:
            query = query.where(FulfilmentJob.mode == mode)
        query = query.order_by(FulfilmentJob.created_at.desc()).limit(300)
        return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def describe_jobs(session: AsyncSession, business_id: uuid.UUID,
                            jobs: list[FulfilmentJob]) -> list[dict[str, Any]]:
        """Jobs as the Workspace shows them: whose order, its number, and the
        delivery address in one line — never an id or a stored status."""
        from platform_core.resolvers.customer_resolver import CustomerResolver

        order_ids = [j.order_id for j in jobs]
        orders = {o.id: o for o in (await session.execute(select(SalesOrder).where(
            SalesOrder.business_id == business_id, SalesOrder.id.in_(order_ids)))).scalars().all()} if order_ids else {}
        people = await CustomerResolver.summaries(
            session, business_id=business_id,
            contact_ids={o.customer_contact_id for o in orders.values() if o.customer_contact_id})
        out = []
        for j in jobs:
            order = orders.get(j.order_id)
            person = people.get(order.customer_contact_id) if order and order.customer_contact_id else None
            a = j.delivery_address if isinstance(j.delivery_address, dict) else {}
            keys = ("line1", "line2", "line", "address_line", "street", "area", "locality", "landmark", "city",
                    "postal_code", "pincode")
            parts = [str(a[k]).strip() for k in keys if isinstance(a.get(k), str) and str(a[k]).strip()]
            out.append(FulfilmentService.serialize_job(j) | {
                "order_number": order.order_number if order else None,
                "order_total": float(order.total_amount) if order else None,
                "customer_name": (person["name"] if person else None) or (
                    str(a.get("name")).strip() if isinstance(a.get("name"), str) else None),
                "customer_phone": (person["phone"] if person else None) or (
                    str(a.get("phone")).strip() if isinstance(a.get("phone"), str) else None),
                "address_line": ", ".join(dict.fromkeys(parts)) or None,
                "note": str(a.get("note")).strip() if isinstance(a.get("note"), str) and a.get("note") else None,
            })
        return out

    @staticmethod
    async def get_job(
        session: AsyncSession, *, business_id: uuid.UUID, job_id: uuid.UUID
    ) -> FulfilmentJob:
        job = (
            (
                await session.execute(
                    select(FulfilmentJob).where(
                        FulfilmentJob.business_id == business_id,
                        FulfilmentJob.id == job_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if job is None:
            raise ResourceNotFound("FulfilmentJob")
        return job

    @staticmethod
    async def get_job_by_order(
        session: AsyncSession, *, business_id: uuid.UUID, order_id: uuid.UUID
    ) -> FulfilmentJob | None:
        return (
            (
                await session.execute(
                    select(FulfilmentJob).where(
                        FulfilmentJob.business_id == business_id,
                        FulfilmentJob.order_id == order_id,
                    )
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    async def transition_status(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        job_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> FulfilmentJob:
        job = await FulfilmentService.get_job(session, business_id=business_id, job_id=job_id)
        validated = validate_job_status_payload(payload, current=job.status)
        next_status = validated["status"]
        if job.mode == "pickup" and next_status == "out_for_delivery":
            raise ValidationError("Pickup jobs cannot enter out_for_delivery")
        if job.mode == "delivery" and job.status == "ready" and next_status == "delivered":
            raise ValidationError(
                "Delivery jobs must pass through out_for_delivery",
                details={"from": "ready", "to": "delivered"},
            )
        before = FulfilmentService.serialize_job(job)
        job.status = next_status
        job.outcome_reason = validated["reason"]
        job.updated_by = actor_id
        job.updated_at = datetime.now(timezone.utc)
        job.version += 1
        await session.flush()
        after = FulfilmentService.serialize_job(job)
        await AuditService.record(
            session,
            event_type="fulfilment.status_changed",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="fulfilment_job",
            resource_id=job.id,
            action="status_changed",
            before_state=before,
            after_state=after,
            reason=validated["reason"],
        )
        event_type = "fulfilment.status_changed"
        if next_status == "delivered":
            event_type = "fulfilment.delivered"
        elif next_status == "failed":
            event_type = "fulfilment.failed"
        await OutboxService.publish(
            session,
            event_type=event_type,
            payload={
                "business_id": str(business_id),
                "job_id": str(job.id),
                "order_id": str(job.order_id),
                "from": before["status"],
                "to": next_status,
                "reason": validated["reason"],
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )
        if event_type != "fulfilment.status_changed":
            await OutboxService.publish(
                session,
                event_type="fulfilment.status_changed",
                payload={
                    "business_id": str(business_id),
                    "job_id": str(job.id),
                    "order_id": str(job.order_id),
                    "from": before["status"],
                    "to": next_status,
                },
                business_id=business_id,
                correlation_id=correlation_id,
            )
        return job

    @staticmethod
    async def cancel_for_order(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        order_id: uuid.UUID,
        correlation_id: str,
        reason: str,
    ) -> None:
        job = await FulfilmentService.get_job_by_order(
            session, business_id=business_id, order_id=order_id
        )
        if job is None or job.status in {"delivered", "cancelled", "failed"}:
            return
        before = job.status
        job.status = "cancelled"
        job.outcome_reason = reason
        job.updated_at = datetime.now(timezone.utc)
        job.version += 1
        await session.flush()
        await OutboxService.publish(
            session,
            event_type="fulfilment.status_changed",
            payload={
                "business_id": str(business_id),
                "job_id": str(job.id),
                "order_id": str(order_id),
                "from": before,
                "to": "cancelled",
                "reason": reason,
            },
            business_id=business_id,
            correlation_id=correlation_id,
        )

    # Where an order's step puts its pickup / delivery job. Only ever forward: a
    # job already further along (or finished) is left alone.
    _FOLLOW: dict[str, dict[str, str]] = {
        "order.preparing": {"pending": "preparing"},
        "order.ready": {"pending": "ready", "preparing": "ready"},
        # A completed order was handed over: a pickup was collected; a delivery
        # that is on its way arrived. A delivery not yet sent out is left for the
        # owner — it must pass through "out for delivery" (the customer's link).
        "order.completed": {"pending": "delivered", "preparing": "delivered", "ready": "delivered",
                            "out_for_delivery": "delivered"},
    }

    @staticmethod
    async def follow_order(session: AsyncSession, *, business_id: uuid.UUID, order_id: uuid.UUID,
                           event_type: str, correlation_id: str) -> str | None:
        """Move the order's job with the order, so nobody updates the same order twice.
        Returns the job's new status, or None when it was left as it was."""
        job = await FulfilmentService.get_job_by_order(session, business_id=business_id, order_id=order_id)
        if job is None:
            return None
        to = FulfilmentService._FOLLOW.get(event_type, {}).get(job.status)
        if to is None or (to == "delivered" and job.mode != "pickup" and job.status != "out_for_delivery"):
            return None
        before = job.status
        job.status = to
        job.updated_at = datetime.now(timezone.utc)
        job.version += 1
        await session.flush()
        payload = {"business_id": str(business_id), "job_id": str(job.id), "order_id": str(order_id),
                   "from": before, "to": to, "reason": None}
        await OutboxService.publish(session, event_type="fulfilment.status_changed", payload=payload,
                                    business_id=business_id, correlation_id=correlation_id)
        if to == "delivered":
            await OutboxService.publish(session, event_type="fulfilment.delivered", payload=payload,
                                        business_id=business_id, correlation_id=correlation_id)
        return to

    @staticmethod
    async def _due_words(session: AsyncSession, order: SalesOrder) -> str | None:
        if order.due_at is None:
            return None
        from platform_core.models import BusinessLocation
        from platform_core.orders.preorder import when_words, zone_of

        words: str = when_words(order.due_at, zone_of(await session.get(BusinessLocation, order.location_id)))
        return words

    @staticmethod
    async def get_tracking(
        session: AsyncSession,
        *,
        order_id: uuid.UUID,
        token: str | None = None,
    ) -> dict[str, Any]:
        # Public endpoint: no identity, no business context bound yet, and
        # the order/job tables' RLS policies are business-scoped. Resolve the
        # owning Business via a narrow SECURITY DEFINER function (exposes
        # only orders_orders.business_id for this one order id, nothing
        # else) and bind it, mirroring bind_public_context's use elsewhere
        # for guest-facing reads. This bind establishes tenant scope only —
        # it is not an authorization decision. The tracking_token check
        # below remains the sole authorization gate, unchanged.
        business_id = (
            await session.execute(
                text("SELECT resolve_order_business_id(:order_id)"),
                {"order_id": order_id},
            )
        ).scalar()
        if business_id is None:
            raise ResourceNotFound("Order tracking")
        await bind_public_context(session, business_id)

        job = (
            (await session.execute(select(FulfilmentJob).where(FulfilmentJob.order_id == order_id)))
            .scalars()
            .first()
        )
        if job is None:
            raise ResourceNotFound("Order tracking")
        if token is None or not secrets.compare_digest(job.tracking_token, token):
            raise ResourceNotFound("Order tracking")
        order = (
            (await session.execute(select(SalesOrder).where(SalesOrder.id == order_id)))
            .scalars()
            .first()
        )
        if order is None:
            raise ResourceNotFound("Order tracking")
        if job.tracking_expires_at < datetime.now(timezone.utc):
            return {
                "state": "expired",
                "order": {"id": str(order.id), "order_number": order.order_number},
                "fulfilment": None,
            }
        state = "ok"
        if job.status == "failed":
            state = "failed"
        elif job.status == "cancelled":
            state = "cancelled"
        elif (
            job.status == "out_for_delivery"
            and job.updated_at
            and job.updated_at < datetime.now(timezone.utc) - timedelta(hours=6)
        ):
            state = "delayed"
        return {
            "order": {
                "id": str(order.id),
                "order_number": order.order_number,
                "status": order.status,
                "payment_status": order.payment_status,
                "payment_method": order.payment_method,
                "total_amount": float(order.total_amount),
                "currency": order.currency,
                "due_at": order.due_at.isoformat() if order.due_at else None,
                "due_words": await FulfilmentService._due_words(session, order),
            },
            "fulfilment": FulfilmentService.serialize_job(job, public=True),
            "state": state,
            "items": await FulfilmentService._public_items(session, order.id),
            "pickup": await FulfilmentService._pickup_place(session, order.location_id) if job.mode == "pickup" else None,
        }

    @staticmethod
    async def for_order(session: AsyncSession, business_id: uuid.UUID, order_id: uuid.UUID) -> dict[str, Any] | None:
        """How an order reaches its customer, for the Workspace order page: pickup or
        delivery, where it stands, and the delivery address in one line."""
        job = (await session.execute(select(FulfilmentJob).where(
            FulfilmentJob.business_id == business_id, FulfilmentJob.order_id == order_id))).scalars().first()
        if job is None:
            return None
        a = job.delivery_address if isinstance(job.delivery_address, dict) else {}
        keys = ("name", "line1", "line2", "line", "address_line", "street", "area", "locality", "landmark", "city",
                "postal_code", "pincode")
        parts = [str(a[k]).strip() for k in keys if isinstance(a.get(k), str) and str(a[k]).strip()]
        phone = a.get("phone") if isinstance(a.get("phone"), str) else None
        return {"id": str(job.id), "mode": job.mode, "status": job.status,
                "customer_status": CUSTOMER_FACING_STATUS.get(job.status, job.status),
                "address": ", ".join(dict.fromkeys(parts)) or None, "phone": phone,
                "delivery_charge": float(job.delivery_charge)}

    @staticmethod
    async def _public_items(session: AsyncSession, order_id: uuid.UUID) -> list[dict[str, Any]]:
        """What the customer ordered, as their tracking page lists it."""
        from platform_core.models import OrderLineItem

        rows = (await session.execute(select(OrderLineItem).where(OrderLineItem.order_id == order_id)
                                      .order_by(OrderLineItem.created_at))).scalars().all()
        return [{"title": r.title, "quantity": int(r.quantity), "line_total": float(r.line_total)} for r in rows]

    @staticmethod
    async def _pickup_place(session: AsyncSession, location_id: uuid.UUID) -> dict[str, Any] | None:
        """Where to collect it: the location's public address and phone (what the website shows)."""
        loc = await session.get(BusinessLocation, location_id)
        if loc is None:
            return None
        a = loc.address or {}
        keys = ("line1", "line2", "street", "area", "locality", "landmark", "city", "postal_code")
        parts = [str(a[k]).strip() for k in keys if isinstance(a.get(k), str) and str(a[k]).strip()]
        named = loc.name if loc.name and loc.name.lower() not in ("primary location", "main") else None
        if not parts and not named and not loc.phone:
            return None
        return {"name": named, "address": ", ".join(dict.fromkeys(parts)) or None, "phone": loc.phone}
