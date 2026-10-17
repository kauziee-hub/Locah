"""Website fixtures: 24 businesses, their interviews, their first websites — zero AI.

Each owner's conversation runs through the real interview (scripted model
readings, see interview_personas / website_personas); the website is composed
exactly as "Build my website" composes it — creative direction, composition,
semantic validation — with no model and no image generation. What comes out:

* the payload (what would be stored as the draft),
* its design signature (distinctness),
* its semantic findings,
* a site-lab file per page (the public renderer's input) for screenshots:
  ``<key>.json`` is the home page, ``<key>~<slug>.json`` each inner page.

    uv run python -m platform_testing.website_fixtures <out_dir> [--images]

``--images`` composes as a deployment with an image provider does: pictures
are expected before the design is chosen, the media plan is made, and every
drawable slot is filled with a synthetic placeholder (an SVG gradient in the
site's palette, visibly not a photograph) so compositions can be judged
without paying for, or pretending to have, real Gemini pictures.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platform_core.interview.capabilities import resolve_recommendations
from platform_core.interview.creative_director import direct
from platform_core.interview.distinctness import Report, report, signature
from platform_core.interview.models import BusinessBlueprint
from platform_core.interview.site_composer import compose_site
from platform_core.interview.website import with_draft
from platform_testing.interview_eval import Persona, every_module_entitled, run_persona
from platform_testing.interview_personas import PERSONAS
from platform_testing.website_personas import WEBSITE_PERSONAS

# Every distinct business, once (the interview's talk-first variants are the
# same businesses).
FIXTURE_PERSONAS: list[Persona] = [p for p in PERSONAS if p.key != "wift-app"] + WEBSITE_PERSONAS


@dataclass
class SiteFixture:
    key: str
    name: str
    business: str
    bp: BusinessBlueprint
    payload: dict[str, Any]
    signature: dict[str, str]
    dimensions: dict[str, Any]


def contact_for(bp: BusinessBlueprint) -> dict[str, str]:
    from platform_core.services.business_interview import public_contact

    return {k: str(v) for k, v in public_contact(bp).items() if isinstance(v, str)}


def compose(bp: BusinessBlueprint, business_type: str, *, images: bool = False) -> dict[str, Any]:
    """The first website, as the build composes it — deterministic, no model."""
    from uuid import uuid4

    from platform_core.interview.media_director import plan_media, plan_slots, record

    resolve_recommendations(bp, every_module_entitled(), business_type)
    active = frozenset(m.module_id for m in bp.recommended_modules if m.strength == "strong")
    direction = direct(bp, business_type, media_expected=images)
    plan_media(bp, direction)
    if images:
        for slot in plan_slots(bp, direction):
            if slot.truth_class != "factual":
                record(bp, slot, uuid4())
    return dict(compose_site(
        bp, direction, with_draft(bp, None), business_type=business_type, contact=contact_for(bp),
        active_modules=active, meta={"stage": "immediate", "creative_strategy": "deterministic",
                                     "fallback_used": False},
    ))


async def build(p: Persona, *, images: bool = False) -> SiteFixture:
    run = await run_persona(p, "model")
    payload = compose(run.bp, p.business_type, images=images)
    theme = payload["theme_hints"]
    dims = dict((theme.get("creative_direction") or {}).get("dimensions") or {})
    return SiteFixture(p.key, p.name, p.business, run.bp, payload, signature(payload), dims)


async def build_all(personas: list[Persona] | None = None, *, images: bool = False) -> list[SiteFixture]:
    return [await build(p, images=images) for p in (personas or FIXTURE_PERSONAS)]


def distinctness(fixtures: list[SiteFixture]) -> Report:
    return report({f.key: (f.signature, f.dimensions) for f in fixtures})


def _placeholder(asset_id: str, theme: dict[str, Any], label: str) -> dict[str, str]:
    """A synthetic stand-in picture: a gradient in the site's palette. Not a photo."""
    from urllib.parse import quote

    a = str(theme.get("primary_color") or "#555555")
    b = str(theme.get("accent_color") or "#999999")
    c = str(theme.get("surface_alt_color") or "#dddddd")
    angle = int(asset_id.replace("-", "")[:2], 16) % 90
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='900' viewBox='0 0 1200 900'>"
           f"<defs><linearGradient id='g' gradientTransform='rotate({angle})'><stop offset='0' stop-color='{c}'/>"
           f"<stop offset='.55' stop-color='{a}'/><stop offset='1' stop-color='{b}'/></linearGradient></defs>"
           f"<rect width='1200' height='900' fill='url(#g)'/><circle cx='800' cy='420' r='260' fill='{b}' "
           f"opacity='.35'/></svg>")
    return {"url": "data:image/svg+xml;utf8," + quote(svg), "alt_text": f"Placeholder · {label}"}


def _lab_assets(content: dict[str, Any], theme: dict[str, Any],
                pictures: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Each picture a section names: a real one from ``pictures`` (asset id →
    {url, alt_text}) where the lab was given one, else a placeholder."""
    def picture(asset_id: str, label: str) -> dict[str, Any]:
        return (pictures or {}).get(asset_id) or _placeholder(asset_id, theme, label)

    assets: dict[str, dict[str, Any]] = {}
    if content.get("image_asset_id"):
        assets["image_asset_id"] = picture(str(content["image_asset_id"]), "picture")
    for key in ("items", "categories"):
        for i, row in enumerate(content.get(key) or []):
            if isinstance(row, dict) and row.get("image_asset_id"):
                assets[f"{key}.{i}"] = picture(str(row["image_asset_id"]), str(row.get("name") or row.get("title", "")))
    return assets


def lab_payload(f: SiteFixture, page_index: int = 0,
                pictures: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The public renderer's input (PublicWebsitePayload) for one page, for the site lab."""
    page = f.payload["pages"][page_index]
    theme = f.payload.get("theme_hints", {})
    contact = contact_for(f.bp)
    return {
        "business": {"id": str(f.bp.business_id), "slug": f.key, "display_name": f.name,
                     "business_type": None, "contact": contact},
        "capabilities": {},
        "website": {"status": "draft"},
        "page": {
            "title": page.get("title", "Home"), "slug": page.get("slug", "home"), "seo_title": page.get("seo_title"),
            "seo_description": page.get("seo_description"),
            "sections": [{"id": f"{f.key}-{page_index}-{i}", "section_type_id": s["section_type_id"],
                          "layout_variant": s.get("layout_variant"), "content": s.get("content", {}),
                          "assets": _lab_assets(s.get("content", {}), theme, pictures),
                          "is_visible": s.get("is_visible", True)}
                         for i, s in enumerate(page["sections"])],
        },
        "navigation": f.payload.get("navigation", []),
        "theme": f.payload.get("theme_hints", {}),
        "is_preview": False,
        "fixture": {"business": f.business, "signature": f.signature,
                    "semantic": f.payload["theme_hints"]["quality"].get("semantic", []),
                    "reasons": (f.payload["theme_hints"].get("creative_direction") or {}).get("reasons", [])},
    }


def write_lab(root: Path, f: SiteFixture, pictures: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Every page of a fixture as site-lab files; returns the page slugs."""
    slugs = []
    for i, page in enumerate(f.payload["pages"]):
        name = f.key if i == 0 else f"{f.key}~{page['slug']}"
        (root / f"{name}.json").write_text(json.dumps(lab_payload(f, i, pictures), ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        slugs.append(str(page["slug"]))
    return slugs


def main(out: str, images: bool = False) -> None:  # pragma: no cover — a tool
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    fixtures = asyncio.run(build_all(images=images))
    index = []
    for f in fixtures:
        pages = write_lab(root, f)
        index.append({"key": f.key, "name": f.name, "business": f.business, "pages": pages, **f.signature})
    rep = distinctness(fixtures)
    (root / "index.json").write_text(json.dumps({"sites": index, "distinctness": {
        "ok": rep.ok, "families": rep.families, "palettes": rep.palettes, "clusters": rep.clusters,
        "identical": rep.identical}}, indent=1), encoding="utf-8")
    for row in index:
        print(f"{row['key']:22} {row['family']:22} {row['variant']:14} {row['hero']:16} {row['palette']}")
    print("distinct:", rep.ok, rep.clusters, rep.identical)


if __name__ == "__main__":  # pragma: no cover
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "site-lab", images="--images" in sys.argv)
