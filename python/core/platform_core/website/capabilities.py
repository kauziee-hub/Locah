"""What a visitor can actually do with a business, right now (Founder §14–16; Guide §4).

The website, the Marketplace listing and the website's own navigation all read
this one answer, so they can never disagree. It comes from real module
*readiness* — built, switched on and set up (a priced product, a published
plan, a bookable service) — never from the business category and never from a
module merely being switched on.

When a module becomes ready its customer surface appears on the website without
a rebuild: `auto_sections` adds the module's section to the home page if the
owner's design has none (the catalogue for Offerings — a Menu, Products or
Services, by what the business really lists — Plans for Memberships, a booking
band for Bookings, reviews once there are reviews). The owner can hide any of
them; a module that stops being ready takes its actions away again.

These sections are platform mechanics, not generated content: each carries a
`module_binding` naming the module whose public read contract fills it, its
words are LOCAH's (translated on the site), and it is keyed by module so the
same module can never add itself twice (Doc 12 §11.9, §12.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import BusinessTrait, Offering

# Actions every surface understands. The first ready one that a business's own
# way of trading leads with becomes its primary call to action.
_PRIMARY_BY_TRAIT: tuple[tuple[str, str], ...] = (
    ("donation_led", "donate"), ("booking_led", "book"), ("subscription_led", "join"),
    ("order_led", "order"), ("quote_led", "request_quote"), ("project_led", "request_quote"),
    ("enquiry_led", "enquire"),
)
PRIMARY_LABELS = {
    "order": "Order now", "book": "Book now", "join": "See plans", "request_quote": "Get a quote",
    "enquire": "Enquire", "donate": "Donate", "site_visit": "Book a site visit", "call": "Call", "whatsapp": "WhatsApp",
}
PRIMARY_PATHS = {
    "order": "/checkout", "book": "/book", "join": "/#plans", "request_quote": "/enquire?purpose=quote_request",
    "enquire": "/enquire", "site_visit": "/enquire?purpose=site_visit",
}


def decide(ready: Mapping[str, bool], kinds: Mapping[str, int], traits: Iterable[str], *,
           has_whatsapp: bool = False, has_phone: bool = False) -> dict[str, Any]:
    """Pure: which customer actions are real for this business, and which leads.

    `ready` is module → ready (built, enabled, configured); `kinds` counts live,
    public offerings by kind; `traits` are the business's operating traits."""
    t = set(traits)

    def live(*names: str) -> bool:
        return any(kinds.get(n, 0) > 0 for n in names)

    leads = bool(ready.get("leads"))
    flags: dict[str, Any] = {
        # The catalogue is something to browse on its own (Doc 08 §23.2: a menu
        # without online ordering); ordering is a separate, later capability.
        "catalogue": bool(ready.get("offerings-catalog")),
        # Checkout cannot complete without a way to hand the order over (pickup
        # or delivery — CheckoutService.place_for_contact), so a cart before
        # that would be a dead end: Orders and Fulfilment both ready.
        "order": bool(ready.get("orders")) and bool(ready.get("fulfilment")),
        "book": bool(ready.get("bookings")),
        "join": bool(ready.get("memberships")),
        "enquire": leads,
        # A request for a quote lands as a lead the team quotes from (RFQ intake).
        "request_quote": bool(ready.get("quotes")) and leads,
        "site_visit": leads and live("property_project", "unit"),
        "test_drive": leads and live("vehicle"),
        # A cause takes gifts through the same checkout (P1-03).
        "donate": bool(ready.get("orders")) and live("cause"),
        "track": bool(ready.get("orders")) and bool(ready.get("fulfilment")),
        "reviews": bool(ready.get("reviews")),
        "contact": True,
        "visit_website": True,
        # Presentation traits (§22): digital-only businesses publish no address.
        "show_address": "digital_only" not in t,
    }
    flags.update(pick_primary(flags, t, landings={}, has_whatsapp=has_whatsapp, has_phone=has_phone))
    return flags


def _candidates(flags: Mapping[str, Any], traits: set[str]) -> list[str]:
    """Ready actions, the business's own way of trading first (§22)."""
    out = [action for trait, action in _PRIMARY_BY_TRAIT if trait in traits and flags.get(action)]
    for action in ("order", "book", "join", "request_quote", "site_visit", "donate", "enquire"):
        if flags.get(action) and action not in out:
            out.append(action)
    return out


def pick_primary(flags: Mapping[str, Any], traits: Iterable[str], *, landings: Mapping[str, str | None],
                 has_whatsapp: bool = False, has_phone: bool = False) -> dict[str, Any]:
    """The header's main button. An action whose landing place is known to be
    missing (`landings[action] is None` — say the owner hid the only Plans
    section) is skipped, so the button never points at nothing."""
    for action in _candidates(flags, set(traits)):
        if action in landings:
            if landings[action] is None:
                continue
            path = landings[action]
        else:
            path = PRIMARY_PATHS.get(action)
        return {"primary": action, "primary_label": PRIMARY_LABELS[action], "primary_path": path}
    fallback = "whatsapp" if has_whatsapp else "call" if has_phone else None
    return {"primary": fallback, "primary_label": PRIMARY_LABELS.get(fallback or ""), "primary_path": None}


# Sections a visitor lands on for an action (the rest have their own page).
# Category tiles are not one: they show no item a visitor could add.
LANDING_SECTIONS = {
    "order": ({"offerings_list", "menu_section", "product_showcase"}, "shop"),
    "donate": ({"offerings_list", "menu_section", "product_showcase"}, "shop"),
    "join": ({"plans_section"}, "plans"),
}


async def gather(session: AsyncSession, business_id: uuid.UUID) -> tuple[dict[str, bool], dict[str, int], list[str]]:
    states, kinds, traits = await gather_states(session, business_id)
    return {k: bool(v["ready"]) for k, v in states.items()}, kinds, traits


async def gather_states(
    session: AsyncSession, business_id: uuid.UUID
) -> tuple[dict[str, dict[str, Any]], dict[str, int], list[str]]:
    """Full module readiness (with the reason a module is not ready), live
    offering counts by kind, and the business's operating traits."""
    from platform_core.services.module_readiness import readiness

    states = await readiness(session, business_id)
    kinds = {row[0]: int(row[1]) for row in (await session.execute(
        select(Offering.offering_type, func.count()).where(
            Offering.business_id == business_id, Offering.deleted_at.is_(None), Offering.status == "active",
            Offering.visibility == "public").group_by(Offering.offering_type))).all()}
    traits = [row[0] for row in (await session.execute(select(BusinessTrait.trait_key).where(
        BusinessTrait.business_id == business_id, BusinessTrait.enabled.is_(True)))).all()]
    return states, kinds, traits


async def site_capabilities(session: AsyncSession, business_id: uuid.UUID, *, has_whatsapp: bool = False,
                            has_phone: bool = False) -> dict[str, Any]:
    ready, kinds, traits = await gather(session, business_id)
    return flags_for(ready, kinds, traits, has_whatsapp=has_whatsapp, has_phone=has_phone)


def flags_for(ready: Mapping[str, bool], kinds: Mapping[str, int], traits: Iterable[str], *,
              has_whatsapp: bool = False, has_phone: bool = False) -> dict[str, Any]:
    flags = decide(ready, kinds, traits, has_whatsapp=has_whatsapp, has_phone=has_phone)
    flags["catalogue_label"] = catalogue_label(kinds)
    flags["_kinds"] = dict(kinds)
    flags["_traits"] = list(traits)
    return flags


# ---------------------------------------------------------------- sections bound to a module
def section_module(section_type_id: str, binding: Any, type_modules: Mapping[str, str | None]) -> str | None:
    """The module whose public read contract fills a section, if any: its own
    `module_binding`, else the module its SectionType is contributed by."""
    if isinstance(binding, dict) and isinstance(binding.get("module"), str) and binding["module"]:
        return str(binding["module"])
    return type_modules.get(section_type_id)


def section_available(section_type_id: str, module: str | None, ready: Mapping[str, bool]) -> bool:
    """Doc 12 §11.9: a bound section shows only while its module is ready."""
    if not module:
        return True
    if section_type_id == "plans_section" and module == "offerings-catalog":
        # A Plans section lists catalogue plans or real Membership plans.
        return bool(ready.get("offerings-catalog") or ready.get("memberships"))
    return bool(ready.get(module))


def unavailable_reason(state: Mapping[str, Any] | None) -> str:
    """Why a module is not ready, in the order an owner would fix it."""
    if not state or not state.get("built", True):
        return "module_not_available"
    if not state.get("entitled"):
        return "module_not_entitled"
    if not state.get("enabled"):
        return "module_not_active"
    if state.get("blocked_by"):
        return "module_dependency_not_ready"
    return "module_setup_required"


# Offering kinds grouped the way a visitor reads a catalogue. Plans and causes
# have their own sections, so they never name the catalogue.
_GOODS = frozenset({"product", "weighed_product", "digital_product", "package", "vehicle", "menu_item"})
_SERVICES = frozenset({"service", "class_session", "course"})
_OWN_SECTION = frozenset({"membership_plan", "cause"})


def catalogue_label(kinds: Mapping[str, int]) -> str:
    """What this business's catalogue is called, from what it really lists.

    Pure. A restaurant's live menu items make it a "Menu"; a salon's services
    make it "Services"; a shop's products "Products". It reads the records, not
    the business category (Doc 07 §3.3: terminology adapts comprehension, never
    domain identity), so a cafe that also sells retail packs reads correctly.
    """
    from platform_core.catalog.offering_kinds import KINDS

    live = {k: int(n) for k, n in kinds.items() if int(n or 0) > 0 and k not in _OWN_SECTION}
    if not live:
        return "What we offer"
    total = sum(live.values())
    if live.get("menu_item", 0) * 2 > total:  # most of what is listed is the menu
        return "Menu"
    if len(live) == 1:
        only = next(iter(live))
        return KINDS[only].plural if only in KINDS else "What we offer"
    goods = sum(n for k, n in live.items() if k in _GOODS)
    services = sum(n for k, n in live.items() if k in _SERVICES)
    if goods == total:
        return "Products"
    if services == total:
        return "Services"
    if goods and services:
        return "Products & services"
    return "What we offer"


# ---------------------------------------------------------------- sections a ready module adds
# Sections that already show the catalogue's live records (a product showcase
# switches to them once the catalogue is ready): with one of these on the site,
# the catalogue adds none. Category tiles are the owner's own design — names and
# pictures, no prices — so beside them the real, priced list is still added.
_BROWSE = {"offerings_list", "menu_section", "product_showcase", "rooms_section", "classes_section"}
AUTO_SECTION_MODULES = ("offerings-catalog", "bookings", "memberships", "reviews", "leads")
# Before the catalogue was its own website capability, the shop section was
# keyed by Orders; an owner who hid that section hid the catalogue.
LEGACY_HIDDEN = {"orders": "offerings-catalog"}


def auto_sections(flags: Mapping[str, Any], existing_types: set[str], *, hidden: Iterable[str],
                  published_reviews: int, traits: Iterable[str]) -> list[dict[str, Any]]:
    """Sections the home page gains because a module is ready and the owner's
    design has nothing that shows it. Pure; the renderer draws them like any
    other section, filled from live records through the bound module's public
    read contract. Idempotent: one section per module, keyed by the module, so
    switching a module on twice, or off and on again, never adds a second."""
    kinds = flags.get("_kinds") or {}
    off = set(hidden) | {LEGACY_HIDDEN[h] for h in hidden if h in LEGACY_HIDDEN}
    t = set(traits)
    out: list[dict[str, Any]] = []

    def add(module: str, section_type: str, content: dict[str, Any], variant: str | None = None) -> None:
        if module in off or any(s["module"] == module for s in out):
            return
        out.append({"id": f"auto-{module}-{section_type}", "section_type_id": section_type,
                    "layout_variant": variant, "content": content, "module_binding": {"module": module},
                    "is_visible": True, "is_auto": True, "module": module})

    if flags.get("book"):
        if kinds.get("class", 0) + kinds.get("class_session", 0) and "classes_section" not in existing_types:
            add("bookings", "classes_section", {"title": "Classes", "offering_types": ["class", "class_session"]})
        elif (kinds.get("room_type", 0) + kinds.get("accommodation", 0)) and "rooms_section" not in existing_types:
            add("bookings", "rooms_section", {"title": "Rooms", "offering_types": ["room_type", "accommodation"]})
        elif "cta_band" not in existing_types and "rooms_section" not in existing_types \
                and "classes_section" not in existing_types:
            add("bookings", "cta_band", {"headline": "Book a time that suits you", "cta_label": "Book now",
                                         "cta_url": "/book"})
    # A rooms or classes list a booking band added already shows the catalogue.
    browsing = set(existing_types) | {s["section_type_id"] for s in out}
    if flags.get("catalogue") and not (browsing & _BROWSE):
        label = str(flags.get("catalogue_label") or "What we offer")
        add("offerings-catalog", "menu_section" if label == "Menu" else "offerings_list",
            {"title": label, "anchor": "shop"})
    if flags.get("join") and "plans_section" not in existing_types:
        add("memberships", "plans_section", {"title": "Plans", "anchor": "plans"})
    if flags.get("reviews") and published_reviews > 0 and "reviews_section" not in existing_types:
        add("reviews", "reviews_section", {"title": "What customers say"})
    leads_first = bool(t & {"quote_led", "enquiry_led", "project_led"}) or flags.get("site_visit") \
        or flags.get("test_drive")
    if flags.get("enquire") and leads_first and "enquiry_form" not in existing_types:
        add("leads", "enquiry_form", {"title": "Get a quote" if flags.get("request_quote") else "Send an enquiry",
                                      "anchor": "enquire"})
    # Page order is the module order, whatever order they were worked out in.
    out.sort(key=lambda s: _AUTO_ORDER.index(s["module"]))
    return out


_AUTO_ORDER = ("offerings-catalog", "memberships", "bookings", "reviews", "leads")


async def published_review_count(session: AsyncSession, business_id: uuid.UUID) -> int:
    row = (await session.execute(text(
        "SELECT count(*) FROM reviews_reviews WHERE business_id = CAST(:b AS uuid) AND status = 'published'"),
        {"b": str(business_id)})).scalar()
    return int(row or 0)


async def section_types(session: AsyncSession, version_id: uuid.UUID | None) -> set[str]:
    """Visible section types across every page of one website version."""
    if version_id is None:
        return set()
    from platform_core.models import WebsitePage, WebsiteSection

    rows = (await session.execute(
        select(WebsiteSection.section_type_id).join(WebsitePage, WebsitePage.id == WebsiteSection.page_id)
        .where(WebsitePage.website_version_id == version_id, WebsiteSection.is_visible.is_(True)))).all()
    return {row[0] for row in rows}


# Where a Marketplace action lands when the section it needs is one a tool added
# to the home page (so the listing and the site always agree).
_AUTO_PATHS = {"offerings-catalog": ("browse", "#shop"), "memberships": ("join", "#plans"),
               "leads": ("contact", "#enquire")}


async def published_auto_paths(session: AsyncSession, business_id: uuid.UUID, *, version_id: uuid.UUID | None,
                               hidden: Iterable[str]) -> dict[str, str]:
    if version_id is None:
        return {}
    flags = await site_capabilities(session, business_id)
    extra = auto_sections(flags, await section_types(session, version_id), hidden=hidden,
                          published_reviews=await published_review_count(session, business_id),
                          traits=flags.get("_traits") or [])
    out: dict[str, str] = {}
    for section in extra:
        key_path = _AUTO_PATHS.get(section["module"])
        if key_path:
            out.setdefault(key_path[0], key_path[1])
    return out
