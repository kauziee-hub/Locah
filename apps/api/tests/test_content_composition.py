"""Composition must survive real media, not just emit impressive metadata."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any
from uuid import uuid4

import pytest

from platform_core.interview.composition import CHAPTERS, OPENINGS, RANGES, plan, vocabulary
from platform_core.interview.creative_director import CreativeChoices, creative_plan_schema, direct, generate_creative_plan
from platform_core.interview.site_composer import compose_site
from platform_core.interview.website import with_draft
from test_site_composer import ACTIVE
from test_website_premium_site import _rich_meat


def content() -> dict[str, Any]:
    return {
        "items": [{"name": f"Offering {i}", "category": f"Kind {i % 2}",
                   "image_asset_id": f"photo-{i}",
                   "description": "The owner's own substantial description of this specific offering."}
                  for i in range(8)],
        "categories": [{"name": f"Kind {i}", "image_asset_id": f"category-{i}"} for i in range(2)],
    }


def test_one_catalogue_supports_distinct_coherent_brand_intents() -> None:
    data = content()
    luxury = plan(**data, concept="quiet_luxury", archetype="product_commerce", seed="one")
    playful = plan(**data, concept="playful_pop", archetype="product_commerce", seed="one")
    technical = plan(**data, concept="technical_grid", archetype="product_commerce", seed="one")
    assert len({p["range_layout"] for p in (luxury, playful, technical)}) == 3
    assert luxury["chapters"] == "gallery" and technical["chapters"] == "index"
    assert luxury == plan(**data, concept="quiet_luxury", archetype="product_commerce", seed="one")


@pytest.mark.parametrize("layout", RANGES)
def test_director_choices_reach_the_plan_when_feasible(layout: str) -> None:
    data = content()
    before = deepcopy(data)
    result = plan(**data, concept="warm_craft", archetype="menu_commerce", seed="one",
                  choices={"range_layout": layout, "opening": "poster", "chapters": "index",
                           "rationale": "The owner describes a precise neighbourhood counter."})
    assert result["range_layout"] == layout
    assert result["opening"] == "poster" and result["chapters"] == "index"
    assert data == before  # no rewritten facts, discarded offerings or invented imagery


@pytest.mark.parametrize("layout", ["chapters", "hover_list", "spotlight", "bento", "menu_book", "unknown"])
def test_missing_photos_never_produce_an_empty_photographic_layout(layout: str) -> None:
    result = plan(items=[{"name": "Consultation"}], categories=[], concept="calm_care",
                  archetype="service_appointment", seed="one", choices={"range_layout": layout})
    assert result["range_layout"] == "compact_list"
    assert "rejected" in result["reasons"][-1]


def test_duplicate_photos_cannot_satisfy_the_layout_requirements() -> None:
    data = content()
    for row in data["items"] + data["categories"]:
        row["image_asset_id"] = "same-photo"
    result = plan(**data, concept="noir_editorial", archetype="product_commerce", seed="one")
    assert result["candidates"] == ["compact_list"]


def test_large_food_menu_prefers_browsing_over_individual_fullscreen_stories() -> None:
    data = content()
    data["items"] *= 4
    result = plan(**data, concept="fresh_market", archetype="menu_commerce", seed="one")
    assert result["range_layout"] == "menu_book"


def test_vocabulary_and_nested_schema_are_executable() -> None:
    words = vocabulary()
    assert set(words["opening"]) == set(OPENINGS)
    assert set(words["chapters"]) == set(CHAPTERS)
    assert set(words["range_layout"]) == set(RANGES)
    schema = creative_plan_schema()
    assert "CompositionChoices" in schema["$defs"]
    assert CreativeChoices().composition.range_layout == ""  # old responses still work


def test_chapter_photos_no_longer_override_the_directors_range_layout() -> None:
    from platform_core.interview.media_director import Slot, record

    bp = _rich_meat()
    for key in ("category:chicken", "category:mutton", "category:fish-seafood"):
        record(bp, Slot(key, "x", "4:3", "gallery", "Test asset"), uuid4())
    direction = direct(bp, "other")
    direction.model_choices["composition"] = {"range_layout": "compact_list", "opening": "poster"}
    payload = compose_site(bp, direction, with_draft(bp, None), business_type="other",
                           contact={"phone": "+919999999999"}, active_modules=ACTIVE)
    shop = next(p for p in payload["pages"] if p["slug"] == "shop")
    section = next(s for s in shop["sections"] if s["section_type_id"] == "product_showcase")
    assert section["layout_variant"] == "compact_list"
    assert payload["theme_hints"]["composition"]["opening"] == "poster"


@pytest.mark.asyncio
async def test_model_response_carries_composition_through_the_real_director() -> None:
    class LocalProvider:
        async def generate_structured(self, prompt, schema, config, **kwargs):
            context = json.loads(prompt)
            assert context["composition_grammar"] == vocabulary()
            assert "list position is not a preference" in config["system_prompt"]
            return {"creative": {"composition": {"opening": "poster", "chapters": "index",
                    "range_layout": "compact_list", "rationale": "A precise counter menu."}}, "copy": {}}

    bp = _rich_meat()
    direction, words, _, _ = await generate_creative_plan(bp, "other", provider=LocalProvider())
    payload = compose_site(bp, direction, with_draft(bp, words), business_type="other",
                           contact={"phone": "+919999999999"}, active_modules=ACTIVE)
    composed = payload["theme_hints"]["composition"]
    assert composed["opening"] == "poster" and composed["chapters"] == "index"
    assert composed["range_layout"] == "compact_list" and composed["rationale"] == "A precise counter menu."
