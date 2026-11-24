"""The composition grammar: a section arranged freely, drawn only by the platform.

Every other section type is one design with a few layouts. A `composition` is
an arrangement: blocks — words, pictures, a number, a quote, a numbered list,
an action, a vertical label — placed on a 12-column grid, with layers that may
overlap, frames and masks for pictures, a ground, a height, motion, and an
arrangement of its own for a phone. The layout engine
(`interview/layout_engine.py`) and the reference reader
(`website/reference_style.py`) choose arrangements; the AI never writes markup,
and nothing here can carry it (AGENTS.md: "AI chooses allowed layouts").

`normalize` is the one rule-keeper. Whatever proposed an arrangement — the
engine, a vision model reading a screenshot, an owner moving a block — the
result is held to it before it is stored:

* every block sits inside the grid; a block too narrow to read is widened;
* words that overlap a picture sit on a higher layer with a plate behind them,
  so no headline is ever set straight onto a busy photograph;
* every block has a phone place (a 6-column grid, in reading order), and a
  words block laid over a picture lifts onto that picture's lower edge;
* unknown kinds, frames, sizes and motions fall back to safe values; a block
  with nothing to show is dropped; a composition with nothing left is refused.

The renderer is `apps/web/src/components/website/experience/Composition.tsx`
with `packages/ui/src/site-compose.css`; both read exactly these values.
"""

from __future__ import annotations

from typing import Any

from platform_core.exceptions import ValidationError

COLS = 12
PHONE_COLS = 6
MAX_ROWS = 10
MAX_BLOCKS = 12

KINDS = ("words", "picture", "number", "quote", "list", "action", "label")
SIZES = ("xs", "s", "m", "l", "xl", "xxl")
TONES = ("ink", "muted", "accent", "inverse")
FRAMES = ("none", "rounded", "arch", "circle", "slant", "inset", "bleed")
ALIGNS = ("start", "center", "end")
MOTIONS = ("none", "rise", "mask", "scale", "parallax")
GROUNDS = ("base", "alt", "ink", "tint")
HEIGHTS = ("auto", "tall", "screen")
PHONE_RATIOS = ("1/1", "4/5", "3/4", "3/2", "16/9", "2/3")
ROLES = ("story", "statement", "pillars", "numbers", "featured", "process", "visit", "closing", "free")

# Which kinds carry words a person reads (and so need room and contrast).
_READING = frozenset({"words", "quote", "list", "number", "action"})
# The narrowest a block may be on the 12-column grid and still read.
_MIN_SPAN = {"words": 3, "quote": 4, "list": 3, "number": 2, "action": 2, "label": 1, "picture": 2}

BLOCK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "maxLength": 12},
        "slot": {"type": "string", "maxLength": 40},
        "col": {"type": "integer"}, "span": {"type": "integer"},
        "row": {"type": "integer"}, "rows": {"type": "integer"},
        "layer": {"type": "integer"},
        "m_col": {"type": "integer"}, "m_span": {"type": "integer"}, "m_order": {"type": "integer"},
        "m_ratio": {"type": "string", "maxLength": 6},
        "lift": {"type": "boolean"}, "plate": {"type": "boolean"}, "vertical": {"type": "boolean"},
        "size": {"type": "string", "maxLength": 4},
        "tone": {"type": "string", "maxLength": 10},
        "frame": {"type": "string", "maxLength": 10},
        "align": {"type": "string", "maxLength": 8},
        "valign": {"type": "string", "maxLength": 8},
        "motion": {"type": "string", "maxLength": 10},
        "eyebrow": {"type": "string", "maxLength": 60},
        "title": {"type": "string", "maxLength": 160},
        "body": {"type": "string", "maxLength": 600},
        "value": {"type": "string", "maxLength": 24},
        "label": {"type": "string", "maxLength": 80},
        "caption": {"type": "string", "maxLength": 120},
        "cta_label": {"type": "string", "maxLength": 40},
        "cta_url": {"type": "string", "maxLength": 200},
        "price": {"type": "string", "maxLength": 40},
        "image_asset_id": {"type": "string", "format": "uuid"},
        "points": {
            "type": "array", "maxItems": 6,
            "items": {"type": "object", "required": ["title"], "properties": {
                "title": {"type": "string", "maxLength": 80},
                "body": {"type": "string", "maxLength": 240},
                "meta": {"type": "string", "maxLength": 40},
            }},
        },
    },
}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "role": {"type": "string", "maxLength": 12},
        "recipe": {"type": "string", "maxLength": 40},
        "title": {"type": "string", "maxLength": 120},
        "anchor": {"type": "string", "maxLength": 30},
        "ground": {"type": "string", "maxLength": 8},
        "height": {"type": "string", "maxLength": 8},
        "rows": {"type": "integer"},
        "items": {"type": "array", "maxItems": MAX_BLOCKS, "items": BLOCK_SCHEMA},
    },
}


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _pick(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _has_content(block: dict[str, Any]) -> bool:
    kind = block["kind"]
    if kind == "picture":
        return bool(block.get("image_asset_id"))
    if kind == "number":
        return bool(str(block.get("value") or "").strip())
    if kind == "list":
        return any(str(p.get("title") or "").strip() for p in block.get("points") or [] if isinstance(p, dict))
    if kind == "action":
        return bool(str(block.get("cta_label") or "").strip() and str(block.get("cta_url") or "").strip())
    if kind == "label":
        return bool(str(block.get("label") or "").strip())
    return any(str(block.get(k) or "").strip() for k in ("title", "body", "eyebrow"))


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(a["col"] < b["col"] + b["span"] and b["col"] < a["col"] + a["span"]
                and a["row"] < b["row"] + b["rows"] and b["row"] < a["row"] + a["rows"])


def normalize(content: dict[str, Any]) -> dict[str, Any]:
    """The composition held to the grammar (see the module note). Raises when
    nothing showable is left."""
    out: dict[str, Any] = {k: v for k, v in content.items() if k != "items"}
    out["role"] = _pick(content.get("role"), ROLES, "free")
    out["ground"] = _pick(content.get("ground"), GROUNDS, "base")
    out["height"] = _pick(content.get("height"), HEIGHTS, "auto")
    blocks: list[dict[str, Any]] = []
    for raw in (content.get("items") or [])[:MAX_BLOCKS]:
        if not isinstance(raw, dict):
            continue
        block = dict(raw)
        block["kind"] = _pick(block.get("kind"), KINDS, "")
        if not block["kind"] or not _has_content(block):
            continue
        kind = block["kind"]
        span = _int(block.get("span"), 6, 1, COLS)
        span = max(span, _MIN_SPAN[kind])
        col = _int(block.get("col"), 1, 1, COLS)
        if col + span - 1 > COLS:
            col = COLS - span + 1
        block.update(col=col, span=span, row=_int(block.get("row"), 1, 1, MAX_ROWS),
                     rows=_int(block.get("rows"), 1, 1, MAX_ROWS), layer=_int(block.get("layer"), 0, 0, 3))
        if block["row"] + block["rows"] - 1 > MAX_ROWS:
            block["rows"] = MAX_ROWS - block["row"] + 1
        block["size"] = _pick(block.get("size"), SIZES, "m")
        block["tone"] = _pick(block.get("tone"), TONES, "ink")
        block["frame"] = _pick(block.get("frame"), FRAMES, "none")
        block["align"] = _pick(block.get("align"), ALIGNS, "start")
        block["valign"] = _pick(block.get("valign"), ALIGNS, "start" if kind != "picture" else "center")
        block["motion"] = _pick(block.get("motion"), MOTIONS, "rise")
        if kind == "picture":
            block["m_ratio"] = block.get("m_ratio") if block.get("m_ratio") in PHONE_RATIOS else "4/5"
        else:
            block.pop("m_ratio", None)
        blocks.append(block)
    if not blocks:
        raise ValidationError("A composition needs at least one block with something to show",
                              details={"code": "composition_empty"})

    # No empty band at the top: a recipe whose first row had nothing to hold
    # (a title the owner never gave) starts at its first real row.
    top = min(b["row"] for b in blocks)
    if top > 1:
        for block in blocks:
            block["row"] -= top - 1

    # Words over a picture: above it, on a plate. Never a headline set straight
    # onto a photograph (template tell, and a contrast failure on most pictures).
    pictures = [b for b in blocks if b["kind"] == "picture"]
    for block in blocks:
        if block["kind"] not in _READING and block["kind"] != "label":
            continue
        under = [p for p in pictures if _overlaps(block, p)]
        if under:
            block["layer"] = max(block["layer"], max(p["layer"] for p in under) + 1)
            if block["kind"] != "label":
                block["plate"] = True
        else:
            block.pop("plate", None)

    # The grid's height: the last row any block reaches.
    out["rows"] = max(b["row"] + b["rows"] - 1 for b in blocks)

    # A phone place for every block: a 6-column grid in reading order. Words
    # laid over a picture on desktop lift onto that picture's lower edge.
    reading = sorted(enumerate(blocks), key=lambda ib: (
        _int(ib[1].get("m_order"), 0, 0, 99) or (ib[1]["row"] * 100 + ib[1]["col"]), ib[0]))
    for order, (_, block) in enumerate(reading, start=1):
        block["m_order"] = order
        default_span = PHONE_COLS if block["kind"] != "number" else 3
        block["m_span"] = _int(block.get("m_span"), default_span, 2, PHONE_COLS)
        block["m_col"] = _int(block.get("m_col"), 1, 1, PHONE_COLS)
        if block["m_col"] + block["m_span"] - 1 > PHONE_COLS:
            block["m_col"] = PHONE_COLS - block["m_span"] + 1
    for block in blocks:
        if block["kind"] == "picture":
            block.pop("lift", None)
            continue
        # Lift only onto a picture that comes just before it on the phone.
        block["lift"] = bool(block.get("plate")) and any(
            _overlaps(block, p) and p["m_order"] == block["m_order"] - 1 for p in pictures)
    out["items"] = blocks
    return out


def picture_ids(content: dict[str, Any]) -> list[str]:
    """Every picture a composition shows, in its blocks' order."""
    return [str(b["image_asset_id"]) for b in content.get("items") or []
            if isinstance(b, dict) and b.get("kind") == "picture" and b.get("image_asset_id")]
