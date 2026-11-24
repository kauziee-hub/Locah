"""Website content validation (Stage 2 — Doc 12 §11.3, §12.5)."""

from __future__ import annotations

import re
from typing import Any

from platform_core.exceptions import ValidationError
from platform_core.website.section_registry import ALLOWED_SECTION_TYPE_IDS, CORE_SECTION_SCHEMAS

_HTML_RE = re.compile(r"<\s*/?\s*[a-zA-Z!]|javascript:|on\w+\s*=", re.IGNORECASE)
_EXTERNAL_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script|</script", re.IGNORECASE)


def _field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


# DB CHECK on website_pages.page_type. AI output drifts to synonyms; coerce
# rather than reject the whole draft.
_ALLOWED_PAGE_TYPES = frozenset(
    {
        "home", "about", "contact", "locations", "offerings", "services",
        "menu", "rooms", "plans", "classes", "enquire", "custom",
    }
)
_PAGE_TYPE_SYNONYMS = {
    "landing": "home", "homepage": "home", "index": "home", "main": "home",
    "products": "offerings", "shop": "offerings", "catalog": "offerings",
    "catalogue": "offerings", "store": "offerings",
    "team": "about", "story": "about", "our-story": "about", "info": "about",
    "location": "locations", "find-us": "locations", "visit": "locations",
    "book": "enquire", "booking": "enquire", "contact-us": "contact",
    "gallery": "custom", "faq": "custom", "reviews": "custom", "pricing": "plans",
}


def _coerce_page_type(raw: Any) -> str:
    value = str(raw or "").strip().lower().replace(" ", "-")
    if value in _ALLOWED_PAGE_TYPES:
        return value
    return _PAGE_TYPE_SYNONYMS.get(value, "custom")


def assert_no_unsafe_content(value: Any, *, path: str = "content") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            assert_no_unsafe_content(nested, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for idx, nested in enumerate(value):
            assert_no_unsafe_content(nested, path=f"{path}[{idx}]")
        return
    if not isinstance(value, str):
        return
    if _SCRIPT_RE.search(value) or _HTML_RE.search(value):
        raise ValidationError(
            "Arbitrary HTML/JavaScript is not allowed in website content",
            details={"errors": [_field_error(path, "Unsafe markup detected")]},
        )
    # Permanent external URLs are forbidden; relative paths and mailto/tel are allowed.
    if _EXTERNAL_URL_RE.search(value) and not value.startswith(("mailto:", "tel:")):
        raise ValidationError(
            "External URLs may not be stored as permanent website content",
            details={"errors": [_field_error(path, "External URL not allowed")]},
        )


def _validate_against_schema(
    content: dict[str, Any], schema: dict[str, Any], *, field: str, lenient: bool = False
) -> dict[str, Any]:
    """Strict by default (manual edits — a stray field is a typo worth catching).
    `lenient=True` (AI generation) instead drops unknown keys, drops wrong-typed
    values, and truncates over-long strings. The result still goes through
    `assert_no_unsafe_content` and lands only in a draft the owner reviews."""
    if schema.get("type") == "object" and not isinstance(content, dict):
        raise ValidationError(
            "Invalid section content",
            details={"errors": [_field_error(field, "Must be an object")]},
        )
    required = schema.get("required") or []
    for key in required:
        if key not in content or content[key] in (None, ""):
            raise ValidationError(
                "Missing required section content field",
                details={"errors": [_field_error(f"{field}.{key}", "Required")]},
            )
    properties: dict[str, Any] = schema.get("properties") or {}
    cleaned: dict[str, Any] = {}
    for key, value in content.items():
        if key not in properties:
            if lenient:
                continue
            raise ValidationError(
                "Unknown section content field",
                details={"errors": [_field_error(f"{field}.{key}", "Not allowed")]},
            )
        prop = properties[key]
        if prop.get("type") == "string" and value is not None:
            if not isinstance(value, str):
                if lenient:
                    continue
                raise ValidationError(
                    "Invalid section content field type",
                    details={"errors": [_field_error(f"{field}.{key}", "Must be a string")]},
                )
            max_len = prop.get("maxLength")
            if max_len is not None and len(value) > int(max_len):
                if lenient:
                    value = value[: int(max_len)]
                else:
                    raise ValidationError(
                        "Section content field too long",
                        details={"errors": [_field_error(f"{field}.{key}", "Too long")]},
                    )
        if prop.get("type") == "boolean" and value is not None and not isinstance(value, bool):
            if lenient:
                continue
            raise ValidationError(
                "Invalid section content field type",
                details={"errors": [_field_error(f"{field}.{key}", "Must be a boolean")]},
            )
        if prop.get("type") == "integer" and value is not None and not isinstance(value, int):
            if lenient:
                continue
            raise ValidationError(
                "Invalid section content field type",
                details={"errors": [_field_error(f"{field}.{key}", "Must be an integer")]},
            )
        if prop.get("type") == "array" and value is not None:
            value = _validate_array(value, prop, field=f"{field}.{key}", lenient=lenient)
            if value is None:
                continue
        cleaned[key] = value
    return cleaned


def _validate_array(
    value: Any, schema: dict[str, Any], *, field: str, lenient: bool
) -> list[Any] | None:
    """Arrays were passed through unchecked; list sections now carry real items.

    Items that are objects are validated with the same rules as section content,
    so a highlight or feature card cannot smuggle an unknown field or an
    over-long string into a draft. Lenient mode (AI output) drops bad items and
    truncates to `maxItems`; strict mode (owner edits) reports them.
    """
    if not isinstance(value, list):
        if lenient:
            return None
        raise ValidationError(
            "Invalid section content field type",
            details={"errors": [_field_error(field, "Must be a list")]},
        )
    max_items = schema.get("maxItems")
    if max_items is not None and len(value) > int(max_items):
        if not lenient:
            raise ValidationError(
                "Too many items",
                details={"errors": [_field_error(field, f"At most {int(max_items)} items")]},
            )
        value = value[: int(max_items)]
    item_schema = schema.get("items") or {}
    if item_schema.get("type") != "object":
        return list(value)
    cleaned: list[Any] = []
    for index, item in enumerate(value):
        try:
            cleaned.append(
                _validate_against_schema(item, item_schema, field=f"{field}.{index}", lenient=lenient)
            )
        except ValidationError:
            if not lenient:
                raise
    return cleaned


def validate_section_content(
    section_type_id: str,
    content: dict[str, Any],
    *,
    content_schema: dict[str, Any] | None = None,
    lenient: bool = False,
) -> dict[str, Any]:
    if section_type_id not in ALLOWED_SECTION_TYPE_IDS and content_schema is None:
        raise ValidationError(
            "Unknown or disallowed section type",
            details={"errors": [_field_error("section_type_id", "Not a platform section type")]},
        )
    if not isinstance(content, dict):
        raise ValidationError(
            "Section content must be an object",
            details={"errors": [_field_error("content", "Must be an object")]},
        )
    schema = content_schema or CORE_SECTION_SCHEMAS.get(section_type_id) or {"type": "object"}
    cleaned = _validate_against_schema(content, schema, field="content", lenient=lenient)
    assert_no_unsafe_content(cleaned)
    if section_type_id == "composition":
        # Geometry, layers, plates and the phone arrangement are the grammar's,
        # whoever proposed them: always the normalized form is stored.
        from platform_core.website.composition_grammar import normalize

        return normalize(cleaned)
    return cleaned if lenient else content


def validate_generation_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("Generation payload must be an object")
    pages = raw.get("pages")
    navigation = raw.get("navigation")
    theme_hints = raw.get("theme_hints") or {}
    if not isinstance(pages, list) or not pages:
        raise ValidationError("Generation payload must include pages")
    if not isinstance(navigation, list):
        raise ValidationError("Generation payload must include navigation")
    if not isinstance(theme_hints, dict):
        raise ValidationError("theme_hints must be an object")
    for page in pages:
        if not isinstance(page, dict):
            raise ValidationError("Invalid page in generation payload")
        for key in ("slug", "title", "page_type", "sections"):
            if key not in page:
                raise ValidationError(f"Page missing {key}")
        page["page_type"] = _coerce_page_type(page.get("page_type"))
        kept_sections: list[Any] = []
        for section in page["sections"]:
            if not isinstance(section, dict):
                raise ValidationError("Invalid section in generation payload")
            section_type_id = str(section.get("section_type_id") or "")
            content = section.get("content") or {}
            try:
                section["content"] = validate_section_content(
                    section_type_id, content, lenient=True
                )
            except ValidationError:
                # A section the AI got wrong (missing a required field, wrong
                # type) is dropped rather than failing the whole draft. The
                # deterministic fallback covers a genuinely empty result.
                continue
            assert_no_unsafe_content({k: v for k, v in section.items() if k != "content"})
            kept_sections.append(section)
        page["sections"] = kept_sections
    assert_no_unsafe_content(navigation)
    assert_no_unsafe_content(theme_hints)
    return {
        "pages": pages,
        "navigation": navigation,
        "theme_hints": theme_hints,
    }


def validate_page_patch(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "seo_title", "seo_description", "is_published", "sort_order", "navigation", "theme"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValidationError(
            "Unknown page fields",
            details={"errors": [_field_error(k, "Not allowed") for k in sorted(unknown)]},
        )
    out: dict[str, Any] = {}
    if "title" in raw:
        title = str(raw["title"]).strip()
        if not title or len(title) > 120:
            raise ValidationError("Invalid title")
        out["title"] = title
        assert_no_unsafe_content(title, path="title")
    for key in ("seo_title", "seo_description"):
        if key in raw:
            value = raw[key]
            if value is not None:
                value = str(value).strip()
                assert_no_unsafe_content(value, path=key)
            out[key] = value
    if "is_published" in raw:
        out["is_published"] = bool(raw["is_published"])
    if "sort_order" in raw:
        out["sort_order"] = int(raw["sort_order"])
    return out


def validate_section_patch(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {"content", "layout_variant", "is_visible", "sort_order"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValidationError(
            "Unknown section fields",
            details={"errors": [_field_error(k, "Not allowed") for k in sorted(unknown)]},
        )
    out: dict[str, Any] = {}
    if "content" in raw:
        if not isinstance(raw["content"], dict):
            raise ValidationError("content must be an object")
        out["content"] = raw["content"]
    if "layout_variant" in raw:
        out["layout_variant"] = (
            str(raw["layout_variant"]).strip() if raw["layout_variant"] is not None else None
        )
    if "is_visible" in raw:
        out["is_visible"] = bool(raw["is_visible"])
    if "sort_order" in raw:
        out["sort_order"] = int(raw["sort_order"])
    return out
