"""The certification critic and gate (python/testing/platform_testing/certify/).

No model is called: a fake vision provider answers from a script, and the
screenshots are solid-colour PNGs drawn here. What is proven: the critic's
answers parse (strings, out-of-range values, unknown layers), render.json's
measurements become deterministic defects, a page near the pass mark is
judged twice and keeps the lower score, look-alike sites become major defects,
missing reference images are handled, every image sent stays within the tile
limit, and the gate's pass / repair / fail_closed boundaries and owner
requests hold exactly at the founder's thresholds.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from platform_testing.certify import critic, gate, references

# ----------------------------------------------------------------- fixtures


def _png(path: Path, size: tuple[int, int], colour: tuple[int, int, int] = (200, 180, 160)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path, format="PNG")
    return path.name


def _vp(png: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"png": f"shots/{png}", "height": 1000, "overflow_x": False,
                           "broken_images": 0, "imgs_without_alt": 0, "lazy_offscreen_missing": 0,
                           "lcp_ms": 1500, "cls": 0.01, "console_errors": [],
                           "axe": {"violations": []}, "links": []}
    return row | over


def _site(tmp_path: Path, *, menu_faults: bool = True) -> Path:
    """A rendered two-page site: home is clean, menu carries every fault."""
    site = tmp_path / "rest-a"
    shots = site / "shots"
    home_l = _png(shots / "home__laptop.png", (1440, 3000))
    home_m = _png(shots / "home__mobile.png", (390, 5000))
    menu_xl = _png(shots / "menu__xl.png", (1920, 9000))
    menu_l = _png(shots / "menu__laptop.png", (1440, 6000))
    menu_t = _png(shots / "menu__tablet.png", (834, 7000))
    menu_m = _png(shots / "menu__mobile.png", (390, 12000))
    faults: dict[str, Any] = {}
    if menu_faults:
        faults = {
            "laptop": {"lcp_ms": 5200, "console_errors": ["TypeError: x is undefined"]},
            "tablet": {"overflow_x": True, "cls": 0.25},
            "mobile": {"overflow_x": 12, "broken_images": ["/a.jpg"], "imgs_without_alt": 3,
                       "lcp_ms": 9000,
                       "axe": {"violations": [{"id": "color-contrast", "impact": "serious", "nodes": 4},
                                              {"id": "region", "impact": "moderate", "nodes": 9}]}},
        }
    render = {"pages": [
        {"slug": "home", "url": "http://x/", "status": 200, "title": "Rest A",
         "meta": {"description": "Rest A in town", "og_image": "", "canonical": ""},
         "viewports": {"laptop": _vp(home_l), "mobile": _vp(home_m)}},
        {"slug": "menu", "url": "http://x/menu", "status": 200, "title": "Menu" if not menu_faults else "",
         "meta": {"description": "" if menu_faults else "Our menu"},
         "viewports": {"xl": _vp(menu_xl), "laptop": _vp(menu_l, **faults.get("laptop", {})),
                       "tablet": _vp(menu_t, **faults.get("tablet", {})),
                       "mobile": _vp(menu_m, **faults.get("mobile", {}))}},
    ]}
    (site / "render.json").write_text(json.dumps(render), encoding="utf-8")
    return site


MANIFEST: dict[str, Any] = {
    "site_key": "rest-a", "business_name": "Rest A",
    "payload": {"pages": [
        {"slug": "home", "sections": [{"section_type_id": "hero", "layout_variant": "cinematic_zoom"},
                                      {"section_type_id": "statement", "layout_variant": "giant"}]},
        {"slug": "menu", "sections": [{"section_type_id": "product_showcase", "layout_variant": "list"}]},
    ], "theme_hints": {"dna": {"concept": "warm editorial", "budget": "gentle"}}},
}


def _scores(value: Any, **over: Any) -> dict[str, Any]:
    return {d: value for d in critic.PAGE_DIMENSIONS} | over


class FakeVision:
    """Answers each page from a script (one answer per call, the last repeats);
    records every call and decodes every image it was sent."""

    model_name = "fake-vision"

    def __init__(self, pages: dict[str, list[Any]], cross: list[Any]) -> None:
        self.pages, self.cross = pages, cross
        self.calls: list[dict[str, Any]] = []

    async def generate_structured_with_images(
        self, prompt: str, images: list[Any], schema: dict[str, Any], model_config: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ctx = json.loads(prompt)
        sizes = [Image.open(io.BytesIO(i.data)).size for i in images]
        self.calls.append({"ctx": ctx, "sizes": sizes, "schema": schema, "config": model_config,
                           "timeout": timeout_seconds})
        if "page" in ctx:
            script = self.pages[ctx["page"]]
            n = sum(1 for c in self.calls if c["ctx"].get("page") == ctx["page"]) - 1
        else:
            script = self.cross
            n = sum(1 for c in self.calls if "page" not in c["ctx"]) - 1
        answer = script[min(n, len(script) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)


def _page_calls(fake: FakeVision, slug: str) -> list[dict[str, Any]]:
    return [c for c in fake.calls if c["ctx"].get("page") == slug]


# ----------------------------------------------------------------- references


def test_references_are_read_from_the_brief() -> None:
    assert sorted(references.REFERENCES) == [f"{i:02d}" for i in range(1, 16)]
    title, takeaway = references.REFERENCES["07"]
    assert title == "Restaurant / Dark Premium Menu"
    assert "price-list" in takeaway
    assert any(m.startswith("Menu/shop/service pages are currently too blunt") for m in references.MUST_IMPROVE)
    assert "excessive cards" in references.CRITIQUE_FOR
    assert references.EXPECTED_STANDARD["must_not_think"] == "This is a polished template."


@pytest.mark.parametrize(("category", "refs", "family"), [
    ("restaurant", ("05", "06", "07"), "restaurant"),
    ("Restaurant — reservations", ("05", "06", "07"), "restaurant"),
    ("gym", ("08",), "gym"),
    ("beauty_studio", ("11", "12"), "salon"),
    ("medical", ("13", "14"), "clinic"),
    ("coaching", ("09",), "consultant"),
    ("Architecture / interiors", ("01", "02", "03", "04"), "architecture"),
    ("hotel", ("15",), "hotel"),
    ("NGO", ("10",), "ngo"),
    ("Meat / butcher shop", ("04", "05", "07"), "meat"),
    ("bakery", ("04", "05", "07"), "bakery"),
    ("Retail store", ("04", "05", "07"), "retail"),
    ("Mango Tree Cafe", ("05", "06", "07"), "restaurant"),  # "mango" is not an NGO
    ("submarine repair", references.DEFAULT_REFERENCES, "other"),
])
def test_category_references(category: str, refs: tuple[str, ...], family: str) -> None:
    assert references.refs_for(category) == refs
    assert references.category_family(category) == family


def test_reference_images_are_optional(tmp_path: Path) -> None:
    assert references.images(["05", "06"], tmp_path) == []
    _png(tmp_path / "ref_06.png", (1600, 1000))
    assert references.images(["05", "06", "07"], tmp_path) == [tmp_path / "ref_06.png"]


# ----------------------------------------------------------------- tiles


def _sizes(tiles: list[bytes]) -> list[tuple[int, int]]:
    return [Image.open(io.BytesIO(t)).size for t in tiles]


def test_tiles_stay_within_limits() -> None:
    tiles, cols = critic.desktop_tiles(Image.new("RGB", (1920, 5000)))
    assert cols == 1 and _sizes(tiles) == [(1280, 1600), (1280, 1600), (1280, 133)]
    tiles, cols = critic.desktop_tiles(Image.new("RGB", (1920, 12000)))  # 8000 at 1280: two columns
    assert cols == 2 and len(tiles) == 2
    assert all(h <= critic.TILE_MAX_HEIGHT for _, h in _sizes(tiles))
    phone = _sizes(critic.mobile_tiles(Image.new("RGB", (390, 12000))))
    assert len(phone) == 2 and all(h <= 1600 for _, h in phone)
    assert phone[0][0] == 6 * 360 + 5 * critic.MOBILE_GUTTER  # six columns side by side
    huge = _sizes(critic.mobile_tiles(Image.new("RGB", (390, 40000))))
    assert len(huge) <= critic.MAX_TILES and all(h <= 1600 for _, h in huge)


# ----------------------------------------------------------------- deterministic defects


def test_render_measurements_become_defects(tmp_path: Path) -> None:
    render = json.loads((_site(tmp_path) / "render.json").read_text(encoding="utf-8"))
    render["pages"].append({"slug": "about", "status": 404, "viewports": {}})
    found = {d["kind"] + (":" + d["id"].rsplit(":", 1)[-1] if d["kind"] == "axe" else ""): d
             for d in critic.render_defects(render, 1)}
    by = {k: (d["page"], d["severity"], d["layer"]) for k, d in found.items()}
    assert by["overflow_x"] == ("menu", "critical", "responsive")
    assert found["overflow_x"]["viewport"] == "mobile" and found["overflow_x"]["viewports"] == ["mobile", "tablet"]
    assert by["broken_images"] == ("menu", "critical", "photo")
    assert by["axe:color-contrast"] == ("menu", "major", "styling")
    assert "axe:region" not in by  # moderate impact is not a defect
    assert by["imgs_without_alt"] == ("menu", "major", "copy")
    assert by["meta_description"] == ("menu", "major", "architecture")
    assert by["meta_title"] == ("menu", "major", "architecture")
    assert by["lcp"] == ("menu", "major", "architecture")
    assert found["lcp"]["viewports"] == ["laptop"]  # the 9s mobile LCP is not the laptop rule
    assert by["cls"] == ("menu", "major", "responsive")
    assert by["console_errors"] == ("menu", "minor", "architecture")
    assert by["status"] == ("about", "critical", "architecture")
    assert not [d for d in found.values() if d["page"] == "home"]
    assert all(d["source"] == "render" for d in found.values())


# ----------------------------------------------------------------- the critique


async def test_critique_parses_scores_and_merges_pages(tmp_path: Path) -> None:
    site = _site(tmp_path)
    fake = FakeVision(
        pages={
            "home": [{"scores": _scores(6), "verdict": "A template.", "defects": [
                {"section": 0, "viewport": "desktop", "severity": "major", "layer": "photo",
                 "text": "Hero photography feels like stock and could be any restaurant."},
                {"section": 1, "viewport": "phone", "severity": "HIGH", "layer": "layout",
                 "text": "Mobile heading collides with the navigation."},
                {"section": 1, "viewport": "all", "severity": "minor", "layer": "copy", "text": "  "},
            ]}],
            "menu": [{"scores": _scores("5", hero=14, mobile="n/a"), "verdict": "A data dump.", "defects": [
                {"section": 0, "viewport": "all", "severity": "major", "layer": "input",
                 "text": "Menu page is a long data dump: names and prices, no descriptions."}]}],
        },
        cross=[{"scores": {"consistency": 4, "originality": 3}, "verdict": "Generic.", "defects": [
            {"page": "menu", "severity": "major", "layer": "composition",
             "text": "Menu and home repeat the same banner."},
            {"page": "nowhere", "severity": "minor", "layer": "styling", "text": "Footer feels unfinished."}]}],
    )
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=2,
                                     references_dir=tmp_path / "no-references")

    assert len(fake.calls) == 3  # one per page and one across pages; no page was near the line
    assert out["page_scores"]["menu"]["hero"] == 10.0  # clamped
    assert "mobile" not in out["page_scores"]["menu"]  # "n/a" is no score
    assert out["scores"]["hero"] == 8.0  # mean of 6 and 10
    assert out["scores"]["mobile"] == 6.0  # only home scored it
    assert out["scores"]["typography"] == 5.5
    assert out["scores"]["consistency"] == 4.0 and out["scores"]["originality"] == 3.0
    assert list(out["scores"]) == list(gate.DIMENSIONS)
    assert out["complete"] is False and any("menu: no score for mobile" in e for e in out["errors"])

    vision = [d for d in out["defects"] if d["source"] == "vision"]
    texts = {d["text"]: d for d in vision}
    hero = texts["Hero photography feels like stock and could be any restaurant."]
    assert (hero["page"], hero["section"], hero["viewport"], hero["severity"], hero["layer"]) == (
        "home", 0, "laptop", "major", "photo")
    clash = texts["Mobile heading collides with the navigation."]
    assert (clash["viewport"], clash["severity"], clash["layer"]) == ("mobile", "major", "composition")
    assert texts["Menu page is a long data dump: names and prices, no descriptions."]["layer"] == "input"
    assert texts["Footer feels unfinished."]["page"] == "*"  # an unknown page is site-wide
    assert len(vision) == 5  # the blank one is dropped
    assert {d["kind"] for d in out["defects"] if d["source"] == "render"} >= {"overflow_x", "broken_images"}
    sev = [gate.SEVERITIES.index(d["severity"]) for d in out["defects"]]
    assert sev == sorted(sev)  # most severe first

    home_call, menu_call = _page_calls(fake, "home")[0], _page_calls(fake, "menu")[0]
    assert home_call["config"]["temperature"] == 0.1
    assert home_call["config"]["purpose"] == critic.PURPOSE
    assert home_call["ctx"]["sections"] == [{"index": 0, "type": "hero", "layout": "cinematic_zoom"},
                                            {"index": 1, "type": "statement", "layout": "giant"}]
    assert home_call["ctx"]["reference_class"][0]["id"] == "05"
    assert home_call["ctx"]["art_direction"] == {"concept": "warm editorial", "motion_budget": "gentle"}
    assert any("too blunt" in m for m in home_call["ctx"]["must_improve"])
    assert "laptop" in home_call["ctx"]["screenshots"][0]["shows"]
    assert "xl" in menu_call["ctx"]["screenshots"][0]["shows"]  # xl is preferred over laptop
    for call in fake.calls:
        assert all(h <= critic.TILE_MAX_HEIGHT for _, h in call["sizes"])
    cross = next(c for c in fake.calls if "page" not in c["ctx"])
    assert [p["page"] for p in cross["ctx"]["pages"]] == ["home", "menu"] and len(cross["sizes"]) == 2
    assert out["references"] == {"ids": ["05", "06", "07"], "images": 0}

    written = json.loads((site / "critique.json").read_text(encoding="utf-8"))
    assert written["scores"] == out["scores"] and (site / "critique.r2.json").is_file()


async def test_a_page_near_the_line_is_judged_twice_and_keeps_the_lower_score(tmp_path: Path) -> None:
    site = _site(tmp_path, menu_faults=False)
    first = {"scores": _scores(8), "verdict": "Close.", "defects": [
        {"section": 0, "viewport": "desktop", "severity": "major", "layer": "composition",
         "text": "Three consecutive sections use identical card grids."}]}
    second = {"scores": _scores(9, hero=7), "verdict": "Closer.", "defects": [
        {"section": 2, "viewport": "mobile", "severity": "critical", "layer": "responsive",
         "text": "Mobile booking button is off screen."},
        {"section": 0, "viewport": "desktop", "severity": "minor", "layer": "styling",
         "text": "Card corners differ."}]}
    fake = FakeVision(pages={"home": [first, second], "menu": [{"scores": _scores(5), "defects": [],
                                                                "verdict": "Weak."}]},
                      cross=[{"scores": {"consistency": 9, "originality": 9.5}, "defects": [],
                              "verdict": "Distinct."}])
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=1, write=False)

    assert len(_page_calls(fake, "home")) == 2  # 8.0 is within 1.0 of 8.5
    assert len(_page_calls(fake, "menu")) == 1  # 5.0 is not
    assert len([c for c in fake.calls if "page" not in c["ctx"]]) == 1  # 9 and 9.5 are far from 7
    assert out["double_judged"] == ["home"]
    assert len(out["raw"]["pages"]["home"]) == 2 and out["raw"]["pages"]["home"][1]["verdict"] == "Closer."
    home = out["page_scores"]["home"]
    assert home["hero"] == 7.0 and home["typography"] == 8.0  # the lower of each
    texts = [d["text"] for d in out["defects"] if d["page"] == "home"]
    assert "Three consecutive sections use identical card grids." in texts  # the harsher answer's defects
    assert "Mobile booking button is off screen." in texts  # plus a critical only the other saw
    assert "Card corners differ." not in texts
    assert out["complete"] is True and not out["errors"]
    assert not (site / "critique.json").exists()


async def test_cross_page_scores_near_the_floor_are_judged_twice(tmp_path: Path) -> None:
    site = _site(tmp_path, menu_faults=False)
    fake = FakeVision(pages={"home": [{"scores": _scores(4), "defects": []}],
                             "menu": [{"scores": _scores(4), "defects": []}]},
                      cross=[{"scores": {"consistency": 7.5, "originality": 9}, "defects": []},
                             {"scores": {"consistency": 8, "originality": 6.5}, "defects": []}])
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=1, write=False)
    assert len(out["raw"]["cross"]) == 2 and "*" in out["double_judged"]
    assert out["scores"]["consistency"] == 7.5 and out["scores"]["originality"] == 6.5


async def test_reference_images_join_the_call_when_present(tmp_path: Path) -> None:
    site = _site(tmp_path, menu_faults=False)
    refs = tmp_path / "refs"
    _png(refs / "ref_06.png", (2400, 1500))
    answer = {"scores": _scores(4), "defects": []}
    fake = FakeVision(pages={"home": [answer], "menu": [answer]},
                      cross=[{"scores": {"consistency": 3, "originality": 3}, "defects": []}])
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=1,
                                     references_dir=refs, write=False)
    call = _page_calls(fake, "home")[0]
    assert out["references"] == {"ids": ["05", "06", "07"], "images": 1}
    assert call["sizes"][-1] == (1280, 800)  # the reference, fitted, sent last
    assert call["ctx"]["screenshots"][-1]["shows"] == "reference 1"
    rows = {r["id"]: r for r in call["ctx"]["reference_class"]}
    assert rows["06"]["image"] == "reference 1" and "image" not in rows["05"]


async def test_look_alike_sites_become_major_defects(tmp_path: Path) -> None:
    site = _site(tmp_path, menu_faults=False)
    answer = {"scores": _scores(4), "defects": []}
    fake = FakeVision(pages={"home": [answer], "menu": [answer]},
                      cross=[{"scores": {"consistency": 3, "originality": 3}, "defects": []}])
    distinct_report = {"limits": {"pair": 0.6}, "too_similar": [["rest-a", "rest-b", ["section_sequence"]]],
                       "pairs": [{"a": "rest-a", "b": "rest-b", "similarity": 0.72},
                                 {"a": "rest-a", "b": "rest-c", "similarity": 0.4},
                                 {"a": "rest-c", "b": "rest-d", "similarity": 0.9}]}
    similar = critic.similar_from_distinct(distinct_report, "rest-a")
    assert similar == [{"site_key": "rest-b", "similarity": 0.72, "shared": ["section_sequence"]}]
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=1,
                                     similar_to=similar + ["rest-e"], write=False)
    alike = [d for d in out["defects"] if d["source"] == "distinct"]
    assert [d["text"] for d in alike] == [
        "same visual structure as rest-b (similarity 0.72; shared: section_sequence)",
        "same visual structure as rest-e"]
    assert all(d["severity"] == "major" and d["page"] == "*" for d in alike)


async def test_a_failed_vision_call_makes_the_critique_incomplete(tmp_path: Path) -> None:
    site = _site(tmp_path, menu_faults=False)
    fake = FakeVision(pages={"home": [{"scores": _scores(10), "defects": []}],
                             "menu": [RuntimeError("deepseek unavailable (503)")]},
                      cross=[{"scores": {"consistency": 10, "originality": 10}, "defects": []}])
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=1, write=False)
    assert out["complete"] is False
    assert any(e.startswith("menu: vision call failed (RuntimeError") for e in out["errors"])
    verdict = gate.decide(out, rounds_used=1, max_rounds=3)
    assert verdict["status"] == "repair"  # 10s everywhere, but an unjudged page never passes
    assert any("incomplete" in r for r in verdict["reasons"])


async def test_a_missing_phone_shot_is_judged_but_never_complete(tmp_path: Path) -> None:
    site = _site(tmp_path, menu_faults=False)
    (site / "shots" / "menu__mobile.png").unlink()
    fake = FakeVision(pages={"home": [{"scores": _scores(10), "defects": []}],
                             "menu": [{"scores": _scores(10), "defects": []}]},
                      cross=[{"scores": {"consistency": 10, "originality": 10}, "defects": []}])
    out = await critic.critique_site(fake, site, MANIFEST, category="restaurant", round_no=1, write=False)
    menu = _page_calls(fake, "menu")[0]
    assert menu["ctx"]["missing"] == ["mobile"] and all("phone" not in s["shows"]
                                                        for s in menu["ctx"]["screenshots"])
    assert out["errors"] == ["menu: no readable mobile screenshot"] and out["complete"] is False


# ----------------------------------------------------------------- the gate


def _critique(score: float = 9.0, defects: list[dict[str, Any]] | None = None, *,
              category: str = "clinic", **over: float) -> dict[str, Any]:
    return {"scores": {d: score for d in gate.DIMENSIONS} | over, "defects": defects or [],
            "category": category, "business": "Sunrise Clinic", "complete": True}


def _defect(severity: str, layer: str = "composition", text: str = "x", source: str = "vision",
            n: int = 0) -> dict[str, Any]:
    return {"id": f"d{n}:{severity}:{layer}", "page": "home", "section": 0, "viewport": "all",
            "severity": severity, "layer": layer, "text": text, "source": source}


def test_weighted_score_uses_the_founder_weights() -> None:
    total = sum(gate.WEIGHTS.values())
    assert total == pytest.approx(15 + 0.5 + 6 * 0.2)
    assert gate.weighted_score({d: 10 for d in gate.DIMENSIONS} | {"hero": 0}) == pytest.approx(
        10 * (total - 1.5) / total)
    assert gate.weighted_score({}) == 0.0


def test_gate_passes_at_exactly_the_thresholds() -> None:
    two_major = [_defect("major", n=1), _defect("major", n=2)] + [_defect("minor", n=i) for i in range(3, 9)]
    verdict = gate.decide(_critique(8.5, two_major), rounds_used=1, max_rounds=3)
    assert verdict["status"] == "pass" and verdict["score"] == 8.5 and verdict["reasons"] == []
    # the plain dimensions at the floor of 7, the weighted ones carrying the mean over 8.5
    floor = {d: 7.0 for d in gate.DIMENSIONS if gate.WEIGHTS[d] == 1.0}
    lifted = {d: 10.0 for d in gate.DIMENSIONS if gate.WEIGHTS[d] > 1.0}
    scores = floor | lifted
    assert gate.weighted_score(scores) == pytest.approx(143 / 16.7)
    assert gate.decide({"scores": scores, "defects": [], "complete": True},
                       rounds_used=0, max_rounds=3)["status"] == "pass"


@pytest.mark.parametrize(("critique", "reason"), [
    (_critique(8.49), "weighted score 8.49 is below 8.5"),
    (_critique(10.0, typography=6.9), "typography 6.9 is below 7"),
    (_critique(9.0, [_defect("critical")]), "1 critical defect(s)"),
    (_critique(9.0, [_defect("major", n=i) for i in range(3)]), "3 major defects (at most 2)"),
    ({"scores": {d: 10 for d in gate.DIMENSIONS if d != "motion"}, "defects": [], "complete": True},
     "motion was not scored"),
])
def test_gate_repairs_below_any_threshold(critique: dict[str, Any], reason: str) -> None:
    verdict = gate.decide(critique, rounds_used=1, max_rounds=3)
    assert verdict["status"] == "repair"
    assert any(r.startswith(reason) for r in verdict["reasons"]), verdict["reasons"]
    assert verdict["owner_requests"] == []


def test_gate_fails_closed_with_owner_requests_when_no_rounds_remain() -> None:
    defects = [
        _defect("major", "photo", "The gallery is stock photography of a generic hospital.", n=1),
        _defect("major", "input", "Service descriptions are one line each, too thin to sell.", n=2),
        _defect("minor", "input", "The about page has no story of the founders or the team.", n=3),
        _defect("critical", "photo", "3 broken image(s) on the home page", source="render", n=4),
        _defect("major", "composition", "Three consecutive sections use identical card grids.", n=5),
    ]
    verdict = gate.decide(_critique(7.5, defects), rounds_used=3, max_rounds=3)
    assert verdict["status"] == "fail_closed" and verdict["blocked_on"] == "owner"
    requests = verdict["owner_requests"]
    assert requests[0].startswith("We need 2–3 photographs of your actual clinic and team to finish "
                                  "this site to our quality standard.")
    assert requests[1].startswith("The service descriptions are too limited to build the experience "
                                  "properly. Please answer these three questions: 1. ")
    assert "2. " in requests[1] and "3. " in requests[1]
    assert requests[2].startswith("Your story is what makes Sunrise Clinic different")
    assert len(requests) == 3
    photo = verdict["owner_request_details"][0]
    assert photo["defect_ids"] == ["d1:major:photo"]  # the broken image is Locah's, never the owner's


def test_owner_requests_are_category_aware() -> None:
    defects = [_defect("major", "input", "Dish descriptions are missing on the menu.", n=1),
               _defect("major", "photo", "Hero photo is stock.", n=2)]
    verdict = gate.decide(_critique(6.0, defects, category="Restaurant — delivery"),
                          rounds_used=2, max_rounds=2)
    assert "your actual restaurant" in verdict["owner_requests"][0]
    assert verdict["owner_requests"][1].startswith("The menu descriptions are too limited")
    assert "Which 3–5 dishes" in verdict["owner_requests"][1]


def test_low_imagery_alone_asks_for_photos() -> None:
    verdict = gate.decide(_critique(9.0, category="gym", imagery=5.0), rounds_used=3, max_rounds=3)
    assert verdict["status"] == "fail_closed"
    assert verdict["owner_requests"] == [
        "We need 2–3 photographs of your actual gym — the training floor, the equipment and your "
        "coaches to finish this site to our quality standard. Phone photos in good daylight are perfect."]


def test_design_only_failures_are_blocked_on_the_platform() -> None:
    defects = [_defect("major", "composition", "Identical card grids.", n=i) for i in range(4)]
    defects.append(_defect("major", "composition", "same visual structure as rest-b", source="distinct", n=9))
    verdict = gate.decide(_critique(9.0, defects), rounds_used=3, max_rounds=3)
    assert verdict["status"] == "fail_closed"
    assert verdict["owner_requests"] == [] and verdict["blocked_on"] == "platform"
    assert any("generator, composer or renderer" in r for r in verdict["reasons"])


def test_gate_thresholds_are_the_founders() -> None:
    assert (gate.PASS_SCORE, gate.DIMENSION_FLOOR, gate.MAX_CRITICAL, gate.MAX_MAJOR) == (8.5, 7.0, 0, 2)
    assert {d: w for d, w in gate.WEIGHTS.items() if w != 1.0} == {
        "hero": 1.5, "typography": 1.2, "composition": 1.2, "imagery": 1.2, "art_direction": 1.2,
        "catalog_presentation": 1.2, "mobile": 1.2}
