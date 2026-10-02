"""What the Workspace navigation projects for one Business (Doc 05 §9.1, §12.2;
Doc 09 §7.2; Doc 07 §3.3).

Navigation is a projection, not a fixed list:

    Platform Core + Entitlement + enabled/configured module contributions
    + permission and Location scope + progressive complexity.

This module answers the module part — one navigation state per catalogue
module, from the same `readiness` every customer surface reads — and the
vocabulary part (Menu instead of Products, Reservations instead of Bookings).
Permissions are the request context's; the Workspace combines the two. Nothing
here grants anything: the API still authorises every route and action.

Navigation states:

* ``active`` — entitled, switched on, set up: an operational destination.
* ``setup_required`` — entitled and switched on but not set up (or waiting on a
  module it needs). NAV-008: shown to people who can complete setup, marked as
  such, never as operational.
* ``not_entitled`` — a stale activation without an Entitlement (Doc 08 §20.2):
  no operational entry; the owner's recovery lives in Modules.
* ``deactivated`` / ``not_enabled`` / ``unavailable`` — no operational entry.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import Business, Offering


def navigation_state(row: Mapping[str, Any]) -> str:
    """One module's navigation state from its readiness row. Pure."""
    if row.get("ready"):
        return "active"
    if not row.get("built"):
        return "unavailable"
    if not row.get("enabled"):
        return "deactivated" if row.get("state") == "deactivated" else "not_enabled"
    if not row.get("entitled"):
        return "not_entitled"
    return "setup_required"


async def navigation_modules(session: AsyncSession, business_id: uuid.UUID) -> dict[str, str]:
    from platform_core.services.module_readiness import readiness

    return {key: navigation_state(row) for key, row in (await readiness(session, business_id)).items()}


def _plural(term: str) -> str:
    term = term.strip()
    if not term:
        return term
    if term.lower().endswith(("s", "x", "ch", "sh")):
        return term + "es"
    if term.lower().endswith("y") and term[-2:-1].lower() not in "aeiou":
        return term[:-1] + "ies"
    return term + "s"


# Doc 11 §7.3 / Doc 09 §7.2: a restaurant or hotel takes Reservations; an
# appointment-led business keeps "Bookings" (Clinic: Services / Bookings).
_BOOKING_TERMS = {"reservation": "Reservations", "check-in": "Reservations"}
_CATALOGUE_TERMS = {"menu item": "Menu", "product": "Products & services", "membership": "Plans", "stay": "Rooms"}


def workspace_terms(kinds: Mapping[str, int], terminology: Mapping[str, str]) -> dict[str, str]:
    """Labels for the Workspace's own destinations. Pure.

    The catalogue is named by what the Business really lists (a restaurant's
    menu items make it the "Menu"); before anything is listed, by the Business's
    terminology (its own words first, then its profile's suggestion). Route ids
    and permissions never change — only the label does (Doc 07 §3.3)."""
    from platform_core.website.capabilities import catalogue_label

    named = catalogue_label(kinds) if any(int(n or 0) > 0 for n in kinds.values()) else ""
    if not named or named == "What we offer":
        product = str(terminology.get("product") or "").strip()
        named = _CATALOGUE_TERMS.get(product.lower()) or (_plural(product) if product else "Products & services")
    appointment = str(terminology.get("appointment") or "").strip()
    bookings = _BOOKING_TERMS.get(appointment.lower(), "Bookings")
    customer = str(terminology.get("customer") or "").strip()
    return {
        "offerings": named,
        "bookings": bookings,
        "customers": _plural(customer) if customer else "Customers",
    }


async def terms_for(session: AsyncSession, business: Business) -> dict[str, str]:
    from platform_core.services.business_configuration import BusinessConfigurationResolver

    # Everything the owner has listed, published or not: the Workspace names the
    # list they are working on, not only what the website shows. Archived items
    # are put away and no longer name it.
    kinds = {row[0]: int(row[1]) for row in (await session.execute(
        select(Offering.offering_type, func.count()).where(
            Offering.business_id == business.id, Offering.deleted_at.is_(None), Offering.status != "archived"
        ).group_by(Offering.offering_type))).all()}
    terminology = BusinessConfigurationResolver.resolve_from_business(business).resolved.get("terminology") or {}
    return workspace_terms(kinds, terminology)
