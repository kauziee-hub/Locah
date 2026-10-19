"""What Locah shows it has understood — typed, never a field dump.

The panel used to print strings: whatever landed in `customer_actions` was
split on commas into "What a customer does", so "GYm equipment, available
trainers, dumbells, contact section" appeared as four customer steps, and a
delivery area filed as opening hours read "Hours: All india".

Every value here has a type and is re-derived from the owner's own words
through the reader's checks:

* OFFERING — something sold or provided (from the structured range);
* CUSTOMER ACTION — something a customer does, canonical (order on WhatsApp,
  book a table, ask for a quote…);
* CONTENT — a part of the website the owner asked for ("contact section");
* OPERATING FACT — how buying works: units, delivery, pickup, payment;
* LOCATION — where the business is; SERVICE AREA — where it delivers or serves;
* HOURS — only an actual schedule;
* MODULE — a recommended tool.

A value that fails its type check is not shown. Nothing is split on commas.
"""

from __future__ import annotations

import re
from typing import Any

from platform_core.interview.models import BusinessBlueprint, TargetState
from platform_core.interview.reader import (
    ACTION_LABELS,
    area_phrase,
    canonical_actions,
    fulfilment_modes,
    location_text,
    looks_like_hours,
    offering_names,
    payment_methods,
    phone_number,
    service_area,
    service_area_said,
    units,
)
from platform_core.interview.taxonomy import catalogue_lines

# Characteristics seen in the owner's words, shown as quiet chips.
_TRAITS = (
    ("sells_products", "Sells products"),
    ("provides_services", "Offers services"),
    ("accepts_orders", "Takes orders"),
    ("accepts_appointments", "Takes bookings"),
    ("quote_led", "Quotes first"),
    ("serves_businesses", "Sells to businesses"),
    ("has_memberships", "Memberships"),
    ("made_to_order", "Made to order"),
    ("walk_in", "Walk-ins"),
)


def _state(bp: BusinessBlueprint, target: str) -> TargetState:
    return bp.discovery.get(target) or TargetState()


def _heard(bp: BusinessBlueprint, target: str) -> str:
    """The owner's own words for a discovery target (quote first, then summary)."""
    s = _state(bp, target)
    if s.status not in {"answered", "partial"}:
        return ""
    # Separate sentences: joined without a stop, "…call" + "Order online" read
    # as "call to order".
    return ". ".join(part.strip(" .") for part in (s.quote, s.summary) if part)


def _facts(bp: BusinessBlueprint) -> dict[str, str]:
    return {k: f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items()}


# ----------------------------------------------------------------- typed parts


def customer_actions(bp: BusinessBlueprint) -> list[str]:
    """Canonical customer actions, from the owner's words (or their correction)."""
    if bp.owner_choices.actions is not None:
        return [a for a in bp.owner_choices.actions if a in ACTION_LABELS]
    facts = _facts(bp)
    # The owner's words only — the model's one-line summary ("Table bookings
    # and takeaway orders") is a paraphrase and loses the channel.
    state = _state(bp, "commerce.action")
    said = state.quote if state.status in {"answered", "partial"} else ""
    sources = [said or _heard(bp, "commerce.action"), facts.get("customer_actions", "")]
    if not any(sources):
        # Pattern quotes are fragments ("order pannuvaanga") that lose the
        # channel; used only when nothing fuller was said.
        sources += [e.quote for e in bp.operating_patterns
                    if e.pattern in {"order_led", "appointment_led", "quote_led", "lead_generation", "walk_in"}]
    found: list[str] = []
    for text in sources:
        for action in canonical_actions(text):
            if action not in found:
                found.append(action)
    # A specific way of doing something makes the bare channel redundant.
    if {"order_whatsapp", "book_whatsapp"} & set(found) and "whatsapp" in found:
        found.remove("whatsapp")
    if {"order_call", "book_call"} & set(found) and "call" in found:
        found.remove("call")
    return found[:5]


def fulfilment(bp: BusinessBlueprint) -> list[str]:
    """How orders reach customers — only what the owner said."""
    if bp.owner_choices.fulfilment is not None:
        return list(bp.owner_choices.fulfilment)
    facts = _facts(bp)
    text = " ".join([_heard(bp, "fulfilment.mode"), _heard(bp, "fulfilment.area"),
                     facts.get("operational_characteristics", "")])
    modes = fulfilment_modes(text)
    for evidence in bp.operating_patterns:
        mode = {"local_delivery": "delivery", "delivery": "delivery", "pickup": "pickup",
                "shipping": "shipping"}.get(evidence.pattern)
        if mode and mode not in modes:
            modes.append(mode)
    return list(modes)


def delivery_area(bp: BusinessBlueprint) -> str:
    s = _state(bp, "fulfilment.area")
    if s.status != "answered":
        return ""
    # The quote can be a whole sentence ("We sell chicken, mutton and fish, we
    # deliver within 5 km of Adyar"): the places named after the delivery verb
    # first, then the reply read whole as the answer.
    return str(service_area_said(s.quote) or service_area(s.quote) or service_area(s.summary))


def payments(bp: BusinessBlueprint) -> list[str]:
    if bp.owner_choices.payment is not None:
        return list(bp.owner_choices.payment)
    return list(payment_methods(_heard(bp, "commerce.payment")))


def sold_by(bp: BusinessBlueprint) -> str:
    kind = units(_heard(bp, "offerings.units"))
    if not kind:
        kind = next((units(g.sold_by) for g in bp.taxonomy.groups if units(g.sold_by)), "")
    return {"weight": "By the kg", "packs": "In fixed packs"}.get(kind, "")


def location(bp: BusinessBlueprint) -> str:
    raw = _facts(bp).get("locations", "")
    places = [location_text(part) for part in raw.split(";")]
    places = [p for p in places if p]
    # Most specific last: "Chennai; Nookampalayam Road" -> "Nookampalayam Road, Chennai".
    unique: list[str] = []
    for place in places:
        if all(place.casefold() != u.casefold() for u in unique):
            unique.append(place)
    unique = [p for p in unique if not any(p != o and p.casefold() in o.casefold() for o in unique)]
    return ", ".join(reversed(unique))[:120]


def phone(bp: BusinessBlueprint) -> str:
    digits = phone_number(_facts(bp).get("phone", ""))
    return f"+91 {digits[:5]} {digits[5:]}" if digits else ""


def hours(bp: BusinessBlueprint) -> str:
    value = _facts(bp).get("opening_hours", "")
    return value[:120] if value and looks_like_hours(value) else ""


def offer_groups(bp: BusinessBlueprint) -> list[dict[str, Any]]:
    """What is sold, as groups with items — the structured range when there is one."""
    lines = catalogue_lines(bp)
    if lines:
        return [{"name": str(line["name"]), "items": list(line["items"])[:10],
                 "price": str(line.get("price") or ""), "needs": list(line.get("needs") or [])}
                for line in lines]
    names = offering_names(_facts(bp).get("offerings", ""))
    return [{"name": name, "items": [], "price": "", "needs": []} for name in names]


def _join(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def offer_summary(bp: BusinessBlueprint) -> str:
    found = offer_groups(bp)
    groups = [g["name"] for g in found][:5]
    if not groups:
        return ""
    # One generic group ("Projects") says less than what is in it.
    if len(found) == 1 and found[0]["items"]:
        groups = list(found[0]["items"])[:4]
    # Names as the owner (or the range) has them — "Chettinad chicken", "Fish & Seafood".
    text = _join(groups)
    how = sold_by(bp)
    return f"{text}, {how[:1].lower() + how[1:]}" if how else text


def buying(bp: BusinessBlueprint) -> list[dict[str, str]]:
    """How customers buy, one plain line per fact."""
    rows: list[dict[str, str]] = []
    how = sold_by(bp)
    if how:
        rows.append({"kind": "units", "text": how})
    modes = fulfilment(bp)
    area = delivery_area(bp)
    if "delivery" in modes or "shipping" in modes:
        where = f" {area_phrase(area)}" if area and "delivery" in modes and "shipping" not in modes else \
            f" — {area}" if area else ""
        label = "Delivery" if "shipping" not in modes else "Delivery and shipping"
        rows.append({"kind": "delivery", "text": f"{label}{where}"})
    if "pickup" in modes:
        rows.append({"kind": "pickup", "text": "Pickup"})
    if "dine_in" in modes:
        rows.append({"kind": "dine_in", "text": "Dine-in"})
    if "on_site" in modes:
        rows.append({"kind": "on_site", "text": "At the customer's place" + (f" — {area}" if area else "")})
    pay = payments(bp)
    if pay:
        rows.append({"kind": "payment", "text": _join(pay[:1] + [p[:1].lower() + p[1:] if p != "UPI" else p
                                                              for p in pay[1:]])})
    return rows


def identity_line(bp: BusinessBlueprint) -> str:
    """One line on what the business is: the owner's words, else their category."""
    s = _state(bp, "business.identity")
    said = (s.summary or s.quote) if s.status in {"answered", "partial"} else ""
    if said and len(said) <= 160 and not canonical_actions(said):
        return said
    if bp.category and bp.category.label:
        return str(bp.category.label)
    facts = _facts(bp)
    return (facts.get("classification") or "")[:160]


def actions(bp: BusinessBlueprint) -> list[dict[str, str]]:
    return [{"id": a, "label": ACTION_LABELS[a]} for a in customer_actions(bp)]


def synthesis(bp: BusinessBlueprint, lang: str = "") -> str:
    """One short "so far" line, built only from typed understanding.

    English gets a sentence ("customers can order on WhatsApp"); for an owner
    writing Tamil or Tamil-English the typed parts are listed plainly rather
    than wrapped in English connectors.
    """
    lang = lang or ("ta" if bp.language_style == "ta" else "ta_en" if bp.language_style.startswith("ta") else "en")
    parts: list[str] = []
    offer = offer_summary(bp)
    if offer:
        parts.append(offer)
    labels = [ACTION_LABELS[a] for a in customer_actions(bp)[:2]]
    if labels and lang == "en":
        acts = [label if label.startswith("WhatsApp") else label[:1].lower() + label[1:] for label in labels]
        parts.append("customers can " + " or ".join(acts))
    elif labels:
        parts.append(" / ".join(labels))
    for row in buying(bp):
        if row["kind"] in {"delivery", "pickup"}:
            parts.append(row["text"][:1].lower() + row["text"][1:] if lang == "en" else row["text"])
    place = location(bp)
    if place and len(parts) < 4:
        parts.append(f"in {place}" if lang == "en" else place)
    return "; ".join(parts[:4])


# ------------------------------------------------------------- the read-back
#
# Locah says back what it understood in one plain sentence before asking
# anything — the way an expert shows they were listening. Built only from the
# typed understanding above: nothing in it was not said (or picked) by the
# owner, and an assumption the owner did not make ("with delivery") is never
# added. English only; an owner writing Tamil gets the typed parts listed.

_PLACE_NOUNS = ("shop", "store", "gym", "salon", "clinic", "kitchen", "studio", "restaurant", "cafe",
                "café", "bakery", "hotel", "school", "centre", "center", "academy", "agency", "hospital",
                "spa", "boutique", "club", "resort", "homestay", "lab", "pharmacy")


def place_noun(bp: BusinessBlueprint) -> str:
    """"shop", "gym", "studio"… — what the owner would call the place; else "business"."""
    label = (bp.category.label if bp.category else "").casefold()
    label = _PRACTICE.get(label, label)
    for noun in reversed(label.replace("/", " ").split()):
        if noun in _PLACE_NOUNS:
            return "café" if noun == "cafe" else noun
    return "business"


def kind_phrase(bp: BusinessBlueprint) -> str:
    """"a meat shop", "an industrial supplier" — from the category, never invented."""
    label = bp.category.label if bp.category and bp.category.label else ""
    label = re.sub(r"\s*/.*$", "", label).strip()
    if not label or bp.category is None or bp.category.category_key == "other":
        return ""
    words = [w if (w[:1].isupper() and w[1:2].isupper()) or w in {"CrossFit", "ENT", "PG", "IT"}
             else w.lower() for w in label.split()]
    text = " ".join(words)
    # A practice is not a place: "a physiotherapy" reads wrong.
    text = _PRACTICE.get(text.casefold(), text)
    return ("an " if text[:1].lower() in "aeiou" else "a ") + text


_PRACTICE = {
    "physiotherapy": "physiotherapy centre", "yoga": "yoga studio", "pilates": "pilates studio",
    "powerlifting": "powerlifting gym", "crossfit": "CrossFit gym", "martial arts": "martial arts academy",
    "dance fitness": "dance fitness studio", "dermatology": "dermatology clinic",
    "paediatrics": "paediatric clinic", "home nursing": "home nursing service", "dairy": "dairy",
    "snacks": "snacks business", "sweets": "sweets business", "spices": "spice business",
    "eggs": "egg business", "pickles & podi": "pickles and podi business", "catering": "catering business",
    "photography": "photography studio", "interior design": "interior design studio",
}


_GOALS = {
    "order": "see what you have and order",
    "book": "see what you offer and book",
    "trial": "understand the {noun}, see the plans and take the first step",
    "quote": "understand what you supply and ask for a quote",
    "site_visit": "see the projects and arrange a visit",
    "dates": "see your work and check your dates",
    "contact": "find you and get in touch",
}


def _goal(actions_: list[str]) -> str:
    first = actions_[0] if actions_ else ""
    if first.startswith("order"):
        return _GOALS["order"]
    if first in {"book_trial", "join", "subscribe"}:
        return _GOALS["trial"]
    if first.startswith("book"):
        return _GOALS["book"]
    if first in {"request_quote", "enquire"}:
        return _GOALS["quote"]
    if first == "book_site_visit":
        return _GOALS["site_visit"]
    if first == "check_dates":
        return _GOALS["dates"]
    return _GOALS["contact"] if first else ""


# How an action reads inside a sentence about the business.
_DOES = {
    "order_online": "order online", "order_whatsapp": "order on WhatsApp", "order_call": "call to order",
    "book_online": "book online", "book_whatsapp": "book on WhatsApp", "book_call": "call to book",
    "book_table": "book a table", "book_trial": "book a trial", "book_site_visit": "book a site visit",
    "book_consultation": "book a consultation", "check_dates": "check your dates",
    "request_quote": "ask for a quote", "enquire": "send an enquiry", "call": "call you",
    "whatsapp": "message you on WhatsApp", "visit": "come in person", "join": "sign up",
    "subscribe": "subscribe", "donate": "donate", "get_app": "get the app", "browse": "browse the range",
}


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def _titled(place: str) -> str:
    """"nookampalayam road" -> "Nookampalayam Road"; the owner's own casing otherwise."""
    if not place or place != place.lower():
        return place
    small = {"and", "of", "the", "near", "to", "in", "on", "or"}
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(place.split()))


def read_back(bp: BusinessBlueprint, stage: str = "first") -> str:
    """One sentence of what Locah understood — "first", "shape" or "checkpoint"."""
    kind = kind_phrase(bp)
    place = ", ".join(_titled(p.strip()) for p in location(bp).split(","))
    area_titled = True
    acts = customer_actions(bp)
    modes = fulfilment(bp)
    area = _titled(delivery_area(bp)) if area_titled else delivery_area(bp)
    groups = [g["name"] for g in offer_groups(bp)][:4]
    how = sold_by(bp)
    # LOCAH's own group labels ("Fish & Seafood") read in lower case inside a
    # sentence; the owner's names keep their capitals ("Aranya Greens").
    ours = {g.name for g in bp.taxonomy.groups if g.label_source == "ai_suggestion"}
    def phrase(name: str) -> str:
        if name in ours:
            return name.lower()
        words = name.split()
        # "Aranya Greens" is a name; "Strength classes" is not.
        if len(words) > 1 and all(w[:1].isupper() for w in words if w[:1].isalpha()):
            return name
        return _lower_first(name)

    offer = _join([phrase(g) for g in groups]) if groups else ""
    subject = kind or ("a business" if not offer else "")
    if not subject and not offer:
        return ""
    sentence = subject
    if place:
        sentence += f" in {place}"
    if offer and kind:
        verb = "built around" if bp.category and place_noun(bp) in {"gym", "studio", "club", "academy"} \
            else "offering" if kind else ""
        sentence += f" {verb} {offer}"
    elif offer:
        sentence = f"you offer {offer}" + (f" in {place}" if place else "")
    tail: list[str] = []
    does = " or ".join(_DOES[a] for a in acts[:2] if a in _DOES)
    if how == "By the kg" and does:
        tail.append(f"where people choose what they want by the kg and {does}")
    elif how == "By the kg":
        tail.append("sold by the kg")
    elif does:
        tail.append(f"where people {does}")
    if "delivery" in modes and "pickup" not in modes:
        tail.append(f"with delivery {area_phrase(area)}" if area else "with delivery as part of the service")
    elif "delivery" in modes and "pickup" in modes:
        tail.append(f"delivering {area_phrase(area)} or ready for pickup" if area else "with delivery or pickup")
    elif "pickup" in modes and "delivery" not in modes:
        tail.append("collected from you")
    elif "shipping" in modes:
        tail.append(f"shipped {('across ' + area) if area else 'to customers'}")
    if tail:
        sentence += " " + ", ".join(tail) if tail[0].startswith("where") else ", " + ", ".join(tail)
    sentence = sentence.strip()
    if stage == "first":
        return f"Got it — {sentence}."
    goal = _goal(acts).format(noun=place_noun(bp))
    you = sentence if sentence.startswith("you ") else f"you're {sentence}"
    if stage == "shape":
        line = f"Okay — I have the shape of it now: {you}."
        return line + (f" The website should mainly help people {goal}." if goal else "")
    if stage == "so_far":
        return f"So far: {you}."
    return f"{you[:1].upper()}{you[1:]}."


# ------------------------------------------------------------------ the panel


def understanding(
    bp: BusinessBlueprint, business_type: str | None = None, logo_url: str | None = None
) -> dict[str, Any]:
    from platform_core.interview.coverage import dimensions, worth_knowing
    from platform_core.interview.discovery import characteristics

    chars = characteristics(bp, business_type)
    seen = {c for c, how in chars.items() if how == "observed"}
    name = bp.identity["display_name"].value if "display_name" in bp.identity else ""
    logo_request = next((r for r in bp.media_generation_requests if r.role == "logo"), None)
    logo_asset = next((m for m in reversed(bp.media_assets) if m.role == "logo"), None)
    if logo_asset:
        logo: dict[str, Any] = {"state": "ready", "source": logo_asset.source, "url": logo_url}
    elif logo_request:
        logo = {"state": logo_request.status, "reason": logo_request.reason}
    else:
        logo = {"state": "none"}
    contact = {"location": location(bp), "phone": phone(bp), "hours": hours(bp)}
    tools = [
        {"id": m.module_id, "label": m.label, "why": _tool_reason(m.reason), "choice": m.choice}
        for m in bp.recommended_modules if m.strength != "dependency"
    ][:5]
    return {
        "business": {
            "name": "" if bp.name_pending else name, "kind": identity_line(bp),
            "category": bp.category.label if bp.category else "",
            "category_key": bp.category.category_key if bp.category else "",
            "subcategory_key": bp.category.subcategory_key if bp.category else "",
            "category_group": bp.category.group if bp.category else "",
            # "inferred": shown as "Looks like…" with a one-tap correction.
            "category_source": bp.category.source if bp.category else "",
            "place": location(bp),
            "name_pending": bp.name_pending,
        },
        # What the side panel's "Change" can set, and what is set now (typed ids).
        "options": _options(bp),
        "choices": {"actions": customer_actions(bp), "fulfilment": fulfilment(bp), "payment": payments(bp),
                    "area": delivery_area(bp)},
        # How the website will feel — the design family's words, once there is
        # enough to decide (never shown as "template" or "family").
        "direction": _direction(bp, business_type),
        # One sentence: what Locah understood, for the confirmation screen.
        "read_back": read_back(bp, "checkpoint") if bp.language_style == "en" else synthesis(bp),
        "offer": {"summary": offer_summary(bp), "groups": offer_groups(bp)},
        "actions": actions(bp),
        "buying": buying(bp),
        "contact": contact,
        "content": list(bp.content_wishes),
        "traits": [label for key, label in _TRAITS if key in seen],
        "worth_knowing": worth_knowing(bp, business_type),
        "tools": tools,
        "progress": dimensions(bp, business_type),
        "readiness": bp.readiness.model_dump(),
        "logo": logo,
        "synthesis": synthesis(bp),
        # Kept for older clients: the same typed facts, flattened.
        "kind": identity_line(bp)[:160],
        "catalogue": _with_photo_needs(bp),
    }


_FULFILMENT_LABELS = (("delivery", "Delivery"), ("pickup", "Pickup"), ("shipping", "Shipping / courier"),
                      ("dine_in", "Dine-in"), ("on_site", "At the customer's place"))


def _direction(bp: BusinessBlueprint, business_type: str | None) -> dict[str, Any] | None:
    from platform_core.interview.coverage import floor_met

    if not floor_met(bp, business_type):
        return None
    from platform_core.interview.design_system import choose, read_dimensions

    picked = choose(bp, read_dimensions(bp, business_type))
    return {"family": picked.family.key, "words": list(picked.family.words)}


def _relevant_actions(bp: BusinessBlueprint) -> list[str]:
    """What a customer of THIS business might do — the owner's own first, then
    the trade's usual ones, then the ways any business can be reached."""
    from platform_core.interview.playbooks import playbook_for

    pb = playbook_for(bp)
    wanted = list(customer_actions(bp)) + list(pb.likely_actions)
    kind = pb.offer_kind
    if pb.booking_led:
        wanted += ["book_online", "book_whatsapp", "book_call"]
    elif kind in {"weighed_product", "product", "menu_item", "digital_product"}:
        wanted += ["order_whatsapp", "order_online", "order_call"]
    elif kind == "property_project":
        wanted += ["book_site_visit", "enquire", "request_quote"]
    elif kind in {"portfolio_item", "package", "service"}:
        wanted += ["request_quote", "check_dates", "enquire"]
    elif kind in {"plan", "class"}:
        wanted += ["book_trial", "join"]
    elif kind in {"room_type", "rental_resource", "vehicle"}:
        wanted += ["check_dates", "book_online", "book_whatsapp"]
    elif kind == "cause":
        wanted += ["donate", "join"]
    wanted += ["call", "whatsapp", "visit", "enquire"]
    out: list[str] = []
    for action in wanted:
        if action in ACTION_LABELS and action not in out:
            out.append(action)
    return out[:9]


def _options(bp: BusinessBlueprint) -> dict[str, list[dict[str, str]]]:
    from platform_core.interview.corrections import PAYMENTS

    return {
        "actions": [{"id": k, "label": ACTION_LABELS[k]} for k in _relevant_actions(bp)],
        "all_actions": [{"id": k, "label": v} for k, v in ACTION_LABELS.items()],
        "fulfilment": [{"id": k, "label": v} for k, v in _FULFILMENT_LABELS],
        "payment": [{"id": p, "label": p} for p in PAYMENTS],
    }


def _tool_reason(reason: str) -> str:
    """The owner-facing why, without the module jargon."""
    reason = re.sub(r"^Because you said “[^”]*”\.\s*", "", reason or "")
    return reason[:160]


def _with_photo_needs(bp: BusinessBlueprint) -> list[dict[str, Any]]:
    """A group still needs a picture until it has a real photo or a draft visual."""
    from platform_core.interview.media_director import picture_for, slug

    lines = catalogue_lines(bp)
    for line in lines:
        needs = list(line["needs"])
        if not picture_for(bp, f"category:{slug(str(line['name']))}") and "photo" not in needs:
            needs.append("photo")
        line["needs"] = needs
    return list(lines)
