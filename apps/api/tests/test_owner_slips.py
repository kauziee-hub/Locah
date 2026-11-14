"""An owner who types fast, with slips, still gets their own business.

Found on a real owner run (2026-11-13, restaurant-delivery / bad_input): "pepper
vine kichen … we make kerala food biriyani appam stew meals" was filed as
"other", so its dishes were imported as bookable services and the live website
could not take an order; the menu read "Chiken biriyani" and "Stew chiken 240
veg"; "appam 50 for 2" and "duck 420" lost their prices.
"""

from __future__ import annotations

import pytest
from platform_core.catalog.taxonomy import infer_from_text, respell
from platform_core.interview.catalogue_capture import read_priced_list
from platform_core.interview.spelling import fix_words
from platform_testing.certify.owners import all_scenarios

KITCHEN = ("hi this is pepper vine kichen in kadavantra kochi, we make kerala food biriyani appam stew meals "
           "duck rost etc and we deliver also near by areas, ordr online pay online that is what i want")


def _kind(text: str) -> str | None:
    found = infer_from_text(text)
    return found[0] if found and found[1] >= 0.72 else None


# ------------------------------------------------------------------ what kind of business
@pytest.mark.parametrize(("said", "kind"), [
    (KITCHEN, "restaurant"),
    ("we run a small resturant in anna nagar", "restaurant"),
    ("bekary shop cakes puffs bread", "bakery"),
    ("gymm with personal training", "gym"),
    ("tution centre for 10th and 12th", "tuition_centre"),
    ("grocary store home delivery", "grocery"),
    ("mobail shop repair and accessories", "mobile_store"),
    ("physiotherpy centre", "physiotherapy"),
    ("i do wedding photografy", "wedding_photographer"),
    ("tiffin centre idli dosa pongal morning only", "restaurant"),
    ("we make cakes on order from home", "home_bakery"),
])
def test_a_misspelt_or_unnamed_trade_is_still_the_trade(said: str, kind: str) -> None:
    assert _kind(said) == kind


@pytest.mark.parametrize(("said", "kind"), [
    # What the business designs, sits beside or buys from is not what it is.
    ("Laterite Studio is an architecture and interiors practice in Fort Kochi. We design homes, small hotels "
     "and restorations across Kerala", "architect"),
    ("Mylapore Tiffin Room — idli, dosa, pongal and filter coffee, a small tiffin place near the "
     "Kapaleeshwarar temple, Mylapore.", "restaurant"),
    ("Velan Fresh Meats is our chicken, mutton and seafood shop on GST Road. Chicken comes from one supplier "
     "farm in Padappai every morning", "meat_shop"),
    ("Nalam Family Clinic is a family practice on OMR — general medicine, children's care, and a small "
     "in-house lab for blood tests.", "clinic"),
    ("I run Anjali Menon Consulting. I help family-run businesses and small D2C brands fix pricing, margins "
     "and growth: audits, retainers and team workshops.", "business_consultant"),
])
def test_what_an_owner_mentions_is_not_what_they_are(said: str, kind: str) -> None:
    assert _kind(said) == kind


def test_clean_sentences_are_left_alone() -> None:
    """The spelling repair fires only on real slips: across every certification
    persona it changes a handful of words, each one a misspelt trade word."""
    changed: set[tuple[str, str]] = set()
    for scenario in all_scenarios():
        for script in scenario.variants.values():
            for text in (script.opening, *script.answers.values()):
                before = " ".join(text.casefold().split())
                for was, now in zip(respell(before).split(), respell(respell(before)).split()):
                    assert was == now  # settled in one pass
                tokens = [t for t in __import__("re").sub(r"[^a-z0-9\s&/+-]", " ", before).split()]
                for token in tokens:
                    fixed = respell(token)
                    if fixed and fixed != token and " " not in fixed:
                        changed.add((token, fixed))
    real_words = {"stuff", "message", "still", "sprouts", "properly", "parents", "points", "designed", "trained",
                  "reports", "tired", "calling", "turning", "tasting", "scale", "roles", "sides", "noon"}
    assert not {was for was, _ in changed} & real_words
    assert len(changed) <= 20, sorted(changed)


def test_every_persona_still_reads_as_its_own_kind() -> None:
    """The six tellings of each certification business stay in the same family."""
    family = {
        "restaurant-delivery": {"restaurant", "cloud_kitchen", None},
        "meat-shop": {"meat_shop"},
        "bakery": {"bakery"},
        "gym": {"gym"},
        "salon": {"salon"},
        "hotel": {"resort"},
    }
    for scenario in all_scenarios():
        allowed = family.get(scenario.key)
        if not allowed:
            continue
        for variant, script in scenario.variants.items():
            assert _kind(script.opening) in allowed, (scenario.key, variant, _kind(script.opening))


# ------------------------------------------------------------------ the menu, typed in one breath
def _read(text: str, known: tuple[str, ...] = ()) -> list[tuple[str, str, str]]:
    return [(item.name, item.price, item.unit) for group in read_priced_list(text, known) for item in group.items]


def test_a_price_list_typed_without_commas_is_every_item_with_its_price() -> None:
    read = _read("chiken biriyani 280 mutton 360 appam 50 for 2, stew chiken 240 veg 180, meals 180, "
                 "fish meals 260 duck 420... rest i will tel later", ("Duck roast",))
    assert read == [
        ("Chicken biriyani", "280", ""), ("Mutton biriyani", "360", ""), ("Appam", "50", "for 2"),
        ("Stew chicken", "240", ""), ("Stew veg", "180", ""), ("Meals", "180", ""),
        ("Fish meals", "260", ""), ("Duck roast", "420", ""),
    ]


def test_sizes_measures_and_numbers_in_names_survive_a_run_on_list() -> None:
    assert _read("mutton biryani half 220 full 400 chicken 65 180 parotta 15") == [
        ("Mutton biryani", "220 / 400", "half / full"), ("Chicken 65", "180", ""), ("Parotta", "15", "")]
    assert _read("haircut 30 min 250 facial 60 min 800 bleech 300") == [
        ("Haircut", "250", "30 min"), ("Facial", "800", "60 min"), ("Bleach", "300", "")]
    assert _read("chicken 240/kg mutton 780/kg prawns 550 per kg") == [
        ("Chicken", "240", "per kg"), ("Mutton", "780", "per kg"), ("Prawns", "550", "per kg")]
    assert _read("monthly 1500 quaterly 4000 yerly 14000 personel traning 6000 per month") == [
        ("Monthly", "1500", ""), ("Quarterly", "4000", ""), ("Yearly", "14000", ""),
        ("Personal training", "6000", "per month")]


def test_a_sentence_that_is_not_a_price_list_is_not_read_as_one() -> None:
    assert _read("we are open 9 to 9 and have 12 staff, call 98470 21456") == []


def test_a_paneer_tikka_is_not_meat_and_a_slipped_chicken_is() -> None:
    items = {i.name: i.diet for g in read_priced_list("panner tikka 180, butter chiken 220, stew veg 150")
             for i in g.items}
    assert items == {"Paneer tikka": "", "Butter chicken": "non_veg", "Stew veg": "veg"}


def test_slips_are_put_right_and_regional_spellings_are_kept() -> None:
    assert fix_words("Chiken biriyani and duck rost") == "Chicken biriyani and duck roast"
    assert fix_words("Parotta, porotta, kabab") == "Parotta, porotta, kabab"
    assert fix_words("hair straitening, montly membarship") == "hair straightening, monthly membership"


def test_a_bare_word_that_names_the_shelf_is_not_a_dish_without_a_price() -> None:
    from uuid import uuid4

    from platform_core.interview.catalogue_capture import respell as respell_catalogue
    from platform_core.interview.models import BusinessBlueprint, CatalogueGroup, CatalogueItem

    bp = BusinessBlueprint(business_id=uuid4())
    bp.taxonomy.groups = [
        CatalogueGroup(name="Kerala food", items=[
            CatalogueItem(name="Biriyani"), CatalogueItem(name="Appam"), CatalogueItem(name="Stew")]),
        CatalogueGroup(name="Biriyani", items=[
            CatalogueItem(name="Chiken biriyani", price="280"), CatalogueItem(name="Mutton biriyani", price="360")]),
        CatalogueGroup(name="Stew", items=[
            CatalogueItem(name="Chicken stew", price="240"), CatalogueItem(name="Veg stew", price="180")]),
    ]
    respell_catalogue(bp)
    names = [[i.name for i in g.items] for g in bp.taxonomy.groups]
    assert names == [["Appam"], ["Chicken biriyani", "Mutton biriyani"], ["Chicken stew", "Veg stew"]]


def test_both_means_delivery_and_pickup_only_as_the_answer_to_that_question() -> None:
    from platform_core.interview import reader as rd

    assert rd.fulfilment_modes("both") == ["delivery", "pickup"]
    assert rd.fulfilment_modes("yes both we do") == ["delivery", "pickup"]
    salon = ("amber room salon rs puram cbe, we do al types of haircut nd colur, ladies gents both, facial, "
             "bridel makeup also, apointment booking venum")
    assert rd.fulfilment_modes(salon) == []
    assert rd.fulfilment_modes("veg and non veg both") == []


def test_who_a_business_serves_and_how_it_was_said_are_not_shelves() -> None:
    from platform_core.interview.taxonomy import normalise_name

    assert normalise_name("Ladies gents both") == ("", False)
    assert normalise_name("Bridal makeup also") == ("Bridal makeup", False)
    assert normalise_name("Facial too") == ("Facial", False)
    assert normalise_name("Kids") == ("Kids", False)  # a clothes shop's own shelf
    assert normalise_name("Kids wear") == ("Kids wear", False)
    assert fix_words("Keratine") == "Keratin"


def test_a_days_own_closing_time_said_without_a_comma() -> None:
    """A gym's live site said "Mon–Sat closed; Sun 6 am–10 pm" for "6am-10pm sunday till 12"."""
    from platform_core.interview import hours

    week = hours.parse("6am-10pm sunday till 12", asked=True)
    assert week is not None
    assert week["mon"] == [["06:00", "22:00"]] and week["sat"] == [["06:00", "22:00"]]
    assert week["sun"] == [["06:00", "12:00"]]
    kept = hours.parse("9 to 6 Monday to Saturday", asked=True)
    assert kept is not None and kept["sun"] == [] and kept["mon"] == [["09:00", "18:00"]]


def test_chat_shorthand_is_written_out_for_the_page_and_facts_are_left_alone() -> None:
    from platform_core.interview.spelling import for_the_page

    assert for_the_page("ppl shud book trial first then join") == "People should book trial first then join"
    assert for_the_page("hsr layout blr") == "HSR layout Bengaluru"
    assert for_the_page("rs 500 for 5 min walk") == "Rs 500 for 5 min walk"
