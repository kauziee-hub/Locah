"""LOCAH's design vocabulary for tenant websites: dimensions → family → variant.

The first creative director mapped a business's *archetype* straight to one
reference look, so every meat shop came out dark red and black and every gym
came out yellow on black. A premium butcher, a family butcher and a modern
delivery brand are the same category and three different brands.

Here the look is reasoned from independent dimensions of the business — what
it offers, how a customer acts, how it positions itself, its personality and
energy, how much its pictures matter and whether it has any, how dense its
range is, how local it is, whether it is portfolio-led, who buys, how much
trust the visitor needs — read only from what the owner said (and the trade's
playbook as a prior, never as fact).

Ten families, each with variants. A family is a design language (type, palette
recipes, geometry, rhythm, image treatment, navigation, footer, motion); a
variant is a concrete composition inside it. Every value maps to something
the renderer draws (``theme`` → ``data-*`` on the site root → site-studio.css
and site-families.css) and to section layouts that already exist — so a new
family needs no migration and no template.

The owner never sees "family" or "variant". They see their website.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from platform_core.interview.models import BusinessBlueprint

# ----------------------------------------------------------------- dimensions


@dataclass(frozen=True)
class Dimensions:
    offering: str  # weighed_product | product | menu | plan | class | service | property | portfolio |
    #                b2b_catalogue | stay | rental | cause
    journey: str  # order | book | join | quote | visit | dates | enquire | browse
    primary_action: str  # canonical customer action id, or ""
    positioning: str  # premium | everyday | value | heritage | modern
    personality: str  # bold | warm | calm | playful | refined | technical | friendly
    energy: str  # high | medium | low
    media_importance: str  # critical | high | medium | low
    # The site WILL have pictures: the owner's own, or drafts LOCAH draws now.
    # Decided before the design, so a business without photos still gets the
    # image-led composition its trade deserves.
    has_media: bool
    density: str  # catalogue | curated | sparse
    locality: str  # local | regional | national
    portfolio: str  # heavy | light | none
    audience: str  # b2c | b2b | both
    trust: str  # high | normal
    transaction: str  # online | channel | in_person
    # How the service is experienced, from the trade: care | advisory | wellbeing |
    # learning | hospitality | craft | retail | food | making | none
    service_mode: str = "none"
    # The owner described the feel themselves ("fun, colourful") — worth more
    # than anything inferred.
    personality_said: bool = False
    # The owner's own photos (uploads, catalogue pictures) — not drafts.
    owner_media: bool = False
    evidence: tuple[str, ...] = ()  # why, in plain words — for review and tests

    def as_dict(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "evidence"} | {
            "evidence": list(self.evidence)}


_PREMIUM = re.compile(r"\b(premium|luxur\w*|high[- ]end|finest|exclusive|boutique|artisan\w*|gourmet|"
                      r"hand[- ]?picked|curated|bespoke|elegan\w*|signature)\b", re.I)
_VALUE = re.compile(r"\b(affordable|budget|cheap\w*|low (?:price|cost)|best price|value for money|wholesale "
                    r"price|discount\w*)\b", re.I)
_HERITAGE = re.compile(r"\b(since (?:19|20)\d\d|\d+ years|generations?|family[- ](?:run|owned|business)|"
                       r"traditional|heritage|homemade|home[- ]made|grandmother|paati|amma'?s)\b", re.I)
_MODERN = re.compile(r"\b(app|online|express|fast delivery|quick delivery|within \d+ ?min\w*|subscription|"
                     r"modern|tech|digital|smart)\b", re.I)
_FEEL = {
    "bold": re.compile(r"\b(bold|strong|powerful|intense|loud|energetic|hardcore|raw)\b", re.I),
    "warm": re.compile(r"\b(warm|cosy|cozy|homely|earthy|rustic|traditional|soulful)\b", re.I),
    "calm": re.compile(r"\b(calm|clean|simple|minimal|peaceful|quiet|trustworthy|clinical|serene)\b", re.I),
    "playful": re.compile(r"\b(fun|playful|colou?rful|cheerful|quirky|kids?|children|cute|happy|bright)\b", re.I),
    "refined": re.compile(r"\b(elegant|classy|premium|luxur\w*|sophisticated|refined|minimalist luxury)\b", re.I),
    "technical": re.compile(r"\b(precise|technical|engineer\w*|industrial|specs?|certified|iso)\b", re.I),
}
_HIGH_ENERGY = re.compile(r"\b(gym|crossfit|boxing|mma|martial|sports?|dance|zumba|kids|party|adventure|"
                          r"trek\w*|energetic|intense)\b", re.I)
_LOW_ENERGY = re.compile(r"\b(clinic|hospital|doctor|therapy|counsel\w*|dental|law|legal|ca firm|audit|"
                         r"insurance|finance|funeral|spa|meditation|yoga|calm)\b", re.I)
_HIGH_TRUST = frozenset({"healthcare", "therapy", "finance_insurance", "professional", "real_estate", "care",
                         "labs", "education", "security_staffing"})

# The trade's own knowledge of how its service is experienced (a prior).
_SERVICE_MODE = {
    "clinic": "care", "hospital": "care", "diagnostics": "care", "therapy": "care", "care_service": "care",
    "pharmacy": "care", "professional_firm": "advisory", "consulting": "advisory", "finance": "advisory",
    "software": "advisory", "security_facility": "advisory", "studio": "wellbeing", "spa": "wellbeing",
    "salon": "wellbeing", "coach": "wellbeing", "makeup_artist": "wellbeing", "tuition": "learning",
    "school": "learning", "arts_school": "learning", "tutor": "learning", "daycare": "learning",
    "hotel": "hospitality", "homestay": "hospitality", "stay": "hospitality", "travel": "hospitality",
    "banquet_hall": "hospitality", "tailoring": "craft", "repair": "craft", "home_service": "craft",
    "laundry": "craft", "auto_service": "craft", "detailing": "craft", "contractor": "craft",
    "restaurant": "food", "cafe": "food", "home_food": "food", "bakery_sweets": "food", "catering": "food",
    "tiffin": "food", "meat_seafood": "food", "produce": "food", "photographer": "making",
    "design_studio": "making", "creative_agency": "making", "maker": "making", "event_planner": "making",
    "handmade": "making",
}

_OFFERING = {
    "weighed_product": "weighed_product", "product": "product", "digital_product": "product",
    "menu_item": "menu", "plan": "plan", "class": "class", "service": "service", "package": "service",
    "portfolio_item": "portfolio", "property_project": "property", "room_type": "stay",
    "rental_resource": "rental", "vehicle": "rental", "cause": "cause",
}


def _said(bp: BusinessBlueprint) -> str:
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    words = [m.text for m in bp.messages if m.role == "user"]
    words += [f.value for k, f in facts.items() if k in {"description", "brand", "tone", "colours"}]
    feel = bp.discovery.get("brand.feel")
    story = bp.discovery.get("brand.story")
    words += [s.quote for s in (feel, story) if s and s.quote]
    return " ".join(words)


def read_dimensions(
    bp: BusinessBlueprint, business_type: str | None = None, *, media_expected: bool | None = None,
) -> Dimensions:
    """The business, as the dimensions a designer would reason from.

    ``media_expected`` says whether the site will have pictures; by default it
    is worked out from the owner's photos, their choice about drafts and
    whether an image provider is configured (media_director.pictures_expected).
    """
    from platform_core.interview.discovery import characteristics
    from platform_core.interview.playbooks import playbook_for
    from platform_core.interview.understanding import customer_actions, delivery_area, fulfilment

    pb = playbook_for(bp)
    said = _said(bp)
    chars = characteristics(bp, business_type)
    seen = {c for c, how in chars.items() if how == "observed"}
    evidence: list[str] = []

    offering = _OFFERING.get(pb.offer_kind, "service")
    if pb.key == "other":
        # No trade recognised: what the business does, read from its answers.
        from platform_core.interview.creative_director import derive_archetype
        from platform_core.interview.understanding import sold_by

        archetype = derive_archetype(bp, business_type)
        offering = {"product_commerce": "weighed_product" if sold_by(bp) == "By the kg" else "product",
                    "menu_commerce": "menu", "membership_fitness": "plan", "real_estate_projects": "property",
                    "b2b_rfq": "b2b_catalogue", "project_portfolio": "portfolio"}.get(archetype, "service")
    if "serves_businesses" in seen and ("quote_led" in seen or pb.offer_kind == "product") \
            and offering in {"product", "service"}:
        offering = "b2b_catalogue"
    evidence.append(f"offers: {offering} ({pb.key})")

    actions = customer_actions(bp)
    first = actions[0] if actions else (pb.likely_actions[0] if pb.likely_actions else "")
    journey = ("order" if first.startswith("order") else "join" if first in {"book_trial", "join", "subscribe"}
               else "visit" if first in {"book_site_visit", "visit"} else "dates" if first == "check_dates"
               else "book" if first.startswith("book") else "quote" if first == "request_quote"
               else "enquire" if first in {"enquire", "call", "whatsapp"} else "browse")
    evidence.append(f"customers: {journey}" + (f" ({first})" if first else ""))

    if _PREMIUM.search(said):
        positioning = "premium"
    elif _VALUE.search(said):
        positioning = "value"
    elif _HERITAGE.search(said):
        positioning = "heritage"
    elif _MODERN.search(said):
        positioning = "modern"
    else:
        positioning = "everyday"
    evidence.append(f"positioning: {positioning}")

    personality = next((name for name, rx in _FEEL.items() if rx.search(said)), "")
    personality_said = bool(personality)
    if not personality:
        personality = {"premium": "refined", "heritage": "warm", "modern": "bold", "value": "friendly"}.get(
            positioning, "")
    category = bp.category.category_key if bp.category else ""
    haystack = f"{said} {bp.category.label if bp.category else ''} {pb.key}"
    energy = "high" if _HIGH_ENERGY.search(haystack) else "low" if _LOW_ENERGY.search(haystack) else "medium"
    service_mode = _SERVICE_MODE.get(pb.key, "retail" if offering in {"product", "weighed_product"} else "none")
    if not personality:
        # A class is bold at a gym and calm at a tuition centre: energy decides.
        personality = {"b2b_catalogue": "technical", "plan": "bold" if energy != "low" else "calm",
                       "class": "bold" if energy == "high" else "calm", "menu": "warm",
                       "portfolio": "refined", "property": "calm", "stay": "refined"}.get(offering, "")
    if not personality and pb.key in {"salon", "makeup_artist", "spa"}:
        personality = "refined"  # beauty is presented, not prescribed
    if not personality:
        personality = {"care": "calm", "advisory": "calm", "wellbeing": "calm", "learning": "calm",
                       "hospitality": "refined"}.get(service_mode, "friendly")
    evidence.append(f"personality: {personality}")

    from platform_core.interview.media_director import owner_photos as _owner_photos
    from platform_core.interview.media_director import pictures_expected

    owner_photos = _owner_photos(bp)
    if media_expected is None:
        media_expected = pictures_expected(bp)
    media_expected = media_expected or bool(owner_photos)
    items = sum(len(g.items) for g in bp.taxonomy.groups)
    density = "catalogue" if items >= 12 or len(bp.taxonomy.groups) >= 6 else \
        "curated" if items >= 4 or len(bp.taxonomy.groups) >= 3 else "sparse"
    modes = fulfilment(bp)
    area = delivery_area(bp)
    locality = "national" if "shipping" in modes or re.search(r"\b(all india|pan india|india|nationwide)\b",
                                                               area, re.I) else \
        "regional" if re.search(r"\b(tamil nadu|kerala|karnataka|state|districts?)\b", area, re.I) else "local"
    audience = "b2b" if offering == "b2b_catalogue" or ("serves_businesses" in seen and
                                                         "sells_products" not in seen) else \
        "both" if "serves_businesses" in seen else "b2c"
    transaction = "online" if any(a in {"order_online", "book_online"} for a in actions) else \
        "channel" if any(a.endswith(("whatsapp", "call")) or a in {"call", "whatsapp"} for a in actions) \
        else "in_person"
    return Dimensions(
        offering=offering, journey=journey, primary_action=first, positioning=positioning,
        personality=personality, energy=energy, media_importance=pb.media, has_media=media_expected,
        density=density, locality=locality,
        portfolio="heavy" if pb.portfolio else "light" if offering in {"property", "service"} and
        "made_to_order" in seen else "none",
        audience=audience, trust="high" if category in _HIGH_TRUST or pb.key in {"hospital", "clinic"}
        else "normal", transaction=transaction, service_mode=service_mode, personality_said=personality_said,
        owner_media=bool(owner_photos), evidence=tuple(evidence),
    )


# ------------------------------------------------------------------ palettes


@dataclass(frozen=True)
class Palette:
    key: str
    mode: str  # light | dark
    primary: str  # buttons, highlights
    accent: str  # second voice
    surface: str  # page ground
    surface_alt: str  # alternating ground
    ink: str
    muted: str
    hue: str  # bucket for distinctness: red | orange | yellow | green | teal | blue | violet | pink | neutral


def _pal(key: str, mode: str, primary: str, accent: str, surface: str, surface_alt: str, ink: str, muted: str,
         hue: str) -> Palette:
    return Palette(key, mode, primary, accent, surface, surface_alt, ink, muted, hue)


# ------------------------------------------------------------------ families


@dataclass(frozen=True)
class Variant:
    key: str
    hero: str  # an allowed hero layout
    nav: str  # commerce | editorial | cinematic | airy | standard
    type_system: str
    cards: str  # sharp | soft | editorial | glass | outline | tile
    image: str  # full | rounded | arch | framed | duotone | plain
    rhythm: str  # compact | balanced | spacious
    surface: str  # sharp | soft | round
    footer: str  # simple | columns | statement
    motion: str  # subtle | lively
    category_variant: str
    product_variant: str
    needs_media: bool = False  # only right when the owner has photos
    fits: frozenset[str] = frozenset()  # dimension values this composition suits


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    words: tuple[str, str, str]  # how the website will feel — shown to the owner
    base_profile: str  # the v2 language whose section styling it builds on
    affinity: dict[str, float]  # "dimension=value" -> weight
    palettes: tuple[Palette, ...]
    variants: tuple[Variant, ...]
    cta_tone: str = "plain"  # plain | direct | invitation


def _v(key: str, hero: str, nav: str, type_system: str, cards: str, image: str, rhythm: str, surface: str,
       footer: str, motion: str, category_variant: str, product_variant: str, *fits: str,
       needs_media: bool = False) -> Variant:
    return Variant(key, hero, nav, type_system, cards, image, rhythm, surface, footer, motion,
                   category_variant, product_variant, needs_media, frozenset(fits))


FAMILIES: dict[str, Family] = {f.key: f for f in (
    Family(
        "editorial_warm", "Editorial Warm", ("Warm", "Crafted", "Inviting"), "editorial_home_food",
        {"offering=menu": 3, "personality=warm": 3, "positioning=heritage": 3, "offering=product": 0.5,
         "media_importance=high": 1, "audience=b2c": 0.5, "energy=medium": 0.5, "energy=low": 0.5,
         "journey=order": 0.5},
        (
            _pal("forest_turmeric", "light", "#2f5d1f", "#c8922a", "#fbf8f1", "#f3ede0", "#1f1d17", "#6b655a",
                 "green"),
            _pal("terracotta_olive", "light", "#a3442a", "#6b7a3a", "#fbf6ef", "#f2e9dc", "#2a1d16", "#6f6256",
                 "orange"),
            _pal("burgundy_saffron", "light", "#7a2336", "#d99a2b", "#fdf8f2", "#f5ebe0", "#26141a", "#6e5b60",
                 "red"),
        ),
        (
            _v("overlay", "editorial_overlay", "editorial", "editorial_food", "soft", "full", "balanced",
               "soft", "columns", "subtle", "chips", "menu_grid", "has_media=True", needs_media=True),
            _v("split", "editorial_split", "editorial", "editorial_food", "editorial", "rounded", "spacious",
               "soft", "statement", "subtle", "image_cards", "menu_grid", "positioning=heritage"),
            _v("letterpress", "centered", "editorial", "friendly_local", "editorial", "framed", "spacious",
               "sharp", "statement", "subtle", "tiles", "compact_list", "journey=visit", "journey=book"),
            _v("menu_board", "left_aligned", "editorial", "editorial_food", "soft", "rounded", "balanced", "soft",
               "columns", "subtle", "tiles", "category_boards", "journey=order"),
            _v("counter_book", "editorial_split", "editorial", "calm_serif", "editorial", "framed", "balanced",
               "sharp", "statement", "subtle", "tiles", "category_boards", "offering=weighed_product",
               "positioning=heritage"),
        ),
        cta_tone="invitation",
    ),
    Family(
        "premium_dark", "Premium Dark", ("Refined", "Confident", "Premium"), "bold_food_commerce",
        {"positioning=premium": 4, "personality=refined": 3, "personality=bold": 0.5,
         "offering=weighed_product": 1, "offering=service": 0.5, "offering=stay": 1, "media_importance=high": 1},
        (
            _pal("charcoal_brass", "dark", "#c9a45c", "#e7d3a8", "#121212", "#1b1a18", "#f4efe6", "#aaa296",
                 "yellow"),
            _pal("midnight_champagne", "dark", "#d8c3a5", "#8fa3b8", "#0e1320", "#161c2b", "#f3efe8", "#a3a8b4",
                 "neutral"),
            _pal("ebony_rose", "dark", "#d49a89", "#c8b08a", "#141011", "#1d1718", "#f6eeea", "#ab9f9c", "pink"),
        ),
        (
            _v("gallery", "commerce_split", "editorial", "premium_serif", "sharp", "framed", "spacious",
               "sharp", "statement", "subtle", "image_cards", "commerce_grid", "has_media=True", needs_media=True),
            _v("salon", "centered", "editorial", "premium_serif", "editorial", "plain", "spacious", "sharp",
               "statement", "subtle", "tiles", "category_boards", "has_media=False"),
            _v("counter", "editorial_split", "commerce", "premium_serif", "sharp", "framed", "balanced", "sharp",
               "columns", "subtle", "tiles", "category_boards", "journey=order", "density=catalogue"),
        ),
        cta_tone="plain",
    ),
    Family(
        "modern_commerce", "Modern Commerce", ("Clear", "Fast", "Fresh"), "bold_food_commerce",
        {"journey=order": 3, "offering=weighed_product": 2, "offering=product": 2, "positioning=modern": 3,
         "positioning=value": 2, "positioning=everyday": 1, "density=catalogue": 2, "transaction=online": 2,
         "transaction=channel": 0.5, "personality=bold": 1},
        (
            _pal("signal_tomato", "light", "#e0412b", "#1a1a1a", "#ffffff", "#f5f4f1", "#141414", "#5f5f5a", "red"),
            _pal("electric_cobalt", "light", "#2146d0", "#ffb020", "#ffffff", "#f3f5fb", "#0f1426", "#58607a",
                 "blue"),
            _pal("fresh_emerald", "light", "#0f8a5f", "#ff7a3d", "#ffffff", "#f1f7f3", "#0f1f18", "#56665d",
                 "green"),
            _pal("charcoal_chili", "dark", "#d93a2b", "#e3d5c1", "#0f0f10", "#18181b", "#f2eee8", "#9e978e", "red"),
        ),
        (
            _v("storefront", "commerce_split", "commerce", "bold_commerce", "sharp", "rounded", "compact",
               "soft", "columns", "lively", "image_cards", "commerce_grid", "has_media=True", "density=catalogue"),
            _v("catalogue", "left_aligned", "commerce", "bold_commerce", "tile", "plain", "compact", "soft",
               "columns", "lively", "tiles", "category_boards", "has_media=False"),
            _v("app_like", "centered", "commerce", "modern_grotesk", "soft", "rounded", "balanced", "round",
               "simple", "lively", "tiles", "category_boards", "positioning=modern", "transaction=online"),
        ),
        cta_tone="direct",
    ),
    Family(
        "playful_editorial", "Playful Editorial", ("Bright", "Friendly", "Full of life"), "friendly_local",
        {"personality=playful": 4, "energy=high": 1, "offering=menu": 1, "offering=class": 1,
         "offering=product": 0.5, "audience=b2c": 0.5},
        (
            _pal("peach_ink", "light", "#e4572e", "#2e86ab", "#fff6ef", "#ffe9dc", "#1d1a2b", "#6a6378", "orange"),
            _pal("lilac_lime", "light", "#6b4de6", "#b5e61d", "#faf7ff", "#efe9ff", "#1b1530", "#665f7e", "violet"),
            _pal("mint_berry", "light", "#d6336c", "#20c997", "#f3fbf7", "#e2f5ec", "#14231d", "#5c6d66", "pink"),
        ),
        (
            _v("sticker", "editorial_split", "standard", "playful_grotesk", "tile", "rounded", "balanced", "round",
               "statement", "lively", "tiles", "service_cards", "has_media=False"),
            _v("scrapbook", "editorial_split", "standard", "playful_grotesk", "soft", "arch", "balanced", "round",
               "statement", "lively", "image_cards", "menu_grid", "has_media=True", needs_media=True),
            _v("poster", "centered", "standard", "playful_grotesk", "outline", "rounded", "spacious", "round",
               "simple", "lively", "chips", "service_cards", "energy=high"),
        ),
        cta_tone="invitation",
    ),
    Family(
        "calm_professional", "Calm Professional", ("Calm", "Trustworthy", "Clear"), "calm_care",
        {"trust=high": 3, "personality=calm": 3, "journey=book": 2, "journey=enquire": 1, "offering=service": 1,
         "energy=low": 2, "service_mode=care": 2, "service_mode=advisory": 2, "service_mode=learning": 1,
         "service_mode=wellbeing": 1},
        (
            _pal("clinic_teal", "light", "#0f766e", "#b45309", "#ffffff", "#f2f7f6", "#10201e", "#5b6b69", "teal"),
            _pal("harbour_navy", "light", "#1e3a5f", "#3f9c8f", "#fbfcfd", "#eef3f7", "#0f1b2b", "#556476", "blue"),
            _pal("sage_clay", "light", "#4d6b57", "#b8643c", "#fbfaf7", "#eff2ec", "#1b231d", "#5f675f", "green"),
        ),
        (
            _v("reassure", "editorial_split", "standard", "calm_care", "soft", "rounded", "spacious", "soft",
               "columns", "subtle", "image_cards", "service_cards", "has_media=True", "positioning=modern",
               "positioning=premium", "journey=enquire", "service_mode=care"),
            _v("practice", "left_aligned", "standard", "calm_care", "outline", "plain", "spacious", "soft",
               "columns", "subtle", "tiles", "service_cards", "service_mode=care", "positioning=everyday"),
            _v("desk", "left_aligned", "editorial", "calm_serif", "editorial", "plain", "balanced", "sharp",
               "simple", "subtle", "tiles", "compact_list", "service_mode=advisory", "personality=refined"),
            _v("retreat", "centered", "airy", "calm_serif", "soft", "arch", "spacious", "round",
               "statement", "subtle", "chips", "service_cards", "service_mode=wellbeing"),
            _v("campus", "editorial_split", "standard", "calm_care", "tile", "rounded", "balanced", "soft",
               "columns", "subtle", "tiles", "service_cards", "service_mode=learning"),
        ),
        cta_tone="plain",
    ),
    Family(
        "monumental", "Monumental", ("Strong", "Focused", "Performance-led"), "cinematic_fitness",
        {"energy=high": 3, "personality=bold": 3, "offering=plan": 3, "offering=class": 2, "journey=join": 2},
        (
            _pal("black_volt", "dark", "#d7ff3a", "#d7ff3a", "#0b0b0c", "#141416", "#f5f5f4", "#a3a3a3", "yellow"),
            _pal("black_signal", "dark", "#ff5a1f", "#ff5a1f", "#0d0c0c", "#171514", "#f7f3ef", "#a8a19b", "orange"),
            _pal("concrete_ink", "light", "#111111", "#e63b2e", "#f1f0ec", "#e4e2dc", "#111111", "#555350",
                 "neutral"),
        ),
        (
            _v("cinema", "cinematic", "cinematic", "cinematic_fitness", "glass", "full", "balanced", "sharp",
               "statement", "lively", "image_cards", "plan_cards", "has_media=True", needs_media=True),
            _v("wordmark", "centered", "cinematic", "monumental_condensed", "sharp", "duotone", "compact",
               "sharp", "statement", "lively", "tiles", "plan_cards", "has_media=False"),
            _v("block", "left_aligned", "standard", "monumental_condensed", "outline", "plain", "compact",
               "sharp", "columns", "lively", "tiles", "plan_cards", "personality=bold", "energy=medium"),
        ),
        cta_tone="direct",
    ),
    Family(
        "portfolio_sketchbook", "Portfolio / Sketchbook", ("Considered", "Personal", "Work-first"),
        "friendly_local",
        {"portfolio=heavy": 5, "offering=portfolio": 3, "journey=dates": 2, "journey=quote": 0.5,
         "personality=refined": 1},
        (
            _pal("paper_ink", "light", "#1a1a1a", "#b0552f", "#fafaf7", "#f0efe9", "#151515", "#6a6a64", "neutral"),
            _pal("dusk_film", "dark", "#e8d5b5", "#c77d5b", "#16150f", "#201e17", "#efe9dd", "#a39c8c", "neutral"),
            _pal("linen_moss", "light", "#3f5a3c", "#9c6b3a", "#f8f6f0", "#ecebe2", "#1c201a", "#63675e", "green"),
        ),
        (
            _v("contact_sheet", "full_width", "editorial", "portfolio_serif", "editorial", "framed", "spacious",
               "sharp", "simple", "subtle", "image_cards", "project_cards", "has_media=True", needs_media=True),
            _v("notebook", "left_aligned", "editorial", "portfolio_serif", "editorial", "plain", "spacious",
               "sharp", "simple", "subtle", "tiles", "compact_list", "journey=dates"),
            _v("studio", "editorial_split", "editorial", "portfolio_serif", "outline", "framed", "balanced",
               "sharp", "statement", "subtle", "tiles", "project_cards", "journey=quote", "journey=book",
               "journey=enquire"),
        ),
        cta_tone="invitation",
    ),
    Family(
        "technical_b2b", "Technical B2B", ("Precise", "Dependable", "Specific"), "technical_b2b",
        {"audience=b2b": 4, "offering=b2b_catalogue": 3, "journey=quote": 3, "personality=technical": 3,
         "density=catalogue": 1},
        (
            _pal("slate_cobalt", "light", "#1d4ed8", "#f59e0b", "#ffffff", "#f3f5f8", "#0f172a", "#526077", "blue"),
            _pal("graphite_safety", "light", "#1f2933", "#f97316", "#fbfbfa", "#eef0f2", "#111827", "#4b5563",
                 "orange"),
            _pal("steel_teal", "dark", "#2dd4bf", "#fbbf24", "#0f1720", "#16212c", "#e8eef4", "#94a3b8", "teal"),
        ),
        (
            _v("spec_sheet", "left_aligned", "standard", "technical_b2b", "sharp", "plain", "compact", "sharp",
               "columns", "subtle", "tiles", "compact_list", "has_media=False"),
            _v("plant", "commerce_split", "standard", "technical_b2b", "sharp", "framed", "balanced", "sharp",
               "columns", "subtle", "image_cards", "compact_list", "has_media=True"),
            _v("blueprint", "centered", "standard", "technical_mono", "outline", "plain", "compact", "sharp",
               "columns", "subtle", "tiles", "compact_list", "density=catalogue"),
        ),
        cta_tone="plain",
    ),
    Family(
        "airy_property", "Airy Property", ("Spacious", "Assured", "Light"), "airy_real_estate",
        # Calm is how a property site should feel: a developer who says "calm,
        # green" is describing homes, not asking for a clinic's page.
        {"offering=property": 5, "journey=visit": 3, "offering=stay": 4, "service_mode=hospitality": 2,
         "positioning=premium": 0.5, "trust=high": 0.5, "personality=calm": 3},
        (
            _pal("sky_navy", "light", "#0f8fd6", "#0b1220", "#ffffff", "#f1f8fd", "#0b1220", "#5a6778", "blue"),
            _pal("sand_sage", "light", "#5b7a5a", "#b88a55", "#fcfbf8", "#f2efe7", "#1d231c", "#666d64", "green"),
            _pal("stone_terracotta", "light", "#b3563a", "#2d3e50", "#fbfaf8", "#f1ede7", "#1f1b18", "#6a625a",
                 "orange"),
        ),
        (
            _v("horizon", "airy_split", "airy", "premium_property", "soft", "rounded", "spacious", "round",
               "columns", "subtle", "chips", "project_cards", "has_media=True"),
            _v("brochure", "airy_split", "airy", "premium_property", "outline", "plain", "spacious", "round",
               "statement", "subtle", "tiles", "project_cards", "has_media=False"),
            _v("estate", "centered", "airy", "calm_serif", "editorial", "arch", "spacious", "soft",
               "statement", "subtle", "chips", "service_cards", "offering=stay", "service_mode=hospitality"),
        ),
        cta_tone="invitation",
    ),
    Family(
        "local_friendly", "Local Friendly", ("Friendly", "Local", "Straightforward"), "friendly_local",
        {"locality=local": 1, "positioning=everyday": 2, "positioning=value": 1, "personality=friendly": 3,
         "offering=service": 1, "journey=enquire": 1, "transaction=channel": 1},
        (
            _pal("brick_teal", "light", "#9a3412", "#0f766e", "#fffdf9", "#f7f1e8", "#1c1917", "#6b625a", "orange"),
            _pal("butter_green", "light", "#1f6f43", "#e0a526", "#fffcf2", "#fbf3dc", "#1b2419", "#646b5c", "green"),
            _pal("denim_marigold", "light", "#27497a", "#e59a1c", "#fbfaf6", "#eef1f6", "#141c2b", "#5b6474", "blue"),
        ),
        (
            _v("shopfront", "editorial_split", "standard", "friendly_local", "soft", "rounded", "balanced",
               "soft", "columns", "subtle", "image_cards", "service_cards", "has_media=True"),
            _v("noticeboard", "editorial_split", "standard", "friendly_local", "tile", "plain", "balanced", "soft",
               "columns", "subtle", "tiles", "service_cards", "has_media=False"),
            _v("neighbour", "image_right", "standard", "calm_care", "outline", "rounded", "balanced", "round",
               "simple", "subtle", "tiles", "compact_list", "density=sparse"),
        ),
        cta_tone="plain",
    ),
)}

# The trade's own lean (playbook.families): a prior, worth less than evidence.
_PRIOR_WEIGHT = 2.0


@dataclass(frozen=True)
class Choice:
    family: Family
    variant: Variant
    palette: Palette
    scores: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


def _stable(seed: str) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)


def _dim_values(d: Dimensions) -> set[str]:
    return {f"{k}={getattr(d, k)}" for k in ("offering", "journey", "positioning", "personality", "energy",
                                             "media_importance", "density", "locality", "portfolio", "audience",
                                             "trust", "transaction", "service_mode")} | {
        f"has_media={d.has_media}"}


def choose(bp: BusinessBlueprint, dims: Dimensions, *, seed: str = "") -> Choice:
    """The family that fits the evidence best, its best composition, its palette.

    Deterministic. Ties between equally-fitting options are broken by the
    business's own id, so two businesses that said the same things still get
    a stable look — while different evidence gives different looks.
    """
    from platform_core.interview.playbooks import playbook_for

    values = _dim_values(dims)
    pb = playbook_for(bp)
    # A recognised trade leans towards its usual families; "other" leans nowhere.
    priors = pb.families if pb.key != "other" else ()
    scores: dict[str, float] = {}
    said_feel = f"personality={dims.personality}" if dims.personality_said else ""
    for key, family in FAMILIES.items():
        score = sum(weight for dim, weight in family.affinity.items() if dim in values)
        if said_feel and said_feel in family.affinity:
            score += 2.5
        if key in priors:
            score += _PRIOR_WEIGHT * (1.0 - 0.3 * priors.index(key))
        scores[key] = round(score, 3)
    seed = seed or str(bp.business_id)
    ranked = sorted(scores, key=lambda k: (-scores[k], _stable(seed + k)))
    family = FAMILIES[ranked[0]]
    feel = bp.website_prefs.feel
    if feel:
        # The owner asked for a feel: stay in this family if it has a palette
        # for it, else move to the nearest family the evidence also supports.
        best = max(scores.values()) or 1.0
        supported = [k for k in ranked if scores[k] >= best * 0.55][:4]
        for key in supported:
            current = _palette(FAMILIES[key], dims, seed) if key == family.key else None
            if [p for p in _feel_palettes(FAMILIES[key], feel) if current is None or p.key != current.key]:
                family = FAMILIES[key]
                break

    variant = _variant(family, dims)
    palette = _palette(family, dims, seed, feel)
    def said(keys: object) -> str:
        # "offering: menu" — never "offering=menu", which the site's markup guard rightly refuses.
        return ", ".join(sorted(str(k).replace("=", ": ") for k in keys))  # type: ignore[attr-defined]

    pictures = ("owner photos" if dims.owner_media else "draft visuals" if dims.has_media
                else "no pictures")
    reasons = (f"{family.label} — " + said(d for d in family.affinity if d in values)[:200],
               f"composition {variant.key} — " + pictures
               + f", {dims.offering}, {dims.journey}, {dims.service_mode}",
               f"palette {palette.key}")
    return Choice(family, variant, palette, scores, reasons)


# (family, dimension=value) -> palette: which recipe the evidence leans to.
_PALETTE_BY_EVIDENCE: dict[tuple[str, str], str] = {
    ("calm_professional", "service_mode=care"): "clinic_teal",
    ("calm_professional", "service_mode=advisory"): "harbour_navy",
    ("calm_professional", "service_mode=wellbeing"): "sage_clay",
    ("calm_professional", "service_mode=learning"): "harbour_navy",
    ("editorial_warm", "offering=weighed_product"): "terracotta_olive",
    ("editorial_warm", "journey=order"): "forest_turmeric",
    ("editorial_warm", "journey=visit"): "burgundy_saffron",
    ("editorial_warm", "journey=book"): "burgundy_saffron",
    ("airy_property", "offering=property"): "sky_navy",
    ("airy_property", "offering=stay"): "sand_sage",
    ("portfolio_sketchbook", "journey=dates"): "dusk_film",
    ("portfolio_sketchbook", "journey=quote"): "linen_moss",
    ("modern_commerce", "positioning=modern"): "electric_cobalt",
    ("modern_commerce", "offering=weighed_product"): "charcoal_chili",
    ("technical_b2b", "offering=b2b_catalogue"): "slate_cobalt",
    ("technical_b2b", "offering=service"): "graphite_safety",
    ("local_friendly", "service_mode=food"): "brick_teal",
    ("local_friendly", "service_mode=wellbeing"): "denim_marigold",
    ("local_friendly", "offering=product"): "butter_green",
    ("monumental", "offering=plan"): "black_volt",
}


def _variant(family: Family, d: Dimensions) -> Variant:
    """The composition inside the family, from the evidence — one readable rule per family.

    Pictures (the owner's, or drafts LOCAH draws) make image-led compositions
    possible; they do not decide which one. A restaurant people book and a
    café people drop into are both warm and pictured, and still not the same
    page.
    """
    photos = d.has_media
    order, weighed = d.journey == "order", d.offering == "weighed_product"
    modern = d.positioning == "modern" or d.transaction == "online"
    key = {
        "editorial_warm": "overlay" if photos and order and not weighed else "counter_book" if weighed
        else "menu_board" if order else "split" if d.positioning == "heritage" else "letterpress",
        "premium_dark": "counter" if order or d.density == "catalogue" else "gallery" if photos else "salon",
        "modern_commerce": "app_like" if modern else "storefront" if photos else "catalogue",
        "playful_editorial": "scrapbook" if photos and d.offering not in {"class", "service"}
        else "sticker" if d.offering in {"class", "service"} else "poster",
        "calm_professional": "desk" if d.service_mode == "advisory" else "retreat" if d.service_mode == "wellbeing"
        else "campus" if d.service_mode == "learning" else "reassure" if d.positioning in {
            "modern", "premium"} or d.journey == "enquire" else "practice",
        "monumental": "cinema" if photos else "wordmark" if d.offering == "plan" else "block",
        "portfolio_sketchbook": "contact_sheet" if photos and d.owner_media else "notebook"
        if d.journey == "dates" else "studio",
        "technical_b2b": "plant" if photos and d.offering == "b2b_catalogue" else "blueprint"
        if d.density == "catalogue" else "spec_sheet",
        "airy_property": "estate" if d.offering == "stay" else "horizon" if photos else "brochure",
        "local_friendly": "shopfront" if photos else "neighbour" if d.density == "sparse" else "noticeboard",
    }.get(family.key, "")
    chosen = next((v for v in family.variants if v.key == key), None)
    if chosen is None or (chosen.needs_media and not photos):
        chosen = next(v for v in family.variants if not (v.needs_media and not photos))
    return chosen


_WARM = {"orange", "red", "yellow", "pink"}
_COOL = {"blue", "teal", "green", "violet"}


def _feel_palettes(family: Family, feel: str) -> list[Palette]:
    """The family's palettes that answer "make it …"."""
    tests: dict[str, Callable[[Palette], bool]] = {
        # Warmer means a warm colour on a light, soft ground — not a darker red.
        "warmer": lambda p: p.mode == "light" and (
            p.hue in _WARM or p.key in {"terracotta_olive", "forest_turmeric", "butter_green"}),
        "cooler": lambda p: p.hue in _COOL,
        "darker": lambda p: p.mode == "dark",
        "lighter": lambda p: p.mode == "light",
        "calmer": lambda p: p.hue in _COOL | {"neutral"} and p.mode == "light",
        "bolder": lambda p: p.hue in {"red", "orange", "yellow", "violet"},
        "simpler": lambda p: p.hue == "neutral" or p.mode == "light",
        "premium": lambda p: p.mode == "dark" or p.hue == "neutral",
        "playful": lambda p: p.hue in {"orange", "violet", "pink", "yellow"},
    }
    test = tests.get(feel)
    return [p for p in family.palettes if test(p)] if test else []


def _palette(family: Family, dims: Dimensions, seed: str, feel: str | None = None) -> Palette:
    """A palette from the family's recipes: the owner's asked-for feel first, then
    the one the evidence leans to, else stable by business."""
    if feel:
        asked = _feel_palettes(family, feel)
        # Asking for a change should change something: not the palette it already had.
        before = _palette(family, dims, seed)
        fresh = [p for p in asked if p.key != before.key] or asked
        if fresh:
            return fresh[_stable(seed + feel) % len(fresh)]
    values = _dim_values(dims)
    for (fam, dim), key in _PALETTE_BY_EVIDENCE.items():
        if fam == family.key and dim in values:
            found = next((p for p in family.palettes if p.key == key), None)
            if found:
                return found
    lean = {
        ("premium_dark", "heritage"): "burgundy", ("modern_commerce", "modern"): "cobalt",
        ("modern_commerce", "value"): "tomato", ("modern_commerce", "heritage"): "emerald",
        ("editorial_warm", "premium"): "burgundy", ("editorial_warm", "heritage"): "terracotta",
        ("calm_professional", "premium"): "navy", ("local_friendly", "heritage"): "butter",
        ("airy_property", "premium"): "stone",
    }.get((family.key, dims.positioning), "")
    if lean:
        for p in family.palettes:
            if lean in p.key:
                return p
    return family.palettes[_stable(seed + family.key + "palette") % len(family.palettes)]
