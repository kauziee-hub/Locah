"""Compose a business's website from its creative direction and its own truth.

The page is not a template with slots. Its sections follow from what the
business is (the archetype) and what is actually known about it:

* a range with named items becomes browsable product cards, grouped by category
  (a meat shop's cuts, a kitchen's dishes, a developer's projects, a gym's plans);
* a range known only as categories becomes image-led category cards;
* how people order, how it reaches them and how they pay — the owner's answers —
  become a short ordering strip and the hero's fact chips;
* the owner's story (and any line they asked the site to say) becomes a story
  section with that line as a pull quote;
* contact comes last, with Call / WhatsApp / directions from what they gave.

Nothing is added that was not said: no ratings, counts, awards, prices or
promises; a section with nothing true to show is left out. Headings and short
lines are editorial and may be the model's, after governance.
"""

from __future__ import annotations

import re
from typing import Any

from platform_core.interview.creative_director import CreativeDirection
from platform_core.interview.catalogue_capture import item_traits
from platform_core.interview.experience import choose_experience, marquee_words
from platform_core.interview.media_director import picture_for, slug
from platform_core.interview.models import BusinessBlueprint, CatalogueGroup, TargetState
from platform_core.interview.taxonomy import normalise_name
from platform_core.interview.website_copy import WebsiteCopy
from platform_core.validation.website import validate_generation_payload

COMPOSER_VERSION = "creative-composer-v4"

# What the browse section is called, by archetype. "What we do" is for services
# only — for a shop it hides the fact that there are things to buy.
BROWSE_TITLE = {
    "product_commerce": "Shop by category", "menu_commerce": "Our menu",
    "membership_fitness": "Programmes & plans", "real_estate_projects": "Featured projects",
    "service_appointment": "Services", "b2b_rfq": "What we supply",
    "project_portfolio": "What we make", "local_service": "Services",
}
NAV_BROWSE = {
    "product_commerce": "Shop", "menu_commerce": "Menu", "membership_fitness": "Programmes",
    "real_estate_projects": "Projects", "service_appointment": "Services", "b2b_rfq": "Products",
    "project_portfolio": "Work", "local_service": "Services",
}
_COMMERCE = {"product_commerce", "menu_commerce"}
# Headings that could sit on any site. "Available options" came back from a
# live gym build; the section is its programmes and plans.
_GENERIC_TITLE = re.compile(
    r"^\s*(what we do|our services|what we offer|our offerings|(?:available|our) options|"
    r"our products|products|offerings|services|our items|items|browse|explore)\s*$", re.I)


def _expected_pictures(bp: BusinessBlueprint) -> int:
    """Pictures this site will have once its media plan is done: the ready
    ones, and the drafts still to be drawn where drawing is possible."""
    ready = sum(1 for p in bp.media_plan if p.status == "ready")
    planned = sum(1 for p in bp.media_plan
                  if p.status == "planned" and p.source in {"gemini_generated", "stock_retrieved"})
    if planned:
        from platform_core.website.image_generation import pictures_available

        if not pictures_available():
            planned = 0
    return ready + planned


def _facts(bp: BusinessBlueprint) -> dict[str, str]:
    return {k: f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items()}


def _answer(bp: BusinessBlueprint, target: str) -> str:
    state = bp.discovery.get(target)
    if not state or state.status not in {"answered", "partial"}:
        return ""
    return f"{state.summary} {state.quote}".strip()


def _display_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    return ""


def _place(text: str) -> str:
    """A tidy place name from "In nookampalayam road" -> "Nookampalayam Road"."""
    text = re.sub(r"^\s*(?:in|at|near|on)\s+", "", " ".join((text or "").split()), flags=re.I).strip(" .,")
    if not text or len(text) > 60:
        return ""
    small = {"and", "of", "the", "near", "to", "in", "on", "only", "or"}
    return " ".join(
        w if w.isupper() or any(c.isdigit() for c in w) else w.lower() if i and w.lower() in small
        else w.capitalize()
        for i, w in enumerate(text.split())
    )


def _places(bp: BusinessBlueprint) -> list[str]:
    """Each place the owner named, in the order they said them.

    Locations accumulate ("Coimbatore; our home in Saibaba Colony"): the town
    for the eyebrow, the most specific place for pickup and the address.
    """
    raw = _facts(bp).get("locations", "")
    parts: list[str] = []
    for part in raw.split(";"):
        part = re.sub(r"^\s*(?:in|at|near|on)\s+", "", " ".join(part.split()), flags=re.I).strip(" .,")
        if part and all(part.casefold() != seen.casefold() for seen in parts):
            parts.append(part)
    # "Chennai" adds nothing to "OMR, Thoraipakkam, Chennai".
    return [p for p in parts if not any(p != o and p.casefold() in o.casefold() for o in parts)]


def _town(bp: BusinessBlueprint) -> str:
    parts = [p for p in _places(bp) if not re.match(r"(?:our|my)\b", p, re.I)]
    return _place(parts[0]) if parts else ""


def _home_based(bp: BusinessBlueprint) -> bool:
    """A home kitchen or home baker: pickup is from their home, not a store."""
    sub = (bp.category.subcategory_key if bp.category else "") or ""
    said = " ".join(m.text for m in bp.messages if m.role == "user")
    return sub.startswith("home_") or bool(re.search(
        r"\b(?:from (?:my|our) home|at (?:my|our) home|home kitchen|veet(?:la|il|ile)|veedu)\b", said, re.I))


def _pickup_line(bp: BusinessBlueprint) -> str:
    parts = _places(bp)
    if _home_based(bp):
        spot = _place(parts[-1]) if parts else ""
        return f"Collect your order from our home in {spot}." if spot else "Collect your order from our home."
    if not parts:
        return "Collect your order from the shop."
    spot = parts[-1]
    if re.match(r"(?:our|my)\b", spot, re.I):
        return f"Collect your order from {spot[0].lower() + spot[1:]}."
    return f"Collect your order at {_place(spot) or spot}."


def _address(bp: BusinessBlueprint) -> str:
    parts = _places(bp)
    if len(parts) > 1:
        # Most specific first: "Our home in Saibaba Colony, Coimbatore".
        text = ", ".join(reversed(parts))
        return text[0].upper() + text[1:]
    return parts[0] if parts else ""


def _join(names: list[str], word: str = "and") -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {word} " + names[-1]


def _seen(bp: BusinessBlueprint, business_type: str | None) -> set[str]:
    from platform_core.interview.discovery import characteristics

    return {c for c, how in characteristics(bp, business_type).items() if how == "observed"}


# ----------------------------------------------------------------- facts


def ordering_facts(bp: BusinessBlueprint, business_type: str | None) -> list[dict[str, str]]:
    """How buying works, from the owner's answers — each item a real fact."""
    seen = _seen(bp, business_type)
    units = _answer(bp, "offerings.units").lower()
    mode = _answer(bp, "fulfilment.mode").lower()
    area_state = bp.discovery.get("fulfilment.area")
    payment = _answer(bp, "commerce.payment").lower()
    items: list[dict[str, str]] = []
    if re.search(r"\b(kg|kilo|weight|gram)", units):
        items.append({"kind": "weight", "title": "Choose your weight",
                      "body": "Pick the cut, pick the quantity — ordered by the kg."})
    elif units:
        items.append({"kind": "order", "title": "Choose what you need",
                      "body": (bp.discovery["offerings.units"].summary or "")[:160]})
    delivers = "delivers" in seen or re.search(r"\bdeliver", mode)
    pickup = "pickup" in seen or re.search(r"pick ?up|collect|takeaway", mode)
    area_text = (area_state.quote or area_state.summary) if area_state and area_state.status == "answered" else ""
    courier = re.search(r"\b(courier|ship|shipping|shipped|post|parcel|dispatch)\w*", f"{mode} {area_text}", re.I)
    if delivers or courier:
        where = _area(area_text)
        if courier:
            items.append({"kind": "delivery", "title": "Sent by courier",
                          "body": f"Across {where}." if where else "Packed and sent to you."})
        else:
            items.append({"kind": "delivery", "title": "Home delivery",
                          "body": (f"Delivered {where}." if where.startswith("within ") else f"Delivered around {where}.")
                          if where else "Brought to your door."})
    if pickup:
        items.append({"kind": "pickup", "title": "Pickup", "body": _pickup_line(bp)})
    if payment:
        # Only the ways the owner named, in their order — no "securely", no "instant".
        named = [label for pattern, label in (
            (r"\bupi\b|gpay|google pay|phonepe|paytm", "UPI"), (r"\bcards?\b", "card"),
            (r"bank transfer|neft|imps", "bank transfer"), (r"\bonline\b", "online"),
            (r"cash on delivery|\bcod\b", "cash on delivery"), (r"\bcash\b", "cash"),
        ) if re.search(pattern, payment)]
        if "cash on delivery" in named and "cash" in named:
            named.remove("cash")
        if named:
            body = " or ".join(dict.fromkeys(named))
            if re.search(r"\bbefore\b.*\b(dispatch|deliver|ship)", payment):
                body += ", before dispatch"
            items.append({"kind": "payment", "title": "How to pay", "body": body[0].upper() + body[1:] + "."})
    return items[:4]


def _area(text: str) -> str:
    """ "All over Tamil Nadu by courier." -> "Tamil Nadu"; "around X and Y" -> "X and Y"."""
    raw = re.sub(r"\b(?:by|through|via)\s+(?:courier|post|parcel)\w*", "", text, flags=re.I)
    raw = re.sub(r"^\s*(?:we\s+)?(?:deliver|ship|send|courier)\w*\s+", "", raw.strip(), flags=re.I)
    raw = re.sub(r"^(?:all over|across|anywhere in|throughout|around|in|to|within)\s+", "", raw.strip(), flags=re.I)
    raw = raw.strip(" .,")
    # "3 km kulla" (Tamil: within 3 km) / "within 5 km" — a radius, not a place.
    radius = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kms|kilomet\w*)\b(?:\s*(?:kulla|kulle|ulla|ulle|radius))?",
                       raw, re.I)
    if radius and re.search(r"kulla|kulle|ulla|ulle", text, re.I):
        return f"within {radius.group(1)} km"
    if radius and raw.lower().startswith(radius.group(1)):
        return f"within {raw}"[:60]  # "within 5 km of Adyar"
    return _place(raw) if raw and len(raw) <= 60 else ""


def visit_facts(bp: BusinessBlueprint) -> list[dict[str, str]]:
    """How visiting or booking works, from the owner's answers — each a real fact.

    The booking-led counterpart of `ordering_facts`: how to book, what is
    booked, the hours, where. Nothing that was not said.
    """
    from platform_core.interview.understanding import customer_actions

    items: list[dict[str, str]] = []
    labels = {"book_online": "Book online", "book_whatsapp": "Book on WhatsApp", "book_call": "Book by phone",
              "book_trial": "A free trial first", "book_site_visit": "Site visits", "check_dates": "Check dates",
              "book_table": "Book a table", "book_consultation": "Book a consultation", "visit": "Walk in",
              "enquire": "Ask on WhatsApp or call"}
    said = [a for a in customer_actions(bp) if a in labels]
    if said:
        items.append({"kind": "book", "title": labels[said[0]], "body": _booking_sentence(bp, said[0])})
    hours = _facts(bp).get("opening_hours", "")
    if hours:
        items.append({"kind": "hours", "title": "Opening hours", "body": hours[:160]})
    where = _address(bp)
    if where:
        items.append({"kind": "place", "title": "Where to find us", "body": where[:160]})
    return [i if i["body"] else {"kind": i["kind"], "title": i["title"]} for i in items][:4]


_BOOKING_WORDS = {
    "book_trial": r"\btrial\b", "book_site_visit": r"\bsite visit|\bvisit\b", "book_table": r"\btable\b",
    "book_consultation": r"\bconsult", "check_dates": r"\bdates?\b|\bavailab", "visit": r"\bwalk|\bvisit\b",
}


def _booking_sentence(bp: BusinessBlueprint, action: str) -> str:
    """The owner's own sentence about how that booking works — or nothing.

    Never a summary glued to a quote ("Sign up, Book a trial, WhatsApp Monthly
    membership is 3500…"): one sentence the owner said, that names it.
    """
    words = _BOOKING_WORDS.get(action, r"\bbook|\bappointment|\bslot")
    said = [_answer(bp, "bookings.format"), (bp.discovery.get("commerce.action") or TargetState()).quote,
            *(m.text for m in bp.messages if m.role == "user")]
    for text in said:
        for sentence in re.split(r"(?<=[.!?])\s+|\s[—–]\s", " ".join((text or "").split())):
            if re.search(words, sentence, re.I) and not re.search(r"\d{3,}", sentence) and len(sentence) <= 140:
                sentence = sentence.strip(" .")
                return (sentence[0].upper() + sentence[1:] + ".") if sentence else ""
    return ""


def hero_badges(bp: BusinessBlueprint, business_type: str | None) -> list[str]:
    """Short true chips under the headline — never a rating, a count or an award."""
    badges: list[str] = []
    for item in ordering_facts(bp, business_type):
        home = "from our home" in item["body"] or "from my home" in item["body"]
        label = {"weight": "Sold by the kg", "delivery": item["title"],
                 "pickup": "Pickup available" if home else "Store pickup",
                 "payment": item["body"].rstrip(".")}.get(item["kind"])
        if label and label not in badges:
            badges.append(label[:40])
    return badges[:3]


# ------------------------------------------------------------- sections


def money(price: str) -> str:
    """The owner's price as a visitor reads it: bare digits are rupees ("240" -> "₹240")."""
    price = " ".join(price.split())
    lead = re.match(r"(from|starting (?:at|from)|starts at)\s+(?=\d)", price, re.I)
    if lead:  # "from 1.2 crore" -> "From ₹1.2 crore"
        return "From " + money(price[lead.end():])
    if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", price):
        return f"₹{price}"
    if re.match(r"\d[\d,.]*\s*(?:crores?|cr|lakhs?|lacs?|l|k)\b", price, re.I):
        return f"₹{price}"
    return re.sub(r"^(?:rs\.?|inr)\s*", "₹", price, flags=re.I)


def _amount(price: str) -> float:
    digits = re.sub(r"[^\d.]", "", price)
    try:
        return float(digits)
    except ValueError:
        return float("inf")


def _group_meta(group: CatalogueGroup) -> str:
    if group.price:
        return f"From {money(group.price)} {group.unit}".strip()[:60]
    priced = [i for i in group.items if i.price]
    if priced:
        low = min(priced, key=lambda i: _amount(i.price))
        prefix = "From " if len(priced) > 1 else ""
        return f"{prefix}{money(low.price)} {low.unit or group.unit}".strip()[:60]
    if re.search(r"\b(kg|kilo|weight)", group.sold_by, re.I):
        return "Sold by the kg"
    return ""


def _line(copy: WebsiteCopy, name: str, kind: str) -> str:
    lines = copy.category_lines if kind == "category" else copy.item_lines
    return next((c.line for c in lines if c.name.casefold() == name.casefold()), "")


def browse_sections(
    bp: BusinessBlueprint, direction: CreativeDirection, copy: WebsiteCopy, order_label: str
) -> list[dict[str, Any]]:
    """Categories and items, presented the way this kind of site browses."""
    groups = [g for g in bp.taxonomy.groups if g.name]
    if not groups:
        return []
    arche = direction.archetype
    # The trade's own heading first ("Our menu", "Treatments", "Classes & timings");
    # the archetype's only when the trade is unknown.
    default = _trade_heading(bp, arche)
    title = copy.products_title or copy.categories_title or default
    if _GENERIC_TITLE.match(title) and not _GENERIC_TITLE.match(default):
        title = default
    drafts = {o.name.casefold(): o for o in bp.website_draft.offerings}
    # The owner's choice about prices wins: none, "on request", or starting prices only.
    prices = bp.owner_choices.price_visibility or "show"
    items: list[dict[str, Any]] = []
    for group in groups:
        for item in group.items:
            name, vague = normalise_name(item.name)
            if not name or vague:
                continue  # "fish different varieties" is not a product
            # "Projects" above every project says nothing: a generic group is no label.
            entry: dict[str, Any] = {"name": name[:80]}
            if not _GENERIC_GROUP.match(group.name):
                entry["category"] = group.name[:80]
            description = item.description or _line(copy, name, "item")
            if not description and arche == "real_estate_projects":
                description = project_status(bp, name)
            draft = drafts.get(name.casefold())
            if not description and draft and draft.description:
                description = draft.description.text
            if description:
                entry["description"] = description[:200]
            if item.price and prices == "show":
                entry["price"] = money(item.price)[:40]
                if item.unit:
                    entry["unit"] = item.unit[:40]
            elif prices == "on_request" and (item.price or group.price):
                entry["price"] = "Price on request"
            elif group.price and arche == "real_estate_projects" and prices in {"show", "from"}:
                # "Villas from 1.2 crore": the owner's starting price for the kind.
                shown = money(group.price)
                entry["price"] = (shown if shown.startswith("From ") else f"From {shown}")[:40]
            picture = picture_for(bp, f"item:{slug(name)}") or picture_for(bp, f"project:{slug(name)}")
            if picture:
                entry["image_asset_id"] = picture
            # Veg or non-veg, how hot, the owner's own "Bestseller" — as they said it.
            entry.update(item_traits(item))
            items.append(entry)
    categories: list[dict[str, Any]] = []
    for group in groups:
        card: dict[str, Any] = {"name": group.name[:80]}
        description = group.description or _line(copy, group.name, "category")
        draft = drafts.get(group.name.casefold())
        if not description and draft and draft.description:
            description = draft.description.text
        if description:
            card["description"] = description[:200]
        tags = [i.name for i in group.items if not normalise_name(i.name)[1]][:6]
        if tags:
            card["tags"] = tags
        meta = _group_meta(group) if prices in {"show", "from"} else (
            "Price on request" if prices == "on_request" and (group.price or any(i.price for i in group.items))
            else "Sold by the kg" if re.search(r"\b(kg|kilo|weight)", group.sold_by, re.I) else "")
        if meta:
            card["meta"] = meta
        picture = picture_for(bp, f"category:{slug(group.name)}")
        if picture:
            card["image_asset_id"] = picture
        categories.append(card)

    subtitle = copy.offerings_subtitle
    out: list[dict[str, Any]] = []
    has_item_pictures = sum(1 for i in items if i.get("image_asset_id")) >= 2
    if items:
        variant = direction.product_variant
        if arche == "product_commerce" and not has_item_pictures:
            variant = "category_boards"  # a board per category: one picture, its cuts listed
        elif variant == "menu_grid" and not has_item_pictures:
            variant = "category_boards" if any(c.get("image_asset_id") for c in categories) else "compact_list"
        content: dict[str, Any] = {
            "title": title[:120], "anchor": "shop", "items": items[:48],
            "categories": categories[:12], "filters": [g.name[:40] for g in groups][:10],
        }
        if subtitle:
            content["subtitle"] = subtitle[:300]
        if order_label:
            content["order_label"] = order_label[:40]
        out.append({"section_type_id": "product_showcase", "layout_variant": variant, "content": content})
    else:
        variant = direction.category_variant
        if variant == "image_cards" and not any(c.get("image_asset_id") for c in categories):
            variant = "tiles"
        if variant == "chips":
            variant = "image_cards" if any(c.get("image_asset_id") for c in categories) else "tiles"
        content = {"title": title[:120], "anchor": "shop", "items": categories[:8]}
        if subtitle:
            content["subtitle"] = subtitle[:300]
        out.append({"section_type_id": "category_showcase", "layout_variant": variant, "content": content})
    return out


def compose_site(
    bp: BusinessBlueprint,
    direction: CreativeDirection,
    copy: WebsiteCopy,
    *,
    business_type: str | None,
    contact: dict[str, Any],
    active_modules: frozenset[str],
    capability_rows: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The whole website payload: pages, navigation and theme."""
    facts = _facts(bp)
    name = bp.identity["display_name"].value if "display_name" in bp.identity else "Our business"
    arche = direction.archetype
    phone = contact.get("phone", "")
    whatsapp = contact.get("whatsapp", "")
    # Stored content never holds an external URL: "whatsapp:" is resolved when
    # the page renders, from the number the business published.
    wa_link = WHATSAPP if whatsapp else ""

    # What a visitor can actually do. A cart only where ordering is switched on
    # AND there are live items to put in it — decided at render time.
    order_label = ""
    if arche in _COMMERCE:
        order_label = "Order on WhatsApp" if whatsapp else "Call to order" if phone else ""
    elif arche == "real_estate_projects":
        order_label = "Enquire on WhatsApp" if whatsapp else "Call to enquire" if phone else ""
    browse = browse_sections(bp, direction, copy, order_label)
    booking = "bookings" in active_modules and arche in {"service_appointment", "membership_fitness"}
    dims = direction.dimensions or {}
    if booking:
        primary = (copy_cta(bp) or _BOOK_LABEL.get(str(dims.get("primary_action", "")), "Book now"), "/book")
    elif browse:
        default = _browse_cta(bp, arche, str(dims.get("offering", "")), str(dims.get("audience", "")))
        label = copy_cta(bp)
        # A label that names a channel ("Order on WhatsApp") must not scroll to
        # the menu: that button is the browse one; Call and WhatsApp sit beside it.
        if _CHANNEL.search(label):
            label = ""
        primary = (label or default, "#shop")
    elif wa_link:
        primary = ("Message on WhatsApp", wa_link)
    else:
        primary = ("", "")

    hero: dict[str, Any] = {
        "headline": (copy.headline or designed_headline(bp, arche) or name)[:120],
        "subheadline": (copy.subheadline or designed_subheadline(bp, business_type))[:300],
    }
    if copy.headline and copy.headline_accent and copy.headline_accent in copy.headline:
        hero["headline_accent"] = copy.headline_accent[:60]
    elif not copy.headline:
        accent = designed_accent(hero["headline"])
        if accent:
            hero["headline_accent"] = accent
    place = _town(bp)
    if place:
        hero["eyebrow"] = place[:60]
    if primary[0] and primary[1]:
        hero["cta_label"], hero["cta_url"] = primary[0][:60], primary[1][:500]
    badges = hero_badges(bp, business_type)
    if arche not in _COMMERCE:
        # "UPI or cash" under a gym's hero reads as filler; how a shop takes
        # money is part of buying, how a gym does is a detail for later.
        paying = {f["body"].rstrip(".") for f in ordering_facts(bp, business_type) if f["kind"] == "payment"}
        badges = [b for b in badges if b not in paying]
    if badges:
        hero["badges"] = badges
    hero_picture = picture_for(bp, "hero")
    if hero_picture:
        hero["image_asset_id"] = hero_picture
    if not hero["subheadline"]:
        hero.pop("subheadline")

    # Every section this business has something true to say in, by role; the
    # architecture below decides which appear and in what order.
    parts: dict[str, list[dict[str, Any]]] = {
        "hero": [{"section_type_id": "hero", "layout_variant": direction.hero, "content": hero}],
        "catalogue": browse,
    }
    ordering = ordering_facts(bp, business_type)
    if arche not in _COMMERCE and len(ordering) < 2:
        # A booking- or visit-led business: how visiting or booking works.
        visiting = visit_facts(bp)
        if len(visiting) >= 2:
            parts["how"] = [{"section_type_id": "fulfilment_strip", "layout_variant": "icons", "content": {
                "title": (copy.steps_title or "Good to know")[:120], "anchor": "visit", "items": visiting}}]
    if len(ordering) >= 2:
        parts["how"] = [{
            "section_type_id": "fulfilment_strip", "layout_variant": "icons",
            "content": {"title": (copy.steps_title or ("How ordering works" if arche in _COMMERCE
                                                     else "Good to know"))[:120],
                        "anchor": "ordering", "items": ordering},
        }]
    if copy.steps:
        # How customers work with the business, each step from the owner's own sentence.
        parts["steps"] = [{"section_type_id": "feature_grid", "layout_variant": "steps", "content": {
            "title": (copy.steps_title or "How it works")[:120],
            "items": [{"title": st.title[:80], "body": st.body[:240]} for st in copy.steps[:4]]}}]
    plans = plans_from_answer(bp) if arche == "membership_fitness" else []
    if plans:
        parts["plans"] = [{"section_type_id": "product_showcase", "layout_variant": "plan_cards", "content": {
            "title": "Memberships", "anchor": "memberships", "items": plans}}]
        if primary[1] == "#shop" and "plan" in primary[0].lower():
            # "See plans" goes to the plans the owner listed. (Not "#plans":
            # that means joining online, which needs the memberships tool.)
            primary = (primary[0], "#memberships")
            hero["cta_url"] = "#memberships"
    served = served_list(bp)
    if served:
        parts["served"] = [{"section_type_id": "feature_grid", "layout_variant": "list", "content": {
            "title": "Industries we serve" if arche == "b2b_rfq" else "Who we work with",
            "items": [{"title": item[:80]} for item in served[:9]]}}]
    if len(bp.highlights) >= 2:
        parts["proof"] = [{"section_type_id": "highlights", "layout_variant": "strip", "content": {
            "items": [{"value": h.value[:24], "label": h.label[:40]} for h in bp.highlights[:6]]}}]

    from_owner = not copy.about_body
    story_body = copy.about_body or owner_story(bp)
    # The owner's own answer to "what should people remember?" is the story's
    # line; a claim the model filed is only the fallback ("Crab and squid
    # cleaned and sold by kg" was quoted as the shop's story).
    remembered = (bp.discovery.get("brand.story") or TargetState()).quote
    claims = [_first_sentence(remembered)] if remembered else []
    claims += [c.claim for c in bp.website_draft.owner_claims]
    story_picture: str | None = None
    if story_body:
        story: dict[str, Any] = {"title": (copy.about_title or "Our story")[:120], "body": story_body[:2000],
                                 "eyebrow": "Our story", "anchor": "story"}
        # A pull quote beside a written story; not the same words twice when the
        # story IS the owner's own answer.
        if claims and not (from_owner and _plain_text(claims[0]) in _plain_text(story_body)):
            story["quote"] = claims[0][:200]
        # Its own picture first; else the first category's (the last one was
        # just shown above); the hero only as a last resort.
        story_picture = picture_for(bp, "story")
        if not story_picture and bp.taxonomy.groups:
            story_picture = picture_for(bp, "category:" + slug(bp.taxonomy.groups[0].name))
        story_picture = story_picture or hero_picture
        if story_picture:
            story["image_asset_id"] = story_picture
        parts["story"] = [{"section_type_id": "about",
                           "layout_variant": direction.story_variant if story_picture else "text_only",
                           "content": story}]

    if phone or whatsapp or (primary[0] and primary[1]):
        band: dict[str, Any] = {
            "headline": (copy.closing_headline or _closing(arche, name))[:200],
            "cta_label": (primary[0] or ("Call now" if phone else ""))[:60] or "Get in touch",
            "cta_url": primary[1][:500],
        }
        if copy.closing_body:
            band["body"] = copy.closing_body[:500]
        # A picture the page has not already shown, where there is one.
        band_picture = _unshown_picture(bp, {hero_picture, story_picture}) or hero_picture
        if band_picture:
            band["image_asset_id"] = band_picture
        parts["cta"] = [{"section_type_id": "cta_band",
                         "layout_variant": "image_banner" if band_picture else "centered",
                         "content": band}]

    contact_section: dict[str, Any] = {"title": (copy.contact_title or ("Visit us" if place else "Get in touch"))[:120],
                                       "show_map": False}
    display = _display_phone(facts.get("phone", ""))
    if display:
        contact_section["phone"] = display
    if _address(bp):
        contact_section["address"] = _address(bp)[:500]
    if facts.get("email"):
        contact_section["email"] = facts["email"][:200]
    if facts.get("opening_hours"):
        contact_section["hours_summary"] = facts["opening_hours"][:500]
    if len(contact_section) > 2:
        parts["contact"] = [{"section_type_id": "contact", "layout_variant": "full", "content": contact_section}]

    sections = [section for role in page_architecture(arche, direction.page_order) for section in parts.get(role, [])]

    lead = bp.website_prefs.lead_section
    if lead:
        # "Put delivery higher": the section the owner named comes right after the hero.
        found = next((s for s in sections[1:] if s["section_type_id"] == lead), None)
        if found:
            sections.remove(found)
            sections.insert(1, found)

    # How this site moves and which scenes it is built from (experience.py):
    # chosen from what the page really carries, so a ring only where there
    # are pictures for it and a menu book only where there are dishes.
    experience = choose_experience(
        bp, archetype=arche, family=direction.family, dims=dims, sections=sections,
        expected_pictures=_expected_pictures(bp),
        choices=(direction.model_choices or {}).get("experience") or None,
    )
    showcases = [s for s in sections if s["section_type_id"] == "product_showcase"]
    for section in sections:
        kind = section["section_type_id"]
        if kind == "hero" and experience.hero:
            section["layout_variant"] = experience.hero
        elif kind == "about" and experience.story:
            section["layout_variant"] = experience.story
        elif kind == "cta_band" and experience.cta:
            section["layout_variant"] = experience.cta
        elif kind == "highlights" and experience.motion != "calm":
            section["layout_variant"] = "counters"
    if not showcases and experience.catalogue in {"rail", "bento"}:
        # A range known only by its categories takes the same composition.
        categories = next((s for s in sections if s["section_type_id"] == "category_showcase"), None)
        if categories:
            categories["layout_variant"] = experience.catalogue
    if showcases and experience.catalogue:
        showcases[0]["layout_variant"] = experience.catalogue
        # A second range (a gym's memberships under its programmes) stacks,
        # unless the first already does.
        for extra in showcases[1:]:
            if experience.catalogue != "stack" and extra["layout_variant"] == "plan_cards":
                extra["layout_variant"] = "stack"
    if experience.marquee:
        words = marquee_words(sections, list(hero.get("badges") or []))
        if len(words) >= 3:
            sections.insert(1, {"section_type_id": "marquee", "layout_variant": experience.marquee,
                                "content": {"items": words}})

    for section in sections:
        section["is_visible"] = True

    anchors = {s["content"].get("anchor") for s in sections}
    navigation = [{"label": "Home", "path": "/"}]
    if "shop" in anchors:
        navigation.append({"label": _trade_nav(bp, arche), "path": "/#shop"})
    if "story" in anchors:
        navigation.append({"label": "About", "path": "/#story"})
    if any(s["section_type_id"] == "contact" for s in sections):
        navigation.append({"label": "Contact", "path": "/#contact"})

    palette = direction.palette
    theme: dict[str, Any] = {
        # Kept for the renderer's older paths; the direction below is what it reads now.
        "personality": "dark" if palette.mode == "dark" else "clean",
        "primary_color": palette.primary,
        "accent_color": palette.accent,
        "background_color": palette.surface,
        "text_color": palette.ink,
        "surface_alt_color": palette.surface_alt,
        "muted_color": palette.muted,
        "palette_mode": palette.mode,
        "site_archetype": arche,
        "reference_profile": direction.reference_profile,
        # design-system v3 — read by the renderer as data-family / data-variant / …
        "design_family": direction.family,
        "design_variant": direction.variant,
        "palette_key": direction.palette_key,
        "palette_hue": direction.palette_hue,
        "rhythm": direction.rhythm,
        "image_treatment": direction.image_treatment,
        "surface": direction.surface,
        "footer_style": direction.footer,
        "type_system": direction.type_system,
        "hero_style": direction.hero,
        "card_style": direction.cards,
        "nav_style": direction.nav,
        "motion_preference": "subtle",
        "motion_intensity": direction.motion,
        # The type system below chooses the faces; the older direction must
        # not layer its serif and weights on top of it.
        "typography_direction": "modern_sans",
        "creative_direction": direction.model_dump(mode="json"),
        # Motion language and scenes — read by the renderer's experience layer.
        "experience": experience.theme(),
        "mobile": direction.mobile,
        "composer_version": COMPOSER_VERSION,
        "generation": meta or {},
    }
    if arche in _COMMERCE and wa_link and primary[1] == "#shop":
        # The one button always in view is the one that orders.
        theme["nav_cta"] = {"label": "Order on WhatsApp", "href": wa_link}
    elif primary[0] and primary[1]:
        theme["nav_cta"] = {"label": primary[0][:40], "href": primary[1][:500]}
    utility: list[str] = []
    for item in ordering:
        if item["kind"] == "delivery":
            utility.append(item["body"].rstrip("."))
    if display:
        utility.append(display)
    if utility and direction.nav == "commerce":
        theme["utility_bar"] = utility[:2]

    home = {
        "slug": "home", "title": "Home", "page_type": "home", "sections": sections,
        "seo_title": name[:160],
        "seo_description": (hero.get("subheadline") or facts.get("description", ""))[:300],
    }
    from platform_core.interview.semantic_design import validate as validate_semantics

    checked, findings = validate_semantics(
        {"pages": [home], "navigation": navigation, "theme_hints": theme}, bp, direction)
    payload: dict[str, Any] = validate_generation_payload(checked)
    issues = quality_issues(payload, arche)
    payload["theme_hints"]["quality"] = {
        "valid": not issues, "issues": issues,
        "repair_count": sum(1 for f in findings if f.severity == "fail"),
        # Business semantics vs navigation, calls to action, titles and media.
        "semantic": [f.as_dict() for f in findings],
    }
    return payload


# The main button says what this visitor does next — not a generic verb.
_BOOK_LABEL = {
    "book_table": "Book a table", "book_trial": "Book a free trial", "book_consultation": "Book a consultation",
    "book_site_visit": "Book a site visit", "check_dates": "Check dates", "book_online": "Book now",
    "book_whatsapp": "Book now", "book_call": "Book now",
}


def _browse_cta(bp: BusinessBlueprint, arche: str, offering: str, audience: str) -> str:
    """The button that takes a visitor to what the business offers, in its own terms."""
    from platform_core.interview.playbooks import playbook_for

    label = playbook_for(bp).browse_label
    by_offering = {
        "menu": "See the menu", "weighed_product": "Shop now", "plan": "See plans", "property": "View projects",
        "portfolio": "See the work", "stay": "See the rooms", "b2b_catalogue": "See the range",
        "product": "See the range" if audience == "b2b" else "Shop now",
    }
    if offering in by_offering:
        return by_offering[offering]
    if label and label not in {"Services", "Shop"}:
        return f"See {label.lower()}"[:40]
    return {"menu_commerce": "See the menu", "real_estate_projects": "View projects",
            "membership_fitness": "See plans"}.get(arche, "See what we do")


def _trade_heading(bp: BusinessBlueprint, arche: str) -> str:
    from platform_core.interview.playbooks import playbook_for

    pb = playbook_for(bp)
    return pb.browse_title if pb.key != "other" else BROWSE_TITLE[arche]


def _trade_nav(bp: BusinessBlueprint, arche: str) -> str:
    from platform_core.interview.playbooks import playbook_for

    pb = playbook_for(bp)
    return pb.browse_label if pb.key != "other" else NAV_BROWSE[arche]



# ------------------------------------------------------ page architecture
#
# Which sections a site has, and in what order, follows what the business is:
# a kitchen leads with its menu and how ordering works; a gym with programmes
# and plans, then proof; a developer with projects and its record; a B2B
# supplier with product families, who it serves and how buying works. The
# model may reorder or drop the optional roles (never hero, catalogue, the
# closing band or contact), and a role with nothing true to show is left out.

ARCHITECTURE: dict[str, tuple[str, ...]] = {
    "menu_commerce": ("hero", "catalogue", "how", "story", "proof", "cta", "contact"),
    "product_commerce": ("hero", "catalogue", "how", "story", "proof", "cta", "contact"),
    "membership_fitness": ("hero", "catalogue", "plans", "proof", "how", "steps", "story", "cta", "contact"),
    "real_estate_projects": ("hero", "catalogue", "proof", "story", "steps", "how", "cta", "contact"),
    "b2b_rfq": ("hero", "catalogue", "served", "steps", "proof", "story", "how", "cta", "contact"),
    "service_appointment": ("hero", "catalogue", "steps", "how", "story", "proof", "cta", "contact"),
    "project_portfolio": ("hero", "catalogue", "story", "steps", "proof", "how", "cta", "contact"),
    "local_service": ("hero", "catalogue", "how", "steps", "story", "proof", "cta", "contact"),
}
_FIXED_ROLES = ("hero", "catalogue", "cta", "contact")


def page_architecture(archetype: str, proposed: list[str] | None = None) -> list[str]:
    """The order of roles on the page: the archetype's recipe, or the model's
    proposal when it only reorders or drops optional roles of that recipe."""
    recipe = list(ARCHITECTURE.get(archetype, ARCHITECTURE["local_service"]))
    if not proposed:
        return recipe
    middle = [r for r in dict.fromkeys(proposed) if r in recipe and r not in _FIXED_ROLES]
    return ["hero", "catalogue", *middle, "cta", "contact"]


_GENERIC_GROUP = re.compile(r"^(?:our )?(projects?|services?|products?|items?|offerings?|work|portfolio|"
                            r"range|catalogue|menu|options)$", re.I)
_KINDS = re.compile(r"\b(villas?|apartments?|plots?|flats?|homes?|row houses?|commercial spaces?|offices?)\b", re.I)


def _headline_name(text: str) -> str:
    name = re.sub(r"^(?:a|an|the|our)\s+", "", text.strip(), flags=re.I)
    return name[0].upper() + name[1:] if name else ""


def designed_headline(bp: BusinessBlueprint, archetype: str) -> str:
    """A headline with a point of view, from the owner's own words, when no model
    wrote one: what they offer and where ("Podis, Pickles & Sweets in Coimbatore")."""
    names: list[str] = []
    for group in bp.taxonomy.groups:
        name, vague = normalise_name(group.name)
        if name and not vague and not _GENERIC_GROUP.match(name):
            names.append(_headline_name(name))
    if not names and archetype == "real_estate_projects":
        # "Projects" says nothing; the kinds the owner builds do ("villas and apartments").
        said = " ".join(f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items()
                        if k in {"description", "offerings"})
        names = list(dict.fromkeys(m.group(1).lower() for m in _KINDS.finditer(said)))
        names = [n[0].upper() + n[1:] for n in names]
    if not names:
        return ""
    word = "and" if any("&" in n for n in names) else "&"
    head = _join(names[:3], word)
    if len(head) > 34:
        head = _join(names[:2], word)
    # The place, as short as it can be said: "Coimbatore", not "Saibaba Colony,
    # Coimbatore" (the eyebrow carries the full place). A headline that would
    # sprawl drops it — "Chicken, Mutton & Fish" says enough.
    place = _town(bp).split(",")[-1].strip()
    latin = all(re.fullmatch(r"[\x00-\x7F’–—]+", n) for n in names)
    joiner = "across" if archetype == "real_estate_projects" else "in"
    return f"{head} {joiner} {place}" if place and latin and len(head) + len(place) <= 40 else head


def designed_accent(headline: str) -> str:
    """The second voice of a designed headline: what follows its first item."""
    head = re.split(r" (?:in|across) ", headline, maxsplit=1)[0]
    for sep in (", ", " & ", " and "):
        first, found, rest = head.partition(sep)
        if found and rest:
            return rest
    return ""


def designed_subheadline(bp: BusinessBlueprint, business_type: str | None) -> str:
    """One plain line of how buying works, from the owner's answers — never the
    raw first sentence of a Tamil or Tanglish answer."""
    description = _first_sentence(_facts(bp).get("description", ""))
    if description and reads_as_english(description) and len(description) > 24:
        return description
    facts = [f["body"].rstrip(".") for f in ordering_facts(bp, business_type) if f["kind"] in {"delivery", "pickup"}]
    from platform_core.interview.understanding import customer_actions

    actions = {"order_whatsapp": "Order on WhatsApp", "order_online": "Order online", "order_call": "Order by phone",
               "book_online": "Book online", "book_whatsapp": "Book on WhatsApp", "book_call": "Book by phone",
               "request_quote": "Ask for a quotation", "book_site_visit": "Book a site visit",
               "book_trial": "Book a free trial"}
    lead = next((actions[a] for a in customer_actions(bp) if a in actions), "")
    line = " · ".join(p for p in [lead, *facts[:1]] if p)
    return line or description


def owner_story(bp: BusinessBlueprint) -> str:
    """The story in the owner's own words when no model wrote one: their answer
    to "what should people remember?", as they said it (English only)."""
    state = bp.discovery.get("brand.story")
    if not state or state.status not in {"answered", "partial"} or bp.language_style != "en":
        return ""
    words = " ".join((state.quote or state.summary or "").split())
    return words if len(words) >= 24 and reads_as_english(words) else ""


_ENGLISH = frozenset("a an the and or but we our us i my me is are was be to of in on at for from with by "
                     "it its this that you your they their all every only just who what how when".split())


def reads_as_english(text: str) -> bool:
    """Whether a sentence the owner typed is English, not Tanglish or Tamil —
    "Naan veetla irundhu home food pannuren" is not a website subheadline."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words or len(words) < len(text.split()) * 0.8:
        return False  # Tamil script, or mostly not Latin letters
    function = sum(1 for w in words if w in _ENGLISH)
    return function >= 2 and function / len(words) >= 0.15


_PLAN = re.compile(
    r"^(?P<name>[a-z][a-z &'-]{1,30}?)\s*(?:plan|membership|pass)?\s*(?:is|at|for|costs?|-|:|=)?\s*"
    r"(?:rs\.?|₹|inr)?\s*(?P<price>\d[\d,]*)\s*(?:(?:/|per|a)\s*(?P<per>month|quarter|year|session))?$", re.I)
_PACK = re.compile(r"^(?P<name>[a-z][a-z &'-]{1,30}?)\s+(?:of|with)\s+(?P<size>\d+\s+[a-z]+)$", re.I)


def plans_from_answer(bp: BusinessBlueprint) -> list[dict[str, str]]:
    """ "Monthly 2500, quarterly 6500, and PT packs of 12 sessions" — the plans
    as the owner said them. A price only where the owner gave a number."""
    state = bp.discovery.get("memberships.plans")
    if not state or state.status not in {"answered", "partial"}:
        return []
    text = state.quote or state.summary or ""
    plans: list[dict[str, str]] = []
    for part in re.split(r",|;|\band\b", text):
        part = part.strip(" .")
        plan, pack = _PLAN.match(part), _PACK.match(part)
        if plan:
            entry = {"name": plan.group("name").strip().capitalize()[:60], "price": money(plan.group("price"))[:40]}
            if plan.group("per"):
                entry["unit"] = f"per {plan.group('per').lower()}"
            plans.append(entry)
        elif pack:
            plans.append({"name": pack.group("name").strip()[:60], "description": pack.group("size")[:80]})
    return plans[:6] if sum(1 for p in plans if p.get("price")) >= 2 else []


_STATUS = re.compile(r"\b(ready to move(?: in)?|ready for possession|under construction|upcoming|"
                     r"launching soon|newly launched|sold out|completed|nearing completion)\b", re.I)


def project_status(bp: BusinessBlueprint, project: str) -> str:
    """ "Aranya Greens is ready to move, Heights is under construction" — the
    status the owner gave this project, in their words. Nothing if not said."""
    words = [w for w in re.split(r"\s+", project) if w]
    names = [re.escape(project)] + ([re.escape(words[-1])] if len(words) > 1 else [])
    said = " ".join(m.text for m in bp.messages if m.role == "user")
    for name in names:
        match = re.search(rf"\b{name}\b[^,.;]{{0,30}}?\b(?:is|are)\s+(?:now\s+)?([^,.;]{{3,40}})", said, re.I)
        status = _STATUS.search(match.group(1)) if match else None
        if status:
            return status.group(1)[0].upper() + status.group(1)[1:].lower()
    return ""


def served_list(bp: BusinessBlueprint) -> list[str]:
    """Who a B2B business supplies, as the owner listed them."""
    state = bp.discovery.get("b2b.customers")
    if not state or state.status not in {"answered", "partial"}:
        return []
    text = state.quote or state.summary or ""
    # "factories and apartment builders around Chennai and Hosur": who, not where.
    text = re.sub(r"\s+(?:around|in|across|near|within|throughout|all over)\s+[A-Z][\w .&-]*$", "", text.strip(" ."))
    items = [p.strip(" .") for p in re.split(r",|\band\b|;|/", text) if p.strip(" .")]
    items = [i[0].upper() + i[1:] for i in items if 2 < len(i) <= 40]
    return items if len(items) >= 2 else []


def _plain_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()


def _unshown_picture(bp: BusinessBlueprint, shown: set[str | None]) -> str | None:
    for group in bp.taxonomy.groups:
        picture = picture_for(bp, "category:" + slug(group.name))
        if picture and picture not in shown:
            return str(picture)
    return None

WHATSAPP = "whatsapp:"
_CHANNEL = re.compile(r"\b(whats\s?app|call|phone|ring|message|dm)\b", re.I)


def copy_cta(bp: BusinessBlueprint) -> str:
    return bp.website_draft.cta_label.text[:40] if bp.website_draft.cta_label else ""


def _first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return (match.group(1) if match else text)[:300]


def _closing(arche: str, name: str) -> str:
    return {
        "product_commerce": "Ready when you are.", "menu_commerce": "Hungry already?",
        "membership_fitness": "Your first session starts here.",
        "real_estate_projects": "Find the home that fits.",
    }.get(arche, f"Talk to {name}.")


def quality_issues(payload: dict[str, Any], archetype: str) -> list[dict[str, str]]:
    """What a reviewer would reject: generic headings, vague items, dead anchors."""
    issues: list[dict[str, str]] = []
    page = payload["pages"][0]
    anchors = {str(s["content"].get("anchor")) for s in page["sections"] if s["content"].get("anchor")}
    anchors.add("contact")
    for section in page["sections"]:
        content = section["content"]
        title = str(content.get("title") or "")
        if archetype in _COMMERCE and _GENERIC_TITLE.match(title):
            issues.append({"code": "generic_commerce_heading", "path": section["section_type_id"]})
        for item in content.get("items") or []:
            name = str(item.get("name") or item.get("title") or "") if isinstance(item, dict) else ""
            if name and normalise_name(name)[1]:
                issues.append({"code": "vague_item_name", "path": name})
    for item in payload["navigation"]:
        path = str(item.get("path") or "")
        if path.startswith("/#") and path[2:] not in anchors:
            issues.append({"code": "dead_anchor", "path": path})
    return issues
