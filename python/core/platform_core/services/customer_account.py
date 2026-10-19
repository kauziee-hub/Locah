"""One LOCAH customer identity across every business (Founder §12–13; Guide §1).

A person signs in to LOCAH once. On any business's website they see their own
orders, bookings, bills, khata, quotes and memberships with *that* business;
in My Activity they see all businesses at once. Both read the same records the
business works from — no second customer truth.

Linking follows Doc 12: "Guest-to-authenticated linking: only through verified
identifier matching". `link_verified_customer_contacts()` (SECURITY DEFINER)
links only the calling identity, only on its verified email, only onto contacts
nobody has claimed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import (
    Booking,
    Business,
    CustomerContact,
    FulfilmentJob,
    InvoicingDocument,
    LedgerAccount,
    MembershipEnrolment,
    MembershipPlan,
    Offering,
    OrderLineItem,
    Quote,
    SalesOrder,
)
from platform_core.services.consumer_activity import ConsumerActivityService


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


async def bind_customer_context(session: AsyncSession, business_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    """A signed-in customer on one business's website: that business bound for
    its rows, the customer's identity bound so identity-checked functions
    (`my_contacts_in_business`) return only their own contacts."""
    await session.execute(text("SELECT set_config('app.current_business_id', :b, false)"), {"b": str(business_id)})
    await session.execute(text("SELECT set_config('app.current_identity_id', :i, false)"), {"i": str(identity_id)})


class CustomerAccountService:
    # ------------------------------------------------------------ linking
    @staticmethod
    async def link_verified(session: AsyncSession, identity_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Claim guest contacts carrying this identity's verified email, then
        write their past records into My Activity. Idempotent."""
        await session.execute(text("SELECT set_config('app.current_identity_id', :i, false)"),
                              {"i": str(identity_id)})
        linked = [(r[0], r[1]) for r in (await session.execute(
            text("SELECT business_id, contact_id FROM link_verified_customer_contacts()"))).all()]
        for business_id, contact_id in linked:
            await bind_customer_context(session, business_id, identity_id)
            await CustomerAccountService.project_contact(session, business_id, contact_id, identity_id)
        await session.execute(text("SELECT set_config('app.current_business_id', '', false)"))
        await session.execute(text("SELECT set_config('app.current_identity_id', :i, false)"),
                              {"i": str(identity_id)})
        return linked

    @staticmethod
    async def contact_for_identity(
        session: AsyncSession, *, business_id: uuid.UUID, identity_id: uuid.UUID, display_name: str,
        phone: str | None, actor_id: uuid.UUID, correlation_id: str,
    ) -> CustomerContact:
        """The signed-in customer's contact in this business: theirs already;
        or one carrying their *verified* email that nobody has claimed; or a new
        one linked to them. Never matched on name or an unverified phone."""
        from platform_core.exceptions import ConflictError
        from platform_core.models import PlatformIdentity
        from platform_core.services.customer import CustomerService

        base = select(CustomerContact).where(CustomerContact.business_id == business_id,
                                             CustomerContact.deleted_at.is_(None))
        mine = (await session.execute(base.where(CustomerContact.identity_id == identity_id))).scalars().first()
        if mine is not None:
            if phone and not mine.phone:
                mine.phone = phone
                await session.flush()
            return mine
        identity = await session.get(PlatformIdentity, identity_id)
        email = (identity.email or "").strip().lower() if identity else ""
        if identity is not None and identity.email_verified and email:
            found = (await session.execute(base.where(
                func.lower(CustomerContact.email) == email, CustomerContact.identity_id.is_(None)))).scalars().first()
            if found is not None:
                found.identity_id = identity_id
                await session.flush()
                return found
        payload = {"display_name": display_name or (identity.display_name if identity else None) or email,
                   "email": email or None, "phone": phone, "identity_id": str(identity_id)}
        try:
            async with session.begin_nested():
                return await CustomerService.create_customer(
                    session, business_id=business_id, actor_id=actor_id, correlation_id=correlation_id,
                    actor_context="signed_in_customer", payload=payload)
        except ConflictError:
            # Someone else's contact already uses that phone here: keep theirs,
            # make this customer's without it rather than merge on a guess.
            return await CustomerService.create_customer(
                session, business_id=business_id, actor_id=actor_id, correlation_id=correlation_id,
                actor_context="signed_in_customer", payload={**payload, "phone": None})

    # ------------------------------------------------------------ activity projection
    @staticmethod
    async def project_contact(session: AsyncSession, business_id: uuid.UUID, contact_id: uuid.UUID,
                              identity_id: uuid.UUID) -> int:
        """Write one My Activity row per order, bill, quote, membership and
        khata of a contact just linked to an identity."""
        written = 0
        orders = (await session.execute(select(SalesOrder).where(
            SalesOrder.business_id == business_id, SalesOrder.customer_contact_id == contact_id))).scalars()
        for order in orders:
            await CustomerAccountService.record_order(session, order, identity_id)
            written += 1
        docs = (await session.execute(select(InvoicingDocument).where(
            InvoicingDocument.business_id == business_id, InvoicingDocument.customer_contact_id == contact_id,
            InvoicingDocument.status.in_(("issued", "cancelled"))))).scalars()
        for doc in docs:
            await CustomerAccountService.record_bill(session, doc, identity_id)
            written += 1
        quotes = (await session.execute(select(Quote).where(
            Quote.business_id == business_id, Quote.customer_contact_id == contact_id,
            Quote.status.notin_(("draft",))))).scalars()
        for quote in quotes:
            await CustomerAccountService.record_quote(session, quote, identity_id)
            written += 1
        for enrolment in (await session.execute(select(MembershipEnrolment).where(
                MembershipEnrolment.business_id == business_id,
                MembershipEnrolment.customer_contact_id == contact_id))).scalars():
            await CustomerAccountService.record_membership(session, enrolment, identity_id)
            written += 1
        for booking in (await session.execute(select(Booking).where(
                Booking.business_id == business_id, Booking.customer_contact_id == contact_id))).scalars():
            await ConsumerActivityService.record(
                session, business_id=business_id, identity_id=identity_id, activity_type=f"booking.{booking.status}",
                resource_type="booking", resource_id=booking.id,
                summary={"booking_number": booking.booking_number, "label": booking.title, "status": booking.status,
                         "starts_at": booking.starts_at.isoformat(), "business_slug": await _slug(session, business_id)},
                occurred_at=booking.created_at)
            written += 1
        return written

    @staticmethod
    async def record_order(session: AsyncSession, order: SalesOrder, identity_id: uuid.UUID) -> None:
        count = len(list((await session.execute(select(OrderLineItem.id).where(
            OrderLineItem.order_id == order.id))).scalars()))
        job = (await session.execute(select(FulfilmentJob).where(FulfilmentJob.order_id == order.id))).scalars().first()
        await ConsumerActivityService.record(
            session, business_id=order.business_id, identity_id=identity_id, activity_type=f"order.{order.status}",
            resource_type="order", resource_id=order.id,
            summary={"order_number": order.order_number, "status": order.status, "total": _f(order.total_amount),
                     "items": count, "business_slug": await _slug(session, order.business_id),
                     "tracking_token": job.tracking_token if job else None,
                     "fulfilment": job.status if job else None},
            occurred_at=datetime.now(timezone.utc))

    @staticmethod
    async def record_bill(session: AsyncSession, doc: InvoicingDocument, identity_id: uuid.UUID) -> None:
        if doc.number is None:
            return
        await ConsumerActivityService.record(
            session, business_id=doc.business_id, identity_id=identity_id, activity_type=f"bill.{doc.status}",
            resource_type="bill", resource_id=doc.id,
            summary={"number": doc.number, "kind": doc.doc_kind, "status": doc.status,
                     "total": _f(doc.grand_total), "amount_due": _f(doc.amount_due),
                     "business_slug": await _slug(session, doc.business_id)},
            occurred_at=doc.issued_at or datetime.now(timezone.utc))

    @staticmethod
    async def record_quote(session: AsyncSession, quote: Quote, identity_id: uuid.UUID) -> None:
        await ConsumerActivityService.record(
            session, business_id=quote.business_id, identity_id=identity_id, activity_type=f"quote.{quote.status}",
            resource_type="quote", resource_id=quote.id,
            summary={"number": quote.quote_number, "label": quote.title, "status": quote.status,
                     "total": _f(quote.total), "business_slug": await _slug(session, quote.business_id)},
            occurred_at=datetime.now(timezone.utc))

    @staticmethod
    async def record_membership(session: AsyncSession, enrolment: MembershipEnrolment,
                                identity_id: uuid.UUID) -> None:
        plan = await session.get(MembershipPlan, enrolment.plan_id)
        await ConsumerActivityService.record(
            session, business_id=enrolment.business_id, identity_id=identity_id,
            activity_type=f"membership.{enrolment.status}", resource_type="membership", resource_id=enrolment.id,
            summary={"label": plan.name if plan else "Membership", "status": enrolment.status,
                     "starts_at": enrolment.starts_at.isoformat(),
                     "ends_at": enrolment.ends_at.isoformat() if enrolment.ends_at else None,
                     "business_slug": await _slug(session, enrolment.business_id)},
            occurred_at=datetime.now(timezone.utc))

    @staticmethod
    async def membership_view(session: AsyncSession, e: MembershipEnrolment, plan: MembershipPlan, *,
                              now: datetime) -> dict[str, Any]:
        """One relationship in the customer's own words (Founder refinement §23):
        valid until and days left, sessions left, the next instalment, tomorrow's
        delivery — and only the actions the business's rules allow now."""
        from platform_core.memberships.service import RENEWING_KINDS, MembershipCore
        from platform_core.memberships.subscriptions import SubscriptionService
        from platform_core.memberships.words import words

        st = await MembershipCore.state(session, e, plan, now=now)
        w = words(plan.plan_kind)
        item: dict[str, Any] = {
            "id": str(e.id), "plan": plan.name, "kind": plan.plan_kind, "title": w["customer_title"],
            "valid_label": w["valid"], "status": st.status, "starts_at": e.starts_at.isoformat(),
            "ends_at": st.valid_until.isoformat() if st.valid_until else (e.ends_at.isoformat() if e.ends_at else None),
            # The last day covered, in the business's days (ends_at is the instant after it).
            "last_day": st.last_day.isoformat() if st.last_day else None,
            "days_left": st.days_remaining if st.status in ("active", "paused", "grace") else None,
            "sessions_left": st.sessions_remaining, "outstanding": _f(st.outstanding), "paid": _f(st.paid),
            "next_due_on": st.next_due_on.isoformat() if st.next_due_on else None, "overdue": st.overdue,
            "good_standing": st.good_standing,
            "checkin_code": e.checkin_code if plan.plan_kind in ("access", "session_pack", "member_dues")
            and st.status in ("active", "grace") else None,
            "can_renew": plan.plan_kind in RENEWING_KINDS and plan.billing_timing == "prepaid"
            and st.status in ("active", "paused", "grace", "expired") and not st.renewed_ahead,
            "can_pay": st.outstanding > 0 and plan.billing_timing != "postpaid"
            and st.status not in ("cancelled", "completed"),
        }
        if plan.plan_kind == "fee_plan":
            nxt = next((i for i in await MembershipCore.instalments(session, e.id)
                        if i.status in ("due", "part_paid")), None)
            item["next_instalment"] = {"label": nxt.label, "amount": _f(Decimal(str(nxt.amount)) - Decimal(
                str(nxt.paid_amount))), "due_on": str(nxt.due_on)} if nxt else None
        if plan.plan_kind == "recurring_delivery" and e.delivery and st.status in ("active", "paused", "grace"):
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(await MembershipCore.tz(session, e.business_id, e.location_id))
            tomorrow = now.astimezone(zone).date() + timedelta(days=1)
            day = next((o for o in await SubscriptionService.plan_day(session, e.business_id, tomorrow)
                        if o.enrolment_id == e.id), None)
            item["tomorrow"] = {"date": str(tomorrow), "status": day.status if day else "no_delivery",
                                "quantity": float(day.quantity) if day else 0,
                                "cutoff": (e.delivery or {}).get("cutoff", "21:00"),
                                "open": not await SubscriptionService._cutoff_passed(session, e, tomorrow, now)}
        return item

    # ------------------------------------------------------------ one business's "My account"
    @staticmethod
    async def contacts(session: AsyncSession, business_id: uuid.UUID) -> list[uuid.UUID]:
        return [r[0] for r in (await session.execute(
            text("SELECT contact_id FROM my_contacts_in_business(:b)"), {"b": str(business_id)})).all()]

    @staticmethod
    async def account(session: AsyncSession, business: Business, identity_id: uuid.UUID) -> dict[str, Any]:
        """Everything this customer has with this business, newest first, each
        with the link the business already sends them (tracking, bill, khata
        statement, booking, quote) — derived here, never stored in the page."""
        from platform_core.services.invoicing import share_token
        from platform_core.services.ledger import _hash, statement_token

        await bind_customer_context(session, business.id, identity_id)
        mine = await CustomerAccountService.contacts(session, business.id)
        slug = business.slug
        out: dict[str, Any] = {"business": {"id": str(business.id), "slug": slug, "name": business.display_name},
                               "linked": bool(mine), "orders": [], "bookings": [], "bills": [], "quotes": [],
                               "memberships": [], "khata": None, "erasure_request": None}
        if not mine:
            return out
        now = datetime.now(timezone.utc)
        orders = list((await session.execute(select(SalesOrder).where(
            SalesOrder.business_id == business.id, SalesOrder.customer_contact_id.in_(mine))
            .order_by(SalesOrder.created_at.desc()).limit(20))).scalars())
        lines: dict[uuid.UUID, list[OrderLineItem]] = {}
        for line in (await session.execute(select(OrderLineItem).where(
                OrderLineItem.order_id.in_([o.id for o in orders])).order_by(OrderLineItem.sort_order))).scalars():
            lines.setdefault(line.order_id, []).append(line)
        jobs = {j.order_id: j for j in (await session.execute(select(FulfilmentJob).where(
            FulfilmentJob.order_id.in_([o.id for o in orders])))).scalars()}
        bills_by_order = {d.order_id: d for d in (await session.execute(select(InvoicingDocument).where(
            InvoicingDocument.order_id.in_([o.id for o in orders]), InvoicingDocument.status == "issued",
            InvoicingDocument.doc_kind.in_(("tax_invoice", "bill_of_supply", "bill"))))).scalars()}
        for o in orders:
            job = jobs.get(o.id)
            bill = bills_by_order.get(o.id)
            out["orders"].append({
                "id": str(o.id), "number": o.order_number, "status": o.status, "payment_status": o.payment_status,
                "total": _f(o.total_amount), "placed_at": o.created_at.isoformat(),
                "due_at": o.due_at.isoformat() if o.due_at else None,
                "due_words": await _due_words(session, o),
                "items": [{"title": li.title, "quantity": _f(li.quantity)} for li in lines.get(o.id, [])],
                "fulfilment": {"mode": job.mode, "status": job.status} if job else None,
                "track_url": f"/{slug}/track/{o.id}?token={job.tracking_token}" if job else None,
                "bill_url": f"/{slug}/bill/{share_token(business.id, bill.id)}" if bill else None,
                "can_reorder": o.status in ("completed", "cancelled", "rejected") or o.status == "delivered",
            })
        for b in (await session.execute(select(Booking).where(
                Booking.business_id == business.id, Booking.customer_contact_id.in_(mine))
                .order_by(Booking.starts_at.desc()).limit(20))).scalars():
            usable = b.management_token and (b.management_token_expires_at is None
                                              or b.management_token_expires_at > now)
            out["bookings"].append({
                "id": str(b.id), "number": b.booking_number, "title": b.title, "status": b.status,
                "starts_at": b.starts_at.isoformat(), "ends_at": b.ends_at.isoformat(),
                "upcoming": b.starts_at > now and b.status not in ("cancelled", "rejected", "no_show"),
                "manage_url": f"/{slug}/bookings/{b.id}?token={b.management_token}" if usable else None,
            })
        for d in (await session.execute(select(InvoicingDocument).where(
                InvoicingDocument.business_id == business.id, InvoicingDocument.customer_contact_id.in_(mine),
                InvoicingDocument.status.in_(("issued", "cancelled")), InvoicingDocument.number.is_not(None))
                .order_by(InvoicingDocument.issued_at.desc()).limit(30))).scalars():
            out["bills"].append({
                "id": str(d.id), "number": d.number, "kind": d.doc_kind, "status": d.status,
                "issue_date": d.issue_date.isoformat() if d.issue_date else None, "total": _f(d.grand_total),
                "amount_due": _f(d.amount_due) if d.status == "issued" else 0.0,
                "url": f"/{slug}/bill/{share_token(business.id, d.id)}",
            })
        for q in (await session.execute(select(Quote).where(
                Quote.business_id == business.id, Quote.customer_contact_id.in_(mine), Quote.deleted_at.is_(None),
                Quote.status.notin_(("draft",))).order_by(Quote.created_at.desc()).limit(20))).scalars():
            live = q.access_token and (q.access_token_expires_at is None or q.access_token_expires_at > now)
            out["quotes"].append({"id": str(q.id), "number": q.quote_number, "title": q.title, "status": q.status,
                                  "total": _f(q.total),
                                  "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                                  "url": f"/q/{q.access_token}" if live else None})
        from sqlalchemy import or_

        for e, plan in (await session.execute(select(MembershipEnrolment, MembershipPlan)
                        .join(MembershipPlan, MembershipPlan.id == MembershipEnrolment.plan_id)
                        .where(MembershipEnrolment.business_id == business.id,
                               or_(MembershipEnrolment.customer_contact_id.in_(mine),
                                   MembershipEnrolment.payer_contact_id.in_(mine)))
                        .order_by(MembershipEnrolment.starts_at.desc()).limit(10))).all():
            out["memberships"].append(await CustomerAccountService.membership_view(session, e, plan, now=now))
        acct = (await session.execute(select(LedgerAccount).where(
            LedgerAccount.business_id == business.id, LedgerAccount.customer_contact_id.in_(mine),
            LedgerAccount.party_type == "customer", LedgerAccount.status == "active"))).scalars().first()
        if acct is not None:
            token = statement_token(business.id, acct.id)
            if acct.public_token_hash != _hash(token):
                acct.public_token_hash = _hash(token)
                await session.flush()
            out["khata"] = {"balance": _f(acct.balance), "url": f"/{slug}/khata/{token}"}
        # DPDP (MD §25.1): their latest request to delete their details, and how it stands.
        ask = (await session.execute(text(
            "SELECT status, created_at, resolution_note FROM customer_relationships_privacy_requests "
            "WHERE business_id = CAST(:b AS uuid) AND contact_id = ANY(CAST(:ids AS uuid[])) AND kind = 'erasure' "
            "ORDER BY created_at DESC LIMIT 1"), {"b": str(business.id), "ids": [str(c) for c in mine]})).first()
        out["erasure_request"] = {"status": ask[0], "asked_at": ask[1].isoformat(), "reason": ask[2]} if ask else None
        return out

    # ------------------------------------------------------------ order again
    @staticmethod
    async def reorder(session: AsyncSession, business: Business, identity_id: uuid.UUID,
                      order_id: uuid.UUID) -> list[dict[str, Any]]:
        """The lines of one of the customer's orders as they could be bought
        now: today's catalogue price, and why a line cannot be (the item is no
        longer sold). The checkout prices again on the server anyway."""
        from platform_core.exceptions import ResourceNotFound
        from platform_core.services.offering_pricing import price_selection

        await bind_customer_context(session, business.id, identity_id)
        mine = await CustomerAccountService.contacts(session, business.id)
        order = await session.get(SalesOrder, order_id)
        if order is None or order.business_id != business.id or order.customer_contact_id not in mine:
            raise ResourceNotFound("Order")
        out: list[dict[str, Any]] = []
        for line in (await session.execute(select(OrderLineItem).where(
                OrderLineItem.order_id == order.id).order_by(OrderLineItem.sort_order))).scalars():
            offering = await session.get(Offering, line.offering_id)
            base = {"offering_id": str(line.offering_id), "variant_id": str(line.variant_id) if line.variant_id else None,
                    "title": line.title, "quantity": _f(line.quantity), "options": line.options or None}
            if offering is None or offering.deleted_at is not None or offering.status != "active" \
                    or offering.visibility != "public":
                out.append({**base, "available": False, "reason": "No longer sold"})
                continue
            try:
                from platform_core.models import OfferingVariant

                variant = await session.get(OfferingVariant, line.variant_id) if line.variant_id else None
                priced = price_selection(offering, variant, line.options or None)
                price: Decimal = priced.unit_price
            except Exception:  # noqa: BLE001 — a choice the catalogue no longer offers
                out.append({**base, "available": False, "reason": "That choice is no longer offered"})
                continue
            out.append({**base, "available": True, "unit_price": float(price),
                        "was_unit_price": _f(line.unit_price), "title": line.title})
        return out


async def _slug(session: AsyncSession, business_id: uuid.UUID) -> str | None:
    business = await session.get(Business, business_id)
    return business.slug if business else None


async def contact_identity(session: AsyncSession, contact_id: uuid.UUID | None) -> uuid.UUID | None:
    if contact_id is None:
        return None
    contact = await session.get(CustomerContact, contact_id)
    return contact.identity_id if contact is not None and contact.deleted_at is None else None


async def _due_words(session: AsyncSession, order: Any) -> str | None:
    """When a dated order is wanted, in the business's own time zone (P1-10D2)."""
    if order.due_at is None:
        return None
    from platform_core.models import BusinessLocation
    from platform_core.orders.preorder import when_words, zone_of

    words: str = when_words(order.due_at, zone_of(await session.get(BusinessLocation, order.location_id)))
    return words
