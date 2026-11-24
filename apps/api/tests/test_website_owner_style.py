"""An owner personalises their website — and never loses its design doing so.

Found 2026-11-13: the Workspace's Theme page sent two colours and the API kept
them as the WHOLE theme, so one click turned a designed site back into the
default template. A theme edit is now laid over the stored theme; the design
pipeline's keys cannot be dropped; `owner_style` holds only what the renderer
can draw; and the same edits can be asked for in words.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.exceptions import ValidationError
from platform_core.website import site_assistant as sa
from platform_core.website.owner_style import clean_owner_style, merge_theme

from test_website_kernel import _create_business, owner  # noqa: F401 — fixture

DESIGNED = {
    "primary_color": "#2f5d1f", "accent_color": "#c8922a", "personality": "warm",
    "dna": {"concept": "warm_craft", "display": "fraunces", "body": "manrope"},
    "experience": {"motion": "silk", "hero": "arch"}, "composition": {"range_layout": "menu_book"},
    "type_system": "friendly_local", "design_family": "editorial_warm",
}


# ------------------------------------------------------------------ the merge rule
def test_a_colour_edit_keeps_the_design() -> None:
    merged = merge_theme(DESIGNED, {"primary_color": "#7b1e2b"})
    assert merged["primary_color"] == "#7b1e2b" and merged["accent_color"] == "#c8922a"
    assert merged["dna"] == DESIGNED["dna"] and merged["experience"] == DESIGNED["experience"]
    assert merged["composition"] == DESIGNED["composition"] and merged["design_family"] == "editorial_warm"


def test_design_keys_cannot_be_removed_but_an_owners_colour_can() -> None:
    merged = merge_theme({**DESIGNED, "background_color": "#fff8ee"},
                         {"dna": None, "experience": None, "background_color": None})
    assert merged["dna"] == DESIGNED["dna"] and merged["experience"] == DESIGNED["experience"]
    assert "background_color" not in merged


def test_owner_style_is_merged_choice_by_choice_and_held_to_the_renderers_values() -> None:
    first = merge_theme(DESIGNED, {"owner_style": {"heading_size": "large"}})
    second = merge_theme(first, {"owner_style": {"font": "elegant"}})
    assert second["owner_style"] == {"heading_size": "large", "font": "elegant",
                                     "font_display": "cormorant", "font_body": "manrope"}
    back = merge_theme(second, {"owner_style": {"font": None}})
    assert back["owner_style"] == {"heading_size": "large"}
    assert "owner_style" not in merge_theme(back, {"owner_style": None}) or merge_theme(
        back, {"owner_style": {"heading_size": None}}).get("owner_style") is None
    with pytest.raises(ValidationError):
        clean_owner_style({"heading_size": "gigantic"})
    with pytest.raises(ValidationError):
        clean_owner_style({"font_display": "comic-sans"})
    with pytest.raises(ValidationError):
        clean_owner_style({"custom_css": "body{display:none}"})
    with pytest.raises(ValidationError):
        merge_theme(DESIGNED, {"primary_color": "red; background:url(x)"})


# ------------------------------------------------------------------ saying it
@pytest.mark.parametrize(("said", "changes"), [
    ("make the headings bigger", [("style", "heading_size")]),
    ("chnge colur to maroon", [("colour", "primary")]),
    ("make it green and gold", [("colour", "primary"), ("colour", "accent")]),
    ("change the background to cream", [("colour", "background")]),
    ("text is too small, cant read", [("style", "text_size")]),
    ("heading too big", [("style", "heading_size")]),
    ("use a more elegant font", [("style", "font")]),
    ("rounded buttons please", [("style", "corners")]),
    ("move the menu above our story", [("move", "")]),
    ("please mov menu up", [("move", "")]),
    ("hide the gallery", [("visibility", "")]),
    ("delete the faq section", [("remove", "")]),
    ("duplicate the about section", [("duplicate", "")]),
    ("add a gallery", [("add", "gallery")]),
    ("headline should say Fresh every morning", [("text", "")]),
    ("change button text to Order on WhatsApp", [("text", "")]),
    ("rewrite the about section", [("rewrite", "")]),
    ("go back to the original design", [("undo_style", "")]),
    ("make headline bigger and change colour to navy then hide the story",
     [("style", "heading_size"), ("colour", "primary"), ("visibility", "")]),
])
def test_an_owners_words_are_read_into_governed_changes(said: str, changes: list[tuple[str, str]]) -> None:
    assert [(c.kind, c.target) for c in sa.read(said).changes] == changes


def test_words_given_for_a_headline_are_kept_exactly_and_never_read_as_a_colour_or_a_move() -> None:
    text = sa.read("change headline to Move over, green chutney — red is here").changes
    assert len(text) == 1 and text[0].kind == "text" and text[0].value == "Move over, green chutney — red is here"
    button = sa.read("change button text to Order on WhatsApp").changes[0]
    assert (button.field_name, button.value, button.section) == ("cta_label", "Order on WhatsApp", "")


@pytest.mark.parametrize("said", ["add online payment", "make the site load faster", "what is my revenue"])
def test_what_cannot_be_done_is_not_pretended(said: str) -> None:
    plan = sa.read(said)
    assert plan.changes == [] and plan.unclear


def test_a_models_answer_is_held_to_the_same_vocabulary() -> None:
    plan = sa.from_model({"changes": [
        {"kind": "colour", "target": "primary", "value": "#0a7d5c"},
        {"kind": "colour", "target": "everything", "value": "#000000"},
        {"kind": "style", "target": "font", "value": "comic sans"},
        {"kind": "style", "target": "custom_css", "value": "x"},
        {"kind": "run_sql", "value": "drop table"},
        {"kind": "move", "section": "menu", "where": "sideways"},
        {"kind": "text", "field_name": "headline", "value": ""},
        {"kind": "add", "target": "payments"},
    ], "cannot": "I cannot add payments from here."})
    assert [(c.kind, c.value) for c in plan.changes] == [("colour", "#0a7d5c")]
    assert plan.unclear == ["I cannot add payments from here."]


# ------------------------------------------------------------------ through the API
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_the_theme_page_can_no_longer_erase_a_sites_design(owner: tuple[dict[str, str], uuid.UUID]) -> None:  # noqa: F811
    headers, _ = owner
    client = TestClient(app)
    bid = _create_business(client, headers)["id"]
    assert client.patch(f"/v1/b/{bid}/website/theme", json={"theme": DESIGNED}, headers=headers).status_code == 200

    # What the old Theme page sent: two colours and nothing else.
    res = client.patch(f"/v1/b/{bid}/website/theme",
                       json={"theme": {"primary_color": "#0F766E", "accent_color": "#F59E0B"}}, headers=headers)
    assert res.status_code == 200, res.text
    theme = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]["draft"]["theme"]
    assert theme["primary_color"] == "#0F766E" and theme["dna"] == DESIGNED["dna"]
    assert theme["experience"] == DESIGNED["experience"] and theme["type_system"] == "friendly_local"

    bad = client.patch(f"/v1/b/{bid}/website/theme",
                       json={"theme": {"owner_style": {"heading_size": "gigantic"}}}, headers=headers)
    assert bad.status_code == 422


def _sections(client: TestClient, bid: str, headers: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    draft = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]["draft"]
    page = next(p for p in draft["pages"] if p["slug"] == "home")
    return draft, sorted(page["sections"], key=lambda s: s["sort_order"])


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_an_owner_changes_the_site_by_saying_so(owner: tuple[dict[str, str], uuid.UUID], monkeypatch: Any) -> None:  # noqa: F811
    monkeypatch.setenv("LOCAH_TEST_NO_EXTERNAL_AI", "1")
    headers, _ = owner
    client = TestClient(app)
    bid = _create_business(client, headers)["id"]
    client.patch(f"/v1/b/{bid}/website/theme", json={"theme": DESIGNED}, headers=headers)
    draft, before = _sections(client, bid, headers)
    page_id = next(p["id"] for p in draft["pages"] if p["slug"] == "home")
    for kind, content in (("text_block", {"title": "A note", "body": "Hello."}), ("gallery", {"title": "Gallery"})):
        added = client.post(f"/v1/b/{bid}/website/pages/{page_id}/sections",
                            json={"section_type_id": kind, "content": content}, headers=headers)
        assert added.status_code == 200, added.text

    def ask(message: str) -> dict[str, Any]:
        res = client.post(f"/v1/b/{bid}/website/assistant", json={"message": message}, headers=headers)
        assert res.status_code == 200, res.text
        return dict(res.json()["data"])

    look = ask("chnge colur to maroon and make the headings much bigger, use an elegant font")
    assert look["changed"] and look["theme_changed"]
    theme = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]["draft"]["theme"]
    assert theme["primary_color"] == "#7b1e2b" and theme["dna"] == DESIGNED["dna"]
    assert theme["owner_style"] == {"heading_size": "xlarge", "font": "elegant",
                                    "font_display": "cormorant", "font_body": "manrope"}

    _, sections = _sections(client, bid, headers)
    kinds = [s["section_type_id"] for s in sections]
    assert kinds[-2:] == ["text_block", "gallery"]
    moved = ask("move the gallery above the text")
    assert moved["structure_changed"], moved
    _, sections = _sections(client, bid, headers)
    assert [s["section_type_id"] for s in sections][-2:] == ["gallery", "text_block"]

    hidden = ask("hide the gallery")
    _, sections = _sections(client, bid, headers)
    assert hidden["changed"] and next(s for s in sections if s["section_type_id"] == "gallery")["is_visible"] is False
    ask("show the gallery again")
    _, sections = _sections(client, bid, headers)
    assert next(s for s in sections if s["section_type_id"] == "gallery")["is_visible"] is True

    worded = ask("change the text heading to Fresh every morning")
    _, sections = _sections(client, bid, headers)
    assert worded["changed"] and next(
        s for s in sections if s["section_type_id"] == "text_block")["content"]["title"] == "Fresh every morning"

    ask("remove the gallery")
    _, sections = _sections(client, bid, headers)
    assert "gallery" not in [s["section_type_id"] for s in sections]

    honest = ask("add online payment")
    assert honest["changed"] is False and "did not change anything" in honest["reply"]

    back = ask("go back to the original design")
    theme = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]["draft"]["theme"]
    assert back["changed"] and "owner_style" not in theme and theme["dna"] == DESIGNED["dna"]


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_only_someone_who_may_edit_the_website_may_ask(owner: tuple[dict[str, str], uuid.UUID]) -> None:  # noqa: F811
    from test_website_kernel import _headers, _seed

    headers, _ = owner
    client = TestClient(app)
    bid = _create_business(client, headers)["id"]
    stranger = uuid.uuid4()
    _seed(stranger, f"{stranger}@example.com")
    res = client.post(f"/v1/b/{bid}/website/assistant", json={"message": "make it pink"},
                      headers=_headers(stranger, f"{stranger}@example.com"))
    assert res.status_code in (403, 404)


def test_the_renderer_knows_every_face_and_size_an_owner_may_choose() -> None:
    """owner_style.py is the registry; experience.ts must be able to draw all of it."""
    import re
    from pathlib import Path

    from platform_core.website.owner_style import BODY_FACES, CORNERS, DISPLAY_FACES, FONT_PAIRS, SIZES

    root = Path(__file__).resolve().parents[3]
    source = (root / "apps/web/src/components/website/experience/experience.ts").read_text(encoding="utf-8")

    def listed(name: str) -> set[str]:
        block = re.search(rf"\b{name}: \[(.*?)\]", source, re.S)
        assert block, name
        return set(re.findall(r"'([a-z0-9]+)'", block.group(1)))

    assert set(DISPLAY_FACES) == listed("display") and set(BODY_FACES) == listed("body")
    for pair in FONT_PAIRS.values():
        assert pair["display"] in DISPLAY_FACES and pair["body"] in BODY_FACES
    sizes = re.search(r"OWNER_SIZES = \[(.*?)\]", source)
    corners = re.search(r"OWNER_CORNERS = \[(.*?)\]", source)
    assert sizes and set(re.findall(r"'([a-z]+)'", sizes.group(1))) == set(SIZES)
    assert corners and set(re.findall(r"'([a-z]+)'", corners.group(1))) == set(CORNERS)
    sheet = (root / "packages/ui/src/site-owner.css").read_text(encoding="utf-8")
    for size in SIZES:
        if size != "regular":
            assert f"data-owner-heading='{size}'" in sheet and f"data-owner-text='{size}'" in sheet
    for corner in CORNERS:
        assert f"data-owner-corners='{corner}'" in sheet


# ------------------------------------------------------------------ "make it look like this"
def test_a_reference_is_read_into_the_sites_own_vocabulary_and_nothing_else() -> None:
    from platform_core.website import reference_style as rs

    style = rs.govern({"is_design": True, "background": "#0e0e0e", "text": "#333333", "primary": "#d4ff3a",
                       "accent": "#ffffff", "lettering": "poster", "corners": "sharp", "heading_size": "xlarge",
                       "mood": ["cinematic", "bold"], "why": "Huge condensed capitals on black.",
                       "layout": "copy this exactly", "custom_css": "body{display:none}", "logo": "NIKE"})
    assert style is not None
    assert style.theme["background_color"] == "#0e0e0e" and style.theme["palette_mode"] == "dark"
    assert style.theme["text_color"] == "#f5f1ea"  # grey on black would not read: replaced, not trusted
    assert style.theme["primary_color"] == "#d4ff3a"
    assert style.theme["owner_style"] == {"font": "poster", "corners": "sharp", "heading_size": "xlarge"}
    assert set(style.theme) <= {"background_color", "text_color", "palette_mode", "primary_color",
                                "accent_color", "owner_style", "surface_alt_color", "muted_color"}
    # A dark ground brings a dark alternate band with it, never a light one.
    assert style.theme["surface_alt_color"] != "#ffffff" and style.theme["surface_alt_color"] < "#40"
    merged = merge_theme(DESIGNED, style.theme)
    assert merged["dna"] == DESIGNED["dna"] and merged["experience"] == DESIGNED["experience"]


def test_a_colour_that_would_vanish_and_a_picture_that_is_no_design_are_refused() -> None:
    from platform_core.website import reference_style as rs

    faint = rs.govern({"is_design": True, "background": "#ffffff", "text": "#111111", "primary": "#fdfdf5",
                       "lettering": "modern", "corners": "soft", "heading_size": "regular"})
    assert faint is not None and "primary_color" not in faint.theme and faint.dropped
    assert rs.govern({"is_design": False, "background": "#ffffff", "text": "#000000", "primary": "#ff0000",
                      "lettering": "modern", "corners": "soft", "heading_size": "regular"}) is None
    assert rs.govern({"lettering": "comic sans", "corners": "wobbly"}) is None


def test_undoing_a_match_puts_the_designed_look_back() -> None:
    from platform_core.website import reference_style as rs

    before = {**DESIGNED, "owner_style": {"heading_size": "large"}}
    matched = merge_theme(before, {"background_color": "#0e0e0e", "text_color": "#f5f1ea", "palette_mode": "dark",
                                   "primary_color": "#d4ff3a", "owner_style": {"font": "poster"},
                                   rs.UNDO_KEY: rs.snapshot(before)})
    back = rs.undo(matched)
    assert back is not None
    edit, drop = back
    restored = merge_theme(matched, edit)
    for key in drop:
        restored.pop(key, None)
    restored = merge_theme(restored, {"owner_style": matched[rs.UNDO_KEY]["owner_style"]})
    assert restored == before
    voiced = {**before, "dna": {**before["dna"], "headline": "italic"}}
    borrowed = merge_theme(voiced, {"dna": {**voiced["dna"], "headline": "none"}, rs.UNDO_KEY: rs.snapshot(voiced)})
    edit, _ = rs.undo(borrowed) or ({}, ())
    assert merge_theme(borrowed, edit)["dna"]["headline"] == "italic"
