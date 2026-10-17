"""The certification owners (platform_testing.certify.owners) are complete and truthful.

Pure data checks: no database, no provider. Every scenario has its six tellings,
uses only built modules from PLAN.md §1, names real reference images, and every
telling is the same business — same phone, same place, same prices.
"""

from __future__ import annotations

import re
from pathlib import Path

from platform_core.business_types import SUPPORTED_BUSINESS_TYPES
from platform_core.catalog import taxonomy
from platform_core.catalog.modules import MODULES, is_built, storefront_modules
from platform_core.interview.planner import ASKS
from platform_testing.certify.owners import (
    ASK_IDS,
    BAKERY_PHOTOS,
    CATALOGUES,
    DISTINCT,
    MEAT_PHOTOS,
    MEDIA_GAPS,
    MISSPELLINGS,
    NOT_THE_OWNERS,
    PHOTO_DIR,
    REFS,
    ROOT,
    SCENARIOS,
    VARIANTS,
    Scenario,
    all_scenarios,
    inr,
    journeys,
    media_gap,
    scenario,
)

# PLAN.md §1, copied on purpose: owners.py drifting from the plan fails here.
PLAN_MATRIX: dict[str, tuple[str, ...]] = {
    "restaurant-delivery": ("offerings-catalog", "orders", "payments", "fulfilment"),
    "restaurant-reservations": ("offerings-catalog", "bookings"),
    "meat-shop": ("offerings-catalog", "orders", "fulfilment"),
    "bakery": ("offerings-catalog",),
    "gym": ("offerings-catalog", "memberships", "bookings", "payments"),
    "salon": ("offerings-catalog", "bookings", "payments"),
    "clinic": ("offerings-catalog", "bookings", "queue-operations", "workforce"),
    "consultant": ("offerings-catalog", "leads", "customer-relationships", "invoicing"),
    "retail": ("offerings-catalog", "inventory", "orders", "payments", "fulfilment"),
    "architecture": ("offerings-catalog", "leads", "quotes", "projects"),
    "hotel": ("offerings-catalog", "bookings", "payments"),
    "ngo": ("donations", "leads"),
}
MAX_TURN_TEXT = 4000  # InterviewCommand.text max_length
PHONE = re.compile(r"(?<!\d)[6-9]\d{4}\s?\d{5}(?!\d)")
WORD = re.compile(r"(?<![0-9a-z])[a-z]+")
NUMBER = re.compile(r"(?<![\d.])\d{2,6}(?![\d.])")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _words(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def _rich_prices(key: str) -> set[int]:
    return {price for items in CATALOGUES[key].values() for _, price, _, _ in items}


def test_twelve_scenarios_each_told_six_ways() -> None:
    assert list(SCENARIOS) == list(PLAN_MATRIX)
    for s in SCENARIOS.values():
        assert tuple(s.variants) == VARIANTS, s.key


def test_modules_are_exactly_the_plan_matrix() -> None:
    for key, modules in PLAN_MATRIX.items():
        assert SCENARIOS[key].modules == modules, key


def test_every_module_exists_is_built_and_has_its_dependencies() -> None:
    always_on = set(storefront_modules())
    for s in all_scenarios():
        assert s.modules, s.key
        assert len(set(s.modules)) == len(s.modules), s.key
        for key in s.modules:
            info = MODULES.get(key)
            assert info is not None, f"{s.key}: unknown module {key}"
            assert is_built(key) and not info.future, f"{s.key}: {key} is not built"
            missing = set(info.depends_on) - set(s.modules) - always_on
            assert not missing, f"{s.key}: {key} needs {sorted(missing)}"


def test_category_hint_is_a_taxonomy_subcategory_and_type_is_its_template() -> None:
    for s in all_scenarios():
        found = taxonomy.resolve(s.category_key, s.subcategory_key)
        assert found is not None, f"{s.key}: {s.category_hint}"
        category, sub = found
        assert (category.key, sub.key) == (s.category_key, s.subcategory_key), s.key
        assert s.business_type == category.template, s.key
        assert s.business_type in SUPPORTED_BUSINESS_TYPES, s.key


def test_reference_ids_are_real_brief_images_for_the_category() -> None:
    brief = (ROOT / "docs/visual-references/BRIEF.md").read_text(encoding="utf-8")
    for s in all_scenarios():
        assert s.reference_ids, s.key
        assert s.reference_ids == REFS[s.kind], s.key
        for ref in s.reference_ids:
            assert re.fullmatch(r"ref_\d\d", ref), ref
            assert f"({ref}.png)" in brief, ref
    assert SCENARIOS["restaurant-delivery"].reference_ids == ("ref_05", "ref_06", "ref_07")
    assert SCENARIOS["gym"].reference_ids == ("ref_08",)
    assert SCENARIOS["salon"].reference_ids == ("ref_11", "ref_12")
    assert SCENARIOS["clinic"].reference_ids == ("ref_13", "ref_14")
    assert SCENARIOS["consultant"].reference_ids == ("ref_09",)
    assert SCENARIOS["architecture"].reference_ids == ("ref_01", "ref_02", "ref_03", "ref_04")
    assert SCENARIOS["hotel"].reference_ids == ("ref_15",)
    assert SCENARIOS["ngo"].reference_ids == ("ref_10",)
    for key in ("meat-shop", "bakery", "retail"):
        assert SCENARIOS[key].reference_ids == ("ref_04", "ref_05", "ref_07")


def test_answers_are_keyed_by_the_planners_ask_ids() -> None:
    assert ASK_IDS == tuple(a.id for a in ASKS)
    for s in all_scenarios():
        for variant, script in s.variants.items():
            unknown = set(script.answers) - set(ASK_IDS)
            assert not unknown, f"{s.key}/{variant}: {sorted(unknown)}"
            assert script.opening.strip() and script.fallback.strip() and script.confirm_text.strip()
            assert all(text.strip() for text in script.answers.values()), f"{s.key}/{variant}"
            assert script.reply("contact") == script.answers.get("contact", script.fallback)
            assert script.reply("no-such-ask") == script.fallback
            for text in (script.opening, *script.answers.values()):
                assert len(text) <= MAX_TURN_TEXT, f"{s.key}/{variant}: {len(text)} chars"


def test_minimal_says_only_what_is_required_and_is_shorter_than_rich() -> None:
    for s in SCENARIOS.values():
        minimal, rich, normal = s.variants["minimal"], s.variants["rich"], s.variants["normal"]
        assert len(minimal.text()) < len(normal.text()) < len(rich.text()), s.key
        assert set(minimal.answers) <= {"identity", "contact", "phone", "conversion"}, s.key
        assert s.business_name.split()[0].lower() in minimal.opening.lower(), s.key
        assert not minimal.media


def test_bad_input_is_misspelt_but_the_same_business() -> None:
    for s in SCENARIOS.values():
        bad = s.variants["bad_input"]
        clean = s.variants["rich"].text() + s.variants["normal"].text()
        slips = _words(bad.text()) & MISSPELLINGS
        assert len(slips) >= 3, f"{s.key}: only {sorted(slips)}"
        assert not slips & _words(clean), f"{s.key}: {sorted(slips & _words(clean))} also in clean text"
        assert s.business_name.split()[0].lower() in bad.opening.lower(), s.key
        assert _digits(s.phone) in _digits(bad.text()), s.key


def test_every_telling_gives_the_same_single_phone_number() -> None:
    phones = [s.phone for s in all_scenarios()]
    assert len(set(phones)) == len(phones), "two owners share a number"
    for s in all_scenarios():
        for variant, script in s.variants.items():
            found = {_digits(p) for p in PHONE.findall(script.text())}
            assert found == {_digits(s.phone)}, f"{s.key}/{variant}: {found}"


def test_the_place_is_named_in_the_normal_telling() -> None:
    for s in all_scenarios():
        area = s.place.split(",")[0].lower()
        normal = s.variants["normal"]
        said = (normal.opening + " " + normal.answers.get("contact", "")).lower()
        assert area in said, f"{s.key}: {area}"


def test_rich_has_a_full_priced_described_catalogue() -> None:
    assert set(CATALOGUES) == set(SCENARIOS)
    for key, groups in CATALOGUES.items():
        items = [item for group in groups.values() for item in group]
        assert 3 <= len(groups) <= 5, key
        assert 8 <= len(items) <= 20, key
        rich = SCENARIOS[key].variants["rich"]
        for name, price, _unit, note in items:
            assert price > 0 and note.strip(), f"{key}: {name}"
            assert name in rich.answers["catalogue"], f"{key}: {name}"
            assert inr(price) in rich.answers["catalogue"], f"{key}: {name}"


def test_rich_carries_story_positioning_preferences_hours_and_address() -> None:
    for s in SCENARIOS.values():
        rich = s.variants["rich"]
        for ask in ("identity", "offer", "story", "look", "hours", "contact", "phone", "conversion", "photos"):
            assert rich.answers.get(ask), f"{s.key}: rich has no {ask}"
        assert len(rich.answers["story"]) > 120, s.key
        assert s.place.split(",")[0].lower() in rich.answers["contact"].lower(), s.key


def test_normal_prices_agree_with_the_rich_list() -> None:
    for key, s in SCENARIOS.items():
        said = {int(n) for n in NUMBER.findall(s.variants["normal"].answers["catalogue"])}
        assert len(said & _rich_prices(key)) >= 3, f"{key}: {sorted(said)}"


def test_photo_variants_differ_from_normal_only_in_photos() -> None:
    for s in SCENARIOS.values():
        normal = s.variants["normal"]
        for variant in ("no_photos", "owner_media"):
            script = s.variants[variant]
            rest = {k: v for k, v in script.answers.items() if k != "photos"}
            assert rest == normal.answers, f"{s.key}/{variant}"
            assert script.opening.startswith(normal.opening), f"{s.key}/{variant}"
            assert script.fallback == normal.fallback
        no_photos = s.variants["no_photos"]
        assert "no photos" in no_photos.opening.lower() and "no photos" in no_photos.answers["photos"].lower()
        assert not no_photos.media


def test_owner_media_are_real_files_that_truly_fit_the_business() -> None:
    fits = {"meat-shop": MEAT_PHOTOS, "bakery": BAKERY_PHOTOS}
    for s in SCENARIOS.values():
        rich, own = s.variants["rich"].media, s.variants["owner_media"].media
        for variant in ("normal", "bad_input", "minimal", "no_photos"):
            assert not s.variants[variant].media, f"{s.key}/{variant}"
        if s.key in MEDIA_GAPS:
            assert rich == () and own == (), s.key
            assert media_gap(s, "owner_media") == MEDIA_GAPS[s.key]
            assert media_gap(s, "rich") == MEDIA_GAPS[s.key]
            continue
        assert 3 <= len(rich) <= 6 and 3 <= len(own) <= 6, s.key
        assert set(own) <= set(rich) and len(set(rich)) == len(rich), s.key
        assert media_gap(s, "owner_media") is None
        for raw in rich:
            path = Path(raw)
            assert path.is_absolute() and path.is_file() and path.suffix == ".jpg", raw
            rel = path.relative_to(PHOTO_DIR).as_posix()
            assert rel in fits[s.key], f"{s.key}: {rel} is not a photo of this trade"
            assert rel not in NOT_THE_OWNERS, rel
    assert set(MEDIA_GAPS) == set(SCENARIOS) - {"meat-shop", "bakery"}
    for rel in (*MEAT_PHOTOS, *BAKERY_PHOTOS, *NOT_THE_OWNERS):
        assert (PHOTO_DIR / rel).is_file(), rel


def test_journeys_are_72_plus_25() -> None:
    every = journeys()
    assert len(every) == 97
    assert len([j for j in every if j[0].key in SCENARIOS]) == 72
    site_keys = [s.site_key(v) for s, v in every]
    assert len(set(site_keys)) == 97
    for s, variant in every:
        assert variant in s.variants
        assert scenario(s.key) is s


def test_distinctness_owners_differ_within_each_category() -> None:
    assert list(DISTINCT) == ["restaurant", "gym", "salon", "professional", "retail"]
    names = [s.business_name for s in all_scenarios()]
    assert len(set(names)) == len(names), "two owners share a business name"
    keys = [s.key for s in all_scenarios()]
    assert len(set(keys)) == len(keys)
    for category, group in DISTINCT.items():
        assert len(group) == 5, category
        for s in group:
            assert isinstance(s, Scenario) and tuple(s.variants) == ("normal",), s.key
            assert s.key.startswith(f"distinct-{category}-"), s.key
            assert s.variants["normal"].answers.get("story"), s.key
        for field_of in (lambda s: s.business_name, lambda s: s.place, lambda s: s.place.split(",")[0],
                         lambda s: s.variants["normal"].answers["story"],
                         lambda s: s.variants["normal"].opening):
            values = [field_of(s) for s in group]
            assert len(set(values)) == 5, f"{category}: {values}"


def test_inr_uses_indian_grouping() -> None:
    assert inr(45) == "₹45"
    assert inr(1050) == "₹1,050"
    assert inr(125000) == "₹1,25,000"
    assert inr(1200000) == "₹12,00,000"
