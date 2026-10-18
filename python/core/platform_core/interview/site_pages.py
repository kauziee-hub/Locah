"""A business's website as a real site: a home page and inner pages.

The composer's first websites were one long page. A good studio site — what an
owner gets after many rounds with a site builder — is a home page that
introduces the business and inner pages that each do one job: the full menu
or shop, the story, how to visit. Each has many sections, and none is a
template: which pages exist, what each holds and in what order follow from
what this business has to say.

Pages (each only when there is enough to fill it):

* **home** — the opening scene, a moving band, one sentence as a centrepiece,
  a teaser of the range linking to its page, what the business stands on,
  numbers the owner gave, a short set of questions, the closing line;
* **the range** (menu / shop / services / plans / projects / work) — its own
  opening, the whole catalogue, how ordering works, ordering questions;
* **about** — the story, passages beside their pictures, how working together goes;
* **visit** — where and when, the map, every question answered.

Everything a visitor reads is the owner's (or governed copy). The questions
are answered only from facts the owner gave; a pillar is a phrase the owner
said or a fact about how they sell; nothing here invents a claim.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from platform_core.interview.models import BusinessBlueprint, TargetState
from platform_core.interview.website_copy import WebsiteCopy

# The range's own page, by archetype: (slug, page_type).
_RANGE_PAGE = {
    "menu_commerce": ("menu", "menu"),
    "product_commerce": ("shop", "offerings"),
    "service_appointment": ("services", "services"),
    "local_service": ("services", "services"),
    "membership_fitness": ("plans", "plans"),
    "real_estate_projects": ("projects", "offerings"),
    "project_portfolio": ("work", "offerings"),
    "b2b_rfq": ("products", "offerings"),
}
# The range page's own address, by the trade's word for its range — a
# restaurant whose range is its "Menu" gets /menu even when booking leads.
_RANGE_BY_LABEL = {"menu": ("menu", "menu"), "shop": ("shop", "offerings"), "services": ("services", "services"),
                   "plans": ("plans", "plans"), "memberships": ("plans", "plans"),
                   "programmes": ("programmes", "classes"), "classes": ("classes", "classes"),
                   "projects": ("projects", "offerings"), "work": ("work", "offerings"),
                   "products": ("products", "offerings"), "rooms": ("rooms", "rooms")}
_MORE_BY_SLUG = {"menu": "See the full menu", "shop": "See everything", "services": "All services",
                 "plans": "All plans", "projects": "All projects", "work": "All work", "products": "The full range",
                 "programmes": "All programmes", "classes": "All classes", "rooms": "All rooms"}
_SCENES = frozenset({"rail", "bento", "spotlight", "stack", "menu_book"})
_MORE_LABEL = {
    "menu_commerce": "See the full menu", "product_commerce": "See everything",
    "service_appointment": "All services", "local_service": "All services",
    "membership_fitness": "All plans", "real_estate_projects": "All projects",
    "project_portfolio": "All work", "b2b_rfq": "The full range",
}

# A pillar's picture-word, by what it says.
_ICON_WORDS = (
    (r"deliver|courier|ship|dispatch|doorstep", "truck"),
    (r"pick ?up|collect|takeaway|parcel", "bag"),
    (r"fresh|leaf|natural|garden|organic|green|veg", "leaf"),
    (r"stone|ground|grind|hand|craft|made|cook|bake|prepare|mother|amma|home", "hand"),
    (r"spic|chill|hot|fire|flame|wood", "flame"),
    (r"week|daily|morning|every day|hour|time|minute|quick|fast", "clock"),
    (r"no preservative|pure|clean|hygien|safe|trust", "shield"),
    (r"love|family|care|heart", "heart"),
    (r"cut|trim|slice|clean", "cut"),
    (r"book|appointment|slot|schedule", "calendar"),
    (r"whatsapp|call|message|chat", "chat"),
    (r"upi|pay|cash|card", "check"),
    (r"\bkg\b|kilo|weigh|gram|by weight", "scale"),
    (r"strength|power|train|coach|lift", "bolt"),
    (r"home|house|villa|plot|room|stay", "home"),
)


def icon_for(text: str) -> str:
    low = text.casefold()
    return next((icon for pattern, icon in _ICON_WORDS if re.search(pattern, low)), "sparkle")


def _answer(bp: BusinessBlueprint, target: str) -> TargetState | None:
    state = bp.discovery.get(target)
    return state if state and state.status in {"answered", "partial"} else None


def _english(text: str) -> bool:
    from platform_core.interview.site_composer import reads_as_english

    return bool(reads_as_english(text))


def _owner_lines(bp: BusinessBlueprint) -> list[str]:
    """What the owner said the business is about, as English sentences."""
    remembered = (bp.discovery.get("brand.story") or TargetState()).quote
    return [s for s in [*_sentences(remembered), *(c.claim for c in bp.website_draft.owner_claims)] if _english(s)]


def _sentences(text: str) -> list[str]:
    return [s.strip(" .") for s in re.split(r"(?<=[.!?])\s+", " ".join((text or "").split())) if s.strip(" .")]


def _cap(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def _fragments(sentence: str) -> list[str]:
    """ "Mother's recipes, stone-ground spices, no preservatives" → its phrases."""
    parts = [p.strip(" .") for p in re.split(r",|;|\band\b|—|–", sentence) if p.strip(" .")]
    return [_cap(p) for p in parts if 1 < len(p.split()) <= 5 and len(p) <= 48]


# ------------------------------------------------------------- statement

_MARK_WORDS = re.compile(
    r"\b(fresh\w*|home\w*|stone[- ]ground|hand\w*|mother'?s|amma'?s|small batch\w*|no preservatives?|"
    r"every (?:week|day|morning)|wood[- ]fire\w*|cut to order|made to order|since \d{4}|by hand|"
    r"grand(?:mother|ma|father)'?s?(?: \w+)?|paati'?s|patti'?s|family recipes?|our own \w+)\b", re.I)
_SMALL = frozenset("a an the of to in on at for and or but is are was we our my your it its this that with "
                   "from by as be every all".split())


def statement_for(bp: BusinessBlueprint, copy: WebsiteCopy, story_body: str) -> dict[str, str] | None:
    """One sentence as a centrepiece: governed copy, else the owner's own line."""
    text = copy.statement
    highlight = copy.statement_highlight
    if not text:
        candidates = [*_owner_lines(bp), *[s for s in _sentences(story_body)[:1] if _english(s)]]
        text = next((c for c in candidates if 6 <= len(c.split()) <= 34), "")
        if text and not re.search(r"[.!?]$", text):
            text += "."
    if not text:
        return None
    if not highlight or highlight not in text:
        found = _MARK_WORDS.search(text)
        highlight = found.group(0) if found else ""
    if not highlight:
        # The sentence's last two words that carry meaning ("Karaikudi kitchen").
        words = re.findall(r"[\w'-]+", text)
        tail = [w for w in words[-3:] if w.casefold() not in _SMALL][-2:]
        if len(words) >= 6 and len(tail) == 2 and " ".join(tail) in text:
            highlight = " ".join(tail)
    return {"text": text[:280], "highlight": highlight[:60]}


# --------------------------------------------------------------- pillars

def pillars_for(bp: BusinessBlueprint, copy: WebsiteCopy, ordering: list[dict[str, str]],
                badges: list[str], visiting: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """What the business stands on: its own phrases, then facts about how it sells."""
    if copy.pillars:
        return [{"title": p.title[:60], "body": p.body[:200], "icon": icon_for(f"{p.title} {p.body}")}
                for p in copy.pillars][:4]
    out: list[dict[str, str]] = []
    seen: list[set[str]] = []

    def add(title: str, body: str = "") -> None:
        words = {w for w in re.findall(r"[a-z]+", title.casefold()) if w not in _SMALL}
        # "Store pickup" after "Pickup" says the same thing twice.
        if title and words and len(out) < 4 and not any(words <= s or s <= words for s in seen):
            seen.append(words)
            out.append({"title": title[:60], "body": body[:200], "icon": icon_for(f"{title} {body}")})

    for sentence in _owner_lines(bp):
        for fragment in _fragments(sentence):
            add(fragment)
    owned = len(out)
    for fact in [*ordering, *(visiting or [])]:
        if fact.get("kind") in {"delivery", "pickup", "weight", "book", "hours"}:
            add(fact["title"], fact.get("body", ""))
    for badge in badges:
        add(badge)
    # What a business stands on is its own to say: two phrases of the owner's
    # at least, or the "pillars" are only the ordering strip again.
    return out if len(out) >= 3 and owned >= 2 else []


# ------------------------------------------------------------------- faq

def _phone(contact: dict[str, Any]) -> str:
    digits = re.sub(r"\D", "", str(contact.get("whatsapp") or contact.get("phone") or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return f"+91 {digits[:5]} {digits[5:]}" if len(digits) == 10 else ""


def faqs_for(bp: BusinessBlueprint, *, ordering: list[dict[str, str]], visiting: list[dict[str, str]],
             contact: dict[str, Any], address: str, booking: bool) -> list[dict[str, str]]:
    """Questions a visitor asks, each answered only from a fact the owner gave."""
    facts = {k: f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items()}
    kinds = {f["kind"]: f for f in ordering}
    out: list[dict[str, str]] = []

    def add(q: str, a: str) -> None:
        a = " ".join(a.split()).strip(" ,;")
        # An answer is a sentence a visitor can use: never a fragment of the
        # owner's reply ("choose the doctor.").
        if not q or len(a.split()) < 3 or len(out) >= 10:
            return
        a = a[0].upper() + a[1:]
        out.append({"q": q[:140], "a": (a if re.search(r"[.!?]$", a) else a + ".")[:500]})

    number = _phone(contact)
    whatsapp, phone = bool(contact.get("whatsapp")), bool(contact.get("phone"))
    verb = "book" if booking else "order"
    if whatsapp and phone:
        add(f"How do I {verb}?", f"Message us on WhatsApp or call {number}" if number
            else "Message us on WhatsApp or give us a call")
    elif whatsapp:
        add(f"How do I {verb}?", f"Message us on WhatsApp{f' at {number}' if number else ''}")
    elif phone:
        add(f"How do I {verb}?", f"Give us a call{f' on {number}' if number else ''}")
    if "delivery" in kinds:
        d = kinds["delivery"]
        if d["title"].lower().startswith("sent by courier"):
            add("Do you deliver?", f"Yes, by courier — {d.get('body', '').strip().rstrip('.').lower() or 'we pack and send it'}")
        else:
            add("Do you deliver?", f"Yes. {d.get('body', '')}")
    if "pickup" in kinds:
        add("Can I pick up my order?", f"Yes. {kinds['pickup'].get('body', '')}")
    if "payment" in kinds:
        add("How can I pay?", kinds["payment"].get("body", ""))
    unit = kinds.get("weight") or kinds.get("order")
    if unit and unit.get("body"):
        add("How is it sold?", unit["body"])
    items = [i for g in bp.taxonomy.groups for i in g.items]
    if items and all(i.diet for i in items):
        if all(i.diet in {"veg", "vegan"} for i in items):
            add("Is everything vegetarian?", "Yes — everything on the menu is vegetarian")
        else:
            add("Do you have vegetarian dishes?",
                "Yes — every dish on the menu is marked vegetarian or non-vegetarian")
    from platform_core.interview.discovery import characteristics

    custom = bp.discovery.get("offerings.customisation")
    # Only a business that makes things to order is asked about custom work
    # (a clinic's FAQ asked "Can I ask for something custom?").
    if custom and custom.status == "answered" and (custom.quote or custom.summary) and \
            characteristics(bp).get("made_to_order") == "observed":
        add("Can I ask for something custom?", custom.quote or custom.summary)
    booked = bp.discovery.get("bookings.format")
    if booking:
        # What can be booked, by name, then how it works in the owner's words.
        names = [i.name for i in items if i.name][:4]
        how = " ".join(((booked.quote or booked.summary) if booked and booked.status == "answered" else "").split())
        listed = (", ".join(names[:-1]) + " or " + names[-1]) if len(names) > 1 else (names[0] if names else "")
        if listed:
            add("What can I book?", f"{listed}." + (f" {how[0].upper()}{how[1:]}" if len(how.split()) >= 4 else ""))
        elif how:
            add("What can I book?", how)
    if facts.get("opening_hours"):
        add("When are you open?", facts["opening_hours"])
    if address:
        add("Where are you?", address)
    del visiting
    return out


# --------------------------------------------------------------- numbers

_FOUNDED = re.compile(r"\b(?:since|started|established|estd\.?|founded|opened|began)\b[^.]{0,48}?\b(19[4-9]\d|20[0-2]\d)\b",
                      re.I)
_OPENS = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|a\.m\.))", re.I)
_OPEN_SAID = re.compile(r"\bopen(?:s|ing)?\b[^.]{0,30}?\b(\d{1,2}(?::\d{2})?\s?(?:am|a\.m\.))", re.I)
_COUNTED = {"menu_commerce": "dishes on the menu", "product_commerce": "items on the counter",
            "service_appointment": "services", "local_service": "services", "membership_fitness": "ways to train",
            "real_estate_projects": "projects", "project_portfolio": "kinds of work", "b2b_rfq": "products"}


def numbers_for(bp: BusinessBlueprint, *, archetype: str, items: list[dict[str, Any]],
                ordering: list[dict[str, str]]) -> list[dict[str, str]]:
    """A band of numbers a visitor can trust: each one a fact the owner gave or
    a count of what they listed — the year they started, how many things are on
    the counter, how many areas they deliver to, when they open. Never a
    rating, a customer count or anything the owner did not say."""
    from platform_core.interview.website_copy import owner_corpus

    out: list[dict[str, str]] = []
    corpus = owner_corpus(bp)
    founded = _FOUNDED.search(corpus)
    if founded:
        out.append({"value": founded.group(1), "label": "Serving since"})
    named = [i for i in items if i.get("name")]
    if len(named) >= 4:
        out.append({"value": str(len(named)), "label": _COUNTED.get(archetype, "things to choose from")})
    area = bp.discovery.get("fulfilment.area")
    if area and area.status in {"answered", "partial"}:
        places = [p for p in re.split(r",|\band\b|&", area.summary or area.quote) if p.strip(" .")]
        if 2 <= len(places) <= 12:
            out.append({"value": str(len(places)), "label": "areas we deliver to"})
    hours = {k: f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items()}.get("opening_hours", "")
    opens = _OPENS.search(hours) or _OPEN_SAID.search(corpus)
    if opens:
        out.append({"value": opens.group(1).replace(" ", "").replace(".", "").lower(), "label": "we open"})
    # Two numbers set enormous look thin, not proud: a band needs three.
    return out if len(out) >= 3 else []


# ------------------------------------------------------------ media rows

_PLAN_GROUP = re.compile(r"\b(plans?|memberships?|packages?|pass(es)?|fees|pricing)\b", re.I)
_CRAFT_EYEBROW = {"menu_commerce": "How we cook", "membership_fitness": "How we train",
                  "service_appointment": "How we work", "local_service": "How we work",
                  "project_portfolio": "How we work", "real_estate_projects": "How we build"}


def media_rows_for(bp: BusinessBlueprint, copy: WebsiteCopy, *, trade_label: str, ordering: list[dict[str, str]],
                   pictures: dict[str, str | None], archetype: str = "") -> list[dict[str, Any]]:
    """Two or three passages, each beside its own picture: the range, how it is
    made, how it reaches you — from the owner's words."""
    rows: list[dict[str, Any]] = []
    # What is offered, not how it is paid for: a gym's "Plans" is no passage.
    groups = [g for g in bp.taxonomy.groups if g.name and not _PLAN_GROUP.search(g.name)]
    craft = [f for s in _owner_lines(bp) for f in _fragments(s)]
    # The range's picture is shown again in the range itself; with no passage
    # about the making, the picture of the making stands beside the range.
    range_picture = pictures.get("range") if craft else (pictures.get("process") or pictures.get("range"))
    if groups:
        names = [g.name for g in groups][:4]
        title = ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1 else names[0])
        body = copy.catalogue_intro or copy.offerings_subtitle or next(
            (g.description for g in groups if g.description), "")
        unit = next((f["body"] for f in ordering if f["kind"] in {"weight", "order"} and f.get("body")), "")
        rows.append({"eyebrow": trade_label, "title": _cap(title)[:80], "body": (body or unit)[:360],
                     "image_asset_id": range_picture})
    remembered = (bp.discovery.get("brand.story") or TargetState()).quote
    story_lines = [s for s in (_sentences(copy.about_body) or _sentences(remembered)) if _english(s)]
    if craft:
        rows.append({"eyebrow": _CRAFT_EYEBROW.get(archetype, "How we do it"), "title": craft[0][:80],
                     "body": (story_lines[0] + "." if story_lines else "")[:360],
                     "image_asset_id": pictures.get("process")})
    kinds = {f["kind"]: f for f in ordering}
    reach = kinds.get("delivery") or kinds.get("pickup")
    if reach:
        more = [kinds[k]["body"] for k in ("pickup", "payment") if k in kinds and kinds[k] is not reach]
        rows.append({"eyebrow": "Getting it to you", "title": reach["title"][:80],
                     "body": " ".join([reach.get("body", ""), *more]).strip()[:360],
                     "image_asset_id": pictures.get("detail")})
    rows = [{k: v for k, v in r.items() if v} for r in rows if r.get("title")]
    return rows if len(rows) >= 2 else []


# ------------------------------------------------------------------ pages

@dataclass
class Site:
    pages: list[dict[str, Any]]
    navigation: list[dict[str, str]]
    range_path: str = ""
    visit_path: str = ""
    notes: list[str] = field(default_factory=list)


def _section(type_id: str, variant: str, content: dict[str, Any]) -> dict[str, Any]:
    return {"section_type_id": type_id, "layout_variant": variant, "content": content, "is_visible": True}


def _page_hero(eyebrow: str, headline: str, sub: str, image: str | None) -> dict[str, Any]:
    content: dict[str, Any] = {"headline": headline[:120]}
    if eyebrow:
        content["eyebrow"] = eyebrow[:60]
    if sub:
        content["subheadline"] = sub[:300]
    if image:
        content["image_asset_id"] = image
    return _section("hero", "page", content)


# The order a home page tells its story in, by art direction: a quiet brand
# leads with its sentence and its story, a market with its range and how to
# order, a gym with its numbers. Roles a site does not have are skipped.
_RHYTHM = {
    "quiet_luxury": ("statement", "range", "story", "pillars", "numbers", "steps", "faq"),
    "warm_craft": ("statement", "story", "range", "pillars", "steps", "numbers", "faq"),
    "fresh_market": ("range", "steps", "pillars", "numbers", "statement", "story", "faq"),
    "kinetic_sport": ("statement", "numbers", "range", "pillars", "steps", "story", "faq"),
    "noir_editorial": ("statement", "range", "pillars", "numbers", "story", "steps", "faq"),
    "calm_care": ("range", "steps", "pillars", "story", "numbers", "faq"),
    "technical_grid": ("range", "numbers", "pillars", "steps", "story", "faq"),
    "playful_pop": ("range", "statement", "pillars", "steps", "numbers", "story", "faq"),
}


def _role(section: dict[str, Any]) -> str:
    kind = section["section_type_id"]
    content = section.get("content") or {}
    if kind in {"product_showcase", "category_showcase"}:
        return "range" if content.get("anchor") in {"shop", None, ""} else "range+"
    return {"statement": "statement", "pillars": "pillars", "highlights": "numbers", "fulfilment_strip": "steps",
            "about": "story", "media_text": "story", "faq": "faq",
            "feature_grid": "steps" if section.get("layout_variant") == "steps" else "pillars"}.get(kind, "")


def arrange(sections: list[dict[str, Any]], concept: str, lead: str = "") -> list[dict[str, Any]]:
    """Home's middle in the order its art direction tells it. The opening (hero,
    its moving band) and the close (band, contact) stay where they are; the
    owner's own "put X higher" stays right after the opening."""
    rhythm = _RHYTHM.get(concept)
    if not rhythm:
        return sections
    head = [s for s in sections[:2] if s["section_type_id"] in {"hero", "marquee"}]
    tail = [s for s in sections if s["section_type_id"] in {"cta_band", "contact"}]
    middle = [s for s in sections if s not in head and s not in tail]

    def rank(item: tuple[int, dict[str, Any]]) -> tuple[float, int]:
        at, section = item
        role = _role(section)
        if role == "range+":
            return (rhythm.index("range") + 0.5 if "range" in rhythm else 99.0, at)
        return (float(rhythm.index(role)) if role in rhythm else 99.0, at)

    middle = [s for _, s in sorted(enumerate(middle), key=rank)]
    first = next((s for s in middle if lead and s["section_type_id"] == lead), None)
    if first:
        middle.remove(first)
        middle.insert(0, first)
    return head + middle + tail


def _category_tiles(content: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each pictured category as a card: its name, the things in it, where its
    prices start — the owner's own catalogue, said shorter."""
    tiles = []
    for category in content.get("categories") or []:
        if not category.get("image_asset_id"):
            continue
        tile: dict[str, Any] = {"name": str(category["name"])[:80], "image_asset_id": category["image_asset_id"]}
        names = [str(i["name"]) for i in items if i.get("category") == category["name"]][:4]
        if names:
            tile["description"] = ", ".join(names)[:200]
        if category.get("meta"):
            tile["price"] = str(category["meta"])[:40]
        tiles.append(tile)
    return tiles[:6]


def _featured(items: list[dict[str, Any]], at_most: int = 6) -> list[dict[str, Any]]:
    """The home page's teaser: the owner's tagged favourites, then pictured ones."""
    ranked = sorted(items, key=lambda i: (0 if i.get("tag") else 1, 0 if i.get("image_asset_id") else 1))
    return ranked[:at_most]


def build(
    bp: BusinessBlueprint,
    *,
    copy: WebsiteCopy,
    archetype: str,
    name: str,
    home: list[dict[str, Any]],
    trade_label: str,
    ordering: list[dict[str, str]],
    visiting: list[dict[str, str]],
    badges: list[str],
    contact: dict[str, Any],
    address: str,
    booking: bool,
    pictures: dict[str, str | None],
    dna_seed: int,
    range_variant: str = "",
    order_link: str = "",
    concept: str = "",
    keep_order: bool = False,
    lead: str = "",
) -> Site:
    """Home and inner pages from the composed home sections and the owner's facts."""
    def first_of(kind: str) -> dict[str, Any] | None:
        return next((s for s in home if s["section_type_id"] == kind), None)

    hero = first_of("hero")
    story = first_of("about")
    showcase = next((s for s in home if s["section_type_id"] in {"product_showcase", "category_showcase"}
                     and s["content"].get("anchor") == "shop"), None)
    how = first_of("fulfilment_strip")
    contact_section = first_of("contact")

    hero_picture = (hero or {}).get("content", {}).get("image_asset_id")
    statement = statement_for(bp, copy, str((story or {}).get("content", {}).get("body", "")))
    pillars = pillars_for(bp, copy, ordering, badges, visiting)
    faqs = faqs_for(bp, ordering=ordering, visiting=visiting, contact=contact, address=address, booking=booking)
    rows = media_rows_for(bp, copy, trade_label=trade_label, ordering=ordering, pictures=pictures,
                          archetype=archetype)

    items = list((showcase or {}).get("content", {}).get("items") or [])
    range_page = bool(showcase and showcase["section_type_id"] == "product_showcase" and len(items) >= 6)
    about_page = bool(story and (rows or first_of("feature_grid") or first_of("highlights")))
    visit_page = bool(contact_section and (len(faqs) >= 3 or address))
    slug, page_type = _RANGE_BY_LABEL.get(trade_label.strip().casefold()) or _RANGE_PAGE.get(
        archetype, ("offerings", "offerings"))

    # ---- the extra sections, in the site's own variants
    statement_section = None
    if statement:
        # A cinematic brand sets its sentence over a full-bleed photograph; others
        # beside a picture, or in giant type on its own.
        picture = pictures.get("process")
        variant = ("image" if picture and concept in {"noir_editorial", "quiet_luxury", "kinetic_sport"} else
                   "split" if picture and dna_seed % 3 == 0 else "giant")
        content: dict[str, Any] = {"text": statement["text"]}
        if statement["highlight"]:
            content["highlight"] = statement["highlight"]
        if variant != "giant":
            content["image_asset_id"] = picture
        statement_section = _section("statement", variant, content)
    pillars_section = None
    if pillars:
        bodies = sum(1 for p in pillars if p["body"])
        # The pillars follow the range, which is usually a grid of cards: so a
        # numbered list beside a picture, or a ruled strip — chosen per
        # business — and cards only where the range is a list.
        listed = not range_page and str((showcase or {}).get("layout_variant") or "") in {
            "compact_list", "menu_book", "hover_list"}
        if bodies == 0:
            variant = "strip"
        elif listed:
            variant = "cards"
        else:
            variant = "numbered" if bodies == len(pillars) and dna_seed % 3 != 1 else "strip"
        pillars_content: dict[str, Any] = {"items": pillars}
        if variant == "numbered" and (pictures.get("detail") or pictures.get("process")):
            # What the business stands on, beside a close picture of it.
            pillars_content["image_asset_id"] = pictures.get("detail") or pictures.get("process")
        if copy.pillars_title:
            pillars_content["title"] = copy.pillars_title
        elif variant != "strip":
            pillars_content["title"] = "What we stand on"
        pillars_section = _section("pillars", variant, pillars_content)
    rows_section = _section("media_text", "alternating", {"items": rows}) if rows else None

    def faq_section(questions: list[dict[str, str]], variant: str, title: str = "Good to know") -> dict[str, Any] | None:
        return _section("faq", variant, {"title": title, "items": questions}) if len(questions) >= 2 else None

    story_teaser = None
    row: dict[str, Any] = {}
    if about_page and story:
        said =(statement or {}).get("text", "").casefold()
        told = [s for s in _sentences(str(story["content"].get("body") or "")) if s.casefold() not in said]
        title = str(story["content"].get("title") or "Our story")[:80]
        eyebrow = str(story["content"].get("eyebrow") or "Our story")[:40]
        row = {"eyebrow": "" if eyebrow.casefold() == title.casefold() else eyebrow, "title": title,
               "body": (". ".join(told[:2]) + "." if told else "")[:360]}
        if story["content"].get("image_asset_id"):
            row["image_asset_id"] = story["content"]["image_asset_id"]
    if row.get("body"):
        # Only when it has something the page has not said yet.
        story_teaser = _section("media_text", "alternating", {
            "items": [{k: v for k, v in row.items() if v}], "more_label": "Our story", "more_path": "/about"})
    if showcase and showcase["section_type_id"] == "product_showcase":
        showcase["content"]["eyebrow"] = trade_label[:40]

    multi = range_page or about_page or visit_page
    range_path = f"/{slug}" if range_page else ""
    visit_path = "/visit" if visit_page else ""

    # ---- home
    teaser = None
    if range_page and showcase:
        content = {**showcase["content"], "items": _featured(items),
                   "more_label": _MORE_BY_SLUG.get(slug) or _MORE_LABEL.get(archetype, "See all"),
                   "more_path": range_path}
        content.pop("filters", None)
        pictured = sum(1 for i in content["items"] if i.get("image_asset_id"))
        tiles = _category_tiles(content, items)
        if pictured < 3 and len(tiles) >= 2:
            # A taste of the range as one picture per kind — what is in it and
            # where its prices start — not the whole price list again.
            content["items"] = tiles
            teaser = _section("product_showcase", "bento", content)
        # The home page keeps the experience's scene for the range (a ring, a
        # bento, a spotlight); its own page lists everything to browse.
        scene = showcase["layout_variant"] if showcase["layout_variant"] in _SCENES else ""
        # Otherwise a taste of the range the way the trade browses it (a board
        # per meat, a price list), or its best pictures large.
        if teaser is None:
            teaser = _section("product_showcase", scene or (
                "spotlight" if pictured >= 3 and dna_seed % 2 == 0 else
                "bento" if pictured >= 3 else str(showcase["layout_variant"])), content)
    numbers = [] if first_of("highlights") else numbers_for(bp, archetype=archetype, items=items, ordering=ordering)
    numbers_section = _section("highlights", "counters", {"items": numbers}) if numbers else None
    home_out: list[dict[str, Any]] = []
    for section in home:
        kind = section["section_type_id"]
        if section is showcase and teaser:
            home_out.append(teaser)
            if pillars_section and not about_page:
                home_out.append(pillars_section)
            continue
        if kind == "fulfilment_strip" and range_page:
            # How ordering works lives once, on the range's own page, beside
            # what is ordered (certification: the menu page replayed home's
            # steps, FAQ and closing band word for word).
            if numbers_section:
                home_out.append(numbers_section)
            continue
        if kind == "about" and about_page:
            # The story lives on its own page; the home page tells its start.
            if story_teaser:
                home_out.append(story_teaser)
            continue
        if kind == "contact" and visit_page:
            continue
        if kind == "cta_band":
            if not about_page and rows_section:
                home_out.append(rows_section)
            # The questions live once: on the visit page when there is one.
            questions = None if visit_page else faq_section(
                faqs[:6], "split" if dna_seed % 2 else "accordion", "Questions, answered")
            if questions:
                home_out.append(questions)
        home_out.append(section)
        if kind in {"hero", "marquee"} and statement_section and statement_section not in home_out:
            nxt = home[home.index(section) + 1] if home.index(section) + 1 < len(home) else None
            if not nxt or nxt["section_type_id"] != "marquee":
                home_out.append(statement_section)
    if numbers_section and numbers_section not in home_out:
        # Beside what the business stands on, or after its range.
        after = next((i for i, s in enumerate(home_out) if s is pillars_section), None)
        if after is None:
            after = next((i for i, s in enumerate(home_out) if s["section_type_id"] in {
                "product_showcase", "category_showcase"}), 0)
        home_out.insert(after + 1, numbers_section)
    if pillars_section and pillars_section not in home_out and not about_page:
        at = next((i for i, s in enumerate(home_out) if s["section_type_id"] in {"product_showcase",
                                                                                 "category_showcase"}), 0)
        home_out.insert(at + 1, pillars_section)
    if statement_section and statement_section not in home_out:
        home_out.insert(1, statement_section)

    if not keep_order:
        # The model did not choose an order: the art direction's rhythm.
        home_out = arrange(home_out, concept, lead)

    pages: list[dict[str, Any]] = [{
        "slug": "home", "title": "Home", "page_type": "home", "sections": home_out,
        "seo_title": name[:160],
        "seo_description": str((hero or {}).get("content", {}).get("subheadline") or "")[:300],
    }]

    # ---- the range
    if range_page and showcase:
        full = {**showcase, "content": {**showcase["content"]}}
        variant = range_variant or showcase["layout_variant"]
        if variant == "menu_grid" and showcase["layout_variant"] == "menu_book":
            variant = "menu_book"  # the menu as a book, on its own page too
        pictured_all = sum(1 for i in items if i.get("image_asset_id"))
        kinds = [c for c in full["content"].get("categories") or [] if c.get("name")]
        if len(kinds) >= 2 and sum(1 for c in kinds if c.get("image_asset_id")) >= 2:
            # Each kind its own chapter: a large picture, its name, where its
            # prices start, its lines like a printed menu.
            variant = "chapters"
        elif variant in {"commerce_grid", "compact_list"} and pictured_all >= 4 and dna_seed % 2:
            variant = "hover_list"  # a price list whose pictures follow the pointer
        full["layout_variant"] = variant
        # An opening picture the range below does not show again.
        first = pictures.get("detail") or hero_picture or pictures.get("range")
        range_sections = [_page_hero(trade_label, str(full["content"].get("title") or trade_label),
                                     copy.catalogue_intro or str(full["content"].get("subtitle") or ""), first), full]
        # How it is made or sourced, and how it reaches you: the owner's words,
        # beside pictures, between the range and the ordering details.
        made = [r for r in rows if r.get("eyebrow") != trade_label]
        if len(made) >= 2:
            range_sections.append(_section("media_text", "alternating", {"items": made}))
        if how:
            steps = how["content"].get("items") or []
            range_sections.append(_section("fulfilment_strip", "steps" if len(steps) >= 3 else "icons",
                                           {**how["content"]}))
        if not visit_page:
            ordering = [f for f in faqs if not f["q"].startswith(("Where", "When"))]
            ordering_qs = faq_section(ordering[:5], "accordion", "Ordering, answered")
            if ordering_qs:
                range_sections.append(ordering_qs)
        # The page ends on its own last section and the footer: home's closing
        # band on every page read as one page replayed.
        pages.append({"slug": slug, "title": trade_label, "page_type": page_type, "sections": range_sections,
                      "seo_title": f"{trade_label} — {name}"[:160],
                      "seo_description": str(full["content"].get("subtitle") or "")[:300]})

    # ---- about
    if about_page and story:
        content = story["content"]
        # The page opens on the business's name; the story below keeps its own title.
        about_sections = [_page_hero("About", name, copy.about_intro or "",
                                     hero_picture or pictures.get("process")),
                          story]
        if statement_section and statement_section not in home_out:
            about_sections.append(statement_section)
        if rows_section:
            pictured_rows = sum(1 for r in rows if r.get("image_asset_id"))
            about_sections.append(_section("media_text", "sticky" if pictured_rows >= 2 else "alternating",
                                           {"items": rows}))
        if pillars_section:
            # What the business stands on lives here, once — numbered beside a
            # picture or as a ruled strip, never a grid of icon cards.
            stands_on = deepcopy(pillars_section)
            if stands_on["layout_variant"] == "cards":
                stands_on["layout_variant"] = "numbered" if all(
                    p.get("body") for p in stands_on["content"].get("items") or []) else "strip"
            about_sections.append(stands_on)
        for kind in ("feature_grid", "highlights"):
            about_sections += [s for s in home if s["section_type_id"] == kind and s not in home_out]
        if numbers_section and numbers_section not in home_out:
            about_sections.append(numbers_section)
        pages.append({"slug": "about", "title": "About", "page_type": "about", "sections": about_sections,
                      "seo_title": f"About — {name}"[:160],
                      "seo_description": str(content.get("body") or "")[:300]})

    # ---- visit
    if visit_page and contact_section:
        place = {**contact_section, "content": {**contact_section["content"]}}
        if address and (re.search(r"\d", address) or "," in address):
            place["content"]["show_map"] = True
        hours = str(place["content"].get("hours_summary") or "")
        sub = copy.visit_intro or " · ".join(p for p in (address, hours) if p)
        visit_sections = [_page_hero(str(place["content"].get("title") or "Visit us"),
                                     "Come and see us" if address else "Get in touch", sub,
                                     pictures.get("story") or hero_picture), place]
        if how and not range_page:
            visit_sections.append(_section("fulfilment_strip", "icons", {**how["content"]}))
        everything = faq_section(faqs, "split", "Questions, answered")
        if everything:
            visit_sections.append(everything)
        pages.append({"slug": "visit", "title": "Visit", "page_type": "contact", "sections": visit_sections,
                      "seo_title": f"Visit — {name}"[:160], "seo_description": sub[:300]})

    navigation = [{"label": "Home", "path": "/"}]
    if range_page:
        navigation.append({"label": trade_label, "path": range_path})
    elif showcase:
        navigation.append({"label": trade_label, "path": "/#shop"})
    if about_page:
        navigation.append({"label": "About", "path": "/about"})
    elif story:
        navigation.append({"label": "About", "path": "/#story"})
    if visit_page:
        navigation.append({"label": "Visit", "path": "/visit"})
    elif contact_section:
        navigation.append({"label": "Contact", "path": "/#contact"})

    # Each page owns its sections: a closing band on two pages is two bands,
    # so polishing one never changes the other.
    for page in pages:
        page["sections"] = [deepcopy(s) for s in page["sections"]]
    # A button that pointed at a section now on another page follows it there.
    for page in pages:
        for section in page["sections"]:
            content = section.get("content") or {}
            for key in ("cta_url", "more_path"):
                value = str(content.get(key) or "")
                if value == "#shop" and range_page:
                    content[key] = range_path
                elif value == "#contact" and visit_page:
                    content[key] = visit_path
    return Site(pages=pages, navigation=navigation, range_path=range_path, visit_path=visit_path,
                notes=[] if multi else ["single page: not enough yet for inner pages"])
