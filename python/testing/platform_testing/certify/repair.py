"""The repair loop: one targeted fix per defect, kept only when the page gets better.

    uv run python -m platform_testing.certify.repair <run_dir> <site_key> [--rounds 2] [--per-round 3]

Reads the site's critique, attributes each critical/major defect to a section
of the draft (the critic's own index when it gave one, else the section whose
title the defect quotes, else the kind of section it names — "the FAQ", "the
hero"), and applies the lever for the defect's LAYER, through the Workspace
API, on that section only:

  photo                 "change this image" (a new photograph for that slot)
  composition, styling  the section's next allowed layout variant
  copy                  that section written anew (the scoped regeneration)
  order (repeats)       the repeated section hidden

input and architecture defects have no automatic lever: they are the owner's
requests or a product change, and stay in the report. After each fix the
page is published, rendered (laptop + phone) and critiqued alone; the fix is
kept only if the page's weighted score rises by at least KEEP_MARGIN and no
new critical defect appears — otherwise it is reverted. The critic's own
run-to-run variance is why a fix must clear a margin, not merely tie.

Writes repair.json beside the critique: every attempt with its defect, lever,
the page score before and after, and whether it was kept.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from platform_testing.certify.edits import Site, _data, _sections
from platform_testing.certify.setup import Setup, Workspace, owner_token

KEEP_MARGIN = 0.25
LEVERS = {"photo": "new_photo", "composition": "variant", "styling": "variant", "copy": "rewrite", "order": "hide"}
# What a critic calls each kind of section.
KIND_WORDS: dict[str, tuple[str, ...]] = {
    "hero": ("hero", "headline", "first screen", "above the fold", "opening"),
    "statement": ("statement", "manifesto", "big line", "oversized line"),
    "product_showcase": ("menu", "services", "price list", "items", "dishes", "catalog", "range", "treatments",
                         "products", "cards"),
    "category_showcase": ("categories", "category"),
    "faq": ("faq", "questions"),
    "contact": ("map", "find us", "address", "contact block", "directions", "visit block"),
    "pillars": ("pillars", "stands on", "icon cards", "four-up"),
    "fulfilment_strip": ("good to know", "how ordering", "how a visit", "how booking", "pickup"),
    "feature_grid": ("how it works", "steps"),
    "media_text": ("story", "alternating", "split section"),
    "about": ("our story", "about"),
    "cta_band": ("closing", "cta band", "call-to-action band", "final call"),
    "marquee": ("marquee", "word band", "category band"),
    "highlights": ("numbers", "counters", "stats"),
    "gallery": ("gallery",),
}


def attribute(defect: dict[str, Any], page: dict[str, Any]) -> dict[str, Any] | None:
    """The draft section a defect is about, or None when it cannot be told."""
    sections: list[dict[str, Any]] = [s for s in _sections(page) if s.get("is_visible", True)]
    index = defect.get("section")
    if isinstance(index, int) and 0 <= index < len(sections):
        return sections[index]
    text = str(defect.get("text") or "").casefold()
    found: dict[str, Any]
    for found in sections:  # a quoted title names its section
        content = found.get("content") or {}
        for key in ("title", "headline", "eyebrow"):
            title = str(content.get(key) or "").strip().casefold()
            if len(title) >= 6 and title in text:
                return found
    # The kind of section the defect names first ("The statement repeats the
    # hero" is about the statement).
    best: tuple[int, dict[str, Any]] | None = None
    for found in sections:
        for word in KIND_WORDS.get(str(found.get("section_type_id")), ()):
            hit = re.search(rf"\b{re.escape(word)}\b", text)
            if hit and (best is None or hit.start() < best[0]):
                best = (hit.start(), found)
    return best[1] if best else None


def plan(critique: dict[str, Any], draft: dict[str, Any], limit: int, tried: set[str]) -> list[dict[str, Any]]:
    """The fixes to try this round: worst defects first, one per section."""
    pages = {str(p.get("slug")): p for p in draft.get("pages") or []}
    order = {"critical": 0, "major": 1}
    chosen: list[dict[str, Any]] = []
    taken: set[str] = set()
    for defect in sorted(critique.get("defects") or [], key=lambda d: order.get(str(d.get("severity")), 9)):
        lever = LEVERS.get(str(defect.get("layer")))
        if defect.get("severity") not in order or not lever or defect.get("source") not in {None, "vision"}:
            continue
        if lever == "hide" and not re.search(r"\b(repeat|twice|duplicate|again|same)\w*\b", str(defect.get("text")), re.I):
            continue
        page = pages.get(str(defect.get("page")))
        section = attribute(defect, page) if page else None
        if not section or not section.get("id"):
            continue
        key = f"{section['id']}:{lever}"
        if section["id"] in taken or key in tried:
            continue
        if lever == "new_photo" and not (section.get("content") or {}).get("image_asset_id"):
            continue
        taken.add(section["id"])
        chosen.append({"defect": defect, "page": defect["page"], "section": section, "lever": lever, "key": key})
        if len(chosen) >= limit:
            break
    return chosen


async def variants_by_type(ws: Workspace, b: str) -> dict[str, list[str]]:
    _, body = await ws.call("GET", f"/v1/b/{b}/website/section-types", expect=False)
    types = ((_data(body) or {}).get("section_types") or []) if isinstance(body, dict) else []
    return {str(t.get("id")): [str(v) for v in t.get("allowed_variants") or []] for t in types if isinstance(t, dict)}


async def score_page(folder: Path, journey: dict[str, Any], page: str, tag: str, category: str) -> dict[str, Any]:
    """Render one page (laptop + phone) and critique it alone."""
    from platform_core.website.ai_provider import get_ai_provider
    from platform_testing.certify.critic import critique_site
    from platform_testing.certify.run import _node

    out = folder / f"repair-{tag}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(folder / "journey.json", out / "journey.json")
    url = str(journey.get("public_url") or "")
    _node("tools/certify/render.mjs", str(out), url, "--pages", page, "--only", "--viewports", "laptop,mobile",
          "--no-axe", "--no-links", timeout=900)
    if not (out / "render.json").exists():
        return {"score": None, "critical": None}
    critique = await critique_site(get_ai_provider(), out, {"journey": journey, "draft": {}}, category=category,
                                   round_no=1)
    score = (critique.get("page_weighted") or {}).get(page)
    critical = sum(1 for d in critique.get("defects") or [] if d.get("severity") == "critical" and d.get("page") == page)
    return {"score": score, "critical": critical}


async def apply(fix: dict[str, Any], site: Site, ws: Workspace, b: str, variants: dict[str, list[str]]) -> dict[str, Any]:
    """Apply one fix; return what reverting it needs (or {'skipped': why})."""
    section = fix["section"]
    sid, kind = section["id"], str(section.get("section_type_id"))
    path = f"/v1/b/{b}/website/sections/{sid}"
    before = {"content": section.get("content") or {}, "layout_variant": section.get("layout_variant"),
              "is_visible": section.get("is_visible", True)}
    lever = fix["lever"]
    if lever == "variant":
        options = [v for v in variants.get(kind, []) if v != section.get("layout_variant")]
        if not options:
            return {"skipped": "no other layout for this section"}
        status, _ = await ws.call("PATCH", path, {"layout_variant": options[0]})
        fix["change"] = f"{section.get('layout_variant')} → {options[0]}"
    elif lever == "hide":
        status, _ = await ws.call("PATCH", path, {"is_visible": False})
        fix["change"] = "hidden"
    elif lever == "new_photo":
        status, body = await ws.call("POST", f"{path}/generate-image", {}, expect=False)
        result = _data(body) or {}
        if status >= 400 or not result.get("ok"):
            return {"skipped": f"no new photograph: {result.get('reason') or status}"}
        fix["change"] = "new photograph"
    else:  # rewrite
        started = time.monotonic()
        status, _ = await ws.call("POST", f"{path}/regenerate", expect=False)
        job = await site.wait_job(started) if status < 400 else {}
        if job.get("status") not in {"completed", "fallback_used"}:
            return {"skipped": f"rewrite did not finish: {job.get('status') or status}"}
        fix["change"] = "written anew"
    if status >= 400:
        return {"skipped": f"the change was refused ({status})"}
    await site.publish()
    return {"before": before, "kind": kind, "page": fix["page"]}


async def revert(undo: dict[str, Any], fix: dict[str, Any], site: Site, ws: Workspace, b: str) -> None:
    """Put the section back as it was (found again by kind on its page after a rewrite)."""
    sid = fix["section"]["id"]
    if fix["lever"] == "rewrite":
        page: dict[str, Any] = next(
            (p for p in (await site.draft()).get("pages") or [] if p.get("slug") == undo["page"]), {})
        same = [s for s in _sections(page) if s.get("section_type_id") == undo["kind"]]
        sid = same[0]["id"] if same else sid
    await ws.call("PATCH", f"/v1/b/{b}/website/sections/{sid}", undo["before"], expect=False)
    await site.publish()


async def run(run_dir: Path, site_key: str, *, rounds: int = 2, per_round: int = 3) -> dict[str, Any]:
    from platform_testing.certify.owners import DISTINCT, SCENARIOS

    folder = run_dir / "sites" / site_key
    journey = json.loads((folder / "journey.json").read_text(encoding="utf-8"))
    critique = json.loads((folder / "critique.json").read_text(encoding="utf-8"))
    scenario = SCENARIOS.get(journey["scenario"]) or next(
        s for group in DISTINCT.values() for s in group if s.key == journey["scenario"])
    category = scenario.kind or scenario.category_key
    ws = Workspace(owner_token(journey["owner_id"], journey["owner_email"]), Setup(site_key))
    b = str(journey["business_id"])
    site = Site(ws, b, str(journey["slug"]))
    report: dict[str, Any] = {"site_key": site_key, "attempts": [], "page_before": critique.get("page_weighted"),
                              "rounds": 0}
    page_scores: dict[str, float] = {k: float(v) for k, v in (critique.get("page_weighted") or {}).items()}
    tried: set[str] = set()
    try:
        variants = await variants_by_type(ws, b)
        for round_no in range(1, rounds + 1):
            fixes = plan(critique, await site.draft(), per_round, tried)
            if not fixes:
                break
            report["rounds"] = round_no
            for n, fix in enumerate(fixes):
                tried.add(fix["key"])
                attempt = {"round": round_no, "page": fix["page"], "lever": fix["lever"],
                           "section": fix["section"].get("section_type_id"),
                           "defect": f"{fix['defect'].get('severity')}/{fix['defect'].get('layer')}: "
                                     f"{str(fix['defect'].get('text'))[:200]}"}
                undo = await apply(fix, site, ws, b, variants)
                if "skipped" in undo:
                    attempt.update(kept=False, why=undo["skipped"])
                    report["attempts"].append(attempt)
                    continue
                before = page_scores.get(fix["page"])
                after = await score_page(folder, journey, fix["page"], f"r{round_no}-{n}", category)
                better = (after["score"] is not None and before is not None
                          and after["score"] >= before + KEEP_MARGIN and not after["critical"])
                attempt.update(change=fix.get("change"), before=before, after=after["score"],
                               critical_after=after["critical"], kept=better)
                if better:
                    page_scores[fix["page"]] = float(after["score"])
                else:
                    await revert(undo, fix, site, ws, b)
                report["attempts"].append(attempt)
        report["page_after"] = page_scores
    finally:
        await site.close()
        await ws.close()
        (folder / "repair.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    flags = sys.argv[3:]
    rounds = int(flags[flags.index("--rounds") + 1]) if "--rounds" in flags else 2
    per = int(flags[flags.index("--per-round") + 1]) if "--per-round" in flags else 3
    out = asyncio.run(run(Path(sys.argv[1]), sys.argv[2], rounds=rounds, per_round=per))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps(out, indent=1, ensure_ascii=False))
