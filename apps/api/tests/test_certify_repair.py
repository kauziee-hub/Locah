"""The repair loop finds the section a defect is about and the lever for its layer."""

from __future__ import annotations

from platform_testing.certify.repair import attribute, plan

PAGE = {"slug": "home", "sections": [
    {"id": "s-hero", "section_type_id": "hero", "content": {"headline": "Family care on OMR",
                                                            "image_asset_id": "a1"}},
    {"id": "s-stmt", "section_type_id": "statement", "content": {"text": "Two doctors."}},
    {"id": "s-svc", "section_type_id": "product_showcase", "content": {"title": "Book a consultation"}},
    {"id": "s-faq", "section_type_id": "faq", "content": {"title": "Questions, answered"}},
    {"id": "s-hide", "section_type_id": "feature_grid", "content": {"title": "Hidden"}, "is_visible": False},
]}


def _d(text: str, layer: str = "composition", severity: str = "major", section: int = -1) -> dict:
    return {"page": "home", "section": section, "text": text, "layer": layer, "severity": severity,
            "source": "vision"}


def test_a_defect_is_matched_by_index_then_title_then_kind() -> None:
    assert attribute(_d("x", section=2), PAGE)["id"] == "s-svc"  # type: ignore[index]
    assert attribute(_d('"Book a consultation" is a bare price list'), PAGE)["id"] == "s-svc"  # type: ignore[index]
    assert attribute(_d("The FAQ accordion is cramped"), PAGE)["id"] == "s-faq"  # type: ignore[index]
    assert attribute(_d("The hero headline breaks mid-word"), PAGE)["id"] == "s-hero"  # type: ignore[index]
    assert attribute(_d("Something vague about the page"), PAGE) is None


def test_each_layer_gets_its_own_lever_and_input_has_none() -> None:
    critique = {"defects": [
        _d("The hero photo is a stock desk", layer="photo", severity="critical"),
        _d("The FAQ is cramped", layer="styling"),
        _d('"Book a consultation" says nothing', layer="copy"),
        _d("No photographs of the doctors", layer="input", severity="critical"),
        _d("The statement repeats the hero twice", layer="order"),
    ]}
    fixes = plan(critique, {"pages": [PAGE]}, limit=10, tried=set())
    assert [(f["section"]["id"], f["lever"]) for f in fixes] == [
        ("s-hero", "new_photo"), ("s-faq", "variant"), ("s-svc", "rewrite"), ("s-stmt", "hide")]


def test_a_tried_fix_is_not_tried_again_and_the_limit_holds() -> None:
    critique = {"defects": [_d("The FAQ is cramped", layer="styling"), _d("The hero is flat", layer="styling")]}
    fixes = plan(critique, {"pages": [PAGE]}, limit=1, tried={"s-faq:variant"})
    assert [f["key"] for f in fixes] == ["s-hero:variant"]
