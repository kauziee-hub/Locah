"""The site critic and its polish loop: Locah's own "no, make it better".

A merchant using a general site builder improves a page by saying what is
wrong with it, again and again: "the same picture twice", "too many cards",
"that part is a wall of text", "too much going on". This module is that
reviewer, run before the merchant sees anything:

    compose → critique → polish → critique … (at most ``ROUNDS`` rounds)

The critique reads the composed site (every page) the way an art director
reads a layout. Each finding has a code, where it is, and whether it can be
fixed without inventing anything — a fix only moves, re-lays or removes what
the site already has; it never writes a word or a fact. What cannot be fixed
here (a home with no centrepiece because the owner has not yet said what makes
them different) stays on record for the interview to ask about.

It is deterministic and needs no rendering. A rendered critic (screenshots read
by a vision model) can add findings through the same ``Finding`` shape; the
polish loop does not care who noticed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

ROUNDS = 3

# Sections that read as a grid of boxes.
_CARDS = {
    "product_showcase": {"commerce_grid", "menu_grid", "service_cards", "plan_cards", "project_cards", "bento",
                         "category_boards"},
    "category_showcase": {"image_cards", "tiles", "bento"},
    "pillars": {"cards"},
    "feature_grid": {"cards", "steps", "list"},
}
# Sections that are words and nothing else.
_TEXT_ONLY = {"statement": {"giant"}, "faq": {"accordion", "split"}, "about": {"text_only", "word_reveal"},
              "pillars": {"strip", "numbered"}}
# Layouts that move on their own as you scroll.
_MOVING = {"hero": {"orbit", "plane", "kinetic", "depth", "cinematic_zoom"},
           "product_showcase": {"rail", "stack"}, "category_showcase": {"rail"},
           "about": {"word_reveal", "collage"}, "marquee": {"band", "outline"},
           "media_text": {"sticky"}, "statement": {"giant"}}
_ALLOWANCE = {"restrained": 2, "gentle": 4, "signature": 5, "expressive": 99}


@dataclass
class Finding:
    code: str
    page: str
    where: str
    note: str
    fixable: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is(section: dict[str, Any], table: dict[str, set[str]]) -> bool:
    return str(section.get("layout_variant") or "") in table.get(str(section["section_type_id"]), set())


def _pictures(section: dict[str, Any]) -> list[str]:
    content = section.get("content") or {}
    found = [str(content["image_asset_id"])] if content.get("image_asset_id") else []
    for key in ("items", "categories"):
        found += [str(r["image_asset_id"]) for r in content.get(key) or []
                  if isinstance(r, dict) and r.get("image_asset_id")]
    return found


def _layout(section: dict[str, Any]) -> tuple[str, Any]:
    """What makes two sections the same design: a composition is its recipe."""
    kind = str(section["section_type_id"])
    if kind == "composition":
        return kind, (section.get("content") or {}).get("recipe")
    return kind, section.get("layout_variant")


def _featured_beside_range(a: str, b: str) -> bool:
    """A range page's signature block shows things the list below also shows: intended."""
    return {a, b} == {"composition", "product_showcase"}


def critique(payload: dict[str, Any]) -> list[Finding]:
    budget = str(((payload.get("theme_hints") or {}).get("dna") or {}).get("budget") or "gentle")
    out: list[Finding] = []
    for page in payload["pages"]:
        slug = str(page["slug"])
        sections = page["sections"]
        # The same picture twice on one page: a reader notices at once.
        seen: dict[str, str] = {}
        for section in sections:
            kind = str(section["section_type_id"])
            for picture in dict.fromkeys(_pictures(section)):
                if picture in seen and seen[picture] != kind and not _featured_beside_range(seen[picture], kind):
                    out.append(Finding("repeated_picture", slug, kind, f"same picture as the {seen[picture]}",
                                       kind in {"cta_band", "media_text", "statement", "about", "composition"}))
                seen.setdefault(picture, kind)
        for a, b in zip(sections, sections[1:]):
            if _is(a, _CARDS) and _is(b, _CARDS):
                out.append(Finding("card_after_card", slug, str(b["section_type_id"]),
                                   "two grids of boxes in a row", b["section_type_id"] in {"pillars", "feature_grid"}))
            if _is(a, _TEXT_ONLY) and _is(b, _TEXT_ONLY):
                out.append(Finding("wall_of_text", slug, str(b["section_type_id"]),
                                   "two sections of only words in a row", True))
        layouts = [_layout(s) for s in sections]
        for i, layout in enumerate(layouts):
            if layout in layouts[:i] and layout[0] not in {"product_showcase"}:
                out.append(Finding("repeated_layout", slug, str(layout[0]), "the same section twice", True))
        if slug != "home" and len(sections) < 3:
            out.append(Finding("thin_page", slug, "page", "an inner page with little on it", False))
        moving = sum(1 for s in sections if _is(s, _MOVING))
        if moving > _ALLOWANCE.get(budget, 4):
            out.append(Finding("motion_overload", slug, "page",
                               f"{moving} moving sections for a {budget} brand", True))
    home = payload["pages"][0]["sections"]
    hero = next((s for s in home if s["section_type_id"] == "hero"), None)
    if hero and not hero["content"].get("image_asset_id") and not any(
            s["section_type_id"] in {"statement", "about"} or (
                s["section_type_id"] == "composition"
                and (s.get("content") or {}).get("role") in {"statement", "story"}) for s in home):
        out.append(Finding("no_centrepiece", "home", "hero",
                           "no picture, story or statement to carry the page — ask the owner", False))
    return out


def _quiet(section: dict[str, Any]) -> bool:
    """Make one moving section still. True if it changed."""
    kind, variant = str(section["section_type_id"]), str(section.get("layout_variant") or "")
    still = {("marquee", "band"): None, ("marquee", "outline"): None,
             ("media_text", "sticky"): "alternating", ("about", "word_reveal"): "sticky_split",
             ("about", "collage"): "sticky_split", ("product_showcase", "stack"): "spotlight",
             ("product_showcase", "rail"): "spotlight",
             ("category_showcase", "rail"): "bento"}
    if (kind, variant) in still:
        after = still[(kind, variant)]
        if after == "sticky_split" and not (section.get("content") or {}).get("image_asset_id"):
            after = "text_only"
        section["layout_variant"] = after or variant
        if after is None:
            section["_drop"] = True
        return True
    return False


def polish(payload: dict[str, Any], findings: list[Finding]) -> list[str]:
    """Fix what can be fixed without inventing anything. Returns what was done."""
    done: list[str] = []
    pages = {str(p["slug"]): p for p in payload["pages"]}
    for f in [f for f in findings if f.fixable]:
        sections = pages[f.page]["sections"]
        target = next((s for s in reversed(sections) if s["section_type_id"] == f.where), None)
        if f.code == "repeated_picture" and target:
            content = target["content"]
            if f.where == "cta_band":
                content.pop("image_asset_id", None)
                target["layout_variant"] = "centered" if target.get("layout_variant") == "image_banner" else \
                    target.get("layout_variant")
            elif f.where == "statement":
                content.pop("image_asset_id", None)
                target["layout_variant"] = "giant"
            elif f.where == "media_text":
                used = {p for s in sections if s is not target for p in _pictures(s)}
                for row in content.get("items") or []:
                    if str(row.get("image_asset_id")) in used:
                        row.pop("image_asset_id", None)
            elif f.where == "about":
                content.pop("image_asset_id", None)
                target["layout_variant"] = "text_only"
            elif f.where == "composition":
                # Its repeated picture leaves; the arrangement keeps its words.
                used = {p for s in sections if s is not target for p in _pictures(s)}
                kept = [b for b in content.get("items") or []
                        if not (b.get("kind") == "picture" and str(b.get("image_asset_id")) in used)]
                if any(b.get("kind") != "picture" for b in kept):
                    from platform_core.website.composition_grammar import normalize

                    target["content"] = normalize({**content, "items": kept})
                else:
                    target["_drop"] = True
            done.append(f"{f.page}: {f.where} no longer repeats a picture")
        elif f.code == "card_after_card" and target:
            target["layout_variant"] = "numbered" if f.where == "pillars" else "list"
            done.append(f"{f.page}: {f.where} set as a list, not more boxes")
        elif f.code == "wall_of_text" and target:
            i = sections.index(target)
            pictured = next((j for j in range(i + 1, len(sections)) if _pictures(sections[j])), None)
            if pictured is not None and sections[pictured]["section_type_id"] not in {"cta_band", "contact"}:
                sections.insert(i, sections.pop(pictured))
                done.append(f"{f.page}: a picture now breaks the run of words before the {f.where}")
            elif f.where == "pillars":
                target["layout_variant"] = "cards"
                done.append(f"{f.page}: pillars set as cards to break the words")
        elif f.code == "repeated_layout" and target:
            target["_drop"] = True
            done.append(f"{f.page}: second {f.where} removed")
        elif f.code == "motion_overload":
            # Still the later moments first, until the page is within budget.
            budget = str(((payload.get("theme_hints") or {}).get("dna") or {}).get("budget") or "gentle")
            for section in reversed(sections):
                moving = sum(1 for s in sections if _is(s, _MOVING) and not s.get("_drop"))
                if moving <= _ALLOWANCE.get(budget, 4):
                    break
                if section["section_type_id"] != "hero" and _is(section, _MOVING) and _quiet(section):
                    done.append(f"{f.page}: {section['section_type_id']} made still")
    for page in payload["pages"]:
        page["sections"] = [s for s in page["sections"] if not s.pop("_drop", False)]
    return done


def review(payload: dict[str, Any]) -> dict[str, Any]:
    """The loop: critique and polish until clean or out of rounds."""
    fixed: list[str] = []
    rounds = 0
    findings = critique(payload)
    while rounds < ROUNDS and any(f.fixable for f in findings):
        rounds += 1
        changed = polish(payload, findings)
        if not changed:
            break
        fixed += changed
        findings = critique(payload)
    return {"rounds": rounds, "fixed": fixed, "open": [f.as_dict() for f in findings]}
