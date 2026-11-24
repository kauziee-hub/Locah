"""What an owner may change about how their website looks — and what they may not.

An owner personalises their site: its colours, its typefaces, how large the
words are, how round the corners. They do not get the full privileges of a
designer: the composition, the motion and the art direction the site was built
with (``theme.dna``, ``theme.experience``, ``theme.composition`` and the rest)
stay the design pipeline's, so no edit from the Workspace can turn a designed
site back into a template.

That is exactly what used to happen (found 2026-11-13): the Workspace's Theme
page sent ``{"primary_color", "accent_color"}`` and the API stored that as the
WHOLE theme — the site lost its design DNA, its type system and its layouts in
one click, and came back in default teal and amber.

``merge_theme`` is the one rule: an edit is laid over the stored theme; the
pipeline's keys cannot be removed; ``owner_style`` holds only values the
renderer knows (``apps/web/.../experience/experience.ts`` mirrors these lists).
"""

from __future__ import annotations

import re
from typing import Any

from platform_core.exceptions import ValidationError

# Keys the design pipeline writes. A theme edit may replace one with a new
# value (the pipeline itself does, on a rebuild) but can never drop it.
DESIGN_KEYS = frozenset({
    "dna", "experience", "composition", "design_strategy", "design_family", "design_variant",
    "reference_profile", "type_system", "personality", "palette_key", "palette_hue", "palette_mode",
    "rhythm", "image_treatment", "surface", "footer_style", "card_style", "nav_style", "hero_style",
    "creative_direction", "motion_intensity", "mobile", "nav_cta", "utility_bar", "quality",
    "typography_direction", "content_density", "hero_density", "motion_preference", "mobile_priority",
    "navigation_style",
})

# Display and body faces the public renderer has loaded (site-fonts.ts).
DISPLAY_FACES = (
    "syne", "unbounded", "dmserif", "bodoni", "youngserif", "bigshoulders", "spacegrotesk", "italiana",
    "fraunces", "playfair", "cormorant", "anton", "archivo", "bricolage", "outfit", "newsreader", "plex",
    "manrope", "instrumentserif", "intertight", "instrumentsans",
)
BODY_FACES = ("dm", "manrope", "outfit", "plex", "spacegrotesk", "bricolage", "instrumentsans", "intertight")

# Pairings an owner picks by what they feel like, not by a font's name.
FONT_PAIRS: dict[str, dict[str, str]] = {
    "classic": {"label": "Classic", "note": "A graceful serif for headings — established, trusted",
                "display": "playfair", "body": "dm"},
    "elegant": {"label": "Elegant", "note": "Fine, high-contrast headings — premium and quiet",
                "display": "cormorant", "body": "manrope"},
    "warm": {"label": "Warm", "note": "Soft, friendly serif — home-made, local",
             "display": "fraunces", "body": "manrope"},
    "editorial": {"label": "Editorial", "note": "Magazine-style headings — stylish, modern",
                  "display": "instrumentserif", "body": "instrumentsans"},
    "modern": {"label": "Modern", "note": "Clean and confident — works for anything",
               "display": "intertight", "body": "intertight"},
    "friendly": {"label": "Friendly", "note": "Rounded and approachable — cafés, kids, pets",
                 "display": "bricolage", "body": "bricolage"},
    "bold": {"label": "Bold", "note": "Heavy headings that shout — gyms, street food, sales",
             "display": "archivo", "body": "dm"},
    "poster": {"label": "Poster", "note": "Tall condensed capitals — sport, events",
               "display": "bigshoulders", "body": "outfit"},
    "geometric": {"label": "Geometric", "note": "Wide, designed shapes — studios, tech",
                  "display": "syne", "body": "spacegrotesk"},
    "technical": {"label": "Technical", "note": "Precise and engineered — B2B, clinics, services",
                  "display": "plex", "body": "plex"},
}

SIZES = ("small", "regular", "large", "xlarge")
CORNERS = ("sharp", "soft", "round")
OWNER_STYLE_VALUES: dict[str, tuple[str, ...]] = {
    "font": tuple(FONT_PAIRS),
    "font_display": DISPLAY_FACES,
    "font_body": BODY_FACES,
    "heading_size": SIZES,
    "text_size": SIZES,
    "corners": CORNERS,
}
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
COLOUR_KEYS = ("primary_color", "accent_color", "background_color", "text_color", "surface_alt_color",
               "muted_color")
# Everything a page's ground decides: set together, or a dark page keeps light
# alternate bands (found on a reference match, 2026-11-23).
GROUND_KEYS = ("background_color", "text_color", "surface_alt_color", "muted_color", "palette_mode")


def _mix(a: str, b: str, share: float) -> str:
    """`share` of colour b laid over colour a, as hex."""
    pa = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    pb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(pa, pb))


def ground_family(background: str, text: str, *, dark: bool) -> dict[str, str]:
    """A page ground with the alternate ground, muted words and mode that go with it."""
    return {"background_color": background, "text_color": text,
            "surface_alt_color": _mix(background, text, 0.06 if dark else 0.045),
            "muted_color": _mix(text, background, 0.38), "palette_mode": "dark" if dark else "light"}


def clean_owner_style(raw: Any) -> dict[str, str]:
    """An owner's style choices, held to what the renderer can draw."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError("owner_style must be an object")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if value in (None, ""):
            continue  # back to what the design chose
        allowed = OWNER_STYLE_VALUES.get(str(key))
        if allowed is None:
            raise ValidationError(f"'{key}' is not something a website style can set")
        if str(value) not in allowed:
            raise ValidationError(f"'{value}' is not a choice for {key}", details={"choices": list(allowed)})
        out[str(key)] = str(value)
    pair = FONT_PAIRS.get(out.get("font", ""))
    if pair:
        # A pairing is its two faces; naming a pairing replaces a face chosen earlier.
        out["font_display"], out["font_body"] = pair["display"], pair["body"]
    return out


def merge_theme(stored: dict[str, Any] | None, edit: dict[str, Any]) -> dict[str, Any]:
    """The stored theme with an edit laid over it.

    A key in the edit replaces the stored one; ``None`` removes an owner's own
    key (a colour, say) and is ignored for the design pipeline's keys;
    ``owner_style`` is merged choice by choice and validated; colours must be
    hex. Keys the edit does not mention are untouched.
    """
    merged = dict(stored or {})
    for key, value in edit.items():
        if key == "owner_style":
            if value is None:
                merged.pop("owner_style", None)  # back to the designed look, all of it
                continue
            stored_style = merged.get("owner_style")
            current: dict[str, Any] = dict(stored_style) if isinstance(stored_style, dict) else {}
            incoming = value
            if not isinstance(incoming, dict):
                raise ValidationError("owner_style must be an object")
            combined = {**current, **incoming}
            if "font" in incoming and incoming.get("font") in (None, ""):
                # Back to the designed faces: the pairing and both faces go together.
                combined = {k: v for k, v in combined.items() if k not in {"font", "font_display", "font_body"}}
            cleaned = clean_owner_style(combined)
            if cleaned:
                merged["owner_style"] = cleaned
            else:
                merged.pop("owner_style", None)
            continue
        if value is None:
            if key not in DESIGN_KEYS:
                merged.pop(key, None)
            continue
        if key in COLOUR_KEYS and not (isinstance(value, str) and _HEX.match(value)):
            raise ValidationError(f"{key} must be a hex colour like #1f3d34")
        merged[key] = value
    return merged


def style_options() -> dict[str, Any]:
    """Everything the Workspace's design panel offers, from this one place."""
    return {
        "fonts": [{"id": key, **pair} for key, pair in FONT_PAIRS.items()],
        "sizes": list(SIZES),
        "corners": list(CORNERS),
    }
