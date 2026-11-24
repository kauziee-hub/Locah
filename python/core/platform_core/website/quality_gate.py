"""The hard gates every built website is checked against, from the draft itself.

The founder's pass bar (Website Quality Program, decision 1, 2026-11-25) is a
rubric average of at least 4/5 with no dimension under 3, plus hard gates that
no score can buy back. Four of those gates read the structured draft, so every
build can be checked here with no browser and no model call:

  photo_twice        no picture is shown twice on one page
  chat_speak         no raw chat shorthand in copy a visitor reads ("Ppl shud book
                     trial first then join" was on a gym's live site)
  drawn_as_business  no AI drawing where a visitor reads the business's own place,
                     people or products — drawings are mood only (media_prompts)
  primary_action     the home page opens on a section that offers the primary action

The gates that need a rendered page on a throttled phone (LCP <= 2.5 s, main
thread blocked <= 600 ms, no serious or critical axe violation, the primary
action inside the first phone screen) are measured by the certification harness
(tools/site-lab/perf-baseline.mjs, platform_testing.certify) and join the verdict
with the rubric in Phase 1.

Shadow mode (WEBSITE_CERTIFICATION=record, the default): every verdict is
recorded and logged; nothing is held back.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Mapping
from typing import Any

from platform_core.website.image_generation import DRAWN_SOURCES

GATES: tuple[str, ...] = ("photo_twice", "chat_speak", "drawn_as_business", "primary_action")
# Gates only a rendered page can answer; named in every verdict so a "pass" here
# is never read as the whole bar.
RENDER_GATES: tuple[str, ...] = ("lcp_mobile", "blocking_mobile", "axe_serious", "primary_action_first_screen")

# ---------------------------------------------------------------- pictures

_SINGLE_KEYS = ("image_asset_id", "hero_asset_id", "hero_image_asset_id")
_LIST_KEYS = ("image_asset_ids", "gallery_asset_ids")

# Sections a visitor reads as the business itself — its rooms, dishes, products,
# programmes, people, premises. A drawing may never stand in for any of them.
_BUSINESS_SECTIONS = frozenset({
    "product_showcase", "category_showcase", "gallery", "rooms_section", "menu_section",
    "classes_section", "plans_section", "offerings_list", "properties", "reviews_section",
    "location_list", "contact",
})
# A composed section (composition_grammar) is read by its role: a featured offering
# or the way in is the business; a story, statement or closing is mood.
_BUSINESS_ROLES = frozenset({"featured", "visit"})


def pictures(content: Mapping[str, Any]) -> Iterator[tuple[str, bool]]:
    """Every picture a section shows, and whether it stands for one thing the
    business sells or is (an item's picture, a gallery frame). A composed
    section's picture block is a placement, not an item: its role decides."""
    for key in _SINGLE_KEYS:
        if content.get(key):
            yield str(content[key]), False
    for key in _LIST_KEYS:
        for asset in content.get(key) or []:
            if asset:
                yield str(asset), True
    for item in content.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        one_thing = item.get("kind") != "picture"
        if item.get("image_asset_id"):
            yield str(item["image_asset_id"]), one_thing
        for asset in item.get("image_asset_ids") or []:
            if asset:
                yield str(asset), one_thing


def _reads_as_business(kind: str, content: Mapping[str, Any]) -> bool:
    return kind in _BUSINESS_SECTIONS or (kind == "composition" and content.get("role") in _BUSINESS_ROLES)


# ---------------------------------------------------------------- chat-speak

# How people type in a chat (interview/spelling.py writes these out for the page).
_CHAT_WORDS = frozenset({
    "ppl", "shud", "shld", "cud", "wud", "pls", "plz", "bcoz", "bcz", "coz", "abt", "frm",
    "tmrw", "tmrow", "nite", "gud", "gr8",
})
# Chat-speak only in lower case: a capital is an initial or a name ("U. Lakshmi",
# "Wat Arun"), and city shorthand is how a place is written in a chat ("hsr layout blr").
_CHAT_LOWER = frozenset({"u", "ur", "nd", "wat", "wen", "wid", "hv", "hav",
                         "blr", "blore", "cbe", "chn", "hyd", "tvm", "ekm", "mdu"})
_WORD = re.compile(r"(?<![A-Za-z0-9'])[A-Za-z0-9]+(?![A-Za-z0-9'])")
_AND_N = re.compile(r"(?<=[a-z]) n (?=[a-z])")
# Content keys that are never words on the page.
_NOT_COPY = re.compile(
    r"(^|_)(id|ids|url|href|path|slug|anchor|variant|icon|kind|type|binding|action|target|phone|"
    r"email|whatsapp|lat|lng|currency|sku|code|key|style|layout|tone|mode)$")


def _copy(value: Any, key: str = "") -> Iterator[str]:
    if isinstance(value, str):
        if not _NOT_COPY.search(key):
            yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _copy(v, str(k))
    elif isinstance(value, list):
        for v in value:
            yield from _copy(v, key)


def chat_speak(text: str) -> list[str]:
    """The chat shorthand in one string, as it was typed."""
    found = [w for w in _WORD.findall(text or "") if w.casefold() in _CHAT_WORDS or w in _CHAT_LOWER]
    if _AND_N.search(text or ""):
        found.append("n")
    return found


# ---------------------------------------------------------------- the check


def check(pages: list[Mapping[str, Any]], sources: Mapping[str, str]) -> dict[str, Any]:
    """The static hard gates over a draft.

    ``pages``: [{"slug", "page_type", "sections": [{"section_type_id", "content",
    "is_visible", "sort_order"}]}]; ``sources``: media asset id -> source_type.
    Returns {"status": "pass" | "repair", "failures": [...], "gates": GATES,
    "unchecked": RENDER_GATES}.
    """
    failures: list[dict[str, Any]] = []
    for page in pages:
        slug = str(page.get("slug") or "")
        sections = sorted((s for s in page.get("sections") or [] if s.get("is_visible", True)),
                          key=lambda s: int(s.get("sort_order") or 0))
        shown: Counter[str] = Counter()
        for section in sections:
            kind = str(section.get("section_type_id") or "")
            content = section.get("content") or {}
            for asset, stands_for_one in pictures(content):
                shown[asset] += 1
                if sources.get(asset) in DRAWN_SOURCES and (stands_for_one or _reads_as_business(kind, content)):
                    failures.append({"gate": "drawn_as_business", "page": slug, "section": kind,
                                     "detail": f"a {sources[asset]} picture shown as the business's own"})
            said = sorted({w for text in _copy(content) for w in chat_speak(text)})
            if said:
                failures.append({"gate": "chat_speak", "page": slug, "section": kind,
                                 "detail": "chat shorthand on the page: " + ", ".join(said[:6])})
        for asset, times in shown.items():
            if times > 1:
                failures.append({"gate": "photo_twice", "page": slug, "detail": f"{asset} shown {times} times"})
        if str(page.get("page_type") or "") == "home" or slug in {"home", "/", ""}:
            first = sections[0] if sections else {}
            content = first.get("content") or {}
            if not (str(content.get("cta_label") or "").strip() and str(content.get("cta_url") or "").strip()):
                failures.append({"gate": "primary_action", "page": slug,
                                 "section": str(first.get("section_type_id") or ""),
                                 "detail": "the first section offers no primary action"})
    return {
        "status": "repair" if failures else "pass",
        "failures": failures[:40],
        "failed_gates": sorted({f["gate"] for f in failures}),
        "gates": list(GATES),
        "unchecked": list(RENDER_GATES),
    }
