"""The premium site: design DNA, motion budget, inner pages, the critic loop.

Pure: no database, no model, no network. What is checked is the design
decision and the truth rules — two businesses of one trade do not share a
look; a quiet brand does not get a show; every page exists because it has
something true on it; the critic only moves, re-lays or removes, never writes.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from platform_core.interview.design_dna import BY_KEY, CONCEPTS, SERIF, choose_dna, concept_weights
from platform_core.interview.draft_merge import base_fingerprints, merge
from platform_core.interview.models import BusinessBlueprint, CatalogueGroup, CatalogueItem, TargetState
from platform_core.interview.motion_director import direct as direct_motion
from platform_core.interview.site_critic import critique, review
from platform_core.interview.site_pages import faqs_for, pillars_for, statement_for
from platform_core.interview.website_copy import WebsiteCopy
from test_site_composer import compose, gym, meat, real_estate

ASSET = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
WEB = Path(__file__).resolve().parents[2] / "web" / "src"

BUTCHER = {"offering": "weighed_product", "personality": "warm", "energy": "medium", "trust": "normal",
           "positioning": "heritage", "service_mode": "food", "journey": "order"}
CLINIC = {"offering": "service", "personality": "calm", "energy": "low", "trust": "high",
          "positioning": "everyday", "service_mode": "care"}


# ------------------------------------------------------------- design DNA

def _renderer_values() -> dict[str, set[str]]:
    """DNA_VALUES as the renderer declares it (experience.ts)."""
    source = (WEB / "components" / "website" / "experience" / "experience.ts").read_text(encoding="utf-8")
    block = source[source.index("const DNA_VALUES"):]
    block = block[:block.index("\n}\n")]
    out: dict[str, set[str]] = {}
    for key, body in re.findall(r"\n  (\w+): \[([^\]]*)\]", block):
        out[key] = set(re.findall(r"'([a-z_]+)'", body))
    return out


def test_every_dna_value_is_one_the_renderer_draws() -> None:
    allowed = _renderer_values()
    for concept in CONCEPTS:
        for trait in ("display", "body", "headline", "texture", "pattern", "divider", "button", "navstyle",
                      "cardstyle", "shape", "cursor", "invert"):
            values = set(getattr(concept, trait))
            assert values <= allowed[trait], (concept.key, trait, values - allowed[trait])
        assert concept.key in allowed["concept"]
        assert concept.space in allowed["space"] and concept.photo in allowed["photo"]
        assert concept.budget in allowed["budget"]


def test_every_drawn_face_accent_edge_and_grade_has_its_css() -> None:
    css = (WEB.parents[2] / "packages" / "ui" / "src" / "site-dna.css").read_text(encoding="utf-8")
    for concept in CONCEPTS:
        for trait in ("display", "body", "headline", "divider"):
            for value in getattr(concept, trait):
                assert f"[data-{trait}='{value}']" in css, (concept.key, trait, value)
        assert f"[data-photo='{concept.photo}']" in css, (concept.key, concept.photo)
        for moment in concept.signatures:
            assert f"[data-signature='{moment}']" in css, (concept.key, moment)


def test_each_brand_gets_its_own_signature_moment_within_its_budget() -> None:
    from platform_core.interview.design_dna import SIGNATURES

    pairs: dict[str, set[tuple[str, str]]] = {}
    for family in ("premium_dark", "modern_commerce", "monumental", "playful_editorial", "editorial_warm"):
        for i in range(40):
            dna = choose_dna(BUTCHER, family=family, archetype="product_commerce", motion="silk", seed=f"{family}-{i}")
            assert dna.signature in SIGNATURES or dna.signature == "none"
            assert dna.signature in BY_KEY[dna.concept].signatures or dna.signature == "none"
            # A restrained or gentle brand gets one moment; a second is never the first again.
            if dna.budget in {"restrained", "gentle"}:
                assert dna.flourish == "none", dna
            else:
                assert dna.flourish != dna.signature, dna
            if dna.signature == "variable_type" or dna.flourish == "variable_type":
                from platform_core.interview.design_dna import MOVING_FACES

                assert dna.display in MOVING_FACES, dna
            pairs.setdefault(dna.concept, set()).add((dna.signature, dna.flourish))
    # Businesses of one concept do not all share one moment.
    for concept, seen in pairs.items():
        if len(BY_KEY[concept].signatures) > 1:
            assert len(seen) >= 2, (concept, seen)


def test_a_moment_is_only_drawn_where_the_pages_can_show_it() -> None:
    from dataclasses import replace

    from platform_core.interview.site_composer import unshowable_moments

    def section(kind: str, variant: str, **content: Any) -> dict[str, Any]:
        return {"section_type_id": kind, "layout_variant": variant, "content": content, "is_visible": True}

    pictured = [{"name": f"Cut {i}", "image_asset_id": f"item-{i}"} for i in range(6)]
    rich = [{"sections": [
        section("hero", "arch", image_asset_id="hero"),
        section("product_showcase", "bento", items=pictured),
        section("about", "sticky_split", image_asset_id="story"),
        section("statement", "image", text="Cut to order.", image_asset_id="process"),
    ]}]
    assert unshowable_moments(rich) == frozenset()
    bare = [{"sections": [
        section("hero", "kinetic"),
        section("product_showcase", "bento", items=pictured[:3]),
        section("about", "text_only"),
        section("statement", "giant", text="Cut to order."),
    ]}]
    # Three pictures still lean with the scroll; nothing else has material.
    assert unshowable_moments(bare) == {"living", "ribbon", "dissolve", "zoom_through"}
    # A story's picture alone on its page has nothing to become.
    alone = [{"sections": [section("about", "story_split", image_asset_id="story")]}]
    assert "dissolve" in unshowable_moments(alone)

    # Drawn again without them, the rest of the brand stays exactly as it was.
    unable = frozenset({"living", "ribbon", "dissolve", "zoom_through", "velocity_skew"})
    for family in ("premium_dark", "modern_commerce", "monumental", "playful_editorial", "editorial_warm"):
        for i in range(40):
            seed = f"{family}-{i}"
            free = choose_dna(BUTCHER, family=family, archetype="product_commerce", motion="silk", seed=seed)
            bound = choose_dna(BUTCHER, family=family, archetype="product_commerce", motion="silk", seed=seed,
                               concept=free.concept, unable=unable)
            assert bound.signature not in unable and bound.flourish not in unable, bound
            assert replace(bound, signature=free.signature, flourish=free.flourish) == free


def test_an_accent_is_only_ever_set_in_a_style_its_face_really_has() -> None:
    for family in ("premium_dark", "modern_commerce", "monumental", "playful_editorial", "editorial_warm"):
        for i in range(40):
            dna = choose_dna(BUTCHER, family=family, archetype="product_commerce", motion="silk", seed=f"{family}-{i}")
            # A grotesk's italic accent is a true serif italic; a serif never sets its accent in capitals.
            if dna.headline == "italic":
                assert dna.display in SERIF, (family, i, dna.display)
            if dna.headline in {"caps", "serif"}:
                assert dna.display not in SERIF, (family, i, dna.display, dna.headline)


def test_the_same_business_always_gets_the_same_dna() -> None:
    a = choose_dna(BUTCHER, family="editorial_warm", archetype="product_commerce", motion="silk", seed="b-1")
    b = choose_dna(BUTCHER, family="editorial_warm", archetype="product_commerce", motion="silk", seed="b-1")
    assert a == b


def test_two_butchers_with_the_same_answers_do_not_share_a_look() -> None:
    looks = [choose_dna(BUTCHER, family="premium_dark", archetype="product_commerce", motion="silk",
                        seed=f"butcher-{i}") for i in range(40)]
    assert len({d.concept for d in looks}) >= 2
    assert len({d.display for d in looks}) >= 4
    assert len({(d.concept, d.display, d.headline, d.shape) for d in looks}) >= 12


def test_a_concept_is_one_idea_not_a_bag_of_traits() -> None:
    for i in range(30):
        dna = choose_dna(BUTCHER, family="premium_dark", archetype="product_commerce", motion="silk", seed=f"s{i}")
        concept = BY_KEY[dna.concept]
        # Every trait comes from the concept the site was given.
        assert dna.display in concept.display and dna.shape in concept.shape and dna.button in concept.button
        assert dna.photo == concept.photo and dna.space == concept.space


def test_a_clinic_gets_a_quiet_direction_and_no_show() -> None:
    for i in range(20):
        dna = choose_dna(CLINIC, family="calm_professional", archetype="service_appointment", motion="calm",
                         seed=f"c{i}")
        assert dna.budget == "restrained"
        assert dna.cursor == "none" and dna.invert == "calm"
        assert dna.headline in {"plain", "italic"}
        assert BY_KEY[dna.concept].budget in {"restrained", "gentle"}


def test_the_creative_directors_concept_stands_only_when_it_fits() -> None:
    fits = choose_dna(BUTCHER, family="editorial_warm", archetype="product_commerce", motion="silk", seed="x",
                      concept="warm_craft")
    assert fits.concept == "warm_craft"
    weights = concept_weights(CLINIC, "calm_professional")
    assert weights["kinetic_sport"] < weights["calm_care"]
    loud = choose_dna(CLINIC, family="calm_professional", archetype="service_appointment", motion="calm", seed="x",
                      concept="kinetic_sport")
    assert loud.concept != "kinetic_sport"


# ---------------------------------------------------------- motion budget

def _page(hero: str = "orbit", catalogue: str = "rail", story: str = "word_reveal") -> list[dict[str, Any]]:
    return [
        {"section_type_id": "hero", "layout_variant": hero, "content": {"headline": "x", "image_asset_id": ASSET}},
        {"section_type_id": "marquee", "layout_variant": "band", "content": {"items": ["a", "b", "c"]}},
        {"section_type_id": "product_showcase", "layout_variant": catalogue, "content": {
            "anchor": "shop", "items": [{"name": f"i{i}", "image_asset_id": ASSET} for i in range(4)]}},
        {"section_type_id": "about", "layout_variant": story, "content": {"body": "b", "image_asset_id": ASSET}},
    ]


def test_a_restrained_brand_gets_one_slow_picture_and_nothing_else_moving() -> None:
    page = _page()
    notes = direct_motion(page, "restrained", range_variant="commerce_grid")
    kinds = {s["section_type_id"]: s["layout_variant"] for s in page}
    assert kinds["hero"] == "stage"  # one photograph, framed, rising slowly
    assert "marquee" not in kinds
    assert kinds["product_showcase"] == "spotlight"
    assert kinds["about"] == "sticky_split"
    assert len(notes) == 4


def test_a_gentle_brand_gets_one_scroll_moment_after_the_hero() -> None:
    page = _page(hero="kinetic")
    direct_motion(page, "gentle")
    kinds = {s["section_type_id"]: s["layout_variant"] for s in page}
    assert kinds["hero"] == "stage"  # a poster hero is too loud for it
    assert kinds["product_showcase"] == "rail"  # the range is what people came for
    assert kinds["about"] == "sticky_split"


def test_an_expressive_brand_keeps_everything() -> None:
    page = _page()
    before = copy.deepcopy(page)
    assert direct_motion(page, "expressive") == [] and page == before


def test_a_menu_book_is_how_a_menu_reads_not_an_effect() -> None:
    page = _page(catalogue="menu_book")
    direct_motion(page, "restrained")
    assert next(s for s in page if s["section_type_id"] == "product_showcase")["layout_variant"] == "menu_book"


# ----------------------------------------------------------------- critic

def _payload(sections: list[dict[str, Any]], budget: str = "gentle") -> dict[str, Any]:
    return {"pages": [{"slug": "home", "sections": sections}], "navigation": [],
            "theme_hints": {"dna": {"budget": budget}}}


def _strings(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {s for k, v in value.items() if k not in {"layout_variant"} for s in _strings(v)}
    if isinstance(value, list):
        return {s for v in value for s in _strings(v)}
    return {value} if isinstance(value, str) else set()


def test_the_critic_fixes_a_repeated_picture_and_a_run_of_boxes_without_writing_a_word() -> None:
    sections = [
        {"section_type_id": "hero", "layout_variant": "plane", "content": {"headline": "H", "image_asset_id": ASSET}},
        {"section_type_id": "product_showcase", "layout_variant": "commerce_grid", "content": {
            "anchor": "shop", "items": [{"name": "Curry cut", "image_asset_id": OTHER}]}},
        {"section_type_id": "pillars", "layout_variant": "cards", "content": {"items": [
            {"title": "Cut by hand"}, {"title": "Fresh daily"}, {"title": "Kept aside"}]}},
        {"section_type_id": "cta_band", "layout_variant": "image_banner", "content": {
            "headline": "Order today", "image_asset_id": ASSET}},
    ]
    payload = _payload(sections)
    words_before = _strings(payload["pages"])
    codes = {f.code for f in critique(payload)}
    assert {"repeated_picture", "card_after_card"} <= codes
    result = review(payload)
    assert result["rounds"] >= 1 and not [f for f in result["open"] if f["fixable"]]
    band = payload["pages"][0]["sections"][-1]
    assert "image_asset_id" not in band["content"] and band["layout_variant"] == "centered"
    assert payload["pages"][0]["sections"][2]["layout_variant"] == "numbered"
    # Only removed, never added: every word after polishing was there before.
    assert _strings(payload["pages"]) <= words_before


def test_the_critic_breaks_a_wall_of_words_with_a_picture() -> None:
    sections = [
        {"section_type_id": "hero", "layout_variant": "plane", "content": {"headline": "H"}},
        {"section_type_id": "statement", "layout_variant": "giant", "content": {"text": "We cut by hand."}},
        {"section_type_id": "faq", "layout_variant": "accordion", "content": {"items": [{"q": "q", "a": "a"}]}},
        {"section_type_id": "media_text", "layout_variant": "alternating", "content": {"items": [
            {"title": "t", "image_asset_id": ASSET}]}},
    ]
    payload = _payload(sections)
    review(payload)
    kinds = [s["section_type_id"] for s in payload["pages"][0]["sections"]]
    assert kinds.index("media_text") < kinds.index("faq")


def test_the_critic_quiets_a_page_that_moves_too_much_for_its_brand() -> None:
    sections = _page() + [
        {"section_type_id": "media_text", "layout_variant": "sticky", "content": {"items": [{"title": "a"}]}},
        {"section_type_id": "statement", "layout_variant": "giant", "content": {"text": "x"}},
    ]
    payload = _payload(sections, budget="restrained")
    assert any(f.code == "motion_overload" for f in critique(payload))
    review(payload)
    assert not any(f.code == "motion_overload" for f in critique(payload))


# ---------------------------------------------------------- inner pages

def _rich_meat() -> BusinessBlueprint:
    bp: BusinessBlueprint = meat()
    bp.discovery["brand.story"] = TargetState(
        status="answered", quote="We started this shop in 1998 and still cut every order by hand.")
    return bp


def test_a_shop_with_a_real_range_gets_real_pages() -> None:
    payload = compose(_rich_meat())
    slugs = [p["slug"] for p in payload["pages"]]
    assert slugs[0] == "home" and "shop" in slugs and "visit" in slugs
    paths = {n["path"] for n in payload["navigation"]}
    # Every link in the header goes to a page that exists, or a part of home.
    home_anchors = {s["content"].get("anchor") for s in payload["pages"][0]["sections"]}
    for path in paths:
        assert path == "/" or path[1:] in slugs or path[2:] in home_anchors, path
    assert payload["theme_hints"]["quality"]["valid"], payload["theme_hints"]["quality"]["issues"]
    shop = next(p for p in payload["pages"] if p["slug"] == "shop")
    opening, showcase = shop["sections"][:2]
    assert opening["layout_variant"] == "page" and showcase["section_type_id"] == "product_showcase"
    # The range's title is said once, by the page's opening.
    assert opening["content"]["headline"] and not showcase["content"].get("title")
    teaser = next(s for s in payload["pages"][0]["sections"] if s["section_type_id"] == "product_showcase")
    assert teaser["content"]["more_path"] == "/shop" and len(teaser["content"]["items"]) <= 6
    # No closing band on the shop page sends the visitor to the page they are on.
    for section in shop["sections"]:
        assert section["content"].get("cta_url") != "/shop"


def test_each_page_owns_its_sections() -> None:
    payload = compose(_rich_meat())
    seen: set[int] = set()
    for page in payload["pages"]:
        for section in page["sections"]:
            assert id(section) not in seen and id(section["content"]) not in seen
            seen |= {id(section), id(section["content"])}


def test_each_question_is_asked_once_and_answered_from_the_owners_facts() -> None:
    bp = _rich_meat()
    payload = compose(bp)
    by_page = {p["slug"]: [q["q"] for s in p["sections"] if s["section_type_id"] == "faq"
                           for q in s["content"]["items"]] for p in payload["pages"]}
    # Once per page; the home page asks a few, the visit page answers them all.
    for asked in by_page.values():
        assert len(asked) == len(set(asked))
    assert by_page["visit"] and set(by_page["home"]) <= set(by_page["visit"])
    assert len(by_page["home"]) <= 4
    answers = " ".join(q["a"] for p in payload["pages"] for s in p["sections"] if s["section_type_id"] == "faq"
                       for q in s["content"]["items"])
    # Nothing the owner did not say: no hours, no prices, no promises.
    assert "open" not in answers.lower() and "₹" not in answers
    assert "Nookampalayam" in answers


def test_no_question_without_a_fact_behind_it() -> None:
    bp = BusinessBlueprint(business_id=uuid4())
    assert faqs_for(bp, ordering=[], visiting=[], contact={}, address="", booking=False) == []
    # A business that takes no orders (a learning trust) is never asked how to order.
    asked = [q["q"] for q in faqs_for(bp, ordering=[], visiting=[], contact={"phone": "+91 98410 57322"},
                                      address="", booking=False)]
    assert asked == ["How do I get in touch?"]
    shop = [q["q"] for q in faqs_for(bp, ordering=[{"kind": "payment", "title": "Pay", "body": "UPI or cash on delivery."}],
                                     visiting=[], contact={"phone": "+91 98410 57322"}, address="", booking=False)]
    assert shop[0] == "How do I order?"


def test_pillars_are_the_owners_to_say() -> None:
    bp = BusinessBlueprint(business_id=uuid4())
    facts = [{"kind": "delivery", "title": "Home delivery", "body": "Around Adyar."},
             {"kind": "pickup", "title": "Pickup", "body": "From the shop."},
             {"kind": "weight", "title": "Sold by the kg", "body": ""}]
    # Ordering facts alone are the ordering strip again, not what a business stands on.
    assert pillars_for(bp, WebsiteCopy(), facts, ["Store pickup"]) == []
    bp.discovery["brand.story"] = TargetState(
        status="answered", quote="We use our mother's recipes, stone-ground spices and no preservatives.")
    pillars = pillars_for(bp, WebsiteCopy(), facts, ["Store pickup"])
    titles = [p["title"] for p in pillars]
    assert titles[:3] == ["We use our mother's recipes", "Stone-ground spices", "No preservatives"]
    assert "Store pickup" not in titles  # says what "Pickup" already says


def test_a_statement_never_quotes_an_owner_in_another_language_as_english() -> None:
    bp = BusinessBlueprint(business_id=uuid4())
    bp.discovery["brand.story"] = TargetState(status="answered",
                                              quote="Ellaam en amma recipe, dhinamum fresh-aa samaippen.")
    assert statement_for(bp, WebsiteCopy(), "") is None
    bp.discovery["brand.story"] = TargetState(status="answered",
                                              quote="Our recipes are from my grandmother's Karaikudi kitchen.")
    said = statement_for(bp, WebsiteCopy(), "")
    assert said and said["highlight"] and said["highlight"] in said["text"]
    # Never the hero's own subline set again at display size.
    hero = ["Recipes from my grandmother's Karaikudi kitchen", "Our recipes come from my grandmother's kitchen."]
    assert statement_for(bp, WebsiteCopy(), "", avoid=hero) is None
    told = statement_for(bp, WebsiteCopy(statement="Our recipes are from my grandmother's Karaikudi kitchen."), "",
                         avoid=hero)
    assert told is None


def test_a_gym_shows_its_plans_once() -> None:
    bp: BusinessBlueprint = gym()
    bp.discovery["memberships.plans"] = TargetState(status="answered", quote="Monthly 2500, quarterly 6500")
    bp.taxonomy.groups.append(CatalogueGroup(name="Plans", items=[
        CatalogueItem(name="Monthly", price="2500"), CatalogueItem(name="Quarterly", price="6500")]))
    payload = compose(bp)
    browse = next(s for s in payload["pages"][0]["sections"] if s["content"].get("anchor") == "shop")
    shown = [c.get("name") for c in browse["content"].get("categories") or browse["content"].get("items") or []]
    assert "Plans" not in shown and "Memberships" not in shown
    lists = [s for p in payload["pages"] for s in p["sections"] if s["section_type_id"] == "product_showcase"]
    names = [i["name"] for s in lists for i in s["content"].get("items") or []]
    assert len(names) == len(set(names)), names


def test_a_thin_business_stays_one_honest_page() -> None:
    payload = compose(real_estate())
    assert payload["pages"][0]["slug"] == "home"
    for page in payload["pages"][1:]:
        assert len(page["sections"]) >= 2
    assert json.dumps(payload).count('"slug": "home"') == 1


# ------------------------------------------------- owner edits, every page

def _s(kind: str, **content: Any) -> dict[str, Any]:
    return {"section_type_id": kind, "content": content, "layout_variant": "x", "is_visible": True}


def _site(home: list[dict[str, Any]], **inner: list[dict[str, Any]]) -> dict[str, Any]:
    pages = [{"slug": "home", "sections": home}] + [{"slug": k, "sections": v} for k, v in inner.items()]
    return {"pages": pages, "theme": {"a": 1}, "navigation": []}


def test_personalization_lands_on_every_page_and_owner_edits_win_on_each() -> None:
    built = _site([_s("hero", headline="A")], shop=[_s("hero", headline="Shop"), _s("product_showcase", items=[1])],
                  visit=[_s("contact")])
    base = base_fingerprints(built)
    live = _site([_s("hero", headline="A")], shop=[_s("hero", headline="Shop"),
                                                   _s("product_showcase", items=[1, 2])])  # edited; visit deleted
    personalized = {"pages": [{"slug": "home", "sections": [_s("hero", headline="B")]},
                              {"slug": "shop", "sections": [_s("hero", headline="Our shop"),
                                                            _s("product_showcase", items=[9])]},
                              {"slug": "visit", "sections": [_s("contact", title="Visit")]},
                              {"slug": "about", "sections": [_s("about", body="story")]}],
                    "navigation": [], "theme_hints": {}}
    merged, kept = merge(personalized, live, base)
    assert merged is not None
    pages = {p["slug"]: p for p in merged["pages"]}
    assert pages["home"]["sections"][0]["content"]["headline"] == "B"
    assert pages["shop"]["sections"][0]["content"]["headline"] == "Our shop"
    assert pages["shop"]["sections"][1]["content"]["items"] == [1, 2]  # the owner's edit stands
    assert "visit" not in pages  # the owner deleted it: it stays deleted
    assert "about" in pages  # new in personalization
    assert set(kept) == {"shop:product_showcase", "page:visit"}


def test_a_page_the_owner_added_means_they_restructured_the_site() -> None:
    built = _site([_s("hero")])
    live = _site([_s("hero")], offers=[_s("text_block")])
    personalized = {"pages": [{"slug": "home", "sections": [_s("hero", headline="B")]}],
                    "navigation": [], "theme_hints": {}}
    assert merge(personalized, live, base_fingerprints(built)) == (None, [])


def test_a_build_recorded_before_inner_pages_still_merges() -> None:
    old_base = {"sections": {"hero": base_fingerprints(_site([_s("hero")]))["sections"]["hero"]},
                "theme": base_fingerprints(_site([]))["theme"], "navigation": base_fingerprints(_site([]))["navigation"],
                "pages": 1}
    personalized = {"pages": [{"slug": "home", "sections": [_s("hero", headline="B")]},
                              {"slug": "shop", "sections": [_s("product_showcase")]}],
                    "navigation": [], "theme_hints": {}}
    merged, _ = merge(personalized, _site([_s("hero")]), old_base)
    assert merged is not None and [p["slug"] for p in merged["pages"]] == ["home", "shop"]


# --------------------------------------------- the critic that sees the site

def test_the_vision_critic_keeps_only_what_exists_and_never_writes() -> None:
    import asyncio

    from platform_core.interview.site_vision_critic import Shot, critique, revise

    payload: dict[str, Any] = {"pages": [{"slug": "home", "sections": [
        {"section_type_id": "hero", "layout_variant": "cinematic_zoom", "content": {"headline": "H",
                                                                                    "image_asset_id": ASSET}},
        {"section_type_id": "product_showcase", "layout_variant": "bento", "content": {"anchor": "shop", "items": []}},
        {"section_type_id": "pillars", "layout_variant": "cards", "content": {"items": [{"title": "a"}]}},
    ]}], "navigation": [], "theme_hints": {"dna": {"budget": "gentle"}}}

    class Seeing:
        async def generate_structured_with_images(self, prompt: str, images: list[Any], schema: dict[str, Any],
                                                  model_config: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
            assert len(images) == 1 and model_config["purpose"] == "website.critique"
            return {"scores": {"hierarchy": 5, "imagery": 11},
                    "findings": [{"code": "generic_hero", "page": "home", "section": 0, "severity": "high",
                                  "note": "Looks like any template."},
                                 {"code": "excessive_cards", "page": "home", "section": 2, "severity": "medium",
                                  "note": "Boxes after boxes."},
                                 {"code": "add_testimonials", "page": "home", "section": 1, "severity": "high",
                                  "note": "Invent some reviews."},
                                 {"code": "poor_image", "page": "pricing", "section": 0, "severity": "low",
                                  "note": "No such page."},
                                 {"code": "weak_hierarchy", "page": "home", "section": 1, "severity": "low",
                                  "note": "Titles too small."}]}

    words_before = _strings(payload["pages"])
    review = asyncio.run(critique(Seeing(), [Shot(b"png", "home", "desktop", ((0, "hero"),))], payload))
    # An unknown code, a page that does not exist and an out-of-range score are dropped.
    assert [f.code for f in review.findings] == ["vision:generic_hero", "vision:excessive_cards",
                                                 "vision:weak_hierarchy"]
    assert review.scores == {"hierarchy": 5}
    assert [f.fixable for f in review.findings] == [True, True, False]
    tried: set[tuple[str, int, str]] = set()
    done = revise(payload, review.findings, tried)
    sections = payload["pages"][0]["sections"]
    assert sections[0]["layout_variant"] != "cinematic_zoom" and sections[2]["layout_variant"] == "numbered"
    assert len(done) == 2
    # The same complaint again: never back to a layout the section already had.
    revise(payload, review.findings, tried)
    assert sections[2]["layout_variant"] == "strip" and sections[0]["layout_variant"] not in {"cinematic_zoom"}
    assert _strings(payload["pages"]) <= words_before


def test_a_quiet_brand_never_gets_a_loud_hero_from_the_critic() -> None:
    from platform_core.interview.site_critic import Finding
    from platform_core.interview.site_vision_critic import revise

    payload: dict[str, Any] = {"pages": [{"slug": "home", "sections": [
        {"section_type_id": "hero", "layout_variant": "cinematic_zoom", "content": {"image_asset_id": ASSET}}]}],
        "theme_hints": {"dna": {"budget": "restrained"}}}
    tried: set[tuple[str, int, str]] = set()
    for _ in range(4):
        revise(payload, [Finding("vision:generic_hero", "home", "hero#0", "generic", True)], tried)
        assert payload["pages"][0]["sections"][0]["layout_variant"] not in {"plane", "orbit", "kinetic"}


# ------------------------------------------------------ rhythm and the range

def test_each_art_direction_tells_the_home_page_in_its_own_order() -> None:
    from platform_core.interview.site_pages import arrange

    def s(kind: str, variant: str = "x", **content: Any) -> dict[str, Any]:
        return {"section_type_id": kind, "layout_variant": variant, "content": content}

    page = [s("hero"), s("statement"), s("product_showcase", anchor="shop"), s("pillars"), s("highlights"),
            s("fulfilment_strip"), s("media_text"), s("faq"), s("cta_band")]
    market = [x["section_type_id"] for x in arrange(page, "fresh_market")]
    craft = [x["section_type_id"] for x in arrange(page, "warm_craft")]
    assert market[0] == "hero" and market[-1] == "cta_band" and craft[-1] == "cta_band"
    assert market[1] == "product_showcase" and craft[1] == "statement"
    assert market != craft
    # The owner's "put delivery higher" still wins.
    led = [x["section_type_id"] for x in arrange(page, "warm_craft", lead="fulfilment_strip")]
    assert led[1] == "fulfilment_strip"
    assert arrange(page, "") == page


def test_a_range_with_pictured_kinds_reads_as_chapters_on_its_own_page() -> None:
    bp: BusinessBlueprint = _rich_meat()
    for slot_key in ("category:chicken", "category:mutton", "category:fish-seafood"):
        from platform_core.interview.media_director import Slot, record

        record(bp, Slot(slot_key, "x", "4:3", "gallery", "Draft visual · x"), uuid4())
    payload = compose(bp)
    shop = next(p for p in payload["pages"] if p["slug"] == "shop")
    showcase = next(s for s in shop["sections"] if s["section_type_id"] == "product_showcase")
    assert showcase["layout_variant"] == "chapters"


def test_the_numbers_band_holds_only_facts() -> None:
    from platform_core.interview.models import Message
    from platform_core.interview.site_pages import numbers_for

    bp = BusinessBlueprint(business_id=uuid4())
    bp.messages = [Message(role="user", text="My father started this stall in 1987. Open 6 am to 1 pm.")]
    items = [{"name": f"Cut {i}"} for i in range(5)]
    got = numbers_for(bp, archetype="product_commerce", items=items, ordering=[])
    assert got == [{"value": "1987", "label": "Serving since"}, {"value": "5", "label": "items on the counter"},
                   {"value": "6am", "label": "we open"}]
    # Two facts are not a band: the counter and nothing else stays off the page.
    bp.messages = [Message(role="user", text="We sell mutton. Open 6 am to 1 pm.")]
    assert numbers_for(bp, archetype="product_commerce", items=items, ordering=[]) == []
