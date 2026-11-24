"""The one place LOCAH writes image prompts for a website.

Before this, two systems disagreed: the MediaDirector asked for realistic
draft photographs in the site's own style, while the older helpers asked for
"abstract artwork that must not read as a photograph" keyed only on a
business type. A site could get one of each. Now every picture for a site —
drawn by the build, by the owner's request in the interview, or from the
editor's "Generate a picture" — is written here, from the same *shoot brief*,
so all of a site's pictures look like one shoot for one brand.

What a prompt may show follows the media truth policy
(`interview.models.TruthClass`):

* mood / representative → an editorial photograph (a kind of dish, a kind of
  room, the trade's atmosphere) — never captioned or presented as theirs;
* graphic → texture or illustration, where realism would mislead;
* factual → never drawn: only the owner's own asset can fill it.

Prompts never carry the transcript, prices, numbers, people, text or logos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "media-v4.2"

# A real brand in a drawn picture reads as an endorsement the business never
# had (the first real gym hero printed an equipment maker's name on the rack
# and plates). Keep the equipment realistic; keep it unbranded.
_UNBRANDED = (
    "Everything unbranded: no brand names, trademarks or manufacturer markings on equipment, "
    "machines, tools or vehicles; no branded logos; no branded clothing; no branded product packaging."
)
_NEVER = (
    "One continuous photograph of a single scene — no collage, split panels, borders, frames or inset "
    "pictures. No text, words, letters, numbers, logos, labels, packaging, price tags, signage or "
    f"watermarks. {_UNBRANDED} No people, faces or hands."
)
_NEVER_GRAPHIC = (
    f"No text, letters, numbers, logos or signage. {_UNBRANDED} No people or faces. Not a photograph "
    "of a real place or product."
)


@dataclass(frozen=True)
class ShootBrief:
    """What every picture of one website shares: one light, one lens, one world."""

    world: str  # the trade's material world ("rustic clay and brass on banana leaf, …")
    light: str
    lens: str
    grade: str
    palette: tuple[str, ...] = ()

    def sentence(self) -> str:
        colours = ", ".join(c for c in self.palette if c)
        accents = f" Colour accents that sit with {colours}." if colours else ""
        return (f"Part of one editorial series for this brand: {self.world}. Light: {self.light}. "
                f"Lens: {self.lens}. Colour grade: {self.grade}.{accents}")


# THE DRAWING RULE (founder, firm, 2026-11-24): a drawn picture may show
# scenery, the region, mood, texture or abstract art — never rooms, food,
# dishes, staff, products, interiors, amenities or buildings a visitor would
# read as the real business. Real things come from the owner or from stock.
# Checked on every drawing at the provider boundary (`unsafe_drawing`).
FORBIDDEN_IN_DRAWINGS = re.compile(
    r"\b(rooms?|bed(?:room)?s?|suites?|interiors?|lobby|lobbies|reception|bathrooms?|pools?|spas?|"
    r"verandas?|verandahs?|balcon(?:y|ies)|terraces?|lounges?|amenit(?:y|ies)|walls?|floors?|ceilings?|"
    r"kitchens?|cooking|food|foods|dish(?:es)?|plates?|bowls?|cups?|mugs?|meals?|breakfast|lunch|dinner|"
    r"snacks?|cakes?|breads?|coffee|tea|drinks?|cocktails?|menus?|biryani|curry|"
    r"people|person|persons|faces?|hands?|staff|chefs?|waiters?|customers?|guests?|patients?|doctors?|"
    r"stylists?|trainers?|"
    r"products?|shelf|shelves|counters?|shops?|stores?|showrooms?|packaging|bottles?|jars?|"
    r"equipment|machines?|barbells?|racks?|tools?|chairs?|tables?|"
    r"buildings?|houses?|cottages?|villas?|bungalows?|hotels?|resorts?|rooftops?|facades?|storefronts?|"
    r"offices?|clinics?|salons?|gyms?|studios?|restaurants?|cafes?|caf\u00e9s?)\b", re.I)


def unsafe_drawing(prompt: str) -> str:
    """The first forbidden thing a drawing prompt would show, or "" when it is safe.

    The prompt's own "never" sentences are not what it shows, so they are left
    out; a logo (no Subject / Motif / series line) is not a scene and passes.
    """
    text = prompt or ""
    if not any(k in text for k in ("Subject:", "Motif:", "Part of one editorial series")):
        return ""
    for sentence in (_NEVER, _NEVER_GRAPHIC):
        text = text.replace(sentence, " ")
    found = FORBIDDEN_IN_DRAWINGS.search(text)
    return found.group(0).casefold() if found else ""


def drawing_prompt(subject: str, brief: "ShootBrief", *, abstract: bool = False) -> str:
    """A drawing that shows only what the rule allows: the subject, the site's
    light and grade — never the site's photo style, which names what it sells."""
    kind = "An abstract editorial image" if abstract else "A calm editorial landscape photograph"
    return (f"{kind}. Subject: {subject}. Light: {brief.light}. Colour grade: {brief.grade}. "
            "Wide, uncluttered composition with open, quiet space.")


# Light and grade follow the site's ground: a dark site is shot low-key, a light
# one airy. The world itself comes from the direction's image style.
_LOW_KEY = ("low-key directional side light with deep shadows", "rich, deep, slightly desaturated")
# Not "from a window": that put a hotel's landscape behind a bedroom window.
_AIRY = ("soft natural daylight, gentle shadows", "clean, bright and natural")


def shoot_brief(direction: Any) -> ShootBrief:
    """The brief for one site, from its creative direction (duck-typed: the
    interview's CreativeDirection or the `creative_direction` dict a draft's
    theme carries)."""

    def get(key: str, default: Any = "") -> Any:
        if isinstance(direction, dict):
            return direction.get(key, default)
        return getattr(direction, key, default)

    palette = get("palette", {}) or {}
    if not isinstance(palette, dict):
        palette = palette.model_dump() if hasattr(palette, "model_dump") else {}
    dark = palette.get("mode") == "dark"
    light, grade = _LOW_KEY if dark else _AIRY
    world = str(get("image_style", "") or "warm, natural editorial photography of the trade's materials")
    lens = "50mm, shallow depth of field, eye-level or slightly above"
    if str(get("hero", "")) in {"airy_split", "full_width"}:
        lens = "35mm, straight verticals, generous negative space"
    return ShootBrief(world=world, light=light, lens=lens, grade=grade,
                      palette=tuple(str(palette.get(k, "")) for k in ("primary", "accent") if palette.get(k)))


# How the hero picture must be framed for the composition that will hold it.
HERO_FRAMING = {
    "cinematic": "Wide composition, darker calm space on the left third for a large headline.",
    "editorial_overlay": "Wide table-top composition, calm darker space on the left for a headline, "
                         "the subject on the right two-thirds.",
    "full_width": "Wide composition with calm space on the left for a headline.",
    "commerce_split": "The subject fills the frame, centred, photographed close on a dark surface.",
    "airy_split": "Architecture on the right, open bright sky and space on the left.",
    "editorial_split": "The subject fills the frame, softly lit.",
    "image_left": "The subject fills the frame, softly lit.",
    "image_right": "The subject fills the frame, softly lit.",
}


def aspect_for_hero(hero: str) -> str:
    return "16:9" if hero in {"cinematic", "editorial_overlay", "full_width"} else "4:3"


def _clean(text: str) -> str:
    """Owner words only, and nothing that reads as a number, a price or a claim."""
    return re.sub(r"\s+", " ", re.sub(r"[\d₹$]+", "", text or "")).strip(" ,.-")[:160]


def build_prompt(
    *,
    subject: str,
    purpose: str,
    truth_class: str,
    brief: ShootBrief,
    trade: str,
    hero_style: str = "",
    framing: str = "",
) -> str:
    """One image prompt. Raises for a factual slot: those are never drawn.
    `framing` replaces the purpose's own when the trade's picture differs."""
    if truth_class == "factual":
        raise ValueError("a factual picture is never generated — it must be the owner's own")
    subject = _clean(subject) or _clean(trade) or "the trade's materials"
    trade = _clean(trade) or "a small local business"
    if truth_class == "graphic":
        return (f"A refined, textured editorial illustration for a small business website ({trade}). "
                f"Motif: {subject}. {brief.sentence()} {_NEVER_GRAPHIC}")
    if framing:
        pass
    elif purpose == "hero":
        framing = HERO_FRAMING.get(hero_style, "The subject fills the frame, softly lit.")
    elif purpose == "story":
        framing = "A quiet, lived-in scene of where the work happens, seen from the side."
    else:
        framing = "The subject fills the frame, centred, styled simply."
    return (f"A realistic, professional editorial photograph for a small business website ({trade}). "
            f"Subject: {subject}. {brief.sentence()} {framing} {_NEVER}")
