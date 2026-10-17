"""A website's design DNA: what makes two businesses of one trade two brands.

The design family (design_system) sets a site's broad language and palette;
the experience (experience.py) its scenes. Two family butchers with the same
answers still came out as the same page in the same type. The DNA is the next
layer of decisions — an art director's, made in order:

1. **concept** — one coherent art direction for this brand, the way a studio
   pitches one idea, never a bag of random traits. One butcher is *noir
   editorial* (dark, huge close-up photography, condensed capitals, sharp cuts,
   one cinematic reveal); another *warm craft* (cream paper, a hand-painted
   accent, story first, a market-board catalogue); a third *quiet luxury*
   (black and white, vast whitespace, full-screen photographs, almost no
   motion). Concepts fit some families and businesses better than others; the
   pick among the fitting ones is a stable draw seeded by the business.
2. **traits, inside the concept** — the typefaces (from a library wider than
   any family's), how a headline carries its accent (italic, outline, a painted
   marker, a handwritten script, a gradient, tight capitals), the ground
   (paper, grain, dots, a drafting grid, the business's own motif), the edge
   between sections, buttons, header, cards, the shape pictures are cut to, a
   trailing cursor, which sections turn dark.
3. **space, photo and motion budget** — how much room the page breathes with,
   how photographs are treated (macro close-ups, warm, full-bleed, clean), and
   how much may move. The budget is the motion director's brief: a restrained
   brand gets one moving moment, an expressive one may move everywhere — never
   every card animated because it can be.

Every value maps to rules in packages/ui/src/site-dna.css (and the budget to
the motion runtime); the renderer drops anything else.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

DNA_VERSION = "dna-v2"

SERIF = frozenset({"dmserif", "bodoni", "youngserif", "italiana", "fraunces", "playfair", "cormorant", "newsreader"})
BUDGETS = ("restrained", "gentle", "signature", "expressive")


@dataclass(frozen=True)
class DesignDna:
    display: str
    body: str
    headline: str
    texture: str
    pattern: str
    divider: str
    button: str
    navstyle: str
    cardstyle: str
    shape: str
    cursor: str
    invert: str
    concept: str = ""
    space: str = "regular"
    photo: str = "clean"
    budget: str = "gentle"

    def theme(self) -> dict[str, Any]:
        return {"version": DNA_VERSION, **asdict(self)}


@dataclass(frozen=True)
class Concept:
    key: str
    describe: str
    families: dict[str, float]  # how well it sits on each design family's palette and language
    fits: dict[str, float]  # "dimension=value" -> how much this business suits it
    display: tuple[str, ...]  # preferred first
    headline: tuple[str, ...]
    body: tuple[str, ...]
    texture: tuple[str, ...]
    pattern: tuple[str, ...]
    divider: tuple[str, ...]
    button: tuple[str, ...]
    navstyle: tuple[str, ...]
    cardstyle: tuple[str, ...]
    shape: tuple[str, ...]
    cursor: tuple[str, ...]
    invert: tuple[str, ...]
    space: str
    photo: str
    budget: str


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "noir_editorial",
        "dark editorial: huge close-up photography, condensed capitals, sharp cuts, one cinematic reveal",
        {"premium_dark": 3, "monumental": 3, "modern_commerce": 1.5},
        {"personality=bold": 3, "energy=high": 2, "positioning=premium": 2, "positioning=modern": 2,
         "service_mode=food": 1, "service_mode=retail": 1},
        ("bigshoulders", "anton", "archivo", "syne"), ("caps", "outline"), ("dm", "manrope"),
        ("grain", "none"), ("rays",), ("slant", "none"), ("sharp", "underline"), ("overlay", "bar"),
        ("flat", "bordered"), ("rect", "slant"), ("dot", "none"), ("bold", "bands"),
        "regular", "macro", "signature",
    ),
    Concept(
        "warm_craft",
        "warm craft: cream paper, a hand-painted accent, story first, a market-board catalogue",
        {"editorial_warm": 3, "local_friendly": 2.5, "playful_editorial": 1},
        {"positioning=heritage": 3, "personality=warm": 3, "personality=friendly": 1.5,
         "service_mode=food": 2, "service_mode=craft": 2, "service_mode=making": 1.5},
        ("youngserif", "fraunces", "dmserif"), ("script", "marker", "italic"), ("dm", "manrope", "outfit"),
        ("paper", "pattern"), ("kolam", "arcs", "checks"), ("ticket", "curve"), ("soft", "pill"),
        ("centered", "bar"), ("elevated", "offset", "bordered"), ("arch", "rounded"), ("none",),
        ("bands", "calm"), "regular", "warm", "gentle",
    ),
    Concept(
        "quiet_luxury",
        "quiet luxury: black and white, vast whitespace, full-screen photographs, restrained motion",
        {"premium_dark": 3, "airy_property": 2.5, "calm_professional": 1.5, "editorial_warm": 1},
        {"positioning=premium": 3, "personality=refined": 3, "personality=calm": 1.5, "service_mode=wellbeing": 1.5,
         "service_mode=hospitality": 2},
        ("italiana", "bodoni", "cormorant", "newsreader"), ("plain", "italic"), ("manrope", "dm"),
        ("none",), ("arcs",), ("none",), ("underline", "outline"), ("centered", "overlay"),
        ("flat",), ("rect",), ("none", "dot"), ("calm", "bands"), "airy", "full", "restrained",
    ),
    Concept(
        "fresh_market",
        "bright and quick: clean modern type, a vivid accent, rounded cards, snappy motion",
        {"modern_commerce": 3, "local_friendly": 2, "playful_editorial": 1},
        {"positioning=modern": 2, "positioning=value": 2, "positioning=everyday": 1.5, "service_mode=retail": 1.5,
         "service_mode=food": 1, "energy=high": 1, "journey=order": 1},
        ("syne", "unbounded", "spacegrotesk", "outfit", "archivo"), ("gradient", "marker", "plain"), ("dm", "manrope"),
        ("dots", "grid", "none"), ("waves", "rays"), ("none", "curve", "wave"), ("pill", "soft"),
        ("floating", "bar"), ("elevated", "glass"), ("rounded", "blob"), ("none",), ("bold", "calm"),
        "regular", "clean", "expressive",
    ),
    Concept(
        "playful_pop",
        "playful: chunky friendly type, offset cards, wavy edges, springy motion",
        {"playful_editorial": 3, "local_friendly": 2},
        {"personality=playful": 4, "personality=friendly": 1.5, "service_mode=learning": 1},
        ("bricolage", "youngserif", "unbounded"), ("marker", "script", "outline"), ("dm", "outfit"),
        ("dots", "pattern"), ("checks", "waves"), ("wave", "curve"), ("pill",), ("floating",),
        ("offset",), ("blob", "rounded"), ("none",), ("bold",), "regular", "clean", "expressive",
    ),
    Concept(
        "calm_care",
        "calm and trustworthy: a gentle serif, soft cards, generous space, fades only",
        {"calm_professional": 4, "airy_property": 2, "editorial_warm": 0.5},
        {"trust=high": 3, "personality=calm": 3, "service_mode=care": 2, "service_mode=advisory": 2,
         "service_mode=learning": 1.5, "service_mode=wellbeing": 1},
        ("newsreader", "fraunces", "manrope", "outfit"), ("plain", "italic"), ("manrope", "dm"),
        ("none", "paper"), ("waves",), ("curve", "none"), ("soft", "pill"), ("bar", "floating", "centered"),
        ("elevated", "flat"), ("rounded", "arch"), ("none",), ("calm",), "airy", "clean", "restrained",
    ),
    Concept(
        "technical_grid",
        "engineered: grotesk type on a drafting grid, sharp bordered cards, precise motion",
        {"monumental": 1.5, "modern_commerce": 1.5, "calm_professional": 1.5},
        {"personality=technical": 4, "audience=b2b": 2},
        ("spacegrotesk", "plex", "archivo"), ("plain", "caps", "outline"), ("plex", "dm"),
        ("grid",), ("rays",), ("none", "slant"), ("sharp",), ("bar",), ("bordered",), ("rect",), ("none",),
        ("bands",), "dense", "clean", "gentle",
    ),
    Concept(
        "kinetic_sport",
        "kinetic: poster type, slanted cuts, hard contrast, punchy motion",
        {"monumental": 4, "modern_commerce": 1},
        {"energy=high": 3, "personality=bold": 2, "offering=plan": 2, "offering=class": 2},
        ("bigshoulders", "anton", "unbounded"), ("caps", "outline"), ("dm", "manrope"),
        ("grain", "none"), ("rays",), ("slant",), ("sharp",), ("overlay", "bar"), ("bordered", "offset"),
        ("slant", "rect"), ("dot", "none"), ("bold",), "regular", "macro", "expressive",
    ),
)
BY_KEY = {c.key: c for c in CONCEPTS}


def _draw(options: list[tuple[str, float]], seed: str, salt: str) -> str:
    """A stable weighted choice: the same seed always draws the same value."""
    weighted = [(value, int(round(weight * 10))) for value, weight in options]
    weighted = [(value, weight) for value, weight in weighted if weight > 0]
    if not weighted:
        return ""
    total = sum(weight for _, weight in weighted)
    roll = int(hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()[:8], 16) % total
    for value, weight in weighted:
        if roll < weight:
            return value
        roll -= weight
    return weighted[0][0]


def _ranked(values: tuple[str, ...]) -> list[tuple[str, float]]:
    """A concept's preferences, the first most likely."""
    return [(v, float(len(values) - i) + 1) for i, v in enumerate(values)]


def concept_weights(dims: dict[str, Any], family: str) -> dict[str, float]:
    """How well each concept suits this business on this family."""
    said = {f"{k}={v}" for k, v in dims.items() if isinstance(v, str)}
    out: dict[str, float] = {}
    for concept in CONCEPTS:
        fit = 1 + sum(w for key, w in concept.fits.items() if key in said)
        out[concept.key] = concept.families.get(family, 0.25) * fit
    return out


def choose_dna(dims: dict[str, Any], *, family: str, archetype: str, motion: str, seed: str,
               concept: str | None = None) -> DesignDna:
    personality = str(dims.get("personality") or "friendly")
    mode = str(dims.get("service_mode") or "none")
    trust = str(dims.get("trust") or "normal")
    calm = motion == "calm" or (trust == "high" and mode in {"care", "advisory"})

    weights = concept_weights(dims, family)
    if calm:
        # Trust first: only a quiet direction.
        weights = {k: w for k, w in weights.items() if BY_KEY[k].budget in {"restrained", "gentle"}}
    # Only the strongest few compete, so a clinic never draws a poster concept.
    best = max(weights.values())
    shortlist = [(k, w) for k, w in weights.items() if w >= best * 0.45]
    # The creative director's pick stands when it is one of the fitting ones.
    chosen = BY_KEY[concept] if concept in dict(shortlist) else BY_KEY[_draw(shortlist, seed, "concept")]

    display = _draw(_ranked(chosen.display), seed, "display")
    serif = display in SERIF
    headline = _draw(_ranked(chosen.headline), seed, "headline")
    if headline == "caps" and serif:
        headline = "italic"
    if calm:
        headline = "italic" if serif else "plain"
    cursor = "none" if calm or personality == "calm" else _draw(_ranked(chosen.cursor), seed, "cursor")
    budget = "restrained" if calm else chosen.budget

    del archetype  # the family's palette already carries it
    return DesignDna(
        display=display, body=_draw(_ranked(chosen.body), seed, "body"), headline=headline,
        texture=_draw(_ranked(chosen.texture), seed, "texture"), pattern=_draw(_ranked(chosen.pattern), seed, "pattern"),
        divider=_draw(_ranked(chosen.divider), seed, "divider"), button=_draw(_ranked(chosen.button), seed, "button"),
        navstyle=_draw(_ranked(chosen.navstyle), seed, "nav"), cardstyle=_draw(_ranked(chosen.cardstyle), seed, "cards"),
        shape=_draw(_ranked(chosen.shape), seed, "shape"), cursor=cursor,
        invert="calm" if calm else _draw(_ranked(chosen.invert), seed, "invert"),
        concept=chosen.key, space=chosen.space, photo=chosen.photo, budget=budget,
    )
