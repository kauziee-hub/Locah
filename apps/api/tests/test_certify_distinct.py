"""Certification distinctness (docs/certification/PLAN.md §2.8): two sites of one
category must read as two brands.

Pure: small synthetic payloads, no database, no model, no network. Checked:
both loaders (a composed draft, a site-lab set) produce one signature; the
per-axis measures behave (order matters, hues compare on the colour wheel,
greys on lightness, what neither site carries is left out); and the category
verdict fails on a too-similar pair *or* a too-similar mean.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from platform_testing.certify.distinct import (
    MEAN_LIMIT,
    PAIR_LIMIT,
    WEIGHTS,
    colour,
    colour_similarity,
    compare,
    lab_keys,
    main,
    matrix_text,
    multiset_similarity,
    report,
    sequence_similarity,
    signature_from_draft,
    signature_from_lab,
    similarity,
)

ASSET = "11111111-1111-4111-8111-111111111111"


def sec(kind: str, variant: str, *, visible: bool = True, **content: Any) -> dict[str, Any]:
    return {"section_type_id": kind, "layout_variant": variant, "content": content, "is_visible": visible}


NOIR: dict[str, Any] = {
    "primary_color": "#c9a45c", "accent_color": "#e7d3a8", "background_color": "#121212",
    "palette_key": "charcoal_brass", "palette_mode": "dark", "hero_style": "editorial_split",
    "type_system": "premium_serif", "image_treatment": "framed",
    "dna": {"version": "dna-v2", "display": "bodoni", "body": "instrumentsans", "headline": "italic",
            "texture": "grain", "pattern": "rays", "divider": "slant", "button": "sharp", "navstyle": "overlay",
            "cardstyle": "flat", "shape": "rect", "concept": "noir_editorial", "photo": "macro",
            "budget": "signature"},
    "experience": {"motion": "silk", "hero": "cinematic_zoom"},
}
POP: dict[str, Any] = {
    "primary_color": "#2e7d32", "accent_color": "#ffb300", "background_color": "#fbf7ee",
    "palette_key": "butter_green", "palette_mode": "light", "hero_style": "airy_split",
    "type_system": "playful", "image_treatment": "rounded",
    "dna": {"version": "dna-v2", "display": "bricolage", "body": "outfit", "headline": "script",
            "texture": "dots", "pattern": "waves", "divider": "wave", "button": "pill", "navstyle": "floating",
            "cardstyle": "offset", "shape": "blob", "concept": "playful_pop", "photo": "clean",
            "budget": "expressive"},
    "experience": {"motion": "spring", "hero": "orbit"},
}
NOIR_HOME = [
    sec("hero", "cinematic_zoom", image_asset_id=ASSET),
    sec("statement", "giant"),
    sec("product_showcase", "chapters", items=[{"image_asset_id": ASSET}, {"name": "no picture"}]),
    sec("about", "word_reveal"),
    sec("cta_band", "giant"),
]
POP_HOME = [
    sec("hero", "airy_split"),
    sec("highlights", "counters"),
    sec("category_showcase", "image_cards"),
    sec("gallery", "masonry", image_asset_ids=[ASSET, ASSET, ASSET]),
    sec("faq", "accordion"),
    sec("contact", "full"),
]


def draft(theme: dict[str, Any], home: list[dict[str, Any]],
          inner: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    pages = [{"slug": "home", "page_type": "home", "sections": copy.deepcopy(home)}]
    pages += [{"slug": slug, "page_type": slug, "sections": copy.deepcopy(rows)}
              for slug, rows in (inner or {}).items()]
    return {"id": "v1", "theme": copy.deepcopy(theme), "pages": pages}


def write_lab(lab: Path, key: str, theme: dict[str, Any], home: list[dict[str, Any]],
              inner: dict[str, list[dict[str, Any]]] | None = None) -> None:
    def payload(slug: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"business": {"display_name": key.title()}, "page": {"slug": slug, "sections": rows},
                "navigation": [], "theme": theme}

    (lab / f"{key}.json").write_text(json.dumps(payload("home", home)), encoding="utf-8")
    for slug, rows in (inner or {}).items():
        (lab / f"{key}~{slug}.json").write_text(json.dumps(payload(slug, rows)), encoding="utf-8")


# ----------------------------------------------------------------- loaders

def test_lab_loader_reads_the_home_and_every_inner_page(tmp_path: Path) -> None:
    write_lab(tmp_path, "noir", NOIR, NOIR_HOME + [sec("marquee", "band", visible=False)],
              {"shop": [sec("hero", "page", image_asset_id=ASSET), sec("product_showcase", "rail")],
               "about": [sec("hero", "page"), sec("media_text", "sticky")]})
    write_lab(tmp_path, "noirx", POP, POP_HOME)  # a key that merely starts alike is another site
    (tmp_path / "index.json").write_text(json.dumps({"sites": []}), encoding="utf-8")

    sig = signature_from_lab(tmp_path, "noir")

    assert sig.name == "Noir"
    assert sig.page_set == ("about", "home", "shop")
    assert list(sig.section_sequence)[0] == "home"
    assert sig.section_sequence["home"] == ("hero:cinematic_zoom", "statement:giant", "product_showcase:chapters",
                                            "about:word_reveal", "cta_band:giant")  # the hidden band is not seen
    assert sig.hero == {"variant": "cinematic_zoom", "hero_style": "editorial_split", "experience": "cinematic_zoom"}
    assert sig.typography == {"display": "bodoni", "body": "instrumentsans", "headline": "italic",
                              "type_system": "premium_serif"}
    assert sig.palette.primary is not None and sig.palette.primary.bucket == "orange"
    assert sig.palette.background is not None and sig.palette.background.bucket == "neutral"
    assert sig.palette.key == "charcoal_brass" and sig.palette.mode == "dark"
    assert sig.image_treatment.pictures == {"home": 2, "shop": 1, "about": 0}
    # hero zoom, chapters, word reveal, rail, sticky media — the hidden marquee does not count
    assert sig.motion.moving == 5
    assert sig.layout_primitives.traits["shape"] == "rect"
    assert sig.concept == "noir_editorial"
    assert lab_keys(tmp_path) == ["noir", "noirx"]


def test_draft_loader_takes_the_api_envelope_and_follows_sort_order() -> None:
    raw = draft(NOIR, NOIR_HOME, {"shop": [sec("hero", "page")]})
    raw["pages"] = list(reversed(raw["pages"]))  # inner page first in the list
    raw["pages"][0]["sort_order"], raw["pages"][1]["sort_order"] = 1, 0
    raw["pages"][1]["slug"] = ""  # home known by its page_type
    for i, row in enumerate(raw["pages"][1]["sections"]):
        row["sort_order"] = 10 - i  # stored in reverse
    row = raw["pages"][1]["sections"][0]
    row["assets"] = {"image_asset_id": {"url": "https://x/1.jpg"}, "og_image_asset_id": {"url": "https://x/og.jpg"}}

    sigs = [signature_from_draft(raw, key="s"), signature_from_draft({"draft": raw}, key="s"),
            signature_from_draft({"data": {"draft": raw}}, key="s")]

    assert sigs[0] == sigs[1] == sigs[2]
    sig = sigs[0]
    assert sig.page_set == ("home", "shop")
    assert sig.section_sequence["home"][0] == "cta_band:giant"  # sort_order wins over list order
    assert sig.hero["variant"] == "cinematic_zoom"  # the home's hero, wherever it now sits
    assert sig.image_treatment.pictures["home"] == 2  # og image is not on the page; the same id counts once
    assert signature_from_draft(raw).key == "v1"


# ------------------------------------------------------------- measures

def test_sequence_similarity_is_order_aware_and_half_credits_another_layout() -> None:
    abc = ["hero:zoom", "about:split", "faq:accordion"]
    assert sequence_similarity(abc, abc) == 1.0
    assert sequence_similarity(abc, list(reversed(abc))) < 0.5  # same parts, other story
    assert sequence_similarity(["hero:zoom"], ["hero:orbit"]) == 0.5
    assert sequence_similarity([], ["hero:zoom"]) == 0.0
    assert sequence_similarity([], []) is None
    assert multiset_similarity(["a", "a", "b"], ["a", "b", "b"]) == 0.5
    assert multiset_similarity([], []) is None


def test_colours_compare_on_the_wheel_and_greys_on_lightness() -> None:
    assert colour("#ABC") == colour("aabbcc")
    assert colour("not a colour") is None and colour(None) is None
    red, orange, green = colour("#d93a2b"), colour("#e07a1f"), colour("#2e7d32")
    assert red is not None and red.bucket == "red"
    assert green is not None and green.bucket == "green"
    near, far = colour_similarity(red, orange), colour_similarity(red, green)
    assert near is not None and far is not None and near > far
    black, ink, paper = colour("#111111"), colour("#121212"), colour("#fafafa")
    same_grey, black_paper = colour_similarity(black, ink), colour_similarity(black, paper)
    assert same_grey is not None and same_grey > 0.99
    assert black_paper is not None and black_paper < 0.15
    assert colour_similarity(None, None) is None and colour_similarity(red, None) == 0.0


def test_moving_sections_follow_the_renderer_list() -> None:
    home = [sec("hero", variant) for variant in ("cinematic_zoom", "orbit", "plane", "kinetic", "depth",
                                                 "editorial_split", "page")]
    home += [sec("marquee", "outline"), sec("marquee", "band")]
    home += [sec("about", v) for v in ("word_reveal", "sticky_split", "collage", "story_split")]
    home += [sec("product_showcase", v) for v in ("rail", "stack", "chapters", "hover_list", "bento", "menu_book")]
    home += [sec("media_text", "sticky"), sec("media_text", "alternating"), sec("category_showcase", "rail")]
    assert signature_from_draft(draft(NOIR, home)).motion.moving == 5 + 2 + 3 + 4 + 1


# ----------------------------------------------------------- similarity

def test_the_same_site_twice_is_identical_and_fails_its_category() -> None:
    a = signature_from_draft(draft(NOIR, NOIR_HOME), key="a")
    b = signature_from_draft(draft(NOIR, NOIR_HOME), key="b")
    assert similarity(a, b) == 1.0

    rep = report("butchers", {"a": a, "b": b})

    assert rep["verdict"] == "fail" and rep["max"] == 1.0
    assert rep["too_similar"] == [("a", "b", ["section_sequence", "hero", "typography"])]
    assert any(f"> {PAIR_LIMIT}" in r for r in rep["reasons"])


def test_two_different_brands_are_far_apart_and_pass() -> None:
    a = signature_from_draft(draft(NOIR, NOIR_HOME), key="noir")
    b = signature_from_draft(draft(POP, POP_HOME), key="pop")
    axes = compare(a, b)

    assert similarity(a, b) < 0.2
    assert axes["concept"] == 0.0 and axes["typography"] == 0.0
    assert axes["palette"] is not None and axes["palette"] < 0.4
    rep = report("mixed", {"noir": a, "pop": b})
    assert rep["verdict"] == "pass" and rep["too_similar"] == [] and rep["reasons"] == []


def test_one_new_trait_is_not_a_new_brand() -> None:
    """A recolour of the same composition is still too similar."""
    recoloured = copy.deepcopy(NOIR)
    recoloured.update(primary_color="#d93a2b", accent_color="#f2c9c4", palette_key="charcoal_chili")
    a = signature_from_draft(draft(NOIR, NOIR_HOME), key="a")
    b = signature_from_draft(draft(recoloured, NOIR_HOME), key="b")
    assert similarity(a, b) > PAIR_LIMIT
    assert report("c", {"a": a, "b": b})["verdict"] == "fail"


def test_similarity_is_symmetric_and_bounded() -> None:
    sites = [signature_from_draft(draft(t, h, inner), key=str(i)) for i, (t, h, inner) in enumerate([
        (NOIR, NOIR_HOME, None), (POP, POP_HOME, None), (NOIR, POP_HOME, {"menu": [sec("hero", "page")]}),
        (POP, NOIR_HOME, {"shop": [sec("hero", "page")], "about": [sec("about", "collage")]}),
    ])]
    for a in sites:
        for b in sites:
            value = similarity(a, b)
            assert 0.0 <= value <= 1.0
            assert value == similarity(b, a)
    assert sum(WEIGHTS.values()) == 1.0


def test_what_neither_site_carries_is_left_out_not_counted_as_alike() -> None:
    old = {k: v for k, v in NOIR.items() if k not in {"dna", "experience"}}
    a = signature_from_draft(draft(old, NOIR_HOME), key="a")
    b = signature_from_draft(draft(old, POP_HOME), key="b")
    axes = compare(a, b)
    assert axes["concept"] is None  # neither has a concept
    assert "no design DNA" in a.notes[0]
    rep = report("old", {"a": a, "b": b})
    assert rep["pairs"][0]["skipped"] == ["concept"]
    # one side with a concept, the other without: that is a difference
    assert compare(a, signature_from_draft(draft(NOIR, NOIR_HOME)))["concept"] == 0.0


def test_a_category_fails_on_its_mean_even_without_a_pair_over_the_limit() -> None:
    """Three sites, each pair under the pair limit, still too alike as a set."""
    a, b, c = copy.deepcopy(NOIR), copy.deepcopy(NOIR), copy.deepcopy(NOIR)
    b["dna"].update(concept="quiet_luxury", display="cormorant", headline="plain", budget="restrained",
                    cardstyle="bordered", button="underline")
    b.update(primary_color="#d93a2b", palette_key="b")
    c["dna"].update(concept="warm_craft", display="newsreader", body="manrope", photo="warm", texture="paper")
    c.update(primary_color="#7a4b2a", palette_key="c", type_system="calm_serif")
    c["experience"]["hero"] = "depth"
    homes = [NOIR_HOME,
             [sec("hero", "editorial_split"), *NOIR_HOME[1:3], sec("faq", "split"), sec("cta_band", "giant")],
             [sec("hero", "depth"), sec("highlights", "counters"), *NOIR_HOME[2:]]]
    sigs = {k: signature_from_draft(draft(t, h), key=k) for k, t, h in zip("abc", (a, b, c), homes, strict=True)}

    rep = report("mean", sigs)

    assert rep["max"] <= PAIR_LIMIT, rep["pairs"]
    assert rep["mean"] > MEAN_LIMIT, rep["pairs"]
    assert rep["verdict"] == "fail" and rep["too_similar"] == []
    assert rep["reasons"] == [f"category mean {rep['mean']} > {MEAN_LIMIT}"]


def test_a_category_of_one_cannot_pass() -> None:
    rep = report("solo", {"a": signature_from_draft(draft(NOIR, NOIR_HOME), key="a")})
    assert rep["verdict"] == "fail" and rep["pairs"] == []
    assert "at least two" in rep["reasons"][0]


def test_the_matrix_and_the_cli_read_a_lab(tmp_path: Path, capsys: Any) -> None:
    write_lab(tmp_path, "noir", NOIR, NOIR_HOME)
    write_lab(tmp_path, "pop", POP, POP_HOME)
    out = tmp_path / "rep.json"

    code = main(["--lab", str(tmp_path), "--category", "demo", "--json", str(out)])

    assert code == 0
    printed = capsys.readouterr().out
    assert printed.startswith("demo: max") and "PASS" in printed
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["sites"] == ["noir", "pop"] and len(rep["pairs"]) == 1
    assert matrix_text(rep).splitlines()[2].startswith("noir")


def test_a_malformed_payload_still_yields_a_signature() -> None:
    broken = {"theme": {"dna": "oops", "experience": None, "primary_color": "teal", "creative_direction": []},
              "pages": [{"slug": "/", "sections": [{"section_type_id": "hero", "content": None, "assets": []},
                                                    "not a section"]}, "not a page"]}
    sig = signature_from_draft(broken, key="x")
    assert sig.section_sequence == {"home": ("hero:-",)}
    assert sig.palette.primary is None and sig.image_treatment.pictures == {"home": 0}
    assert 0.0 <= similarity(sig, signature_from_draft(draft(NOIR, NOIR_HOME))) <= 1.0
