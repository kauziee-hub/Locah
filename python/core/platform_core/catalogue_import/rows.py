"""Turn an imported sheet's rows into catalogue drafts — mapping, cleaning,
validation and duplicate detection. Pure functions, no database.

Every row ends up `ready`, `duplicate` or `error`, with the exact reason in the
owner's words. Nothing here creates or publishes anything.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

FIELDS: tuple[str, ...] = ("name", "description", "category", "price", "duration", "sku", "stock",
                           "location", "kind")
FIELD_LABELS = {
    "name": "Name", "description": "Description", "category": "Category", "price": "Price",
    "duration": "Duration (minutes)", "sku": "SKU / code", "stock": "Stock", "location": "Location",
    "kind": "Kind",
}

# Header words → field. Matched on a normalised header ("Price (₹)" → "price").
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("name", "item", "item name", "items", "product", "product name", "products", "service",
             "service name", "services", "menu item", "dish", "dish name", "title", "offering", "particulars"),
    "description": ("description", "details", "desc", "about", "notes", "item description"),
    "category": ("category", "categories", "section", "menu section", "group", "department", "collection",
                 "course", "menu category"),
    "price": ("price", "rate", "cost", "amount", "mrp", "selling price", "sale price", "price inr", "rs",
              "rupees", "inr"),
    "duration": ("duration", "time", "minutes", "mins", "duration minutes", "duration mins", "length",
                 "service time"),
    "sku": ("sku", "code", "item code", "product code", "sku code", "article", "article no"),
    "stock": ("stock", "quantity", "qty", "opening stock", "in stock", "inventory", "available qty",
              "stock qty"),
    "location": ("location", "branch", "outlet", "store", "shop"),
    "kind": ("kind", "item type", "offering type", "type of item"),
}


def _norm_header(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = re.sub(r"[₹$€£]", " ", text)
    text = re.sub(r"\(.*?\)", " ", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def suggest_mapping(headers: list[str]) -> list[str | None]:
    """One field (or None) per column; each field is used at most once."""
    out: list[str | None] = [None] * len(headers)
    used: set[str] = set()
    normed = [_norm_header(h) for h in headers]
    for exact in (True, False):
        for i, h in enumerate(normed):
            if out[i] is not None or not h:
                continue
            for fld, words in _SYNONYMS.items():
                if fld in used:
                    continue
                hit = h in words if exact else any(w and (h.startswith(w + " ") or h.endswith(" " + w)) for w in words)
                if hit:
                    out[i] = fld
                    used.add(fld)
                    break
    return out


def apply_mapping(rows: list[list[str]], mapping: list[str | None]) -> list[dict[str, str]]:
    out = []
    for row in rows:
        item = {f: "" for f in FIELDS}
        for i, fld in enumerate(mapping):
            if fld and i < len(row) and row[i] and not item[fld]:
                item[fld] = row[i]
        out.append(item)
    return out


# ---------------------------------------------------------------- cleaning

_PRICE = re.compile(r"^(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:/-|rs\.?|inr|only)?$", re.I)


def parse_price(raw: str) -> Decimal | None:
    """'₹1,200' / 'Rs. 99' / '99/-' / '149.50' → Decimal. '' → None. Anything else raises ValueError."""
    text = (raw or "").strip()
    if not text or text in {"-", "—"}:
        return None
    m = _PRICE.match(text.replace(" ", "") if text.count(" ") <= 1 else text)
    if not m:
        raise ValueError(f"“{text}” is not a price")
    try:
        value = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"“{text}” is not a price") from exc
    if value > Decimal("10000000"):
        raise ValueError(f"{text} is too large for a price")
    return value


_DUR_HM = re.compile(r"^(?:(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours))?\s*(?:(\d+)\s*(?:m|min|mins|minute|minutes))?$", re.I)


def parse_duration(raw: str) -> int | None:
    """'45' / '45 min' / '1h 30m' / '1.5 hours' / '1:30' → minutes. '' → None."""
    text = (raw or "").strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d{1,4}", text):
        minutes = int(text)
    elif re.fullmatch(r"\d{1,2}:\d{2}", text):
        h, m = text.split(":")
        minutes = int(h) * 60 + int(m)
    else:
        m2 = _DUR_HM.match(text.replace(" ", ""))
        if not m2 or not (m2.group(1) or m2.group(2)):
            raise ValueError(f"“{raw}” is not a duration — use minutes, like 45")
        minutes = round(float(m2.group(1) or 0) * 60) + int(m2.group(2) or 0)
    if not 1 <= minutes <= 24 * 60:
        raise ValueError(f"{minutes} minutes is not a usable duration")
    return minutes


def parse_stock(raw: str) -> int | None:
    text = (raw or "").strip().replace(",", "")
    if not text:
        return None
    if not re.fullmatch(r"\d+(?:\.0+)?", text):
        raise ValueError(f"“{raw}” is not a whole quantity")
    value = int(float(text))
    if value > 10_000_000:
        raise ValueError(f"{value} is too large for a stock count")
    return value


def norm_name(name: str) -> str:
    """For duplicate checks: case, accents, punctuation and spacing don't make a new item."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^0-9a-z஀-௿ऀ-ॿ]+", " ", text).split())


# ---------------------------------------------------------------- validation

@dataclass
class Existing:
    id: str
    title: str
    status: str
    sku: str | None = None


@dataclass
class RowResult:
    index: int
    values: dict[str, Any]
    status: str  # ready | duplicate | error
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duplicate_of: dict[str, str] | None = None  # an existing item
    repeats_row: int | None = None  # an earlier row in this file

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "values": self.values, "status": self.status, "problems": self.problems,
                "notes": self.notes, "duplicate_of": self.duplicate_of, "repeats_row": self.repeats_row}


def validate_rows(
    rows: list[dict[str, str]],
    *,
    existing: list[Existing],
    kinds: dict[str, str],
    default_kind: str,
    bookable_kinds: frozenset[str],
    location_names: dict[str, str],
    stock_allowed: bool,
) -> list[RowResult]:
    """Clean every row and say what would happen to it.

    `kinds` maps accepted words (kind keys and their labels, normalised) to kind
    keys; `location_names` maps normalised location names to ids.
    """
    by_name = {norm_name(e.title): e for e in existing}
    by_sku = {e.sku.casefold(): e for e in existing if e.sku}
    seen_names: dict[str, int] = {}
    seen_skus: dict[str, int] = {}
    out: list[RowResult] = []
    for i, raw in enumerate(rows):
        problems: list[str] = []
        notes: list[str] = []
        name = " ".join((raw.get("name") or "").split())
        if not name:
            problems.append("Name is missing")
        elif len(name) > 200:
            problems.append("Name is longer than 200 characters")
        values: dict[str, Any] = {"name": name, "description": (raw.get("description") or "").strip()[:5000],
                                  "category": " ".join((raw.get("category") or "").split())[:120]}
        try:
            price = parse_price(raw.get("price", ""))
            values["price"] = str(price) if price is not None else None
        except ValueError as exc:
            problems.append(str(exc))
            values["price"] = None
        kind_word = norm_name(raw.get("kind", ""))
        if kind_word and kind_word not in kinds:
            problems.append(f"“{raw.get('kind')}” is not a kind Locah knows")
        values["kind"] = kinds.get(kind_word, default_kind) if kind_word else default_kind
        try:
            duration = parse_duration(raw.get("duration", ""))
            values["duration"] = duration
            if duration is not None and values["kind"] not in bookable_kinds:
                notes.append("Duration is kept only for services, classes and other bookable kinds")
        except ValueError as exc:
            problems.append(str(exc))
            values["duration"] = None
        sku = (raw.get("sku") or "").strip()
        if len(sku) > 64:
            problems.append("SKU is longer than 64 characters")
        values["sku"] = sku or None
        try:
            values["stock"] = parse_stock(raw.get("stock", ""))
        except ValueError as exc:
            problems.append(str(exc))
            values["stock"] = None
        loc_word = norm_name(raw.get("location", ""))
        values["location_id"] = None
        if loc_word:
            if loc_word in location_names:
                values["location_id"] = location_names[loc_word]
            else:
                problems.append(f"No location called “{raw.get('location')}”")
        if values.get("stock") is not None and not stock_allowed:
            notes.append("Stock is not applied: switch on Stock (and have permission to adjust it) first")
        result = RowResult(i, values, "error" if problems else "ready", problems, notes)
        if not problems:
            key = norm_name(name)
            if key in seen_names:
                result.status, result.repeats_row = "duplicate", seen_names[key]
            elif key in by_name:
                e = by_name[key]
                result.status = "duplicate"
                result.duplicate_of = {"id": e.id, "title": e.title, "status": e.status}
            elif sku and sku.casefold() in by_sku:
                e = by_sku[sku.casefold()]
                result.status = "duplicate"
                result.duplicate_of = {"id": e.id, "title": e.title, "status": e.status}
            elif sku and sku.casefold() in seen_skus:
                result.status, result.repeats_row = "error", None
                result.problems.append(f"SKU {sku} is already used by row {seen_skus[sku.casefold()] + 2}")
            seen_names.setdefault(key, i)
            if sku:
                seen_skus.setdefault(sku.casefold(), i)
        out.append(result)
    return out
