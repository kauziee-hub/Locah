"""Category → traits → modules, for every subcategory (Capability Universe §4, §21, §27).

Deterministic fixtures, zero model calls. What they prove:

* the family registry is well formed (unique keys, every list parses);
* every §4.2 subcategory is selectable and belongs to one §21 family;
* at a subcategory's default traits, Core is the family's Core minus only
  the demotions its traits justify (listed below, so each is a conscious
  decision), and Recommended is exactly the family's Rec;
* traits the owner changes move modules, and Storefront is always on;
* the full per-subcategory result matches the committed snapshot
  (`fixtures/module_recommendations.json`; regenerate with
  `uv run python -m platform_testing.recommendation_snapshot --write`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_core.catalog.families import BY_KEY, FAMILIES
from platform_core.catalog.modules import MODULES, STOREFRONT
from platform_core.catalog.recommendation import family_key_for, recommend
from platform_core.catalog.source_tables import parse_module_list
from platform_core.catalog.taxonomy import CATEGORIES, ORG_SHAPES, SUBCATEGORIES, TRAIT_GROUPS, TRAITS, search
from platform_testing.recommendation_snapshot import snapshot

SNAPSHOT = Path(__file__).parent / "fixtures" / "module_recommendations.json"

# Core modules a subcategory's own traits take out of its family's Core
# (MD §2 rule 3: traits decide, names don't). Each line is a real difference
# inside a §21 family, e.g. a tea shop is a "restaurant, café" but takes no
# table bookings.
TRAIT_DEMOTIONS: dict[str, set[str]] = {
    "cafe": {"bookings"}, "tea_shop": {"bookings"}, "juice_bar": {"bookings"},
    "fast_food": {"bookings"}, "food_truck": {"bookings"}, "ice_cream": {"bookings"},
    "car_wash": {"inventory"}, "detailing": {"inventory"},
    "spare_parts": {"bookings", "jobs"},
    "last_mile": {"bookings"},
    "dj": {"dispatch", "orders"}, "sound_light_rental": {"orders"}, "invitations": {"bookings", "dispatch"},
    "nursery": {"memberships"},
    "agri_inputs": {"bookings"}, "seed_supplier": {"bookings"}, "fertiliser_dealer": {"bookings"},
    "agri_equipment_dealer": {"bookings"}, "tractor_rental": {"inventory", "pos"},
    "generator_rental": {"memberships"},
    "self_storage": {"inventory"}, "document_storage": {"inventory"},
}


def _mods(text: str) -> set[str]:
    return {m for m, _ in parse_module_list(text)} - set(STOREFRONT)


def _future(m: str) -> bool:
    return bool(MODULES.get(m) and MODULES[m].future)


def test_family_registry_is_well_formed() -> None:
    assert len(FAMILIES) == 93
    assert len({f.key for f in FAMILIES}) == len(FAMILIES) == len(BY_KEY)
    for f in FAMILIES:
        assert f.label.strip() and f.group.strip(), f.key
        assert parse_module_list(f.core), f"{f.key} has no Core modules"
        # A module may appear twice with different configuration (bookings, and
        # rentals → bookings (rental)); the same module and hint twice is a typo.
        listed = parse_module_list(f.core) + parse_module_list(f.rec)
        assert len(listed) == len(set(listed)), f"{f.key} lists the same module and hint twice"


def test_every_module_named_in_a_playbook_exists_in_the_catalogue() -> None:
    for f in FAMILIES:
        for m, _ in parse_module_list(f.core) + parse_module_list(f.rec):
            assert m in MODULES or m in STOREFRONT, (f.key, m)


def test_taxonomy_shape() -> None:
    assert len(CATEGORIES) == 33  # 32 + Other (§4.2)
    assert sum(len(c.subcategories) for c in CATEGORIES) >= 420
    assert len(TRAITS) == sum(len(v) for v in TRAIT_GROUPS.values()) == 44
    assert ORG_SHAPES == ("solo", "team", "multi_location", "franchise_brand", "franchise_outlet", "enterprise")
    for c in CATEGORIES:
        for s in c.subcategories:
            assert s.traits <= TRAITS, (s.key, s.traits - TRAITS)


@pytest.mark.parametrize("phrase,expected", [
    ("pumps", "pumps"), ("valves", "valves"), ("ielts coaching", "tutor_ielts"),
    ("fmcg distributor", "fmcg_distributor"), ("animal rescue", "animal_rescue"),
    ("hydroponic farm", "hydroponics"), ("mechanic", "mechanic"), ("seo", "seo"),
])
def test_md_subcategories_are_individually_selectable(phrase: str, expected: str) -> None:
    assert search(phrase)[0]["subcategory_key"] == expected


def test_every_subcategory_has_a_family_and_every_family_is_used() -> None:
    used = set()
    for c in CATEGORIES:
        for s in c.subcategories:
            if s.key == "other":
                continue
            key = family_key_for(s.key, s.playbook)
            assert key in BY_KEY, (s.key, key)
            used.add(key)
    assert used == set(BY_KEY)


def test_default_traits_reproduce_each_family_core_and_rec() -> None:
    for c in CATEGORIES:
        for s in c.subcategories:
            if s.key == "other":
                continue
            fam = BY_KEY[family_key_for(s.key, s.playbook)]  # type: ignore[index, unused-ignore]
            rec = recommend(subcategory_key=s.key, playbook=s.playbook, traits=s.traits)
            core = {m for m in _mods(fam.core) if not _future(m)}
            want_core = core - TRAIT_DEMOTIONS.get(s.key, set())
            assert set(rec.tier("core")) == want_core, (s.key, sorted(rec.tier("core")), sorted(want_core))
            want_rec = {m for m in _mods(fam.rec) - core if not _future(m)}
            assert set(rec.tier("recommended")) == want_rec, (s.key, sorted(rec.tier("recommended")), sorted(want_rec))
            assert set(rec.tier("always")) == set(STOREFRONT)
            for demoted in TRAIT_DEMOTIONS.get(s.key, set()):
                assert rec.picks[demoted].tier == "optional"
                assert rec.picks[demoted].reason.startswith("Useful only if")


def test_owner_trait_changes_move_modules() -> None:
    s = SUBCATEGORIES["restaurant"][1]
    # Adding "I sell to businesses" switches on the §4.3 b2b modules.
    b2b = recommend(subcategory_key=s.key, playbook=s.playbook, traits=s.traits | {"b2b"},
                    default_traits=s.traits)
    for m in ("quotes", "invoicing", "ledger", "trade-network"):
        assert b2b.picks[m].tier in {"core", "recommended"}, m
    assert b2b.picks["quotes"].reason == "Because you sell to businesses"

    meat = SUBCATEGORIES["meat_shop"][1]
    no_delivery = recommend(subcategory_key=meat.key, playbook=meat.playbook,
                            traits=meat.traits - {"local_delivery"}, default_traits=meat.traits)
    assert no_delivery.picks["dispatch"].tier == "optional"
    assert no_delivery.picks["fulfilment"].tier == "core"  # still pickup

    bakery = SUBCATEGORIES["bakery"][1]
    no_counter = recommend(subcategory_key=bakery.key, playbook=bakery.playbook,
                           traits=bakery.traits - {"walk_in"}, default_traits=bakery.traits)
    assert no_counter.picks["pos"].tier == "optional"

    salon = SUBCATEGORIES["salon"][1]
    no_subs = recommend(subcategory_key=salon.key, playbook=salon.playbook,
                        traits=salon.traits - {"walk_in"}, default_traits=salon.traits)
    assert no_subs.picks["queue-operations"].tier == "optional"


def test_home_baker_and_bakery_chain_share_a_category_not_a_module_set() -> None:
    """MD §2 rule 3's own example."""
    home = SUBCATEGORIES["home_bakery"][1]
    shop = SUBCATEGORIES["bakery"][1]
    a = recommend(subcategory_key=home.key, playbook=home.playbook, traits=home.traits)
    b = recommend(subcategory_key=shop.key, playbook=shop.playbook, traits=shop.traits)
    assert "pos" in b.tier("core") and "pos" not in a.tier("core")
    assert a.tier("core") != b.tier("core")


def test_other_uses_traits_only_and_starts_as_storefront() -> None:
    empty = recommend(subcategory_key=None, playbook=None, traits=set())
    assert empty.tier("core") == [] and empty.tier("recommended") == []
    assert set(empty.tier("always")) == set(STOREFRONT)
    typed = recommend(subcategory_key=None, playbook=None, traits={"b2c", "sells_services", "booking_led"})
    assert "bookings" in typed.tier("recommended")


def test_snapshot_matches_every_subcategory() -> None:
    expected = json.loads(SNAPSHOT.read_text())
    assert snapshot() == expected, (
        "module recommendations changed; if intended, regenerate with "
        "`uv run python -m platform_testing.recommendation_snapshot --write`"
    )


def test_module_catalogue_fields_are_well_formed() -> None:
    """A missing comma turns ("one line") into characters — seen once in the browser."""
    for m in MODULES.values():
        for field_name in ("customer_can", "staff_can", "packs", "depends_on", "site", "marketplace_actions", "surfaces"):
            value = getattr(m, field_name)
            assert isinstance(value, tuple), (m.key, field_name)
            assert all(isinstance(v, str) and len(v) > 1 for v in value), (m.key, field_name, value)
        for step in m.setup:
            assert step.key and step.label
