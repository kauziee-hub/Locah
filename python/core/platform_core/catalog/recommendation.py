"""Recommendation rules: traits → Core / Recommended / Optional modules
(Capability Universe §4.3, §4.4, §21, §24 #2).

A pure function, fixture-tested for every subcategory (§27). No AI.

How the three sources of truth combine
--------------------------------------
* **Category guides.** Each subcategory belongs to one §21 sector family. At the
  subcategory's default traits, the family's Core and Rec lists are the answer
  (the fixtures prove it for every subcategory).
* **Traits decide.** Every module has a requirement over traits ("counter
  billing needs walk-in customers"). A family module whose requirement fails
  for this business's traits is not pre-ticked — it drops to Optional, with the
  reason. A trait the owner adds switches its modules on as Recommended
  (§4.3 "Switches on"); a trait the owner removes takes them away.
* **Owner choice wins.** This function only recommends. Enabling a module is
  the owner's act, and enabled ≠ configured ≠ ready (see readiness).

Storefront modules (§5) are always on and are reported separately.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from platform_core.catalog.families import BY_KEY as FAMILIES
from platform_core.catalog.families import Family
from platform_core.catalog.modules import MODULES, STOREFRONT, is_built
from platform_core.catalog.source_tables import parse_module_list

Traits = frozenset[str]

# ---------------------------------------------------------------- families

# Interview playbook (First Launch) -> §21 family. Overrides below.
_BY_PLAYBOOK: dict[str, str] = {
    "meat_seafood": "meat_chicken_fish_shops",
    "produce": "fruit_vegetable_dairy_egg",
    "grocery": "grocery_kirana_supermarket",
    "dairy_subscription": "fruit_vegetable_dairy_egg",
    "home_food": "home_kitchens_pickles_podi",
    "bakery_sweets": "bakeries_sweet_shops",
    "tiffin": "tiffin_services_meal_subscriptions",
    "restaurant": "restaurants_caf_s_qsr",
    "cafe": "restaurants_caf_s_qsr",
    "catering": "catering_canteens",
    "fashion_retail": "clothing_footwear_fashion_retail",
    "jewellery": "jewellery",
    "general_retail": "hardware_sports_stationery_books",
    "electronics": "electronics_mobile_stores",
    "furniture_decor": "furniture_home_decor_kitchenware",
    "optical": "cosmetics_optical",
    "pet_shop": "pet_shops_pet_food",
    "boutique": "tailors_bridal_wear_designer",
    "tailoring": "tailors_bridal_wear_designer",
    "uniform_b2b": "uniform_suppliers_custom_t",
    "handmade": "leather_goods_bags_handmade",
    "salon": "salons_barbers_nail_studios",
    "spa": "spas_massage_centres_skincare",
    "makeup_artist": "makeup_artists_bridal_makeup",
    "institute": "beauty_academies",
    "gym": "gyms_crossfit_powerlifting",
    "studio": "yoga_pilates_dance_fitness",
    "coach": "personal_trainers_nutrition_coaches",
    "hospital": "hospitals_polyclinics",
    "clinic": "clinics_dental_eye_ent",
    "diagnostics": "diagnostic_centres_medical_labs",
    "pharmacy": "pharmacies",
    "care_service": "home_nursing_caregivers_ambulance",
    "therapy": "therapy_psychologists_counsellors_speech",
    "school": "schools_preschools",
    "tuition": "coaching_institutes_tuition_centres",
    "arts_school": "language_music_dance_coding",
    "tutor": "individual_tutors",
    "creator": "youtubers_influencers_podcasters_newsletter",
    "professional_firm": "chartered_accountants_accountants_tax",
    "consulting": "management_hr_business_b2b",
    "finance": "financial_advisers_insurance_agents",
    "real_estate_developer": "developers_builders_plot_sellers",
    "real_estate_broker": "brokers_agencies_rental_agencies",
    "stay": "property_management_co_living",
    "design_studio": "architects_interior_designers_landscape",
    "contractor": "contractors_civil_electrical_plumbing",
    "home_service": "home_services_cleaning_pest",
    "laundry": "laundry_dry_cleaning",
    "repair": "repair_specialists_it_support",
    "vehicle_dealer": "car_bike_dealers_used",
    "auto_service": "garages_mechanics_car_wash",
    "detailing": "garages_mechanics_car_wash",
    "auto_parts": "garages_mechanics_car_wash",
    "rentals": "rentals_cars_bikes_cameras",
    "logistics": "courier_packers_movers_trucking",
    "hotel": "hotels_resorts",
    "homestay": "homestays_hostels_villa_rentals",
    "travel": "travel_agencies_tour_operators",
    "event_planner": "event_wedding_planners_decorators",
    "banquet_hall": "mandapams_banquet_community_halls",
    "florist": "florists_djs_sound_light",
    "print_shop": "packaging_printing_signage",
    "photographer": "photographers_videographers_filmmakers_editors",
    "creative_agency": "ad_digital_marketing_seo",
    "maker": "graphic_designers_illustrators_artists",
    "software": "software_saas_it_services",
    "industrial_supplier": "industrial_suppliers_pumps_valves",
    "manufacturer": "manufacturers_food_textiles_garments",
    "wholesale": "wholesale_distribution_fmcg_pharma",
    "farm": "farms_organic_dairy_poultry",
    "agri_dealer": "agri_services_tractor_rental",
    "energy": "solar_epc_ev_charging",
    "pet_care": "grooming_boarding_training_dog",
    "daycare": "daycare_play_schools_activity",
    "coworking": "co_working_office_rental",
    "security_facility": "security_agencies_alarm_fire",
    "testing_lab": "testing_calibration_r_d",
    "community": "clubs_sports_hobby_clubs",
    "ngo": "ngos_animal_rescue_education",
}

# Subcategories whose §21 family differs from their interview playbook's.
_BY_SUBCATEGORY: dict[str, str] = {
    "home_bakery": "home_kitchens_pickles_podi",
    "cloud_kitchen": "tiffin_services_meal_subscriptions",
    "cosmetics": "cosmetics_optical",
    "kitchenware": "furniture_home_decor_kitchenware",
    "embroidery": "uniform_suppliers_custom_t",
    "piercing_studio": "makeup_artists_bridal_makeup",
    "skincare_clinic": "spas_massage_centres_skincare",
    "polyclinic": "hospitals_polyclinics",
    "veterinary": "veterinary_clinics",
    "elder_care": "elder_care_assisted_living",
    "assisted_living": "elder_care_assisted_living",
    "maternity_services": "maternity_services",
    "babysitting": "daycare_play_schools_activity",
    "language_school": "language_music_dance_coding",
    "coding_academy": "language_music_dance_coding",
    "vocational_institute": "vocational_institutes_driving_schools",
    "driving_school": "vocational_institutes_driving_schools",
    "online_educator": "online_educators_course_sellers",
    "author": "coaches_speakers_authors",
    "coach": "coaches_speakers_authors",
    "speaker": "coaches_speakers_authors",
    "lawyer": "lawyers",
    "bookkeeping_service": "chartered_accountants_accountants_tax",
    "recruitment": "recruitment_temp_staffing_domestic",
    "temp_staffing": "recruitment_temp_staffing_domestic",
    "domestic_help_agency": "recruitment_temp_staffing_domestic",
    "property_management": "property_management_co_living",
    "modular_kitchen": "modular_kitchens_renovation_furniture",
    "furniture_designer": "modular_kitchens_renovation_furniture",
    "renovation": "modular_kitchens_renovation_furniture",
    "cctv": "repair_specialists_it_support",
    "networking": "repair_specialists_it_support",
    "car_rental": "car_rental_driver_services",
    "driver_service": "car_rental_driver_services",
    "taxi": "taxi_bus_operators_last",
    "bus_operator": "taxi_bus_operators_last",
    "last_mile": "taxi_bus_operators_last",
    "warehousing": "warehousing_cold_storage_self",
    "cold_storage": "warehousing_cold_storage_self",
    "self_storage": "warehousing_cold_storage_self",
    "document_storage": "warehousing_cold_storage_self",
    "sound_light_rental": "florists_djs_sound_light",
    "dj": "florists_djs_sound_light",
    "invitations": "florists_djs_sound_light",
    "tractor_rental": "agri_services_tractor_rental",
    "generator_rental": "solar_epc_ev_charging",
    "adventure_tourism": "adventure_tourism",
    "community_hall": "mandapams_banquet_community_halls",
    "process_equipment": "oem_engineering_firms_process",
    "boilers": "oem_engineering_firms_process",
    "compressors": "oem_engineering_firms_process",
    "water_treatment_equipment": "oem_engineering_firms_process",
    "conveyors": "oem_engineering_firms_process",
    "packaging": "packaging_printing_signage",
    "corrugated_boxes": "packaging_printing_signage",
    "labels": "packaging_printing_signage",
    "bottles": "packaging_printing_signage",
    "flexible_packaging": "packaging_printing_signage",
    "packaging_manufacturer": "packaging_printing_signage",
    "exporter": "import_export_trading_companies",
    "importer": "import_export_trading_companies",
    "export_house": "import_export_trading_companies",
    "garment_exporter": "import_export_trading_companies",
    "food_exporter": "import_export_trading_companies",
    "handicraft_exporter": "import_export_trading_companies",
    "machinery_importer": "import_export_trading_companies",
    "trading_company": "import_export_trading_companies",
    "dairy_farm": "farms_organic_dairy_poultry",
    "waste_management": "waste_management_recycling_composting",
    "water_treatment": "waste_management_recycling_composting",
    "recycling": "waste_management_recycling_composting",
    "composting": "waste_management_recycling_composting",
    "environmental_consultancy": "waste_management_recycling_composting",
    "facility_management": "facilities_management_commercial_cleaning",
    "commercial_cleaning": "facilities_management_commercial_cleaning",
    "maintenance_contracts": "facilities_management_commercial_cleaning",
    "building_management": "facilities_management_commercial_cleaning",
    "manpower": "facilities_management_commercial_cleaning",
    "temple_trust": "temple_service_organisations_cultural",
    "cultural_centre": "temple_service_organisations_cultural",
    "trust": "temple_service_organisations_cultural",
    "pet_photography": "photographers_videographers_filmmakers_editors",
    "pet_food": "pet_shops_pet_food",
}


def family_key_for(subcategory_key: str, playbook: str) -> str | None:
    if subcategory_key in _BY_SUBCATEGORY:
        return _BY_SUBCATEGORY[subcategory_key]
    return _BY_PLAYBOOK.get(playbook)


# ---------------------------------------------------------------- trait rules


def _any(*traits: str) -> Callable[[Traits], bool]:
    return lambda t: any(x in t for x in traits)


def _all(*traits: str) -> Callable[[Traits], bool]:
    return lambda t: all(x in t for x in traits)


# A module is pre-ticked only when its requirement holds for this business.
# Modules not listed have no trait requirement.
REQUIRES: dict[str, tuple[Callable[[Traits], bool], str]] = {
    "pos": (_any("walk_in"), "customers buy at a counter"),
    "queue-operations": (_any("walk_in"), "customers walk in"),
    "fulfilment": (_any("pickup", "local_delivery", "shipping"), "you hand over, deliver or ship"),
    "dispatch": (_any("local_delivery", "field_team", "on_site_service"),
                 "you deliver locally or send people out"),
    "bookings": (lambda t: "booking_led" in t or any(k in t for k in ("appointment", "table", "stay",
                 "class", "rental", "site_visit", "event_date")), "customers book a time or a date"),
    "memberships": (_any("subscription_led", "sells_access"), "customers join plans or subscriptions"),
    "donations": (_any("donation_led", "nonprofit"), "you receive donations"),
    "orders": (_any("sells_products", "order_led"), "you sell things people order"),
    "inventory": (_any("stock_tracked", "perishable", "weight_based", "variant_based", "serialised",
                       "made_to_order", "ingredient_based"), "you keep stock"),
    "recipes": (_any("ingredient_based", "made_to_order"), "you make what you sell from materials"),
    "kitchen": (_all("sells_products", "order_led"), "you prepare orders"),
    "jobs": (_any("sells_services", "on_site_service", "field_team"), "you do service or repair work"),
    "attendance": (_any("sells_access", "class", "shift_staff", "field_team", "subscription_led"),
                   "people check in"),
}

# §4.3 "Switches on": trait → modules, with the owner-facing reason.
TRIGGERS: tuple[tuple[Callable[[Traits], bool], tuple[str, ...], str], ...] = (
    (_any("b2b"), ("quotes", "invoicing", "ledger", "trade-network"), "you sell to businesses"),
    (_any("sells_products"), ("offerings-catalog", "orders"), "you sell products"),
    (_any("sells_access"), ("memberships",), "people pay for access"),
    (_any("order_led"), ("orders",), "customers order from you"),
    (_any("booking_led"), ("bookings",), "customers book with you"),
    (_any("quote_led"), ("quotes",), "you quote before you sell"),
    (_any("enquiry_led"), ("leads",), "your business starts with an enquiry"),
    (_any("subscription_led"), ("memberships",), "customers subscribe or renew"),
    (_any("project_led"), ("projects",), "your work runs as projects"),
    (_any("donation_led", "nonprofit"), ("donations",), "you receive donations"),
    (_any("appointment", "table", "stay", "class", "rental", "site_visit", "event_date"),
     ("bookings",), "customers book a time or a date"),
    (_any("stay"), ("tasks",), "rooms are turned around between stays"),
    (_any("rental"), ("tasks",), "rentals are handed over and checked on return"),
    (_all("walk_in", "sells_products"), ("pos",), "customers buy at your counter"),
    (_all("walk_in", "sells_services"), ("queue-operations",), "customers walk in for service"),
    (_any("local_delivery"), ("fulfilment", "dispatch"), "you deliver locally"),
    (_any("pickup", "shipping"), ("fulfilment",), "customers collect or you ship"),
    (_any("on_site_service"), ("jobs",), "you work at the customer's place"),
    (_any("stock_tracked", "perishable", "weight_based", "variant_based", "serialised"),
     ("inventory",), "you keep stock"),
    (_any("ingredient_based", "made_to_order"), ("recipes", "procurement"),
     "you make what you sell from materials"),
    (_any("provider_based"), ("workforce",), "customers are served by a named person"),
    (_any("field_team"), ("workforce", "dispatch"), "your team works in the field"),
    (_any("shift_staff"), ("workforce", "attendance"), "your staff work in shifts"),
    (_any("gst_registered", "composition_scheme"), ("invoicing",), "you issue GST bills"),
    (_any("portfolio_led"), ("offerings-catalog",), "you win work by showing past work"),
)

# Configuration hints traits add (setup, not modules).
TRAIT_HINTS: dict[str, tuple[str, str]] = {
    "weight_based": ("offerings-catalog", "weighed_product"),
    "variant_based": ("offerings-catalog", "variants"),
    "serialised": ("inventory", "serials"),
    "perishable": ("inventory", "batches_expiry"),
    "appointment": ("bookings", "appointment"),
    "table": ("bookings", "table"),
    "stay": ("bookings", "stay"),
    "class": ("bookings", "class"),
    "rental": ("bookings", "rental"),
    "site_visit": ("bookings", "site_visit"),
    "event_date": ("bookings", "event_date"),
    "composition_scheme": ("invoicing", "bill_of_supply"),
    "gst_registered": ("invoicing", "tax_invoice"),
    "minors_involved": ("customer-relationships", "guardians"),
}


# ---------------------------------------------------------------- output


@dataclass
class Pick:
    module: str
    tier: str  # always | core | recommended | optional
    reason: str
    hints: list[str] = field(default_factory=list)
    order: int = 999  # position in the source's own list, so the page reads like §21

    def as_dict(self) -> dict[str, object]:
        info = MODULES.get(self.module)
        return {
            "module": self.module,
            "tier": self.tier,
            "reason": self.reason,
            "hints": sorted(set(self.hints)),
            "label": info.label if info else self.module,
            "built": is_built(self.module),
            "phase": info.phase if info else None,
            "order": self.order,
        }


@dataclass
class Recommendation:
    family: str | None
    picks: dict[str, Pick]
    people: str = ""
    ai_employees: str = ""

    def tier(self, name: str) -> list[str]:
        return sorted(m for m, p in self.picks.items() if p.tier == name)

    def as_dict(self) -> dict[str, object]:
        order = {"always": 0, "core": 1, "recommended": 2, "optional": 3}
        picks = sorted(self.picks.values(), key=lambda p: (order[p.tier], p.order, p.module))
        return {
            "family": self.family,
            "family_label": FAMILIES[self.family].label if self.family else None,
            "always": self.tier("always"),
            "core": self.tier("core"),
            "recommended": self.tier("recommended"),
            "optional": self.tier("optional"),
            "people": self.people,
            "ai_employees": self.ai_employees,
            "modules": [p.as_dict() for p in picks],
        }


def _family_modules(fam: Family, which: str) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = parse_module_list(fam.core if which == "core" else fam.rec)
    return parsed


def _requirement_holds(module: str, traits: Traits) -> bool:
    rule = REQUIRES.get(module)
    return True if rule is None else rule[0](traits)


def _triggered(traits: Iterable[str]) -> dict[str, str]:
    t = frozenset(traits)
    out: dict[str, str] = {}
    for when, modules, reason in TRIGGERS:
        if when(t):
            for m in modules:
                out.setdefault(m, reason)
    return out


def trigger_reasons(traits: Iterable[str]) -> dict[str, str]:
    """module -> why these traits switch it on, in the owner's words
    ("you quote before you sell"), for modules whose requirement holds.

    When several rules switch a module on, the most specific one speaks: "you
    quote before you sell" says more about Quotes than "you sell to businesses",
    which switches on four tools at once."""
    t = frozenset(traits)
    out: dict[str, tuple[int, str]] = {}
    for when, modules, reason in TRIGGERS:
        if not when(t):
            continue
        for m in modules:
            if _requirement_holds(m, t) and (m not in out or len(modules) < out[m][0]):
                out[m] = (len(modules), reason)
    return {m: r for m, (_, r) in out.items()}


def triggered_by_trait(traits: Iterable[str]) -> dict[str, str]:
    """module -> the single trait (of these) that switches it on, by the §4.3 rules.

    Used to say which of the owner's own answers makes a tool worth having
    ("You told LOCAH: “We deliver locally”"). Rules that need two traits at
    once are left out: no one trait is the reason for them."""
    out: dict[str, str] = {}
    for trait in sorted(set(traits)):
        for module in _triggered([trait]):
            if _requirement_holds(module, frozenset(traits)):
                out.setdefault(module, trait)
    return out


def recommend(
    *,
    subcategory_key: str | None,
    playbook: str | None,
    traits: Iterable[str],
    default_traits: Iterable[str] | None = None,
    family_label: str | None = None,
) -> Recommendation:
    """Core / Recommended / Optional modules for a business with these traits.

    `default_traits` are the subcategory's defaults; traits beyond them were
    added by the owner (their modules become Recommended), traits missing from
    them were removed by the owner (their modules lose their requirement).
    """
    traits = frozenset(traits)
    defaults = frozenset(default_traits if default_traits is not None else traits)
    added = traits - defaults
    fam_key = family_key_for(subcategory_key or "", playbook or "") if subcategory_key else None
    fam = FAMILIES.get(fam_key) if fam_key else None
    picks: dict[str, Pick] = {}

    for m in STOREFRONT:
        picks[m] = Pick(m, "always", "Every business on LOCAH has this")

    seq = iter(range(1000))

    def put(module: str, tier: str, reason: str, hint: str = "") -> None:
        if module not in MODULES and module not in STOREFRONT:
            return
        current = picks.get(module)
        rank = {"always": 0, "core": 1, "recommended": 2, "optional": 3}
        if current is None or rank[tier] < rank[current.tier]:
            hints = current.hints if current else []
            picks[module] = Pick(module, tier, reason, hints, next(seq))
            current = picks[module]
        if hint:
            current.hints.append(hint)

    label = (fam.label if fam else family_label) or "businesses like yours"
    if fam:
        for which, tier in (("core", "core"), ("rec", "recommended")):
            for module, hint in _family_modules(fam, which):
                if MODULES.get(module) and MODULES[module].future:
                    continue
                holds = _requirement_holds(module, traits)
                # Core is trait-checked outright (a café without table service is
                # not pre-ticked for table bookings). Recommended is the source's
                # explicit "usually add", so it only drops when the owner removed
                # the trait that justified it.
                removed = tier == "recommended" and not holds and _requirement_holds(module, defaults)
                if (tier == "core" and holds) or (tier == "recommended" and not removed):
                    who = label[:1].lower() + label[1:]
                    put(module, tier, f"Most {who} rely on this" if tier == "core" else f"Many {who} add this", hint)
                else:
                    why = REQUIRES[module][1]
                    put(module, "optional", f"Useful only if {why}", hint)

    for module, reason in _triggered(traits).items():
        if not _requirement_holds(module, traits):
            continue
        if module in picks:
            continue
        caused_by_owner = module in _triggered(added) and module not in _triggered(defaults)
        # No family (Other): traits are all there is, so they recommend.
        tier = "recommended" if (caused_by_owner or fam is None) else "optional"
        put(module, tier, f"Because {reason}")

    for trait in traits:
        if trait in TRAIT_HINTS:
            module, hint = TRAIT_HINTS[trait]
            if module in picks:
                picks[module].hints.append(hint)

    return Recommendation(fam_key, picks, fam.people if fam else "", fam.ai if fam else "")
