"""The motion director: how much of a site moves, and where.

The experience layer (experience.py) picks the scene each role *could* use — a
3D ring for the hero, a pinned rail for the range, a story lit word by word.
Picked independently, a site could get all of them at once: a page full of
effects, which reads as machine-made, not premium. A studio decides where the
one or two moments are and keeps the rest still.

The design DNA's budget (design_dna.py) is that decision:

* **restrained** — quiet luxury, care: one slow moving picture at the top and
  fades; no moving bands, no pinned rails, no word-by-word story;
* **gentle** — the hero's scene and at most one more moment as you scroll;
* **signature** — a cinematic hero and one scroll moment, with a moving band;
* **expressive** — playful or loud brands: everything the content can carry.

The renderer reads the same budget (``data-budget``) to decide whether cards
tilt, stagger in and pictures follow the pointer. Pure function over the
composed sections; returns what it changed, for the record.
"""

from __future__ import annotations

from typing import Any

# A hero scene that suits a still, slow page; the rest are loud.
_LOUD_HEROES = frozenset({"kinetic", "orbit", "plane"})
# Range and story layouts that are a scroll moment in themselves.
_SCROLL_RANGE = frozenset({"rail", "stack", "menu_book"})
_SCROLL_STORY = frozenset({"word_reveal", "collage"})


def direct(sections: list[dict[str, Any]], budget: str, *, range_variant: str = "") -> list[str]:
    """Spend the budget on the page: change layouts in place, return notes."""
    notes: list[str] = []
    if budget == "expressive":
        return notes

    def first(kind: str) -> dict[str, Any] | None:
        return next((s for s in sections if s["section_type_id"] == kind), None)

    hero = first("hero")
    has_picture = bool(hero and hero["content"].get("image_asset_id"))
    if hero:
        variant = str(hero.get("layout_variant") or "")
        # A quiet opening: one photograph that opens slowly. (The experience
        # layer already gives calm brands its other quiet scene, depth; only a
        # loud scene is replaced here, so quiet sites keep their variety.)
        quiet = "cinematic_zoom" if has_picture else "aurora"
        if budget == "restrained" and variant in _LOUD_HEROES:
            hero["layout_variant"] = quiet
            notes.append(f"hero {variant} → {quiet}: one slow moving picture, not a show")
        elif budget == "gentle" and variant == "kinetic":
            hero["layout_variant"] = quiet
            notes.append(f"hero kinetic → {quiet}: too loud for this brand")

    if budget == "restrained":
        band = first("marquee")
        if band:
            sections.remove(band)
            notes.append("moving band removed: the page stays still")

    showcase = next((s for s in sections if s["section_type_id"] in {"product_showcase", "category_showcase"}
                     and s["content"].get("anchor") == "shop"), None)
    story = first("about")
    range_moves = bool(showcase and showcase.get("layout_variant") in _SCROLL_RANGE)
    story_moves = bool(story and story.get("layout_variant") in _SCROLL_STORY)

    def still_range() -> None:
        assert showcase is not None
        before = str(showcase["layout_variant"])
        if before == "menu_book":
            return  # a menu with chapters is how a menu reads, not an effect
        pictured = sum(1 for i in showcase["content"].get("items") or [] if i.get("image_asset_id"))
        after = "spotlight" if pictured >= 3 else (range_variant or "bento")
        if showcase["section_type_id"] == "category_showcase":
            after = "bento"
        showcase["layout_variant"] = after
        notes.append(f"range {before} → {after}: no pinned scroll here")

    def still_story() -> None:
        assert story is not None
        before = str(story["layout_variant"])
        after = "sticky_split" if story["content"].get("image_asset_id") else "text_only"
        story["layout_variant"] = after
        notes.append(f"story {before} → {after}: one scroll moment is enough")

    if budget == "restrained":
        if range_moves:
            still_range()
        if story_moves:
            still_story()
    elif range_moves and story_moves:
        # One scroll moment beyond the hero: the range is what people came for.
        still_story()
    return notes
