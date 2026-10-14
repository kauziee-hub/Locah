"""The experience layer: how a site moves and which scenes it is built from.

Pure: no database, no model. Every choice must be one the business's real
content can carry — a ring of pictures needs pictures, a menu book needs
dishes — and the model's preference wins only inside that set.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from platform_core.interview.experience import (
    CATALOGUE_LAYOUTS,
    HERO_SCENES,
    MOTIONS,
    choose_experience,
    content_of,
    marquee_words,
    options_for_model,
)
from platform_core.interview.models import BusinessBlueprint
from platform_core.validation.website import validate_generation_payload

ASSET = "11111111-1111-4111-8111-111111111111"


def _bp() -> BusinessBlueprint:
    return BusinessBlueprint(business_id=uuid4())


def _menu(items: int, pictured: int = 0) -> list[dict[str, Any]]:
    rows = [{"name": f"Dish {i}", "category": "Mains" if i % 2 else "Starters", "price": "₹120"}
            for i in range(items)]
    for row in rows[:pictured]:
        row["image_asset_id"] = ASSET
    return [
        {"section_type_id": "hero", "content": {"headline": "Home food", "image_asset_id": ASSET}},
        {"section_type_id": "product_showcase", "content": {"items": rows, "categories": [
            {"name": "Starters"}, {"name": "Mains"}]}},
        {"section_type_id": "about", "content": {"body": "We cook at home every morning. " * 6,
                                                 "image_asset_id": ASSET}},
    ]


WARM_FOOD = {"offering": "menu", "personality": "warm", "energy": "medium", "trust": "normal",
             "positioning": "heritage", "service_mode": "food"}
CALM_CLINIC = {"offering": "service", "personality": "calm", "energy": "low", "trust": "high",
               "positioning": "everyday", "service_mode": "care"}
GYM = {"offering": "plan", "personality": "bold", "energy": "high", "trust": "normal",
       "positioning": "modern", "service_mode": "none"}


def test_a_menu_is_read_like_a_menu() -> None:
    exp = choose_experience(_bp(), archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                            sections=_menu(12, pictured=6), expected_pictures=8)
    assert exp.catalogue == "menu_book"
    assert exp.motion == "silk"
    assert exp.hero in HERO_SCENES


def test_a_ring_or_a_wall_only_where_there_are_pictures_for_it() -> None:
    for seed in range(30):
        bp = _bp()
        few = choose_experience(bp, archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                                sections=_menu(8), expected_pictures=1, seed=str(seed))
        assert few.hero not in {"orbit", "plane"}
    many = {choose_experience(_bp(), archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                              sections=_menu(8, pictured=6), expected_pictures=8, seed=str(s)).hero
            for s in range(40)}
    assert many & {"orbit", "plane"}


def test_no_photographs_means_type_or_a_living_gradient() -> None:
    sections = [{"section_type_id": "hero", "content": {"headline": "Strength"}}]
    exp = choose_experience(_bp(), archetype="membership_fitness", family="monumental", dims=GYM,
                            sections=sections, expected_pictures=0)
    assert exp.hero in {"kinetic", "aurora"}
    assert exp.motion == "snap"


def test_a_clinic_is_calm_and_never_spins() -> None:
    sections = _menu(6, pictured=6)
    for seed in range(30):
        exp = choose_experience(_bp(), archetype="service_appointment", family="calm_professional",
                                dims=CALM_CLINIC, sections=sections, expected_pictures=6, seed=str(seed),
                                choices={"hero": "orbit", "motion": "snap"})
        assert exp.motion == "calm"
        assert exp.hero not in {"orbit", "plane", "kinetic"}
        assert not exp.marquee and not exp.intro


def test_the_model_wins_only_inside_what_the_content_can_carry() -> None:
    sections = _menu(12, pictured=6)
    chosen = choose_experience(_bp(), archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                               sections=sections, expected_pictures=8,
                               choices={"hero": "plane", "motion": "float", "story": "word_reveal"})
    assert (chosen.hero, chosen.motion, chosen.story) == ("plane", "float", "word_reveal")
    refused = choose_experience(_bp(), archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                                sections=_menu(12), expected_pictures=0, choices={"hero": "orbit"})
    assert refused.hero != "orbit"


def test_the_same_business_always_gets_the_same_site() -> None:
    bp = _bp()
    a = choose_experience(bp, archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                          sections=_menu(10, pictured=6), expected_pictures=8)
    b = choose_experience(bp, archetype="menu_commerce", family="editorial_warm", dims=WARM_FOOD,
                          sections=_menu(10, pictured=6), expected_pictures=8)
    assert a == b


def test_plans_stack_and_projects_take_the_spotlight() -> None:
    plans = [{"section_type_id": "product_showcase", "content": {"items": [{"name": "Monthly"}, {"name": "Yearly"}]}}]
    assert choose_experience(_bp(), archetype="membership_fitness", family="monumental", dims=GYM,
                             sections=plans).catalogue == "stack"
    projects = [{"section_type_id": "product_showcase", "content": {"items": [
        {"name": "Greens", "image_asset_id": ASSET}, {"name": "Heights"}, {"name": "Meadows"}]}}]
    dims = {**WARM_FOOD, "offering": "property", "personality": "refined"}
    assert choose_experience(_bp(), archetype="real_estate_projects", family="airy_property", dims=dims,
                             sections=projects, expected_pictures=4).catalogue in {"spotlight", "stack"}


def test_the_moving_band_says_only_the_business_own_words() -> None:
    sections = [{"section_type_id": "product_showcase", "content": {
        "categories": [{"name": "Podis"}, {"name": "Pickles"}, {"name": "A very long category name that is a sentence"}],
        "filters": ["Sweets"]}}]
    words = marquee_words(sections, ["Sent by courier", "UPI, before dispatch"])
    assert words == ["Podis", "Pickles", "Sweets", "Sent by courier", "UPI, before dispatch"]


def test_every_option_offered_to_the_model_is_one_the_renderer_draws() -> None:
    options = options_for_model("menu_commerce", "editorial_warm", WARM_FOOD, pictures=8, items=14,
                                story_chars=300)
    assert {o["id"] for o in options["motion"]} <= set(MOTIONS)
    assert {o["id"] for o in options["hero"]} <= set(HERO_SCENES)
    assert {o["id"] for o in options["catalogue"]} <= set(CATALOGUE_LAYOUTS) | {"category_boards"}
    assert all(o["is"] for role in options.values() for o in role)


def test_menu_items_carry_what_a_diner_looks_for_and_the_band_validates() -> None:
    payload = {
        "pages": [{"slug": "home", "title": "Home", "page_type": "home", "sections": [
            {"section_type_id": "hero", "layout_variant": "orbit", "content": {"headline": "Home food"}},
            {"section_type_id": "marquee", "layout_variant": "band", "content": {"items": ["Podis", "Pickles"]}},
            {"section_type_id": "product_showcase", "layout_variant": "menu_book", "content": {"items": [
                {"name": "Lemon pickle", "price": "₹150", "diet": "veg", "spice": "hot", "tag": "Bestseller"}]}},
        ]}],
        "navigation": [{"label": "Home", "path": "/"}],
        "theme_hints": {},
    }
    checked = validate_generation_payload(payload)
    item = checked["pages"][0]["sections"][2]["content"]["items"][0]
    assert (item["diet"], item["spice"], item["tag"]) == ("veg", "hot", "Bestseller")


def test_content_counts_planned_pictures_before_they_are_drawn() -> None:
    sections = [{"section_type_id": "hero", "content": {"headline": "x"}}]
    assert content_of(sections, expected_pictures=5).pictures == 5
    assert content_of(sections).pictures == 0
