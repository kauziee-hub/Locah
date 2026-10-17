"""Distinctness: do two businesses of one category get two brands, or one template twice?

A site's *signature* is what a visitor notices first, on eight weighted axes:
how its pages are put together (section sequence), the opening (hero), the type,
the palette, the layout primitives (section variants + the DNA's card, shape,
edge, button, header, ground and pattern), the image treatment, how much moves,
and the art-direction concept. ``similarity(a, b)`` is the weighted mean of the
per-axis similarities, each in [0, 1]; ``report`` judges a category: it FAILS
when any pair is above ``PAIR_LIMIT`` (0.6) or the category's mean is above
``MEAN_LIMIT`` (0.45) — docs/certification/PLAN.md §2.8. The limits are the
founder's bar; they are never lowered to pass.

Two payload shapes load into one signature:

* a composed draft — ``GET /v1/b/{id}/website`` → ``data.draft`` (theme +
  ``pages[].sections``): ``signature_from_draft``;
* a site-lab set — ``.site-lab/<key>.json`` (home) + ``<key>~<page>.json``,
  each a PublicWebsitePayload with ``theme`` and ``page.sections``:
  ``signature_from_lab``.

Missing data is not sameness: a part of an axis that neither site carries (an
old fixture with no design DNA) is left out and the remaining weights are
renormalised; a part only one site carries counts as different. Deterministic,
no rendering, no model, no network.

CLI (prints the matrix, ``--json`` writes the full report)::

    uv run python -m platform_testing.certify.distinct --lab .site-lab \\
        --category butchers lab-cleaver lab-selvam lab-ishant family-butcher premium-butcher
"""

from __future__ import annotations

import argparse
import colorsys
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from platform_core.interview.design_dna import SERIF

PAIR_LIMIT = 0.6
MEAN_LIMIT = 0.45

# The eight judged axes (sum 1.0). page_set is carried for the record only.
WEIGHTS: dict[str, float] = {
    "section_sequence": 0.20,
    "hero": 0.15,
    "typography": 0.15,
    "palette": 0.12,
    "layout_primitives": 0.13,
    "image_treatment": 0.08,
    "motion": 0.07,
    "concept": 0.10,
}
AXES: tuple[str, ...] = (*WEIGHTS, "page_set")

# Sections that move on scroll or on load (the renderer's scenes and scroll moments).
MOVING_VARIANTS: dict[str, frozenset[str]] = {
    "hero": frozenset({"cinematic_zoom", "orbit", "plane", "kinetic", "depth"}),
    "about": frozenset({"word_reveal", "sticky_split", "collage"}),
    "product_showcase": frozenset({"rail", "stack", "chapters", "hover_list"}),
    "media_text": frozenset({"sticky"}),
}
MOVING_TYPES = frozenset({"marquee"})  # every variant of a marquee moves
BUDGETS = ("restrained", "gentle", "signature", "expressive")

LAYOUT_TRAITS = ("cardstyle", "shape", "divider", "button", "navstyle", "texture", "pattern")
_PICTURE_SKIP = frozenset({"og_image_asset_id", "logo_asset_id"})  # not on the page
_NESTED_PICTURE_LISTS = ("items", "categories")
_HOME_SLUGS = frozenset({"", "/", "home", "index"})
_HUE_NAMES = ("red", "orange", "yellow", "lime", "green", "teal", "cyan", "azure", "blue", "violet", "magenta",
              "rose")


# --------------------------------------------------------------- signature

@dataclass(frozen=True)
class Colour:
    hex: str
    hue: float  # degrees, 0-360
    saturation: float  # 0-1 (HLS)
    lightness: float  # 0-1 (HLS)
    bucket: str  # one of _HUE_NAMES, or "neutral"
    tone: str  # dark | mid | light

    @property
    def achromatic(self) -> bool:
        return self.bucket == "neutral"


@dataclass(frozen=True)
class Palette:
    primary: Colour | None
    accent: Colour | None
    background: Colour | None
    key: str
    mode: str


@dataclass(frozen=True)
class Layout:
    variants: tuple[str, ...]  # sorted multiset of "type:variant" over every page
    traits: dict[str, str]  # LAYOUT_TRAITS from the DNA


@dataclass(frozen=True)
class Imagery:
    photo: str  # dna.photo
    treatment: str  # theme.image_treatment
    pictures: dict[str, int]  # page slug -> pictures on that page


@dataclass(frozen=True)
class Motion:
    budget: str  # dna.budget
    experience: str  # experience.motion
    moving: int  # moving sections over every page


@dataclass(frozen=True)
class Signature:
    key: str
    name: str
    section_sequence: dict[str, tuple[str, ...]]  # page slug (home first) -> "type:variant" tokens
    hero: dict[str, str]  # variant, hero_style, experience
    typography: dict[str, str]  # display, body, headline, type_system
    palette: Palette
    layout_primitives: Layout
    image_treatment: Imagery
    motion: Motion
    concept: str
    page_set: tuple[str, ...]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def colour(value: Any) -> Colour | None:
    """A #rgb / #rrggbb(aa) value, normalised; None when it is not a colour."""
    raw = _text(value).lstrip("#").lower()
    if len(raw) in (3, 4):
        raw = "".join(ch * 2 for ch in raw[:3])
    raw = raw[:6]
    if len(raw) != 6 or any(ch not in "0123456789abcdef" for ch in raw):
        return None
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    hue = round(h * 360, 1)
    neutral = s < 0.15 or lightness < 0.08 or lightness > 0.95
    bucket = "neutral" if neutral else _HUE_NAMES[int(((hue + 15) % 360) // 30)]
    tone = "dark" if lightness < 0.3 else "light" if lightness > 0.75 else "mid"
    return Colour(f"#{raw}", hue, round(s, 3), round(lightness, 3), bucket, tone)


def _sections(page: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [s for s in page.get("sections") or [] if isinstance(s, dict) and s.get("is_visible") is not False]
    if all("sort_order" in s for s in rows):
        rows.sort(key=lambda s: (s.get("sort_order") is None, s.get("sort_order") or 0))
    return rows


def _token(section: Mapping[str, Any]) -> str:
    return f"{_text(section.get('section_type_id')) or '?'}:{_text(section.get('layout_variant')) or '-'}"


def _is_moving(section: Mapping[str, Any]) -> bool:
    kind = _text(section.get("section_type_id"))
    if kind in MOVING_TYPES:
        return True
    return _text(section.get("layout_variant")) in MOVING_VARIANTS.get(kind, frozenset())


def _pictures(section: Mapping[str, Any]) -> int:
    """Pictures a section shows: resolved assets plus asset ids in its content."""
    refs = {k for k in _dict(section.get("assets")) if k not in _PICTURE_SKIP}
    content = _dict(section.get("content"))
    if content.get("image_asset_id"):
        refs.add("image_asset_id")
    for i, raw in enumerate(content.get("image_asset_ids") or []):
        if raw:
            refs.add(f"image_asset_id_{i}")
    for list_key in _NESTED_PICTURE_LISTS:
        for i, row in enumerate(content.get(list_key) or []):
            if isinstance(row, dict) and row.get("image_asset_id"):
                refs.add(f"{list_key}.{i}")
    return len(refs)


def _slug(page: Mapping[str, Any]) -> str:
    slug = _text(page.get("slug")).strip("/").lower()
    if _text(page.get("page_type")) == "home" or slug in _HOME_SLUGS:
        return "home"
    return slug or "page"


def build_signature(key: str, theme: Mapping[str, Any], pages: Sequence[Mapping[str, Any]], *,
                    name: str = "") -> Signature:
    """One site's signature from its theme and pages (each ``{slug, sections}``)."""
    theme = _dict(theme)
    dna = _dict(theme.get("dna"))
    experience = _dict(theme.get("experience"))
    cd_palette = _dict(_dict(theme.get("creative_direction")).get("palette"))
    notes: list[str] = []

    ordered: list[tuple[str, list[dict[str, Any]]]] = []
    seen: Counter[str] = Counter()
    for page in pages:
        slug = _slug(page)
        seen[slug] += 1
        if seen[slug] > 1:
            notes.append(f"duplicate page slug {slug!r}")
            slug = f"{slug}#{seen[slug]}"
        ordered.append((slug, _sections(page)))
    ordered.sort(key=lambda item: item[0] != "home")  # stable: home first, the rest as given
    if not ordered or ordered[0][0] != "home":
        notes.append("no home page")

    sequence = {slug: tuple(_token(s) for s in rows) for slug, rows in ordered}
    home_rows = ordered[0][1] if ordered and ordered[0][0] == "home" else []
    hero_variant = next((_text(s.get("layout_variant")) for s in home_rows
                         if s.get("section_type_id") == "hero"), "")
    if not dna:
        notes.append("no design DNA (pre-DNA payload): DNA parts are left out of the comparison")

    def hexes(theme_key: str, cd_key: str) -> Colour | None:
        return colour(theme.get(theme_key)) or colour(cd_palette.get(cd_key))

    every = [s for _, rows in ordered for s in rows]
    return Signature(
        key=key,
        name=name,
        section_sequence=sequence,
        hero={"variant": hero_variant, "hero_style": _text(theme.get("hero_style")),
              "experience": _text(experience.get("hero"))},
        typography={"display": _text(dna.get("display")), "body": _text(dna.get("body")),
                    "headline": _text(dna.get("headline")), "type_system": _text(theme.get("type_system"))},
        palette=Palette(
            primary=hexes("primary_color", "primary"),
            accent=hexes("accent_color", "accent"),
            background=hexes("background_color", "surface"),
            key=_text(theme.get("palette_key")),
            mode=_text(theme.get("palette_mode") or cd_palette.get("mode")),
        ),
        layout_primitives=Layout(
            variants=tuple(sorted(_token(s) for s in every)),
            traits={t: _text(dna.get(t)) for t in LAYOUT_TRAITS},
        ),
        image_treatment=Imagery(
            photo=_text(dna.get("photo")),
            treatment=_text(theme.get("image_treatment")),
            pictures={slug: sum(_pictures(s) for s in rows) for slug, rows in ordered},
        ),
        motion=Motion(budget=_text(dna.get("budget")), experience=_text(experience.get("motion")),
                      moving=sum(1 for s in every if _is_moving(s))),
        concept=_text(dna.get("concept")),
        page_set=tuple(sorted(sequence)),
        notes=notes,
    )


def signature_from_draft(draft: Mapping[str, Any], *, key: str | None = None, name: str = "") -> Signature:
    """A composed draft: ``data.draft`` of ``GET /v1/b/{id}/website``.

    The whole response (``{"data": {"draft": ...}}``) or its ``data`` is accepted too.
    """
    if isinstance(draft.get("data"), dict):
        draft = draft["data"]
    if isinstance(draft.get("draft"), dict):
        draft = draft["draft"]
    pages = [p for p in draft.get("pages") or [] if isinstance(p, dict)]
    if all("sort_order" in p for p in pages):
        pages.sort(key=lambda p: (p.get("sort_order") is None, p.get("sort_order") or 0))
    return build_signature(key or _text(draft.get("id")) or "draft", _dict(draft.get("theme")), pages, name=name)


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a website payload")
    return data


def signature_from_lab(lab_dir: Path, key: str) -> Signature:
    """A site-lab set: ``<key>.json`` (home) and every ``<key>~<page>.json``."""
    home = _read(Path(lab_dir) / f"{key}.json")
    if not isinstance(home.get("page"), dict):
        raise ValueError(f"{key}: not a PublicWebsitePayload (no page)")
    pages: list[Mapping[str, Any]] = [home["page"]]
    for path in sorted(Path(lab_dir).glob(f"{key}~*.json")):
        page = _read(path).get("page")
        if isinstance(page, dict):
            pages.append(page)
    name = _text(_dict(home.get("business")).get("display_name"))
    return build_signature(key, _dict(home.get("theme")), pages, name=name)


def lab_keys(lab_dir: Path) -> list[str]:
    """Every site in a lab directory: a ``<key>.json`` PublicWebsitePayload (inner pages excluded)."""
    keys: list[str] = []
    for path in sorted(Path(lab_dir).glob("*.json")):
        if "~" in path.stem:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("page"), dict) and "theme" in data:
            keys.append(path.stem)
    return keys


# -------------------------------------------------------------- similarity

def _wmean(parts: Iterable[tuple[float, float | None]]) -> float | None:
    """Weighted mean over the parts that are known; None when none is."""
    known = [(w, v) for w, v in parts if v is not None]
    total = sum(w for w, _ in known)
    return sum(w * v for w, v in known) / total if total else None


def _cat(a: str, b: str) -> float | None:
    if not a and not b:
        return None
    return 1.0 if a == b else 0.0


def _count(a: int, b: int) -> float:
    return 1.0 if a == b else 1.0 - abs(a - b) / max(a, b)


def _token_match(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return 0.5 if a.split(":", 1)[0] == b.split(":", 1)[0] else 0.0


def sequence_similarity(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Order-aware: a soft longest common subsequence (same section in another layout = half)."""
    if not a and not b:
        return None
    if not a or not b:
        return 0.0
    prev = [0.0] * (len(b) + 1)
    for x in a:
        row = [0.0]
        for j, y in enumerate(b, 1):
            row.append(max(prev[j], row[j - 1], prev[j - 1] + _token_match(x, y)))
        prev = row
    return 2 * prev[-1] / (len(a) + len(b))


def multiset_similarity(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Jaccard over multisets: sum of minimum counts over sum of maximum counts."""
    ca, cb = Counter(a), Counter(b)
    union = sum((ca | cb).values())
    return sum((ca & cb).values()) / union if union else None


def set_similarity(a: Iterable[str], b: Iterable[str]) -> float | None:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else None


def colour_similarity(a: Colour | None, b: Colour | None, *, hue_weight: float = 0.65) -> float | None:
    """Hue distance (90 degrees apart = unrelated) and lightness; greys compare on lightness alone."""
    if a is None and b is None:
        return None
    if a is None or b is None:
        return 0.0
    light = 1.0 - abs(a.lightness - b.lightness)
    if a.achromatic and b.achromatic:
        return light
    if a.achromatic or b.achromatic:
        hue = 0.25
    else:
        apart = abs(a.hue - b.hue) % 360
        hue = max(0.0, 1.0 - min(apart, 360 - apart) / 90)
    return hue_weight * hue + (1 - hue_weight) * light


def _section_sequence(a: Signature, b: Signature) -> float | None:
    home = sequence_similarity(a.section_sequence.get("home", ()), b.section_sequence.get("home", ()))
    inner_a = {k: v for k, v in a.section_sequence.items() if k != "home"}
    inner_b = {k: v for k, v in b.section_sequence.items() if k != "home"}
    if not inner_a and not inner_b:
        return home
    # Pair inner pages by how alike they are (a shop and a menu are both the range page).
    scored = sorted(((sequence_similarity(va, vb) or 0.0, ka, kb)
                     for ka, va in inner_a.items() for kb, vb in inner_b.items()), reverse=True)
    used_a: set[str] = set()
    used_b: set[str] = set()
    total = 0.0
    for score, ka, kb in scored:
        if ka not in used_a and kb not in used_b:
            used_a.add(ka)
            used_b.add(kb)
            total += score
    inner = total / max(len(inner_a), len(inner_b))
    return _wmean([(0.5, home), (0.5, inner)])


def _display(a: str, b: str) -> float | None:
    if not a and not b:
        return None
    if a == b:
        return 1.0
    if a and b and ((a in SERIF) == (b in SERIF)):
        return 0.4  # two serifs (or two sans) read closer than a serif against a grotesk
    return 0.0


def _budget(a: str, b: str) -> float | None:
    if a in BUDGETS and b in BUDGETS:
        return 1.0 - abs(BUDGETS.index(a) - BUDGETS.index(b)) / (len(BUDGETS) - 1)
    return _cat(a, b)


def compare(a: Signature, b: Signature) -> dict[str, float | None]:
    """Per-axis similarity in [0, 1]; None for an axis neither site carries."""
    ta, tb = a.typography, b.typography
    pa, pb = a.palette, b.palette
    la, lb = a.layout_primitives, b.layout_primitives
    ia, ib = a.image_treatment, b.image_treatment
    ma, mb = a.motion, b.motion
    pictures = (_count(ia.pictures.get("home", 0), ib.pictures.get("home", 0))
                + _count(sum(ia.pictures.values()), sum(ib.pictures.values()))) / 2
    return {
        "section_sequence": _section_sequence(a, b),
        "hero": _wmean([(0.5, _cat(a.hero["variant"], b.hero["variant"])),
                        (0.25, _cat(a.hero["hero_style"], b.hero["hero_style"])),
                        (0.25, _cat(a.hero["experience"], b.hero["experience"]))]),
        "typography": _wmean([(0.35, _display(ta["display"], tb["display"])),
                              (0.2, _cat(ta["body"], tb["body"])),
                              (0.2, _cat(ta["headline"], tb["headline"])),
                              (0.25, _cat(ta["type_system"], tb["type_system"]))]),
        "palette": _wmean([(0.35, colour_similarity(pa.primary, pb.primary)),
                           (0.2, colour_similarity(pa.accent, pb.accent)),
                           (0.25, colour_similarity(pa.background, pb.background, hue_weight=0.35)),
                           (0.1, _cat(pa.key, pb.key)),
                           (0.1, _cat(pa.mode, pb.mode))]),
        "layout_primitives": _wmean([(0.5, multiset_similarity(la.variants, lb.variants)),
                                     (0.5, _wmean([(1.0, _cat(la.traits.get(t, ""), lb.traits.get(t, "")))
                                                   for t in LAYOUT_TRAITS]))]),
        "image_treatment": _wmean([(0.4, _cat(ia.photo, ib.photo)), (0.3, _cat(ia.treatment, ib.treatment)),
                                   (0.3, pictures)]),
        "motion": _wmean([(0.4, _budget(ma.budget, mb.budget)), (0.3, _cat(ma.experience, mb.experience)),
                          (0.3, _count(ma.moving, mb.moving))]),
        "concept": _cat(a.concept, b.concept),
        "page_set": set_similarity(a.page_set, b.page_set),
    }


def _overall(axes: Mapping[str, float | None]) -> float:
    value = _wmean([(w, axes.get(axis)) for axis, w in WEIGHTS.items()])
    return 0.0 if value is None else min(1.0, max(0.0, value))


def similarity(a: Signature, b: Signature) -> float:
    """Weighted mean of the judged axes, in [0, 1] (1 = the same site)."""
    return _overall(compare(a, b))


# ------------------------------------------------------------------ report

def _shared(axes: Mapping[str, float | None], top: int = 3) -> list[str]:
    """The axes that make a pair alike, most to blame first."""
    order = list(WEIGHTS)
    ranked = sorted((k for k, v in axes.items() if k in WEIGHTS and v is not None),
                    key=lambda k: (-WEIGHTS[k] * (axes[k] or 0.0), order.index(k)))
    strong = [k for k in ranked if (axes.get(k) or 0.0) >= 0.75]
    return (strong or ranked)[:top]


def report(category: str, sigs: Mapping[str, Signature]) -> dict[str, Any]:
    """Pairwise similarity for one category, judged against PAIR_LIMIT and MEAN_LIMIT."""
    pairs: list[dict[str, Any]] = []
    for ka, kb in combinations(sorted(sigs), 2):
        axes = compare(sigs[ka], sigs[kb])
        pairs.append({
            "a": ka, "b": kb, "similarity": round(_overall(axes), 3),
            "axes": {k: (None if v is None else round(v, 3)) for k, v in axes.items()},
            "skipped": [k for k in WEIGHTS if axes.get(k) is None],
        })
    pairs.sort(key=lambda p: (-p["similarity"], p["a"], p["b"]))
    scores = [p["similarity"] for p in pairs]
    top = max(scores) if scores else 0.0
    mean = round(sum(scores) / len(scores), 3) if scores else 0.0
    reasons: list[str] = []
    if len(sigs) < 2:
        reasons.append(f"{len(sigs)} site(s): distinctness needs at least two to compare")
    too_similar = [(p["a"], p["b"], _shared(p["axes"])) for p in pairs if p["similarity"] > PAIR_LIMIT]
    for a, b, shared in too_similar:
        reasons.append(f"{a} ~ {b} = {next(p['similarity'] for p in pairs if p['a'] == a and p['b'] == b)}"
                       f" > {PAIR_LIMIT} (shared: {', '.join(shared)})")
    if mean > MEAN_LIMIT:
        reasons.append(f"category mean {mean} > {MEAN_LIMIT}")
    return {
        "category": category,
        "sites": sorted(sigs),
        "limits": {"pair": PAIR_LIMIT, "mean": MEAN_LIMIT},
        "weights": dict(WEIGHTS),
        "pairs": pairs,
        "max": top,
        "mean": mean,
        "verdict": "fail" if reasons else "pass",
        "too_similar": too_similar,
        "reasons": reasons,
        "notes": {k: s.notes for k, s in sorted(sigs.items()) if s.notes},
    }


def matrix_text(rep: Mapping[str, Any]) -> str:
    """The pairwise matrix as aligned text, for a terminal or a report."""
    sites: list[str] = list(rep["sites"])
    sims = {(p["a"], p["b"]): p["similarity"] for p in rep["pairs"]}
    width = max([len(s) for s in sites] + [6])
    lines = [f"{rep['category']}: max {rep['max']}  mean {rep['mean']}  -> {rep['verdict'].upper()}",
             " " * width + " " + " ".join(f"{s[:7]:>7}" for s in sites)]
    for a in sites:
        cells = []
        for b in sites:
            value = sims.get((a, b), sims.get((b, a)))
            cells.append(f"{'-':>7}" if a == b else f"{value:>7.3f}")
        lines.append(f"{a:<{width}} " + " ".join(cells))
    lines += [f"  ! {r}" for r in rep["reasons"]]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pairwise design distinctness over site-lab payloads.")
    parser.add_argument("keys", nargs="*", help="lab keys (default: every site in --lab)")
    parser.add_argument("--lab", type=Path, default=Path(".site-lab"))
    parser.add_argument("--category", default="lab")
    parser.add_argument("--json", type=Path, help="write the full report here")
    args = parser.parse_args(argv)
    keys = args.keys or lab_keys(args.lab)
    rep = report(args.category, {k: signature_from_lab(args.lab, k) for k in keys})
    print(matrix_text(rep))
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if rep["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
