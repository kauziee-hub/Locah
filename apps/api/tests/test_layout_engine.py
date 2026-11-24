"""The layout engine: sections arranged for each business, held to one grammar.

A composition is words, pictures, numbers, lists and actions placed on a
12-column grid (website.composition_grammar); the layout engine chooses
arrangements per business (interview.layout_engine), the reference reader can
read one from a screenshot (website.reference_style.layouts). These tests hold
the three to their promises: every arrangement is drawable and readable, no
word is invented and none is lost, two businesses do not get one layout, and a
reference steers the arrangement without bringing its words.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from platform_core.exceptions import ValidationError
from platform_core.interview.layout_engine import (
    RECIPES,
    Composer,
    Material,
    Style,
    bind,
    from_geometry,
    material_from,
    mirrored,
    rearranged,
)
from platform_core.interview.site_critic import critique
from platform_core.validation.website import validate_section_content
from platform_core.website.composition_grammar import COLS, PHONE_COLS, SCHEMA, normalize
from platform_core.website.reference_style import layouts
from test_site_composer import compose, meat

P = [f"{n}{n}{n}{n}{n}{n}{n}{n}-{n}{n}{n}{n}-{n}{n}{n}{n}-{n}{n}{n}{n}-{n * 12}" for n in "123456"]
OWNER_WORDS = Material(
    eyebrow="Our story", title="A Kadavanthra kitchen, cooking the way home does",
    body="Fresh masala ground every morning. Nothing from a packet.", pictures=P[:2],
    action=("Our story", "/about"), quote="Home-style Kerala food, cooked with masala ground daily.",
    points=[{"title": "Fresh masala", "body": "Ground every morning."},
            {"title": "No packets", "body": "Nothing from a box."},
            {"title": "Home style", "body": "Cooked the way home does."}],
    figures=[("2013", "Cooking since"), ("8", "Dishes on the menu")],
    items=[{"name": "Chicken Biriyani", "price": "₹280", "description": "Our best seller", "image_asset_id": P[0]},
           {"name": "Mutton Biriyani", "price": "₹360", "image_asset_id": P[1]},
           {"name": "Fish Meals", "price": "₹260", "image_asset_id": P[2]}],
)
CONCEPTS = ("noir_editorial", "warm_craft", "quiet_luxury", "fresh_market", "playful_pop", "calm_care",
            "technical_grid", "kinetic_sport")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["col"] < b["col"] + b["span"] and b["col"] < a["col"] + a["span"]
            and a["row"] < b["row"] + b["rows"] and b["row"] < a["row"] + a["rows"])


# ------------------------------------------------------------------ the grammar
def test_a_composition_is_held_to_the_grid_and_words_never_sit_bare_on_a_picture() -> None:
    held = normalize({"role": "story", "items": [
        {"kind": "picture", "image_asset_id": P[0], "col": 11, "span": 9, "row": 9, "rows": 7},
        {"kind": "words", "title": "Over the picture", "col": 0, "span": 1, "row": 10, "rows": 2},
        {"kind": "words"},  # nothing to show
        {"kind": "marquee", "title": "not a kind"},
        {"kind": "picture"},  # no picture
    ]})
    picture, words = held["items"]
    assert picture["col"] + picture["span"] - 1 <= COLS and picture["row"] + picture["rows"] - 1 <= 10
    assert words["span"] >= 3, "a block too narrow to read is widened"
    # The empty top rows are gone: the composition starts where its first block does.
    assert min(b["row"] for b in held["items"]) == 1
    if _overlap(words, picture):
        assert words["plate"] and words["layer"] > picture["layer"]
    for block in held["items"]:
        assert 1 <= block["m_col"] <= PHONE_COLS and block["m_col"] + block["m_span"] - 1 <= PHONE_COLS
    assert sorted(b["m_order"] for b in held["items"]) == [1, 2]
    with pytest.raises(ValidationError):
        normalize({"items": [{"kind": "words"}, {"kind": "picture"}]})


def test_words_laid_over_a_picture_rest_on_its_edge_on_a_phone() -> None:
    held = normalize({"items": [
        {"kind": "picture", "image_asset_id": P[0], "col": 1, "span": 8, "row": 1, "rows": 4},
        {"kind": "words", "title": "Laid over", "col": 6, "span": 6, "row": 2, "rows": 2},
    ]})
    picture, words = sorted(held["items"], key=lambda b: b["m_order"])
    assert picture["kind"] == "picture" and words["plate"] and words["lift"]


def test_the_stored_schema_is_the_registrys_own() -> None:
    migration = next(Path(__file__).resolve().parents[3].glob(
        "infra/supabase/migrations/*_website_composition_section.sql")).read_text(encoding="utf-8")
    stored = json.loads(re.search(r"\n '(\{.*\})',\n", migration, re.S).group(1).replace("''", "'"))
    assert stored == SCHEMA


def test_an_owner_edit_is_validated_and_normalized_like_the_engines() -> None:
    content = validate_section_content("composition", {"items": [
        {"kind": "words", "title": "Mine", "col": 1, "span": 2, "row": 1, "rows": 1}]})
    assert content["items"][0]["span"] >= 3 and content["items"][0]["m_order"] == 1
    with pytest.raises(ValidationError):
        validate_section_content("composition", {"items": [{"kind": "words", "title": "<script>x</script>"}]})


# ------------------------------------------------------------------ the engine
@pytest.mark.parametrize("concept", CONCEPTS)
def test_every_recipe_draws_a_valid_composition_from_only_the_owners_words(concept: str) -> None:
    allowed = set(_strings(OWNER_WORDS.__dict__))
    composer = Composer(f"seed-{concept}", concept=concept, shape="arch", budget="signature")
    for role, recipes in RECIPES.items():
        for _ in recipes:
            section = composer.compose(role, OWNER_WORDS)
            assert section is not None and section["section_type_id"] == "composition"
            content = section["content"]
            assert content == normalize(content), "stored as the grammar holds it"
            said = {s for b in content["items"] for k, v in b.items()
                    if k in {"eyebrow", "title", "body", "value", "label", "caption", "cta_label", "price"}
                    for s in _strings(v)}
            for text in said:
                if re.fullmatch(r"\d{2}", text):
                    continue  # an ordinal marker (01, 02): numbering, not words
                pieces = [p for p in text.split(" · ") if p]
                assert all(p in allowed or any(p in a for a in allowed) for p in pieces), text
    assert len(composer.used) == len(set(composer.used)), "no arrangement twice on one site"


def test_two_businesses_of_one_trade_are_not_given_one_layout() -> None:
    def layout(seed: str) -> list[tuple[str, int]]:
        composer = Composer(seed, concept="warm_craft", shape="arch")
        out = []
        for role in ("story", "statement", "pillars", "featured"):
            content = composer.compose(role, OWNER_WORDS)["content"]
            out.append((content["recipe"], content["items"][0]["col"]))
        return out

    shapes = {tuple(layout(f"kitchen-{n}")) for n in range(12)}
    assert len(shapes) >= 8, "a dozen kitchens should rarely share an arrangement"


def test_a_role_the_material_cannot_carry_is_left_to_the_old_section() -> None:
    composer = Composer("x")
    assert composer.compose("story", Material(title="No picture")) is None
    assert composer.compose("featured", Material(items=OWNER_WORDS.items[:1])) is None


# ------------------------------------------------------------------ re-arranging
def test_another_arrangement_keeps_every_word_and_picture() -> None:
    content = Composer("x", concept="warm_craft", shape="arch").compose("story", OWNER_WORDS)["content"]
    before = material_from(content)
    after = rearranged(content, Style("warm_craft", "arch"))
    assert after is not None and after["recipe"] != content["recipe"]
    again = material_from(after)
    assert (again.title, again.body, again.action) == (before.title, before.body, before.action)
    assert set(again.pictures) <= set(before.pictures) and again.pictures
    flipped = mirrored(content)
    assert [b["col"] + b["span"] - 1 for b in flipped["items"]] == [COLS - b["col"] + 1 for b in content["items"]]


def test_an_arrangement_from_a_reference_takes_the_owners_words_and_loses_none() -> None:
    m = Material(title="A Kadavanthra kitchen", body="Fresh masala.", eyebrow="Our story", pictures=P[:2],
                 action=("Our story", "/about"))
    geometry = [{"kind": "picture", "col": 1, "span": 12, "row": 1, "rows": 4, "frame": "bleed"},
                {"kind": "words", "col": 2, "span": 5, "row": 3, "rows": 2, "size": "xl"},
                {"kind": "picture", "col": 9, "span": 3, "row": 5, "rows": 2},
                {"kind": "picture", "col": 1, "span": 3, "row": 5, "rows": 2}]  # more places than pictures
    blocks = bind(geometry, m, Style())
    said = {k: v for b in blocks for k, v in b.items() if k in {"title", "body", "eyebrow", "cta_url"}}
    assert said == {"title": m.title, "body": m.body, "eyebrow": m.eyebrow, "cta_url": "/about"}
    assert [b.get("image_asset_id") for b in blocks if b["kind"] == "picture"] == P[:2]
    content = Composer("x").compose("story", m)["content"]
    remade = from_geometry("story", geometry, content, Style())
    assert remade is not None and remade["recipe"] == "reference"
    words = next(b for b in remade["items"] if b.get("title"))
    assert words["plate"], "the reference laid its words over a picture: they get a plate"
    only_pictures = [{"kind": "picture", "col": 1, "span": 6, "row": 1, "rows": 3}]
    assert from_geometry("story", only_pictures, content, Style()) is None


def test_a_references_layout_is_geometry_and_never_its_words() -> None:
    read = layouts([
        {"role": "story", "blocks": [
            {"kind": "picture", "col": 9, "span": 9, "row": 0, "rows": 40, "frame": "bleed",
             "title": "Words from the picture"},
            {"kind": "words", "col": 2, "span": 5, "row": 3, "rows": 2, "size": "xl", "body": "Their copy",
             "cta_url": "https://elsewhere.example"},
            {"kind": "iframe", "col": 1, "span": 2, "row": 1, "rows": 1}]},
        {"role": "story", "blocks": [{"kind": "words", "col": 1, "span": 4, "row": 1, "rows": 1}]},
        {"role": "pillars", "blocks": [{"kind": "picture", "col": 1, "span": 4, "row": 1, "rows": 2}]},
        {"role": "hacked", "blocks": [{"kind": "words", "col": 1, "span": 4, "row": 1, "rows": 1}]},
    ])
    assert list(read) == ["story"], "one per role; a role needs something to read; unknown roles dropped"
    picture, words = read["story"]
    assert picture["col"] + picture["span"] - 1 <= 12 and picture["row"] >= 1 and picture["rows"] <= 10
    assert not set(_strings({k: v for k, v in words.items() if k not in {"kind", "size"}}))
    assert "title" not in picture and "body" not in words and "cta_url" not in words


# ------------------------------------------------------------------ on a whole site
def test_a_real_site_is_composed_and_the_critic_does_not_undo_it() -> None:
    payload = compose(meat())
    compositions = [(p["slug"], s) for p in payload["pages"] for s in p["sections"]
                    if s["section_type_id"] == "composition"]
    for _, section in compositions:
        assert section["content"] == normalize(section["content"])
    recipes = [s["content"]["recipe"] for _, s in compositions]
    assert len(recipes) == len(set(recipes))
    findings = [f for f in critique(payload) if f.where == "composition"]
    assert not [f for f in findings if f.code == "repeated_layout"], findings
