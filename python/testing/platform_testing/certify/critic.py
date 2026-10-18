"""The certification critic: a demanding creative director looks at every page.

    critique = await critique_site(provider, site_dir, manifest, category="clinic", round_no=1)

Reads ``<site_dir>/render.json`` and its full-page shots (tools/certify/render.mjs,
PLAN.md §2.4) and returns — and writes to ``<site_dir>/critique.json`` and
``critique.r<round>.json`` — the critique contract (PLAN.md §2.5)::

    {scores{hero, typography, spacing, composition, imagery, art_direction, page_depth,
            originality, relevance, cta_hierarchy, catalog_presentation, mobile,
            consistency, motion, not_template}: 0-10,
     defects[{id, page, section, viewport, severity, layer, text, source}], ...}

How it judges:

1. **One vision call per page** — the desktop shot (xl, else laptop) cut into up to
   three tiles of at most 1600px, the phone shot cut into columns laid side by
   side (so a 15 000px phone page stays legible), the category's reference
   screenshots when ``docs/visual-references/ref_XX.png`` exist (none are checked
   in today — the written takeaways then carry the bar), and a JSON context: the
   business, category, page, its sections from the payload, the reference
   takeaways, and the brief's "What must improve" list. Thirteen dimensions are
   scored per page against the REFERENCE CLASS (8 = belongs beside the references,
   5 = a polished template, 3 = amateur).
2. **One cross-page call** — a thumbnail per page — scores ``consistency`` and
   ``originality``, which only make sense for the site as a whole.
3. **Variance control** — vision judging wobbles. A page whose first weighted
   score lands within 1.0 of the pass mark (8.5) is judged a second time and the
   lower score of each dimension is kept; both answers are kept in ``raw``. The
   cross-page call is judged again when either of its scores lands within 1.0 of
   the dimension floor (7).
4. **Deterministic defects** from render.json — horizontal overflow and broken
   images (critical), serious/critical axe violations, images without alt,
   missing title/description, LCP > 4s on laptop, CLS > 0.1 (major), console
   errors (minor) — and, from the distinctness check, "same visual structure as
   <other site>" (major).

Site score per dimension = the mean of the page scores; consistency and
originality come from the cross-page call. A page the model could not judge is
reported in ``errors`` and ``complete`` is false — the gate never passes an
incomplete critique.

This is a tool a person runs (through the certification run); the suite drives
it with a fake provider and never reaches a real model.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
from collections.abc import Awaitable, Callable, Collection, Mapping
from pathlib import Path
from typing import Any, Protocol

from platform_testing.certify import references
from platform_testing.certify.gate import (
    DIMENSION_FLOOR,
    DIMENSIONS,
    LAYERS,
    PASS_SCORE,
    SEVERITIES,
    weighted_score,
)

# v2: the page context lists the draft's visible sections, so a defect's section
# number means something (v1 critiques never listed them).
CRITIC_VERSION = "certify-critic-v2"
PURPOSE = "image.site_critique"  # routes to the provider's vision model pin, if any

CROSS_DIMENSIONS: tuple[str, ...] = ("consistency", "originality")
PAGE_DIMENSIONS: tuple[str, ...] = tuple(d for d in DIMENSIONS if d not in CROSS_DIMENSIONS)
DOUBLE_JUDGE_MARGIN = 1.0

DESKTOP_VIEWPORTS = ("xl", "laptop")
MOBILE_VIEWPORT = "mobile"
VIEWPORT_ORDER = ("mobile", "tablet", "laptop", "xl")  # most telling first

TILE_MAX_HEIGHT = 1600
DESKTOP_TILE_WIDTH = 1280
DESKTOP_MIN_WIDTH = 640
MAX_TILES = 3
MOBILE_COLUMN_WIDTH = 360
MOBILE_COLUMNS_PER_TILE = 6
MOBILE_GUTTER = 14
THUMB_BOX = (480, TILE_MAX_HEIGHT)
REFERENCE_BOX = (1280, TILE_MAX_HEIGHT)
MAX_REFERENCE_IMAGES = 3
MAX_CROSS_PAGES = 12

LCP_LIMIT_MS = 4000
CLS_LIMIT = 0.1
OUTPUT_TOKENS = 8000
RETRY_OUTPUT_TOKENS = 16384  # the budget the site generator itself uses with this provider


class VisionProvider(Protocol):
    async def generate_structured_with_images(
        self, prompt: str, images: list[Any], schema: dict[str, Any], model_config: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


# ----------------------------------------------------------------- the prompts

_SCALE = """Scale for every score (0-10), always against the REFERENCE CLASS — premium, art-directed,
custom builds that look like a $10k agency project — never against average small-business sites:
10 = could itself be a reference; 8 = belongs beside the references ("this looks expensive, a real
designer worked on this"); 7 = good custom work with visible weak spots; 5 = a polished template, tidy
but generic, what any site builder produces; 3 = amateur; 0-1 = broken. Most AI-built sites earn 4-6.
Do not round up and do not be kind: an 8 must be earned by what you can see."""

_DEFECT_RULES = """Defects: each one concrete, observable problem a designer could act on — the most
damaging first. Good: "menu page is a long data dump of names and prices", "three consecutive sections
use identical card grids", "hero photography feels like stock and could be any restaurant", "mobile:
the hero heading collides with the navigation", "service descriptions are one line each, too thin to
sell", "footer feels unfinished: one line and a stray link". Never vague ("could be better").
- severity: critical = a client would refuse to launch (broken, unreadable, embarrassing, wrong
  business); major = clearly below the reference class; minor = polish.
- layer: what would FIX it — copy (the words), photo (a different picture or crop), composition (another
  layout for the section), order (reorder or remove sections), styling (colour, type, spacing tokens),
  motion, responsive (the phone/tablet layout), architecture (page structure, missing blocks or pages),
  input (only the owner can fix it: real photographs of the place, team or products, fuller descriptions,
  facts we do not have). Choose input when the root cause is missing owner material — e.g. a gallery
  that feels empty because no real photos exist, or one-line descriptions because the owner gave names.
- text: one sentence. Do not invent facts about the business; judge what you see and what the context
  says."""

PAGE_PROMPT = f"""You are the creative director of a top independent design studio, the kind whose
sites win awards. Before a website may go live for a real small business you review it page by page.
You are demanding.

{_SCALE}

You receive, in order: the DESKTOP screenshots of one page (consecutive tiles, top to bottom); the same
page on a PHONE (the page cut into columns, read left to right, then the next tile); possibly reference
screenshots (the quality bar — never templates to copy); and a JSON context: the business, its
category, this page, the page's sections in order (index, type, layout) when known, the references'
takeaways for this category, what the founder says must improve, and the site's declared motion plan.

Score THIS page:
- hero: the opening screen (on an inner page, the page's opening) — a strong, art-directed
  single-screen identity, or a generic photo + headline + button?
- typography: type personality, scale contrast, hierarchy, pairing, measure, rhythm.
- spacing: whitespace, rhythm between sections, varied density, alignment.
- composition: layout variety and intent — asymmetry, overlap, editorial grids, split layouts —
  versus predictable stacks and card grid after card grid.
- imagery: photo quality, relevance to THIS business, crops and treatment; stock-looking,
  mismatched or empty image slots score low.
- art_direction: one coherent visual concept carried through colour, type, imagery and detail.
- page_depth: does the page earn its place with real substance, storytelling and hierarchy, or is it
  thin, or a data dump?
- relevance: does every section serve this business and its customers, in the right order for the
  category?
- cta_hierarchy: is the primary action (book, order, reserve, call, donate) clear, well placed and
  repeated sensibly, without competing buttons?
- catalog_presentation: menu / shop / services / programmes / rooms — category-led, featured items,
  meaningful descriptions, imagery and hierarchy, versus a plain list or price dump. On a page with no
  offerings, judge how well it presents and leads to them.
- mobile: the phone version on its own merits — composition, type scale, tap targets, no collisions,
  no cramped or blank stretches.
- motion: shots are taken with reduced motion. Judge the declared motion plan in the context and
  whether the composition is motion-ready (reveals, depth, sticky storytelling) — never reward
  animation for its own sake; 5 when nothing is declared or implied.
- not_template: 10 = unmistakably custom, 0 = obviously a template or an AI-generated page.

{_DEFECT_RULES}
- section: the section index from the context when you can tell which one, else -1.
- viewport: desktop, mobile or all.
Return at most 14 defects and a one-sentence verdict."""

CROSS_PROMPT = f"""You are the creative director of a top independent design studio reviewing a whole
website before it may go live for a real small business. You are demanding.

{_SCALE}

You receive one thumbnail per page (the full desktop page scaled down), in the order the context lists
them, possibly reference screenshots (the quality bar), and a JSON context: the business, its category
and the references' takeaways.

Score the SITE:
- consistency: one visual system across the pages (type, colour, spacing, components, image treatment)
  while each page still has a composition of its own.
- originality: could this be mistaken for a template, or for another business in the same category?
  Distinct mood, rhythm, type personality and signature moments score high.

{_DEFECT_RULES}
- page: the page slug the defect is on, or "*" for the whole site.
Cross-page problems only, e.g. "every inner page opens with the same banner", "about and services repeat
the same three-column card grid", "the contact page uses a different type style from the rest".
Return at most 8 defects and a one-sentence verdict."""


def _defect_schema(extra: dict[str, Any], max_items: int) -> dict[str, Any]:
    props: dict[str, Any] = {
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "layer": {"type": "string", "enum": list(LAYERS)},
        "text": {"type": "string", "maxLength": 280},
    } | extra
    return {"type": "array", "maxItems": max_items, "items": {
        "type": "object", "required": ["severity", "layer", "text", *extra], "properties": props}}


def _scores_schema(dims: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "object", "required": list(dims),
            "properties": {d: {"type": "number", "minimum": 0, "maximum": 10} for d in dims}}


PAGE_SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["scores", "defects", "verdict"],
    "properties": {
        "scores": _scores_schema(PAGE_DIMENSIONS),
        "defects": _defect_schema({
            "section": {"type": "integer", "minimum": -1, "maximum": 60},
            "viewport": {"type": "string", "enum": ["desktop", "mobile", "all"]},
        }, 14),
        "verdict": {"type": "string", "maxLength": 400},
    },
}

CROSS_SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["scores", "defects", "verdict"],
    "properties": {
        "scores": _scores_schema(CROSS_DIMENSIONS),
        "defects": _defect_schema({"page": {"type": "string", "maxLength": 60}}, 8),
        "verdict": {"type": "string", "maxLength": 400},
    },
}


# ----------------------------------------------------------------- images

def _open(path: Path) -> Any:
    """A screenshot as an RGB Pillow image, or None. Full-page shots are tall;
    they are our own artefacts, so Pillow's decompression-bomb limit is raised
    for this one read."""
    from PIL import Image

    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max(previous or 0, 400_000_000)
    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def _jpeg(img: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue()


def _resize(img: Any, width: int, height: int) -> Any:
    from PIL import Image

    width, height = max(1, int(width)), max(1, int(height))
    if (width, height) == img.size:
        return img
    return img.resize((width, height), Image.Resampling.LANCZOS)


def column_tiles(img: Any, width: int, per_tile: int) -> list[bytes]:
    """The page scaled to ``width`` (never enlarged), cut into ≤ 1600px
    columns, ``per_tile`` columns side by side per tile, at most three tiles.
    A page too long even for that is scaled down until it fits."""
    from PIL import Image

    w, h = img.size
    scale = min(1.0, width / w)
    capacity = per_tile * MAX_TILES * TILE_MAX_HEIGHT
    if h * scale > capacity:
        scale = capacity / h
    page = _resize(img, round(w * scale), min(capacity, round(h * scale)))
    pw, ph = page.size
    columns = [page.crop((0, top, pw, min(ph, top + TILE_MAX_HEIGHT)))
               for top in range(0, ph, TILE_MAX_HEIGHT)][:per_tile * MAX_TILES]
    tiles: list[bytes] = []
    for start in range(0, len(columns), per_tile):
        group = columns[start:start + per_tile]
        if len(group) == 1:
            tiles.append(_jpeg(group[0]))
            continue
        sheet_w = len(group) * pw + (len(group) - 1) * MOBILE_GUTTER
        sheet = Image.new("RGB", (sheet_w, max(c.size[1] for c in group)), (128, 128, 128))
        for i, column in enumerate(group):
            sheet.paste(column, (i * (pw + MOBILE_GUTTER), 0))
        tiles.append(_jpeg(sheet))
    return tiles


def desktop_tiles(img: Any) -> tuple[list[bytes], int]:
    """The desktop page in at most three tiles of ≤ 1600px: 1280 wide, one
    column per tile; a page too long for that (over ~7200px at 1920) at 640
    wide, two columns per tile. Returns (tiles, columns per tile)."""
    w, h = img.size
    if h * min(1.0, DESKTOP_TILE_WIDTH / w) <= MAX_TILES * TILE_MAX_HEIGHT:
        return column_tiles(img, DESKTOP_TILE_WIDTH, 1), 1
    return column_tiles(img, DESKTOP_MIN_WIDTH, 2), 2


def mobile_tiles(img: Any) -> list[bytes]:
    """The phone page at 360 wide in ≤ 1600px columns, six side by side per
    tile, at most three tiles (≈ 28 800px of page before any downscale)."""
    return column_tiles(img, MOBILE_COLUMN_WIDTH, MOBILE_COLUMNS_PER_TILE)


def fit(img: Any, box: tuple[int, int]) -> bytes:
    """The whole image scaled to fit inside ``box`` (never enlarged)."""
    w, h = img.size
    scale = min(1.0, box[0] / w, box[1] / h)
    return _jpeg(_resize(img, round(w * scale), round(h * scale)))


def _image_input(data: bytes) -> Any:
    from platform_core.website.ai_provider import ImageInput

    return ImageInput(data=data, mime_type="image/jpeg")


# ----------------------------------------------------------------- reading the run

def _shot_path(site_dir: Path, slug: str, vp: str, entry: Mapping[str, Any]) -> Path | None:
    named = str(entry.get("png") or "")
    candidates = []
    if named:
        p = Path(named)
        candidates += [p] if p.is_absolute() else [site_dir / p, site_dir / "shots" / p.name]
    safe = slug.strip("/").replace("/", "_") or "home"
    candidates.append(site_dir / "shots" / f"{safe}__{vp}.png")
    return next((c for c in candidates if c.is_file()), None)


def _page_slug(page: Mapping[str, Any]) -> str:
    return str(page.get("slug") or "").strip("/") or "home"


def _payload_pages(manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """``{slug: [{index, type, layout, title}]}`` from a composed payload or the
    owner's draft, wherever the manifest carries one (``payload.pages``,
    ``pages`` or ``draft.pages`` with sections). Hidden sections are not on the
    page, so they are not listed, and ``index`` counts the visible ones in page
    order: the number the critic gives a defect is the one the repair loop reads
    back (repair.attribute)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for holder in (manifest.get("payload"), manifest, manifest.get("draft")):
        if not isinstance(holder, Mapping):
            continue
        for page in holder.get("pages") or []:
            if not isinstance(page, Mapping) or not isinstance(page.get("sections"), list):
                continue
            rows: list[dict[str, Any]] = []
            for s in page["sections"]:
                if not isinstance(s, Mapping) or s.get("is_visible") is False:
                    continue
                row: dict[str, Any] = {"index": len(rows),
                                       "type": str(s.get("section_type_id") or s.get("type") or ""),
                                       "layout": str(s.get("layout_variant") or s.get("layout") or "")}
                content = s.get("content") if isinstance(s.get("content"), Mapping) else {}
                assert isinstance(content, Mapping)
                title = next((str(content.get(k)).strip() for k in ("title", "headline", "eyebrow")
                              if str(content.get(k) or "").strip()), "")
                if title:
                    row["title"] = title[:80]
                rows.append(row)
            out.setdefault(_page_slug(page), rows)
    return out


def _art_direction(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The declared concept and motion plan, when the manifest carries them."""
    payload = manifest.get("payload") if isinstance(manifest.get("payload"), Mapping) else manifest
    assert isinstance(payload, Mapping)
    hints = payload.get("theme_hints") if isinstance(payload.get("theme_hints"), Mapping) else {}
    assert isinstance(hints, Mapping)
    dna = hints.get("dna") if isinstance(hints.get("dna"), Mapping) else {}
    experience = hints.get("experience") or payload.get("experience") or {}
    assert isinstance(dna, Mapping)
    out: dict[str, Any] = {}
    for key in ("concept", "budget", "display", "body", "photo", "grade"):
        if dna.get(key):
            out[key if key != "budget" else "motion_budget"] = dna[key]
    if isinstance(experience, Mapping) and experience.get("motion"):
        out["motion"] = experience["motion"]
    return out


def _business(manifest: Mapping[str, Any]) -> str:
    business = manifest.get("business")
    for value in (manifest.get("business_name"),
                  business.get("name") if isinstance(business, Mapping) else business,
                  manifest.get("scenario"), manifest.get("site_key")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _must_improve() -> list[str]:
    return [m for m in references.MUST_IMPROVE if not m.casefold().startswith("visual self-critique")]


# ----------------------------------------------------------------- answers

def _score(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(10.0, max(0.0, f)), 2) if math.isfinite(f) else None


def parse_scores(raw: Any, dims: tuple[str, ...]) -> dict[str, float]:
    got = raw.get("scores") if isinstance(raw, Mapping) else None
    if not isinstance(got, Mapping):
        return {}
    out: dict[str, float] = {}
    for d in dims:
        s = _score(got.get(d))
        if s is not None:
            out[d] = s
    return out


_SEVERITY_ALIASES = {"high": "major", "blocker": "critical", "severe": "critical", "medium": "major",
                     "low": "minor", "nit": "minor"}


def _severity(value: Any) -> str:
    s = str(value or "").strip().casefold()
    s = _SEVERITY_ALIASES.get(s, s)
    return s if s in SEVERITIES else "major"


def _layer(value: Any) -> str:
    s = str(value or "").strip().casefold()
    return s if s in LAYERS else "composition"


def parse_defects(raw: Any, *, page: str | None, desktop_vp: str, round_no: int,
                  known_pages: set[str], prefix: str) -> list[dict[str, Any]]:
    rows = raw.get("defects") if isinstance(raw, Mapping) else None
    out: list[dict[str, Any]] = []
    for n, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, Mapping):
            continue
        text = " ".join(str(row.get("text") or "").split())[:280]
        if not text:
            continue
        where = page
        if where is None:
            named = str(row.get("page") or "").strip("/ ")
            where = named if named in known_pages else "*"
        try:
            section = int(row.get("section", -1))
        except (TypeError, ValueError):
            section = -1
        vp = str(row.get("viewport") or "all").strip().casefold()
        viewport = desktop_vp if vp == "desktop" else MOBILE_VIEWPORT if vp in {"mobile", "phone"} \
            else "all"
        out.append({"id": f"r{round_no}:{prefix}:{where}:{n + 1}", "page": where, "section": section,
                    "viewport": viewport, "severity": _severity(row.get("severity")),
                    "layer": _layer(row.get("layer")), "text": text, "source": "vision"})
    return out


# ----------------------------------------------------------------- deterministic defects

def _count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value) if math.isfinite(value) else 0
    if isinstance(value, (list, tuple, dict)):
        return len(value)
    return 0


def _metric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def render_defects(render: Mapping[str, Any], round_no: int) -> list[dict[str, Any]]:
    """What the render measured, as defects: no judgement involved. One defect
    per page and kind (an axe rule counts once per page), on the most telling
    viewport, with every viewport it was seen on."""
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def add(page: str, kind: str, vp: str, severity: str, layer: str, text: str) -> None:
        key = (page, kind)
        if key in found:
            row = found[key]
            if vp not in row["viewports"]:
                row["viewports"].append(vp)
                row["viewports"].sort(key=lambda v: VIEWPORT_ORDER.index(v) if v in VIEWPORT_ORDER else 9)
                row["viewport"] = row["viewports"][0]
            return
        found[key] = {"id": f"r{round_no}:render:{page}:{kind}", "page": page, "section": -1,
                      "viewport": vp, "viewports": [vp] if vp != "all" else [], "severity": severity,
                      "layer": layer, "text": text, "source": "render", "kind": kind.split(":")[0]}

    for page in render.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        slug = _page_slug(page)
        status = page.get("status")
        if isinstance(status, int) and not isinstance(status, bool) and status >= 400:
            add(slug, "status", "all", "critical", "architecture",
                f"the {slug} page answers HTTP {status} instead of rendering")
            continue
        meta = page.get("meta") if isinstance(page.get("meta"), Mapping) else {}
        assert isinstance(meta, Mapping)
        if not str(page.get("title") or "").strip():
            add(slug, "meta_title", "all", "major", "architecture",
                f"the {slug} page has no <title>")
        if not str(meta.get("description") or "").strip():
            add(slug, "meta_description", "all", "major", "architecture",
                f"the {slug} page has no meta description")
        viewports = page.get("viewports") if isinstance(page.get("viewports"), Mapping) else {}
        assert isinstance(viewports, Mapping)
        for vp, m in viewports.items():
            if not isinstance(m, Mapping):
                continue
            vp = str(vp)
            if _count(m.get("overflow_x")):
                add(slug, "overflow_x", vp, "critical", "responsive",
                    f"the {slug} page scrolls sideways (horizontal overflow) at {vp}")
            if (n := _count(m.get("broken_images"))):
                add(slug, "broken_images", vp, "critical", "photo",
                    f"{n} broken image(s) on the {slug} page at {vp}")
            if (n := _count(m.get("imgs_without_alt"))):
                add(slug, "imgs_without_alt", vp, "major", "copy",
                    f"{n} image(s) without alt text on the {slug} page")
            axe = m.get("axe") if isinstance(m.get("axe"), Mapping) else {}
            assert isinstance(axe, Mapping)
            for v in axe.get("violations") or []:
                if isinstance(v, Mapping) and str(v.get("impact") or "") in {"serious", "critical"}:
                    rule = str(v.get("id") or "unknown")
                    add(slug, f"axe:{rule}", vp, "major", "styling",
                        f"accessibility: axe '{rule}' ({v.get('impact')}, {_count(v.get('nodes'))} "
                        f"element(s)) on the {slug} page")
            lcp = _metric(m.get("lcp_ms"))
            if vp == "laptop" and lcp is not None and lcp > LCP_LIMIT_MS:
                add(slug, "lcp", vp, "major", "architecture",
                    f"the {slug} page paints its largest element after {lcp / 1000:.1f}s on laptop "
                    f"(limit {LCP_LIMIT_MS / 1000:.0f}s)")
            cls = _metric(m.get("cls"))
            if cls is not None and cls > CLS_LIMIT:
                add(slug, "cls", vp, "major", "responsive",
                    f"the {slug} page shifts while loading (CLS {cls:.2f} > {CLS_LIMIT}) at {vp}")
            if (n := _count(m.get("console_errors"))):
                add(slug, "console_errors", vp, "minor", "architecture",
                    f"{n} console error(s) on the {slug} page at {vp}")
    return list(found.values())


def similar_from_distinct(report: Mapping[str, Any], site_key: str) -> list[dict[str, Any]]:
    """``similar_to`` for one site from a distinct.py category report: every
    pair over its limit that involves this site, as {site_key, similarity, shared}."""
    limit = _metric((report.get("limits") or {}).get("pair")) if isinstance(
        report.get("limits"), Mapping) else None
    shared = {(str(a), str(b)): list(s) for a, b, s in report.get("too_similar") or []}
    out: list[dict[str, Any]] = []
    for p in report.get("pairs") or []:
        if not isinstance(p, Mapping) or site_key not in (p.get("a"), p.get("b")):
            continue
        a, b = str(p.get("a")), str(p.get("b"))
        sim = _metric(p.get("similarity"))
        if (a, b) not in shared and (limit is None or sim is None or sim <= limit):
            continue
        out.append({"site_key": b if a == site_key else a, "similarity": sim,
                    "shared": shared.get((a, b), [])})
    return out


def similarity_defects(similar_to: list[Any] | None, round_no: int) -> list[dict[str, Any]]:
    """From the distinctness check: this site looks like another one."""
    out: list[dict[str, Any]] = []
    for row in similar_to or []:
        shared: list[str] = []
        if isinstance(row, Mapping):
            other = str(row.get("site_key") or row.get("other") or row.get("site") or "").strip()
            sim = _metric(row.get("similarity"))
            shared = [str(s) for s in row.get("shared") or [] if s]
        else:
            other, sim = str(row).strip(), None
        if not other:
            continue
        bits = ([f"similarity {sim:.2f}"] if sim is not None else []) + (
            [f"shared: {', '.join(shared)}"] if shared else [])
        detail = f" ({'; '.join(bits)})" if bits else ""
        out.append({"id": f"r{round_no}:distinct:{other}", "page": "*", "section": -1, "viewport": "all",
                    "severity": "major", "layer": "composition",
                    "text": f"same visual structure as {other}{detail}", "source": "distinct",
                    "other": other, "similarity": sim})
    return out


# ----------------------------------------------------------------- the critique

Carried = dict[str, tuple[dict[str, float], float, list[dict[str, Any]], Any]]


def _carried_pages(carry: Mapping[str, Any] | None, rejudge: Collection[str] | None) -> Carried:
    """slug -> (scores, weighted, vision defects, raw) for each page ``carry``
    judged in full and ``rejudge`` does not name; nothing without ``rejudge``."""
    if carry is None or rejudge is None:
        return {}
    page_scores = carry.get("page_scores")
    raw = carry.get("raw")
    raws = raw.get("pages") if isinstance(raw, Mapping) else None
    out: Carried = {}
    for slug, scores in (page_scores.items() if isinstance(page_scores, Mapping) else []):
        if slug in rejudge or not isinstance(scores, Mapping) \
                or any(d not in scores for d in PAGE_DIMENSIONS):
            continue  # touched, or never judged in full: judged now
        clean = {d: float(scores[d]) for d in PAGE_DIMENSIONS}
        # A section number from an older critic, never shown the list, is dropped.
        renumber = {} if carry.get("version") == CRITIC_VERSION else {"section": -1}
        found = [dict(d, carried=True, **renumber) for d in carry.get("defects") or []
                 if isinstance(d, Mapping) and d.get("page") == slug and d.get("source") == "vision"
                 and ":page:" in str(d.get("id") or "")]
        out[str(slug)] = (clean, round(weighted_score(clean, PAGE_DIMENSIONS), 2), found,
                          raws.get(slug, []) if isinstance(raws, Mapping) else [])
    return out


def _merge_lower(first: dict[str, float], second: dict[str, float]) -> dict[str, float]:
    keys = set(first) | set(second)
    return {k: min(v for v in (first.get(k), second.get(k)) if v is not None) for k in keys}


def _cut_off(exc: Exception) -> bool:
    """The answer ran out of room: the reasoning used the whole budget ("empty
    content (length)") or the JSON stopped half-way ("non-JSON output")."""
    text = str(exc)
    return isinstance(exc, RuntimeError) and ("(length)" in text or "non-JSON" in text)


async def _call(provider: VisionProvider, context: dict[str, Any], images: list[bytes],
                schema: dict[str, Any], system: str, model: str | None,
                timeout_seconds: int) -> dict[str, Any]:
    config: dict[str, Any] = {"purpose": PURPOSE, "system_prompt": system,
                              # A long page (14 defects) plus the model's reasoning outran 3000
                              # tokens: the home page came back cut off ("length").
                              "max_output_tokens": OUTPUT_TOKENS, "temperature": 0.1}
    if model:
        config["model"] = model
    prompt = json.dumps(context, separators=(",", ":"), ensure_ascii=False)
    try:
        raw = await provider.generate_structured_with_images(
            prompt, [_image_input(b) for b in images], schema, config, timeout_seconds)
    except Exception as exc:
        # run7: two home pages lost their judgment when the reasoning alone used
        # all 8000 tokens. Asked once more with room to answer; any other
        # failure (and a second cut-off) is the page's reported error.
        if not _cut_off(exc):
            raise
        raw = await provider.generate_structured_with_images(
            prompt, [_image_input(b) for b in images], schema,
            config | {"max_output_tokens": RETRY_OUTPUT_TOKENS}, timeout_seconds)
    return raw if isinstance(raw, dict) else {}


Parsed = tuple[dict[str, float], list[dict[str, Any]]]
Judged = tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]], bool]
_Call = Callable[[], Awaitable[dict[str, Any]]]
_Parse = Callable[[dict[str, Any]], Parsed]
_Near = Callable[[dict[str, float]], bool]
_Job = tuple[str, _Call, _Parse, _Near]


async def _judged_twice_if_close(call: _Call, parse: _Parse, near: _Near) -> Judged:
    """Judge once; if the score lands near the line, judge again and keep the
    lower score of each dimension, the defects of the harsher answer and any
    critical defect only the other one saw. Returns (scores, defects, raws, twice)."""
    first = await call()
    scores, defects = parse(first)
    if not scores or not near(scores):
        return scores, defects, [first], False
    second = await call()
    scores2, defects2 = parse(second)
    if not scores2:
        return scores, defects, [first, second], True
    harsher, other = (defects, defects2) if weighted_score(scores) <= weighted_score(scores2) \
        else (defects2, defects)
    seen = {(d["layer"], d["viewport"], d["section"]) for d in harsher if d["severity"] == "critical"}
    extra = [d for d in other if d["severity"] == "critical"
             and (d["layer"], d["viewport"], d["section"]) not in seen]
    merged = harsher + [dict(d, id=d["id"] + ":b") for d in extra]
    return _merge_lower(scores, scores2), merged, [first, second], True


async def critique_site(
    provider: VisionProvider, site_dir: Path, manifest: dict[str, Any], *, category: str,
    round_no: int, model: str | None = None, similar_to: list[Any] | None = None,
    references_dir: Path | None = None, timeout_seconds: int = 150, write: bool = True,
    concurrency: int = 2, carry: Mapping[str, Any] | None = None,
    rejudge: Collection[str] | None = None,
) -> dict[str, Any]:
    """Judge every rendered page of one site; the critique.json contract.

    ``similar_to``: look-alike sites from the distinctness check (see
    `similar_from_distinct`); falls back to ``manifest["similar_to"]``.
    ``concurrency``: page calls in flight at once (results keep page order).
    ``carry`` + ``rejudge``: a repair round re-rendered only the pages in
    ``rejudge``; every other page the earlier critique ``carry`` judged in full
    keeps that judgment (its scores and its own vision defects; ``carried``
    lists it) instead of being judged again: its screenshots did not change,
    and judging an untouched page again would only add the critic's variance.
    The site-wide call and the render defects are always made afresh."""
    site_dir = Path(site_dir)
    render = json.loads((site_dir / "render.json").read_text(encoding="utf-8"))
    ref_ids = references.refs_for(category)
    ref_paths = references.images(ref_ids, references_dir)[:MAX_REFERENCE_IMAGES]
    ref_images: list[bytes] = []
    ref_rows: list[dict[str, Any]] = []
    for row in references.takeaways(ref_ids):
        path = next((p for p in ref_paths if p.stem == f"ref_{row['id']}"), None)
        img = _open(path) if path else None
        if img is not None:
            ref_images.append(fit(img, REFERENCE_BOX))
            row = row | {"image": "reference " + str(len(ref_images))}
        ref_rows.append(row)
    sections = _payload_pages(manifest)
    business = _business(manifest)
    kept = _carried_pages(carry, rejudge)
    art = _art_direction(manifest)
    pages = [p for p in render.get("pages") or [] if isinstance(p, Mapping)]
    known = {_page_slug(p) for p in pages}
    errors: list[str] = []
    raw: dict[str, Any] = {"pages": {}, "cross": []}
    page_scores: dict[str, dict[str, float]] = {}
    page_weighted: dict[str, float] = {}
    defects: list[dict[str, Any]] = []
    double_judged: list[str] = []
    thumbs: list[tuple[str, bytes]] = []
    jobs: list[_Job] = []
    base_context = {
        "business": business, "category": category, "round": round_no,
        "reference_class": ref_rows, "must_improve": _must_improve(),
        "critique_for": references.CRITIQUE_FOR, "expected_standard": references.EXPECTED_STANDARD,
        "site_pages": sorted(known), "art_direction": art,
        # Every LOCAH business is in India: a critic once called "₹230" the
        # wrong currency (the rupee sign is small in a scaled tile).
        "locale": {"country": "India", "currency": "Indian rupees, written ₹ (e.g. ₹230)",
                   "note": "₹ is the correct currency sign; do not report it as wrong"},
    }

    for page in pages:
        slug = _page_slug(page)
        status = page.get("status")
        if isinstance(status, int) and not isinstance(status, bool) and status >= 400:
            continue  # a deterministic critical defect says so; nothing to look at
        vps = page.get("viewports") if isinstance(page.get("viewports"), Mapping) else {}
        assert isinstance(vps, Mapping)
        desktop_vp, desktop = "", None
        for vp in DESKTOP_VIEWPORTS:
            entry = vps.get(vp) if isinstance(vps.get(vp), Mapping) else {}
            assert isinstance(entry, Mapping)
            path = _shot_path(site_dir, slug, vp, entry)
            desktop = _open(path) if path else None
            if desktop is not None:
                desktop_vp = vp
                break
        mob_entry = vps.get(MOBILE_VIEWPORT) if isinstance(vps.get(MOBILE_VIEWPORT), Mapping) else {}
        assert isinstance(mob_entry, Mapping)
        mob_path = _shot_path(site_dir, slug, MOBILE_VIEWPORT, mob_entry)
        mobile = _open(mob_path) if mob_path else None
        if desktop is None and mobile is None:
            errors.append(f"{slug}: no readable desktop or mobile screenshot")
            continue
        for label, img in (("desktop (xl or laptop)", desktop), ("mobile", mobile)):
            if img is None:  # judged on what there is, but never certified half-seen
                errors.append(f"{slug}: no readable {label} screenshot")
        d_tiles, d_cols = desktop_tiles(desktop) if desktop is not None else ([], 1)
        m_tiles = mobile_tiles(mobile) if mobile is not None else []
        if desktop is not None:
            thumbs.append((slug, fit(desktop, THUMB_BOX)))
        if slug in kept:
            continue  # unchanged since ``carry`` judged it
        d_note = " (columns read left to right)" if d_cols > 1 else ""
        listing = [{"image": i + 1,
                    "shows": f"desktop ({desktop_vp}) tile {i + 1}/{len(d_tiles)}{d_note}"}
                   for i in range(len(d_tiles))]
        listing += [{"image": len(d_tiles) + i + 1,
                     "shows": f"phone tile {i + 1}/{len(m_tiles)} (columns read left to right)"}
                    for i in range(len(m_tiles))]
        listing += [{"image": len(d_tiles) + len(m_tiles) + i + 1, "shows": f"reference {i + 1}"}
                    for i in range(len(ref_images))]
        context = base_context | {
            "page": slug, "title": str(page.get("title") or ""), "screenshots": listing,
            "sections": sections.get(slug, []),
            "missing": [v for v, img in (("desktop", desktop), ("mobile", mobile)) if img is None],
        }
        images = d_tiles + m_tiles + ref_images

        async def call(context: dict[str, Any] = context, images: list[bytes] = images) -> dict[str, Any]:
            return await _call(provider, context, images, PAGE_SCHEMA, PAGE_PROMPT, model, timeout_seconds)

        def parse(answer: dict[str, Any], slug: str = slug, desktop_vp: str = desktop_vp,
                  listed: int = len(sections.get(slug, []))) -> tuple[dict[str, float], list[dict[str, Any]]]:
            found = parse_defects(answer, page=slug, desktop_vp=desktop_vp or "laptop",
                                  round_no=round_no, known_pages=known, prefix="page")
            for d in found:  # an index the context never listed names no section
                if not 0 <= d["section"] < listed:
                    d["section"] = -1
            return parse_scores(answer, PAGE_DIMENSIONS), found

        def near(scores: dict[str, float]) -> bool:
            gap = abs(weighted_score(scores, PAGE_DIMENSIONS) - PASS_SCORE)
            return bool(gap <= DOUBLE_JUDGE_MARGIN)

        jobs.append((slug, call, parse, near))

    limit = asyncio.Semaphore(max(1, concurrency))

    async def judge(job: _Job) -> Judged | Exception:
        _, call, parse, near = job
        async with limit:
            try:
                return await _judged_twice_if_close(call, parse, near)
            except Exception as exc:  # noqa: BLE001 — one page's failure is reported, not fatal
                return exc

    results = await asyncio.gather(*(judge(job) for job in jobs))
    for (slug, *_), result in zip(jobs, results):
        if isinstance(result, Exception):
            errors.append(f"{slug}: vision call failed ({type(result).__name__}: {str(result)[:160]})")
            continue
        scores, found, raws, twice = result
        raw["pages"][slug] = raws
        missing = [d for d in PAGE_DIMENSIONS if d not in scores]
        if missing:
            errors.append(f"{slug}: no score for {', '.join(missing)}")
        if not scores:
            continue
        if twice:
            double_judged.append(slug)
        page_scores[slug] = scores
        page_weighted[slug] = round(weighted_score(scores, PAGE_DIMENSIONS), 2)
        defects += found

    carried: list[str] = []
    order = [_page_slug(p) for p in pages]
    for slug, (kept_scores, kept_weighted, kept_defects, kept_raw) in kept.items():
        if slug not in order:
            continue  # no longer rendered
        carried.append(slug)
        page_scores[slug], page_weighted[slug] = kept_scores, kept_weighted
        raw["pages"][slug] = kept_raw
        defects += kept_defects
        if slug in ((carry or {}).get("double_judged") or []):
            double_judged.append(slug)
    page_scores = {s: page_scores[s] for s in order if s in page_scores}
    page_weighted = {s: page_weighted[s] for s in order if s in page_weighted}

    cross_scores: dict[str, float] = {}
    if thumbs:
        shown = thumbs[:MAX_CROSS_PAGES]
        cross_context = base_context | {
            "pages": [{"image": i + 1, "page": s} for i, (s, _) in enumerate(shown)]
                     + [{"image": len(shown) + i + 1, "shows": f"reference {i + 1}"}
                        for i in range(len(ref_images))],
        }
        cross_images = [b for _, b in shown] + ref_images

        async def cross_call() -> dict[str, Any]:
            return await _call(provider, cross_context, cross_images, CROSS_SCHEMA, CROSS_PROMPT, model,
                               timeout_seconds)

        def cross_parse(answer: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
            return (parse_scores(answer, CROSS_DIMENSIONS),
                    parse_defects(answer, page=None, desktop_vp="xl", round_no=round_no,
                                  known_pages=known, prefix="site"))

        def cross_near(scores: dict[str, float]) -> bool:
            return any(abs(v - DIMENSION_FLOOR) <= DOUBLE_JUDGE_MARGIN for v in scores.values())

        try:
            cross_scores, found, raws, twice = await _judged_twice_if_close(cross_call, cross_parse,
                                                                             cross_near)
            raw["cross"] = raws
            defects += found
            if twice:
                double_judged.append("*")
            missing = [d for d in CROSS_DIMENSIONS if d not in cross_scores]
            if missing:
                errors.append(f"site: no score for {', '.join(missing)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"site: cross-page vision call failed ({type(exc).__name__}: {str(exc)[:160]})")
    elif pages:
        errors.append("site: no desktop screenshot to judge consistency and originality")
    if not pages:
        errors.append("render.json lists no pages")

    scores_out: dict[str, float] = {}
    for d in PAGE_DIMENSIONS:
        values = [s[d] for s in page_scores.values() if d in s]
        if values:
            scores_out[d] = round(sum(values) / len(values), 2)
    scores_out |= cross_scores
    scores_out = {d: scores_out[d] for d in DIMENSIONS if d in scores_out}

    defects += render_defects(render, round_no)
    similar = similar_to if similar_to is not None else manifest.get("similar_to")
    defects += similarity_defects(similar if isinstance(similar, list) else None, round_no)
    defects.sort(key=lambda d: SEVERITIES.index(d["severity"]))
    critique: dict[str, Any] = {
        "version": CRITIC_VERSION,
        "site_key": str(manifest.get("site_key") or site_dir.name),
        "business": business, "category": category, "round": round_no,
        "model": model or getattr(provider, "model_name", None),
        "scores": scores_out, "weighted_score": round(weighted_score(scores_out), 2),
        "page_scores": page_scores, "page_weighted": page_weighted,
        "defects": defects,
        "complete": not errors and len(scores_out) == len(DIMENSIONS),
        "errors": errors,
        "double_judged": double_judged,
        "carried": carried,
        "references": {"ids": list(ref_ids), "images": len(ref_images)},
        "raw": raw,
    }
    if write:
        text = json.dumps(critique, ensure_ascii=False, indent=1)
        (site_dir / "critique.json").write_text(text, encoding="utf-8")
        (site_dir / f"critique.r{round_no}.json").write_text(text, encoding="utf-8")
    return critique
