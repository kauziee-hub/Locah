"""Owner usefulness and refinement regressions; no external model or network."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from platform_core.interview.site_critic import Finding
from platform_core.interview.site_pages import range_title
from platform_core.interview.site_vision_critic import Review, prefer_review, revise
from platform_core.interview.website_copy import WebsiteCopy, govern_copy
from test_site_composer import compose
from test_website_premium_site import _rich_meat


def test_range_opening_names_what_is_offered_instead_of_a_ui_instruction() -> None:
    content = {"title": "Shop by category", "categories": [{"name": "Mutton"}, {"name": "Chicken"}]}
    assert range_title(WebsiteCopy(), content, "Shop") == "Mutton & Chicken"
    assert range_title(WebsiteCopy(catalogue_title="Cuts for your kitchen"), content, "Shop") == "Cuts for your kitchen"
    assert range_title(WebsiteCopy(), {"title": "Hand-cut steaks"}, "Shop") == "Hand-cut steaks"


def test_new_editorial_title_cannot_smuggle_in_a_business_claim() -> None:
    bp = _rich_meat()
    assert not govern_copy(WebsiteCopy(catalogue_title="Award winning cuts since 1888"), bp).catalogue_title


def test_a_generated_brand_does_not_hide_its_offer_behind_a_timed_logo() -> None:
    payload = compose(_rich_meat())
    assert payload["theme_hints"]["experience"]["intro"] is False


def test_about_starts_telling_the_story_without_inventing_or_repeating_its_first_sentence() -> None:
    bp = _rich_meat()
    words = WebsiteCopy(about_body="We cut every order by hand in our shop. We deliver around Nookampalayam.")
    payload = compose(bp, copy=words)
    about = next(p for p in payload["pages"] if p["slug"] == "about")
    opening = about["sections"][0]["content"]
    story = next(s for s in about["sections"] if s["section_type_id"] == "about")["content"]
    assert opening["subheadline"] == "We cut every order by hand in our shop."
    assert story["body"] == "We deliver around Nookampalayam."
    assert opening["subheadline"] not in story["body"]
    assert opening["cta_url"] == "/shop"
    shop = next(p for p in payload["pages"] if p["slug"] == "shop")
    assert shop["sections"][0]["content"]["cta_url"] == "#shop"


def review(score: int, high: int = 0) -> Review:
    return Review(scores=dict.fromkeys(["hierarchy", "imagery", "rhythm", "distinctness", "mobile"], score),
                  raw=[{"severity": "high"}] * high)


def test_higher_score_cannot_hide_a_worse_mobile_page_or_new_severe_issue() -> None:
    assert prefer_review(review(8), review(6))
    assert not prefer_review(review(6), review(6))
    assert not prefer_review(review(8, high=1), review(6))
    candidate = review(9)
    candidate.scores["mobile"] = 3
    assert not prefer_review(candidate, review(6))
    assert not prefer_review(Review(scores={"hierarchy": 10}), review(6))


def test_range_repair_respects_content_and_never_cycles() -> None:
    section = {"section_type_id": "product_showcase", "layout_variant": "service_cards",
               "content": {"items": [{"name": "Consultation"}], "categories": []}}
    payload = {"pages": [{"slug": "services", "sections": [section]}],
               "theme_hints": {"site_archetype": "service_appointment"}}
    original = deepcopy(section["content"])
    tried: set[tuple[str, int, str]] = set()
    finding = Finding("vision:underdesigned_range", "services", "product_showcase#0", "Plain", True)
    assert revise(payload, [finding], tried)
    assert section["layout_variant"] == "compact_list"
    assert not revise(payload, [finding], tried)
    assert section["content"] == original


@pytest.mark.asyncio
async def test_visual_loop_restores_best_and_never_saves_an_unreviewed_final_change(tmp_path: Path, monkeypatch) -> None:
    from platform_testing import site_vision_loop as loop

    fixture = {"theme": {"dna": {"budget": "gentle"}}, "page": {"sections": [
        {"section_type_id": "hero", "layout_variant": "cinematic_zoom", "content": {"image_asset_id": "photo"}}]}}
    source = tmp_path / "sample.json"
    source.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(loop, "LAB", tmp_path)
    monkeypatch.setattr(loop, "shots_for", lambda *args: [])
    monkeypatch.setattr(loop, "sheet", lambda *args: None)
    calls = 0

    async def seeing(*args: Any) -> Review:
        nonlocal calls
        score = [5, 8, 6][calls]
        calls += 1
        result = review(score)
        result.findings = [Finding("vision:generic_hero", "home", "hero#0", "Try a stronger opening", True)]
        return result

    monkeypatch.setattr(loop, "critique", seeing)
    result = await loop.run(["sample"], rounds=2, dry_run=True)
    assert calls == 3  # original and both proposals reviewed
    assert [r["kept"] for r in result["sample"]] == [True, True, False]
    saved = json.loads(source.read_text(encoding="utf-8"))
    assert saved["page"]["sections"][0]["layout_variant"] == "arch"  # round 1's accepted design
    assert not result["sample"][-1]["revised"]


@pytest.mark.asyncio
async def test_failed_critic_restores_the_original_instead_of_leaving_a_proposal(tmp_path: Path, monkeypatch) -> None:
    from platform_testing import site_vision_loop as loop

    fixture = {"theme": {}, "page": {"sections": [
        {"section_type_id": "hero", "layout_variant": "cinematic_zoom", "content": {"image_asset_id": "photo"}}]}}
    source = tmp_path / "sample.json"
    source.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(loop, "LAB", tmp_path)
    monkeypatch.setattr(loop, "shots_for", lambda *args: [])
    calls = 0

    async def seeing(*args: Any) -> Review:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("Critic unavailable")
        result = review(5)
        result.findings = [Finding("vision:generic_hero", "home", "hero#0", "Generic", True)]
        return result

    monkeypatch.setattr(loop, "critique", seeing)
    with pytest.raises(TimeoutError):
        await loop.run(["sample"], rounds=2, dry_run=True)
    saved = json.loads(source.read_text(encoding="utf-8"))
    assert saved["page"] == fixture["page"]


def test_phone_review_includes_the_inner_pages(monkeypatch) -> None:
    from platform_testing import site_vision_loop as loop

    monkeypatch.setattr(loop, "shoot", lambda *args: b"synthetic")
    payload = {"pages": [{"slug": slug, "sections": [
        {"section_type_id": "hero"}, {"section_type_id": "product_showcase"}]} for slug in ("home", "services")]}
    shots = loop.shots_for("sample", payload)
    assert any(s.page == "services" and s.viewport == "phone" and s.sections == ((1, "product_showcase"),) for s in shots)
