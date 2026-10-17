"""The site seen, not just read: a vision critic for the polish loop.

site_critic.py reads the composed payload. Some faults only show once a site is
rendered — a hero that looks like every other, a weak type hierarchy, a crop
that cuts a face, a phone layout that turns to mush. This module hands
screenshots of the rendered site to a vision-capable model (through the
provider's own `generate_structured_with_images`; the provider set-up is not
touched) with an art director's rubric, and turns its answer into the same
`Finding` shape the polish loop already fixes:

    render → screenshot (desktop + phone) → critique → revise → render again

What the model may change is narrow, by design: a layout among the ones the
renderer has, the order of sections, a picture dropped where it hurts. It never
writes a word or a fact — the copy is governed elsewhere — and a finding it
cannot act on (hierarchy, spacing) is recorded for the design system instead.

Rendering is the caller's: a `Shot` is a PNG with what it shows (page, viewport,
which sections). platform_testing/site_vision_loop.py renders the site lab with
headless Chrome; production can hand in the same shots from any renderer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from platform_core.interview.site_critic import Finding

CRITIC_VERSION = "vision-critic-v1"

# What the critic may say. The first group the polish loop can act on.
FIXABLE = ("generic_hero", "excessive_cards", "repetitive_layout", "underdesigned_range", "poor_image",
           "thin_section")
RECORDED = ("weak_hierarchy", "awkward_spacing", "bland_mobile", "ai_generated_feel", "weak_contrast")
CODES = FIXABLE + RECORDED

PROMPT = """You are the art director of a premium web studio reviewing a website your team built for a real
small business, before the client sees it. The bar: a site that looks custom-designed and expensive — a strong
type hierarchy, purposeful whitespace, image-led composition, varied section rhythm, no generic template feel.

You are shown screenshots. The manifest says, for each one, the page, the viewport (desktop or phone) and which
sections (by index and type) it shows. Judge only what you can see. For every real problem return one finding:
- code: one of %s
  generic_hero — the opening looks like any template; excessive_cards — grids of boxes one after another;
  repetitive_layout — a section repeats the layout of a nearby one; underdesigned_range — the menu/shop/services
  page reads as a plain list; poor_image — a picture is low quality, badly cropped or wrong for the business;
  thin_section — a section has too little in it to earn its space; weak_hierarchy, awkward_spacing,
  bland_mobile, ai_generated_feel, weak_contrast — say so, they are recorded for the design system.
- page and section: the page slug and the section index from the manifest.
- severity: high (a client would object), medium, low.
- note: one short sentence a designer would act on.
Do not ask for new text, facts, reviews or numbers: the words are the business owner's. Score the site 1-10 on
hierarchy, imagery, rhythm, distinctness and mobile. Return at most 12 findings, the most important first."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scores", "findings"],
    "properties": {
        "scores": {"type": "object", "properties": {k: {"type": "integer", "minimum": 1, "maximum": 10} for k in (
            "hierarchy", "imagery", "rhythm", "distinctness", "mobile")}},
        "findings": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "required": ["code", "page", "section", "severity", "note"],
            "properties": {
                "code": {"type": "string", "enum": list(CODES)},
                "page": {"type": "string", "maxLength": 40},
                "section": {"type": "integer", "minimum": -1, "maximum": 40},
                "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                "note": {"type": "string", "maxLength": 240},
            }}},
    },
}


@dataclass(frozen=True)
class Shot:
    """One screenshot of the rendered site and what it shows."""

    png: bytes
    page: str
    viewport: str  # "desktop" | "phone"
    sections: tuple[tuple[int, str], ...] = ()  # (index, section type) visible in it


@dataclass
class Review:
    scores: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    raw: list[dict[str, Any]] = field(default_factory=list)


class VisionProvider(Protocol):
    async def generate_structured_with_images(
        self, prompt: str, images: list[Any], schema: dict[str, Any], model_config: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


def manifest(shots: list[Shot]) -> list[dict[str, Any]]:
    return [{"screenshot": i + 1, "page": s.page, "viewport": s.viewport,
             "sections": [{"index": n, "type": t} for n, t in s.sections]} for i, s in enumerate(shots)]


def to_findings(raw: list[dict[str, Any]], payload: dict[str, Any]) -> list[Finding]:
    """The model's findings, held to what exists: a page and section it names
    must be on the site, and only the codes the loop knows are kept."""
    pages = {str(p["slug"]): p for p in payload["pages"]}
    out: list[Finding] = []
    for row in raw:
        code, page = str(row.get("code") or ""), str(row.get("page") or "")
        if code not in CODES or page not in pages:
            continue
        try:
            index = int(row.get("section", -1))
        except (TypeError, ValueError):
            continue
        sections = pages[page]["sections"]
        where = str(sections[index]["section_type_id"]) if 0 <= index < len(sections) else "page"
        out.append(Finding(f"vision:{code}", page, f"{where}#{index}" if where != "page" else "page",
                           str(row.get("note") or "")[:240], code in FIXABLE and where != "page"
                           or code == "underdesigned_range"))
    return out


async def critique(provider: VisionProvider, shots: list[Shot], payload: dict[str, Any], *,
                   model: str | None = None, timeout_seconds: int = 90) -> Review:
    """One vision call over the screenshots; findings the loop can use."""
    from platform_core.website.ai_provider import ImageInput

    config: dict[str, Any] = {"purpose": "website.critique", "system_prompt": PROMPT % ", ".join(CODES),
                              "max_output_tokens": 2500, "temperature": 0.2}
    if model:
        config["model"] = model
    context = {"business": (payload.get("theme_hints") or {}).get("site_archetype", ""),
               "art_direction": ((payload.get("theme_hints") or {}).get("dna") or {}).get("concept", ""),
               "manifest": manifest(shots)}
    raw = await provider.generate_structured_with_images(
        json.dumps(context, separators=(",", ":"), ensure_ascii=False),
        [ImageInput(data=s.png, mime_type="image/png") for s in shots], SCHEMA, config, timeout_seconds)
    rows = [r for r in (raw.get("findings") or []) if isinstance(r, dict)] if isinstance(raw, dict) else []
    scores = {k: int(v) for k, v in ((raw or {}).get("scores") or {}).items()
              if isinstance(v, (int, float)) and 1 <= int(v) <= 10} if isinstance(raw, dict) else {}
    return Review(scores=scores, findings=to_findings(rows, payload), raw=rows)


# ------------------------------------------------------------------ revising

# Another layout for a section the critic calls repetitive or too boxy, among
# the ones the renderer has — never one the content cannot carry.
_ALTERNATIVE = {
    "pillars": ("numbered", "strip", "cards"),
    "product_showcase": ("spotlight", "bento", "chapters", "commerce_grid"),
    "category_showcase": ("bento", "image_cards", "tiles"),
    "faq": ("split", "accordion"),
    "media_text": ("alternating", "sticky"),
    "statement": ("giant", "image", "split"),
    "fulfilment_strip": ("steps", "icons"),
    "cta_band": ("giant", "centered"),
}
_HEROES = ("arch", "window", "gallery", "stage", "cinematic_zoom", "depth", "plane", "orbit", "kinetic", "aurora")


def _pictures(section: dict[str, Any]) -> int:
    content = section.get("content") or {}
    return int(bool(content.get("image_asset_id"))) + sum(
        1 for key in ("items", "categories") for r in content.get(key) or []
        if isinstance(r, dict) and r.get("image_asset_id"))


def revise(payload: dict[str, Any], findings: list[Finding],
           tried: set[tuple[str, int, str]] | None = None) -> list[str]:
    """Act on what the critic saw, within the renderer's layouts. Returns notes.

    ``tried`` (page, section, layout) carries across rounds: a section never
    goes back to a layout it has already had, so the loop cannot flip-flop."""
    tried = tried if tried is not None else set()
    budget = str(((payload.get("theme_hints") or {}).get("dna") or {}).get("budget") or "gentle")
    pages = {str(p["slug"]): p for p in payload["pages"]}
    done: list[str] = []
    for f in findings:
        if not f.fixable or not f.code.startswith("vision:"):
            continue
        code = f.code.split(":", 1)[1]
        page = pages[f.page]
        if code == "underdesigned_range":
            showcase = next((s for s in page["sections"] if s["section_type_id"] == "product_showcase"), None)
            if showcase:
                kinds = [c for c in showcase["content"].get("categories") or [] if c.get("image_asset_id")]
                before = showcase["layout_variant"]
                after = "chapters" if len(kinds) >= 2 else "menu_book"
                if before != after:
                    showcase["layout_variant"] = after
                    done.append(f"{f.page}: range {before} → {after}")
            continue
        try:
            index = int(f.where.rsplit("#", 1)[1])
            section = page["sections"][index]
        except (IndexError, ValueError):
            continue
        kind, before = str(section["section_type_id"]), str(section.get("layout_variant") or "")
        tried.add((f.page, index, before))
        if code == "generic_hero" and kind == "hero" and f.page == "home":
            has = bool(section["content"].get("image_asset_id"))
            options = [h for h in _HEROES if (has or h == "aurora") and (f.page, index, h) not in tried
                       and not (budget == "restrained" and h in {"plane", "orbit", "kinetic"})]
            if options:
                section["layout_variant"] = options[0]
                done.append(f"home: hero {before} → {options[0]}")
        elif code in {"excessive_cards", "repetitive_layout"} and kind in _ALTERNATIVE:
            options = [v for v in _ALTERNATIVE[kind] if (f.page, index, v) not in tried]
            if kind == "statement":
                options = [v for v in options if v == "giant" or section["content"].get("image_asset_id")]
            if kind == "product_showcase" and f.page == "home":
                options = [v for v in options if v != "chapters"]
            if options:
                section["layout_variant"] = options[0]
                done.append(f"{f.page}: {kind} {before} → {options[0]}")
        elif code == "poor_image" and kind in {"statement", "cta_band", "media_text", "pillars"}:
            content = section["content"]
            if kind == "media_text":
                for row in content.get("items") or []:
                    row.pop("image_asset_id", None)
            else:
                content.pop("image_asset_id", None)
                if kind == "statement":
                    section["layout_variant"] = "giant"
                if kind == "cta_band":
                    section["layout_variant"] = "centered"
            done.append(f"{f.page}: {kind} picture dropped")
        elif code == "thin_section" and kind in {"marquee", "highlights"} and _pictures(section) == 0:
            section["_drop"] = True
            done.append(f"{f.page}: {kind} removed")
    for page in payload["pages"]:
        page["sections"] = [s for s in page["sections"] if not s.pop("_drop", False)]
    return done
