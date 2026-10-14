"""The owner's whole range, captured — not three words in a sentence.

"We sell podis, pickles and sweets" names a shop; it is not a menu. A site
built from it can only show three category tiles. For a business whose
website IS its catalogue (a kitchen's dishes, a salon's services, a shop's
products, a gym's plans, a homestay's rooms), Locah asks for the real list —
a photo or PDF of the menu card or price list (read by documents.py), or the
items typed out with their prices — and keeps every line.

This module is the deterministic half of that, so it works with the model
down and never guesses:

* ``ask`` — the question, in this trade's own words ("Send me your menu…",
  "…your service list with prices and how long each takes");
* ``read_priced_list`` — reads a typed list ("Idli 30, Dosa 50", one dish per
  line, "Starters: Paneer 65 180", "Haircut 300 (30 min)", "Curry cut
  240/kg") into groups and priced items. Numbers are the owner's own, read
  where they wrote them;
* ``read_traits`` — what a diner or customer looks for, only as the owner said
  it: "all veg", "chicken and fish are non-veg", "bestsellers are …",
  "… is spicy"; a dish named with meat or fish is non-veg by its own name;
* ``completeness`` — how much of the range is known, for the planner.

Item traits live on the Blueprint's CatalogueItem (diet, spice, tag) and
travel to the website's catalogue section, where they become diet marks,
chillies and "Bestseller" tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from platform_core.interview.models import BusinessBlueprint, CatalogueGroup, CatalogueItem

# Trades whose website is its catalogue, by the playbook's offer kind.
CATALOGUE_KINDS = frozenset({
    "menu_item", "product", "weighed_product", "service", "package", "plan", "class", "room_type",
})
FOOD_KINDS = frozenset({"menu_item"})

# What to ask for, in the trade's words: the document they already have, and
# how to type it if they would rather.
ASK: dict[str, dict[str, str]] = {
    "menu_item": {
        "en": "Can you send me your full menu? A photo of the menu card or a PDF is perfect — or just "
              "type the dishes with prices, like “Idli 40, Masala dosa 70”. I'll put every dish on your "
              "site with its price.",
        "ta_en": "Unga full menu anuppa mudiyumaa? Menu card photo illa PDF podhum — illa dishes-a "
                 "price-oda type pannunga, “Idli 40, Masala dosa 70” maadhiri. Ella dish-um price-oda "
                 "site-la varum.",
        "ta": "உங்க முழு மெனுவை அனுப்ப முடியுமா? மெனு கார்டு படம் அல்லது PDF போதும் — இல்லன்னா "
              "உணவுகளை விலையோட டைப் பண்ணுங்க, “இட்லி 40, மசாலா தோசை 70” மாதிரி.",
    },
    "product": {
        "en": "Can you share your price list? A photo, PDF or spreadsheet works — or just type each "
              "one with its price, separated by commas. Every one goes on your site.",
        "ta_en": "Unga price list share pannunga — photo, PDF illa Excel podhum. Illa ovvonnaiyum "
                 "price-oda type pannunga, comma pottu.",
        "ta": "உங்க விலைப்பட்டியலை அனுப்புங்க — படம், PDF அல்லது Excel போதும். இல்லன்னா பொருட்களை "
              "விலையோட டைப் பண்ணுங்க.",
    },
    "weighed_product": {
        "en": "What are your prices for each — like “Chicken curry cut 240/kg, Boneless 380/kg”? A "
              "photo of your rate board works too.",
        "ta_en": "Ovvonnukkum enna rate — “Chicken curry cut 240/kg, Boneless 380/kg” maadhiri? Rate "
                 "board photo-vum podhum.",
        "ta": "ஒவ்வொன்றுக்கும் என்ன விலை — “சிக்கன் கறி கட் 240/கிலோ” மாதிரி? விலைப் பலகை படமும் போதும்.",
    },
    "service": {
        "en": "Can you send me your service list with prices? A photo of your rate card works — or "
              "type each one with its price and how long it takes, like “Haircut 300 (30 min)”.",
        "ta_en": "Unga services list price-oda anuppunga — rate card photo podhum. Illa ovvonnaiyum "
                 "price, evlo neram-nu type pannunga, “Haircut 300 (30 min)” maadhiri.",
        "ta": "உங்க சேவைகளை விலையோட அனுப்புங்க — ரேட் கார்டு படம் போதும். இல்லன்னா “ஹேர்கட் 300 "
              "(30 நிமிடம்)” மாதிரி டைப் பண்ணுங்க.",
    },
    "package": {
        "en": "Which packages do you offer, and at what price — like “Bridal makeup 15000, Party "
              "makeup 4000”? A photo of your price list works too.",
        "ta_en": "Enna packages, enna price — “Bridal makeup 15000, Party makeup 4000” maadhiri? "
                 "Price list photo-vum podhum.",
        "ta": "என்ன பேக்கேஜ்கள், என்ன விலை? விலைப்பட்டியல் படமும் போதும்.",
    },
    "plan": {
        "en": "Which plans do you have and what does each cost — like “Monthly 2500, Quarterly 6500, "
              "Yearly 22000”?",
        "ta_en": "Enna plans, evlo — “Monthly 2500, Quarterly 6500, Yearly 22000” maadhiri?",
        "ta": "என்ன பிளான்கள், ஒவ்வொன்றும் எவ்வளவு — “மாதம் 2500, வருடம் 22000” மாதிரி?",
    },
    "class": {
        "en": "Which classes do you run, and the fee for each — like “Yoga 1500/month, Zumba "
              "1200/month”? A photo of your timetable works too.",
        "ta_en": "Enna classes, fees evlo — “Yoga 1500/month” maadhiri? Timetable photo-vum podhum.",
        "ta": "என்ன வகுப்புகள், கட்டணம் எவ்வளவு? நேர அட்டவணை படமும் போதும்.",
    },
    "room_type": {
        "en": "Which rooms do you have, and the rate for each — like “Deluxe room 2500/night, Family "
              "suite 4200/night”?",
        "ta_en": "Enna rooms, rate evlo — “Deluxe room 2500/night” maadhiri?",
        "ta": "என்ன அறைகள், ஒவ்வொன்றின் கட்டணம் — “டீலக்ஸ் அறை 2500/இரவு” மாதிரி?",
    },
}

# After the list: what a visitor of this trade looks for that a list does not say.
TRAITS_ASK: dict[str, dict[str, str]] = {
    "menu_item": {
        "en": "Which 2–3 dishes sell the most? I'll feature them. And is everything vegetarian, or "
              "which ones are non-veg?",
        "ta_en": "Edhu 2–3 dishes adhigama sell aagudhu? Adha feature pannuren. Ellaam veg-aa, illa "
                 "edhu non-veg?",
        "ta": "எந்த 2–3 உணவுகள் அதிகம் விற்கும்? அவற்றை முன்னிறுத்துவேன். எல்லாம் சைவமா, எது அசைவம்?",
    },
    "service": {
        "en": "Which services do people book most? I'll put them first.",
        "ta_en": "Customers adhigama edhai book pannuvaanga? Adha first-a podren.",
        "ta": "வாடிக்கையாளர்கள் அதிகம் எதை புக் பண்ணுவாங்க? அதை முதல்ல போடறேன்.",
    },
    "_": {
        "en": "Which ones sell the most? I'll feature them on your site.",
        "ta_en": "Edhu adhigama sell aagudhu? Adha site-la feature pannuren.",
        "ta": "எது அதிகம் விற்கும்? அதை முன்னிறுத்துவேன்.",
    },
}


def offer_kind(bp: BusinessBlueprint) -> str:
    from platform_core.interview.playbooks import playbook_for

    return str(playbook_for(bp).offer_kind)


def catalogue_led(bp: BusinessBlueprint) -> bool:
    return offer_kind(bp) in CATALOGUE_KINDS


def ask(bp: BusinessBlueprint, lang: str) -> str:
    words = ASK.get(offer_kind(bp), ASK["product"])
    return words.get(lang) or words["en"]


def traits_ask(bp: BusinessBlueprint, lang: str) -> str:
    kind = offer_kind(bp)
    words = TRAITS_ASK.get(kind, TRAITS_ASK["_"])
    if kind in FOOD_KINDS and all(item.diet for item in _items(bp)):
        words = TRAITS_ASK["_"]  # diet is already known: only the favourites
    return words.get(lang) or words["en"]


def _items(bp: BusinessBlueprint) -> list[CatalogueItem]:
    return [item for group in bp.taxonomy.groups for item in group.items]


def completeness(bp: BusinessBlueprint) -> str:
    """unknown | partial | sufficient — how much of the real range is known."""
    if any(d.status in {"reading", "ready", "applied"} for d in bp.documents):
        return "sufficient"  # the owner sent the document itself
    items = _items(bp)
    if not items:
        return "unknown"
    kind = offer_kind(bp)
    enough = 3 if kind in {"plan", "class", "room_type", "package"} else 5
    priced = sum(1 for item in items if item.price)
    prices_hidden = (bp.owner_choices.price_visibility or "show") in {"none", "on_request"}
    if len(items) >= enough and (prices_hidden or priced >= 0.6 * len(items)):
        return "sufficient"
    return "partial"


def traits_known(bp: BusinessBlueprint) -> bool:
    items = _items(bp)
    if not items:
        return False
    tagged = any(item.tag for item in items)
    if offer_kind(bp) in FOOD_KINDS:
        return tagged and all(item.diet for item in items)
    return tagged


# ------------------------------------------------------------------ reading

_PHONE = re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b")
_TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\b|\b\d{1,2}\s*(?:to|-)\s*\d{1,2}\s*(?:am|pm)\b",
                   re.I)
_YEAR = re.compile(r"\b(?:since|from|in|est\.?|established)\s+(?:19|20)\d\d\b", re.I)
_DURATION = re.compile(r"\(?\s*(\d{1,3})\s*(?:-|to|–)?\s*(\d{1,3})?\s*(minutes|mins|min|hours|hour|hrs|hr)\b\s*\)?",
                       re.I)
# A price at the end of an entry, with what it is for: "240/kg", "₹ 1,200",
# "Rs. 50 per plate", "2500 per month", "650/-".
_PRICE_TAIL = re.compile(
    r"(?:[-–—:=]|\.{2,}|…)?\s*(?:₹|rs\.?|inr)?\s*(?P<amount>\d{1,3}(?:,\d{2,3})+|\d{1,6})(?:\.\d{1,2})?\s*(?:/-)?"
    r"\s*(?P<unit>(?:/|per\s+|a\s+|for\s+)\s*(?:\d+\s*)?(?:kg|kilo|g|gm|grams?|piece|pc|pcs|plate|litre|ltr|l|ml|"
    r"month|monthly|year|yearly|night|day|session|class|person|head|box|pack|jar|dozen|hour|hr)\b\.?)?\s*$",
    re.I)
_HEADING = re.compile(r"^(?P<head>[A-Za-z][A-Za-z &'/-]{1,30}?)\s*:\s*(?P<rest>.*)$")
_BULLET = re.compile(r"^\s*(?:[-*•·▪►]|\d{1,2}[.)])\s+")
_SIZE = re.compile(r"^(?:half|full|quarter|small|medium|large|regular|mini|family|single|double|"
                   r"\d+\s*(?:g|gm|kg|ml|l|ltr|pcs?|pieces?))$", re.I)
_NOT_A_THING = re.compile(
    r"\b(?:open|closed|call|whatsapp|deliver\w*|km|kms|minutes? away|years?|since|members?|customers?|"
    r"rating|reviews?|followers|branches|staff|people|times?|days? a week|percent|%|off)\b", re.I)

_DIET_MARK = re.compile(
    r"\(\s*(?P<m>veg|v|nv|non[- ]?veg|egg|vegan|jain)\s*\)|"
    r"(?:^|\s)(?P<m2>non[- ]?veg|nonveg|vegan|jain)(?=\s*$)", re.I)
_MEAT = re.compile(
    r"\b(?:chicken|mutton|lamb|goat|beef|pork|fish|prawns?|shrimps?|crab|squid|lobster|seer|pomfret|"
    r"sardine|mackerel|keema|kheema|kebab|kabab|tikka|seafood|nattu kozhi|kozhi|meen|eral|nandu|"
    r"liver|brain|bone|boneless|curry cut|wings?|drumsticks?|meat)\b", re.I)
_EGG = re.compile(r"\b(?:egg|eggs|omelette|omelet|anda|muttai)\b", re.I)
_SPICY_MARK = re.compile(r"(?:🌶+|\(\s*(?:spicy|hot|extra hot)\s*\))", re.I)


@dataclass
class ReadItem:
    name: str
    price: str = ""
    unit: str = ""
    diet: str = ""
    spice: str = ""


@dataclass
class ReadGroup:
    name: str
    items: list[ReadItem] = field(default_factory=list)


def _clean_name(text: str) -> str:
    text = _BULLET.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .,;:-–—=*•")
    return text[:1].upper() + text[1:] if text else ""


def _entry(raw: str) -> ReadItem | None:
    """One "name … price" entry, or None when it is not one."""
    text = " ".join(raw.split())
    if not text or len(text) > 90:
        return None
    diet = spice = ""
    m = _DIET_MARK.search(text)
    if m:
        mark = (m.group("m") or m.group("m2") or "").lower().replace(" ", "").replace("-", "")
        diet = {"v": "veg", "veg": "veg", "jain": "veg", "nv": "non_veg", "nonveg": "non_veg",
                "egg": "egg", "vegan": "vegan"}.get(mark, "")
        text = (text[: m.start()] + text[m.end():]).strip()
    if _SPICY_MARK.search(text):
        spice = "hot"
        text = _SPICY_MARK.sub("", text).strip()
    duration = ""
    d = _DURATION.search(text)
    if d and d.start() > 0:
        low, high, word = d.group(1), d.group(2), d.group(3).lower()
        unit = "min" if word.startswith("min") else "hr"
        duration = f"{low}–{high} {unit}" if high else f"{low} {unit}"
        text = (text[: d.start()] + text[d.end():]).strip()
    p = _PRICE_TAIL.search(text)
    if not p:
        return None
    name = _clean_name(text[: p.start()])
    if not name or len(name) < 2 or not re.search(r"[A-Za-z஀-௿ऀ-ॿ]{2}", name):
        return None
    if len(name.split()) > 7 or _NOT_A_THING.search(name):
        return None
    amount = p.group("amount").replace(",", "")
    if not amount.isdigit() or int(amount) == 0:
        return None
    unit = (p.group("unit") or "").strip(" .")
    unit = re.sub(r"^(?:per|a|for)\s+", "", unit, flags=re.I).strip("/ ")
    unit_text = f"per {unit}" if unit and not re.match(r"\d", unit) else unit
    if duration:
        unit_text = duration if not unit_text else f"{unit_text} · {duration}"
    if not diet and _MEAT.search(name):
        diet = "non_veg"  # a dish named for its meat or fish says so itself
    elif not diet and _EGG.search(name):
        diet = "egg"
    return ReadItem(name=name[:80], price=p.group("amount").replace(" ", "")[:40], unit=unit_text[:40],
                    diet=diet, spice=spice)


def read_priced_list(text: str) -> list[ReadGroup]:
    """A typed menu or price list as groups of priced items.

    Reads one entry per line, or comma/semicolon-separated entries; a line
    that ends in ":" (or "Starters: …") starts a group. "Mutton biryani half
    220, full 400" keeps both prices on one item. Anything that is not
    "name then price" — hours, phone numbers, years — is left alone.
    """
    flat = _PHONE.sub(" ", text or "")
    flat = _TIME.sub(" ", flat)
    flat = _YEAR.sub(" ", flat)
    groups: list[ReadGroup] = []
    current = ReadGroup(name="")
    lines = [ln for ln in re.split(r"[\r\n]+", flat) if ln.strip()]
    for line in lines:
        line = line.strip()
        heading = _HEADING.match(line)
        if heading and not _PRICE_TAIL.search(heading.group("head")):
            head = _clean_name(heading.group("head"))
            if head and len(head.split()) <= 4 and not _NOT_A_THING.search(head):
                if current.items or current.name:
                    groups.append(current)
                current = ReadGroup(name=head)
                line = heading.group("rest")
        if re.fullmatch(r"[A-Za-z][A-Za-z &'/-]{1,30}", line.strip()) and len(lines) > 1:
            # A bare line between priced lines is a heading ("Starters").
            if current.items or current.name:
                groups.append(current)
            current = ReadGroup(name=_clean_name(line))
            continue
        # Sentences around a list ("Our menu is: …. We also do parcels") are
        # split off; the list itself is comma, semicolon or " | " separated.
        for chunk in re.split(r"\s*(?:[,;|]|\s{2,}|\.\s+(?=[A-Z]))\s*", line):
            inline = _HEADING.match(chunk)
            if inline and not _PRICE_TAIL.search(inline.group("head")):
                # "… 140. Pickles: Lemon pickle 150": a new chapter mid-line.
                head = _clean_name(inline.group("head"))
                if head and len(head.split()) <= 4 and not _NOT_A_THING.search(head):
                    if current.items or current.name:
                        groups.append(current)
                    current = ReadGroup(name=head)
                    chunk = inline.group("rest")
            entry = _entry(chunk)
            if entry is None:
                continue
            size = re.match(r"^(?P<base>.+?)\s+(?P<size>half|full|quarter|small|medium|large|regular|"
                            r"\d+\s*(?:g|gm|kg|ml|l|ltr|pcs?))$", entry.name, re.I)
            if _SIZE.match(entry.name) and current.items:
                # "full 400" after "Mutton biryani half 220": the same dish, another size.
                last = current.items[-1]
                last.price = f"{last.price} / {entry.price}"[:40]
                last.unit = f"{last.unit or ''} / {entry.name.lower()}".strip(" /")[:40]
                continue
            if size:
                entry.name = _clean_name(size.group("base"))
                entry.unit = size.group("size").lower() if not entry.unit else entry.unit
            current.items.append(entry)
    if current.items or current.name:
        groups.append(current)
    return [g for g in groups if g.items][:12]


def priced_count(groups: list[ReadGroup]) -> int:
    return sum(len(g.items) for g in groups)


_STEM = re.compile(r"(?:es|s)$", re.I)


def _stem(word: str) -> str:
    return _STEM.sub("", word.casefold())


def _home_for(bp: BusinessBlueprint, item: str) -> CatalogueGroup | None:
    """The owner's group an unheaded item belongs to: "Garlic pickle" → Pickles."""
    words = {_stem(w) for w in re.findall(r"[A-Za-z]{3,}", item)}
    for group in bp.taxonomy.groups:
        group_words = {_stem(w) for w in re.findall(r"[A-Za-z]{3,}", group.name)}
        if group_words and group_words & words:
            return group
        if any(i.name.casefold() == item.casefold() for i in group.items):
            return group
    return None


def _default_group(bp: BusinessBlueprint) -> str:
    return {"menu_item": "Menu", "service": "Services", "plan": "Plans", "class": "Classes",
            "room_type": "Rooms", "package": "Packages"}.get(offer_kind(bp), "Products")


def merge_priced(bp: BusinessBlueprint, groups: list[ReadGroup]) -> int:
    """Fold a read price list into the catalogue. Returns how many items were added or priced."""
    from platform_core.interview.taxonomy import refresh_needs

    changed = 0
    for read in groups:
        for entry in read.items:
            target: CatalogueGroup | None = None
            if read.name:
                target = next((g for g in bp.taxonomy.groups if _stem(g.name) == _stem(read.name)), None)
                if target is None and len(bp.taxonomy.groups) < 12:
                    target = CatalogueGroup(name=read.name[:80])
                    bp.taxonomy.groups.append(target)
            else:
                target = _home_for(bp, entry.name)
                if target is None:
                    name = _default_group(bp)
                    target = next((g for g in bp.taxonomy.groups if g.name == name), None)
                    if target is None and len(bp.taxonomy.groups) < 12:
                        target = CatalogueGroup(name=name, label_source="ai_suggestion")
                        bp.taxonomy.groups.append(target)
            if target is None:
                continue
            if _stem(entry.name) == _stem(target.name) or entry.name.casefold() == target.name.casefold():
                # "Custom cakes 650 per kg": the price of the whole group.
                if entry.price and re.sub(r"\D", "", target.price) != re.sub(r"\D", "", entry.price):
                    target.price, target.unit = entry.price, entry.unit or target.unit
                    target.needs = [n for n in target.needs if n != "price"]
                    changed += 1
                continue
            existing = next((i for i in target.items if i.name.casefold() == entry.name.casefold()), None)
            if existing is None:
                # "Chicken curry cut" under Chicken is its "Curry cut".
                head = re.match(r"^(\w+)\s+(.+)$", entry.name)
                if head and _stem(head.group(1)) in {_stem(w) for w in re.findall(r"[A-Za-z]{3,}", target.name)}:
                    rest = head.group(2).casefold()
                    existing = next((i for i in target.items if i.name.casefold() == rest), None)
            if existing is None:
                if len(target.items) >= 24:
                    continue
                target.items.append(CatalogueItem(name=entry.name, price=entry.price, unit=entry.unit,
                                                  diet=entry.diet, spice=entry.spice))
                changed += 1
            elif existing.source != "owner_edited":
                if entry.price and entry.price != existing.price:
                    existing.price, existing.unit = entry.price, entry.unit or existing.unit
                    changed += 1
                existing.diet = existing.diet or entry.diet
                existing.spice = existing.spice or entry.spice
            # A group the owner named but had not listed is now listed.
            target.needs = [n for n in target.needs if n != "varieties"]
    if changed:
        refresh_needs(bp)
    return changed


# ------------------------------------------------------------------- traits

_ALL_VEG = re.compile(r"\b(?:(?:all|everything|fully|completely|100%?|pure|only)\s+(?:is\s+|are\s+)?"
                      r"(?:veg|vegetarian)|pure[- ]veg|veg only|only veg|no (?:meat|non[- ]?veg))\b", re.I)
_REST_VEG = re.compile(r"\b(?:rest|others?|everything else|all (?:the )?others?)\s+(?:are|is)\s+(?:all\s+)?"
                       r"(?:veg|vegetarian)\b", re.I)
_NONVEG_LIST = re.compile(r"(?:non[- ]?veg(?:etarian)?\s*(?:ones?|items?|dishes?)?\s*(?:are|is|:|-)\s*"
                          r"(?P<a>[^.?!]+))|(?:(?P<b>[^.?!]+?)\s+(?:are|is)\s+(?:the\s+)?non[- ]?veg)", re.I)
_BEST = re.compile(
    r"(?:(?:best ?sellers?|bestselling|most popular|popular ones|favou?rites?|people(?:'s)? favou?rites?|"
    r"sells? (?:the )?most|top sellers?|signature(?: dish(?:es)?)?|speciality|specialty|special(?:ities|s)?)"
    r"\s*(?:are|is|:|-|would be)?\s*(?P<a>[^.?!]+))|"
    r"(?:(?P<b>[^.?!]+?)\s+(?:are|is)\s+(?:our\s+|the\s+)?(?:best ?sellers?|most popular|favou?rites?|"
    r"signature|speciality|specialty)|(?P<c>[^.?!]+?)\s+sells? (?:the )?most)",
    re.I)
_SPICY_LIST = re.compile(r"(?:(?:spicy|hot)\s*(?:ones?|dishes?)?\s*(?:are|is|:|-)\s*(?P<a>[^.?!]+))|"
                         r"(?:(?P<b>[^.?!]+?)\s+(?:are|is)\s+(?:very\s+|quite\s+|bit\s+)?(?:spicy|hot))", re.I)


def _named(bp: BusinessBlueprint, text: str) -> list[CatalogueItem]:
    """Items of the catalogue named in a phrase, by their own names."""
    phrase = text.casefold()
    found: list[CatalogueItem] = []
    for item in _items(bp):
        name = item.name.casefold()
        if name and (name in phrase or (len(name.split()) > 1 and all(w in phrase for w in name.split()))):
            found.append(item)
    return found


def read_traits(bp: BusinessBlueprint, text: str) -> int:
    """Diet, spice and favourites, from what the owner said. Returns how many items changed."""
    items = _items(bp)
    if not items or not text.strip():
        return 0
    changed = 0
    food = offer_kind(bp) in FOOD_KINDS
    if food:
        nonveg: list[CatalogueItem] = []
        for m in _NONVEG_LIST.finditer(text):
            nonveg += _named(bp, m.group("a") or m.group("b") or "")
        for item in nonveg:
            if item.diet != "non_veg":
                item.diet, changed = "non_veg", changed + 1
        if _ALL_VEG.search(text) and not nonveg:
            for item in items:
                if not item.diet:
                    item.diet, changed = "veg", changed + 1
        elif _REST_VEG.search(text) or (nonveg and re.search(r"\b(?:only|just)\b", text, re.I)):
            for item in items:
                if not item.diet and item not in nonveg:
                    item.diet, changed = "veg", changed + 1
        for m in _SPICY_LIST.finditer(text):
            for item in _named(bp, m.group("a") or m.group("b") or ""):
                if item.spice != "hot":
                    item.spice, changed = "hot", changed + 1
    for m in _BEST.finditer(text):
        phrase = m.group("a") or m.group("b") or m.group("c") or ""
        label = "Signature" if re.search(r"signature|special", m.group(0), re.I) else "Bestseller"
        for item in _named(bp, phrase)[:4]:
            if not item.tag:
                item.tag, changed = label, changed + 1
    return changed


def capture(bp: BusinessBlueprint, text: str, answering: tuple[str, ...] = ()) -> int:
    """Read a turn for the catalogue: priced lines, then traits. Returns what changed."""
    groups = read_priced_list(text)
    count = priced_count(groups)
    changed = 0
    # A list in passing needs two priced lines to be a list; an answer to
    # "send me your menu" needs only one.
    if count >= 2 or (count == 1 and "offerings.catalogue" in answering):
        changed += merge_priced(bp, groups)
        _drop_raw_lines(bp, groups)
        if changed:
            _offer_answered_by_list(bp, text)
    changed += read_traits(bp, text)
    return changed


def _drop_raw_lines(bp: BusinessBlueprint, read: list[ReadGroup]) -> None:
    """A plainer reading of the same message may have kept whole lines as
    names ("Idli 40", "Poori 65 Meals: South Indian meals 150"). Once the
    list is read properly, those are not dishes."""
    raw = {f"{e.name} {e.price}".casefold() for g in read for e in g.items}
    heads = {g.name.casefold() for g in read if g.name}
    for group in bp.taxonomy.groups:
        group.items = [
            item for item in group.items
            if item.name.casefold() not in raw
            and not (":" in item.name and any(f"{h}:" in item.name.casefold() for h in heads))
        ]
    bp.taxonomy.groups = [g for g in bp.taxonomy.groups if g.items or g.name.casefold() in heads or not any(
        g.name.casefold() == f"{e.name} {e.price}".casefold() for r in read for e in r.items)]


def _offer_answered_by_list(bp: BusinessBlueprint, text: str) -> None:
    """A typed menu also says what the business sells: what was asked as
    "what do you offer?" is answered by it, in the owner's own groups."""
    from platform_core.interview.models import Fact, TargetState

    names = [g.name for g in bp.taxonomy.groups if g.items][:8]
    if not names:
        return
    said = ", ".join(names)
    state = bp.discovery.setdefault("offerings.main", TargetState())
    if state.status not in {"answered", "declined"}:
        state.status, state.summary, state.quote = "answered", said[:240], text.strip()[:600]
    if "offerings" not in bp.known_facts and "offerings" not in bp.unconfirmed_facts:
        bp.unconfirmed_facts["offerings"] = Fact(value=said[:4000], source="USER_STATEMENT",
                                                 evidence=text.strip()[:4000])
    catalogue = bp.discovery.setdefault("offerings.catalogue", TargetState())
    if catalogue.status not in {"answered", "declined"}:
        catalogue.status, catalogue.quote = "answered", text.strip()[:600]


def item_traits(item: CatalogueItem) -> dict[str, str]:
    """diet / spice / tag for the website: the item's own, else what its
    document line printed ("veg", "spicy")."""
    out: dict[str, str] = {}
    attrs = (item.attributes or "").casefold()
    diet = item.diet or (
        "non_veg" if re.search(r"non[- ]?veg|\bnv\b", attrs) else "vegan" if "vegan" in attrs
        else "egg" if re.search(r"\begg\b", attrs) else "veg" if re.search(r"\bveg\b|vegetarian", attrs) else "")
    spice = item.spice or ("hot" if re.search(r"spicy|\bhot\b", attrs) else "mild" if "mild" in attrs else "")
    if diet:
        out["diet"] = diet
    if spice:
        out["spice"] = spice
    if item.tag:
        out["tag"] = item.tag[:24]
    return out
