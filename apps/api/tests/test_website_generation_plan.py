"""The fence around AI website generation.

No database. Two claims are under test and they are the whole point of the
module: generation starts from a real template rather than a blank page, and a
business only ever gets sections it is actually entitled to — whether the
sections came from the model, from completion, or from the deterministic
fallback.

The capability rows here are shaped exactly as
`WebsiteCompositionService.available_section_types` returns them, which is what
the service feeds in. Keeping that shape is deliberate: if that method's
contract changes, these tests should be the thing that notices.
"""

from __future__ import annotations

from typing import Any

from platform_core.website.generation_plan import (
    PERSONALITIES,
    build_plan,
    describe_plan_for_prompt,
    enforce_capabilities,
    normalise_theme,
    reference_composition,
    select_template,
)
from platform_core.website.template_registry import TEMPLATES_BY_ID

# Every section type the platform seeds, with the module each one belongs to.
# Mirrors `infra/supabase/seed/00_platform.sql`.
_SECTION_MODULES: dict[str, str | None] = {
    "hero": None,
    "about": None,
    "text_block": None,
    "location_list": None,
    "gallery": None,
    "contact": None,
    "cta_band": None,
    "offerings_list": "offerings-catalog",
    "menu_section": "offerings-catalog",
    "rooms_section": "offerings-catalog",
    "plans_section": "offerings-catalog",
    "classes_section": "offerings-catalog",
    "reviews_section": "reviews",
    "enquiry_form": "leads",
    # Filled only from the owner's own words and numbers; no module behind them.
    "highlights": None,
    "feature_grid": None,
    # The owner's own catalogue and ordering facts, composed by the creative
    # composer; a live record is never read, so no module.
    "category_showcase": None,
    "product_showcase": None,
    "fulfilment_strip": None,
    # The business's own short words, moving (experience layer); no module.
    "marquee": None,
}


def _rows(active: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": section_id,
            "label": section_id.replace("_", " ").title(),
            "allowed_variants": ["default"],
            "requires_module": module,
            "available": module is None or module in active,
            "unavailable_reason": None
            if module is None or module in active
            else "module_not_active",
        }
        for section_id, module in _SECTION_MODULES.items()
    ]


def _plan(business_type: str, active: set[str]):
    return build_plan(
        business_type=business_type,
        active_modules=active,
        capability_rows=_rows(active),
    )


def test_the_fixture_still_mirrors_every_platform_section_type() -> None:
    """A new section type must be classified here, not silently untested.

    Without this, adding a module-bound section type would leave the fence
    tested against an inventory that no longer matches the platform's, and
    every assertion below would keep passing while covering less.
    """
    from platform_core.website.section_registry import ALLOWED_SECTION_TYPE_IDS

    assert set(_SECTION_MODULES) == set(ALLOWED_SECTION_TYPE_IDS)


# --------------------------------------------------------------- selection


def test_restaurant_with_a_catalogue_gets_the_menu_led_template() -> None:
    template, reason = select_template(
        business_type="restaurant", active_modules={"offerings-catalog"}
    )
    assert template.id == "menu-first"
    assert reason == "it suits a restaurant"


def test_a_template_that_needs_a_module_the_business_lacks_is_not_chosen() -> None:
    """The suited template is unaffordable, so the reference must be another one.

    Choosing it anyway would have the model personalise a menu that the fence
    deletes a moment later, leaving a site whose copy talks about a menu that
    is not on the page.
    """
    template, reason = select_template(business_type="restaurant", active_modules=set())
    assert template.id != "menu-first"
    assert not set(template.required_modules)
    # And it says what was given up, because that is the actionable half.
    assert "Menu First" in reason and "offerings-catalog" in reason


def test_an_unknown_business_type_still_gets_a_real_template() -> None:
    template, reason = select_template(business_type="taxidermist", active_modules=set())
    assert template.id in TEMPLATES_BY_ID
    assert reason


def test_every_reason_completes_the_sentence_the_prompt_puts_it_in() -> None:
    """The prompt reads "It was chosen because {reason}." — so each one needs a subject.

    Without this the blocked-module branch produced "because it Menu First
    would suit this business better", which is the kind of sentence that tells
    a model the instructions were assembled carelessly.
    """
    seen = set()
    for business_type in ("restaurant", "gym", "hotel", "taxidermist", None):
        for active in (set(), {"offerings-catalog"}, {"offerings-catalog", "leads"}):
            _, reason = select_template(business_type=business_type, active_modules=active)
            seen.add(reason)
    for reason in seen:
        sentence = f"It was chosen because {reason}."
        assert not sentence.startswith("It was chosen because it it"), sentence
        # A reason either starts with its own pronoun or names a template.
        assert reason.startswith("it ") or reason[0].isupper(), reason


def test_selection_never_returns_a_template_the_business_cannot_afford() -> None:
    for business_type in ("restaurant", "cafe", "gym", "hotel", "salon", "retail", None):
        for active in (set(), {"leads"}, {"offerings-catalog"}, {"offerings-catalog", "leads"}):
            template, _ = select_template(business_type=business_type, active_modules=active)
            assert set(template.required_modules) <= active, (business_type, active)


# ------------------------------------------------------------- composition


def test_the_reference_drops_sections_the_business_cannot_have() -> None:
    plan = _plan("professional_service", active={"offerings-catalog"})
    composition = reference_composition(plan)
    flat = [s["section_type_id"] for page in composition for s in page["sections"]]
    assert flat, "a reference with no sections is not a reference"
    # `leads` is off, so the enquiry form must not be described to the model.
    assert "enquiry_form" not in flat


def test_every_page_in_a_reference_keeps_at_least_one_section() -> None:
    for active in (set(), {"leads"}, {"offerings-catalog"}, {"offerings-catalog", "leads"}):
        plan = _plan("restaurant", active=active)
        for page in reference_composition(plan):
            assert page["sections"], (active, page["slug"])


def test_the_prompt_names_the_template_and_both_sides_of_the_fence() -> None:
    plan = _plan("gym", active={"offerings-catalog"})
    prompt = describe_plan_for_prompt(plan)
    assert plan.template.name in prompt
    assert "hero" in prompt
    # What it may use, and what it may not, with the reason.
    assert "AVAILABLE SECTION TYPES" in prompt
    assert "enquiry_form (needs leads)" in prompt
    assert plan.template.primary_color in prompt


# ------------------------------------------------------------------ fence


def test_a_section_whose_module_is_off_is_removed_from_the_answer() -> None:
    plan = _plan("gym", active=set())
    payload = {
        "pages": [
            {
                "slug": "home",
                "title": "Home",
                "page_type": "home",
                "sections": [
                    {"section_type_id": "hero", "content": {"headline": "Iron"}},
                    {"section_type_id": "plans_section", "content": {"title": "Plans"}},
                ],
            }
        ],
        "navigation": [{"label": "Home", "path": "/"}],
        "theme_hints": {},
    }
    cleaned, dropped = enforce_capabilities(payload, plan)
    kept = [s["section_type_id"] for s in cleaned["pages"][0]["sections"]]
    assert kept == ["hero"]
    assert dropped == [
        {
            "page": "home",
            "section_type_id": "plans_section",
            "requires_module": "offerings-catalog",
        }
    ]


def test_a_page_emptied_by_the_fence_takes_its_navigation_entry_with_it() -> None:
    """A nav link to a page with nothing on it is worse than one fewer page."""
    plan = _plan("hotel", active=set())
    payload = {
        "pages": [
            {
                "slug": "home",
                "title": "Home",
                "page_type": "home",
                "sections": [{"section_type_id": "hero", "content": {"headline": "Stay"}}],
            },
            {
                "slug": "rooms",
                "title": "Rooms",
                "page_type": "rooms",
                "sections": [{"section_type_id": "rooms_section", "content": {"title": "Rooms"}}],
            },
        ],
        "navigation": [
            {"label": "Home", "path": "/"},
            {"label": "Rooms", "path": "/rooms"},
        ],
        "theme_hints": {},
    }
    cleaned, dropped = enforce_capabilities(payload, plan)
    assert [p["slug"] for p in cleaned["pages"]] == ["home"]
    assert [n["path"] for n in cleaned["navigation"]] == ["/"]
    assert {"page": "rooms", "section_type_id": "", "requires_module": "page_empty"} in dropped


def test_a_fully_entitled_business_loses_nothing() -> None:
    plan = _plan("restaurant", active={"offerings-catalog", "leads"})
    payload = {
        "pages": [
            {
                "slug": "home",
                "title": "Home",
                "page_type": "home",
                "sections": [
                    {"section_type_id": "hero", "content": {"headline": "Ragi House"}},
                    {"section_type_id": "menu_section", "content": {"title": "Menu"}},
                    {"section_type_id": "enquiry_form", "content": {"title": "Ask"}},
                ],
            }
        ],
        "navigation": [{"label": "Home", "path": "/"}],
        "theme_hints": {},
    }
    cleaned, dropped = enforce_capabilities(payload, plan)
    assert dropped == []
    assert len(cleaned["pages"][0]["sections"]) == 3


def test_the_fence_leaves_a_payload_alone_rather_than_writing_an_empty_website() -> None:
    """Pruning everything should be impossible; if it happens, do not persist it.

    Returning the payload untouched hands the decision back to the caller's
    existing fallback rather than replacing the owner's draft with nothing.
    """
    plan = _plan("gym", active=set())
    payload = {
        "pages": [
            {
                "slug": "home",
                "title": "Home",
                "page_type": "home",
                "sections": [{"section_type_id": "plans_section", "content": {}}],
            }
        ],
        "navigation": [],
        "theme_hints": {},
    }
    cleaned, dropped = enforce_capabilities(payload, plan)
    assert cleaned["pages"], "an empty website is never the right answer"
    assert dropped


# ------------------------------------------------------------------ theme


def test_an_invented_personality_falls_back_to_the_baseline() -> None:
    """A personality outside the five matches no selector and unstyles the site."""
    plan = _plan("restaurant", active={"offerings-catalog"})
    baseline = plan.theme_baseline()
    theme = normalise_theme({"personality": "rustic-artisanal"}, baseline=baseline)
    assert theme["personality"] == plan.template.personality
    assert theme["personality"] in PERSONALITIES


def test_a_personality_the_stylesheet_implements_is_kept() -> None:
    plan = _plan("restaurant", active={"offerings-catalog"})
    baseline = plan.theme_baseline()
    for personality in sorted(PERSONALITIES):
        theme = normalise_theme({"personality": personality}, baseline=baseline)
        assert theme["personality"] == personality


def test_a_colour_that_is_not_a_colour_falls_back_to_the_baseline() -> None:
    plan = _plan("gym", active={"offerings-catalog"})
    theme = normalise_theme(
        {"primary_color": "deep charcoal", "accent_color": "#F0A"},
        baseline=plan.theme_baseline(),
    )
    assert theme["primary_color"] == plan.template.primary_color
    assert theme["accent_color"] == "#f0a"


def test_a_model_chosen_colour_survives_when_it_is_a_real_colour() -> None:
    """Personalisation is the point — governance must not flatten it."""
    plan = _plan("cafe", active={"offerings-catalog"})
    theme = normalise_theme(
        {"primary_color": "#2B4C3F", "personality": "premium"},
        baseline=plan.theme_baseline(),
    )
    assert theme["primary_color"] == "#2b4c3f"
    assert theme["personality"] == "premium"


# ------------------------------------------------------------- provenance


def test_a_draft_is_stamped_with_a_template_only_when_one_was_used() -> None:
    """The picker reads this to say "your site was built from this".

    The deterministic fallback builds from the business type and never looks at
    a template, so stamping one on it would make the picker say something
    untrue about work the owner is looking at.
    """
    plan = _plan("cafe", active={"offerings-catalog"})
    baseline = plan.theme_baseline()

    personalised = normalise_theme({}, baseline=baseline, template_id=plan.template.id)
    assert personalised["template_id"] == plan.template.id

    fallback = normalise_theme({}, baseline=baseline)
    assert "template_id" not in fallback


def test_a_template_id_cannot_be_smuggled_in_through_the_theme() -> None:
    """A model that returns a template_id is claiming a provenance it cannot know."""
    plan = _plan("cafe", active={"offerings-catalog"})
    theme = normalise_theme({"template_id": "menu-first"}, baseline=plan.theme_baseline())
    assert "template_id" not in theme


def test_the_baseline_carries_no_provenance_of_its_own() -> None:
    plan = _plan("restaurant", active={"offerings-catalog"})
    assert "template_id" not in plan.theme_baseline()
