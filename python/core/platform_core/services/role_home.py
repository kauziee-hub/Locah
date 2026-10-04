"""Home answers the role's question (Business OS Guide §3 "Home should answer a
question, not display random cards"; Capability Universe §7.2; Build Spec §8).

Owner:        What needs me now? What is happening today? Is my business live?
Manager:      What is late, blocked or exceptional at my location?
Store keeper: What is low, what arrived?
Accountant:   Unpaid and due (sync status joins with the Tally connector, P4).

Every number is counted from real records, with the viewer's permissions and
location scope applied (the ORM location filter runs on these queries), and
every row links to the records behind it. Nothing is estimated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import (
    Booking,
    Business,
    BusinessMembership,
    CustomerContact,
    ComplianceItem,
    FulfilmentJob,
    InventoryMovement,
    Lead,
    MembershipEnrolment,
    Offering,
    PaymentAttempt,
    SalesOrder,
    Website,
)
from platform_core.permissions import ROLE_PRIMARY_OWNER
from platform_core.services import home_header

IST = ZoneInfo("Asia/Kolkata")
LIVE_ORDER = ("pending", "accepted", "preparing", "ready")
ENDED = ("cancelled", "rejected")


def _item(label: str, count: int, href: str, detail: str = "", tone: str = "warn") -> dict[str, Any]:
    return {"label": label, "count": count, "href": href, "detail": detail, "tone": tone}


def _rupees(amount: Decimal | float | int | None) -> str:
    """Whole rupees with Indian digit grouping (₹1,23,456)."""
    digits = str(int(Decimal(str(amount or 0)).quantize(Decimal("1"))))
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join([g for g in [head, *groups] if g] + [tail])


class RoleHomeService:
    @staticmethod
    async def role_key(session: AsyncSession, membership: BusinessMembership) -> str:
        if membership.role == ROLE_PRIMARY_OWNER:
            return "owner"
        key = membership.role_template or ""
        if key.startswith("custom:"):
            from sqlalchemy import text

            row = (await session.execute(
                text("SELECT based_on FROM business_custom_roles WHERE id = CAST(:id AS uuid)"), {"id": key[7:]},
            )).first()
            key = (row[0] if row else None) or ""
        return key if key in ("manager", "store_keeper", "accountant", "cashier", "provider",
                              "sales_executive", "dispatcher", "delivery_partner") else "member"

    @staticmethod
    async def compose(
        session: AsyncSession, business: Business, membership: BusinessMembership, permissions: frozenset[str],
        live_modules: set[str], *, now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        key = await RoleHomeService.role_key(session, membership)
        can = lambda perm, module=None: perm in permissions and (module is None or module in live_modules)  # noqa: E731
        ctx = _Ctx(session, business.id, now, can, key)
        from platform_core.authorization.role_templates import OWNER, ROLE_TEMPLATES
        from platform_core.services.workspace_projection import terms_for

        tpl = OWNER if key == "owner" else ROLE_TEMPLATES.get(key)
        question = tpl.home if tpl else "Your work today"
        if key == "manager":
            bands = [await ctx.late_or_stuck(), await ctx.today()]
        elif key == "store_keeper":
            bands = [await ctx.low_stock(), await ctx.arrived()]
        elif key == "accountant":
            bands = [await ctx.unpaid(), await ctx.due()]
        elif key == "cashier":
            bands = [await ctx.counter(membership.identity_id)]
        elif key == "provider":
            bands = [await ctx.my_day()]
        elif key == "sales_executive":
            bands = [await ctx.follow_ups()]
        elif key == "dispatcher":
            bands = [await ctx.dispatch_attention()]
        elif key == "delivery_partner":
            bands = [await ctx.my_next_drop()]
        else:
            bands = [await ctx.needs_you_now(), await ctx.today()]
            if key == "owner":
                bands.append(await ctx.your_business(business, live_modules))
        scoped = bool(membership.location_scope) and membership.role != ROLE_PRIMARY_OWNER
        return {
            "role": {"key": key, "label": tpl.label if tpl else "Team member", "question": question},
            "location_scoped": scoped,
            "header": await ctx.header(business),
            "quick_actions": home_header.quick_actions(can, (await terms_for(session, business)).get("offerings")),
            "bands": [b for b in bands if b is not None],
        }


class _Ctx:
    def __init__(self, session: AsyncSession, business_id: uuid.UUID, now: datetime, can: Any,
                 role_key: str) -> None:
        self.s, self.b, self.now, self.can, self.role_key = session, business_id, now, can, role_key
        local = now.astimezone(IST)
        self.day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        self.day_end = self.day_start + timedelta(days=1)

    async def header(self, business: Business) -> dict[str, Any]:
        """"Good morning, Nila Café" · Anna Nagar · Open now — from the primary location."""
        from platform_core.models import BusinessLocation

        loc = (await self.s.execute(select(BusinessLocation).where(
            BusinessLocation.business_id == self.b, BusinessLocation.status == "active",
            BusinessLocation.deleted_at.is_(None),
        ).order_by(BusinessLocation.is_primary.desc(), BusinessLocation.created_at).limit(1))).scalars().first()
        tz = IST.key  # a location still on the column default (UTC) is read as India time
        if loc and loc.timezone and loc.timezone != "UTC":
            tz = loc.timezone
        return {
            "greeting": home_header.greeting(self.now.astimezone(ZoneInfo(tz))),
            "name": business.display_name,
            "place": home_header.place(loc.name if loc else None, loc.address if loc else None),
            "location_id": str(loc.id) if loc else None,
            "open": home_header.open_state(loc.hours if loc else None, tz, self.now),
            "website": (await self.s.execute(select(Website.status).where(Website.business_id == self.b))).scalar()
            == "published",
        }

    async def _count(self, model: Any, *where: Any) -> int:
        return int((await self.s.execute(select(func.count()).select_from(model).where(*where))).scalar_one())

    async def _open_bills(self) -> list[dict[str, Any]]:
        """Issued bills with money still owed (Capability Universe §14), within the viewer's locations."""
        if not self.can("invoices.read", "invoicing"):
            return []
        from platform_core.services.invoicing import InvoiceService

        return list(await InvoiceService.list_documents(self.s, self.b, payment="unpaid", limit=500))

    async def _khata(self) -> dict[str, Any] | None:
        """Customer khata (Capability Universe §14.5): who owes, who is late, who is over their limit."""
        if not self.can("ledger.read", "ledger"):
            return None
        from platform_core.services.ledger import LedgerService

        data = await LedgerService.list_accounts(self.s, self.b, party_type="customer")
        rows = data["accounts"]
        return {"owing": [a for a in rows if a["balance"] > 0], "late": [a for a in rows if a["ageing"]["overdue"] > 0],
                "over": [a for a in rows if a["over_limit"]], "totals": data["totals"]}

    def _khata_items(self, k: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not k:
            return []
        items = []
        if k["late"]:
            items.append(_item("khata accounts past due", len(k["late"]), "/khata?due=1",
                               f"{_rupees(k['totals']['overdue'])} overdue", tone="bad"))
        if k["over"]:
            items.append(_item("khata accounts over their limit", len(k["over"]), "/khata",
                               ", ".join(a["display_name"] for a in k["over"][:3])))
        return items

    async def _chats_waiting(self) -> list[dict[str, Any]]:
        """WhatsApp chats waiting for a person over 10 minutes (Capability Universe §12.5)."""
        if not self.can("messaging.read", "messaging"):
            return []
        from platform_core.services.messaging import MessagingService

        n = await MessagingService.waiting_long(self.s, self.b)
        return [_item("customers waiting over 10 minutes on WhatsApp", n, "/inbox?view=waiting", tone="bad")] if n else []

    # ------------------------------------------------------------------ owner: needs you now
    async def needs_you_now(self) -> dict[str, Any]:
        items = []
        if self.can("orders.read", "orders"):
            n = await self._count(SalesOrder, SalesOrder.business_id == self.b, SalesOrder.deleted_at.is_(None),
                                  SalesOrder.status == "pending")
            if n:
                items.append(_item("orders waiting to be accepted", n, "/orders?status=pending", tone="bad"))
        if self.can("bookings.read", "bookings"):
            n = await self._count(Booking, Booking.business_id == self.b, Booking.deleted_at.is_(None),
                                  Booking.status == "pending", Booking.starts_at >= self.now - timedelta(hours=1))
            if n:
                items.append(_item("bookings to confirm", n, "/bookings?status=pending"))
        if self.can("payments.read", "payments"):
            n = await self._count(PaymentAttempt, PaymentAttempt.business_id == self.b,
                                  PaymentAttempt.deleted_at.is_(None), PaymentAttempt.status == "failed",
                                  PaymentAttempt.created_at >= self.now - timedelta(days=7))
            if n:
                items.append(_item("payments failed this week", n, "/payments", tone="bad"))
        if self.can("inventory.read", "inventory"):
            low = await self._low_rows()
            if low:
                items.append(_item("items low or out of stock", len(low), "/inventory?stock_status=low_stock",
                                   ", ".join(r["title"] for r in low[:3])))
        if self.can("customers.erase", "customer-relationships"):
            # DPDP (MD §25.1): a customer asked for their details to be deleted.
            from platform_core.customers.privacy import PrivacyRequests

            asks = [r for r in await PrivacyRequests.open_for(self.s, self.b) if r["kind"] == "erasure"]
            if asks:
                items.append(_item("customers asked you to delete their details", len(asks),
                                   f"/customers/{asks[0]['contact_id']}" if len(asks) == 1 else "/customers",
                                   ", ".join(str(r["display_name"]) for r in asks[:3]), tone="bad"))
        if self.can("offerings.update", "offerings-catalog"):
            # OK-15: items priced from a daily rate keep yesterday's price until today's is entered.
            from platform_core.pricing.formula import RateService

            stale = await RateService.not_entered_since(self.s, self.b, self.day_start)
            if stale:
                items.append(_item("rates to enter for today", len(stale), "/offerings/rates", ", ".join(stale[:3])))
        if self.can("leads.read", "leads"):
            n = await self._count(Lead, Lead.business_id == self.b, Lead.deleted_at.is_(None), Lead.status == "new")
            if n:
                items.append(_item("new enquiries to answer", n, "/leads?status=new"))
            due = await self._count(Lead, Lead.business_id == self.b, Lead.deleted_at.is_(None),
                                    Lead.status.notin_(("won", "lost")), Lead.next_follow_up_at < self.day_end)
            if due:
                items.append(_item("follow-ups due today", due, "/leads", tone="info"))
        if self.can("memberships.read", "memberships"):
            n = await self._count(MembershipEnrolment, MembershipEnrolment.business_id == self.b,
                                  MembershipEnrolment.deleted_at.is_(None), MembershipEnrolment.status == "active",
                                  MembershipEnrolment.ends_at >= self.now,
                                  MembershipEnrolment.ends_at < self.now + timedelta(days=7))
            if n:
                items.append(_item("memberships ending this week", n, "/memberships", tone="info"))
        if self.role_key == "owner" and self.can("reviews.reply", "reviews"):
            from platform_core.services.reviews import ReviewService

            low = await ReviewService.low_open(self.s, self.b)
            if low:
                contacts = {row.id: row for row in (await self.s.execute(select(CustomerContact).where(
                    CustomerContact.business_id == self.b,
                    CustomerContact.id.in_({r.customer_contact_id for r in low}),
                ))).scalars()}
                details = []
                for review in low[:3]:
                    contact = contacts.get(review.customer_contact_id)
                    if contact:
                        details.append(f"{contact.display_name} ({contact.phone})" if self.can(
                            "customers.read", "customer-relationships") and contact.phone else contact.display_name)
                items.append(_item("low reviews waiting for your reply", len(low), "/reviews?view=low",
                                   ", ".join(details), tone="bad"))
        if self.role_key == "owner" and self.can("compliance.read", "compliance"):
            today = self.now.astimezone(IST).date()
            due_items = list((await self.s.execute(select(ComplianceItem).where(
                ComplianceItem.business_id == self.b, ComplianceItem.status == "active",
                ComplianceItem.due_on <= today + timedelta(days=7),
            ).order_by(ComplianceItem.due_on).limit(100))).scalars())
            if due_items:
                items.append(_item("licences or filings needing attention", len(due_items), "/compliance",
                                   ", ".join(row.title for row in due_items[:3]), tone="bad"))
        late = [b for b in await self._open_bills() if b["overdue"]]
        if late:
            items.append(_item("bills past their due date", len(late), "/invoices?tab=overdue",
                               f"{_rupees(sum(b['outstanding'] for b in late))} owed", tone="bad"))
        items += self._khata_items(await self._khata())
        items = await self._chats_waiting() + items
        return {"key": "now", "title": "Needs you now", "items": items, "empty": "Nothing needs you right now."}

    # ------------------------------------------------------------------ provider / sales executive (P2-01)
    async def _names(self, contact_ids: set[Any]) -> dict[Any, str]:
        ids = {c for c in contact_ids if c}
        if not ids:
            return {}
        return {row[0]: row[1] for row in (await self.s.execute(select(CustomerContact.id, CustomerContact.display_name)
                .where(CustomerContact.business_id == self.b, CustomerContact.id.in_(ids)))).all()}

    async def my_day(self) -> dict[str, Any] | None:
        """A provider's day (§7.2 "My next appointment and my day"): today's appointments in order. The
        assignment scope limits the query to bookings where they are the provider."""
        if not self.can("bookings.read", "bookings"):
            return None
        rows = list((await self.s.execute(select(Booking).where(
            Booking.business_id == self.b, Booking.deleted_at.is_(None), Booking.status.notin_(ENDED),
            Booking.starts_at >= self.day_start, Booking.starts_at < self.day_end,
        ).order_by(Booking.starts_at).limit(40))).scalars())
        names = await self._names({r.customer_contact_id for r in rows})
        upcoming = next((r.id for r in rows if r.ends_at >= self.now), None)
        items = []
        for r in rows:
            when = r.starts_at.astimezone(IST).strftime("%I:%M %p").lstrip("0").lower()
            who = names.get(r.customer_contact_id, "")
            items.append(_item(r.title, 0, f"/bookings/{r.id}", " · ".join(x for x in (when, who) if x),
                               tone="bad" if r.id == upcoming else "info" if r.ends_at >= self.now else "good"))
        return {"key": "myday", "title": "My day", "items": items, "empty": "No appointments today."}

    async def follow_ups(self) -> dict[str, Any] | None:
        """A sales executive's follow-ups (§7.2 "Follow-ups due today"): their open enquiries due by the end of
        today, oldest first, then new ones — the assignment scope limits them to enquiries assigned to them."""
        if not self.can("leads.read", "leads"):
            return None
        due = list((await self.s.execute(select(Lead).where(
            Lead.business_id == self.b, Lead.deleted_at.is_(None), Lead.status.notin_(("won", "lost")),
            or_(Lead.next_follow_up_at < self.day_end, Lead.status == "new"),
        ).order_by(Lead.next_follow_up_at.asc().nulls_last(), Lead.created_at).limit(40))).scalars())
        items = []
        for lead in due:
            at = lead.next_follow_up_at
            when = (at.astimezone(IST).strftime("%I:%M %p").lstrip("0").lower() if at and at >= self.day_start
                    else at.astimezone(IST).strftime("%d %b") if at else "")
            late = at is not None and at < self.now
            items.append(_item(lead.display_name, 0, f"/leads/{lead.id}",
                               " · ".join(x for x in (when, lead.status) if x), tone="bad" if late else "info"))
        return {"key": "followups", "title": "Follow-ups due today", "items": items,
                "empty": "No follow-ups due today."}

    # ------------------------------------------------------------------ dispatch
    async def dispatch_attention(self) -> dict[str, Any] | None:
        """A dispatcher's home (§7.2 "Unassigned and late deliveries")."""
        if not self.can("dispatch.read", "dispatch"):
            return None
        from platform_core.dispatch.models import DispatchJob

        unassigned = await self._count(DispatchJob, DispatchJob.business_id == self.b, DispatchJob.status == "unassigned")
        failed = await self._count(DispatchJob, DispatchJob.business_id == self.b, DispatchJob.status == "failed")
        out = await self._count(
            DispatchJob, DispatchJob.business_id == self.b,
            DispatchJob.status.in_(("picked_up", "out_for_delivery")),
        )
        items = []
        if unassigned:
            items.append(_item("unassigned deliveries", unassigned, "/dispatch", tone="warn"))
        if failed:
            items.append(_item("deliveries that need attention", failed, "/dispatch", tone="bad"))
        if out:
            items.append(_item("out now", out, "/dispatch", tone="info"))
        return {"key": "dispatch", "title": "Unassigned and late deliveries", "items": items,
                "empty": "Nothing is waiting to be dispatched."}

    async def my_next_drop(self) -> dict[str, Any] | None:
        """A delivery partner's home (§7.2 "My next drop"). Assignment scope keeps it to their jobs."""
        if not self.can("dispatch.read", "dispatch"):
            return None
        from platform_core.dispatch.models import DispatchJob

        job = (await self.s.execute(select(DispatchJob).where(
            DispatchJob.business_id == self.b,
            DispatchJob.status.in_(("assigned", "picked_up", "out_for_delivery")),
        ).order_by(DispatchJob.planned_at.asc().nulls_last(), DispatchJob.created_at).limit(1))).scalars().first()
        if job is None:
            return {"key": "nextdrop", "title": "My next drop", "items": [], "empty": "No jobs assigned to you."}
        return {"key": "nextdrop", "title": "My next drop", "items": [
            _item(job.order_number, 0, "/crew", job.pickup_label or job.status, tone="bad"),
        ], "empty": ""}

    # ------------------------------------------------------------------ today
    async def today(self) -> dict[str, Any] | None:
        stats = []
        if self.can("orders.read", "orders"):
            row = (await self.s.execute(
                select(func.count(), func.coalesce(func.sum(SalesOrder.total_amount), 0)).select_from(SalesOrder)
                .where(SalesOrder.business_id == self.b, SalesOrder.deleted_at.is_(None),
                       SalesOrder.status.notin_(ENDED), SalesOrder.created_at >= self.day_start,
                       SalesOrder.created_at < self.day_end)
            )).one()
            stats.append({"label": "Order value today", "value": _rupees(row[1]), "href": "/orders",
                          "note": f"{int(row[0])} order{'s' if int(row[0]) != 1 else ''}"})
        if self.can("bookings.read", "bookings"):
            n = await self._count(Booking, Booking.business_id == self.b, Booking.deleted_at.is_(None),
                                  Booking.status.notin_(ENDED), Booking.starts_at >= self.day_start,
                                  Booking.starts_at < self.day_end)
            stats.append({"label": "Bookings today", "value": str(n), "href": "/bookings", "note": ""})
        if self.can("customers.read", "customer-relationships"):
            n = await self._count(CustomerContact, CustomerContact.business_id == self.b,
                                  CustomerContact.deleted_at.is_(None), CustomerContact.created_at >= self.day_start)
            stats.append({"label": "New customers today", "value": str(n), "href": "/customers", "note": ""})
        if not stats:
            return None
        return {"key": "today", "title": "Today", "stats": stats,
                "empty": "No activity yet today."}

    # ------------------------------------------------------------------ owner: your business
    async def your_business(self, business: Business, live: set[str]) -> dict[str, Any]:
        from platform_core.catalog.modules import MODULES, is_built
        from platform_core.services.module_readiness import readiness

        site = (await self.s.execute(select(Website.status).where(Website.business_id == self.b))).scalar()
        offerings = await self._count(Offering, Offering.business_id == self.b, Offering.deleted_at.is_(None))
        items = [] if offerings else [
            _item("Add what you sell", 0, "/offerings", "No products or services yet — customers need something to buy or book"),
        ]
        items += [
            _item("Website", 0, "/website", "Published" if site == "published" else "Not published yet",
                  "good" if site == "published" else "warn"),
            _item("Marketplace listing", 0, "/marketplace",
                  "Customers can find you" if business.visibility == "discoverable" and site == "published"
                  else "Not listed yet", "good" if business.visibility == "discoverable" else "info"),
        ]
        tools = sorted(m for m in live if not m.startswith("core-") and is_built(m) and m in MODULES)
        states = await readiness(self.s, self.b, tools) if tools else {}
        waiting = [MODULES[m].label for m in tools if states[m]["steps"] and not states[m]["configured"]]
        items.append(_item(
            "Tools", len(tools), "/modules",
            (f"{len(tools)} on · setup left in {', '.join(waiting[:3])}" if waiting else f"{len(tools)} on, all set up")
            if tools else "None switched on yet", "warn" if waiting else "good" if tools else "info"))
        return {"key": "business", "title": "Your business", "items": items, "empty": ""}

    # ------------------------------------------------------------------ manager
    async def late_or_stuck(self) -> dict[str, Any]:
        items = await self._chats_waiting()
        if self.can("orders.read", "orders"):
            n = await self._count(SalesOrder, SalesOrder.business_id == self.b, SalesOrder.deleted_at.is_(None),
                                  SalesOrder.status == "pending",
                                  SalesOrder.created_at < self.now - timedelta(minutes=30))
            if n:
                items.append(_item("orders waiting over 30 minutes", n, "/orders?status=pending", tone="bad"))
            n = await self._count(SalesOrder, SalesOrder.business_id == self.b, SalesOrder.deleted_at.is_(None),
                                  SalesOrder.status.in_(("accepted", "preparing", "ready")),
                                  SalesOrder.created_at < self.now - timedelta(hours=24))
            if n:
                items.append(_item("orders open for more than a day", n, "/orders"))
        if self.can("bookings.read", "bookings"):
            n = await self._count(Booking, Booking.business_id == self.b, Booking.deleted_at.is_(None),
                                  Booking.status == "confirmed", Booking.starts_at < self.now - timedelta(minutes=15),
                                  Booking.starts_at >= self.day_start)
            if n:
                items.append(_item("bookings started but not checked in", n, "/bookings"))
            n = await self._count(Booking, Booking.business_id == self.b, Booking.deleted_at.is_(None),
                                  Booking.status == "pending", Booking.starts_at >= self.now,
                                  Booking.starts_at < self.day_end)
            if n:
                items.append(_item("bookings today still unconfirmed", n, "/bookings?status=pending"))
        if self.can("fulfilment.read", "fulfilment"):
            n = await self._count(FulfilmentJob, FulfilmentJob.business_id == self.b,
                                  or_(and_(FulfilmentJob.status == "out_for_delivery",
                                           FulfilmentJob.updated_at < self.now - timedelta(hours=2)),
                                      and_(FulfilmentJob.status == "failed",
                                           FulfilmentJob.updated_at >= self.day_start)))
            if n:
                items.append(_item("deliveries stuck or failed today", n, "/fulfilment", tone="bad"))
        if self.can("inventory.read", "inventory"):
            low = await self._low_rows()
            if low:
                items.append(_item("items low or out of stock", len(low), "/inventory?stock_status=low_stock",
                                   ", ".join(r["title"] for r in low[:3])))
        return {"key": "late", "title": "Late or stuck", "items": items,
                "empty": "Nothing is late or stuck."}

    # ------------------------------------------------------------------ store keeper
    async def _low_rows(self) -> list[dict[str, Any]]:
        from platform_core.services.inventory import InventoryService

        rows = await InventoryService.list_for_business(self.s, self.b)
        low = [r for r in rows if r["stock_status"] in ("low_stock", "out_of_stock")]
        return [{"title": r["product_title"], "on_hand": r["quantity_on_hand"], "status": r["stock_status"],
                 "location_id": r.get("location_id")} for r in low]

    async def low_stock(self) -> dict[str, Any] | None:
        if not self.can("inventory.read", "inventory"):
            return None
        low = await self._low_rows()
        items = [_item(r["title"], int(r["on_hand"]), "/inventory?stock_status=low_stock",
                       "Out of stock" if r["status"] == "out_of_stock" else f"{r['on_hand']} left",
                       "bad" if r["status"] == "out_of_stock" else "warn") for r in low[:12]]
        return {"key": "low", "title": "What is low", "items": items, "empty": "Nothing is running low."}

    async def arrived(self) -> dict[str, Any] | None:
        if not self.can("inventory.read", "inventory"):
            return None
        rows = (await self.s.execute(
            select(Offering.title, InventoryMovement.quantity_delta, InventoryMovement.movement_type,
                   InventoryMovement.created_at)
            .join(Offering, Offering.id == InventoryMovement.offering_id)
            .where(InventoryMovement.business_id == self.b, InventoryMovement.quantity_delta > 0,
                   InventoryMovement.movement_type.in_(("receipt", "opening_stock", "adjustment")),
                   InventoryMovement.created_at >= self.now - timedelta(days=7))
            .order_by(InventoryMovement.created_at.desc()).limit(12)
        )).all()
        words = {"receipt": "Received", "opening_stock": "Opening stock", "adjustment": "Added"}
        items = [dict(_item(r[0], int(r[1]), "/inventory", f"{words[r[2]]} +{r[1]}", "good"), at=r[3].isoformat())
                 for r in rows]
        return {"key": "arrived", "title": "What arrived", "items": items, "empty": "Nothing arrived this week."}

    # ------------------------------------------------------------------ cashier
    async def counter(self, identity_id: uuid.UUID) -> dict[str, Any] | None:
        """Open shift, bills, drawer balance (§7.2) — at this person's locations."""
        if not self.can("pos.use", "pos"):
            return None
        from platform_core.models import InvoicingRegister, PosShift
        from platform_core.services.pos import PosService

        rows = (await self.s.execute(
            select(PosShift, InvoicingRegister.name).join(InvoicingRegister, InvoicingRegister.id == PosShift.register_id)
            .where(PosShift.business_id == self.b, PosShift.status == "open").order_by(PosShift.opened_at)
        )).all()
        stats = []
        for shift, name in rows:
            s = await PosService.summary(self.s, shift)
            mine = " (yours)" if shift.opened_by == identity_id else ""
            stats.append({"label": f"{name}{mine}", "value": _rupees(s["expected_cash"]), "href": "~/pos",
                          "note": f"in the drawer · {s['bills']} bills since "
                                  f"{shift.opened_at.astimezone(IST).strftime('%-I:%M %p')}"})
        if not stats:
            stats.append({"label": "No shift open", "value": "Open the counter", "href": "~/pos",
                          "note": "Count the drawer and open a shift to start billing"})
        return {"key": "counter", "title": "Your counter", "stats": stats, "empty": ""}

    # ------------------------------------------------------------------ accountant
    async def unpaid(self) -> dict[str, Any]:
        items = []
        if self.can("orders.read", "orders"):
            row = (await self.s.execute(
                select(func.count(), func.coalesce(func.sum(SalesOrder.total_amount), 0)).select_from(SalesOrder)
                .where(SalesOrder.business_id == self.b, SalesOrder.deleted_at.is_(None),
                       SalesOrder.status.notin_(ENDED),
                       SalesOrder.payment_status.in_(("pending", "pending_offline")))
            )).one()
            if int(row[0]):
                items.append(_item("orders not paid yet", int(row[0]), "/orders", f"{_rupees(row[1])} outstanding"))
        if self.can("payments.read", "payments"):
            n = await self._count(PaymentAttempt, PaymentAttempt.business_id == self.b,
                                  PaymentAttempt.deleted_at.is_(None), PaymentAttempt.status == "failed",
                                  PaymentAttempt.created_at >= self.now - timedelta(days=30))
            if n:
                items.append(_item("payments failed in the last 30 days", n, "/payments", tone="bad"))
            n = await self._count(PaymentAttempt, PaymentAttempt.business_id == self.b,
                                  PaymentAttempt.deleted_at.is_(None), PaymentAttempt.status == "pending_offline")
            if n:
                items.append(_item("cash or offline payments to confirm", n, "/payments", tone="info"))
        bills = await self._open_bills()
        if bills:
            items.append(_item("bills not fully paid", len(bills), "/invoices?tab=unpaid",
                               f"{_rupees(sum(b['outstanding'] for b in bills))} outstanding"))
        k = await self._khata()
        if k and k["owing"]:
            items.append(_item("customers owe on khata", len(k["owing"]), "/khata",
                               f"{_rupees(k['totals']['receivable'])} in all"))
        return {"key": "unpaid", "title": "Unpaid", "items": items, "empty": "Nothing is unpaid."}

    async def due(self) -> dict[str, Any] | None:
        late = [b for b in await self._open_bills() if b["overdue"]]
        khata = self._khata_items(await self._khata())
        if not self.can("memberships.read", "memberships"):
            if not self.can("invoices.read", "invoicing") and not khata:
                return None
            items = [_item("bills past their due date", len(late), "/invoices?tab=overdue",
                           f"{_rupees(sum(b['outstanding'] for b in late))} owed", tone="bad")] if late else []
            return {"key": "due", "title": "Due", "items": items + khata, "empty": "Nothing is due."}
        soon = await self._count(MembershipEnrolment, MembershipEnrolment.business_id == self.b,
                                 MembershipEnrolment.deleted_at.is_(None), MembershipEnrolment.status == "active",
                                 MembershipEnrolment.ends_at >= self.now,
                                 MembershipEnrolment.ends_at < self.now + timedelta(days=7))
        lapsed = await self._count(MembershipEnrolment, MembershipEnrolment.business_id == self.b,
                                   MembershipEnrolment.deleted_at.is_(None), MembershipEnrolment.status == "expired",
                                   MembershipEnrolment.ends_at >= self.now - timedelta(days=30))
        items = []
        if soon:
            items.append(_item("renewals due this week", soon, "/memberships", tone="info"))
        if lapsed:
            items.append(_item("memberships lapsed in the last 30 days", lapsed, "/memberships"))
        if late:
            items.append(_item("bills past their due date", len(late), "/invoices?tab=overdue",
                               f"{_rupees(sum(b['outstanding'] for b in late))} owed", tone="bad"))
        return {"key": "due", "title": "Due", "items": items + khata, "empty": "Nothing is due."}
