"""The repair loop: one targeted fix per defect, kept only when the page gets better.

    uv run python -m platform_testing.certify.repair <run_dir> <site_key> [--rounds 2] [--per-round 3]
                                                     [--no-photos]

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
page is published, the public renderer's cache for the site dropped, the page
rendered (xl + phone, the viewports the full critique judges) and critiqued
alone; the fix is kept only if the page's weighted score rises by at least
KEEP_MARGIN and no new critical defect appears — otherwise it is reverted.
The critic's own run-to-run variance is why a fix must clear a margin, not
merely tie.

`until_verdict` is the bounded loop the certification run drives
(`run.py --repair`): critique → verdict; while the verdict is `repair`, one
round of fixes, the touched pages rendered again at every viewport, the site
critiqued again (untouched pages keep their judgment), the verdict again —
ending in a pass, a fail-closed verdict after the last round, or an early
fail-closed verdict when a round finds nothing left to try. The verdict's
owner requests are what the owner is asked for.

This command alone runs the fix rounds against one critique (no re-critique
between rounds) and writes repair.json beside it: every attempt with its
defect, lever, the page score before and after, and whether it was kept.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Collection, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from platform_testing.certify.edits import Site, _data, _sections
from platform_testing.certify.gate import decide
from platform_testing.certify.setup import Setup, Workspace, owner_token

KEEP_MARGIN = 0.25
LEVERS = {"photo": "new_photo", "composition": "variant", "styling": "variant", "copy": "rewrite", "order": "hide"}
ALL_LEVERS = frozenset(LEVERS.values())
# The levers that spend photo quota: a new photograph, and a rewrite — a scoped
# regeneration runs the build's photo search for every empty slot of the site
# (BusinessInterviewService._personalize_creative → retrieve_missing), not just its own.
PHOTO_QUOTA_LEVERS = frozenset({"new_photo", "rewrite"})
# The viewports a single page is judged on after a fix: the full critique
# judges the desktop on xl (when rendered) and the phone on mobile.
SCORE_VIEWPORTS = "xl,mobile"
UNNUMBERED_CRITICS = frozenset({"certify-critic-v1"})
# Sections that carry the page's job (what the business sells, how to reach
# it): a defect about them is fixed in place, never by hiding them.
NEVER_HIDE = frozenset({"hero", "product_showcase", "category_showcase", "contact"})
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
    # Not the bare word: "nothing about beds" is not the About section.
    "about": ("our story", "about section", "about block", "about us"),
    "cta_band": ("closing", "cta band", "call-to-action band", "final call"),
    "marquee": ("marquee", "word band", "category band"),
    "highlights": ("numbers", "counters", "stats"),
    "gallery": ("gallery",),
}


def attribute(defect: dict[str, Any], page: dict[str, Any], *, by_index: bool = True) -> dict[str, Any] | None:
    """The draft section a defect is about, or None when it cannot be told.
    ``by_index``: the critic was shown the numbered sections (critic v2+)."""
    sections: list[dict[str, Any]] = [s for s in _sections(page) if s.get("is_visible", True)]
    index = defect.get("section")
    if by_index and isinstance(index, int) and 0 <= index < len(sections):
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


def plan(critique: dict[str, Any], draft: dict[str, Any], limit: int, tried: set[str],
         levers: Collection[str] = ALL_LEVERS) -> list[dict[str, Any]]:
    """The fixes to try this round: worst defects first, one per section."""
    pages = {str(p.get("slug")): p for p in draft.get("pages") or []}
    order = {"critical": 0, "major": 1}
    # A v1 critic was never shown the section list: its section numbers are guesses.
    by_index = critique.get("version") not in UNNUMBERED_CRITICS
    chosen: list[dict[str, Any]] = []
    taken: set[str] = set()
    for defect in sorted(critique.get("defects") or [], key=lambda d: order.get(str(d.get("severity")), 9)):
        lever = LEVERS.get(str(defect.get("layer")))
        if defect.get("severity") not in order or not lever or defect.get("source") not in {None, "vision"}:
            continue
        if lever not in levers:
            continue
        if lever == "hide" and not re.search(r"\b(repeat|twice|duplicate|again|same)\w*\b", str(defect.get("text")), re.I):
            continue
        page = pages.get(str(defect.get("page")))
        section = attribute(defect, page, by_index=by_index) if page else None
        if not section or not section.get("id"):
            continue
        if lever == "hide" and str(section.get("section_type_id")) in NEVER_HIDE:
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


# ----------------------------------------------------------------- the bounded loop

FixRound = Callable[[dict[str, Any], int], Awaitable[list[dict[str, Any]]]]
Rejudge = Callable[[dict[str, Any], set[str], int], Awaitable[dict[str, Any]]]


async def until_verdict(critique: dict[str, Any], *, fix_round: FixRound, rejudge: Rejudge,
                        max_rounds: int = 3) -> dict[str, Any]:
    """Critique → verdict, then while the verdict is `repair`: one round of fixes
    (``fix_round(critique, round_no)`` → its attempts, each kept or reverted),
    the pages a kept fix touched rendered and judged again (``rejudge(critique,
    pages, round_no)`` → the new critique), the verdict again.

    Round 1 is the first critique; rounds 2..max_rounds repair. A round that
    finds nothing to try ends the loop with a final verdict (fail closed unless
    the site already passes) and the rounds actually used; a round whose fixes
    were all reverted leaves the critique as it was and the next round tries
    the next defects. Returns {verdict, critique, rounds[], rounds_used}."""
    rounds: list[dict[str, Any]] = []
    round_no = 1
    verdict = decide(critique, rounds_used=round_no, max_rounds=max_rounds)
    while verdict["status"] == "repair":
        round_no += 1
        attempts = await fix_round(critique, round_no)
        kept = [a for a in attempts if a.get("kept")]
        touched = sorted({str(a["page"]) for a in kept})
        row: dict[str, Any] = {"round": round_no, "score_before": critique.get("weighted_score"),
                               "attempts": len(attempts), "kept": len(kept), "touched": touched}
        if not attempts:
            row["stopped"] = "no automatic repair left"
            rounds.append(row)
            verdict = decide(critique, rounds_used=round_no - 1, max_rounds=max_rounds, final=True)
            break
        if touched:
            critique = await rejudge(critique, set(touched), round_no)
        row["score_after"] = critique.get("weighted_score")
        rounds.append(row)
        verdict = decide(critique, rounds_used=round_no, max_rounds=max_rounds)
    return {"verdict": verdict, "critique": critique, "rounds": rounds, "rounds_used": verdict["rounds_used"]}


# ----------------------------------------------------------------- the levers, live


async def variants_by_type(ws: Workspace, b: str) -> dict[str, list[str]]:
    _, body = await ws.call("GET", f"/v1/b/{b}/website/section-types", expect=False)
    types = ((_data(body) or {}).get("section_types") or []) if isinstance(body, dict) else []
    return {str(t.get("id")): [str(v) for v in t.get("allowed_variants") or []] for t in types if isinstance(t, dict)}


async def fresh(slug: str) -> bool:
    """Drop the public renderer's cached copy of the site, as the worker does
    on a publish — but now, so the render that follows sees the change rather
    than racing the worker (the pages are ISR with a 60 s window)."""
    url = os.getenv("WEB_REVALIDATE_URL", "").strip()
    secret = os.getenv("WEB_REVALIDATE_SECRET", "").strip()
    if not url or not secret or not url.startswith(("http://localhost:", "http://127.0.0.1:")):
        await asyncio.sleep(3)  # the worker's revalidation is the only one left
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(url, json={"slug": slug, "reason": "certify.repair"},
                                    headers={"x-locah-revalidate-secret": secret})
        return res.status_code < 400
    except httpx.HTTPError:
        await asyncio.sleep(3)
        return False


async def published(site: Site) -> int:
    status = int(await site.publish())
    await fresh(site.slug)
    return status


async def score_page(folder: Path, journey: dict[str, Any], page: str, tag: str, category: str) -> dict[str, Any]:
    """Render one page (xl + phone) and critique it alone."""
    from platform_core.website.ai_provider import get_ai_provider
    from platform_testing.certify.critic import critique_site
    from platform_testing.certify.run import _node

    out = folder / f"repair-{tag}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(folder / "journey.json", out / "journey.json")
    url = str(journey.get("public_url") or "")
    _node("tools/certify/render.mjs", str(out), url, "--pages", page, "--only", "--viewports", SCORE_VIEWPORTS,
          "--no-axe", "--no-links", "--no-perf", "--no-interact", timeout=900)
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
    await published(site)
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
    await published(site)


Scorer = Callable[[Path, dict[str, Any], str, str, str], Awaitable[dict[str, Any]]]


class Repairer:
    """One site's repair session: the owner's Workspace, the levers, and every
    fix already tried (a fix is never tried twice across rounds)."""

    def __init__(self, folder: Path, journey: dict[str, Any], category: str, *,
                 levers: Collection[str] = ALL_LEVERS, score: Scorer = score_page, judgments: int = 1) -> None:
        self.folder, self.journey, self.category = folder, journey, category
        self.levers = frozenset(levers)
        self.score = score
        # The critic wobbles by more than the keep margin (the same page,
        # unchanged, moves ±0.3–0.9): with judgments > 1 a fix is judged that
        # many times, and its page's starting score is judged again once per
        # round, both read as the mean — before and after measured alike.
        self.judgments = max(1, judgments)
        self.rebased: set[str] = set()
        self.tried: set[str] = set()
        self.attempts: list[dict[str, Any]] = []
        self.ws = Workspace(owner_token(journey["owner_id"], journey["owner_email"]),
                            Setup(str(journey.get("site_key") or folder.name)))
        self.b = str(journey["business_id"])
        self.site = Site(self.ws, self.b, str(journey["slug"]))
        self.variants: dict[str, list[str]] | None = None
        self.page_scores: dict[str, float] = {}
        self.page_critical: dict[str, int] = {}
        self._judged: dict[str, Any] | None = None

    async def __aenter__(self) -> Repairer:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                        tb: TracebackType | None) -> None:
        await self.site.close()
        await self.ws.close()

    async def draft(self) -> dict[str, Any]:
        return dict(await self.site.draft())

    async def round(self, critique: dict[str, Any], round_no: int, per_round: int = 3) -> list[dict[str, Any]]:
        """Plan up to ``per_round`` fixes from ``critique``; apply, judge and keep
        or revert each one. Each fix is measured against the page's score in the
        critique, or against the last fix kept on that page this round."""
        if self.variants is None:
            self.variants = await variants_by_type(self.ws, self.b)
        if critique is not self._judged:  # a new critique: its page scores are the baseline
            self._judged = critique
            self.page_scores = {k: float(v) for k, v in (critique.get("page_weighted") or {}).items()}
            self.page_critical = critical_by_page(critique)
            self.rebased = set()
        page_scores, page_critical = self.page_scores, self.page_critical
        out: list[dict[str, Any]] = []
        for n, fix in enumerate(plan(critique, await self.site.draft(), per_round, self.tried, self.levers)):
            self.tried.add(fix["key"])
            if self.judgments > 1 and fix["page"] not in self.rebased and fix["page"] in page_scores:
                # The page as it stands, judged again before anything changes.
                self.rebased.add(fix["page"])
                again = await self._judge(fix["page"], f"r{round_no}-{n}-base", self.judgments - 1)
                if again["score"] is not None:
                    page_scores[fix["page"]] = round(
                        (page_scores[fix["page"]] + again["score"] * (self.judgments - 1)) / self.judgments, 3)
            attempt: dict[str, Any] = {
                "round": round_no, "page": fix["page"], "lever": fix["lever"],
                "section": fix["section"].get("section_type_id"),
                "defect": f"{fix['defect'].get('severity')}/{fix['defect'].get('layer')}: "
                          f"{str(fix['defect'].get('text'))[:200]}"}
            undo = await apply(fix, self.site, self.ws, self.b, self.variants)
            if "skipped" in undo:
                attempt.update(kept=False, why=undo["skipped"])
                out.append(attempt)
                continue
            before = page_scores.get(fix["page"])
            critical_before = page_critical.get(fix["page"], 0)
            after = await self._judge(fix["page"], f"r{round_no}-{n}", self.judgments)
            # Better by the margin, and no NEW critical defect: a page whose
            # critical defects are the owner's (no photographs at all) can still
            # be made better; one the fix broke cannot.
            better = (after["score"] is not None and before is not None and after["critical"] is not None
                      and after["score"] >= before + KEEP_MARGIN and after["critical"] <= critical_before)
            attempt.update(change=fix.get("change"), before=before, after=after["score"],
                           critical_before=critical_before, critical_after=after["critical"], kept=better)
            if self.judgments > 1:
                attempt["readings"] = after["readings"]
            if better:
                page_scores[fix["page"]] = float(after["score"])
                page_critical[fix["page"]] = int(after["critical"])
            else:
                await revert(undo, fix, self.site, self.ws, self.b)
            out.append(attempt)
        self.attempts += out
        return out

    async def _judge(self, page: str, tag: str, times: int) -> dict[str, Any]:
        """The page judged ``times`` times: the mean score, the most critical
        defects any judgment found, and every reading."""
        readings = [await self.score(self.folder, self.journey, page, tag if times == 1 else f"{tag}-{i}",
                                     self.category) for i in range(times)]
        scores = [float(r["score"]) for r in readings if r.get("score") is not None]
        criticals = [int(r["critical"]) for r in readings if r.get("critical") is not None]
        return {"score": round(sum(scores) / len(scores), 3) if len(scores) == times else None,
                "critical": max(criticals) if len(criticals) == times else None,
                "readings": [r.get("score") for r in readings]}


def critical_by_page(critique: Mapping[str, Any]) -> dict[str, int]:
    """How many critical defects the critique found on each page."""
    out: dict[str, int] = {}
    for d in critique.get("defects") or []:
        if isinstance(d, Mapping) and d.get("severity") == "critical":
            out[str(d.get("page"))] = out.get(str(d.get("page")), 0) + 1
    return out


def category_of(journey: Mapping[str, Any]) -> str:
    from platform_testing.certify.owners import DISTINCT, SCENARIOS

    scenario = SCENARIOS.get(journey["scenario"]) or next(
        s for group in DISTINCT.values() for s in group if s.key == journey["scenario"])
    return str(scenario.kind or scenario.category_key)


async def run(run_dir: Path, site_key: str, *, rounds: int = 2, per_round: int = 3,
              levers: Collection[str] = ALL_LEVERS) -> dict[str, Any]:
    folder = run_dir / "sites" / site_key
    journey = json.loads((folder / "journey.json").read_text(encoding="utf-8"))
    critique = json.loads((folder / "critique.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {"site_key": site_key, "attempts": [], "page_before": critique.get("page_weighted"),
                              "rounds": 0}
    try:
        async with Repairer(folder, journey, category_of(journey), levers=levers) as fixer:
            for round_no in range(1, rounds + 1):
                if not await fixer.round(critique, round_no, per_round):
                    break
                report["rounds"] = round_no
            report["attempts"] = fixer.attempts
    finally:
        (folder / "repair.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    flags = sys.argv[3:]
    rounds = int(flags[flags.index("--rounds") + 1]) if "--rounds" in flags else 2
    per = int(flags[flags.index("--per-round") + 1]) if "--per-round" in flags else 3
    allowed = ALL_LEVERS - PHOTO_QUOTA_LEVERS if "--no-photos" in flags else ALL_LEVERS
    out = asyncio.run(run(Path(sys.argv[1]), sys.argv[2], rounds=rounds, per_round=per, levers=allowed))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps(out, indent=1, ensure_ascii=False))
