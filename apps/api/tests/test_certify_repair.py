"""The repair loop finds the section a defect is about and the lever for its layer."""

from __future__ import annotations

from typing import Any

from platform_testing.certify.repair import attribute, plan

PAGE: dict[str, Any] = {"slug": "home", "sections": [
    {"id": "s-hero", "section_type_id": "hero", "content": {"headline": "Family care on OMR",
                                                            "image_asset_id": "a1"}},
    {"id": "s-stmt", "section_type_id": "statement", "content": {"text": "Two doctors."}},
    {"id": "s-svc", "section_type_id": "product_showcase", "content": {"title": "Book a consultation"}},
    {"id": "s-faq", "section_type_id": "faq", "content": {"title": "Questions, answered"}},
    {"id": "s-hide", "section_type_id": "feature_grid", "content": {"title": "Hidden"}, "is_visible": False},
]}


def _d(text: str, layer: str = "composition", severity: str = "major", section: int = -1) -> dict[str, Any]:
    return {"page": "home", "section": section, "text": text, "layer": layer, "severity": severity,
            "source": "vision"}


def test_a_defect_is_matched_by_index_then_title_then_kind() -> None:
    assert attribute(_d("x", section=2), PAGE)["id"] == "s-svc"
    assert attribute(_d('"Book a consultation" is a bare price list'), PAGE)["id"] == "s-svc"
    assert attribute(_d("The FAQ accordion is cramped"), PAGE)["id"] == "s-faq"
    assert attribute(_d("The hero headline breaks mid-word"), PAGE)["id"] == "s-hero"
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


def test_the_offerings_are_never_hidden_and_about_means_the_section() -> None:
    critique = {"defects": [
        _d('"Book a consultation" repeats the services twice', layer="order"),
        _d("Each room line says nothing about beds or views", layer="copy"),
    ]}
    page = dict(PAGE, sections=PAGE["sections"] + [
        {"id": "s-about", "section_type_id": "about", "content": {"title": "Since 1998"}}])
    assert plan(critique, {"pages": [page]}, limit=10, tried=set()) == []
    named = {"defects": [_d("The about section is one thin paragraph", layer="copy")]}
    assert [f["section"]["id"] for f in plan(named, {"pages": [page]}, limit=10, tried=set())] == ["s-about"]


def test_a_v1_critique_section_number_is_not_trusted() -> None:
    critique = {"version": "certify-critic-v1", "defects": [_d("Something vague", layer="styling", section=2)]}
    assert plan(critique, {"pages": [PAGE]}, limit=10, tried=set()) == []
    critique["version"] = "certify-critic-v2"
    assert [f["section"]["id"] for f in plan(critique, {"pages": [PAGE]}, limit=10, tried=set())] == ["s-svc"]
