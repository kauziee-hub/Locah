"""One tool's setup, in words: "why isn't this working yet?" (Doc 05 §12.2, NAV-008;
Doc 09 CORE-014).

Module readiness already knows which setup steps are true in the Business's
real data. This turns it into what a module page shows: a plain status, each
step with where to do it, what is still holding it back (a step, another tool,
the plan), and what it adds for customers once it works. Read-only.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.catalog.modules import MODULES
from platform_core.exceptions import ResourceNotFound

# Where each setup step is done in the Workspace (relative to /b/{id}).
STEP_ACTIONS: dict[str, tuple[str, str]] = {
    "offering_live": ("/offerings/new", "Add an item"),
    "priced_product": ("/offerings", "Price an item"),
    "payment_method": ("/payments", "Choose how customers pay"),
    "stock_recorded": ("/inventory", "Record stock"),
    "fulfilment_mode": ("/fulfilment", "Turn on pickup or delivery"),
    "bookable_offering": ("/offerings/new", "Add something people can book"),
    "plan_live": ("/memberships", "Publish a plan"),
    "provider_added": ("/workforce", "Add a staff member"),
    "tax_profile": ("/settings/invoicing", "Set up billing"),
    "register_created": ("/settings/counter", "Create a register"),
    "channel_connected": ("/whatsapp", "Connect WhatsApp"),
}
# Where a working tool is used day to day.
HOMES: dict[str, str] = {
    "offerings-catalog": "/offerings", "orders": "/orders", "payments": "/payments", "inventory": "/inventory",
    "fulfilment": "/fulfilment", "bookings": "/bookings", "memberships": "/memberships",
    "workforce": "/workforce", "customer-relationships": "/customers", "leads": "/leads", "quotes": "/quotes",
    "projects": "/projects", "invoicing": "/invoices", "ledger": "/khata", "messaging": "/whatsapp",
    "reviews": "/reviews", "compliance": "/compliance", "dispatch": "/dispatch", "queue-operations": "/queue",
    "tasks": "/tasks", "attendance": "/attendance", "kitchen": "/kitchen", "marketing": "/marketing",
    "loyalty": "/loyalty", "ai-employees": "/ai-employees", "expenses": "/expenses", "procurement": "/buying",
    "recipes": "/recipes", "jobs": "/jobs", "academics": "/academics", "documents": "/documents",
    "donations": "/donations", "pos": "/pos/shifts",
}
STATUS_WORDS = {
    "not_enabled": "Not switched on",
    "deactivated": "Switched off — your records are kept",
    "restricted": "Not included in your plan",
    "waiting": "Waiting on another tool",
    "setup_required": "Setup required",
    "partial": "Partly set up",
    "ready": "Working",
    "unavailable": "Not available yet",
}


def _status(row: dict[str, Any]) -> str:
    if not row.get("built"):
        return "unavailable"
    if not row.get("enabled"):
        return "deactivated" if row.get("state") == "deactivated" else "not_enabled"
    if not row.get("entitled"):
        return "restricted"
    if row.get("ready"):
        return "ready"
    steps = row.get("steps") or []
    if steps and all(s["done"] for s in steps) and row.get("blocked_by"):
        return "waiting"
    if any(s["done"] for s in steps):
        return "partial"
    return "setup_required" if steps else ("waiting" if row.get("blocked_by") else "ready")


async def setup(session: AsyncSession, business_id: uuid.UUID, module_id: str) -> dict[str, Any]:
    from platform_core.services.module_readiness import readiness
    from platform_core.services.module_recommendations import SITE_WORDS

    info = MODULES.get(module_id)
    if info is None or info.future:
        raise ResourceNotFound("Tool")
    row = (await readiness(session, business_id, modules=(module_id,)))[module_id]
    deps = await readiness(session, business_id, modules=info.depends_on) if info.depends_on else {}
    status = _status(row)
    steps = [{
        "key": s["key"], "label": s["label"], "done": bool(s["done"]),
        "action": None if s["done"] or s["key"] not in STEP_ACTIONS else
        {"label": STEP_ACTIONS[s["key"]][1], "href": STEP_ACTIONS[s["key"]][0]},
    } for s in row.get("steps") or []]
    blocked = set(row.get("blocked_by") or [])
    tips: list[dict[str, str]] = []
    if module_id == "bookings" and not await _hours_saved(session, business_id):
        # Not a setup step (classes and staff schedules carry their own times),
        # but without hours an appointment has no times to offer.
        tips.append({"text": "No opening hours are saved, so customers type the time they want and you check it. "
                             "Save your hours and they pick from times that are really free.",
                     "label": "Set opening hours", "href": "/locations"})
    customer_can = list(info.customer_can)
    status_label = STATUS_WORDS[status]
    ready_note = None
    if module_id == "payments" and not await _online_payments_active(session, business_id):
        # Paying at the business works without a provider; paying online does
        # not. "Working — customers can use it" over "Pay online" read as if
        # online payment were live with no provider connected (owner lab, salon).
        customer_can = ["Pay at your place or on delivery — you record it"]
        if status == "ready":
            status_label = "Working — payments at your place only"
            ready_note = ("Customers pay at your place or on delivery, and you record it here. "
                          "Online payments are not connected yet.")
        tips.append({"text": "Online payments are not connected, so nobody is asked to pay online. "
                             "Connect your Razorpay account to take payments on the website.",
                     "label": "Connect online payments", "href": "/payments"})
    website = [SITE_WORDS[w] for w in info.site if w in SITE_WORDS]
    if module_id == "memberships" and not await _enquiries_ready(session, business_id):
        # Asking to join on the website is an enquiry; without Enquiries the
        # website's "Ask to join" can only call the business (owner lab, gym:
        # "Working — customers can use it (… joining online …)" while every
        # request was refused).
        customer_can = ["See your plans and call or WhatsApp you to join", "See their membership and renew"]
        website = [w for w in website if w != SITE_WORDS.get("join")]
        if status == "ready":
            status_label = "Working — joining by phone only"
            ready_note = ("Your plans are on your website; people call or WhatsApp you to join. "
                          "Turn on Enquiries to let them ask to join on the website.")
        tips.append({"text": "People can only call or WhatsApp you to join. Turn on Enquiries to take join "
                             "requests on your website.", "label": "Turn on Enquiries", "href": "/modules/leads"})
    return {
        "module": module_id,
        "label": info.label,
        "does": info.does,
        "customer_can": customer_can,
        "staff_can": list(info.staff_can),
        "status": status,
        "status_label": status_label,
        # What "working" means for this tool right now, when it is narrower than
        # "customers can use it" (None: the plain words fit).
        "ready_note": ready_note,
        "enabled": bool(row.get("enabled")),
        "included": bool(row.get("entitled")),
        "steps": steps,
        "remaining": sum(1 for s in steps if not s["done"]) + len(blocked),
        "dependencies": [{
            "module": dep, "label": MODULES[dep].label if dep in MODULES else dep,
            "ready": bool(state.get("ready")), "enabled": bool(state.get("enabled")),
            "holding_back": dep in blocked, "href": f"/modules/{dep}",
        } for dep, state in deps.items()],
        "website": website,
        "home": HOMES.get(module_id),
        "tips": tips,
    }


async def _enquiries_ready(session: AsyncSession, business_id: uuid.UUID) -> bool:
    """Enquiries (leads) can take a request from the website."""
    from platform_core.services.module_readiness import module_ready

    return bool(await module_ready(session, business_id, "leads"))


async def _online_payments_active(session: AsyncSession, business_id: uuid.UUID) -> bool:
    """A verified payment provider account (Razorpay) the business connected."""
    from sqlalchemy import select

    from platform_core.models import MerchantConnection

    rows = (await session.execute(select(MerchantConnection.status).where(
        MerchantConnection.business_id == business_id))).scalars().all()
    return "active" in rows


async def _hours_saved(session: AsyncSession, business_id: uuid.UUID) -> bool:
    from sqlalchemy import select

    from platform_core.models import BusinessLocation

    rows = (await session.execute(select(BusinessLocation.hours).where(
        BusinessLocation.business_id == business_id, BusinessLocation.deleted_at.is_(None),
        BusinessLocation.status == "active"))).scalars().all()
    return any(isinstance(h, dict) and any(h.values()) for h in rows)
