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
    return {
        "module": module_id,
        "label": info.label,
        "does": info.does,
        "customer_can": list(info.customer_can),
        "staff_can": list(info.staff_can),
        "status": status,
        "status_label": STATUS_WORDS[status],
        "enabled": bool(row.get("enabled")),
        "included": bool(row.get("entitled")),
        "steps": steps,
        "remaining": sum(1 for s in steps if not s["done"]) + len(blocked),
        "dependencies": [{
            "module": dep, "label": MODULES[dep].label if dep in MODULES else dep,
            "ready": bool(state.get("ready")), "enabled": bool(state.get("enabled")),
            "holding_back": dep in blocked, "href": f"/modules/{dep}",
        } for dep, state in deps.items()],
        "website": [SITE_WORDS[s] for s in info.site if s in SITE_WORDS],
        "home": HOMES.get(module_id),
    }
