"""The whole range, captured: typed menus and price lists, and what the owner
says about them — read by rule, with the model down, never guessed.

Pure: no database, no model.
"""

from __future__ import annotations

from uuid import uuid4

from platform_core.interview import catalogue_capture as cc
from platform_core.interview.models import (
    BusinessBlueprint,
    CatalogueGroup,
    CatalogueItem,
    CategorySeed,
    Fact,
)


def _names(groups: list[cc.ReadGroup]) -> list[tuple[str, str, str]]:
    return [(i.name, i.price, i.unit) for g in groups for i in g.items]


def test_a_comma_list_of_dishes_with_prices() -> None:
    groups = cc.read_priced_list("Idli 40, Masala dosa 70, Pongal 60, Filter coffee ₹25")
    assert _names(groups) == [("Idli", "40", ""), ("Masala dosa", "70", ""), ("Pongal", "60", ""),
                              ("Filter coffee", "25", "")]


def test_one_dish_per_line_with_headings() -> None:
    text = "Starters\nPaneer 65 - 180\nChilli chicken 220\n\nMains:\nVeg biryani 160\nMutton biryani ₹ 320"
    groups = cc.read_priced_list(text)
    assert [g.name for g in groups] == ["Starters", "Mains"]
    starters = {i.name: i for i in groups[0].items}
    # The dish keeps its own number; the price is the last one.
    assert starters["Paneer 65"].price == "180"
    assert starters["Chilli chicken"].diet == "non_veg"  # named for its meat
    assert {i.name for i in groups[1].items} == {"Veg biryani", "Mutton biryani"}


def test_a_heading_with_its_list_on_the_same_line() -> None:
    groups = cc.read_priced_list("Podis: Idli podi 120, Paruppu podi 140. Pickles: Lemon pickle 150 (veg)")
    assert [(g.name, [i.name for i in g.items]) for g in groups] == [
        ("Podis", ["Idli podi", "Paruppu podi"]), ("Pickles", ["Lemon pickle"])]
    assert groups[1].items[0].diet == "veg"


def test_units_sizes_and_durations_are_kept_with_the_price() -> None:
    meat = cc.read_priced_list("Chicken curry cut 240/kg, Boneless 380 per kg")
    assert _names(meat) == [("Chicken curry cut", "240", "per kg"), ("Boneless", "380", "per kg")]
    salon = cc.read_priced_list("Haircut 300 (30 min), Hair spa 1200 (60 mins), Facial 900 (45-60 min)")
    assert _names(salon) == [("Haircut", "300", "30 min"), ("Hair spa", "1200", "60 min"),
                             ("Facial", "900", "45–60 min")]
    sizes = cc.read_priced_list("Mutton biryani half 220, full 400")
    assert _names(sizes) == [("Mutton biryani", "220 / 400", "half / full")]


def test_hours_phone_numbers_and_years_are_not_a_menu() -> None:
    text = ("We are open 9 am to 10 pm, call 98940 12345. Running since 2009 with 3 branches. "
            "Delivery within 5 km.")
    assert cc.read_priced_list(text) == []


def _kitchen() -> BusinessBlueprint:
    bp = BusinessBlueprint(business_id=uuid4(), identity={
        "display_name": Fact(value="Amma's Kitchen", source="PLATFORM", confirmation="confirmed")})
    bp.category = CategorySeed(category_key="food_service", label="Restaurant", source="owner_picked",
                               subcategory_key="restaurant")
    bp.taxonomy.groups = [CatalogueGroup(name="Biryani", items=[
        CatalogueItem(name="Chicken biryani", price="220"), CatalogueItem(name="Veg biryani", price="160"),
        CatalogueItem(name="Paneer biryani", price="190"), CatalogueItem(name="Egg biryani", price="170")])]
    return bp


def test_an_answer_to_send_me_your_menu_lands_in_the_catalogue() -> None:
    bp = _kitchen()
    changed = cc.capture(bp, "Mutton biryani 320", ("offerings.catalogue",))
    assert changed == 1
    biryani = bp.taxonomy.groups[0]
    assert [i.name for i in biryani.items][-1] == "Mutton biryani"  # its own group, by its name
    assert biryani.items[-1].diet == "non_veg"
    # In passing, one priced phrase is not a list.
    assert cc.capture(bp, "We have been doing this for 12 years", ()) == 0


def test_all_veg_except_marks_every_dish_and_bestsellers_are_featured() -> None:
    bp = _kitchen()
    cc.read_traits(bp, "Chicken biryani and egg biryani are non-veg, the rest are veg. "
                       "Bestsellers are chicken biryani and paneer biryani.")
    by_name = {i.name: i for i in bp.taxonomy.groups[0].items}
    assert by_name["Chicken biryani"].diet == "non_veg"
    assert by_name["Egg biryani"].diet == "non_veg"
    assert by_name["Veg biryani"].diet == "veg" and by_name["Paneer biryani"].diet == "veg"
    assert by_name["Chicken biryani"].tag == "Bestseller" and by_name["Paneer biryani"].tag == "Bestseller"
    assert not by_name["Veg biryani"].tag


def test_pure_veg_marks_everything_and_nothing_is_tagged_without_being_named() -> None:
    bp = _kitchen()
    bp.taxonomy.groups[0].items = [i for i in bp.taxonomy.groups[0].items if "Chicken" not in i.name
                                   and "Egg" not in i.name]
    cc.read_traits(bp, "We are a pure veg restaurant. Our favourites are the ones people love.")
    items = bp.taxonomy.groups[0].items
    assert all(i.diet == "veg" for i in items)
    assert not any(i.tag for i in items)


def test_the_question_is_asked_in_the_trade_own_words() -> None:
    bp = _kitchen()
    assert "menu" in cc.ask(bp, "en").lower()
    assert cc.completeness(bp) == "partial"  # four dishes is not a menu yet
    bp.taxonomy.groups[0].items.append(CatalogueItem(name="Mutton biryani", price="320"))
    assert cc.completeness(bp) == "sufficient"


def test_traits_reach_the_website_from_the_owner_or_their_document() -> None:
    assert cc.item_traits(CatalogueItem(name="Lemon pickle", diet="veg", spice="hot", tag="Bestseller")) == {
        "diet": "veg", "spice": "hot", "tag": "Bestseller"}
    assert cc.item_traits(CatalogueItem(name="Fish fry", attributes="Non-veg, spicy")) == {
        "diet": "non_veg", "spice": "hot"}


# ------------------------------------------------- the conversation itself


def test_a_restaurant_is_asked_for_its_menu_before_anything_else_about_it() -> None:
    import asyncio

    from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine
    from platform_testing.interview_eval import Down

    bp = _kitchen()
    bp.taxonomy.groups = []
    Engine.open(bp)

    async def talk(text: str) -> BusinessBlueprint:
        return await Engine.turn(bp, text, provider=Down(), business_type="restaurant")

    # The model is down: only rules read these messages.
    bp = asyncio.run(talk("We are a South Indian restaurant in RS Puram, Coimbatore. People order on WhatsApp. "
                          "We deliver within 5 km."))
    assert bp.asks[-1].ask == "catalogue"
    assert "menu" in bp.messages[-1].text.lower()

    bp = asyncio.run(talk("Tiffin: Idli 40, Masala dosa 70\nBiryani: Chicken biryani 220, Veg biryani 160"))
    groups = {g.name: [(i.name, i.price) for i in g.items] for g in bp.taxonomy.groups}
    assert groups == {"Tiffin": [("Idli", "40"), ("Masala dosa", "70")],
                      "Biryani": [("Chicken biryani", "220"), ("Veg biryani", "160")]}
    # The typed menu said what is sold too: never asked again.
    assert bp.discovery["offerings.main"].status == "answered"
    assert bp.asks[-1].ask == "traits"
    assert "non-veg" in bp.messages[-1].text.lower()

    bp = asyncio.run(talk("Chicken biryani sells the most. Only chicken biryani is non-veg."))
    items = {i.name: i for g in bp.taxonomy.groups for i in g.items}
    assert items["Chicken biryani"].tag == "Bestseller" and items["Chicken biryani"].diet == "non_veg"
    assert all(items[n].diet == "veg" for n in ("Idli", "Masala dosa", "Veg biryani"))


def test_a_clinic_is_not_held_up_for_a_price_list() -> None:
    from platform_core.interview.coverage import importance, profile

    bp = BusinessBlueprint(business_id=uuid4())
    bp.category = CategorySeed(category_key="healthcare", subcategory_key="dental", label="Dental clinic")
    assert importance("offerings.catalogue", profile(bp), bp) == "enrichment"
