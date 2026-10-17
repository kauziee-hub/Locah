"""Personalization lands on a draft the owner may already be changing.

The first version is written the moment the owner presses Build; the
personalized one (model words, drawn pictures) arrives a minute later. Before
this module, any message the owner sent in that minute — even "looks good" —
changed the draft, and the whole personalized site was thrown away as
"superseded".

Now the build records a fingerprint of every section it wrote. When
personalization finishes, each section is compared with that fingerprint:

* untouched since the build → the personalized section replaces it;
* changed by the owner (talking to LOCAH, the editor) → the owner's section
  stays exactly as it is — owner edits always win;
* removed by the owner → stays removed;
* added by the owner → kept.

Theme and navigation follow the same rule, and so does every page of a
multi-page site: a page the owner deleted stays deleted, a page the
personalization adds that the build did not have is added. A page the owner
added themselves means they restructured the site: personalization then
does not apply. Pure functions over plain dicts.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

_SECTION_KEYS = ("content", "layout_variant", "is_visible")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def section_fingerprint(section: dict[str, Any]) -> str:
    return _digest({k: section.get(k) for k in _SECTION_KEYS})


def _home(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((p for p in pages if p.get("slug") == "home"), pages[0] if pages else None)


def _keyed(sections: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Each section with a key: its type, and "type#n" for the n-th repeat."""
    seen: Counter[str] = Counter()
    out = []
    for section in sections:
        kind = str(section["section_type_id"])
        out.append((kind if not seen[kind] else f"{kind}#{seen[kind]}", section))
        seen[kind] += 1
    return out


def base_fingerprints(draft: dict[str, Any]) -> dict[str, Any]:
    """What the build wrote, as fingerprints: from a draft aggregate's "draft"."""
    pages = draft.get("pages") or []
    home = _home(pages)
    by_page = {str(page.get("slug")): {key: section_fingerprint(s) for key, s in _keyed(page.get("sections") or [])}
               for page in pages}
    return {"sections": by_page.get(str((home or {}).get("slug")), {}), "page_sections": by_page,
            "theme": _digest(draft.get("theme") or {}),
            "navigation": _digest(draft.get("navigation") or []),
            "pages": len(pages)}


def _as_payload_section(section: dict[str, Any]) -> dict[str, Any]:
    out = {"section_type_id": section["section_type_id"], "content": dict(section.get("content") or {}),
           "is_visible": section.get("is_visible", True)}
    if section.get("layout_variant"):
        out["layout_variant"] = section["layout_variant"]
    return out


def _merge_page(page: dict[str, Any], live_page: dict[str, Any], base_sections: dict[str, str]
                ) -> tuple[dict[str, Any], list[str]]:
    live_by_key = dict(_keyed(live_page.get("sections") or []))
    kept: list[str] = []
    merged: list[dict[str, Any]] = []
    composed = _keyed(page["sections"])
    for key, section in composed:
        kind = str(section["section_type_id"])
        mine = live_by_key.get(key)
        if mine is None:
            if key in base_sections:
                kept.append(kind)  # the owner removed it: it stays removed
                continue
            merged.append(section)
        elif section_fingerprint(mine) == base_sections.get(key):
            merged.append(section)
        else:
            kept.append(kind)
            merged.append(_as_payload_section(mine))
    composed_keys = {key for key, _ in composed}
    extras = [s for key, s in _keyed(live_page.get("sections") or [])
              if key not in composed_keys and section_fingerprint(s) != base_sections.get(key)]
    if extras:
        kept += [str(s["section_type_id"]) for s in extras]
        at = next((i for i, s in enumerate(merged) if s["section_type_id"] == "contact"), len(merged))
        merged[at:at] = [_as_payload_section(s) for s in extras]
    return {**page, "sections": merged}, kept


def merge(personalized: dict[str, Any], live: dict[str, Any], base: dict[str, Any]
          ) -> tuple[dict[str, Any] | None, list[str]]:
    """The personalized payload with every owner change since the build kept.

    Returns (payload, kept) — ``kept`` names the section types (prefixed by the
    page slug off the home page; and "theme", "navigation") the owner had
    changed. Returns (None, []) when the owner restructured the site (added
    pages): then personalization does not apply.
    """
    live_pages = live.get("pages") or []
    by_page: dict[str, dict[str, str]] | None = base.get("page_sections")
    if by_page is None:
        # A build recorded before sites had inner pages: its home only.
        if len(live_pages) > max(1, int(base.get("pages") or 1)):
            return None, []
        by_page = {str((_home(live_pages) or {}).get("slug") or "home"): base.get("sections") or {}}
    if {str(p.get("slug")) for p in live_pages} - set(by_page):
        return None, []
    home_slug = str((_home(personalized["pages"]) or {}).get("slug") or "home")
    kept: list[str] = []
    pages: list[dict[str, Any]] = []
    for page in personalized["pages"]:
        slug = str(page.get("slug"))
        live_page = next((p for p in live_pages if str(p.get("slug")) == slug), None)
        if live_page is None:
            if slug in by_page:
                kept.append(f"page:{slug}")  # the owner deleted it: it stays deleted
            else:
                pages.append(page)
            continue
        merged_page, page_kept = _merge_page(page, live_page, by_page.get(slug, {}))
        pages.append(merged_page)
        kept += page_kept if slug == home_slug else [f"{slug}:{k}" for k in page_kept]
    out = {**personalized, "pages": pages}
    if _digest(live.get("theme") or {}) != base.get("theme"):
        out["theme_hints"] = {**(live.get("theme") or {}),
                              "generation": (personalized.get("theme_hints") or {}).get("generation", {})}
        kept.append("theme")
    if _digest(live.get("navigation") or []) != base.get("navigation"):
        out["navigation"] = live.get("navigation") or []
        kept.append("navigation")
    return out, kept


def _live_section(section: dict[str, Any]) -> dict[str, Any]:
    """A live section as payload, its module binding kept."""
    out = _as_payload_section(section)
    if section.get("module_binding"):
        out["module_binding"] = section["module_binding"]
    return out


def _live_page(page: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {"slug": page.get("slug"), "title": page.get("title"), "page_type": page.get("page_type"),
            "seo_title": page.get("seo_title"), "seo_description": page.get("seo_description"),
            "sections": sections}


def section_key(sections: list[dict[str, Any]], section_id: str) -> str | None:
    """The merge key ("type" or "type#n") of the section with this id."""
    return next((key for key, s in _keyed(sections) if str(s.get("id")) == section_id), None)


def replace_scope(personalized: dict[str, Any], live: dict[str, Any], scope: dict[str, Any]
                  ) -> tuple[dict[str, Any] | None, str]:
    """The live draft, untouched, with only ``scope`` taken from a fresh composition.

    ``scope`` is ``{"page": slug}`` — the whole page regenerated — or
    ``{"page": slug, "section": "type#n"}`` — one section. Everything else,
    including every section the owner edited by hand, the theme and the
    navigation, stays exactly as it is: the owner asked for this part anew,
    not the site. Returns (None, reason) when the fresh composition has no
    such page or section (the site's structure moved on since it was built).
    """
    slug = str(scope.get("page") or "")
    key = scope.get("section")
    live_pages = live.get("pages") or []
    target = next((p for p in live_pages if str(p.get("slug")) == slug), None)
    fresh = next((p for p in personalized.get("pages") or [] if str(p.get("slug")) == slug), None)
    if target is None:
        return None, f"the site has no page '{slug}'"
    if fresh is None:
        return None, f"a fresh composition has no '{slug}' page to take"
    fresh_by_key = dict(_keyed(fresh.get("sections") or []))
    if key and key not in fresh_by_key:
        return None, f"a fresh composition has no '{key}' on '{slug}'"
    pages: list[dict[str, Any]] = []
    for page in live_pages:
        keyed = _keyed(page.get("sections") or [])
        if page is not target:
            sections = [_live_section(s) for _, s in keyed]
        elif key:
            sections = [dict(fresh_by_key[k]) if k == key else _live_section(s) for k, s in keyed]
        else:
            sections = [dict(s) for s in fresh.get("sections") or []]
        pages.append(_live_page(page, sections))
    out = {**personalized, "pages": pages, "navigation": live.get("navigation") or [],
           "theme_hints": {**(live.get("theme") or {}),
                           "generation": (personalized.get("theme_hints") or {}).get("generation", {})}}
    return out, ""
