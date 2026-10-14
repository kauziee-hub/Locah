"""Website copy and truthful sections: written freely, never evidenced falsely.

No network: the model output here is a fixture of the kinds of things a model
writes — including the stock phrases and small invented claims that make a
generated site both generic and untrustworthy.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from platform_core.entitlements.module_registry import ModuleRegistry
from platform_core.interview.capabilities import classification_seed
from platform_core.interview.models import BusinessBlueprint, Fact, Highlight, Message
from platform_core.interview.website import build_preview
from platform_core.interview.website_copy import FeatureCopy, StepCopy, WebsiteCopy, govern_copy
from platform_core.services.business_interview import public_contact
from platform_core.website.generation_plan import build_plan
from platform_core.website.section_registry import CORE_SECTION_SCHEMAS
from platform_core.website.template_registry import TEMPLATES_BY_ID

VARIANTS = {
    "hero": ["centered", "left_aligned", "image_left", "image_right", "full_width"],
    "about": ["text_only", "image_left", "image_right"], "contact": ["full", "compact"],
    "text_block": ["default", "highlighted"], "location_list": ["cards", "list"],
    "offerings_list": ["cards", "list", "grid"], "cta_band": ["centered", "left_aligned"],
    "gallery": ["grid", "masonry", "carousel"], "enquiry_form": ["default", "compact"],
    "menu_section": ["categorized", "simple"], "rooms_section": ["cards", "list"],
    "plans_section": ["cards", "comparison"], "classes_section": ["schedule", "cards"],
    "reviews_section": ["cards", "list"],
    "highlights": ["strip", "cards"], "feature_grid": ["cards", "steps", "list"],
    "category_showcase": ["image_cards", "tiles", "chips"],
    "product_showcase": ["category_boards", "commerce_grid", "menu_grid", "compact_list"],
    "fulfilment_strip": ["icons", "steps"],
    "marquee": ["band", "outline"],
}


def furniture() -> BusinessBlueprint:
    bp = BusinessBlueprint(business_id=uuid4(), identity={
        "display_name": Fact(value="Teakwood Furniture Co", source="PLATFORM", confirmation="confirmed")})
    bp.known_facts = {k: Fact(value=v, source="USER_STATEMENT", confirmation="confirmed") for k, v in {
        "description": "We run a small furniture workshop in Coimbatore.",
        "offerings": "Mostly custom wardrobes, sofas and dining tables",
        "customer_actions": "People usually WhatsApp us and come to the showroom.",
        "locations": "Coimbatore",
        "operational_characteristics": "We can deliver around the city.",
        "phone": "98765 43210",
    }.items()}
    bp.messages = [Message(role="user", text=(
        "We run a small furniture workshop in Coimbatore. Mostly custom wardrobes, sofas and "
        "dining tables. People usually WhatsApp us and come to the showroom. We can deliver "
        "around the city. Call 98765 43210."))]
    return bp


def plan_for(bp, template=None):
    active = {row["module_id"] for row in ModuleRegistry.list_modules()}
    rows = [{"id": sid, "available": True, "allowed_variants": VARIANTS[sid], "requires_module": None}
            for sid in CORE_SECTION_SCHEMAS]
    result = build_plan(business_type=classification_seed(bp), active_modules=active, capability_rows=rows)
    return replace(result, template=TEMPLATES_BY_ID[template]) if template else result


# ---------------------------------------------------------------- governance


def test_invented_numbers_claims_and_stock_phrases_are_dropped():
    bp = furniture()
    governed = govern_copy(WebsiteCopy(
        headline="Welcome to Teakwood Furniture Co",
        subheadline="Award-winning furniture since 1995, trusted by 5000 families.",
        about_body="We build wardrobes, sofas and dining tables in Coimbatore.",
        closing_headline="Your trusted partner for quality and excellence",
        contact_title="Visit the showroom",
    ), bp)
    assert governed.headline == ""  # stock phrase
    assert governed.subheadline == ""  # award, a year and a number nobody said
    assert governed.closing_headline == ""
    assert governed.about_body == "We build wardrobes, sofas and dining tables in Coimbatore."
    assert governed.contact_title == "Visit the showroom"


def test_numbers_and_claims_the_owner_did_say_are_allowed():
    bp = furniture()
    governed = govern_copy(WebsiteCopy(subheadline="Call 98765 43210 and we deliver around the city."), bp)
    assert governed.subheadline


def test_feature_titles_must_be_built_from_the_owners_words():
    bp = furniture()
    governed = govern_copy(WebsiteCopy(features=[
        FeatureCopy(title="Custom wardrobes", body="Built to fit the room you have."),
        FeatureCopy(title="Sofas", body="Certified solid teak, 10-year warranty."),
        FeatureCopy(title="Office desks", body="For your team."),  # never mentioned
    ]), bp)
    assert [f.title for f in governed.features] == ["Custom wardrobes", "Sofas"]
    assert governed.features[0].body == "Built to fit the room you have."
    assert governed.features[1].body == ""  # the claims went; the title stayed


def test_the_accent_must_be_part_of_the_headline():
    bp = furniture()
    kept = govern_copy(WebsiteCopy(headline="Wardrobes built for your room.", headline_accent="your room"), bp)
    assert kept.headline_accent == "your room"
    dropped = govern_copy(WebsiteCopy(headline="Wardrobes built for your room.", headline_accent="sofas"), bp)
    assert dropped.headline_accent == ""


def test_steps_need_the_owners_sentence_and_at_least_two():
    bp = furniture()
    governed = govern_copy(WebsiteCopy(steps=[
        StepCopy(title="WhatsApp us", quote="People usually WhatsApp us and come to the showroom."),
        StepCopy(title="We deliver", quote="We can deliver around the city."),
        StepCopy(title="Free installation", quote="We install everything for free."),  # invented
    ]), bp)
    assert [s.title for s in governed.steps] == ["WhatsApp us", "We deliver"]
    one = govern_copy(WebsiteCopy(steps=[
        StepCopy(title="WhatsApp us", quote="People usually WhatsApp us and come to the showroom."),
    ]), bp)
    assert one.steps == []


# --------------------------------------------------------- truthful sections


def _home(payload):
    return next(page for page in payload["pages"] if page["slug"] == "home")


def test_the_immediate_preview_is_specific_without_any_model():
    bp = furniture()
    payload = build_preview(bp, plan_for(bp))
    sections = _home(payload)["sections"]
    hero = sections[0]["content"]
    assert hero["eyebrow"] == "Coimbatore"
    assert hero["headline"] == "Teakwood Furniture Co"
    assert hero["headline_accent"] == "Furniture"
    grid = next(s for s in sections if s["section_type_id"] == "feature_grid")
    assert [i["title"] for i in grid["content"]["items"]] == ["Custom wardrobes", "Sofas", "Dining tables"]


def test_ai_copy_replaces_the_defaults_when_it_survives_governance():
    bp = furniture()
    copy = govern_copy(WebsiteCopy(
        headline="Wardrobes built for your room.", headline_accent="your room",
        features=[FeatureCopy(title="Custom wardrobes"), FeatureCopy(title="Dining tables")],
    ), bp)
    hero = _home(build_preview(bp, plan_for(bp), copy=copy))["sections"][0]["content"]
    assert hero["headline"] == "Wardrobes built for your room."
    assert hero["headline_accent"] == "your room"


def test_no_numbers_means_no_stats_strip_and_two_numbers_means_one():
    bp = furniture()
    payload = build_preview(bp, plan_for(bp))
    assert not any(s["section_type_id"] == "highlights" for s in _home(payload)["sections"])
    bp.highlights = [
        Highlight(value="12", label="years", quote="12 years"),
        Highlight(value="3", label="workshops", quote="3 workshops"),
    ]
    payload = build_preview(bp, plan_for(bp))
    types = [s["section_type_id"] for s in _home(payload)["sections"]]
    assert types[:2] == ["hero", "highlights"]


def test_a_single_offering_does_not_become_a_grid():
    bp = furniture()
    bp.known_facts["offerings"] = Fact(value="Custom wardrobes", source="USER_STATEMENT", confirmation="confirmed")
    payload = build_preview(bp, plan_for(bp))
    assert not any(s["section_type_id"] == "feature_grid" for s in _home(payload)["sections"])


def test_sections_the_registry_lacks_are_never_injected():
    bp = furniture()
    bp.highlights = [Highlight(value="12", label="years", quote="12 years"),
                     Highlight(value="3", label="shops", quote="3 shops")]
    active = {row["module_id"] for row in ModuleRegistry.list_modules()}
    rows = [{"id": sid, "available": sid not in {"highlights", "feature_grid"},
             "allowed_variants": VARIANTS[sid], "requires_module": None} for sid in CORE_SECTION_SCHEMAS]
    p = build_plan(business_type="retail", active_modules=active, capability_rows=rows)
    payload = build_preview(bp, p)
    kinds = {s["section_type_id"] for page in payload["pages"] for s in page["sections"]}
    assert not kinds & {"highlights", "feature_grid"}


# -------------------------------------------------------------- contact


def test_whatsapp_is_offered_only_when_the_owner_mentioned_it():
    bp = furniture()
    assert public_contact(bp) == {"phone": "+919876543210", "whatsapp": "+919876543210"}
    bp.known_facts["customer_actions"] = Fact(value="People call us.", source="USER_STATEMENT")
    bp.messages = [Message(role="user", text="Call 98765 43210.")]
    assert public_contact(bp) == {"phone": "+919876543210"}


def test_something_that_is_not_a_phone_number_is_left_out():
    bp = furniture()
    bp.known_facts["phone"] = Fact(value="call the shop", source="USER_STATEMENT")
    assert "phone" not in public_contact(bp)


# ------------------------------------------------------------- repetition


def test_the_page_says_each_thing_once():
    bp = furniture()
    sections = _home(build_preview(bp, plan_for(bp)))["sections"]
    hero = sections[0]["content"]
    stories = [s["content"]["body"] for s in sections if s["section_type_id"] in {"about", "text_block"}]
    assert hero["subheadline"] == "We run a small furniture workshop in Coimbatore."
    # The story keeps what is new and drops the line the hero already said.
    assert stories == ["We can deliver around the city."]


def test_a_story_that_only_repeats_the_hero_is_left_out():
    bp = furniture()
    del bp.known_facts["operational_characteristics"]
    kinds = [s["section_type_id"] for s in _home(build_preview(bp, plan_for(bp)))["sections"]]
    assert "about" not in kinds and "text_block" not in kinds


# ------------------------------------------- found in the live Gemini run


def test_the_phone_is_shown_as_a_number_not_the_sentence_it_was_said_in():
    bp = furniture()
    bp.known_facts["phone"] = Fact(value="ஃபோன் நம்பர் 98765-43210", source="USER_STATEMENT")
    contact = next(s for s in _home(build_preview(bp, plan_for(bp)))["sections"]
                   if s["section_type_id"] == "contact")
    assert contact["content"]["phone"] == "+91 98765 43210"


def test_an_enquiry_button_on_the_home_page_scrolls_to_contact():
    from platform_core.interview.website import _action_target

    pages = [{"slug": "home", "sections": [{"section_type_id": "hero"}, {"section_type_id": "contact"}]}]
    assert _action_target("enquire", pages)[1] == "#contact"
    pages = [{"slug": "home", "sections": []}, {"slug": "contact", "sections": [{"section_type_id": "contact"}]}]
    assert _action_target("enquire", pages)[1] == "/contact"


def test_after_personalisation_a_story_that_did_not_survive_is_not_replaced_by_raw_quotes():
    bp = furniture()
    copy = govern_copy(WebsiteCopy(headline="Wardrobes built for your room.", headline_accent="your room"), bp)
    kinds = [s["section_type_id"] for s in _home(build_preview(bp, plan_for(bp), copy=copy))["sections"]]
    assert "about" not in kinds and "text_block" not in kinds


def test_a_second_section_with_the_same_story_is_dropped_not_trimmed():
    from platform_core.interview.website import _without_repeats

    story = "We run a workshop. We deliver around the city."
    sections = [
        {"section_type_id": "about", "content": {"title": "Our story", "body": story}},
        {"section_type_id": "text_block", "content": {"title": "Our story", "body": story}},
    ]
    assert [s["section_type_id"] for s in _without_repeats(sections)] == ["about"]


def test_whatsapp_said_in_tamil_script_counts():
    bp = furniture()
    bp.known_facts["customer_actions"] = Fact(value="கஸ்டமர்ஸ் வாட்ஸ்அப் பண்ணிட்டு வருவாங்க", source="USER_STATEMENT")
    bp.messages = [Message(role="user", text="Phone 98765 43210.")]
    assert public_contact(bp)["whatsapp"] == "+919876543210"


def test_the_profile_contract_keeps_the_whatsapp_number():
    """It was silently dropped here, so the site never showed WhatsApp."""
    from platform_core.validation.business_settings import validate_contact

    assert validate_contact({"phone": "+919876543210", "whatsapp": "+919876543210"}) == {
        "phone": "+919876543210", "whatsapp": "+919876543210"}


def test_a_restaurant_without_its_menu_online_still_gets_a_warm_site():
    """Live: a Chettinad restaurant without the catalogue was dressed in navy."""
    from platform_core.interview.design_strategy import select_contextual_template

    bp = furniture()
    bp.known_facts["description"] = Fact(value="We're a South Indian restaurant in Chennai.", source="USER_STATEMENT")
    bp.known_facts["offerings"] = Fact(value="Chettinad lamb, Kerala-style seafood and filter coffee", source="USER_STATEMENT")
    bp.known_facts["classification"] = Fact(value="restaurant", source="USER_STATEMENT")
    rows = [{"id": sid, "available": True, "allowed_variants": VARIANTS[sid], "requires_module": None}
            for sid in CORE_SECTION_SCHEMAS]
    p = build_plan(business_type="restaurant", active_modules=set(), capability_rows=rows)
    chosen = select_contextual_template(bp, p)
    assert chosen.personality == "warm" and not chosen.required_modules
