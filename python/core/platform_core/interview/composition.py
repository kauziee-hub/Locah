"""Content-led composition decisions shared by the director and the composer.

The model gets a vocabulary of executable decisions, not a reference to copy.
Actual content decides which layouts can carry the range. Brand intent ranks
those candidates; business identity breaks close ties without changing facts.
No network, copy generation, module activation or transactional behaviour.
"""

from __future__ import annotations

import hashlib
from typing import Any

OPENINGS = ("masthead", "offset", "poster")
CHAPTERS = ("alternating", "gallery", "index")
RANGES = ("chapters", "menu_book", "hover_list", "spotlight", "bento", "compact_list")


def vocabulary() -> dict[str, Any]:
    return {
        "opening": {
            "masthead": "Wide editorial title, then a panoramic photograph; quiet and spacious.",
            "offset": "Title and introduction beside a portrait photograph; intimate, material-led.",
            "poster": "Oversized typographic opening; strongest when words carry the identity.",
        },
        "chapters": {
            "alternating": "Picture and menu facing each other; suits a warm, narrative brand.",
            "gallery": "Panoramic category photographs above an editorial two-column menu; immersive.",
            "index": "Compact portrait photographs beside a numbered, ruled catalogue; precise and browsable.",
        },
        "range_layout": {
            "chapters": "Category-led editorial: requires at least two pictured categories with items.",
            "menu_book": "A long food menu with chapters, diet marks and prices; requires categories.",
            "hover_list": "An expressive typographic index; requires at least four item photographs.",
            "spotlight": "Individual offering stories; requires three pictured items and substantial descriptions.",
            "bento": "An asymmetric photographic collection; requires at least four pictured items.",
            "compact_list": "A deliberately typeset catalogue when photography cannot carry the page.",
        },
        "instruction": "Choose independent axes around one idea from this owner's actual distinguishing facts. "
                       "Compare two plausible directions before choosing. Do not default to the first option, "
                       "copy a reference, or use effects as a substitute for hierarchy. State the specific "
                       "owner evidence and the visual tradeoff in rationale. Empty values let the platform decide. "
                       "The platform checks photographic feasibility after media selection.",
    }


def plan(
    *, items: list[dict[str, Any]], categories: list[dict[str, Any]],
    concept: str, archetype: str, seed: str, preferred: str = "",
    choices: dict[str, Any] | None = None,
) -> dict[str, Any]:
    choices = choices or {}
    # Only count unique real asset references, not the same photo on six items.
    pictured = len({i["image_asset_id"] for i in items if i.get("image_asset_id")})
    names = {str(i.get("category") or "").strip() for i in items}
    kinds = [c for c in categories if str(c.get("name") or "").strip() in names]
    category_pictures = len({c["image_asset_id"] for c in kinds if c.get("image_asset_id")})
    described = sum(len(str(i.get("description") or "").split()) >= 6 for i in items)
    food = archetype == "menu_commerce"
    scores: dict[str, float] = {"compact_list": 1.0}
    reasons = [f"{len(items)} offerings; {pictured} unique item photos; "
               f"{category_pictures} pictured categories; {described} substantial descriptions"]
    if category_pictures >= 2:
        scores["chapters"] = 5.0
    if food and len(names - {""}) >= 2:
        scores["menu_book"] = 5.0 + (2 if len(items) >= 12 else 0)
    if pictured >= 4:
        scores["hover_list"] = 3.0
        scores["bento"] = 3.0
    if pictured >= 3 and described >= max(3, len(items) / 2):
        scores["spotlight"] = 4.0 if len(items) <= 12 else 2.0

    affinities = {
        "quiet_luxury": {"spotlight": 3, "chapters": 2},
        "warm_craft": {"chapters": 3, "menu_book": 2},
        "noir_editorial": {"spotlight": 3, "hover_list": 3},
        "fresh_market": {"menu_book": 3, "compact_list": 2},
        "playful_pop": {"bento": 4},
        "calm_care": {"spotlight": 2, "compact_list": 2},
        "technical_grid": {"compact_list": 5, "hover_list": 2},
        "kinetic_sport": {"hover_list": 3, "bento": 2},
    }
    for key in scores:
        scores[key] += affinities.get(concept, {}).get(key, 0)
        if key == preferred:
            scores[key] += 0.5
    ranked = sorted(scores, key=lambda key: (
        scores[key], hashlib.sha256(f"{seed}:{concept}:{key}".encode()).hexdigest()), reverse=True)
    requested = str(choices.get("range_layout") or "")
    selected = requested if requested in scores else ranked[0]
    reasons.append(f"range {selected}: " + ("director choice, content requirements met" if requested in scores
                                           else f"content fit + {concept} intent"))
    if requested and requested not in scores:
        reasons.append(f"range {requested} rejected: unknown or insufficient content")
    opening = "offset" if concept in {"warm_craft", "calm_care", "quiet_luxury"} else (
        "poster" if concept in {"kinetic_sport", "playful_pop", "technical_grid"} else "masthead")
    chapter = "gallery" if concept in {"quiet_luxury", "noir_editorial"} else (
        "index" if concept in {"technical_grid", "fresh_market", "kinetic_sport"} else "alternating")
    return {
        "version": "composition-v1", "range_layout": selected,
        "opening": choices.get("opening") if choices.get("opening") in OPENINGS else opening,
        "chapters": choices.get("chapters") if choices.get("chapters") in CHAPTERS else chapter,
        "candidates": ranked, "reasons": reasons,
        # Audit metadata, never rendered as customer-facing copy.
        "rationale": str(choices.get("rationale") or "")[:600],
    }
