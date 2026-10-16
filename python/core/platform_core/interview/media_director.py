"""Which pictures a website needs, where each comes from, and drawing the gaps.

A site with no pictures reads as a form that was filled in, and most small
businesses start with none. The earlier LOCAH sites that owners wanted to
publish had a picture in every slot that carries the design — the hero, the
menu or catalogue, the story, the closing band — all from one visual world.

Media plan (decided BEFORE the design is chosen, so the design knows pictures
will exist):

1. the owner's own uploads, then pictures from their menu/catalogue,
2. pictures already on the business,
3. a real photograph found online and checked against the slot
   (``website.image_retrieval``) — by default, unless the owner asked for a
   text-led site (``visual_consent == "none"``); a Gemini-drawn draft only where
   drawing was switched on by name (``IMAGE_PROVIDER=gemini``),
4. otherwise a designed typographic treatment.

The media truth policy (``interview.models.TruthClass``) decides what may be
drawn at all:

* **mood** — hero, story, closing band: the trade's atmosphere (a home
  kitchen, a gym floor, calm architecture). Drawn for every trade, never
  presented as this business's own premises or project.
* **representative** — what a kind of thing looks like: a category of cuts, a
  bowl of podi, a family of pumps. Drawn as a labelled draft until a real
  photo arrives.
* **factual** — must show THIS project, this work, this person: a developer's
  named project, a photographer's or an interior studio's work. Never drawn;
  the card is typographic until the owner's photo arrives.

Every found photo is marked STOCK_PHOTO (a drawn draft AI_GENERATED) on the
Blueprint, cached by slot key (a rebuild never searches again), and loses to the
owner's real photo the moment one exists. Factual slots are never filled either way.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from platform_core.interview.creative_director import CreativeDirection
from platform_core.interview.models import (
    BusinessBlueprint,
    MediaGenerationRequest,
    MediaReference,
    PlannedMedia,
    TruthClass,
)
from platform_core.website.image_generation import GeneratedImage, generate_image, picture_source
from platform_core.website.media_prompts import (
    PROMPT_VERSION,
    aspect_for_hero,
    build_prompt,
    shoot_brief,
)

# Category slots per archetype (besides the hero and the story). For evidence-led
# trades these are factual: listed in the plan (a real photo improves them), never drawn.
BUDGET: dict[str, int] = {
    "product_commerce": 5, "menu_commerce": 4, "membership_fitness": 0,
    "real_estate_projects": 3, "service_appointment": 3, "b2b_rfq": 4,
    "project_portfolio": 3, "local_service": 3,
}
# Named items pictured as featured cards; the rest of the range is a price list.
FEATURED_ITEMS: dict[str, int] = {"menu_commerce": 6}

# Where the work happens — the story's own picture (mood).
_STORY = {
    "product_commerce": "the shop's counter and workspace — clean chopping block, tools and fresh produce "
                        "laid out, seen from the side",
    "menu_commerce": "the kitchen where everything is made — spices, brass and clay vessels, a stone grinder "
                     "and fresh ingredients on a worn wooden counter",
    "membership_fitness": "the training floor — racks, plates and a lifting platform, seen from a low angle",
    "real_estate_projects": "a calm landscaped courtyard between low-rise homes — a stone walkway, trees and "
                            "soft evening light",
    "b2b_rfq": "the workshop floor — machined parts on a clean workbench, orderly racks, soft industrial light",
    "service_appointment": "the calm, clean room where the work happens, with soft natural light",
    "local_service": "the workbench where the work happens, tools laid out neatly",
    "project_portfolio": "the studio desk — sketches, material samples and tools of the craft by a window",
}
# The hero's subject when the catalogue does not supply one (mood only: never
# a picture of "their" building, room or work).
_HERO_MOOD = {
    "real_estate_projects": "contemporary residential architecture with landscaped greenery, seen from the "
                            "street in soft daylight",
    "membership_fitness": "a strength-training gym interior — barbells, racks and plates, no people",
    "b2b_rfq": "a clean, orderly industrial workshop with precise machined parts in the foreground",
    "project_portfolio": "the tools and materials of the craft arranged on a wide studio table",
    "service_appointment": "a calm, bright, welcoming interior with soft natural light and plants",
    "local_service": "the trade's tools and materials, neatly arranged in warm light",
}
# Trades whose catalogue IS the evidence: their project/work cards are never drawn.
_EVIDENCE_LED_ARCHETYPES = frozenset({"real_estate_projects", "project_portfolio"})


@dataclass(frozen=True)
class Slot:
    key: str  # "hero", "category:chicken", "item:idli-podi", "story"
    subject: str
    aspect: str
    role: str  # MediaReference role it becomes
    label: str
    purpose: str = "category"
    truth_class: TruthClass = "representative"
    section: str = ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:60]


def _clean(text: str) -> str:
    # Owner words only, and nothing that reads as a number or a claim.
    return re.sub(r"\s+", " ", re.sub(r"[\d₹$]+", "", text)).strip(" ,.-")[:80]


def drafts_allowed(bp: BusinessBlueprint) -> bool:
    """Draft visuals fill gaps unless the owner asked for a text-led website."""
    return bool(bp.visual_consent != "none")


def owner_photos(bp: BusinessBlueprint) -> list[MediaReference]:
    """The owner's own pictures (uploads and catalogue pictures), not the logo."""
    return [m for m in bp.media_assets
            if m.role != "logo" and m.source in {"USER_UPLOAD", "CATALOGUE_EXTRACTED"}]


def pictures_expected(bp: BusinessBlueprint, *, images_available: bool | None = None) -> bool:
    """Whether this site will have pictures — asked BEFORE the design is chosen.

    True when the owner has their own, or when LOCAH may draw drafts and an
    image provider is configured. A design is then chosen for a site with
    pictures, not for an empty one.
    """
    if owner_photos(bp):
        return True
    if images_available is None:
        from platform_core.website.image_generation import pictures_available

        images_available = pictures_available()
    return drafts_allowed(bp) and images_available


def evidence_led(bp: BusinessBlueprint, direction: CreativeDirection) -> bool:
    """A trade whose catalogue is its evidence (projects, portfolio work)."""
    from platform_core.interview.playbooks import playbook_for

    return (direction.archetype in _EVIDENCE_LED_ARCHETYPES or playbook_for(bp).portfolio
            or direction.dimensions.get("offering") in {"portfolio", "property"})


def may_draw(bp: BusinessBlueprint, direction: CreativeDirection) -> bool:
    """Whether any draft visual may be drawn for this site (the owner's choice).

    Kept for callers of the old truth rule; the policy is now per slot.
    """
    del direction
    return drafts_allowed(bp)


def plan_slots(bp: BusinessBlueprint, direction: CreativeDirection) -> list[Slot]:
    """The pictures this site should have, most important first — with each
    slot's truth class. Factual slots are listed (the plan shows what a real
    photo would improve) but never drawn."""
    arche = direction.archetype
    groups = [g for g in bp.taxonomy.groups if g.name]
    names = [_clean(g.name) for g in groups if _clean(g.name)]
    evidence = evidence_led(bp, direction)
    if arche in {"product_commerce", "menu_commerce"} and names:
        hero_subject = ", ".join(names[:4])
    else:
        hero_subject = _HERO_MOOD.get(arche, "")
    slots = [Slot("hero", hero_subject, aspect_for_hero(direction.hero), "hero", "Draft visual · cover",
                  purpose="hero", truth_class="mood", section="hero")]
    featured = FEATURED_ITEMS.get(arche, 0)
    items: list[Slot] = []
    if featured and not evidence:
        # Round-robin across groups so every kind of dish is represented —
        # the owner's bestsellers first in each.
        ordered = {g.name: sorted(g.items, key=lambda i: 0 if i.tag else 1) for g in groups}
        for depth in range(4):
            for group in groups:
                if depth < len(ordered[group.name]) and len(items) < featured:
                    item = ordered[group.name][depth]
                    subject = _clean(f"{item.name} ({group.name})")
                    if subject:
                        items.append(Slot(f"item:{slug(item.name)}", subject, "4:3", "offering",
                                          f"Draft visual · {item.name}"[:120], purpose="item",
                                          truth_class="representative", section="product_showcase"))
    slots += items
    if not items:
        for group in groups[:BUDGET.get(arche, 3)]:
            members = ", ".join(_clean(i.name) for i in group.items[:4] if _clean(i.name))
            subject = _clean(group.name) + (f" — {members}" if members else "")
            slots.append(Slot(f"category:{slug(group.name)}", subject, "4:3", "offering",
                              f"Draft visual · {group.name}"[:120], purpose="category",
                              truth_class="factual" if evidence else "representative",
                              section="product_showcase"))
    story = _STORY.get(arche)
    if story and direction.story_variant == "story_split":
        slots.append(Slot("story", story, "4:5", "gallery", "Draft visual · where it is made",
                          purpose="story", truth_class="mood", section="about"))
    return slots


def plan_media(bp: BusinessBlueprint, direction: CreativeDirection) -> list[PlannedMedia]:
    """The media plan, written onto the Blueprint: every slot, its source and state.

    An owner's decision on a slot (approved, removed) survives re-planning.
    """
    brief = shoot_brief(direction)
    before = {p.key: p for p in bp.media_plan}
    plan: list[PlannedMedia] = []
    for slot in plan_slots(bp, direction):
        own = owner_photo(bp, slot)
        drawn = cached(bp, slot.key)
        prior = before.get(slot.key)
        entry = PlannedMedia(
            key=slot.key, purpose=slot.purpose, section=slot.section, subject=slot.subject[:240],
            truth_class=slot.truth_class, aspect=slot.aspect,
            crop="left-space" if slot.purpose == "hero" and slot.aspect == "16:9" else "center",
            style=brief.world[:400], prompt_version=PROMPT_VERSION,
            approval=prior.approval if prior else "draft",
        )
        if prior and prior.approval == "removed":
            entry.status, entry.reason = "skipped", "Removed by the owner."
        elif own:
            source = next((m.source for m in bp.media_assets if m.asset_id == own), "USER_UPLOAD")
            entry.source = "catalogue_extracted" if source == "CATALOGUE_EXTRACTED" else "owner_uploaded"
            entry.asset_id, entry.status = own, "ready"
        elif drawn:
            entry.source, entry.asset_id, entry.status = _source_of(bp, drawn), drawn, "ready"
        elif slot.truth_class == "factual":
            entry.status, entry.reason = "skipped", "Needs a real photo — never drawn."
        elif not drafts_allowed(bp):
            entry.status, entry.reason = "skipped", "Text-led website, as the owner asked."
        else:
            entry.source = "stock_retrieved" if picture_source() != "gemini" else "gemini_generated"
        plan.append(entry)
    bp.media_plan = plan[:24]
    return list(plan[:24])


def cached(bp: BusinessBlueprint, key: str) -> UUID | None:
    """A drawn draft for this slot, if one is ready."""
    request = next((r for r in bp.media_generation_requests
                    if r.role == "visual" and r.key == key and r.status == "ready" and r.asset_id), None)
    return request.asset_id if request else None


def _source_of(bp: BusinessBlueprint, asset_id: UUID) -> str:
    """How a ready picture got onto the site: found online, or drawn."""
    found = next((m for m in bp.media_assets if m.asset_id == asset_id), None)
    return "stock_retrieved" if found is not None and found.source == "STOCK_PHOTO" else "gemini_generated"


def owner_photo(bp: BusinessBlueprint, slot: Slot) -> UUID | None:
    uploads = owner_photos(bp)
    if slot.key == "hero":
        hero = next((m for m in uploads if m.role == "hero"), None)
        return hero.asset_id if hero else None
    if slot.key == "story":
        # A photo of their own place tells the story better than any draft.
        place = next((m for m in uploads if m.role == "business"), None)
        return place.asset_id if place else None
    name = slot.key.split(":", 1)[1]
    for media in uploads:
        if media.role in {"offering", "gallery", "business"} and slug(media.label).startswith(name[:12]):
            return UUID(str(media.asset_id))
    return None


def _removed(bp: BusinessBlueprint, key: str) -> bool:
    return any(p.key == key and p.approval == "removed" for p in bp.media_plan)


def picture_for(bp: BusinessBlueprint, key: str) -> str | None:
    """The asset id to show in a slot: the owner's first, then a drawn draft."""
    own = {"hero": "hero", "story": "business"}.get(key)
    for media in owner_photos(bp):
        if own and media.role == own:
            return str(media.asset_id)
    if _removed(bp, key):
        return None
    found = cached(bp, key)
    if found:
        return str(found)
    if key == "hero":
        hero = next((m for m in bp.media_assets if m.role == "hero"), None)
        return str(hero.asset_id) if hero else None
    name = key.split(":", 1)[1] if ":" in key else key
    for media in owner_photos(bp):
        if media.role in {"offering", "gallery", "business"} and slug(media.label).startswith(name[:12]):
            return str(media.asset_id)
    return None


def prompt_for(slot: Slot, direction: CreativeDirection, trade: str) -> str:
    return str(build_prompt(subject=slot.subject or trade, purpose=slot.purpose, truth_class=slot.truth_class,
                            brief=shoot_brief(direction), trade=trade, hero_style=direction.hero))


Drawer = Callable[[str, str], Awaitable[tuple[GeneratedImage | None, str]]]


async def draw_missing(
    bp: BusinessBlueprint,
    direction: CreativeDirection,
    trade: str,
    *,
    draw: Drawer | None = None,
    concurrency: int = 3,
) -> list[tuple[Slot, GeneratedImage | None, str]]:
    """Draw the planned slots that have no picture yet, a few at a time.

    Never a factual slot, never when the owner asked for a text-led site, never
    a slot the owner removed, never a slot already filled.
    """
    todo = _slots_to_fill(bp, direction)
    if not todo:
        return []
    gate = asyncio.Semaphore(concurrency)
    drawer = draw or (lambda prompt, aspect: generate_image(prompt, aspect_ratio=aspect, timeout_seconds=75))

    async def one(slot: Slot) -> tuple[Slot, GeneratedImage | None, str]:
        async with gate:
            image, reason = await drawer(prompt_for(slot, direction, trade), slot.aspect)
            return slot, image, reason

    return list(await asyncio.gather(*(one(s) for s in todo)))


def _slots_to_fill(bp: BusinessBlueprint, direction: CreativeDirection) -> list[Slot]:
    """Mood and representative slots with no picture yet — never a factual one,
    never when the owner asked for a text-led site, never a removed slot."""
    if not drafts_allowed(bp):
        return []
    return [s for s in plan_slots(bp, direction)
            if s.truth_class != "factual" and not owner_photo(bp, s) and not cached(bp, s.key)
            and not _removed(bp, s.key)]


async def retrieve_missing(
    bp: BusinessBlueprint,
    direction: CreativeDirection,
    trade: str,
    *,
    concurrency: int = 3,
    retriever: Callable[..., Awaitable[list[tuple[Any, Any]]]] | None = None,
) -> list[tuple[Slot, Any]]:
    """Find a verified real photograph for every slot that has none, a few at a time.

    The same slots `draw_missing` would draw, found instead of drawn: the brief
    comes from the Creative Director's own shoot brief, the loop is
    `website.image_retrieval`, and a slot that finds nothing stays empty.
    Returns (slot, Outcome) pairs.
    """
    from platform_core.website.image_retrieval import brief_for_slot, retrieve_many

    todo = _slots_to_fill(bp, direction)
    if not todo:
        return []
    briefs = [brief_for_slot(s, direction, trade) for s in todo]
    by_key = {s.key: s for s in todo}
    results = await (retriever or retrieve_many)(briefs, concurrency=concurrency)
    return [(by_key[brief.key], outcome) for brief, outcome in results]


def record(bp: BusinessBlueprint, slot: Slot, asset_id: UUID | None, reason: str = "", *,
           stock: bool = False) -> None:
    """Remember a found or drawn (or failed) slot on the Blueprint, and in its media plan."""
    bp.media_generation_requests = [
        r for r in bp.media_generation_requests if not (r.role == "visual" and r.key == slot.key)
    ]
    bp.media_generation_requests.append(MediaGenerationRequest(
        role="visual", key=slot.key, status="ready" if asset_id else "failed",
        asset_id=asset_id, reason=None if asset_id else (reason or "error"),
    ))
    if asset_id and all(m.asset_id != asset_id for m in bp.media_assets):
        bp.media_assets.append(MediaReference(
            asset_id=asset_id, role=slot.role if slot.role in {"hero", "offering"} else "gallery",
            label=slot.label.replace("Draft visual", "Stock photo") if stock else slot.label,
            source="STOCK_PHOTO" if stock else "AI_GENERATED",
        ))
    for entry in bp.media_plan:
        if entry.key == slot.key:
            entry.status = "ready" if asset_id else "failed"
            entry.asset_id = asset_id or entry.asset_id
            if asset_id:
                entry.source = "stock_retrieved" if stock else "gemini_generated"
            entry.reason = "" if asset_id else (reason or "error")[:200]


def section_image_prompt(
    theme: dict[str, object], section_type: str, trade: str, *, subject: str = "",
) -> tuple[str, str] | None:
    """(prompt, aspect) for one picture asked for from the editor or a legacy
    fill, drawn in the site's own visual world — or None where a drawn picture
    would stand in for evidence (a developer's project, a studio's work).

    ``theme`` is a draft's stored theme; its ``creative_direction`` carries the
    image style, palette and archetype the site was designed with.
    """
    direction = theme.get("creative_direction") if isinstance(theme.get("creative_direction"), dict) else {}
    assert isinstance(direction, dict)
    arche = str(direction.get("archetype") or theme.get("site_archetype") or "")
    brief = shoot_brief(direction or {"palette": {"mode": theme.get("palette_mode", "light"),
                                                  "primary": theme.get("primary_color", ""),
                                                  "accent": theme.get("accent_color", "")}})
    hero = str(direction.get("hero") or theme.get("hero_style") or "")
    if section_type in {"hero", "cta_band"}:
        return build_prompt(subject=subject or _HERO_MOOD.get(arche, trade), purpose="hero", truth_class="mood",
                            brief=brief, trade=trade, hero_style=hero), aspect_for_hero(hero) \
            if section_type == "hero" else "16:9"
    if section_type in {"about", "text_block"}:
        return build_prompt(subject=subject or _STORY.get(arche, trade), purpose="story", truth_class="mood",
                            brief=brief, trade=trade), "4:5"
    if arche in _EVIDENCE_LED_ARCHETYPES:
        return None
    return build_prompt(subject=subject or trade, purpose="item", truth_class="representative", brief=brief,
                        trade=trade), "4:3"


def section_image_brief(theme: dict[str, object], section_type: str, trade: str, *, subject: str = "") -> Any:
    """The `SlotBrief` for one picture asked for from the editor or a legacy fill —
    the same slot `section_image_prompt` would draw, in the site's own visual
    world — or None where a found picture would stand in for evidence."""
    from platform_core.website.image_retrieval import brief_for_slot

    direction = theme.get("creative_direction") if isinstance(theme.get("creative_direction"), dict) else {}
    assert isinstance(direction, dict)
    arche = str(direction.get("archetype") or theme.get("site_archetype") or "")
    shown = direction or {"palette": {"mode": theme.get("palette_mode", "light"),
                                      "primary": theme.get("primary_color", ""),
                                      "accent": theme.get("accent_color", "")},
                          "hero": theme.get("hero_style", "")}
    hero = str(direction.get("hero") or theme.get("hero_style") or "")
    if section_type in {"hero", "cta_band"}:
        slot = Slot("hero" if section_type == "hero" else "cta", subject or _HERO_MOOD.get(arche, trade),
                    aspect_for_hero(hero) if section_type == "hero" else "16:9", "hero", "",
                    purpose="hero", truth_class="mood", section=section_type)
    elif section_type in {"about", "text_block"}:
        slot = Slot("story", subject or _STORY.get(arche, trade), "4:5", "gallery", "",
                    purpose="story", truth_class="mood", section=section_type)
    elif arche in _EVIDENCE_LED_ARCHETYPES:
        return None
    else:
        slot = Slot("item", subject or trade, "4:3", "offering", "", purpose="item",
                    truth_class="representative", section=section_type)
    return brief_for_slot(slot, shown, trade)


# What the editor may offer for each picture a section can carry — the one
# decision the Workspace follows. "draw": Generate / Regenerate / Upload /
# Remove. "real_photo": Upload / Remove only, with "This should be a real photo
# of your work — upload one instead." A drawn picture never stands in for
# evidence: a named project, a studio's work, a real gallery.
REAL_PHOTO_MESSAGE = "This should be a real photo of your work — upload one instead."
_MOOD_SECTIONS = frozenset({"hero", "cta_band", "about"})
_ROW_SECTIONS = frozenset({"category_showcase", "product_showcase"})
_EVIDENCE_VARIANTS = frozenset({"project_cards"})
_NO_ROW_PICTURES = frozenset({"plan_cards"})


def image_policy(theme: dict[str, object], section_type: str, layout_variant: str | None) -> dict[str, str]:
    """{"self": ..., "items": ...} for the pictures this section can carry."""
    direction = theme.get("creative_direction") if isinstance(theme.get("creative_direction"), dict) else {}
    assert isinstance(direction, dict)
    arche = str(direction.get("archetype") or theme.get("site_archetype") or "")
    if section_type in _MOOD_SECTIONS:
        return {"self": "draw"}
    if section_type == "gallery":
        return {"self": "real_photo"}
    if section_type in _ROW_SECTIONS:
        if layout_variant in _NO_ROW_PICTURES:
            return {}
        evidence = arche in _EVIDENCE_LED_ARCHETYPES or layout_variant in _EVIDENCE_VARIANTS
        return {"items": "real_photo" if evidence else "draw"}
    return {}
