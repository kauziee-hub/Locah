"""A website's design DNA: what makes two businesses of one trade two brands.

The design family (design_system) sets a site's broad language and palette;
the experience (experience.py) its scenes. Two family butchers with the same
answers still came out as the same page in the same type. The DNA is the next
layer of decisions — an art director's, made in order:

1. **concept** — one coherent art direction for this brand, the way a studio
   pitches one idea, never a bag of random traits. One butcher is *noir
   editorial* (dark, huge close-up photography, a display serif or condensed
   capitals, sharp cuts, one cinematic reveal); another *warm craft* (cream
   paper, a warm serif italic accent, story first, a market-board catalogue);
   a third *quiet luxury* (black and white, vast whitespace, full-screen
   photographs, almost no motion). Concepts fit some families and businesses better than others; the
   pick among the fitting ones is a stable draw seeded by the business.
2. **traits, inside the concept** — the typefaces (from a library wider than
   any family's), how a headline carries its accent (the display face's own
   italic, one phrase in a serif italic, the phrase knocked back in tone, a
   handwritten script, tight capitals, or a quiet two-tone), the ground
   (paper, grain, dots, a drafting grid, the business's own motif), the edge
   between sections, buttons, header, cards, the shape pictures are cut to, a
   trailing cursor, which sections turn dark.
3. **space, photo and motion budget** — how much room the page breathes with,
   how photographs are treated (macro close-ups, warm, full-bleed, clean), and
   how much may move. The budget is the motion director's brief: a restrained
   brand gets one moving moment, an expressive one may move everywhere — never
   every card animated because it can be.
4. **the signature moment** — the one thing a visitor remembers and would
   describe to a friend (the living photograph, the curved ribbon of the
   range, a ground that changes colour as you read, type that moves on its
   axes, a photograph you zoom through, a cursor that says what a click does,
   pictures that lean with the speed of the scroll). Each concept owns its
   list, preferred first; the draw is seeded by the business; the budget
   decides how many: restrained and gentle brands get one, signature and
   expressive brands a second one (the flourish), never the same twice.

Every value maps to rules in packages/ui/src/site-dna.css (and the budget to
the motion runtime); the renderer drops anything else.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

DNA_VERSION = "dna-v3"

SERIF = frozenset({"dmserif", "bodoni", "youngserif", "italiana", "fraunces", "playfair", "cormorant", "newsreader",
                   "instrumentserif"})
BUDGETS = ("restrained", "gentle", "signature", "expressive")
# The signature moments (references/signature-moments.md). living, ribbon and
# dissolve are WebGL over a real <img> (experience/gl); the rest are scroll
# and pointer choreography (experience/motion.ts + site-dna.css).
SIGNATURES = ("living", "ribbon", "dissolve", "ground_morph", "variable_type", "zoom_through", "cursor_label",
              "velocity_skew")
# Display faces loaded with an axis the type can move on (site-fonts.ts):
# width (Archivo, Instrument Sans, Bricolage), Fraunces's SOFT and WONK, or
# weight. A static face (Young Serif, DM Serif, Plex, Instrument Serif) has
# nothing to move, so variable type is never drawn for it.
MOVING_FACES = frozenset({"fraunces", "archivo", "instrumentsans", "bricolage", "intertight", "spacegrotesk",
                          "bigshoulders", "newsreader", "bodoni", "manrope", "outfit"})


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
    signature: str = "none"
    flourish: str = "none"

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
    signatures: tuple[str, ...] = ()  # the signature moments it may draw, preferred first


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "noir_editorial",
        "dark editorial: huge close-up photography, a display serif or condensed capitals, sharp cuts, "
        "one cinematic reveal",
        {"premium_dark": 3, "monumental": 3, "modern_commerce": 1.5},
        {"personality=bold": 3, "energy=high": 2, "positioning=premium": 2, "positioning=modern": 2,
         "service_mode=food": 1, "service_mode=retail": 1},
        ("instrumentserif", "bodoni", "archivo"), ("none", "caps", "tone", "italic"), ("instrumentsans", "dm"),
        ("grain", "none"), ("rays",), ("slant", "none"), ("sharp", "underline"), ("overlay", "bar"),
        ("flat", "bordered"), ("rect", "slant"), ("dot", "none"), ("bold", "bands"),
        "regular", "macro", "signature",
        # the living photograph at full strength, a ribbon of the range, pictures that
        # lean with the scroll, the ground turning to ink.
        signatures=("living", "ribbon", "velocity_skew", "ground_morph"),
    ),
    Concept(
        "warm_craft",
        "warm craft: cream paper, a warm serif, story first, a market-board catalogue",
        {"editorial_warm": 3, "local_friendly": 2.5, "playful_editorial": 1},
        {"positioning=heritage": 3, "personality=warm": 3, "personality=friendly": 1.5,
         "service_mode=food": 2, "service_mode=craft": 2, "service_mode=making": 1.5},
        ("fraunces", "dmserif", "youngserif"), ("none", "plain", "italic"), ("dm", "manrope"),
        ("paper", "pattern"), ("kolam", "arcs", "checks"), ("none", "ticket"), ("soft", "pill"),
        ("centered", "bar"), ("elevated", "offset", "bordered"), ("arch", "rounded"), ("none",),
        ("bands", "calm"), "regular", "warm", "gentle",
        # paper warming to crust and back, Fraunces softening as it is read, a gentle living photo.
        signatures=("ground_morph", "variable_type", "living"),
    ),
    Concept(
        "quiet_luxury",
        "quiet luxury: black and white, vast whitespace, full-screen photographs, restrained motion",
        {"premium_dark": 3, "airy_property": 2.5, "calm_professional": 1.5, "editorial_warm": 1},
        {"positioning=premium": 3, "personality=refined": 3, "personality=calm": 1.5, "service_mode=wellbeing": 1.5,
         "service_mode=hospitality": 2},
        ("bodoni", "instrumentserif", "cormorant", "newsreader"), ("none", "plain", "italic"), ("manrope", "instrumentsans"),
        ("none",), ("arcs",), ("none",), ("underline", "outline"), ("centered", "overlay"),
        ("flat",), ("rect",), ("none", "dot"), ("calm", "bands"), "airy", "full", "restrained",
        signatures=("dissolve", "zoom_through", "living"),
    ),
    Concept(
        "fresh_market",
        "bright and quick: clean modern type, a vivid accent, rounded cards, snappy motion",
        {"modern_commerce": 3, "local_friendly": 2, "playful_editorial": 1},
        {"positioning=modern": 2, "positioning=value": 2, "positioning=everyday": 1.5, "service_mode=retail": 1.5,
         "service_mode=food": 1, "energy=high": 1, "journey=order": 1},
        ("intertight", "instrumentsans", "bricolage"), ("none", "tone", "plain", "serif"), ("dm", "instrumentsans", "manrope"),
        ("none", "grain"), ("waves", "rays"), ("none",), ("pill", "soft"),
        ("floating", "bar"), ("elevated", "glass"), ("rounded",), ("none",), ("bold", "calm"),
        "regular", "clean", "expressive",
        signatures=("ribbon", "cursor_label"),
    ),
    Concept(
        "playful_pop",
        "playful: chunky friendly type, offset cards, wavy edges, springy motion",
        {"playful_editorial": 3, "local_friendly": 2},
        {"personality=playful": 4, "personality=friendly": 1.5, "service_mode=learning": 1},
        ("bricolage", "fraunces", "youngserif"), ("none", "plain", "script"), ("dm", "outfit"),
        ("dots", "pattern"), ("checks", "waves"), ("wave", "curve"), ("pill",), ("floating",),
        ("offset",), ("blob", "rounded"), ("none",), ("bold",), "regular", "clean", "expressive",
        signatures=("variable_type", "cursor_label", "velocity_skew"),
    ),
    Concept(
        "calm_care",
        "calm and trustworthy: a gentle serif, soft cards, generous space, fades only",
        {"calm_professional": 4, "airy_property": 2, "editorial_warm": 0.5},
        {"trust=high": 3, "personality=calm": 3, "service_mode=care": 2, "service_mode=advisory": 2,
         "service_mode=learning": 1.5, "service_mode=wellbeing": 1},
        ("newsreader", "fraunces", "instrumentsans", "manrope"), ("none", "plain"), ("manrope", "dm"),
        ("none", "paper"), ("waves",), ("none",), ("soft", "pill"), ("bar", "floating", "centered"),
        ("elevated", "flat"), ("rounded", "arch"), ("none",), ("calm",), "airy", "clean", "restrained",
        signatures=("ground_morph", "dissolve"),
    ),
    Concept(
        "technical_grid",
        "engineered: grotesk type on a drafting grid, sharp bordered cards, precise motion",
        {"monumental": 1.5, "modern_commerce": 1.5, "calm_professional": 1.5},
        {"personality=technical": 4, "audience=b2b": 2},
        ("intertight", "spacegrotesk", "plex"), ("none", "tone", "caps"), ("plex", "dm"),
        ("grid",), ("rays",), ("none", "slant"), ("sharp",), ("bar",), ("bordered",), ("rect",), ("none",),
        ("bands",), "dense", "clean", "gentle",
        signatures=("variable_type", "cursor_label"),
    ),
    Concept(
        "kinetic_sport",
        "kinetic: poster type, slanted cuts, hard contrast, punchy motion",
        {"monumental": 4, "modern_commerce": 1},
        {"energy=high": 3, "personality=bold": 2, "offering=plan": 2, "offering=class": 2},
        ("bigshoulders", "archivo"), ("caps", "none"), ("instrumentsans", "dm"),
        ("grain", "none"), ("rays",), ("slant",), ("sharp",), ("overlay", "bar"), ("bordered", "offset"),
        ("slant", "rect"), ("dot", "none"), ("bold",), "regular", "macro", "expressive",
        signatures=("variable_type", "velocity_skew", "living"),
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


def signature_moments(concept: Concept, *, display: str, budget: str, calm: bool, seed: str,
                      unable: frozenset[str] = frozenset()) -> tuple[str, str]:
    """This brand's signature moment and, when its budget allows a second, the flourish.

    From the concept's own list, preferred first, seeded by the business. A
    face with no axis cannot move on one; a restrained brand never gets
    pictures that lean with the scroll; a calm brand never a cursor show.
    Restrained and gentle brands get one moment; signature and expressive
    brands a second, never the same one twice. `unable`: the moments this
    site has nothing to show on (no cover photograph to make live, too few
    pictured things for a ribbon) — never drawn.
    """
    options = [s for s in concept.signatures
               if s not in unable
               and not (s == "variable_type" and display not in MOVING_FACES)
               and not (s == "velocity_skew" and budget == "restrained")
               and not (s == "cursor_label" and calm)]
    if not options:
        return "none", "none"
    signature = _draw(_ranked(tuple(options)), seed, "signature")
    rest = tuple(s for s in options if s != signature)
    if budget in {"restrained", "gentle"} or not rest:
        return signature, "none"
    return signature, _draw(_ranked(rest), seed, "flourish")


def concept_weights(dims: dict[str, Any], family: str) -> dict[str, float]:
    """How well each concept suits this business on this family."""
    said = {f"{k}={v}" for k, v in dims.items() if isinstance(v, str)}
    out: dict[str, float] = {}
    for concept in CONCEPTS:
        fit = 1 + sum(w for key, w in concept.fits.items() if key in said)
        out[concept.key] = concept.families.get(family, 0.25) * fit
    return out


def choose_dna(dims: dict[str, Any], *, family: str, archetype: str, motion: str, seed: str,
               concept: str | None = None, unable: frozenset[str] = frozenset()) -> DesignDna:
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
    # A headline is set in one voice. The coloured italic phrase was drawn for
    # nearly every site and became the mark of a generated page (founder,
    # 2026-11-14): "none" — the phrase reads like the words around it — is now
    # the likeliest draw, and a change of voice is the exception that a
    # concept's own list has to offer.
    options = [(value, weight * (2.5 if value == "none" else 1)) for value, weight in _ranked(chosen.headline)]
    headline = _draw(options, seed, "headline")
    if headline == "caps" and serif:
        headline = "none"  # a display serif is not set in capitals
    if headline == "italic" and not serif:
        headline = "none"  # a grotesk has no italic worth the name
    if calm and headline not in {"none", "plain"}:
        headline = "none"
    cursor = "none" if calm or personality == "calm" else _draw(_ranked(chosen.cursor), seed, "cursor")
    budget = "restrained" if calm else chosen.budget
    signature, flourish = signature_moments(chosen, display=display, budget=budget,
                                            calm=calm or personality == "calm", seed=seed, unable=unable)

    del archetype  # the family's palette already carries it
    return DesignDna(
        display=display, body=_draw(_ranked(chosen.body), seed, "body"), headline=headline,
        texture=_draw(_ranked(chosen.texture), seed, "texture"), pattern=_draw(_ranked(chosen.pattern), seed, "pattern"),
        divider=_draw(_ranked(chosen.divider), seed, "divider"), button=_draw(_ranked(chosen.button), seed, "button"),
        navstyle=_draw(_ranked(chosen.navstyle), seed, "nav"), cardstyle=_draw(_ranked(chosen.cardstyle), seed, "cards"),
        shape=_draw(_ranked(chosen.shape), seed, "shape"), cursor=cursor,
        invert="calm" if calm else _draw(_ranked(chosen.invert), seed, "invert"),
        concept=chosen.key, space=chosen.space, photo=chosen.photo, budget=budget,
        signature=signature, flourish=flourish,
    )
