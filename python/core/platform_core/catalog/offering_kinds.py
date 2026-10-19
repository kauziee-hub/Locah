"""Offering kinds (Capability Universe §6.3): one catalogue, many kinds; the
kind decides which fields, website section and transaction flow apply.

Kinds already stored under First Launch names keep them (`class_session`,
`accommodation`, `rental`, `membership_plan`); `source` is the §6.3 name. Kind
fields are validated here and stored in `offerings_catalog_offerings.attributes`;
the owner only ever sees them as labelled form fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from platform_core.exceptions import ValidationError


@dataclass(frozen=True)
class KindField:
    key: str
    label: str
    type: str  # text | long_text | int | money | choice | list | bool | date | year | time
    required: bool = False
    choices: tuple[str, ...] = ()
    unit: str | None = None
    help: str | None = None
    public: bool = True  # shown on the website


@dataclass(frozen=True)
class OfferingKind:
    key: str
    source: str
    label: str
    plural: str
    flow: str  # cart | booking | membership | enquiry | give
    cta: str
    help: str
    fields: tuple[KindField, ...] = ()
    options: bool = False  # choice groups (cuts, modifiers, add-ons)
    packs: bool = False  # sold in weighed packs of a stock unit
    variants: bool = False
    stockable: bool = False
    goods: bool = True  # HSN (goods) vs SAC (services)
    extra_ctas: tuple[str, ...] = field(default_factory=tuple)


_AMENITIES = KindField("amenities", "Amenities", "list", help="One per line")

KINDS: dict[str, OfferingKind] = {k.key: k for k in (
    OfferingKind("product", "product", "Product", "Products", "cart", "Add to cart",
                 "Something you sell by the piece. Sizes or colours become variants.",
                 (KindField("brand", "Brand", "text"),), variants=True, stockable=True),
    OfferingKind("weighed_product", "weighed_product", "Sold by weight", "Sold by weight", "cart", "Add to cart",
                 "Meat, fish, produce or sweets priced per kg and sold in packs, with cuts to choose from.",
                 (KindField("price_per", "Price is per", "choice", True, ("kg", "litre")),),
                 options=True, packs=True, stockable=True),
    OfferingKind("menu_item", "menu_item", "Menu item", "Menu", "cart", "Add",
                 "A dish or drink, with choices and add-ons that change the price.",
                 (KindField("diet", "Veg / non-veg", "choice", False, ("Veg", "Non-veg", "Egg", "Vegan")),
                  KindField("spice", "Spice level", "choice", False, ("Mild", "Medium", "Hot")),
                  KindField("serves", "Serves", "int", unit="people")),
                 options=True, stockable=True),
    OfferingKind("service", "service", "Service", "Services", "booking", "Book",
                 "An appointment with a person — a haircut, consultation or repair visit.",
                 (KindField("duration_minutes", "How long it takes", "int", True, unit="minutes"),
                  KindField("at_home", "Can be done at the customer's place", "bool"),
                  KindField("whole_day", "Booked by the date (weddings, events)", "bool")),
                 goods=False),
    OfferingKind("class_session", "class", "Class", "Classes", "booking", "Book a spot",
                 "A scheduled session people join — yoga, zumba, a workshop.",
                 (KindField("duration_minutes", "Session length", "int", True, unit="minutes"),
                  KindField("level", "Level", "choice", False, ("All levels", "Beginner", "Intermediate", "Advanced")),
                  KindField("capacity", "Places per session", "int")),
                 goods=False),
    OfferingKind("course", "course", "Course", "Courses", "enquiry", "Enquire",
                 "A course over weeks — batches and enrolment arrive with the Academics tool.",
                 (KindField("duration_weeks", "Length", "int", True, unit="weeks"),
                  KindField("sessions", "Number of sessions", "int"),
                  KindField("mode", "Where it happens", "choice", False, ("In person", "Online", "Both")),
                  KindField("starts_on", "Next batch starts", "date")),
                 goods=False),
    OfferingKind("accommodation", "room_type", "Room type", "Rooms", "booking", "Check availability",
                 "A kind of room guests book by date.",
                 (KindField("max_guests", "Guests per room", "int", True),
                  KindField("beds", "Beds", "text"), KindField("size_sqft", "Room size", "int", unit="sq ft"),
                  _AMENITIES,
                  # The stay's own rules, as the owner says them ("check-in 1 pm,
                  # check-out 11 am", "2-night minimum on weekends"): the Book
                  # page and the booking hold to them (booking_slots.stay_window
                  # and stay_rule_broken).
                  KindField("check_in", "Check-in from", "time", help="Guests arrive from this time. Usually 2 pm."),
                  KindField("check_out", "Check-out by", "time", help="Guests leave by this time. Usually 11 am."),
                  KindField("min_nights", "Shortest stay", "int", unit="nights"),
                  KindField("weekend_min_nights", "Shortest stay over a Friday or Saturday night", "int",
                            unit="nights")),
                 goods=False),
    OfferingKind("rental", "rental_resource", "Rental", "Rentals", "booking", "Check availability",
                 "Something hired by the hour or day — a hall, equipment, a vehicle.",
                 (KindField("deposit", "Refundable deposit", "money"),
                  KindField("min_hours", "Minimum hire", "int", unit="hours"),
                  KindField("whole_day", "Booked by the date (weddings, events)", "bool"), _AMENITIES),
                 goods=False),
    OfferingKind("membership_plan", "plan", "Plan", "Plans", "membership", "Join",
                 "A membership or subscription people join and renew.",
                 (KindField("period", "Billed", "choice", False, ("Monthly", "Quarterly", "Half-yearly", "Yearly")),
                  KindField("includes", "What it includes", "long_text")),
                 goods=False),
    OfferingKind("package", "package", "Package", "Packages", "cart", "Buy package",
                 "A bundle bought once and used over time — 10 PT sessions, a facial pack.",
                 (KindField("includes", "What is included", "text", True, help="For example: 10 sessions"),
                  KindField("sessions", "Number of sessions", "int"),
                  KindField("valid_days", "Valid for", "int", unit="days")),
                 goods=False),
    OfferingKind("property_project", "property_project", "Property project", "Projects", "enquiry", "Enquire",
                 "A building or layout you are selling — with status, location and unit types.",
                 (KindField("project_status", "Status", "choice", True,
                            ("Upcoming", "Launching", "Live", "Sold out", "Completed", "On hold")),
                  KindField("location", "Location", "text", True),
                  KindField("map_link", "Map link", "text", public=True),
                  KindField("rera_number", "RERA registration number", "text"),
                  KindField("possession", "Possession", "text", help="For example: December 2027"),
                  KindField("unit_types", "Unit types", "list", help="One per line, e.g. 2 BHK · 1,050 sq ft · from ₹82 lakh"),
                  _AMENITIES),
                 goods=False, extra_ctas=("Book a site visit",)),
    OfferingKind("property_unit", "unit", "Property unit", "Units", "enquiry", "Enquire",
                 "One flat, plot or shop in a project.",
                 (KindField("project", "Project", "text", True),
                  KindField("unit_number", "Tower / floor / number", "text"),
                  KindField("configuration", "Configuration", "text", help="For example: 2 BHK"),
                  KindField("area_sqft", "Carpet area", "int", unit="sq ft"),
                  KindField("facing", "Facing", "text"),
                  KindField("unit_status", "Status", "choice", True, ("Available", "Held", "Booked", "Sold", "Blocked"))),
                 goods=False, extra_ctas=("Book a site visit",)),
    OfferingKind("vehicle", "vehicle", "Vehicle", "Vehicles", "enquiry", "Enquire",
                 "A car or bike in stock, with its specs.",
                 (KindField("make", "Make", "text", True), KindField("model", "Model", "text", True),
                  KindField("year", "Year", "year"),
                  KindField("fuel", "Fuel", "choice", False, ("Petrol", "Diesel", "CNG", "Electric", "Hybrid")),
                  KindField("transmission", "Gearbox", "choice", False, ("Manual", "Automatic")),
                  KindField("km_driven", "Kilometres driven", "int", unit="km"),
                  KindField("ownership", "Owners", "choice", False, ("New", "1st owner", "2nd owner", "3rd owner or more")),
                  KindField("registration_state", "Registered in", "text")),
                 extra_ctas=("Book a test drive",)),
    OfferingKind("portfolio_item", "portfolio_item", "Portfolio piece", "Portfolio", "enquiry", "Enquire",
                 "Work you have done, shown to win the next job.",
                 (KindField("client", "Client", "text"), KindField("year", "Year", "year"),
                  KindField("category", "Type of work", "text")),
                 goods=False),
    OfferingKind("digital_product", "digital_product", "Digital product", "Digital products", "cart", "Buy",
                 "An e-book, template or recorded course, sent to the buyer after payment.",
                 (KindField("format", "Format", "text", True, help="For example: PDF, video course"),
                  KindField("delivery_note", "How the buyer gets it", "text", True,
                            help="For example: We send the download link on WhatsApp within an hour")),
                 goods=False),
    OfferingKind("cause", "cause", "Cause", "Causes", "give", "Give",
                 "Something people give towards — a meal drive, a shelter, a scholarship.",
                 (KindField("goal_amount", "Goal", "money"),
                  KindField("min_amount", "Smallest gift", "money", True),
                  KindField("suggested_amounts", "Suggested amounts", "list", help="One per line, e.g. 500"),
                  KindField("receipt_note", "Receipt note shown to donors", "text")),
                 goods=False),
    OfferingKind("listing", "listing", "Listing", "Listings", "enquiry", "Enquire",
                 "A general listing people ask about.", goods=False),
)}

# Legacy First Launch type names map onto the §6.3 names they already are.
SOURCE_NAMES = {k.key: k.source for k in KINDS.values()}
# Kinds First Launch already stored. Their API clients predate kind fields, so
# a missing required field is reported (missing_fields) rather than refused —
# §26.3 P1-03 "existing catalogue tests still pass". New kinds enforce them.
FIRST_LAUNCH_KINDS = frozenset({"product", "menu_item", "service", "accommodation", "membership_plan",
                                "class_session", "rental", "listing"})
STOCK_UNITS = ("piece", "g", "ml")
_HSN = re.compile(r"^\d{4}(\d{2}(\d{2})?)?$")
_SAC = re.compile(r"^99\d{4}$")


def kind(key: str) -> OfferingKind:
    k = KINDS.get(key)
    if k is None:
        raise ValidationError("Unknown kind of offering", details={"field": "offering_type"})
    return k


def _bad(field_key: str, message: str) -> ValidationError:
    return ValidationError(message, details={"errors": [{"field": field_key, "message": message}]})


def clean_attributes(k: OfferingKind, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate kind fields; unknown keys are dropped, required ones enforced."""
    raw = raw or {}
    out: dict[str, Any] = {}
    for f in k.fields:
        v = raw.get(f.key)
        if v in (None, "", []):
            if f.required and k.key not in FIRST_LAUNCH_KINDS:
                raise _bad(f"attributes.{f.key}", f"{f.label} is needed")
            continue
        try:
            if f.type in ("text", "long_text"):
                s = str(v).strip()
                if len(s) > (2000 if f.type == "long_text" else 200):
                    raise _bad(f"attributes.{f.key}", f"{f.label} is too long")
                out[f.key] = s
            elif f.type in ("int", "year"):
                n = int(v)
                lo, hi = (1900, date.today().year + 1) if f.type == "year" else (0, 10**9)
                if not lo <= n <= hi:
                    raise _bad(f"attributes.{f.key}", f"{f.label} is out of range")
                out[f.key] = n
            elif f.type == "money":
                m = Decimal(str(v)).quantize(Decimal("0.01"))
                if m < 0:
                    raise _bad(f"attributes.{f.key}", f"{f.label} cannot be negative")
                out[f.key] = str(m)
            elif f.type == "choice":
                if str(v) not in f.choices:
                    raise _bad(f"attributes.{f.key}", f"Choose one of the options for {f.label}")
                out[f.key] = str(v)
            elif f.type == "list":
                items = v if isinstance(v, list) else str(v).splitlines()
                clean = [str(x).strip()[:200] for x in items if str(x).strip()][:40]
                if clean:
                    out[f.key] = clean
            elif f.type == "bool":
                out[f.key] = bool(v)
            elif f.type == "date":
                out[f.key] = date.fromisoformat(str(v)).isoformat()
            elif f.type == "time":
                # "13:00" (an <input type=time>); seconds are dropped.
                from datetime import time as clock

                out[f.key] = clock.fromisoformat(str(v).strip()).strftime("%H:%M")
        except (ValueError, InvalidOperation):
            raise _bad(f"attributes.{f.key}", f"{f.label} is not valid") from None
    if k.key == "cause" and "suggested_amounts" in out:
        try:
            out["suggested_amounts"] = [str(Decimal(x.replace(",", "").replace("₹", "")).quantize(Decimal("1")))
                                        for x in out["suggested_amounts"]][:6]
        except InvalidOperation:
            raise _bad("attributes.suggested_amounts", "Suggested amounts must be numbers") from None
    return out


def clean_option_groups(k: OfferingKind, raw: Any) -> list[dict[str, Any]]:
    """Choice groups: [{name, required, max, choices: [{label, price_delta}]}], or a
    text box the customer fills in: {name, text: true, required, max_length}."""
    if not raw:
        return []
    if not k.options:
        raise _bad("option_groups", f"{k.plural} do not have choices")
    if not isinstance(raw, list) or len(raw) > 10:
        raise _bad("option_groups", "Up to 10 groups of choices")
    groups, seen = [], set()
    for g in raw:
        name = str((g or {}).get("name") or "").strip()[:60]
        if not name or name.lower() in seen:
            raise _bad("option_groups", "Each group of choices needs its own name")
        seen.add(name.lower())
        if g.get("text"):
            # A few words the customer writes: the message on a cake, a name to engrave.
            try:
                max_length = int(g.get("max_length") or 40)
            except (TypeError, ValueError):
                raise _bad("option_groups", f"{name}: how many letters must be a number") from None
            if not 1 <= max_length <= 200:
                raise _bad("option_groups", f"{name}: between 1 and 200 letters")
            groups.append({"name": name, "text": True, "required": bool(g.get("required")),
                           "max_length": max_length})
            continue
        choices, labels = [], set()
        for c in (g.get("choices") or [])[:30]:
            label = str((c or {}).get("label") or "").strip()[:80]
            if not label or label.lower() in labels:
                raise _bad("option_groups", f"Each choice in {name} needs its own name")
            labels.add(label.lower())
            try:
                delta = Decimal(str(c.get("price_delta") or 0)).quantize(Decimal("0.01"))
            except InvalidOperation:
                raise _bad("option_groups", f"Price change for {label} must be a number") from None
            if delta < 0:
                raise _bad("option_groups", "A choice cannot lower the price below the base")
            choices.append({"label": label, "price_delta": str(delta)})
        if not choices:
            raise _bad("option_groups", f"{name} needs at least one choice")
        required = bool(g.get("required"))
        max_pick = int(g.get("max") or 1)
        if not 1 <= max_pick <= len(choices):
            raise _bad("option_groups", f"{name}: how many can be picked must be between 1 and {len(choices)}")
        groups.append({"name": name, "required": required, "max": max_pick, "choices": choices})
    return groups


def clean_packs(k: OfferingKind, raw: Any, stock_unit: str) -> list[dict[str, Any]]:
    """Packs for weighed goods: [{label, qty}] where qty is in the stock unit."""
    if not raw:
        if k.packs:
            raise _bad("sell_units", "Add at least one pack size, for example 500 g")
        return []
    if not k.packs:
        raise _bad("sell_units", f"{k.plural} are not sold in packs")
    if stock_unit not in ("g", "ml"):
        raise _bad("stock_unit", "Items sold by weight are counted in grams or millilitres")
    packs, labels = [], set()
    for p in raw[:12]:
        label = str((p or {}).get("label") or "").strip()[:40]
        try:
            qty = int(p.get("qty"))
        except (TypeError, ValueError):
            raise _bad("sell_units", "Each pack needs a weight") from None
        if not label or label.lower() in labels or not 1 <= qty <= 1_000_000:
            raise _bad("sell_units", "Each pack needs its own name and a weight")
        labels.add(label.lower())
        packs.append({"label": label, "qty": qty})
    return packs


def clean_variant_options(k: OfferingKind, raw: Any) -> list[dict[str, Any]]:
    """Variant axes for the size × colour matrix: [{name, values}]."""
    if not raw:
        return []
    if not k.variants:
        raise _bad("variant_options", f"{k.plural} do not have variants")
    axes, names = [], set()
    for a in raw[:3]:
        name = str((a or {}).get("name") or "").strip()[:40]
        values = [str(v).strip()[:40] for v in (a.get("values") or []) if str(v).strip()]
        values = list(dict.fromkeys(values))[:30]
        if not name or name.lower() in names or not values:
            raise _bad("variant_options", "Each variant option needs a name and at least one value")
        names.add(name.lower())
        axes.append({"name": name, "values": values})
    return axes


def clean_tax_code(code: Any, k: OfferingKind) -> str | None:
    """HSN for goods (4, 6 or 8 digits), SAC for services (6 digits, 99…)."""
    if code in (None, ""):
        return None
    s = re.sub(r"\s", "", str(code))
    if k.goods and not _HSN.match(s):
        raise _bad("hsn_sac", "HSN codes are 4, 6 or 8 digits")
    if not k.goods and not _SAC.match(s):
        raise _bad("hsn_sac", "SAC codes are 6 digits starting with 99")
    return s


def gtin_ok(code: str) -> bool:
    """GS1 check digit for GTIN-8/12/13/14."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def describe() -> list[dict[str, Any]]:
    """The kinds as the Workspace editor and the website read them."""
    return [
        {"key": k.key, "source": k.source, "label": k.label, "plural": k.plural, "flow": k.flow, "cta": k.cta,
         "extra_ctas": list(k.extra_ctas), "help": k.help, "options": k.options, "packs": k.packs,
         "variants": k.variants, "stockable": k.stockable, "tax_code": "HSN" if k.goods else "SAC",
         "fields": [{"key": f.key, "label": f.label, "type": f.type, "required": f.required,
                     "choices": list(f.choices), "unit": f.unit, "help": f.help} for f in k.fields]}
        for k in KINDS.values() if k.key != "listing"
    ]


def missing_fields(k: OfferingKind, attributes: dict[str, Any] | None) -> list[str]:
    """Required kind fields that are still empty, in owner words."""
    attrs = attributes or {}
    return [f.label for f in k.fields if f.required and attrs.get(f.key) in (None, "", [])]
