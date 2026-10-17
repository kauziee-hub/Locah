"""The founder's quality bar, as data the critic and the gate can use.

`docs/visual-references/BRIEF.md` describes fifteen reference sites (the
professional class a Locah site must belong to) and what must improve. This
module reads it once:

- ``REFERENCES`` — ``{ref_id: (title, takeaway)}``, e.g. ``"05"`` → ("Fine Dining
  / Warm Editorial", "Use a premium serif/sans pairing, …").
- ``MUST_IMPROVE`` / ``CRITIQUE_FOR`` / ``EXPECTED_STANDARD`` — the brief's lists,
  one line each, handed to the vision critic as the bar.
- ``CATEGORY_REFERENCES`` — which references a category is judged against.
- ``images(ref_ids)`` — the reference screenshots that exist on disk
  (``docs/visual-references/ref_XX.png``). None are checked in today; the critic
  then judges from the written takeaways alone.

The references are a quality bar, never templates to copy.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_DIR = Path(os.getenv("LOCAH_VISUAL_REFERENCES_DIR") or REPO_ROOT / "docs" / "visual-references")
BRIEF_PATH = REFERENCE_DIR / "BRIEF.md"

# Which references a category is held to. Keys are the words a category may
# carry; `refs_for` matches them inside longer category names too
# ("restaurant_delivery", "Meat / butcher shop").
CATEGORY_REFERENCES: dict[str, tuple[str, ...]] = {
    "restaurant": ("05", "06", "07"),
    "gym": ("08",),
    "salon": ("11", "12"),
    "beauty": ("11", "12"),
    "clinic": ("13", "14"),
    "medical": ("13", "14"),
    "consultant": ("09",),
    "coaching": ("09",),
    "professional": ("09",),
    "architecture": ("01", "02", "03", "04"),
    "interiors": ("01", "02", "03", "04"),
    "furniture": ("01", "02", "03", "04"),
    "hotel": ("15",),
    "ngo": ("10",),
    "bakery": ("04", "05", "07"),
    "meat": ("04", "05", "07"),
    "retail": ("04", "05", "07"),
}

# Other words for the same families, so a category named in the owner's terms
# still finds its references. Checked after the keys above.
_ALIASES: dict[str, str] = {
    "cafe": "restaurant", "café": "restaurant", "dining": "restaurant", "food": "restaurant",
    "kitchen": "restaurant", "bistro": "restaurant",
    "fitness": "gym", "studio_fitness": "gym", "yoga": "gym", "crossfit": "gym",
    "spa": "salon", "nail": "salon", "hair": "salon", "barber": "salon",
    "dental": "clinic", "dentist": "clinic", "doctor": "clinic", "health": "clinic",
    "hospital": "clinic", "physio": "clinic",
    "consulting": "consultant", "coach": "coaching", "advisor": "consultant",
    "accountant": "professional", "lawyer": "professional", "legal": "professional",
    "agency": "professional", "services": "professional",
    "architect": "architecture", "interior": "interiors", "design_studio": "architecture",
    "hospitality": "hotel", "resort": "hotel", "stay": "hotel", "homestay": "hotel",
    "nonprofit": "ngo", "non_profit": "ngo", "charity": "ngo", "foundation": "ngo",
    "trust": "ngo",
    "bake": "bakery", "patisserie": "bakery", "cake": "bakery",
    "butcher": "meat", "seafood": "meat", "fish": "meat",
    "shop": "retail", "store": "retail", "boutique": "retail", "grocery": "retail",
}

# The family a category belongs to (for owner requests and wording), keyed by
# the CATEGORY_REFERENCES word it matched.
_FAMILY: dict[str, str] = {
    "restaurant": "restaurant", "gym": "gym", "salon": "salon", "beauty": "salon",
    "clinic": "clinic", "medical": "clinic", "consultant": "consultant",
    "coaching": "consultant", "professional": "consultant", "architecture": "architecture",
    "interiors": "architecture", "furniture": "architecture", "hotel": "hotel", "ngo": "ngo",
    "bakery": "bakery", "meat": "meat", "retail": "retail",
}

# A category the map does not know is still judged — against the editorial
# and service-brand references, the two most general of the pack.
DEFAULT_REFERENCES: tuple[str, ...] = ("01", "09")

_REF_HEADING = re.compile(r"^###\s+Reference\s+(\d{1,2})\s*[-–—]\s*(.+?)\s*$")
_NUMBERED = re.compile(r"^###\s+\d+\.\s*(.+?)\s*$")


def _words(category: str) -> str:
    return re.sub(r"[^a-z0-9é]+", "_", category.strip().casefold()).strip("_")


def _matched_key(category: str) -> str | None:
    """The CATEGORY_REFERENCES key a category belongs to, or None."""
    norm = _words(category)
    if not norm:
        return None
    if norm in CATEGORY_REFERENCES:
        return norm
    tokens = {t for t in norm.split("_") if t}
    tokens |= {t[:-1] for t in tokens if len(t) > 3 and t.endswith("s")}  # "meats", "hotels"
    for key in CATEGORY_REFERENCES:  # a whole word of a longer name
        if key in tokens:
            return key
    for alias, key in _ALIASES.items():
        if alias in tokens or ("_" in alias and alias in norm):
            return key
    # A long key inside a compound word ("finedining_restaurantgroup"); short
    # ones ("ngo", "gym") only as whole words, or "mango" would be an NGO.
    for key in CATEGORY_REFERENCES:
        if len(key) >= 5 and key in norm:
            return key
    return None


def category_family(category: str) -> str:
    """restaurant | bakery | meat | retail | gym | salon | clinic | consultant |
    architecture | hotel | ngo | other."""
    key = _matched_key(category)
    return _FAMILY.get(key, "other") if key else "other"


def refs_for(category: str) -> tuple[str, ...]:
    """The reference ids a category is judged against (never empty)."""
    key = _matched_key(category)
    return CATEGORY_REFERENCES[key] if key else DEFAULT_REFERENCES


def parse_references(text: str) -> dict[str, tuple[str, str]]:
    """``### Reference 05 - Fine Dining / Warm Editorial`` followed by its
    takeaway paragraph → ``{"05": ("Fine Dining / Warm Editorial", "Use …")}``."""
    out: dict[str, tuple[str, str]] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _REF_HEADING.match(line.strip())
        if not m:
            continue
        ref_id, title = f"{int(m.group(1)):02d}", m.group(2).strip()
        body: list[str] = []
        for nxt in lines[i + 1:]:
            s = nxt.strip()
            if s.startswith("#"):
                break
            if not s:
                if body:
                    break
                continue
            if s.startswith("!["):  # the image line, not the takeaway
                continue
            body.append(s)
        out[ref_id] = (title, " ".join(body).strip())
    return out


def _section(text: str, heading: str) -> list[str]:
    """Lines under ``## heading`` up to the next ``## `` heading."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().casefold() == f"## {heading}".casefold()), None)
    if start is None:
        return []
    out: list[str] = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        out.append(ln)
    return out


def parse_must_improve(text: str) -> list[str]:
    """Each numbered point under "What must improve", condensed to one line:
    "Title — paragraph; bullet; bullet"."""
    items: list[str] = []
    title: str | None = None
    parts: list[str] = []

    def flush() -> None:
        if not title:
            return
        body = ""
        for part in parts:  # "Use:" introduces its bullets; the rest are a list
            body += part if not body else (" " if body.endswith(":") else "; ") + part
        items.append(title + (" — " + body if body else ""))

    for ln in _section(text, "What must improve"):
        s = ln.strip()
        m = _NUMBERED.match(s)
        if m:
            flush()
            title, parts = m.group(1), []
            continue
        if not s or title is None:
            continue
        if s.startswith("**") and s.endswith("**"):
            s = s.strip("*")
        parts.append(s[2:].strip() if s.startswith("- ") else s)
    flush()
    return items


def parse_critique_for(text: str) -> list[str]:
    """The bullets after "Critique specifically for:"."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().casefold().startswith(
        "critique specifically for")), None)
    if start is None:
        return []
    out: list[str] = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s.startswith("#") or (out and s and not s.startswith("- ")):
            break
    return out


def parse_expected_standard(text: str) -> dict[str, str]:
    """The two quotes under "Expected standard": what a viewer should and
    should not think."""
    quotes = [ln.strip().lstrip(">").strip().strip("“”\"")
              for ln in _section(text, "Expected standard") if ln.strip().startswith(">")]
    quotes = [q for q in quotes if q]
    return {"should_think": quotes[0] if quotes else "",
            "must_not_think": quotes[1] if len(quotes) > 1 else ""}


@lru_cache(maxsize=4)
def _brief_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def brief_text(path: Path | None = None) -> str:
    """The brief's text, or "" when it is not there (the critic still runs)."""
    return _brief_text(str(path or BRIEF_PATH))


_TEXT = brief_text()
REFERENCES: dict[str, tuple[str, str]] = parse_references(_TEXT)
MUST_IMPROVE: list[str] = parse_must_improve(_TEXT)
CRITIQUE_FOR: list[str] = parse_critique_for(_TEXT)
EXPECTED_STANDARD: dict[str, str] = parse_expected_standard(_TEXT)


def takeaways(ref_ids: tuple[str, ...] | list[str]) -> list[dict[str, str]]:
    """``[{id, title, takeaway}]`` for the ids the brief describes."""
    return [{"id": r, "title": REFERENCES[r][0], "takeaway": REFERENCES[r][1]}
            for r in ref_ids if r in REFERENCES]


_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def images(ref_ids: tuple[str, ...] | list[str], directory: Path | None = None) -> list[Path]:
    """The reference screenshots that exist (``ref_XX.png``, or .jpg/.webp), in
    the order asked. Missing files are skipped — none exist in the repo today."""
    base = directory or REFERENCE_DIR
    found: list[Path] = []
    for ref_id in ref_ids:
        rid = f"{int(ref_id):02d}" if str(ref_id).isdigit() else str(ref_id)
        for suffix in _IMAGE_SUFFIXES:
            candidate = base / f"ref_{rid}{suffix}"
            if candidate.is_file():
                found.append(candidate)
                break
    return found
