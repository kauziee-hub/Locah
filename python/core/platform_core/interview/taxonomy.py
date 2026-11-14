"""What a business sells, as a structure — not a comma list.

"We sell chicken, mutton, fish different varieties" used to become three
website cards, one of them titled "Fish different varieties". A merchandiser
reads the same sentence as: Chicken, Mutton and Fish are *groups*; the owner
keeps several kinds of fish without having named them yet; and whether people
choose cuts is still unknown. That reading decides what the site shows (a
category grid, a product grid, chips) and what is worth asking next ("which
fish do you usually keep?"), so it is kept here as first-class state.

The model proposes the grouping each turn; this module decides what is kept:

* item names must be built from the owner's own words;
* a group label may be Locah's ("Fish & Seafood") only when it groups items
  the owner named, and it is marked as a suggestion;
* phrases like "different varieties", "all kinds", "etc" are signals that a
  group has depth, never item names;
* prices and units are kept only when every number in them is the owner's.

Nothing here branches on a kind of business.
"""

from __future__ import annotations

import re

from platform_core.interview.models import (
    BusinessBlueprint,
    CatalogueEdit,
    CatalogueGroup,
    CatalogueItem,
    GroupProposal,
)
from platform_core.interview.website_copy import _built_from_owner_words, _grounded, owner_corpus

# Phrases that say "there are more of these" without naming them.
_DEPTH = re.compile(
    r"\b(?:(?:all|different|various|many|several|lots of|every)\s+(?:types?|kinds?|sorts?|varieties|variety|items?)(?:\s+of)?|"
    r"(?:different|various|many)\s+varieties|varieties|variety|and\s+more|and\s+others?|etc\.?|"
    r"so\s+on|everything)\b",
    re.I,
)
_LEAD = re.compile(
    r"^(?:(?:we|i)\s+(?:also\s+)?(?:mainly\s+|mostly\s+|usually\s+)?(?:sell|make|do|offer|serve|provide|keep|have)\s+|"
    r"(?:mostly|mainly|also|and)\s+)",
    re.I,
)
_UNIT_WORDS = re.compile(
    r"\b(kg|kilo\w*|g|gm|grams?|piece|pieces|pcs|pack|packs|jar|jars|bottle|litre|liter|l|ml|"
    r"plate|plates|box|boxes|dozen|each|per|portion|serving|sq\.?\s?ft|sqft|bhk|month|months|year|"
    r"session|sessions|class|classes)\b",
    re.I,
)
_DIGITS = re.compile(r"\d[\d,.]*")


_TRAILING_FILLER = re.compile(r"(?:\s+(?:also|too|as well|only|both|etc\.?))+$", re.I)
_WHO_FOR = re.compile(r"(?:(?:ladies|gents|men|mens|women|womens|boys|girls|kids|children|unisex|everyone|all|and|&|,|"
                      r"both|for)\W*)+", re.I)


def normalise_name(text: str) -> tuple[str, bool]:
    """(clean name, whether the owner signalled more of it).

    "fish different varieties" -> ("Fish", True); "all types of meat" ->
    ("Meat", True); "chicken" -> ("Chicken", False).
    """
    raw = " ".join((text or "").split()).strip(" .,;:-")
    raw = _LEAD.sub("", raw)
    deep = bool(_DEPTH.search(raw))
    name = _DEPTH.sub(" ", raw)
    name = re.sub(r"\b(?:of|and|the)\s*$", "", " ".join(name.split()), flags=re.I).strip(" .,;:-")
    # "Bridal makeup also", "facial too": how it was said, not what it is called.
    name = _TRAILING_FILLER.sub("", name).strip(" .,;:-")
    if not name or (_WHO_FOR.fullmatch(name) and len(name.split()) >= 2):
        # "Ladies gents both" says who the business serves; it is not a shelf.
        # (One word — "Kids", "Men" — is a clothes shop's real shelf.)
        return "", deep
    return name[0].upper() + name[1:], deep


def split_listing(text: str) -> list[str]:
    """An owner's list of what they sell, as separate phrases."""
    cleaned = _LEAD.sub("", " ".join((text or "").split()).strip(" ."))
    parts = re.split(r"\s*(?:[,;/]|\band\b|&|\bplus\b)\s*", cleaned, flags=re.I)
    return [p.strip(" .") for p in parts if p.strip(" .")]


# How a thing is sold, said after its name: "fish by the kg", "podi in jars".
_SOLD_AS = re.compile(
    r"\s+(?:by the (?:kg|kilo|piece|dozen|litre|box)|per (?:kg|kilo|piece|plate|litre)|in (?:jars|packs|bulk)|"
    r"(?:cut |made )?(?:fresh(?:ly)?|daily)(?: to order)?)$", re.I)
# A clause, not a thing sold: who does what ("people order on WhatsApp", "we deliver around …").
_CLAUSE = re.compile(
    r"\b(?:we|i|people|customers|they|you|our customers|order|orders|ordering|deliver\w*|pick(?:s|ing)? up|"
    r"call|whatsapp|book\w*|visit|open|to order|cut|made|cooked|come|serve)\b", re.I)


def taxonomy_from_listing(text: str) -> list[CatalogueGroup]:
    """The plain reading when the model offered none: one group per phrase.

    Only the listing itself: the first sentence, after any "Our projects:"
    label, each phrase trimmed of how it is sold — and never a clause about
    ordering or delivery, which is not something the business sells.
    """
    groups: list[CatalogueGroup] = []
    first = re.split(r"(?<=[a-z0-9)])\.\s+", " ".join((text or "").split()), maxsplit=1)[0]
    # "Our projects: A, B" / "home-style food — idli, dosa": the list follows the label.
    labelled = re.split(r":\s|\s[—–-]\s", first, maxsplit=1)
    if len(labelled) == 2 and "," in labelled[1]:
        first = labelled[1]
    for part in split_listing(first):
        part = _SOLD_AS.sub("", part).strip(" .")
        if not part or _CLAUSE.search(part) or len(part.split()) > 5:
            continue
        name, deep = normalise_name(part)
        if not name or len(name) > 60 or re.search(r"\d", name):
            continue
        if any(g.name.casefold() == name.casefold() for g in groups):
            continue
        groups.append(CatalogueGroup(name=name[:80], needs=["varieties"] if deep else []))
    return groups[:12]


def _numbers_owned(text: str, corpus: str) -> bool:
    owned = {re.sub(r"[,.]", "", n) for n in _DIGITS.findall(corpus)}
    return all(re.sub(r"[,.]", "", n) in owned for n in _DIGITS.findall(text or ""))


def _price(value: str, corpus: str) -> str:
    value = " ".join((value or "").split())[:40]
    if not value or not _DIGITS.search(value) or not _numbers_owned(value, corpus):
        return ""
    return value


def _unit(value: str, corpus: str) -> str:
    value = " ".join((value or "").split())[:40]
    if not value or not _numbers_owned(value, corpus):
        return ""
    if _UNIT_WORDS.search(value) or _built_from_owner_words(value, corpus):
        return value
    return ""


def _find(groups: list[CatalogueGroup], name: str) -> CatalogueGroup | None:
    key = name.casefold()
    return next((g for g in groups if g.name.casefold() == key), None)


def govern_catalogue(bp: BusinessBlueprint, proposals: list[GroupProposal], heard: str) -> bool:
    """Fold the model's reading of the range into the Blueprint. Returns whether it changed."""
    if not proposals:
        return False
    corpus = " ".join([owner_corpus(bp), heard])
    groups = [g.model_copy(deep=True) for g in bp.taxonomy.groups]
    before = [g.model_dump() for g in groups]
    for proposal in proposals:
        label, label_deep = normalise_name(proposal.group)
        if not label and proposal.items and (proposal.group or "").strip():
            # The model's shelf was no shelf ("Ladies gents both"): its items
            # are still the owner's, and go on the trade's plain one.
            from platform_core.interview.catalogue_capture import _default_group

            label = _default_group(bp)
        elif not label or len(label.split()) > 5 or not _grounded(label, corpus):
            continue
        items: list[CatalogueItem] = []
        unknown = set(proposal.unknown)
        if label_deep:
            unknown.add("varieties")
        for raw in proposal.items:
            # "Aranya Greens - 3 BHK villas in Thalambur": a name, then what it is.
            parts = re.split(r"\s+[-–—:]\s+", raw.name, maxsplit=1)
            head, tail = parts[0], (parts[1] if len(parts) > 1 else "")
            name, deep = normalise_name(head)
            if deep:
                # "fish different varieties" inside a group: the group has depth.
                unknown.add("varieties")
                if not name or name.casefold() == label.casefold():
                    continue
            if not name or not _built_from_owner_words(name, corpus) or len(name) > 60:
                continue
            if name.casefold() == label.casefold():
                continue  # "Chicken" is the group, not one of its items
            if any(i.name.casefold() == name.casefold() for i in items):
                continue
            about = " ".join(tail.split()).strip(" .,")
            items.append(CatalogueItem(
                name=name[:80], price=_price(raw.price, corpus), unit=_unit(raw.unit, corpus),
                description=about[:240] if about and len(about) <= 160 and _grounded(about, corpus) else "",
            ))
        owner_label = _built_from_owner_words(label, corpus)
        if not owner_label and not items:
            continue  # a label of Locah's own needs owner-named items under it
        group = _find(groups, label)
        if group is None:
            group = CatalogueGroup(name=label[:80], label_source="owner" if owner_label else "ai_suggestion")
            groups.append(group)
        for item in items:
            existing = next((i for i in group.items if i.name.casefold() == item.name.casefold()), None)
            if existing is None:
                if len(group.items) < 24:
                    group.items.append(item)
            elif existing.source != "owner_edited":
                existing.price = item.price or existing.price
                existing.unit = item.unit or existing.unit
            # An item that was a group of its own ("Crab") now lives inside
            # this one ("Fish & Seafood"): one place, not two.
            standalone = _find(groups, item.name)
            if standalone is not None and standalone is not group and not standalone.items:
                groups.remove(standalone)
        if group.items:
            # "Fish" was heard first with no varieties; "Fish & Seafood" now
            # holds them. The empty one is the same shelf — one place, not two.
            label_words = set(re.findall(r"[a-z]{3,}", group.name.casefold()))
            for other in list(groups):
                words = set(re.findall(r"[a-z]{3,}", other.name.casefold()))
                if other is not group and not other.items and words and words <= label_words:
                    group.needs = list(dict.fromkeys([*group.needs, *other.needs]))
                    groups.remove(other)
        group.sold_by = " ".join(proposal.sold_by.split())[:80] if proposal.sold_by and _grounded(
            proposal.sold_by, corpus) else group.sold_by
        group.price = _price(proposal.price, corpus) or group.price
        group.unit = _unit(proposal.unit, corpus) or group.unit
        structural = [n for n in group.needs if n in {"varieties", "cuts", "sizes"}]
        if items and "varieties" in structural and "varieties" not in unknown:
            structural.remove("varieties")  # they named them
        for need in ("varieties", "cuts", "sizes"):
            if need in unknown and need not in structural:
                structural.append(need)
            elif need not in unknown and need in structural and need != "varieties":
                structural.remove(need)
        group.needs = structural + (["price"] if "price" in group.needs else [])
    groups = _tidy(groups)[:12]
    bp.taxonomy.groups = groups
    from platform_core.interview.catalogue_capture import respell

    respell(bp)
    refresh_needs(bp)
    return [g.model_dump() for g in bp.taxonomy.groups] != before


def _tidy(groups: list[CatalogueGroup]) -> list[CatalogueGroup]:
    """One shelf per thing: no group inside itself, no group repeated inside another.

    A turn can read "Crab and squid we clean and sell by kg" as groups "Crab",
    "Squid" and "Crab & Squid" while "Fish & Seafood" already holds both —
    four boards (and four drawn pictures) for two things.
    """
    for group in groups:
        items: list[CatalogueItem] = []
        for item in group.items:
            # Stored before names were split: "Aranya Greens - 3 BHK villas ...".
            parts = re.split(r"\s+[-–—:]\s+", item.name, maxsplit=1)
            if len(parts) > 1 and parts[0].strip():
                item = item.model_copy(update={"name": parts[0].strip()[:80],
                                               "description": item.description or parts[1].strip()[:240]})
            if item.name.casefold() == group.name.casefold():
                continue
            same = next((i for i in items if i.name.casefold() == item.name.casefold()), None)
            if same is None:
                items.append(item)
            else:
                same.description = same.description or item.description
                same.price, same.unit = same.price or item.price, same.unit or item.unit
        group.items = items

    def names(g: CatalogueGroup) -> set[str]:
        return {i.name.casefold() for i in g.items}

    kept: list[CatalogueGroup] = []
    for group in groups:
        own = names(group)
        elsewhere = [o for o in groups if o is not group and o.items]
        if not group.items and any(group.name.casefold() in names(o) for o in elsewhere):
            continue  # "Crab" is already an item of another group
        bigger = next((o for o in elsewhere if own and own < names(o)), None)
        if bigger is not None:
            bigger.price = bigger.price or group.price
            bigger.unit = bigger.unit or group.unit
            continue  # "Crab & Squid" is inside "Fish & Seafood"
        kept.append(group)
    return kept



def apply_edits(bp: BusinessBlueprint, edits: list[CatalogueEdit]) -> list[str]:
    """Apply what the owner typed. They are the source; nothing is checked against the chat."""
    touched: list[str] = []
    for edit in edits:
        group = _find(bp.taxonomy.groups, " ".join(edit.group.split()))
        if group is None:
            continue
        price = " ".join(edit.price.split())[:40]
        unit = " ".join(edit.unit.split())[:40]
        if price and not re.search(r"\d", price):
            raise ValueError("A price needs a number")
        if edit.item:
            item = next((i for i in group.items if i.name.casefold() == edit.item.casefold()), None)
            if item is None:
                continue
            item.price, item.unit, item.source = price or item.price, unit or item.unit, "owner_edited"
        elif price or unit:
            group.price, group.unit = price or group.price, unit or group.unit
        for raw in edit.add_items:
            name, vague = normalise_name(raw)
            if name and not vague and all(i.name.casefold() != name.casefold() for i in group.items):
                group.items.append(CatalogueItem(name=name[:80], source="owner_edited"))
                group.needs = [n for n in group.needs if n != "varieties"]
        touched.append(group.name)
    refresh_needs(bp)
    return touched


def refresh_needs(bp: BusinessBlueprint) -> None:
    """Price is needed where nothing in a group has one; structure needs stay as read.

    A property seller's category ("Villas") is not what a buyer chooses — a
    named project is. Until a category has projects under it, it needs them.
    """
    property_led = _property_led(bp)
    for group in bp.taxonomy.groups:
        needs = [n for n in group.needs if n not in {"price", "projects"}]
        if property_led and not group.items:
            needs.insert(0, "projects")
        if not group.price and not any(i.price for i in group.items):
            needs.append("price")
        group.needs = needs[:5]


def _property_led(bp: BusinessBlueprint) -> bool:
    from platform_core.interview.creative_director import _PROPERTY

    return bool(_PROPERTY.search(owner_corpus(bp)))


def ensure_taxonomy(bp: BusinessBlueprint) -> None:
    """A structure exists whenever the owner has said what they sell — and is tidy."""
    if bp.taxonomy.groups:
        tidy = _tidy([g.model_copy(deep=True) for g in bp.taxonomy.groups])
        if [g.model_dump() for g in tidy] != [g.model_dump() for g in bp.taxonomy.groups]:
            bp.taxonomy.groups = tidy
            refresh_needs(bp)
        return
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    if "offerings" in facts:
        bp.taxonomy.groups = taxonomy_from_listing(facts["offerings"].value)
        refresh_needs(bp)


def open_structure(bp: BusinessBlueprint) -> list[CatalogueGroup]:
    """Groups whose shape is still unknown — varieties, cuts or sizes."""
    return [g for g in bp.taxonomy.groups if {"varieties", "cuts", "sizes", "projects"} & set(g.needs)]


def _names(groups: list[CatalogueGroup]) -> str:
    names = [g.name.lower() for g in groups]
    return str(names[0]) if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def structure_question(bp: BusinessBlueprint, style: str = "en") -> str:
    """Ask for the structure the website needs, in one or two linked parts."""
    pending = open_structure(bp)
    varieties = [g for g in pending if "varieties" in g.needs]
    cuts = [g for g in pending if "cuts" in g.needs]
    sizes = [g for g in pending if "sizes" in g.needs and g not in cuts]
    projects = [g for g in pending if "projects" in g.needs]
    tamil = style.startswith("ta")
    if projects:
        # One question: the names and places buyers will look for.
        return (
            "Ippo endha projects sale-la irukku — peru, edam sollunga?" if tamil
            else "Which projects are selling now — their names and where they are?"
        )
    parts: list[str] = []
    if cuts:
        parts.append(
            f"{_names(cuts).capitalize()}-la customers cuts select pannuvaangalaa?" if tamil
            else f"For {_names(cuts)}, do people choose cuts too?"
        )
    if varieties:
        parts.append(
            f"{_names(varieties).capitalize()}-la endha varieties usual-aa vechiruppeenga?" if tamil
            else f"And for {_names(varieties)}, which varieties do you usually keep?" if parts
            else f"You mentioned different {_names(varieties)} varieties. Which ones do you usually keep?"
        )
    if sizes and len(parts) < 2:
        parts.append(
            f"{_names(sizes).capitalize()} endha sizes-la kidaikkum?" if tamil
            else f"What sizes do {_names(sizes)} come in?"
        )
    return " ".join(parts[:2])


def _price_line(group: CatalogueGroup) -> str:
    """The group's own price, or the lowest item price the owner gave ("from 240 per kg")."""
    if group.price:
        return f"{group.price} {group.unit}".strip()
    priced = [i for i in group.items if i.price]
    if not priced:
        return ""

    def amount(item: CatalogueItem) -> float:
        digits = re.sub(r"[^\d.]", "", item.price)
        try:
            return float(digits)
        except ValueError:
            return float("inf")

    low = min(priced, key=amount)
    prefix = "from " if len(priced) > 1 else ""
    price = f"₹{low.price}" if re.fullmatch(r"\d[\d,.]*", low.price) else low.price
    unit = low.unit or group.unit
    # "per kg" reads on its own; a pack size ("250 g") needs the slash.
    if unit and not re.match(r"(per|/|a |an |each)", unit, re.I):
        unit = f"/ {unit}"
    return f"{prefix}{price} {unit}".strip()


def catalogue_lines(bp: BusinessBlueprint) -> list[dict[str, object]]:
    """The structure as the owner reads it in the panel."""
    labels = {"varieties": "varieties", "cuts": "cuts", "sizes": "sizes", "projects": "projects",
              "price": "price", "photo": "photo"}
    out: list[dict[str, object]] = []
    for group in bp.taxonomy.groups:
        out.append({
            "name": group.name,
            "suggested_label": group.label_source == "ai_suggestion",
            "items": [i.name for i in group.items][:12],
            "sold_by": group.sold_by,
            "price": _price_line(group),
            "needs": [labels[n] for n in group.needs],
        })
    return out
