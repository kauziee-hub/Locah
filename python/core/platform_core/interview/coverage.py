"""Coverage-driven readiness: is there enough for a strong first website?

The old rule was a checklist — every "essential" target answered, plus the
story, photos and logo asked once — and it grew with every keyword the owner
used. A meat shop that takes orders needed thirteen separate answers.

Here what Locah knows is judged dimension by dimension (identity, what is
offered, how customers buy, fulfilment, place, pricing, operations, brand,
story, media), and each missing piece is classified **for this business**:

* BLOCKING — without it there is no honest first website (what the business
  is, what it offers, what a customer should be able to do);
* HIGH_VALUE — changes the first website a lot (cuts and units for a meat
  shop, delivery or pickup, a photographer's real work, a gym's plans);
* ENRICHMENT — makes it better, can come after the first version (prices,
  hours, the story, photos for most trades);
* OPTIONAL — only if the owner wants to keep refining (logo, team, stock…).

Ready means every BLOCKING piece is resolved and HIGH_VALUE pieces are either
known, asked once, or the question budget for this kind of business is spent.
Once ready, always ready: saying more adds detail, never takes Build away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from platform_core.interview.discovery import (
    TARGETS,
    TARGETS_BY_ID,
    Target,
    _catalogue_open,
    _relevance,
    characteristics,
)
from platform_core.interview.models import BusinessBlueprint, Readiness, TargetState, now
from platform_core.interview.playbooks import Playbook, playbook_for

Dimension = Literal[
    "identity_positioning", "offerings", "customer_type", "customer_conversion", "sales_model",
    "fulfilment", "location_service_area", "pricing_model", "operational_requirements",
    "brand_direction", "trust_story", "media_readiness",
]
Coverage = Literal["unknown", "partial", "sufficient", "high_confidence"]
Importance = Literal["blocking", "high_value", "enrichment", "optional"]

DIMENSION: dict[str, Dimension] = {
    "business.identity": "identity_positioning",
    "offerings.main": "offerings", "offerings.structure": "offerings", "offerings.units": "offerings",
    "offerings.catalogue": "offerings", "offerings.traits": "offerings",
    "offerings.customisation": "offerings",
    "b2b.customers": "customer_type",
    "commerce.action": "customer_conversion", "contact.phone": "customer_conversion",
    "commerce.payment": "sales_model", "b2b.process": "sales_model", "bookings.format": "sales_model",
    "memberships.plans": "sales_model",
    "fulfilment.mode": "fulfilment", "fulfilment.area": "fulfilment", "fulfilment.operator": "fulfilment",
    "contact.location": "location_service_area",
    "offerings.pricing": "pricing_model",
    "operations.hours": "operational_requirements", "operations.team": "operational_requirements",
    "operations.stock": "operational_requirements", "services.providers": "operational_requirements",
    "brand.feel": "brand_direction",
    "brand.story": "trust_story",
    "media.photos": "media_readiness", "media.logo": "media_readiness",
}

DIMENSION_LABELS: dict[Dimension, str] = {
    "identity_positioning": "What the business is",
    "offerings": "What you offer",
    "customer_type": "Who buys",
    "customer_conversion": "What customers can do",
    "sales_model": "How customers buy",
    "fulfilment": "How it reaches them",
    "location_service_area": "Where you are",
    "pricing_model": "Prices",
    "operational_requirements": "How you run it",
    "brand_direction": "Look and feel",
    "trust_story": "Your story",
    "media_readiness": "Photos and logo",
}

WEIGHT: dict[Importance, float] = {"blocking": 10.0, "high_value": 5.0, "enrichment": 1.2, "optional": 0.2}
_DONE = {"answered", "declined", "deferred"}


@dataclass(frozen=True)
class Profile:
    """What shapes the questions for this business: its traits and its trade."""

    chars: dict[str, str]  # characteristic -> "observed" | "profile"
    playbook: Playbook

    @property
    def observed(self) -> set[str]:
        return {c for c, how in self.chars.items() if how == "observed"}

    def has(self, *names: str) -> bool:
        return any(n in self.chars for n in names)

    def saw(self, *names: str) -> bool:
        return any(n in self.observed for n in names)


def profile(bp: BusinessBlueprint, business_type: str | None = None) -> Profile:
    return Profile(chars=characteristics(bp, business_type), playbook=playbook_for(bp))


def relevant(target: Target, prof: Profile, bp: BusinessBlueprint) -> bool:
    if target.id in prof.playbook.skip:
        return False
    if target.id in prof.playbook.elevate:
        return True
    if target.id in {"offerings.catalogue", "offerings.traits"}:
        # Only where the website IS the catalogue (a menu, a service list, a
        # price list, plans, rooms) — and once Locah knows what is sold.
        from platform_core.interview.catalogue_capture import catalogue_led

        if not catalogue_led(bp):
            return False
        if target.id == "offerings.traits":
            return any(g.items for g in bp.taxonomy.groups)
        return True
    if target.id == "offerings.structure":
        # A range whose groups have no items yet is worth one question in trades
        # where people choose inside a group: cuts, dishes, projects.
        # (Not dishes: "idli, dosa and full meals" already names what is on the menu.)
        return _catalogue_open(bp) or (
            prof.playbook.offer_kind in {"weighed_product", "property_project"}
            and bool(bp.taxonomy.groups) and not any(g.items for g in bp.taxonomy.groups)
        )
    ok, _ = _relevance(target, prof.chars)
    if not ok:
        return False
    if target.when == "catalogue_open":
        return bool(_catalogue_open(bp))
    return True


def importance(target_id: str, prof: Profile, bp: BusinessBlueprint) -> Importance:
    """How much this piece matters to THIS business's first website."""
    pb = prof.playbook
    products = prof.has("sells_products")
    ordering = prof.has("accepts_orders")
    property_led = prof.has("sells_property") or pb.offer_kind == "property_project"
    b2b = prof.has("serves_businesses") and not prof.saw("walk_in")
    local = not prof.has("online_only")
    if target_id in {"business.identity", "offerings.main", "commerce.action"}:
        return "blocking"
    if target_id in pb.elevate:
        return "high_value"
    if target_id == "offerings.structure":
        return "high_value" if (products or property_led or pb.offer_kind == "menu_item") else "enrichment"
    if target_id == "offerings.catalogue":
        # The site's catalogue is the site: asked before the first version —
        # except where the visit is the thing (a clinic, a lawyer, a tutor):
        # there how to book matters more than a price list.
        from platform_core.interview.design_system import _SERVICE_MODE
        from platform_core.interview.playbooks import playbook_key

        if pb.offer_kind in {"service", "package", "class"} and \
                _SERVICE_MODE.get(playbook_key(bp)) in {"care", "advisory", "learning"}:
            return "enrichment"
        return "high_value"
    if target_id == "offerings.traits":
        # Veg or non-veg is what a diner checks first; favourites help everyone.
        items = sum(len(g.items) for g in bp.taxonomy.groups)
        return "high_value" if pb.offer_kind == "menu_item" and items >= 4 else "enrichment"
    if target_id == "offerings.units":
        return "high_value" if products and ordering and pb.offer_kind in {"weighed_product", "product"} \
            else "optional"
    if target_id == "fulfilment.mode":
        return "high_value" if products and ordering else "enrichment" if prof.has("delivers") else "optional"
    if target_id == "fulfilment.area":
        # Where a delivery or a technician goes changes what the site promises.
        return "high_value" if prof.saw("delivers") or prof.has("on_site") else "optional"
    if target_id == "contact.location":
        return "high_value" if local else "enrichment"
    if target_id == "contact.phone":
        return "high_value"
    if target_id in {"b2b.customers", "b2b.process"}:
        return "high_value" if b2b else "optional"
    if target_id == "memberships.plans":
        return "high_value" if prof.has("has_memberships") else "optional"
    booked = pb.booking_led and prof.saw("accepts_appointments", "runs_classes")
    if target_id == "bookings.format":
        # What is booked and how shapes a booking-led site; a restaurant that
        # also takes table bookings can say how later.
        return "high_value" if booked else "enrichment" if prof.has("accepts_appointments", "runs_classes") \
            else "optional"
    if target_id == "services.providers":
        # "Which stylist?" / "which doctor?" decides whether the site has a team.
        return "high_value" if booked and prof.has("has_team") else \
            "enrichment" if prof.has("has_team") and prof.has("accepts_appointments") else "optional"
    if target_id == "commerce.payment":
        # How people pay is set up with the payment tool, after the first
        # version; it never changes what the first website looks like.
        return "enrichment" if ordering or "order_online" in _actions_said(bp) else "optional"
    if target_id == "brand.story":
        return "high_value" if pb.story_matters and not _story_known(bp) else "enrichment"
    if target_id == "media.photos":
        # Where pictures carry the site (food, fitness, fashion, property, work),
        # knowing what the owner has — photos, a menu or catalogue, or nothing
        # (then LOCAH draws drafts) — comes before the first version.
        return "high_value" if pb.media in {"critical", "high"} else "enrichment"
    if target_id in {"offerings.pricing", "operations.hours", "offerings.customisation"}:
        return "enrichment"
    return "optional"


def _actions_said(bp: BusinessBlueprint) -> list[str]:
    from platform_core.interview.understanding import customer_actions

    return list(customer_actions(bp))


def _story_known(bp: BusinessBlueprint) -> bool:
    return bool(bp.highlights or bp.website_draft.owner_claims)


def state(bp: BusinessBlueprint, target_id: str) -> TargetState:
    return bp.discovery.get(target_id) or TargetState()


def coverage(bp: BusinessBlueprint, target_id: str) -> Coverage:
    s = state(bp, target_id)
    if target_id == "offerings.catalogue" and s.status not in {"declined", "deferred"}:
        from platform_core.interview.catalogue_capture import completeness

        level = str(completeness(bp))
        return "sufficient" if level == "sufficient" else "partial" if level == "partial" else "unknown"
    if target_id == "offerings.traits" and s.status not in {"declined", "deferred"}:
        from platform_core.interview.catalogue_capture import traits_known

        if traits_known(bp):
            return "sufficient"
        return "partial" if s.status in {"answered", "partial"} else "unknown"
    if target_id == "business.identity" and s.status not in {"answered", "partial"}:
        # A business the owner named by kind, that has said what it offers, is identified.
        if bp.category and bp.category.source == "owner_picked" and _offer_known(bp):
            return "sufficient"
    if target_id == "b2b.process" and s.status not in {"answered", "partial"} and \
            {"request_quote", "enquire"} & set(_actions_said(bp)):
        # "Buyers send an RFQ" already says how a business orders.
        return "sufficient"
    if target_id == "offerings.structure" and s.status not in {"answered", "partial"}:
        groups = bp.taxonomy.groups
        if playbook_for(bp).offer_kind == "property_project":
            # Project names alone don't say what is ready, being built or coming.
            return "partial" if groups else "unknown"
        if groups and any(g.items for g in groups) and not _catalogue_open(bp):
            return "sufficient"
        return "partial" if any(g.items for g in groups) else "unknown"
    if s.status == "answered":
        fact = TARGETS_BY_ID[target_id].fact if target_id in TARGETS_BY_ID else None
        confirmed = bool(fact and fact in bp.known_facts)
        return "high_confidence" if confirmed else "sufficient"
    if s.status == "partial":
        return "partial"
    return "unknown"


def _offer_known(bp: BusinessBlueprint) -> bool:
    s = state(bp, "offerings.main")
    return s.status in {"answered", "partial"} or bool(bp.taxonomy.groups)


def asked_count(bp: BusinessBlueprint, target_id: str) -> int:
    return int(state(bp, target_id).asked)


def resolved(bp: BusinessBlueprint, target_id: str, imp: Importance) -> bool:
    """Known well enough, or the owner has chosen not to say, or asked enough."""
    s = state(bp, target_id)
    if s.status in _DONE:
        return True
    level = coverage(bp, target_id)
    if level in {"sufficient", "high_confidence"}:
        return True
    if level == "partial":
        # Half-answered ("all types of meat"): worth one follow-up if it matters.
        return s.asked >= 1 or imp in {"enrichment", "optional"}
    # Asked once is enough for anything but the essentials; twice for those.
    return bool(s.asked >= (2 if imp == "blocking" else 1))


def follow_ups(bp: BusinessBlueprint) -> int:
    """Questions about the business asked after the opening one.

    "What pictures or menu do you have?" is intake, not a question about the
    business: it never spends the budget the business's own questions need.
    """
    return sum(1 for a in bp.asks if a.ask not in {"opening", "free", "photos"})


def budget(prof: Profile, bp: BusinessBlueprint) -> int:
    """Follow-up questions worth asking before offering to build, for this business.

    Simple businesses (a tutor, a local service) need three; most need five;
    complex ones (B2B supply with RFQs, a developer's projects, a hospital)
    up to seven. The owner can always keep refining after that.
    """
    high = [t.id for t in TARGETS if relevant(t, prof, bp)
            and importance(t.id, prof, bp) == "high_value"]
    # Questions pair related pieces, so pieces are not questions.
    pairs = {"fulfilment.area": "fulfilment.mode", "contact.phone": "contact.location",
             "b2b.process": "b2b.customers", "offerings.units": "offerings.structure",
             "services.providers": "bookings.format"}
    questions = len({pairs.get(t, t) for t in high})
    return 3 if questions <= 2 else 5 if questions <= 4 else 7


def assess(bp: BusinessBlueprint, business_type: str | None = None) -> Readiness:
    prof = profile(bp, business_type)
    blocking_missing: list[str] = []
    high_open: list[str] = []
    for target in TARGETS:
        if not relevant(target, prof, bp):
            continue
        imp = importance(target.id, prof, bp)
        if imp == "blocking" and not resolved(bp, target.id, imp):
            blocking_missing.append(target.id)
        elif imp == "high_value" and not resolved(bp, target.id, imp):
            high_open.append(target.id)
    spent = follow_ups(bp) >= budget(prof, bp)
    website = _website(bp)
    already = bp.completion_state.ready_at is not None
    ready = already or (not blocking_missing and (not high_open or spent))
    if ready and bp.completion_state.ready_at is None:
        bp.completion_state.ready_at = now()
    if ready:
        return Readiness(ready=True, missing=[], website=website,
                         reason="Enough for a strong first version.")
    pending = blocking_missing + high_open
    labels = ", ".join(TARGETS_BY_ID[t].label.lower() for t in pending[:3])
    return Readiness(ready=False, missing=pending, website=website,
                     reason=("Still worth knowing: " + labels)[:200] if labels else "Almost there.")


def floor_met(bp: BusinessBlueprint, business_type: str | None = None) -> bool:
    """Enough to build *something* honest right now, if the owner insists:
    what the business is, and either what it offers or what customers do."""
    if bp.completion_state.ready_at is not None:
        return True
    s_offer = state(bp, "offerings.main")
    identified = coverage(bp, "business.identity") != "unknown" or bool(bp.category)
    offered = s_offer.status in {"answered", "partial"} or bool(bp.taxonomy.groups)
    return identified and (offered or state(bp, "commerce.action").status == "answered")


def _website(bp: BusinessBlueprint) -> dict[str, bool]:
    return {
        "content": _offer_known(bp),
        "conversion": coverage(bp, "commerce.action") != "unknown" or state(bp, "commerce.action").status in _DONE,
        "visuals": bp.visual_consent != "unknown" or any(m.role != "logo" for m in bp.media_assets),
        "story": coverage(bp, "brand.story") != "unknown",
        "structure": bool(bp.taxonomy.groups),
    }


def dimensions(bp: BusinessBlueprint, business_type: str | None = None) -> list[dict[str, str]]:
    """Coverage per dimension, for the quiet progress list — never "question 12 of 19"."""
    prof = profile(bp, business_type)
    order: list[Dimension] = ["offerings", "customer_conversion", "fulfilment", "location_service_area",
                              "sales_model", "trust_story", "media_readiness"]
    rank = {"unknown": 0, "partial": 1, "sufficient": 2, "high_confidence": 3}
    out: list[dict[str, str]] = []
    for dim in order:
        levels = [
            coverage(bp, t.id) for t in TARGETS
            if DIMENSION.get(t.id) == dim and relevant(t, prof, bp)
            and importance(t.id, prof, bp) in {"blocking", "high_value"}
        ]
        if not levels:
            continue
        worst = min(levels, key=lambda lv: rank[lv])
        best = max(levels, key=lambda lv: rank[lv])
        level = worst if rank[worst] >= 2 else ("partial" if rank[best] >= 1 else "unknown")
        out.append({"dimension": dim, "label": DIMENSION_LABELS[dim], "coverage": level})
    return out


def worth_knowing(bp: BusinessBlueprint, business_type: str | None = None, limit: int = 4) -> list[dict[str, str]]:
    """What would still improve the site, most useful first — offered, never demanded."""
    prof = profile(bp, business_type)
    rows: list[tuple[float, str, Importance]] = []
    for target in TARGETS:
        if not relevant(target, prof, bp):
            continue
        imp = importance(target.id, prof, bp)
        if imp == "optional" or resolved(bp, target.id, imp) or coverage(bp, target.id) != "unknown":
            continue
        rows.append((WEIGHT[imp] * target.value, target.id, imp))
    rows.sort(reverse=True)
    return [{"id": tid, "label": TARGETS_BY_ID[tid].label, "short": SHORT.get(tid, TARGETS_BY_ID[tid].label.lower()),
             "short_ta": SHORT_TA.get(tid, SHORT.get(tid, "")), "importance": imp} for _, tid, imp in rows[:limit]]


SHORT_TA: dict[str, str] = {
    "media.photos": "படங்கள்", "offerings.pricing": "விலை", "brand.story": "உங்க தனித்துவம்",
    "operations.hours": "திறந்திருக்கும் நேரம்", "commerce.payment": "பணம் செலுத்தும் முறை",
    "media.logo": "லோகோ", "bookings.format": "புக்கிங் விவரம்", "contact.location": "இருக்கும் இடம்",
}


# How an optional item reads inside a sentence: "I can also ask about photos,
# prices or what makes you different."
SHORT: dict[str, str] = {
    "media.photos": "photos", "offerings.pricing": "prices", "brand.story": "what makes you different",
    "operations.hours": "opening hours", "bookings.format": "how bookings work", "media.logo": "your logo",
    "commerce.payment": "how people pay", "offerings.units": "how things are sold",
    "offerings.customisation": "custom orders", "contact.location": "where you are",
    "contact.phone": "your number", "services.providers": "who customers book with",
    "memberships.plans": "your plans", "fulfilment.area": "delivery areas",
    "fulfilment.mode": "delivery or pickup", "b2b.customers": "who buys from you",
    "operations.team": "your team", "brand.feel": "the look you'd like",
    "offerings.structure": "your range in detail", "b2b.process": "how buyers order",
    "offerings.catalogue": "your full menu or price list", "offerings.traits": "your bestsellers",
}
