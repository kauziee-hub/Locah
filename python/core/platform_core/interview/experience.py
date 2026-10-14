"""How a business's website moves, and which scenes it is built from.

Design families (design_system) decide the type, palette and geometry of a
site. That alone left every site the same skeleton — a hero, a grid of cards,
a story beside a picture, a band, contact — in different clothes. The
experience decides the *composition and motion*:

* **motion** — the site's motion language: ``silk`` (slow, long eases —
  refined, editorial), ``snap`` (fast, punchy — bold commerce, fitness),
  ``float`` (soft, a little springy — playful, friendly), ``calm`` (gentle
  fades only — care, law, finance: trust first);
* **hero** — a scene, not a banner: a picture that opens to full-bleed, the
  business's pictures on a turning 3D ring, a tilted wall of pictures that
  straightens, poster type around a growing picture, floating framed cards,
  or a living gradient in the brand colours when there are no photos;
* **catalogue** — a real menu with chapters, a pinned horizontal rail, a bento
  grid, a spotlight of signature things, or stacked cards;
* **story** — lit word by word as it is read, a picture that holds while the
  story scrolls, or a collage;
* **closing** — a giant closing line, and a moving band of the business's own
  words where it has some.

Every choice is a renderer-backed layout (apps/web .../experience); the model
may choose among the ones this business's real content can carry — a ring
needs pictures, a menu needs dishes — and ``choose_experience`` is the
authority. Choices are stable for a business (seeded by its id), and two
businesses with the same evidence do not get the same site.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from platform_core.interview.models import BusinessBlueprint

EXPERIENCE_VERSION = "experience-v1"

MOTIONS = ("silk", "snap", "float", "calm")
HERO_SCENES = ("cinematic_zoom", "orbit", "plane", "kinetic", "depth", "aurora")
CATALOGUE_LAYOUTS = ("menu_book", "rail", "bento", "spotlight", "stack")
STORY_LAYOUTS = ("word_reveal", "sticky_split", "collage")

# What each choice is, for the model choosing among them.
DESCRIBE: dict[str, str] = {
    "silk": "slow, long, refined movement — editorial food, hospitality, premium",
    "snap": "fast, punchy, confident movement — bold commerce, fitness",
    "float": "soft, slightly springy movement — playful, friendly, local",
    "calm": "gentle fades only — care, law, finance; trust before spectacle",
    "cinematic_zoom": "the cover picture starts framed beside the headline and opens to full-bleed as you scroll",
    "orbit": "the business's own pictures on a slowly turning 3D ring beside the headline (needs 4+ pictures)",
    "plane": "a tilted wall of the business's pictures that straightens toward you as you scroll (needs 4+)",
    "kinetic": "poster-sized type that pulls apart around a growing picture — loud, typographic",
    "depth": "one photograph with framed pictures floating over it at different depths",
    "aurora": "a slowly moving gradient in the brand colours behind large type — for sites without photos",
    "menu_book": "a real menu: chapters by category, a rail that follows the reader, diet marks, prices",
    "rail": "a horizontal run of large picture cards, held in place while it travels",
    "bento": "an asymmetric grid of a curated range, the best thing largest",
    "spotlight": "one signature thing per row, very large, alternating sides",
    "stack": "cards that stick and stack as you scroll — plans, services, projects",
    "word_reveal": "the story set large, each word lighting up as it is read",
    "sticky_split": "a tall picture that holds still while the story scrolls beside it",
    "collage": "the story beside pictures overlapping at different depths",
}


@dataclass(frozen=True)
class Experience:
    motion: str
    hero: str
    catalogue: str
    story: str
    cta: str  # cta_band layout: "giant" or "" (keep the composer's)
    marquee: str  # "" | "band" | "outline"
    intro: bool
    grain: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def theme(self) -> dict[str, Any]:
        """What the renderer reads (theme.experience)."""
        return {
            "version": EXPERIENCE_VERSION, "motion": self.motion, "hero": self.hero,
            "catalogue": self.catalogue, "story": self.story, "intro": self.intro, "grain": self.grain,
            "progress": self.motion != "calm", "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class Content:
    """What this page really has to compose with."""

    pictures: int  # distinct pictures the page will show (owner's or drafts)
    hero_picture: bool
    items: int  # named things in the catalogue section
    pictured_items: int
    categories: int
    story_chars: int
    story_picture: bool
    pictured_categories: int = 0


def _stable(seed: str, salt: str) -> int:
    return int(hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()[:8], 16)


def _pick(options: list[str], seed: str, salt: str) -> str:
    """A stable, weighted choice: the best fit most often, the others sometimes."""
    if not options:
        return ""
    weights = [5, 3, 2, 1, 1, 1][: len(options)]
    roll = _stable(seed, salt) % sum(weights)
    for option, weight in zip(options, weights):
        if roll < weight:
            return option
        roll -= weight
    return options[0]


def content_of(sections: list[dict[str, Any]], expected_pictures: int = 0) -> Content:
    """Read the composed page: how many pictures, items and words it carries.

    ``expected_pictures`` counts pictures the media plan will still draw, so the
    first build (before drafts exist) already composes for the finished site.
    """
    asset_ids: set[str] = set()
    items = pictured = categories = pictured_categories = story_chars = 0
    hero_picture = story_picture = False
    for section in sections:
        content = section.get("content") or {}
        kind = section.get("section_type_id")
        if content.get("image_asset_id"):
            asset_ids.add(str(content["image_asset_id"]))
        for key in ("items", "categories"):
            for row in content.get(key) or []:
                if isinstance(row, dict) and row.get("image_asset_id"):
                    asset_ids.add(str(row["image_asset_id"]))
        if kind == "hero":
            hero_picture = bool(content.get("image_asset_id"))
        if kind == "product_showcase":
            rows = [r for r in content.get("items") or [] if isinstance(r, dict)]
            items = len(rows)
            pictured = sum(1 for r in rows if r.get("image_asset_id"))
            categories = len(content.get("categories") or []) or len({r.get("category") for r in rows if r.get("category")})
        if kind == "category_showcase":
            rows = [r for r in content.get("items") or [] if isinstance(r, dict)]
            categories = max(categories, len(rows))
            pictured_categories = sum(1 for r in rows if r.get("image_asset_id"))
        if kind == "about":
            story_chars = len(str(content.get("body") or ""))
            story_picture = bool(content.get("image_asset_id"))
    return Content(
        pictures=max(len(asset_ids), expected_pictures), hero_picture=hero_picture or expected_pictures > 0,
        items=items, pictured_items=pictured, categories=categories, story_chars=story_chars,
        story_picture=story_picture, pictured_categories=pictured_categories,
    )


def motion_for(dims: dict[str, Any], family: str) -> tuple[str, str]:
    """The motion language, from how the business presents itself."""
    personality = str(dims.get("personality", ""))
    energy = str(dims.get("energy", ""))
    trust = str(dims.get("trust", ""))
    mode = str(dims.get("service_mode", ""))
    if trust == "high" and (mode in {"care", "advisory"} or personality in {"calm", "technical"}):
        return "calm", "trust first: gentle movement"
    if family in {"calm_professional", "technical_b2b"} and personality != "bold":
        return "calm", f"{family}: gentle movement"
    if energy == "high" or personality == "bold" or family in {"monumental", "modern_commerce"}:
        return "snap", "high energy: punchy movement"
    if personality in {"playful", "friendly"} or family in {"playful_editorial", "local_friendly"}:
        return "float", "playful: soft, springy movement"
    return "silk", "refined: slow, long movement"


def hero_options(arche: str, motion: str, c: Content, dims: dict[str, Any]) -> list[str]:
    """Hero scenes this business can really carry, best-suited first.

    The opening-picture scene (cinematic_zoom) suits almost anyone, so it is
    the fallback at the end of each list, not the default at its head.
    """
    personality = str(dims.get("personality", ""))
    many = c.pictures >= 4
    layered = c.pictures >= 2
    if not c.hero_picture and not c.pictures:
        return ["aurora", "kinetic"] if motion != "calm" else ["aurora"]
    if motion == "calm":
        # Quiet, but never a flat banner: layers that drift, or a picture that
        # opens — and with no photographs, a slow gradient.
        return ["depth", "cinematic_zoom"] if layered else ["cinematic_zoom", "aurora"]
    options: list[str]
    if arche in {"menu_commerce", "product_commerce"}:
        if motion == "snap":
            options = (["plane"] if many else []) + ["kinetic", "cinematic_zoom"]
        elif motion == "float":
            options = (["orbit", "plane"] if many else ["depth"]) + ["cinematic_zoom"]
        else:
            options = (["plane", "orbit"] if many else []) + ["depth", "cinematic_zoom"]
    elif arche == "membership_fitness":
        options = ["kinetic", "depth", "cinematic_zoom"] if personality != "calm" else ["depth", "cinematic_zoom"]
    elif arche in {"real_estate_projects", "project_portfolio"}:
        options = ["depth"] + (["plane"] if many else []) + ["cinematic_zoom"]
    elif arche == "service_appointment":
        if motion == "snap":
            options = ["kinetic", "depth", "cinematic_zoom"]
        elif motion == "float" and many:
            options = ["orbit", "depth", "cinematic_zoom"]
        else:
            options = ["depth", "cinematic_zoom"]
    elif arche == "b2b_rfq":
        options = ["depth", "cinematic_zoom"]
    else:
        options = ["kinetic", "depth", "cinematic_zoom"] if motion in {"snap", "float"} else ["depth", "cinematic_zoom"]
    if not layered:
        options = [o for o in options if o != "depth"]
    return options or ["cinematic_zoom"]


def catalogue_options(arche: str, offering: str, c: Content) -> list[str]:
    """How the range is presented: what a visitor of this trade expects."""
    if c.items == 0:
        # Known only as categories: a rail of them when they are pictured,
        # else an asymmetric grid.
        if c.categories >= 3:
            return ["rail", "bento"] if c.pictured_categories >= 3 else ["bento"]
        return []
    if offering == "menu" or arche == "menu_commerce":
        # A menu is read like a menu, whatever its size.
        return ["menu_book"] if c.items >= 5 else ["bento", "menu_book"]
    if offering == "weighed_product":
        # Cuts by the kg are read like a price list, chapter by chapter, or as
        # one board per kind of meat with its cuts.
        return ["menu_book", "category_boards"]
    if offering in {"plan", "class"} or arche == "membership_fitness":
        return ["stack"]
    if offering in {"property", "portfolio"} or arche in {"real_estate_projects", "project_portfolio"}:
        return ["spotlight", "stack"] if c.pictured_items or c.pictures >= 3 else ["stack"]
    if offering in {"service", "stay"} or arche == "service_appointment":
        # A salon or clinic has a service menu: names, durations, prices.
        return ["menu_book", "stack"] if c.items >= 6 else ["stack", "bento"]
    if arche == "b2b_rfq":
        return ["bento", "menu_book"] if c.items >= 6 else ["bento"]
    # Products: pictured ranges ride a rail or fill a bento; long unpictured
    # ranges read best as a priced list.
    if c.pictured_items >= 3:
        return ["rail", "bento"]
    if c.items >= 10:
        return ["menu_book", "bento"]
    return ["bento", "stack"]


def story_options(motion: str, c: Content, personality: str) -> list[str]:
    if c.story_chars == 0:
        return []
    options: list[str] = []
    if 90 <= c.story_chars <= 700 and personality != "playful":
        options.append("word_reveal")
    if c.story_picture:
        options.append("sticky_split")
        if c.pictures >= 3 and motion in {"float", "silk"}:
            options.append("collage")
    if motion == "calm":
        options = [o for o in options if o != "collage"]
    return options


def choose_experience(
    bp: BusinessBlueprint,
    *,
    archetype: str,
    family: str,
    dims: dict[str, Any],
    sections: list[dict[str, Any]],
    expected_pictures: int = 0,
    choices: dict[str, Any] | None = None,
    seed: str = "",
) -> Experience:
    """The experience for this site. The model's choices win only when they
    are among the options this business's content can really carry."""
    choices = choices or {}
    seed = seed or str(bp.business_id)
    c = content_of(sections, expected_pictures)
    personality = str(dims.get("personality", ""))
    offering = str(dims.get("offering", ""))
    reasons: list[str] = []

    motion, why = motion_for(dims, family)
    said = str(choices.get("motion") or "")
    if said in MOTIONS and not (motion == "calm" and said == "snap"):
        motion, why = said, "chosen for this business"
    reasons.append(f"motion {motion} — {why}")

    def decide(role: str, options: list[str]) -> str:
        wanted = str(choices.get(role) or "")
        if wanted in options:
            reasons.append(f"{role} {wanted} — chosen for this business")
            return wanted
        # The first option is the best fit; a stable, weighted choice among
        # the rest keeps two similar businesses from sharing one skeleton.
        picked = _pick(options, seed, role) if options else ""
        if picked:
            reasons.append(f"{role} {picked} — from {', '.join(options)}")
        return picked

    hero = decide("hero", hero_options(archetype, motion, c, dims))
    catalogue = decide("catalogue", catalogue_options(archetype, offering, c))
    story = decide("story", story_options(motion, c, personality))

    energy = str(dims.get("energy", ""))
    cta = "giant" if motion in {"snap", "silk"} and (c.pictures or energy == "high") else ""
    if motion == "float" and _stable(seed, "cta") % 2:
        cta = "giant"
    marquee = ""
    if motion != "calm" and c.categories >= 3:
        marquee = "band" if motion in {"snap", "float"} else "outline"
    intro = motion in {"silk", "snap"} and str(dims.get("positioning", "")) in {"premium", "heritage", "modern"}
    grain = family in {"editorial_warm", "premium_dark", "portfolio_sketchbook"}
    return Experience(motion=motion, hero=hero, catalogue=catalogue, story=story, cta=cta, marquee=marquee,
                      intro=intro, grain=grain, reasons=tuple(reasons))


def options_for_model(
    archetype: str, family: str, dims: dict[str, Any], *, pictures: int, items: int, story_chars: int,
) -> dict[str, list[dict[str, str]]]:
    """The choices offered to the model, each with what it is — only the
    ones this business's content could carry."""
    c = Content(pictures=pictures, hero_picture=pictures > 0, items=items, pictured_items=min(items, pictures),
                categories=0, story_chars=story_chars, story_picture=pictures > 1)
    motion, _ = motion_for(dims, family)
    motions = [m for m in MOTIONS if not (motion == "calm" and m == "snap")]
    heroes: list[str] = []
    for m in motions:
        for option in hero_options(archetype, m, c, dims):
            if option not in heroes:
                heroes.append(option)
    roles = {
        "motion": motions,
        "hero": heroes,
        "catalogue": catalogue_options(archetype, str(dims.get("offering", "")), c),
        "story": story_options(motion, c, str(dims.get("personality", ""))),
    }
    return {role: [{"id": o, "is": DESCRIBE.get(o, o)} for o in opts] for role, opts in roles.items() if opts}


_CATEGORY_WORD = re.compile(r"^[\w&' -]{2,28}$")


def marquee_words(sections: list[dict[str, Any]], badges: list[str]) -> list[str]:
    """The business's own short words for the moving band: its categories,
    then the true facts under its headline. Nothing invented."""
    words: list[str] = []
    for section in sections:
        content = section.get("content") or {}
        if section.get("section_type_id") in {"product_showcase", "category_showcase"}:
            for row in content.get("categories") or content.get("items") or []:
                name = str(row.get("name") if isinstance(row, dict) else "").strip()
                if name and _CATEGORY_WORD.match(name) and name.casefold() not in {w.casefold() for w in words}:
                    words.append(name)
            for name in content.get("filters") or []:
                name = str(name).strip()
                if name and _CATEGORY_WORD.match(name) and name.casefold() not in {w.casefold() for w in words}:
                    words.append(name)
    for badge in badges:
        badge = badge.strip()
        if badge and len(badge) <= 32 and badge.casefold() not in {w.casefold() for w in words}:
            words.append(badge)
    return words[:10]
