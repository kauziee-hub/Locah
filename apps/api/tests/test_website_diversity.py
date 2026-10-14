"""Different businesses get different websites — for reasons the business implies.

The v3 fixtures let 21 of 23 businesses share one skeleton and, with no
pictures, one family of text-first heroes. These composes run as a deployment
with an image provider does (pictures expected before the design is chosen;
drawable slots filled), deterministic and with zero AI calls. Nothing here
asserts randomness: every expectation follows from what the owner said.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import pytest

from platform_testing.website_fixtures import SiteFixture, build_all, distinctness


@pytest.fixture(scope="module")
def sites() -> dict[str, SiteFixture]:
    return {f.key: f for f in asyncio.run(build_all(images=True))}


def _sections(f: SiteFixture) -> list[dict[str, Any]]:
    return list(f.payload["pages"][0]["sections"])


def _of(f: SiteFixture, kind: str) -> dict[str, Any] | None:
    return next((s for s in _sections(f) if s["section_type_id"] == kind), None)


def _hero(f: SiteFixture) -> dict[str, Any]:
    hero = _of(f, "hero")
    assert hero
    return hero


def test_the_golden_business_types_get_their_own_hero(sites: dict[str, SiteFixture]) -> None:
    # Each hero is a scene suited to how the business presents itself: a home
    # kitchen's dishes turn or open up, a gym is loud type, a developer's
    # homes float in layers, a precise B2B plant stays quiet.
    expected = {"home-food": {"orbit", "plane", "cinematic_zoom", "depth"},
                "gym": {"kinetic", "cinematic_zoom", "depth"},
                "real-estate": {"depth", "cinematic_zoom", "plane"},
                "meat-shop": {"kinetic", "plane", "cinematic_zoom"},
                "industrial": {"depth", "cinematic_zoom"}}
    for key, heroes in expected.items():
        assert _hero(sites[key])["layout_variant"] in heroes, key
    assert len({_hero(sites[k])["layout_variant"] for k in expected}) >= 3


def test_motion_follows_how_the_business_presents_itself(sites: dict[str, SiteFixture]) -> None:
    motion = {k: f.payload["theme_hints"]["experience"]["motion"] for k, f in sites.items()}
    assert motion["gym"] == "snap"
    for calm in ("dental", "hospital", "law-firm"):
        assert motion[calm] == "calm", calm
    assert motion["play-school"] in {"float", "snap"}
    # Calm sites never spin or tilt their pictures.
    for key, f in sites.items():
        if motion[key] == "calm":
            assert _hero(f)["layout_variant"] not in {"orbit", "plane", "kinetic"}, key


def test_no_hero_scene_takes_over(sites: dict[str, SiteFixture]) -> None:
    heroes = Counter(_hero(f)["layout_variant"] for f in sites.values())
    assert len(heroes) >= 4, heroes
    assert heroes.most_common(1)[0][1] <= len(sites) // 2, heroes


def test_the_five_look_like_five_businesses(sites: dict[str, SiteFixture]) -> None:
    five = [sites[k] for k in ("home-food", "gym", "real-estate", "meat-shop", "industrial")]
    assert len({f.signature["type_system"] for f in five}) == 5
    assert len({f.signature["family"] for f in five}) == 5
    assert len({f.payload["theme_hints"]["palette_mode"] for f in five}) == 2  # dark and light worlds


def test_pictures_fill_the_design_where_they_are_allowed(sites: dict[str, SiteFixture]) -> None:
    for key in ("home-food", "gym", "meat-shop", "real-estate", "industrial", "restaurant", "bakery"):
        assert _hero(sites[key])["content"].get("image_asset_id"), key
    # A kitchen's menu pictures featured dishes; the rest stays a list.
    menu = _of(sites["home-food"], "product_showcase") or _of(sites["home-food"], "category_showcase")
    assert menu and any(i.get("image_asset_id") for i in menu["content"].get("items") or [])


def test_factual_slots_are_never_drawn(sites: dict[str, SiteFixture]) -> None:
    # A developer's projects and a photographer's work are the evidence itself.
    for key in ("real-estate", "photographer", "interiors"):
        for kind in ("product_showcase", "category_showcase"):
            section = _of(sites[key], kind)
            rows = (section or {}).get("content", {})
            for row in [*(rows.get("items") or []), *(rows.get("categories") or [])]:
                assert not row.get("image_asset_id"), (key, row.get("name"))


def test_catalogue_is_presented_as_the_trade_browses(sites: dict[str, SiteFixture]) -> None:
    # Projects one at a time, large; cuts as a price list; plans as cards that stack.
    assert (_of(sites["real-estate"], "product_showcase") or {}).get("layout_variant") in {"spotlight", "stack"}
    assert (_of(sites["meat-shop"], "product_showcase") or {}).get("layout_variant") in {
        "menu_book", "category_boards"}
    assert (_of(sites["gym"], "product_showcase") or {}).get("layout_variant") == "stack"


def test_calls_to_action_say_what_this_visitor_does(sites: dict[str, SiteFixture]) -> None:
    labels = {k: str(_hero(f)["content"].get("cta_label", "")) for k, f in sites.items()}
    assert labels["real-estate"] in {"View projects", "Book a site visit"}
    assert "menu" in labels["home-food"].lower()
    assert not labels["industrial"].lower().startswith(("book", "order", "shop"))


def test_b2b_shows_who_it_serves_and_never_a_shop(sites: dict[str, SiteFixture]) -> None:
    industrial = sites["industrial"]
    kinds = [s["section_type_id"] for s in _sections(industrial)]
    assert "feature_grid" in kinds
    assert "cart" not in str(industrial.payload).lower()


def test_no_single_skeleton_dominates(sites: dict[str, SiteFixture]) -> None:
    skeletons = Counter(tuple(f"{s['section_type_id']}:{s.get('layout_variant')}" for s in _sections(f))
                        for f in sites.values())
    most = skeletons.most_common(1)[0][1]
    assert most <= max(3, len(sites) // 5), skeletons.most_common(3)


def test_headlines_are_designed_not_the_business_name(sites: dict[str, SiteFixture]) -> None:
    named = [k for k, f in sites.items() if _hero(f)["content"]["headline"] == f.name]
    assert len(named) <= 2, named


def test_distinct_evidence_gives_distinct_signatures_with_pictures_too(sites: dict[str, SiteFixture]) -> None:
    report = distinctness(list(sites.values()))
    assert report.ok, (report.clusters, report.identical)
