"""Is a module actually ready to show customers? (Business OS Guide §4, Founder §50)

Entitled, enabled, configured, ready and permitted are five different things:

* **entitled** — the Business may commercially use it (Doc 08 §3). A stale
  activation row never stands in for an Entitlement (Doc 08 §20.2, §24.2).
* **enabled** — the owner switched the module on (business_module_states).
* **configured** — the setup steps in the module catalogue are true in the
  business's real data (a priced product exists, a plan is published...).
  Computed here, never stored, so it cannot go stale.
* **ready** — all of the above, and every *hard* dependency is itself ready
  (Doc 08 §9.2 rule 4): Orders sells catalogue items, so Orders is not ready
  while the catalogue is off.
* **permitted** — a particular person may use it; that is the permission engine.

Surfaces (website, Marketplace, WhatsApp, the Workspace navigation) expose a
module's customer actions only when it is ready. Nothing here guesses: a step
whose check does not exist yet is reported not done.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.catalog.modules import MODULES

OPERATIONAL_STATES = frozenset({"enabled", "ready", "active"})

Check = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]


async def _exists(session: AsyncSession, sql: str, business_id: uuid.UUID) -> bool:
    row = (await session.execute(text(f"SELECT EXISTS ({sql})"), {"b": str(business_id)})).scalar()
    return bool(row)


def _sql(sql: str) -> Check:
    async def run(session: AsyncSession, business_id: uuid.UUID) -> bool:
        return await _exists(session, sql, business_id)

    return run


async def _table_exists(session: AsyncSession, name: str) -> bool:
    return bool((await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})).scalar())


def _sql_if_table(table: str, sql: str) -> Check:
    """A check over a table a later packet creates; false until it exists."""

    async def run(session: AsyncSession, business_id: uuid.UUID) -> bool:
        if not await _table_exists(session, table):
            return False
        return await _exists(session, sql, business_id)

    return run


_LIVE_OFFERING = (
    "SELECT 1 FROM offerings_catalog_offerings WHERE business_id = CAST(:b AS uuid) "
    "AND deleted_at IS NULL AND status = 'active' AND visibility = 'public'"
)

CHECKS: dict[str, Check] = {
    "offering_live": _sql(_LIVE_OFFERING),
    "priced_product": _sql(
        _LIVE_OFFERING + " AND price_amount IS NOT NULL AND price_amount > 0 "
        "AND price_type IN ('fixed', 'starting_from')"
    ),
    # Cash / COD / pay-at-business is always available; online payment is an
    # activation on top (merchant connection) and not required for readiness.
    "payment_method": lambda s, b: _true(),
    "stock_recorded": _sql(
        "SELECT 1 FROM inventory_records WHERE business_id = CAST(:b AS uuid)"
    ),
    # The same answer as FulfilmentService.active_modes, which checkout uses: no
    # settings saved yet means the defaults (pickup on); delivery counts only
    # with an active zone to deliver to.
    "fulfilment_mode": _sql(
        "SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM fulfilment_settings WHERE business_id = CAST(:b AS uuid)) "
        "OR EXISTS (SELECT 1 FROM fulfilment_settings s WHERE s.business_id = CAST(:b AS uuid) AND "
        "(s.pickup_enabled OR (s.delivery_enabled AND EXISTS (SELECT 1 FROM fulfilment_zones z "
        "WHERE z.business_id = s.business_id AND z.deleted_at IS NULL AND z.is_active))))"
    ),
    # What the booking engine can schedule (booking_slots.MODE_BY_KIND). A menu
    # item is not bookable — it used to count, so a restaurant with a menu got
    # a "Book now" that offered its dishes as appointments.
    "bookable_offering": _sql(
        _LIVE_OFFERING + " AND offering_type IN ('service', 'class_session', 'accommodation', "
        "'rental', 'property_project', 'property_unit')"
    ),
    "plan_live": _sql(
        "SELECT 1 FROM memberships_plans WHERE business_id = CAST(:b AS uuid) "
        "AND deleted_at IS NULL AND status = 'active' AND visibility = 'public'"
    ),
    "provider_added": _sql(
        "SELECT 1 FROM workforce_members WHERE business_id = CAST(:b AS uuid) "
        "AND deleted_at IS NULL AND status = 'active'"
    ),
    # Billing is set up when the owner chose how they bill, told LOCAH their
    # registration (or that they are not registered) and has a register.
    "tax_profile": _sql_if_table(
        "invoicing_tax_profiles",
        "SELECT 1 FROM invoicing_tax_profiles p WHERE p.business_id = CAST(:b AS uuid) "
        "AND EXISTS (SELECT 1 FROM invoicing_registrations r WHERE r.business_id = p.business_id "
        "AND r.status = 'active') "
        "AND EXISTS (SELECT 1 FROM invoicing_registers g WHERE g.business_id = p.business_id "
        "AND g.status = 'active')",
    ),
    # A POS register is the invoicing register (one concept, §14.4).
    "register_created": _sql_if_table(
        "invoicing_registers",
        "SELECT 1 FROM invoicing_registers WHERE business_id = CAST(:b AS uuid) AND status = 'active'",
    ),
    "channel_connected": _sql_if_table(
        "messaging_channels",
        "SELECT 1 FROM messaging_channels WHERE business_id = CAST(:b AS uuid) "
        "AND status = 'connected'",
    ),
}


async def _true() -> bool:
    return True


# Bookings owns scheduling (Doc 08 §9.3): besides a catalogue service, class or
# room, a business is bookable through its own bookable resources (a table, a
# studio, a court — Doc 08 §23.2: a restaurant can take reservations without
# online ordering) or its people (an appointment with a stylist).
_BOOKING_RESOURCE = _sql(
    "SELECT 1 FROM bookings_resources WHERE business_id = CAST(:b AS uuid) "
    "AND deleted_at IS NULL AND is_active"
)

# Doc 08 §9.2 rule 4: a module-to-module edge is hard "only when every supported
# mode requires it". The registry's `depends_on` is hard except for these two,
# which §9.3 describes as conditional: Memberships sells plans without online
# collection (auto-renewal is what needs Payments), and Bookings takes table
# reservations without the catalogue (services, classes and rooms come from it).
CONDITIONAL_DEPENDENCIES = frozenset({("memberships", "payments"), ("bookings", "offerings-catalog")})


def hard_dependencies(module_id: str) -> tuple[str, ...]:
    info = MODULES.get(module_id)
    return tuple(d for d in (info.depends_on if info else ()) if (module_id, d) not in CONDITIONAL_DEPENDENCIES)


async def module_states(session: AsyncSession, business_id: uuid.UUID) -> dict[str, str]:
    rows = await session.execute(
        text("SELECT module_id, activation_state FROM business_module_states "
             "WHERE business_id = CAST(:b AS uuid)"),
        {"b": str(business_id)},
    )
    return {r[0]: r[1] for r in rows}


async def readiness(
    session: AsyncSession, business_id: uuid.UUID, modules: Iterable[str] | None = None
) -> dict[str, dict[str, Any]]:
    """module -> {state, enabled, entitled, built, steps, configured, blocked_by, ready}.

    `ready` is the one answer every surface reads: built, entitled, switched on,
    set up, and every hard dependency ready too. `blocked_by` names the hard
    dependencies that are holding it back, so a screen can say why.
    """
    from platform_core.services.entitlement import EntitlementService

    entitlements = await EntitlementService.get_effective(session, business_id)
    states = await module_states(session, business_id)
    wanted = list(modules) if modules is not None else list(MODULES)
    # Everything a wanted module's readiness can depend on, transitively.
    needed: list[str] = []
    pending = list(wanted) + (["workforce"] if "bookings" in wanted else [])
    while pending:
        key = pending.pop()
        if key in needed:
            continue
        needed.append(key)
        info = MODULES.get(key)
        pending.extend(info.depends_on if info else ())
    cache: dict[str, bool] = {}
    out: dict[str, dict[str, Any]] = {}
    for key in needed:
        info = MODULES.get(key)
        state = states.get(key, "not_enabled")
        enabled = state in OPERATIONAL_STATES
        steps = []
        for step in info.setup if info else ():
            if step.key not in cache:
                check = CHECKS.get(step.key)
                cache[step.key] = bool(await check(session, business_id)) if check else False
            steps.append({"key": step.key, "label": step.label, "done": cache[step.key]})
        built = bool(info and info.built and not info.future)
        out[key] = {
            "state": state,
            "enabled": enabled,
            "entitled": entitlements.is_entitled(key),
            "built": built,
            "steps": steps,
            "configured": all(s["done"] for s in steps),
            "blocked_by": [],
            "ready": False,
        }

    memo: dict[str, bool] = {}

    def effective(key: str, seen: frozenset[str] = frozenset()) -> bool:
        if key in memo:
            return memo[key]
        row = out.get(key)
        if row is None or key in seen:
            return False
        own = row["built"] and row["entitled"] and row["enabled"] and row["configured"]
        blocked = [dep for dep in hard_dependencies(key) if not effective(dep, seen | {key})]
        row["blocked_by"] = blocked
        memo[key] = bool(own and not blocked)
        return memo[key]

    # A service, class or room is bookable only while the catalogue that lists
    # it is ready; a resource is bookable on its own; a person while Workforce,
    # which owns their schedules, is ready.
    if "bookings" in out:
        row = out["bookings"]
        resources = await _BOOKING_RESOURCE(session, business_id)
        for step in row["steps"]:
            if step["key"] == "bookable_offering":
                step["done"] = resources or effective("workforce") or (
                    step["done"] and effective("offerings-catalog"))
        row["configured"] = all(s["done"] for s in row["steps"])

    for key in needed:
        out[key]["ready"] = effective(key)
    return {key: out[key] for key in wanted}


async def module_ready(session: AsyncSession, business_id: uuid.UUID, module_id: str) -> bool:
    """May a customer use this module's public actions right now?"""
    return bool((await readiness(session, business_id, modules=(module_id,)))[module_id]["ready"])


async def module_operational(session: AsyncSession, business_id: uuid.UUID, module_id: str) -> bool:
    """May the Business's own people operate it? Switched on and entitled — a
    stale activation row without an Entitlement operates nothing (Doc 08 §20.2).
    Setup completeness is not required here: staff are who completes it."""
    from platform_core.services.entitlement import EntitlementService

    states = await module_states(session, business_id)
    if states.get(module_id, "not_enabled") not in OPERATIONAL_STATES:
        return False
    return bool((await EntitlementService.get_effective(session, business_id)).is_entitled(module_id))


async def ready_modules(session: AsyncSession, business_id: uuid.UUID) -> frozenset[str]:
    """Modules whose customer actions any surface may show right now."""
    r = await readiness(session, business_id)
    return frozenset(k for k, v in r.items() if v["ready"])
