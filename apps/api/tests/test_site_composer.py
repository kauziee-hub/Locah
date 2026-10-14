"""The creative composer: one system, four very different websites.

No network. Blueprints are built the way the interview builds them (facts,
answers, the owner's catalogue); pictures come from a fake drawer. What is
checked is the design decision — archetype, reference profile, which sections
exist and in what shape — and the truth rules: no vague items, no generic
"What we do" for things people buy, chips only from the owner's answers, no
cart language anywhere in the content.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from platform_core.interview.creative_director import (
    CreativeChoices,
    contrast,
    derive_archetype,
    direct,
)
from platform_core.interview.media_director import draw_missing, picture_for, plan_slots, record
from platform_core.interview.models import (
    BusinessBlueprint,
    CatalogueGroup,
    CatalogueItem,
    Fact,
    OwnerClaim,
    PatternEvidence,
    TargetState,
)
from platform_core.interview.site_composer import compose_site
from platform_core.interview.website import with_draft
from platform_core.interview.website_copy import NamedLine, WebsiteCopy
from platform_core.website.image_generation import GeneratedImage

ACTIVE = frozenset({"offerings-catalog", "orders", "payments", "inventory", "fulfilment"})


def _bp(name: str, facts: dict[str, str], patterns: list[tuple[str, str]],
        answers: dict[str, tuple[str, str]], groups: list[CatalogueGroup]) -> BusinessBlueprint:
    bp = BusinessBlueprint(
        business_id=uuid4(),
        identity={"display_name": Fact(value=name, source="PLATFORM", confirmation="confirmed")},
    )
    bp.known_facts = {k: Fact(value=v, source="USER_STATEMENT", confirmation="confirmed") for k, v in facts.items()}
    bp.operating_patterns = [PatternEvidence(pattern=p, quote=q) for p, q in patterns]
    for target, (summary, quote) in answers.items():
        bp.discovery[target] = TargetState(status="answered", summary=summary, quote=quote)
    bp.taxonomy.groups = groups
    return bp


def meat() -> BusinessBlueprint:
    bp = _bp(
        "Ishant Proteins",
        {"offerings": "chicken, mutton, fish, crab and squid", "locations": "In nookampalayam road",
         "phone": "8754722026", "customer_actions": "People select the meat and kg and order"},
        [("product_led", "We sell chicken"), ("order_led", "and order"), ("local_delivery", "We deliver"),
         ("pickup", "people can pick up too")],
        {"offerings.units": ("Sold by weight.", "select the meat and kg"),
         "fulfilment.mode": ("You deliver and offer pickup.", "We deliver ourselves, people can pick up too"),
         "fulfilment.area": ("Nookampalayam and Perumbakkam", "around Nookampalayam and Perumbakkam"),
         "commerce.payment": ("Online and cash on delivery.", "Both online and cash on delivery")},
        [CatalogueGroup(name="Chicken", items=[CatalogueItem(name="Whole chicken"), CatalogueItem(name="Curry cut"),
                                               CatalogueItem(name="Boneless")], price="₹240", unit="per kg"),
         CatalogueGroup(name="Mutton", items=[CatalogueItem(name="Curry cut"), CatalogueItem(name="Chops")]),
         CatalogueGroup(name="Fish & Seafood", label_source="ai_suggestion",
                        items=[CatalogueItem(name="Seer fish"), CatalogueItem(name="Pomfret"),
                               CatalogueItem(name="Fish different varieties"), CatalogueItem(name="Crab"),
                               CatalogueItem(name="Squid")])],
    )
    bp.website_draft.owner_claims = [OwnerClaim(claim="Fresh meat from the farm to your house",
                                                quote="we sell fresh meat from farm to ur house")]
    return bp


def home_food() -> BusinessBlueprint:
    return _bp(
        "Amma's Pantry",
        {"offerings": "thokku, podi and pickles", "locations": "Mylapore, Chennai", "phone": "9840012345",
         "customer_actions": "Customers choose jars and order on WhatsApp"},
        [("product_led", "We make thokku"), ("order_led", "order on WhatsApp"), ("local_delivery", "we deliver")],
        {"fulfilment.mode": ("You deliver.", "we deliver in Chennai"),
         "commerce.payment": ("UPI or cash.", "UPI or cash")},
        [CatalogueGroup(name="Thokku", items=[CatalogueItem(name="Vazhaipoo thokku", price="₹250", unit="250g"),
                                              CatalogueItem(name="Nellikai poondu thokku", price="₹250", unit="250g")]),
         CatalogueGroup(name="Podi", items=[CatalogueItem(name="Idli podi", price="₹180", unit="200g")]),
         CatalogueGroup(name="Pickles", items=[CatalogueItem(name="Mango pickle", price="₹220", unit="250g")])],
    )


def gym() -> BusinessBlueprint:
    return _bp(
        "Iron Temple Fitness",
        {"offerings": "monthly memberships, strength classes and personal training", "locations": "Velachery",
         "phone": "9000044321"},
        [("membership_led", "monthly memberships"), ("runs_classes", "strength classes")],
        {},
        [CatalogueGroup(name="Memberships", items=[CatalogueItem(name="Monthly membership", price="₹2500",
                                                                 unit="per month")]),
         CatalogueGroup(name="Classes", items=[CatalogueItem(name="Strength classes")]),
         CatalogueGroup(name="Personal training")],
    )


def real_estate() -> BusinessBlueprint:
    return _bp(
        "SkyNest Homes",
        {"offerings": "villa projects and apartments in OMR", "locations": "OMR, Chennai", "phone": "9840098400",
         "customer_actions": "Buyers call us to book a site visit"},
        [("lead_generation", "call us")],
        {},
        [CatalogueGroup(name="Villa projects", items=[CatalogueItem(name="Palm Grove Villas"),
                                                      CatalogueItem(name="Lake View Residency")]),
         CatalogueGroup(name="Apartments", items=[CatalogueItem(name="Skyline Towers")])],
    )


def compose(
    bp: BusinessBlueprint, copy: WebsiteCopy | None = None, contact: dict[str, Any] | None = None
) -> dict[str, Any]:
    return dict(
        compose_site(
            bp, direct(bp, "other"), with_draft(bp, copy), business_type="other",
            contact=contact or {"phone": "+91" + bp.known_facts["phone"].value},
            active_modules=ACTIVE,
        )
    )


def sections(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["section_type_id"]: s for s in payload["pages"][0]["sections"]}


def test_four_businesses_get_four_different_websites():
    # Design system v3: the family follows the business's dimensions (what it
    # offers, how customers act, how it describes itself), not a fixed profile
    # per archetype.
    looks = {}
    for build, arche, family in (
        (meat, "product_commerce", "modern_commerce"),
        (home_food, "menu_commerce", "editorial_warm"),
        (gym, "membership_fitness", "monumental"),
        (real_estate, "real_estate_projects", "airy_property"),
    ):
        bp = build()
        assert derive_archetype(bp, "other") == arche
        payload = compose(bp)
        theme = payload["theme_hints"]
        assert theme["design_family"] == family
        assert theme["quality"]["valid"], theme["quality"]["issues"]
        looks[arche] = (theme["design_family"], theme["type_system"], theme["palette_key"],
                        sections(payload)["hero"]["layout_variant"])
    # Not one site in four colours: family, type and palette all differ.
    assert len({v[0] for v in looks.values()}) == 4
    assert len({v[1] for v in looks.values()}) == 4
    assert len({v[2] for v in looks.values()}) == 4


def test_the_meat_shop_is_a_shop():
    payload = compose(meat())
    found = sections(payload)
    hero = found["hero"]
    # No photos yet: Modern Commerce's type-led storefront, not an empty photo
    # frame — poster type, or a moving gradient in the shop's colours.
    assert payload["theme_hints"]["design_family"] == "modern_commerce"
    assert hero["layout_variant"] in {"kinetic", "aurora"}
    assert payload["theme_hints"]["experience"]["motion"] == "snap"
    assert hero["content"]["eyebrow"] == "Nookampalayam Road"
    assert hero["content"]["badges"] == ["Sold by the kg", "Home delivery", "Store pickup"]
    assert hero["content"]["cta_url"] == "#shop"
    shop = found["product_showcase"]
    # Cuts by the kg read like a price list: chapters, or a board per meat.
    assert shop["layout_variant"] in {"menu_book", "category_boards"}
    assert shop["content"]["title"] == "Shop by category"
    names = [i["name"] for i in shop["content"]["items"]]
    assert "Fish different varieties" not in names and "Seer fish" in names
    chicken = next(c for c in shop["content"]["categories"] if c["name"] == "Chicken")
    assert chicken["meta"] == "From ₹240 per kg"
    assert shop["content"]["order_label"] == "Call to order"  # no WhatsApp was mentioned
    strip = found["fulfilment_strip"]["content"]["items"]
    assert [i["kind"] for i in strip] == ["weight", "delivery", "pickup", "payment"]
    assert strip[1]["body"] == "Delivered around Nookampalayam and Perumbakkam."
    assert [n["path"] for n in payload["navigation"]] == ["/", "/#shop", "/#contact"]
    text = json.dumps(payload).lower()
    assert "what we do" not in text and "add to cart" not in text and "cart" not in text


def test_a_generic_heading_from_the_model_is_replaced_for_a_shop():
    copy = WebsiteCopy(headline="Meat, by the kilo.", products_title="What we do",
                       category_lines=[NamedLine(name="Chicken", line="Everyday cuts for curries.")])
    shop = sections(compose(meat(), copy))["product_showcase"]
    assert shop["content"]["title"] == "Shop by category"


def test_the_owner_story_becomes_a_story_with_their_line():
    bp = meat()
    copy = WebsiteCopy(about_title="From the farm to your home",
                       about_body="Ishant Proteins brings fresh meat from the farm to your house.")
    story = sections(compose(bp, copy))["about"]
    assert story["content"]["quote"] == "Fresh meat from the farm to your house"
    assert story["content"]["anchor"] == "story"


def test_home_food_shows_a_priced_menu():
    shop = sections(compose(home_food()))["product_showcase"]
    menu = {i["name"]: i for i in shop["content"]["items"]}
    assert menu["Vazhaipoo thokku"]["price"] == "₹250" and menu["Vazhaipoo thokku"]["unit"] == "250g"
    assert shop["content"]["filters"] == ["Thokku", "Podi", "Pickles"]
    # The trade's own heading (the home-food playbook), not the archetype's.
    assert shop["content"]["title"] == "What's cooking"


def test_whatsapp_only_when_the_owner_said_it():
    shop = sections(compose(home_food(), contact={"phone": "+919840012345", "whatsapp": "+919840012345"}))
    assert shop["product_showcase"]["content"]["order_label"] == "Order on WhatsApp"


def test_the_palette_keeps_buttons_readable():
    bp = meat()
    ground = direct(bp, "other").palette.surface
    for colour in (ground, ground[:-1] + ("0" if ground[-1] != "0" else "1")):  # would vanish on its own ground
        direction = direct(bp, "other", CreativeChoices(reference_profile="modern_commerce",
                                                        primary_color=colour))
        assert contrast(direction.palette.primary, direction.palette.surface) >= 3.0
        assert "primary_contrast" in direction.repairs
    # The model may pick only among families the evidence supports: a gym's
    # look for a meat shop is refused.
    from platform_core.interview.creative_director import allowed_families

    wrong = direct(bp, "other", CreativeChoices(reference_profile="monumental"))
    assert "family_not_allowed" in wrong.repairs and wrong.family in allowed_families(bp, "other")


PNG = GeneratedImage(mime_type="image/png", bytes=b"png", model="m", latency_ms=1, prompt="p")


@pytest.mark.asyncio
async def test_draft_visuals_are_on_by_default_off_for_a_text_led_site_and_drawn_once():
    bp = meat()
    direction = direct(bp, "other")
    calls: list[str] = []

    async def draw(prompt: str, aspect: str):
        calls.append(prompt)
        return PNG, ""

    bp.visual_consent = "none"  # the owner asked for a text-led site: nothing is drawn
    assert await draw_missing(bp, direction, "a meat shop", draw=draw) == []
    bp.visual_consent = "unknown"  # an owner with no photos gets pictures by default
    drawn = await draw_missing(bp, direction, "a meat shop", draw=draw)
    assert [s.key for s, _, _ in drawn] == ["hero", "category:chicken", "category:mutton",
                                           "category:fish-seafood", "story"]
    assert all("One continuous photograph" in p for p in calls)
    assert all("No text" in p and "people" in p for p in calls)
    assert all("farm" not in p.lower() and "240" not in p for p in calls)
    for slot, _, _ in drawn:
        record(bp, slot, uuid4())
    assert await draw_missing(bp, direction, "a meat shop", draw=draw) == []  # cached
    payload = compose(bp)
    found = sections(payload)
    assert found["hero"]["content"]["image_asset_id"] == picture_for(bp, "hero")
    boards = found["product_showcase"]["content"]["categories"]
    assert all(c.get("image_asset_id") for c in boards)
    # The story has its own picture: the hero is not shown three times.
    storied = sections(compose_site(
        bp, direction, WebsiteCopy(about_body="Family run for eight years."), business_type="other",
        contact={"phone": "8754722026"}, active_modules=ACTIVE))
    assert storied["about"]["content"]["image_asset_id"] == picture_for(bp, "story")
    assert storied["about"]["content"]["image_asset_id"] != found["hero"]["content"]["image_asset_id"]
    assert all(m.source == "AI_GENERATED" and m.label.startswith("Draft visual") for m in bp.media_assets)


def test_media_budget_follows_the_archetype():
    # Media truth policy: a kitchen's featured dishes are drawn as representative
    # drafts; a developer's projects are factual — listed, never drawn — while its
    # hero and story (architecture, a courtyard) are mood and may be.
    for build, count in ((meat, 5), (home_food, 6), (gym, 2), (real_estate, 2)):
        bp = build()
        drawable = [s for s in plan_slots(bp, direct(bp, "other")) if s.truth_class != "factual"]
        assert len(drawable) == count, build.__name__
    bp = home_food()
    assert any(s.key.startswith("item:") for s in plan_slots(bp, direct(bp, "other")))
    bp = real_estate()
    projects = [s for s in plan_slots(bp, direct(bp, "other")) if s.purpose in {"category", "item"}]
    assert projects and all(s.truth_class == "factual" for s in projects)


# ------------------------------------------------ found in the live Gemini run


def test_the_model_sees_the_shape_of_every_list_it_must_fill() -> None:
    """Nested `$defs` were dropped, so `item_lines` reached Gemini as `items: {}`.

    It answered with bare strings, and validation threw the whole plan away.
    """
    from platform_core.interview.creative_director import creative_plan_schema
    from platform_core.website.ai_provider import _inline_schema

    copy = _inline_schema(creative_plan_schema())["properties"]["copy"]["properties"]
    for field in ("category_lines", "item_lines", "features", "steps"):
        assert copy[field]["items"].get("properties"), field
    assert set(copy["item_lines"]["items"]["properties"]) == {"name", "line"}


def test_one_bad_line_does_not_discard_a_good_answer() -> None:
    from platform_core.interview.creative_director import validate_repairing

    raw = {"headline": "Fresh cuts, your way", "extra": 1,
           "item_lines": [{"name": "Curry cut", "line": "For everyday curries."}, "Boneless"]}
    copy, repairs = validate_repairing(WebsiteCopy, raw, "copy")
    assert copy.headline == "Fresh cuts, your way"
    assert [line.name for line in copy.item_lines] == ["Curry cut"]
    assert "copy.extra:extra_forbidden" in repairs and any("item_lines.1" in r for r in repairs)


def test_an_empty_group_folds_into_the_group_that_names_its_varieties() -> None:
    """"Fish" (varieties unknown) and "Fish & Seafood" (the varieties) are one shelf."""
    from platform_core.interview.models import GroupProposal, ItemProposal
    from platform_core.interview.taxonomy import catalogue_lines, govern_catalogue

    bp = _bp("Ishant Proteins", {"offerings": "chicken, mutton, fish, crab and squid"}, [], {},
             [CatalogueGroup(name="Chicken", items=[CatalogueItem(name="Curry cut", price="240", unit="per kg"),
                                                    CatalogueItem(name="Boneless", price="380", unit="per kg")]),
              CatalogueGroup(name="Fish", needs=["varieties", "price"])])
    heard = "Fish - seer fish, pomfret and sardine. Crab and squid we clean and sell by kg."
    govern_catalogue(bp, [GroupProposal(group="Fish & Seafood", items=[
        ItemProposal(name=n) for n in ("Seer fish", "Pomfret", "Sardine", "Crab", "Squid")])], heard)
    names = [g.name for g in bp.taxonomy.groups]
    assert names == ["Chicken", "Fish & Seafood"]
    seafood = bp.taxonomy.groups[1]
    assert "varieties" not in seafood.needs and len(seafood.items) == 5
    assert catalogue_lines(bp)[0]["price"] == "from ₹240 per kg"


def test_a_claim_the_owner_made_survives_in_another_word_form() -> None:
    from platform_core.interview.website_copy import _grounded

    said = "we deliver around nookampalayam. fresh stock every morning. family run for 8 years"
    assert _grounded("Fresh cuts delivered to your door.", said)
    assert _grounded("Delivery around Nookampalayam.", said)
    assert not _grounded("Fresh daily.", said)  # "every morning" is not "daily"
    assert not _grounded("The best cuts in town.", said)


def test_prices_read_as_rupees_and_boards_show_the_lowest_price_given() -> None:
    from platform_core.interview.site_composer import money

    assert money("240") == "₹240" and money("Rs. 1,200") == "₹1,200" and money("₹99") == "₹99"
    assert money("1.2 crore") == "₹1.2 crore" and money("price on request") == "price on request"
    bp = meat()
    bp.taxonomy.groups[0] = CatalogueGroup(name="Chicken", items=[
        CatalogueItem(name="Curry cut", price="240", unit="per kg"),
        CatalogueItem(name="Boneless", price="380", unit="per kg")])
    payload = compose_site(bp, direct(bp, "other"), with_draft(bp, None), business_type="other",
                           contact={"phone": "8754722026"}, active_modules=ACTIVE)
    show = next(s for p in payload["pages"] for s in p["sections"] if s["section_type_id"] == "product_showcase")
    chicken = next(c for c in show["content"]["categories"] if c["name"] == "Chicken")
    assert chicken["meta"] == "From ₹240 per kg"
    assert {i["price"] for i in show["content"]["items"] if i["category"] == "Chicken"} == {"₹240", "₹380"}


def test_ordering_facts_say_what_the_owner_said() -> None:
    """ "UPI before we dispatch" was shown as "Pay securely when you order"; a
    courier business was "Home delivery … around All over Tamil Nadu"."""
    from platform_core.interview.site_composer import hero_badges, ordering_facts

    bp = home_food()
    bp.discovery["fulfilment.mode"] = TargetState(status="open")
    bp.discovery["fulfilment.area"] = TargetState(status="answered", summary="All over Tamil Nadu",
                                                  quote="All over Tamil Nadu by courier.")
    bp.discovery["commerce.payment"] = TargetState(status="answered", summary="UPI before dispatch.",
                                                   quote="UPI before we dispatch.")
    facts = {f["kind"]: f for f in ordering_facts(bp, "other")}
    assert facts["delivery"]["title"] == "Sent by courier"
    assert facts["delivery"]["body"] == "Across Tamil Nadu."
    assert facts["payment"]["body"] == "UPI, before dispatch."
    assert "Sent by courier" in hero_badges(bp, "other")
    assert not any("secure" in f["body"].lower() for f in facts.values())


def test_an_owner_message_after_the_build_keeps_every_drawn_visual() -> None:
    """Matching on role alone kept one visual; the rebuild redrew the other seven."""
    from platform_core.interview.models import MediaGenerationRequest
    from platform_core.services.business_interview import _carry_media

    fresh = meat()
    for key in ("hero", "category:chicken", "category:mutton", "story"):
        fresh.media_generation_requests.append(
            MediaGenerationRequest(role="visual", key=key, status="ready", asset_id=uuid4()))
    proposed = fresh.model_copy(deep=True)
    _carry_media(fresh, proposed)
    assert [r.key for r in proposed.media_generation_requests if r.role == "visual"] == [
        "hero", "category:chicken", "category:mutton", "story"]
    turn = meat()  # a turn that started before the worker finished
    _carry_media(fresh, turn)
    assert {r.key for r in turn.media_generation_requests} == {"hero", "category:chicken",
                                                              "category:mutton", "story"}


def test_places_the_owner_named_read_as_places() -> None:
    """ "Coimbatore; our home in Saibaba Colony" leaked into the pickup line."""
    from platform_core.interview.site_composer import _address, _pickup_line, _town

    bp = home_food()
    bp.known_facts["locations"] = Fact(value="Coimbatore; our home in Saibaba Colony",
                                       source="USER_STATEMENT", confirmation="confirmed")
    assert _town(bp) == "Coimbatore"
    assert _pickup_line(bp) == "Collect your order from our home in Saibaba Colony."
    assert _address(bp) == "Our home in Saibaba Colony, Coimbatore"


def test_a_supported_intent_in_other_words_is_not_called_unsupported() -> None:
    """ "pickup" was answered with "That request is not supported today"."""
    from platform_core.interview.capabilities import _gaps, canonical_intent
    from platform_core.interview.models import CapabilityIntent

    assert canonical_intent("pickup") == "delivery" and canonical_intent("Cash on delivery") == "payments"
    bp = home_food()
    bp.requested_capabilities = [
        CapabilityIntent(intent="pickup", original_request="People can also pick up from our home."),
        CapabilityIntent(intent="drone_delivery", original_request="We want drone delivery."),
        CapabilityIntent(intent="build_website", original_request="Looks good, please build it."),
    ]
    assert [g.normalized_intent for g in _gaps(bp)] == ["drone_delivery"]


def test_a_whatsapp_label_never_scrolls_to_the_menu() -> None:
    """The hero read "Order on WhatsApp" but went to #shop, beside a second WhatsApp button."""
    from platform_core.interview.models import DraftText

    bp = home_food()
    bp.website_draft.cta_label = DraftText(text="Order on WhatsApp")
    payload = compose_site(bp, direct(bp, "other"), with_draft(bp, None), business_type="other",
                           contact={"phone": "+919840012345", "whatsapp": "+919840012345"},
                           active_modules=ACTIVE)
    hero = sections(payload)["hero"]["content"]
    assert hero["cta_url"] == "#shop" and "whatsapp" not in hero["cta_label"].lower()
    assert payload["theme_hints"]["nav_cta"] == {"label": "Order on WhatsApp", "href": "whatsapp:"}


def test_one_shelf_per_thing() -> None:
    """The live meat run kept "Chicken" inside Chicken, and Crab/Squid four times over."""
    from platform_core.interview.models import GroupProposal, ItemProposal
    from platform_core.interview.taxonomy import govern_catalogue

    bp = _bp("Ishant Proteins", {"offerings": "chicken, mutton, fish, crab and squid"}, [], {}, [])
    heard = ("We sell chicken, mutton, fish, crab and squid. Chicken - whole chicken, curry cut. "
             "Fish - seer fish, pomfret. Crab and squid we clean and sell by kg.")
    govern_catalogue(bp, [
        GroupProposal(group="Chicken", items=[ItemProposal(name=n) for n in ("Chicken", "Whole chicken", "Curry cut")]),
        GroupProposal(group="Crab", items=[ItemProposal(name="Crab")]),
        GroupProposal(group="Squid", items=[ItemProposal(name="Squid")]),
        GroupProposal(group="Fish & Seafood", items=[ItemProposal(name=n) for n in
                                                     ("Seer fish", "Pomfret", "Crab", "Squid")]),
        GroupProposal(group="Crab & Squid", items=[ItemProposal(name="Crab"), ItemProposal(name="Squid")]),
    ], heard)
    assert [g.name for g in bp.taxonomy.groups] == ["Chicken", "Fish & Seafood"]
    assert [i.name for i in bp.taxonomy.groups[0].items] == ["Whole chicken", "Curry cut"]


def test_a_project_name_is_a_name_and_its_description_is_kept() -> None:
    from platform_core.interview.models import GroupProposal, ItemProposal
    from platform_core.interview.taxonomy import govern_catalogue

    bp = real_estate()
    bp.taxonomy.groups = []
    heard = "Aranya Greens - 3 BHK villas in Thalambur, ready to move."
    govern_catalogue(bp, [GroupProposal(group="Villa projects", items=[
        ItemProposal(name="Aranya Greens - 3 BHK villas in Thalambur, ready to move"),
        ItemProposal(name="Aranya Greens")])], heard)
    items = bp.taxonomy.groups[0].items
    assert [i.name for i in items] == ["Aranya Greens"]
    assert items[0].description == "3 BHK villas in Thalambur, ready to move"


def test_a_stored_untidy_catalogue_heals_on_the_next_projection() -> None:
    from platform_core.interview.taxonomy import ensure_taxonomy

    bp = real_estate()
    bp.taxonomy.groups = [
        CatalogueGroup(name="Villas", items=[CatalogueItem(name="Aranya Greens - 3 BHK villas in Thalambur"),
                                             CatalogueItem(name="Aranya Greens")]),
        CatalogueGroup(name="Crab"), CatalogueGroup(name="Seafood", items=[CatalogueItem(name="Crab")]),
    ]
    ensure_taxonomy(bp)
    assert [g.name for g in bp.taxonomy.groups] == ["Villas", "Seafood"]
    villa = bp.taxonomy.groups[0].items
    assert [(i.name, i.description) for i in villa] == [("Aranya Greens", "3 BHK villas in Thalambur")]


def test_the_final_live_details() -> None:
    """Project cards carry the owner's starting price; one place is one place;
    the story quotes what the owner said to remember."""
    from platform_core.interview.site_composer import _address, money

    assert money("1.2 crore") == "₹1.2 crore" and money("68 lakh") == "₹68 lakh"
    assert money("from 1.2 crore") == "From ₹1.2 crore" and money("From 240") == "From ₹240"
    bp = real_estate()
    bp.taxonomy.groups[0].price = "1.2 crore"
    bp.known_facts["locations"] = Fact(value="In Chennai; Chennai", source="USER_STATEMENT",
                                       confirmation="confirmed")
    assert _address(bp) == "Chennai"
    shop = sections(compose(bp))["product_showcase"]["content"]
    villas = [i for i in shop["items"] if i["category"] == "Villa projects"]
    assert villas and all(i["price"] == "From ₹1.2 crore" for i in villas)

    bp = meat()
    bp.discovery["brand.story"] = TargetState(status="answered", summary="Fresh every morning",
                                              quote="Fresh stock comes every morning. Family run for 8 years.")
    about = sections(compose(bp, WebsiteCopy(about_body="Family run for eight years.")))["about"]["content"]
    assert about["quote"] == "Fresh stock comes every morning."
