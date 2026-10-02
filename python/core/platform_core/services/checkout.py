"""Public cart/checkout orchestration (WEB-007) — Doc 11 §17.4 / Doc 12 §11.2.

Coordinates OrderService + FulfilmentService + PaymentAttemptService in one transaction.
Does not modify Order/Payment/Inventory domain internals.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.context_resolver import bind_public_context
from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.models import (
    Business,
    MediaAsset,
    MerchantConnection,
    Offering,
    SalesOrder,
)
from platform_core.services.business import BusinessService
from platform_core.services.customer import CustomerService
from platform_core.services.fulfilment import FulfilmentService
from platform_core.services.location import LocationService
from platform_core.services.order import OrderService
from platform_core.services.payment_attempt import PaymentAttemptService


class CheckoutService:
    @staticmethod
    async def _resolve_business(session: AsyncSession, slug: str) -> Business:
        business = await BusinessService.get_by_slug(session, slug)
        if business is None or business.deleted_at is not None:
            raise ResourceNotFound("Business")
        # Guest request: bind the tenant GUC so subsequent RLS-scoped reads
        # (offerings, inventory, ...) resolve. Doc 11 §21.1 / AUD-02.
        await bind_public_context(session, business.id)
        return business

    @staticmethod
    async def _orders_active(session: AsyncSession, business_id: uuid.UUID) -> bool:
        """Orders switched on and entitled: every order path (website, WhatsApp,
        a phone order staff take) needs at least this."""
        from platform_core.services.module_readiness import module_operational

        return bool(await module_operational(session, business_id, "orders"))

    @staticmethod
    async def cod_rules(session: AsyncSession, business_id: uuid.UUID) -> dict[str, Any]:
        """Cash on delivery as the business set it (read-only; no settings row
        is created by a visitor)."""
        rules: dict[str, Any] = await FulfilmentService.payment_rules(session, business_id)
        return rules

    @staticmethod
    async def _assert_cod(session: AsyncSession, business_id: uuid.UUID, contact_id: uuid.UUID,
                          order_id: uuid.UUID, total: Decimal) -> None:
        rules = await CheckoutService.cod_rules(session, business_id)
        if not rules["on_delivery"]:
            raise ValidationError("Cash on delivery is not available — choose pickup",
                                  details={"code": "cod_off", "field": "payment_method"})
        cap = rules["first_order_cap"]
        if cap is None or total <= Decimal(str(cap)):
            return
        earlier = (await session.execute(select(func.count()).select_from(SalesOrder).where(
            SalesOrder.business_id == business_id, SalesOrder.customer_contact_id == contact_id,
            SalesOrder.id != order_id, SalesOrder.deleted_at.is_(None),
            SalesOrder.status.notin_(("cancelled", "rejected"))))).scalar_one()
        if not earlier:
            raise ValidationError(
                f"For a first order, cash on delivery is up to ₹{cap:,.0f}. Choose pickup, or order a little less.",
                details={"code": "cod_first_order_cap", "field": "payment_method", "cap": cap})

    @staticmethod
    async def list_public_offerings(
        session: AsyncSession, *, slug: str, limit: int = 100, location_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        business = await CheckoutService._resolve_business(session, slug)
        from platform_core.services.module_readiness import module_ready

        # The catalogue's public read contract: nothing is listed while the
        # catalogue module is not ready (switched off, not entitled, or empty).
        # Its records are kept, and return when it is switched on again.
        if not await module_ready(session, business.id, "offerings-catalog"):
            return {"business": {"id": str(business.id), "slug": business.slug,
                                 "display_name": business.display_name}, "offerings": []}
        rows = (
            await session.execute(
                select(Offering).where(
                    Offering.business_id == business.id,
                    Offering.deleted_at.is_(None),
                    Offering.status == "active",
                    Offering.visibility == "public",
                ).order_by(Offering.title.asc()).limit(limit)
            )
        ).scalars().all()
        # First image per Offering, resolved to a public URL. Scoped to this
        # Business so an Offering cannot surface another tenant's asset by
        # holding its id, the same rule the Website section resolver applies.
        wanted = {ids[0] for o in rows if (ids := list(o.image_asset_ids or []))}
        images: dict[str, str] = {}
        if wanted:
            assets = (
                await session.execute(
                    select(MediaAsset).where(
                        MediaAsset.id.in_(wanted),
                        MediaAsset.business_id == business.id,
                        MediaAsset.status == "ready",
                        MediaAsset.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            images = {str(a.id): a.public_url for a in assets if a.public_url}

        def _image_for(o: Offering) -> str | None:
            ids = list(o.image_asset_ids or [])
            return images.get(str(ids[0])) if ids else None

        from platform_core.services.offering_public import public_details

        details = await public_details(session, business.id, list(rows))
        # Inventory contributes availability, not a page (Doc 09 §10.7): one
        # word per tracked offering, through its own public read contract, and
        # only while Inventory is ready. Never a quantity.
        availability: dict[str, str] = {}
        if await module_ready(session, business.id, "inventory"):
            from platform_core.stock.public import public_availability

            availability = await public_availability(session, business.id, list(rows), location_id=location_id)
        return {
            "business": {
                "id": str(business.id),
                "slug": business.slug,
                "display_name": business.display_name,
            },
            "offerings": [
                {
                    "id": str(o.id),
                    "title": o.title,
                    "description": o.description,
                    "offering_type": o.offering_type,
                    "price_type": o.price_type,
                    "price_amount": float(o.price_amount) if o.price_amount is not None else None,
                    "currency": o.currency,
                    "image_url": _image_for(o),
                    "availability": availability.get(str(o.id)),
                    **details[str(o.id)],
                }
                for o in rows
            ],
        }

    @staticmethod
    async def checkout_options(session: AsyncSession, *, slug: str) -> dict[str, Any]:
        business = await CheckoutService._resolve_business(session, slug)
        locations = await LocationService.list_for_business(
            session, business.id, status="active"
        )
        modes = await FulfilmentService.active_modes(session, business.id)
        from platform_core.services.module_readiness import module_operational

        # Payments adds online collection to checkout; it is not a page (Doc 09
        # §10.8). Switched on is not enough without an Entitlement (§20.2).
        payments_active = await module_operational(session, business.id, "payments")
        merchant = (
            await session.execute(
                select(MerchantConnection).where(
                    MerchantConnection.business_id == business.id,
                    MerchantConnection.status == "active",
                ).limit(1)
            )
        ).scalars().first()
        payment_methods = ["cod"]
        if payments_active and merchant is not None:
            payment_methods.append("online")
        return {
            "business": {
                "id": str(business.id),
                "slug": business.slug,
                "display_name": business.display_name,
            },
            "fulfilment_modes": modes,
            "payment_methods": payment_methods,
            "cod": await CheckoutService.cod_rules(session, business.id),
            "locations": [
                {
                    "id": str(loc.id),
                    "name": loc.name,
                    "is_primary": loc.is_primary,
                    "address": loc.address,
                }
                for loc in locations
            ],
        }

    @staticmethod
    async def quote_delivery(
        session: AsyncSession, *, slug: str, address: dict[str, Any]
    ) -> dict[str, Any]:
        business = await CheckoutService._resolve_business(session, slug)
        modes = await FulfilmentService.active_modes(session, business.id)
        if "delivery" not in modes:
            raise ValidationError("Delivery is not available")
        zone, charge = await FulfilmentService.match_zone(
            session, business_id=business.id, address=address
        )
        if zone is None:
            return {"serviceable": False, "delivery_charge": 0, "zone": None}
        return {
            "serviceable": True,
            "delivery_charge": float(charge),
            "zone": FulfilmentService.serialize_zone(zone),
        }

    @staticmethod
    async def price_cart(session: AsyncSession, *, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
        """What the customer will pay, from the server (Founder: Orders — "the server
        is authoritative for price, tax, stock, availability, delivery charge and
        total"): every line priced from the catalogue with its choices, tax by the
        billing engine, the delivery charge for the address, the days a pre-order
        can be ready and the advance it asks. Nothing is created."""
        from platform_core.models import OrderLineItem
        from platform_core.orders import preorder as po
        from platform_core.services.invoicing_pricing import price_order
        from platform_core.services.order_calculation import calculate_order_totals
        from platform_core.services.offering_pricing import price_selection
        from platform_core.resolvers.order_resolver import OrderResolver
        from platform_core.models import OfferingVariant

        business = await CheckoutService._resolve_business(session, slug)
        items = payload.get("items") or []
        if not items:
            raise ValidationError("Cart is empty", details={"code": "empty_cart", "field": "items"})
        order_items = await CheckoutService._order_items(session, business, items)
        locations = await LocationService.list_for_business(session, business.id, status="active")
        location = next((loc for loc in locations if loc.is_primary), locations[0] if locations else None)
        if location is None:
            raise ValidationError("Business has no active location")
        lines: list[OrderLineItem] = []
        problems: list[dict[str, Any]] = []
        for raw in order_items:
            offering = (await session.execute(select(Offering).where(
                Offering.id == raw["offering_id"], Offering.business_id == business.id))).scalars().first()
            assert offering is not None
            variant = None
            if raw.get("variant_id"):
                variant = await session.get(OfferingVariant, uuid.UUID(str(raw["variant_id"])))
            priced = price_selection(offering, variant, raw.get("options"))
            title = offering.title + (f" — {variant.name}" if variant else "") + (
                f" — {priced.title_suffix}" if priced.title_suffix else "")
            qty = int(raw["quantity"])
            line = OrderLineItem(business_id=business.id, offering_id=offering.id, title=title,
                                 unit_price=float(priced.unit_price), quantity=qty,
                                 tax_rate=float(offering.tax_rate) if offering.tax_rate is not None else None,
                                 line_subtotal=float(priced.unit_price * qty), line_tax=0.0,
                                 line_total=float(priced.unit_price * qty), options=priced.options)
            lines.append(line)
            if offering.track_inventory:
                from platform_core.models import InventoryRecord

                record = (await session.execute(select(InventoryRecord).where(
                    InventoryRecord.business_id == business.id, InventoryRecord.offering_id == offering.id,
                    InventoryRecord.location_id == location.id, InventoryRecord.owner_customer_id.is_(None),
                    InventoryRecord.variant_id == variant.id if variant else InventoryRecord.variant_id.is_(None),
                ))).scalars().first()
                free = max((record.quantity_on_hand - record.quantity_reserved) if record else 0, 0)
                need = qty * max(int(priced.stock_per_unit or 1), 1)
                if need > free:
                    can = free // max(int(priced.stock_per_unit or 1), 1)
                    problems.append({"offering_id": str(offering.id), "title": title, "available": can,
                                     "message": f"only {can} left" if can else "out of stock"})
        order = SalesOrder(business_id=business.id, location_id=location.id, currency="INR")
        mode = str(payload.get("fulfilment_mode") or "")
        address = payload.get("delivery_address") if mode == "delivery" else None
        pos = (str(address.get("state_code") or "").strip() or None) if isinstance(address, dict) else None
        if not await price_order(session, business_id=business.id, order=order, lines=lines, discount=Decimal("0"),
                                 place_of_supply=pos):
            totals = calculate_order_totals([OrderResolver.serialize_line_item(i) for i in lines],
                                            discount_amount=Decimal("0"))
            order.total_amount = float(totals["total_amount"])
            order.tax_amount = float(totals["tax_amount"])
        delivery = None
        if mode == "delivery" and isinstance(address, dict) and (address.get("postal_code") or address.get("city")):
            zone, charge = await FulfilmentService.match_zone(session, business_id=business.id, address=address)
            delivery = {"serviceable": zone is not None, "charge": float(charge) if zone is not None else None}
        zone_tz = po.zone_of(location)
        plan_lines = await po.lines_for(session, business.id, [
            (i.offering_id, i.quantity, Decimal(str(i.line_total))) for i in lines])
        due_error = None
        try:
            wanted = po.parse_requested(payload.get("due"), zone_tz)
            plan = await po.plan(session, business_id=business.id, location=location, lines=plan_lines,
                                 requested=wanted, require=False)
        except ValidationError as exc:
            due_error = str((exc.detail or {}).get("message")) if isinstance(exc.detail, dict) else str(exc)
            plan = await po.plan(session, business_id=business.id, location=location, lines=plan_lines, require=False)
        charge = Decimal(str(delivery["charge"])) if delivery and delivery["charge"] else Decimal("0")
        return {
            "lines": [{"offering_id": str(i.offering_id), "title": i.title, "quantity": i.quantity,
                       "unit_price": float(i.unit_price), "line_total": float(i.line_total)} for i in lines],
            "tax_amount": float(order.tax_amount or 0),
            "tax_included": bool((order.tax_basis or {}).get("inclusive")),
            "items_total": float(order.total_amount),
            "delivery": delivery,
            "total": float(Decimal(str(order.total_amount)) + charge),
            "problems": problems,
            "preorder": plan.public(zone_tz),
            "due_error": due_error,
            "cod": await CheckoutService.cod_rules(session, business.id),
        }

    @staticmethod
    async def place_order(
        session: AsyncSession,
        *,
        slug: str,
        correlation_id: str,
        payload: dict[str, Any],
        identity_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """The website's checkout: a guest with a name and email, or a signed-in
        LOCAH customer whose order joins their own record (Founder §12)."""
        business = await CheckoutService._resolve_business(session, slug)
        from platform_core.services.module_readiness import module_operational, module_ready

        # A website checkout is a customer action on catalogue items: Orders
        # switched on and entitled, and the catalogue's public read contract
        # ready. Switching either off stops new checkouts at once (Doc 08 §7.4);
        # the orders already placed are untouched.
        if not (await module_operational(session, business.id, "orders")
                and await module_ready(session, business.id, "offerings-catalog")):
            raise ValidationError("Orders are not available on this website right now",
                                  details={"code": "orders_unavailable"})
        guest = payload.get("guest") or {}
        display_name = str(guest.get("name") or "").strip()
        email = str(guest.get("email") or "").strip().lower()
        phone = (str(guest.get("phone")).strip() if guest.get("phone") else None) or None
        if identity_id is not None:
            from platform_core.services.customer_account import CustomerAccountService

            contact = await CustomerAccountService.contact_for_identity(
                session, business_id=business.id, identity_id=identity_id, display_name=display_name,
                phone=phone, actor_id=business.primary_owner_identity_id, correlation_id=correlation_id)
            return await CheckoutService.place_for_contact(
                session, business=business, contact=contact, correlation_id=correlation_id,
                payload={**payload, "channel": "web"})
        if not display_name or not email:
            raise ValidationError(
                "Guest name and email are required",
                details={"field": "guest"},
            )

        # Doc 05 Part 7.1: a guest checkout is bounded to the transaction and
        # never becomes a Platform Identity. Customer attribution is the
        # business-scoped CustomerContact; audit/actor attribution is the
        # storefront owner acting in a guest-checkout context.
        actor_id = business.primary_owner_identity_id
        contact = await CustomerService.find_or_create_contact(
            session,
            business_id=business.id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            actor_context="guest_checkout",
            display_name=display_name,
            email=email,
            phone=phone,
        )

        return await CheckoutService.place_for_contact(
            session, business=business, contact=contact, correlation_id=correlation_id,
            payload={**payload, "channel": "web"})

    @staticmethod
    async def _order_items(session: AsyncSession, business: Business, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Cart lines checked against the catalogue (active, sold through a cart);
        prices are never taken from the customer."""
        order_items: list[dict[str, Any]] = []
        for raw in items:
            offering_id = uuid.UUID(str(raw["offering_id"]))
            offering = (
                await session.execute(
                    select(Offering).where(
                        Offering.id == offering_id,
                        Offering.business_id == business.id,
                        Offering.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if offering is None or offering.status != "active":
                raise ValidationError(
                    "Cart contains an invalid item",
                    details={"code": "invalid_item", "offering_id": str(offering_id)},
                )
            from platform_core.catalog.offering_kinds import KINDS

            kind = KINDS.get(offering.offering_type)
            if kind is not None and kind.flow not in ("cart", "give"):
                # Customers book services and rooms, and enquire about homes or
                # vehicles; only goods, food, packages and gifts go in a cart.
                raise ValidationError(
                    f"{offering.title} is {'booked' if kind.flow == 'booking' else 'enquired about'}, not added to a cart",
                    details={"code": "not_orderable", "offering_id": str(offering_id)},
                )
            order_items.append(
                {
                    "offering_id": offering_id,
                    "variant_id": raw.get("variant_id"),
                    "quantity": int(raw.get("quantity") or 1),
                    # What was chosen (pack, cut, add-ons, a gift amount) —
                    # priced by the server from the catalogue.
                    "options": raw.get("options") or {},
                    # Never the customer's number: the price comes from the
                    # catalogue (Capability Universe §12.6 "cart price =
                    # catalogue price"). Any unit_price sent is ignored.
                }
            )

        return order_items

    @staticmethod
    async def place_for_contact(
        session: AsyncSession,
        *,
        business: Business,
        contact: Any,
        correlation_id: str,
        payload: dict[str, Any],
        actor_context: str = "guest_checkout",
        actor_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """One order path for every channel (website, WhatsApp, a phone order taken
        by staff): priced from the catalogue, fulfilment job, payment attempt
        (Capability Universe §12). The actor is the staff member when one took
        it, otherwise the business's owner acting for the customer."""
        actor_id = actor_id or business.primary_owner_identity_id
        if not await CheckoutService._orders_active(session, business.id):
            # Auto-enable is not allowed; require module. For First Launch retail types
            # orders is on the plan — Business must enable. Fallback: if entitled core
            # path missing, still allow when orders module state absent but plan includes
            # it by enabling check soft — keep strict.
            raise ValidationError("Orders are not enabled for this Business")

        items = payload.get("items") or []
        if not items:
            raise ValidationError(
                "Cart is empty",
                details={"code": "empty_cart", "field": "items"},
            )

        mode = str(payload.get("fulfilment_mode") or "").strip()
        payment_method = str(payload.get("payment_method") or "cod").strip()
        location_id = payload.get("location_id")
        if not location_id:
            locations = await LocationService.list_for_business(
                session, business.id, status="active"
            )
            primary = next((loc for loc in locations if loc.is_primary), locations[0] if locations else None)
            if primary is None:
                raise ValidationError("Business has no active location")
            location_id = primary.id
        else:
            location_id = uuid.UUID(str(location_id))

        modes = await FulfilmentService.active_modes(session, business.id)
        from platform_core.services.module_readiness import module_operational

        # Payments adds online collection to checkout; it is not a page (Doc 09
        # §10.8). Switched on is not enough without an Entitlement (§20.2).
        payments_active = await module_operational(session, business.id, "payments")
        merchant = (
            await session.execute(
                select(MerchantConnection).where(
                    MerchantConnection.business_id == business.id,
                    MerchantConnection.status == "active",
                ).limit(1)
            )
        ).scalars().first()
        payment_methods = ["cod"]
        if payments_active and merchant is not None:
            payment_methods.append("online")
        if mode not in modes:
            raise ValidationError(
                "Selected fulfilment mode is not available",
                details={"mode": mode, "active_modes": modes},
            )
        if payment_method not in payment_methods:
            raise ValidationError(
                "Selected payment method is not available",
                details={"payment_method": payment_method},
            )

        order_items = await CheckoutService._order_items(session, business, items)

        delivery_address = payload.get("delivery_address")
        delivery_charge = Decimal("0")
        delivery_fee_offering_id = None
        if mode == "delivery":
            if not isinstance(delivery_address, dict):
                raise ValidationError("Delivery address is required")
            zone, delivery_charge = await FulfilmentService.match_zone(
                session, business_id=business.id, address=delivery_address
            )
            if zone is None:
                raise ValidationError("Address is outside configured delivery zones")
            delivery_fee_offering_id = await FulfilmentService._ensure_delivery_fee_offering(
                session, business_id=business.id
            )
            if delivery_charge > 0:
                order_items.append(
                    {
                        "offering_id": delivery_fee_offering_id,
                        "quantity": 1,
                        "unit_price": float(delivery_charge),
                    }
                )

        idempotency_key = payload.get("idempotency_key") or str(uuid.uuid4())
        order = await OrderService.create_order(
            session,
            business_id=business.id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            actor_context=actor_context,
            payload={
                "channel": payload.get("channel"),
                "location_id": location_id,
                "customer_contact_id": contact.id,
                "payment_method": payment_method,
                "currency": payload.get("currency") or "INR",
                "idempotency_key": idempotency_key,
                "items": order_items,
                # When it is wanted (dated pre-orders): checked against the items' rules.
                "due": payload.get("due"),
                # GST place of supply: where delivered goods go (§14.4).
                "place_of_supply": (
                    str(delivery_address.get("state_code") or "").strip() or None
                    if mode == "delivery" and isinstance(delivery_address, dict) else None
                ),
            },
        )

        if payment_method == "cod" and mode == "delivery":
            # The same cash-on-delivery rule as WhatsApp orders (§12.4, PY-07):
            # off entirely, or capped for a customer's first order.
            await CheckoutService._assert_cod(session, business.id, contact.id, order.id,
                                              Decimal(str(order.total_amount)))

        # Idempotent re-entry: ensure job exists for this order.
        job = await FulfilmentService.create_job_for_order(
            session,
            business_id=business.id,
            order=order,
            actor_id=actor_id,
            correlation_id=correlation_id,
            mode=mode,
            delivery_address=delivery_address if mode == "delivery" else None,
        )

        payment_data = None
        payment_state = "order_pending"
        if payment_method == "online":
            try:
                payment = await PaymentAttemptService.create_attempt(
                    session,
                    business_id=business.id,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    payload={
                        "source_type": "order",
                        "source_id": str(order.id),
                        "amount": float(order.total_amount),
                        "currency": order.currency,
                        "payment_method": "online",
                        "customer_contact_id": str(contact.id),
                        "idempotency_key": f"pay-{idempotency_key}",
                    },
                )
                payment_data = PaymentAttemptService.serialize(payment)
                payment_state = (
                    "payment_failed" if payment.status == "failed" else payment.status
                )
            except Exception as exc:  # noqa: BLE001
                payment_state = "payment_failed"
                payment_data = {"error": str(exc)}
        else:
            payment = await PaymentAttemptService.create_attempt(
                session,
                business_id=business.id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "source_type": "order",
                    "source_id": str(order.id),
                    "amount": float(order.total_amount),
                    "currency": order.currency,
                    "payment_method": "cod",
                    "customer_contact_id": str(contact.id),
                    "idempotency_key": f"pay-{idempotency_key}",
                },
            )
            payment_data = PaymentAttemptService.serialize(payment)
            payment_state = payment.status

        advance = None
        if order.advance_amount and Decimal(str(order.advance_amount)) > 0:
            # The advance a pre-order asks (§5 advance, §6 website): a payment link on
            # this order — paid by UPI to the business or, once activated, online.
            from platform_core.orders.preorder import when_words, zone_of
            from platform_core.models import BusinessLocation
            from platform_core.services.payment_collect import PaymentCollectService
            from platform_core.site_urls import business_site_url

            location = await session.get(BusinessLocation, order.location_id)
            note = f"Advance for {when_words(order.due_at, zone_of(location))}" if order.due_at else None
            req, token = await PaymentCollectService.create_request(
                session, business.id, actor_id, source_type="order", source_id=order.id,
                amount=order.advance_amount, purpose="advance", note=note, correlation_id=correlation_id)
            advance = {"amount": float(req.amount), "request_id": str(req.id), "path": f"/{business.slug}/pay/{token}",
                       "url": business_site_url(business.slug, f"/pay/{token}")}

        order_detail = await OrderService.serialize_order_with_items(session, order)
        tracking_path = (
            f"/{business.slug}/track/{order.id}?token={job.tracking_token}"
        )
        return {
            "state": payment_state if payment_state != "processing" else "order_pending",
            "order": order_detail,
            "fulfilment": FulfilmentService.serialize_job(job),
            "payment": payment_data,
            "tracking": {
                "order_id": str(order.id),
                "token": job.tracking_token,
                "href": tracking_path,
            },
            "confirmation": {
                "order_number": order.order_number,
                "grand_total": float(order.total_amount),
                "currency": order.currency,
                "fulfilment_mode": mode,
                "due_at": order.due_at.isoformat() if order.due_at else None,
            },
            "advance": advance,
        }
