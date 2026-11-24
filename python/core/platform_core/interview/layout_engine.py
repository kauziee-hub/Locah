"""The layout engine: each business's sections arranged for it, not picked from a shelf.

A section type with three layouts gives every site one of three pictures of
"our story". Here a story, a statement, what the business stands on, its
numbers or its signature range are *composed*: blocks placed on the grid of
`website.composition_grammar` by parametric recipes — which side the picture
takes, how wide it runs, whether the words overlap it on a plate, a second
picture offset below, a vertical label, a ground, a frame from the design
DNA's shape, a type scale from its concept, motion from its budget. A recipe
is a way of arranging, not a template: the business's own words and pictures
decide what it holds, its seed decides the variation, and no recipe is used
twice on one site.

Nothing here writes a word: every string comes from the material the page
builder hands in (the owner's facts and governed copy). The result is a
`composition` section; `normalize` holds it to the grammar before it is
stored, and `Composition.tsx` draws it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from platform_core.website.composition_grammar import COLS, normalize

Block = dict[str, Any]

# How the design DNA's shape frames a picture.
_FRAME_BY_SHAPE = {"arch": "arch", "rounded": "rounded", "rect": "none", "slant": "slant", "blob": "circle"}
# How large display words run, by art direction.
_SCALE = {
    "noir_editorial": ("l", "xl", "xxl"), "kinetic_sport": ("l", "xl", "xxl"),
    "quiet_luxury": ("m", "l", "xl"), "warm_craft": ("m", "l", "xl"), "playful_pop": ("m", "l", "xl"),
    "fresh_market": ("m", "l", "l"), "calm_care": ("s", "m", "l"), "technical_grid": ("m", "l", "l"),
}
# The one ground a concept may set a composition on for its strongest moment.
_MOMENT_GROUND = {
    "noir_editorial": "ink", "kinetic_sport": "ink", "quiet_luxury": "base", "warm_craft": "tint",
    "playful_pop": "tint", "fresh_market": "alt", "calm_care": "alt", "technical_grid": "base",
}
_MOTION = {
    "restrained": ("rise", "rise"), "gentle": ("rise", "mask"),
    "signature": ("mask", "parallax"), "expressive": ("mask", "scale"),
}


@dataclass
class Material:
    """What one composition may hold — all of it the owner's or governed copy."""

    eyebrow: str = ""
    title: str = ""
    body: str = ""
    quote: str = ""
    pictures: list[str] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)
    points: list[dict[str, str]] = field(default_factory=list)
    figures: list[tuple[str, str]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)  # featured things: name, description, price, picture
    action: tuple[str, str] | None = None


@dataclass
class Style:
    concept: str = ""
    shape: str = "rect"
    budget: str = "gentle"

    @property
    def frame(self) -> str:
        return _FRAME_BY_SHAPE.get(self.shape, "none")

    def size(self, level: int) -> str:
        scale = _SCALE.get(self.concept, ("m", "l", "xl"))
        return scale[max(0, min(2, level))]

    def motion(self, strong: bool = False) -> str:
        quiet, loud = _MOTION.get(self.budget, ("rise", "mask"))
        return loud if strong else quiet


def _mirror(block: Block) -> Block:
    """The same arrangement, the other way round."""
    if "col" in block and "span" in block:
        block["col"] = COLS - (block["col"] + block["span"] - 1) + 1
    return block


def _words(m: Material, *, col: int, span: int, row: int, rows: int, size: str, motion: str,
           with_body: bool = True, **extra: Any) -> Block:
    block: Block = {"kind": "words", "col": col, "span": span, "row": row, "rows": rows, "size": size,
                    "motion": motion, "slot": "words"}
    if m.eyebrow:
        block["eyebrow"] = m.eyebrow
    if m.title:
        block["title"] = m.title
    if with_body and m.body:
        block["body"] = m.body
    if m.action:
        block["cta_label"], block["cta_url"] = m.action
    block.update(extra)
    return block


def _way_on(m: Material) -> dict[str, str]:
    """The link on to more, carried by the block that holds the passage."""
    return {"cta_label": m.action[0], "cta_url": m.action[1]} if m.action else {}


def _picture(asset: str, *, col: int, span: int, row: int, rows: int, frame: str, motion: str,
             caption: str = "", m_ratio: str = "4/5", **extra: Any) -> Block:
    block: Block = {"kind": "picture", "image_asset_id": asset, "col": col, "span": span, "row": row,
                    "rows": rows, "frame": frame, "motion": motion, "m_ratio": m_ratio, "slot": "picture"}
    if caption:
        block["caption"] = caption[:120]
    block.update(extra)
    return block


# ------------------------------------------------------------------ story
def _story_overlap(m: Material, s: Style) -> list[Block]:
    """A large picture with the words laid over its edge on a plate; a second
    picture offset below the words."""
    blocks = [
        _picture(m.pictures[0], col=1, span=7, row=1, rows=5, frame="none" if s.frame == "slant" else s.frame,
                 motion=s.motion(True), m_order=1),
        _words(m, col=7, span=5, row=2, rows=3, size=s.size(1), motion=s.motion(), m_order=2, valign="center"),
    ]
    if len(m.pictures) > 1:
        blocks.append(_picture(m.pictures[1], col=9, span=4, row=5, rows=3, frame=s.frame, motion=s.motion(),
                               m_order=3, m_span=4, m_col=3, m_ratio="1/1"))
    return blocks


def _story_tall_side(m: Material, s: Style) -> list[Block]:
    """Words in a column with room around them; a tall framed picture beside."""
    blocks = [
        _words(m, col=1, span=5, row=1, rows=2, size=s.size(2), motion=s.motion(), with_body=False, m_order=1,
               cta_label="" if m.body else (m.action[0] if m.action else ""),
               cta_url="" if m.body else (m.action[1] if m.action else "")),
        _picture(m.pictures[0], col=7, span=6, row=1, rows=6, frame=s.frame if s.frame != "none" else "arch",
                 motion=s.motion(True), m_order=2, m_ratio="3/4"),
    ]
    if m.body:
        blocks.append({"kind": "words", "body": m.body, "col": 1, "span": 4, "row": 4, "rows": 2,
                       "motion": s.motion(), "m_order": 3, "slot": "body", "tone": "muted", **_way_on(m)})
    if m.eyebrow:
        blocks.append({"kind": "label", "label": m.eyebrow, "vertical": True, "col": 6, "span": 1, "row": 1,
                       "rows": 3, "motion": "rise", "m_order": 0, "tone": "muted"})
        blocks[0].pop("eyebrow", None)
    return blocks


def _story_type_wall(m: Material, s: Style) -> list[Block]:
    """The title set wide at display size; the picture below it to one side,
    the passage in the space it leaves."""
    blocks = [
        _words(m, col=1, span=10, row=1, rows=1, size=s.size(2), motion=s.motion(True), with_body=False,
               m_order=1, cta_label="", cta_url=""),
        _picture(m.pictures[0], col=5, span=8, row=2, rows=4, frame="bleed" if s.concept in {
            "noir_editorial", "kinetic_sport", "quiet_luxury"} else s.frame, motion=s.motion(True),
                 m_order=2, m_ratio="4/5"),
    ]
    if m.body:
        blocks.append({"kind": "words", "body": m.body, "col": 1, "span": 3, "row": 3, "rows": 2,
                       "motion": s.motion(), "m_order": 3, "slot": "body", "valign": "end", **_way_on(m)})
    if len(m.pictures) > 1:
        blocks.append(_picture(m.pictures[1], col=1, span=3, row=5, rows=2, frame=s.frame, motion=s.motion(),
                               m_order=4, m_span=3, m_col=1, m_ratio="1/1"))
    return blocks


def _story_offset_pair(m: Material, s: Style) -> list[Block]:
    """Two pictures staggered against each other; the words under the first."""
    return [
        _picture(m.pictures[0], col=1, span=5, row=1, rows=4, frame=s.frame, motion=s.motion(True), m_order=1,
                 m_ratio="4/5"),
        _picture(m.pictures[1], col=7, span=5, row=3, rows=5, frame="none", motion=s.motion(), m_order=3,
                 m_span=5, m_col=2, m_ratio="3/4"),
        _words(m, col=1, span=5, row=5, rows=3, size=s.size(1), motion=s.motion(), m_order=2),
    ]


def _story_caption(m: Material, s: Style) -> list[Block]:
    """A framed picture set in from the edge; the words high and to the side,
    like a caption in a magazine spread."""
    return [
        _words(m, col=9, span=4, row=1, rows=2, size=s.size(1), motion=s.motion(), m_order=1, valign="start"),
        _picture(m.pictures[0], col=2, span=6, row=1, rows=5, frame="inset", motion=s.motion(True), m_order=2,
                 caption=m.captions[0] if m.captions else "", m_ratio="4/5"),
    ]


# ------------------------------------------------------------------ statement
def _statement_poster(m: Material, s: Style) -> list[Block]:
    """The sentence large, held in the middle of a tall picture's height."""
    blocks: list[Block] = [{"kind": "quote", "title": m.quote, "col": 1, "span": 8 if m.pictures else 11,
                            "row": 1, "rows": 4 if m.pictures else 2, "size": s.size(2), "motion": s.motion(True),
                            "valign": "center", "m_order": 1}]
    if m.eyebrow:
        blocks.append({"kind": "label", "label": m.eyebrow, "col": 1, "span": 4, "row": 5 if m.pictures else 3,
                       "rows": 1, "motion": "rise", "tone": "muted", "m_order": 2})
    if m.pictures:
        blocks.append(_picture(m.pictures[0], col=9, span=4, row=1, rows=5, frame=s.frame, motion=s.motion(),
                               m_order=3, m_span=4, m_col=3, m_ratio="3/4"))
    return blocks


def _statement_against_edge(m: Material, s: Style) -> list[Block]:
    return [
        _picture(m.pictures[0], col=1, span=6, row=1, rows=4, frame="bleed", motion=s.motion(True), m_order=1,
                 m_ratio="4/5"),
        {"kind": "quote", "title": m.quote, "col": 7, "span": 6, "row": 2, "rows": 2, "size": s.size(1),
         "motion": s.motion(), "valign": "center", "m_order": 2},
    ]


# ------------------------------------------------------------------ pillars
def _pillars_index(m: Material, s: Style) -> list[Block]:
    blocks: list[Block] = []
    if m.title:
        blocks.append({"kind": "words", "title": m.title, "eyebrow": m.eyebrow, "col": 1, "span": 6, "row": 1,
                       "rows": 1, "size": s.size(1), "motion": s.motion(), "m_order": 1})
    blocks.append({"kind": "list", "points": m.points[:5], "col": 1, "span": 6, "row": 2, "rows": 4,
                   "motion": s.motion(), "m_order": 2})
    if m.pictures:
        blocks.append(_picture(m.pictures[0], col=8, span=5, row=1, rows=5, frame=s.frame, motion=s.motion(True),
                               m_order=3, m_ratio="4/5"))
    return blocks


def _pillars_columns(m: Material, s: Style) -> list[Block]:
    blocks: list[Block] = []
    if m.title:
        blocks.append({"kind": "words", "title": m.title, "eyebrow": m.eyebrow, "col": 1, "span": 4, "row": 1,
                       "rows": 2, "size": s.size(1), "motion": s.motion(True), "m_order": 1})
    blocks.append({"kind": "list", "points": m.points[:6], "col": 5 if m.title else 1, "span": 8 if m.title else 12,
                   "row": 1, "rows": 3, "motion": s.motion(), "m_order": 2})
    return blocks


def _pillars_stagger(m: Material, s: Style) -> list[Block]:
    """Each thing the business stands on in its own place, stepping down the page."""
    blocks: list[Block] = []
    cols = (1, 5, 9) if len(m.points) >= 3 else (1, 7)
    for i, point in enumerate(m.points[:len(cols)]):
        blocks.append({"kind": "words", "eyebrow": f"{i + 1:02d}", "title": point.get("title", ""),
                       "body": point.get("body", ""), "col": cols[i], "span": 4 if len(cols) == 3 else 5,
                       "row": 1 + i, "rows": 2, "size": s.size(0), "motion": s.motion(), "m_order": i + 1})
    if m.title:
        blocks.append({"kind": "label", "label": m.title, "vertical": True, "col": 12, "span": 1, "row": 1,
                       "rows": 3, "motion": "rise", "tone": "muted", "m_order": 0})
    return blocks


# ------------------------------------------------------------------ numbers
def _numbers_row(m: Material, s: Style) -> list[Block]:
    figures = m.figures[:4]
    width = COLS // len(figures)
    blocks: list[Block] = []
    if m.title:
        blocks.append({"kind": "label", "label": m.title, "col": 1, "span": 6, "row": 1, "rows": 1,
                       "motion": "rise", "tone": "muted", "m_order": 1})
    for i, (value, label) in enumerate(figures):
        blocks.append({"kind": "number", "value": value, "label": label, "col": 1 + i * width, "span": width,
                       "row": 2, "rows": 1, "size": s.size(2), "motion": s.motion(), "m_order": 2 + i,
                       "m_span": 3})
    return blocks


def _numbers_beside(m: Material, s: Style) -> list[Block]:
    value, label = m.figures[0]
    blocks: list[Block] = [
        {"kind": "number", "value": value, "label": label, "col": 1, "span": 5, "row": 1, "rows": 2,
         "size": "xxl", "motion": s.motion(True), "m_order": 1, "m_span": 6},
        _picture(m.pictures[0], col=7, span=6, row=1, rows=4, frame=s.frame, motion=s.motion(), m_order=3,
                 m_ratio="3/2"),
    ]
    rest = m.figures[1:4]
    if rest:
        blocks.append({"kind": "list", "points": [{"title": v, "body": lbl} for v, lbl in rest],
                       "col": 1, "span": 5, "row": 3, "rows": 2, "motion": s.motion(), "m_order": 2})
    return blocks


# ------------------------------------------------------------------ featured (the range's signature)
def _line(item: dict[str, Any]) -> str:
    return " · ".join(str(x) for x in (item.get("name"), item.get("price")) if x)


def _featured_lead(m: Material, s: Style) -> list[Block]:
    """The signature thing large, its words beside it; the next ones offset below."""
    lead, rest = m.items[0], m.items[1:3]
    blocks: list[Block] = []
    if m.title:
        blocks.append({"kind": "words", "eyebrow": m.eyebrow, "title": m.title, "col": 1, "span": 6, "row": 1,
                       "rows": 1, "size": s.size(1), "motion": s.motion(), "m_order": 1})
    blocks += [
        _picture(lead["image_asset_id"], col=1, span=7, row=2, rows=5, frame=s.frame, motion=s.motion(True),
                 m_order=2, m_ratio="4/5"),
        {"kind": "words", "title": str(lead.get("name") or ""), "price": str(lead.get("price") or ""),
         "body": str(lead.get("description") or ""), "col": 8, "span": 5, "row": 2, "rows": 2,
         "size": s.size(1), "motion": s.motion(), "m_order": 3, "valign": "end"},
    ]
    spots = [(8, 5, 4, 3), (3, 4, 7, 3)]
    for (col, span, row, rows), item in zip(spots, rest):
        blocks.append(_picture(item["image_asset_id"], col=col, span=span, row=row, rows=rows, frame="none",
                               motion=s.motion(), caption=_line(item), m_order=4 + len(blocks),
                               m_span=6 if len(rest) == 1 else 3, m_col=1, m_ratio="1/1"))
    if m.action:
        blocks.append({"kind": "action", "cta_label": m.action[0], "cta_url": m.action[1], "col": 8,
                       "span": 4, "row": 8 if len(rest) > 1 else 7, "rows": 1, "motion": "rise",
                       "m_order": 20})
    return blocks


def _featured_wall(m: Material, s: Style) -> list[Block]:
    """Three plates at three heights, each with its name and price; the words
    in the space the shortest leaves."""
    shown = m.items[:3]
    tops = ((1, 4), (2, 4), (1, 3))
    blocks: list[Block] = []
    for i, item in enumerate(shown):
        row, rows = tops[i]
        blocks.append(_picture(item["image_asset_id"], col=1 + i * 4, span=4, row=row, rows=rows,
                               frame=s.frame if i == 1 else "none", motion=s.motion(i == 1),
                               caption=_line(item), m_order=2 + i, m_ratio="4/5"))
    if m.title:
        blocks.append({"kind": "words", "eyebrow": m.eyebrow, "title": m.title, "col": 9, "span": 4, "row": 4,
                       "rows": 2, "size": s.size(1), "motion": s.motion(), "m_order": 1,
                       **({"cta_label": m.action[0], "cta_url": m.action[1]} if m.action else {})})
    return blocks


def _featured_spotlight(m: Material, s: Style) -> list[Block]:
    """The range's names as a quiet list; its best picture large beside it."""
    points = [{"title": str(i.get("name") or ""), "body": str(i.get("description") or ""),
               "meta": str(i.get("price") or "")} for i in m.items[:5]]
    blocks: list[Block] = [
        {"kind": "list", "points": points, "col": 1, "span": 5, "row": 2, "rows": 4, "motion": s.motion(),
         "m_order": 3},
        _picture(m.items[0]["image_asset_id"], col=7, span=6, row=1, rows=6,
                 frame="bleed" if s.concept in {"noir_editorial", "quiet_luxury"} else s.frame,
                 motion=s.motion(True), m_order=2, m_ratio="4/5"),
    ]
    if m.title:
        blocks.append({"kind": "words", "eyebrow": m.eyebrow, "title": m.title, "col": 1, "span": 5, "row": 1,
                       "rows": 1, "size": s.size(1), "motion": s.motion(), "m_order": 1,
                       **({"cta_label": m.action[0], "cta_url": m.action[1]} if m.action else {})})
    return blocks


Recipe = Callable[[Material, Style], list[Block]]

# (name, recipe, what it needs) by role. `needs` is checked against the material.
RECIPES: dict[str, list[tuple[str, Recipe, Callable[[Material], bool]]]] = {
    "story": [
        ("story_overlap", _story_overlap, lambda m: bool(m.pictures and m.title)),
        ("story_tall_side", _story_tall_side, lambda m: bool(m.pictures and m.title)),
        ("story_type_wall", _story_type_wall, lambda m: bool(m.pictures and m.title and len(m.title) <= 70)),
        ("story_offset_pair", _story_offset_pair, lambda m: len(m.pictures) >= 2 and bool(m.title)),
        ("story_caption", _story_caption, lambda m: bool(m.pictures and m.title)),
    ],
    "statement": [
        ("statement_poster", _statement_poster, lambda m: bool(m.quote)),
        ("statement_against_edge", _statement_against_edge, lambda m: bool(m.quote and m.pictures)),
    ],
    "pillars": [
        ("pillars_index", _pillars_index, lambda m: len(m.points) >= 2 and bool(m.pictures)),
        ("pillars_columns", _pillars_columns, lambda m: len(m.points) >= 3),
        ("pillars_stagger", _pillars_stagger, lambda m: 2 <= len(m.points) <= 3
         and all(p.get("body") for p in m.points)),
    ],
    "numbers": [
        ("numbers_row", _numbers_row, lambda m: 2 <= len(m.figures) <= 4),
        ("numbers_beside", _numbers_beside, lambda m: bool(m.figures and m.pictures)),
    ],
    "featured": [
        ("featured_lead", _featured_lead, lambda m: len(m.items) >= 2),
        ("featured_wall", _featured_wall, lambda m: len(m.items) >= 3),
        ("featured_spotlight", _featured_spotlight, lambda m: len(m.items) >= 3),
    ],
}


def _roll(seed: str, salt: str) -> int:
    return int(hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()[:8], 16)


class Composer:
    """One site's compositions: seeded by the business, never the same recipe twice."""

    def __init__(self, seed: str, *, concept: str = "", shape: str = "rect", budget: str = "gentle") -> None:
        self.seed = seed
        self.style = Style(concept=concept, shape=shape, budget=budget)
        self.used: list[str] = []
        self.moment_spent = False

    def options(self, role: str, material: Material) -> list[str]:
        return [name for name, _, needs in RECIPES.get(role, []) if needs(material)]

    def compose(self, role: str, material: Material, *, prefer: str = "", moment: bool = False,
                anchor: str = "") -> dict[str, Any] | None:
        """A composition section for this role, or None when the material cannot
        carry any of its recipes (the page builder then keeps its old section)."""
        feasible = [(name, recipe) for name, recipe, needs in RECIPES.get(role, []) if needs(material)]
        if not feasible:
            return None
        fresh = [(n, r) for n, r in feasible if n not in self.used] or feasible
        chosen = next(((n, r) for n, r in fresh if n == prefer), None)
        if chosen is None:
            chosen = fresh[_roll(self.seed, f"{role}:{len(self.used)}") % len(fresh)]
        name, recipe = chosen
        blocks = [dict(b) for b in recipe(material, self.style)]
        if _roll(self.seed, f"mirror:{name}") % 2:
            blocks = [_mirror(b) for b in blocks]
        ground = "base"
        if moment and not self.moment_spent:
            ground = _MOMENT_GROUND.get(self.style.concept, "base")
            self.moment_spent = ground != "base"
        content: dict[str, Any] = {"role": role, "recipe": name, "ground": ground, "items": blocks}
        if material.title:
            content["title"] = material.title[:120]
        if anchor:
            content["anchor"] = anchor
        self.used.append(name)
        return {"section_type_id": "composition", "layout_variant": "free", "content": normalize(content),
                "is_visible": True}


# ------------------------------------------------------------------ re-arranging what is there
def material_from(content: dict[str, Any]) -> Material:
    """What a stored composition holds, as material another arrangement can take.

    Read back from its blocks: the words and pictures the business already
    has on that section (including an owner's own edits), never new ones."""
    m = Material()
    bodies: list[str] = []
    for block in content.get("items") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("kind")
        if kind == "picture" and block.get("image_asset_id"):
            m.pictures.append(str(block["image_asset_id"]))
            m.captions.append(str(block.get("caption") or ""))
            name, _, price = str(block.get("caption") or "").partition(" · ")
            if name:
                m.items.append({"name": name, "price": price, "image_asset_id": str(block["image_asset_id"])})
        elif kind == "words":
            if block.get("title") and not m.title:
                m.title, m.eyebrow = str(block["title"]), str(block.get("eyebrow") or "")
                if block.get("price") and m.pictures:
                    # A featured lead: its words belong to the first picture's item.
                    m.items.insert(0, {"name": str(block["title"]), "price": str(block["price"]),
                                       "description": str(block.get("body") or ""),
                                       "image_asset_id": m.pictures[0]})
            if block.get("body"):
                bodies.append(str(block["body"]))
            if block.get("cta_label") and block.get("cta_url") and not m.action:
                m.action = (str(block["cta_label"]), str(block["cta_url"]))
        elif kind == "quote" and (block.get("title") or block.get("body")):
            m.quote = str(block.get("title") or block.get("body"))
        elif kind == "list":
            m.points += [p for p in block.get("points") or [] if isinstance(p, dict) and p.get("title")]
        elif kind == "number" and block.get("value"):
            m.figures.append((str(block["value"]), str(block.get("label") or "")))
        elif kind == "action" and block.get("cta_label") and block.get("cta_url") and not m.action:
            m.action = (str(block["cta_label"]), str(block["cta_url"]))
        elif kind == "label" and block.get("label") and not m.eyebrow:
            m.eyebrow = str(block["label"])
    m.body = "\n\n".join(dict.fromkeys(bodies))
    # Items whose pictures are known keep them; a lead read twice is kept once.
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for item in m.items:
        key = str(item.get("image_asset_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item)
    m.items = kept
    if not m.title and content.get("title"):
        m.title = str(content["title"])
    return m


def bind(geometry: list[dict[str, Any]], m: Material, s: Style) -> list[Block]:
    """An arrangement (a reference's, read from a screenshot) filled with this
    business's material, in reading order: pictures in turn, the title and
    eyebrow in the first words, the passage in the next (or the same), the
    statement in a quote, its points in a list, its figures in numbers, its
    way on in an action. A place the material cannot fill is left out; words
    the arrangement had no place for go to its last words block, so nothing
    the business said is lost."""
    pictures = list(m.pictures) or [str(i["image_asset_id"]) for i in m.items if i.get("image_asset_id")]
    figures = list(m.figures)
    told = {"title": False, "body": False, "quote": False, "points": False, "action": False}
    out: list[Block] = []
    words_at: list[int] = []
    for raw in sorted(geometry, key=lambda b: (int(b.get("row", 1)), int(b.get("col", 1)))):
        kind = str(raw.get("kind") or "")
        place: dict[str, Any] = {k: raw[k] for k in ("col", "span", "row", "rows", "layer", "align", "valign")
                                 if k in raw}
        size = str(raw.get("size") or "")
        if kind == "picture":
            if not pictures:
                continue
            asset = pictures.pop(0)
            index = m.pictures.index(asset) if asset in m.pictures else -1
            caption = m.captions[index] if 0 <= index < len(m.captions) else ""
            out.append(_picture(asset, frame=str(raw.get("frame") or s.frame), motion=s.motion(not out),
                                caption=caption, **place))
        elif kind == "words" and (m.title or m.body or m.eyebrow):
            block: Block = {"kind": "words", "size": size or s.size(1), "motion": s.motion(), **place}
            if not told["title"] and m.title:
                block["title"], told["title"] = m.title, True
                if m.eyebrow:
                    block["eyebrow"] = m.eyebrow
            elif not told["body"] and m.body:
                block["body"], told["body"] = m.body, True
            else:
                continue
            out.append(block)
            words_at.append(len(out) - 1)
        elif kind == "quote" and (m.quote or m.title) and not told["quote"]:
            out.append({"kind": "quote", "title": m.quote or m.title, "size": size or s.size(2),
                        "motion": s.motion(True), **place})
            told["quote"] = True
            if not m.quote:
                told["title"] = True
        elif kind == "list" and (m.points or m.items) and not told["points"]:
            points = m.points or [{"title": str(i.get("name") or ""), "body": str(i.get("description") or ""),
                                   "meta": str(i.get("price") or "")} for i in m.items]
            out.append({"kind": "list", "points": points[:6], "motion": s.motion(), **place})
            told["points"] = True
        elif kind == "number" and figures:
            value, label = figures.pop(0)
            out.append({"kind": "number", "value": value, "label": label, "size": size or s.size(2),
                        "motion": s.motion(), **place})
        elif kind == "action" and m.action and not told["action"]:
            out.append({"kind": "action", "cta_label": m.action[0], "cta_url": m.action[1], "motion": "rise",
                        **place})
            told["action"] = True
        elif kind == "label" and m.eyebrow:
            out.append({"kind": "label", "label": m.eyebrow, "vertical": bool(raw.get("vertical")),
                        "tone": "muted", "motion": "rise", **place})
    # Nothing said is lost: what had no place joins the last words block.
    if words_at:
        last = out[words_at[-1]]
        if not told["title"] and m.title and "title" not in last:
            last["title"] = m.title
        if not told["body"] and m.body and "body" not in last:
            last["body"] = m.body
        if not told["action"] and m.action and not any(b.get("kind") == "action" for b in out):
            last["cta_label"], last["cta_url"] = m.action
    return out


def mirrored(content: dict[str, Any]) -> dict[str, Any]:
    """The same composition the other way round (pictures to the other side)."""
    flipped: dict[str, Any] = normalize({**content, "items": [_mirror(dict(b)) for b in content.get("items") or []]})
    return flipped


def rearranged(content: dict[str, Any], style: Style, *, seed: str = "") -> dict[str, Any] | None:
    """The same words and pictures in the role's next arrangement, or None when
    no other arrangement can carry them."""
    role = str(content.get("role") or "")
    material = material_from(content)
    feasible = [name for name, _, needs in RECIPES.get(role, []) if needs(material)]
    current = str(content.get("recipe") or "")
    others = [n for n in feasible if n != current]
    if not others:
        return None
    following = feasible[(feasible.index(current) + 1) % len(feasible)] if current in feasible else others[0]
    composer = Composer(seed or current or role, concept=style.concept, shape=style.shape, budget=style.budget)
    made = composer.compose(role, material, prefer=following)
    if made is None:
        return None
    kept = {k: content[k] for k in ("anchor", "ground", "height") if k in content}
    return {**made["content"], **kept}


def from_geometry(role: str, geometry: list[dict[str, Any]], content: dict[str, Any], style: Style
                  ) -> dict[str, Any] | None:
    """This composition's words and pictures in an arrangement read from a
    reference; None when it would show less than half of what is there now."""
    material = material_from(content)
    blocks = bind(geometry, material, style)
    shown_pictures = sum(1 for b in blocks if b.get("kind") == "picture")
    has_words = any(b.get("kind") in {"words", "quote", "list", "number"} for b in blocks)
    if not has_words or (material.pictures and shown_pictures * 2 < len(material.pictures)):
        return None
    kept: dict[str, Any] = {k: content[k] for k in ("anchor", "height") if k in content}
    extra: dict[str, Any] = {"title": material.title[:120]} if material.title else {}
    made: dict[str, Any] = normalize({"role": role, "recipe": "reference", "ground": content.get("ground", "base"),
                                      "items": blocks, **extra, **kept})
    return made
