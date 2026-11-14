"""The canonical business taxonomy: 32 categories + Other, their subcategories,
synonyms owners actually type, default operating traits and a playbook key.

Source: LOCAH Business Capability Universe §4 (classification) and §21–§22
(sector playbooks, operating models). This file is the one registry for it
(§4.4); the frontend reads it through `/v1/platform/taxonomy`, nothing is
hard-coded twice.

What a category is for — and what it is not:

* It seeds the interview: which questions an expert in this trade would ask,
  in the trade's own words, and which tools are likely to fit.
* Its traits are **priors**, never facts. "Meat shops usually deliver" makes
  "do you deliver?" worth asking; it never puts "Home delivery" on a website.
  Only what the owner says becomes business truth.
* `template` keeps the legacy `business_type` key the rest of the platform
  still reads (Capability Universe §4.1: `business_type` stays as the website
  template key until the P1 migration).

Search is deterministic and spelling-tolerant: no model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

TAXONOMY_VERSION = "2026-09-27.1"

# Operating traits (Capability Universe §4.3) — the complete vocabulary, by group.
TRAIT_GROUPS: dict[str, tuple[str, ...]] = {
    "buyer": ("b2c", "b2b"),
    "offer": ("sells_products", "sells_services", "sells_access"),
    "transact": ("order_led", "booking_led", "quote_led", "enquiry_led", "subscription_led",
                 "project_led", "donation_led"),
    "booking_kind": ("appointment", "table", "stay", "class", "rental", "site_visit", "event_date"),
    "fulfilment": ("walk_in", "pickup", "local_delivery", "shipping", "on_site_service", "digital"),
    "stock": ("stock_tracked", "perishable", "weight_based", "variant_based", "serialised",
              "made_to_order", "ingredient_based"),
    "people": ("provider_based", "field_team", "shift_staff"),
    "regulated": ("gst_registered", "composition_scheme", "food_licensed", "health_regulated",
                  "finance_regulated", "minors_involved"),
    "presentation": ("portfolio_led", "digital_only", "nonprofit"),
}
TRAITS = frozenset(t for group in TRAIT_GROUPS.values() for t in group)
BOOKING_KINDS = frozenset(TRAIT_GROUPS["booking_kind"])

# Org shape (§4.3, §22): one value; decides role templates and plan tier, not modules.
ORG_SHAPES: tuple[str, ...] = ("solo", "team", "multi_location", "franchise_brand",
                               "franchise_outlet", "enterprise")


@dataclass(frozen=True)
class Subcategory:
    key: str
    label: str
    synonyms: tuple[str, ...]
    traits: frozenset[str]
    playbook: str


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    template: str  # legacy business_type
    tile: bool  # shown as a tile before the owner types anything
    subcategories: tuple[Subcategory, ...]


def _s(key: str, label: str, playbook: str, traits: frozenset[str], *synonyms: str) -> Subcategory:
    unknown = traits - TRAITS
    if unknown:  # pragma: no cover — a typo in this file, caught at import
        raise ValueError(f"unknown traits for {key}: {sorted(unknown)}")
    return Subcategory(key, label, tuple(synonyms), traits, playbook)


def _t(*names: str) -> frozenset[str]:
    return frozenset(names)


# Trait sets shared by many subcategories.
FRESH = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery",
           "weight_based", "perishable", "stock_tracked", "food_licensed")
GROCERY = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery", "variant_based", "stock_tracked")
HOME_FOOD = _t("b2c", "sells_products", "order_led", "pickup", "local_delivery", "made_to_order",
               "perishable", "food_licensed")
SHELF_FOOD = _t("b2c", "sells_products", "order_led", "pickup", "local_delivery", "shipping",
                "made_to_order", "food_licensed")
TIFFIN = _t("b2c", "sells_products", "subscription_led", "order_led", "local_delivery", "perishable", "ingredient_based", "food_licensed")
DINE = _t("b2c", "sells_products", "order_led", "booking_led", "table", "walk_in", "pickup",
          "local_delivery", "ingredient_based", "food_licensed")
CAFE = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery", "ingredient_based", "food_licensed")
BAKERY = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery",
            "made_to_order", "perishable", "ingredient_based", "food_licensed")
CATER = _t("b2c", "b2b", "sells_services", "quote_led", "enquiry_led", "event_date", "on_site_service", "ingredient_based", "food_licensed")
SHOP = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery", "variant_based", "stock_tracked")
SHOP_SHIP = SHOP | _t("shipping")
MADE = _t("b2c", "sells_products", "order_led", "enquiry_led", "made_to_order", "pickup", "shipping")
TAILOR = _t("b2c", "sells_services", "sells_products", "booking_led", "appointment", "made_to_order",
            "walk_in")
UNIFORM = _t("b2b", "sells_products", "quote_led", "made_to_order")
SALON = _t("b2c", "sells_services", "booking_led", "appointment", "walk_in", "provider_based")
ARTIST = _t("b2c", "sells_services", "booking_led", "event_date", "enquiry_led", "portfolio_led",
            "on_site_service")
GYM = _t("b2c", "sells_access", "subscription_led", "booking_led", "class", "walk_in")
STUDIO = _t("b2c", "sells_access", "booking_led", "class", "subscription_led")
COACH = _t("b2c", "sells_services", "booking_led", "appointment", "subscription_led", "digital")
CLINIC = _t("b2c", "sells_services", "booking_led", "appointment", "walk_in", "provider_based", "subscription_led", "health_regulated")
HOSPITAL = CLINIC - _t("subscription_led")
LAB = _t("b2c", "b2b", "sells_services", "booking_led", "appointment", "on_site_service", "health_regulated")
PHARMACY = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery", "stock_tracked", "health_regulated")
CARE_HOME = _t("b2c", "sells_services", "enquiry_led", "subscription_led", "on_site_service",
               "field_team", "health_regulated")
THERAPY = _t("b2c", "sells_services", "booking_led", "appointment", "provider_based", "digital", "subscription_led", "health_regulated")
INSTITUTE = _t("b2c", "sells_services", "enquiry_led", "subscription_led", "class")
TUTOR = _t("b2c", "sells_services", "booking_led", "class", "enquiry_led", "digital", "subscription_led")
PRO = _t("b2c", "b2b", "sells_services", "enquiry_led", "booking_led", "appointment")
CONSULT = _t("b2b", "sells_services", "enquiry_led", "quote_led", "project_led")
PROPERTY = _t("b2c", "sells_products", "enquiry_led", "booking_led", "site_visit")
PROPERTY_RENT = _t("b2c", "sells_services", "enquiry_led", "subscription_led", "stay")
DESIGN = _t("b2c", "b2b", "sells_services", "enquiry_led", "quote_led", "project_led", "site_visit",
            "portfolio_led")
CONTRACTOR = _t("b2c", "b2b", "sells_services", "quote_led", "project_led", "on_site_service",
                "field_team")
HOME_SERVICE = _t("b2c", "sells_services", "booking_led", "appointment", "on_site_service",
                  "field_team", "subscription_led")
REPAIR = _t("b2c", "sells_services", "walk_in", "enquiry_led", "booking_led", "appointment")
LAUNDRY = _t("b2c", "sells_services", "order_led", "pickup", "local_delivery", "walk_in")
DEALER = _t("b2c", "sells_products", "enquiry_led", "booking_led", "site_visit", "walk_in")
GARAGE = _t("b2c", "sells_services", "booking_led", "appointment", "walk_in")
DETAILING = _t("b2c", "sells_services", "booking_led", "appointment", "walk_in", "on_site_service",
               "portfolio_led")
PARTS = _t("b2c", "b2b", "sells_products", "order_led", "walk_in", "pickup", "local_delivery", "stock_tracked")
RENTAL = _t("b2c", "sells_services", "booking_led", "rental", "pickup", "local_delivery")
FREIGHT = _t("b2b", "b2c", "sells_services", "quote_led", "enquiry_led", "on_site_service", "order_led")
RIDE = _t("b2c", "sells_services", "booking_led", "on_site_service")
STAY = _t("b2c", "sells_services", "booking_led", "stay")
TOUR = _t("b2c", "sells_services", "enquiry_led", "quote_led", "booking_led", "event_date")
EVENTS = _t("b2c", "b2b", "sells_services", "enquiry_led", "quote_led", "event_date", "project_led",
            "portfolio_led")
HALL = _t("b2c", "sells_services", "booking_led", "event_date", "enquiry_led")
FLORIST = _t("b2c", "sells_products", "order_led", "local_delivery", "pickup", "made_to_order",
             "perishable", "event_date")
PHOTO = _t("b2c", "sells_services", "enquiry_led", "quote_led", "event_date", "portfolio_led")
AGENCY = _t("b2b", "sells_services", "enquiry_led", "quote_led", "project_led", "subscription_led",
            "portfolio_led")
MAKER = _t("b2c", "b2b", "sells_services", "enquiry_led", "quote_led", "portfolio_led", "digital")
CREATOR = _t("b2c", "b2b", "sells_services", "sells_products", "enquiry_led", "digital", "booking_led", "appointment")
TECH = _t("b2b", "sells_services", "enquiry_led", "quote_led", "project_led", "digital", "subscription_led")
SUPPLY = _t("b2b", "sells_products", "quote_led", "enquiry_led", "shipping", "local_delivery", "stock_tracked")
FACTORY = _t("b2b", "sells_products", "quote_led", "made_to_order", "shipping", "stock_tracked")
PRINT = _t("b2b", "b2c", "sells_products", "quote_led", "made_to_order", "walk_in", "pickup")
TRADE = _t("b2b", "sells_products", "order_led", "quote_led", "local_delivery", "shipping", "stock_tracked")
FARM = _t("b2c", "b2b", "sells_products", "order_led", "subscription_led", "pickup", "local_delivery",
          "perishable", "stock_tracked", "food_licensed")
AGRI = _t("b2c", "b2b", "sells_products", "sells_services", "walk_in", "enquiry_led", "stock_tracked")
ENERGY = _t("b2c", "b2b", "sells_services", "enquiry_led", "quote_led", "project_led", "site_visit",
            "on_site_service", "subscription_led")
PET_SHOP = _t("b2c", "sells_products", "order_led", "walk_in", "pickup", "local_delivery", "stock_tracked")
PET_CARE = _t("b2c", "sells_services", "booking_led", "appointment", "stay")
DAYCARE = _t("b2c", "sells_services", "enquiry_led", "subscription_led", "class", "minors_involved")
COWORK = _t("b2b", "b2c", "sells_access", "booking_led", "subscription_led", "rental")
SECURITY = _t("b2b", "sells_services", "quote_led", "enquiry_led", "subscription_led", "field_team",
              "on_site_service", "shift_staff")
TESTLAB = _t("b2b", "sells_services", "quote_led", "enquiry_led")
CLUB = _t("b2c", "sells_access", "subscription_led", "booking_led", "event_date")
NGO = _t("b2c", "donation_led", "nonprofit", "enquiry_led")


CATEGORIES: tuple[Category, ...] = (
    Category("fresh_grocery", "Fresh food & grocery", "retail", True, (
        _s("meat_shop", "Meat shop", "meat_seafood", FRESH, "meat", "mutton shop", "meat market", "kasai"),
        _s("butcher", "Butcher", "meat_seafood", FRESH, "butchery", "butcher shop"),
        _s("chicken_shop", "Chicken shop", "meat_seafood", FRESH, "chicken center", "poultry shop",
           "broiler shop", "kozhi kadai", "chicken kadai"),
        _s("seafood", "Seafood shop", "meat_seafood", FRESH, "sea food", "prawns", "crab shop"),
        _s("fish_market", "Fish market", "meat_seafood", FRESH, "fish shop", "fish stall", "meen kadai",
           "fish seller"),
        _s("fruit_shop", "Fruit shop", "produce", FRESH, "fruits", "fruit stall", "fruit seller"),
        _s("vegetable_shop", "Vegetable shop", "produce", FRESH, "vegetables", "veggies", "sabzi",
           "kaikari kadai"),
        _s("organic_produce", "Organic produce", "produce", FRESH | _t("shipping"), "organic store",
           "organic vegetables", "organic farm produce"),
        _s("grocery", "Grocery / kirana", "grocery", GROCERY, "kirana", "kirana store", "grocery store",
           "general store", "provisions", "maligai kadai", "mini mart"),
        _s("supermarket", "Supermarket", "grocery", GROCERY, "super market", "hypermarket", "departmental store"),
        _s("provision_store", "Provision store", "grocery", GROCERY, "provision shop"),
        _s("dry_fruits", "Dry fruits", "grocery", GROCERY | _t("shipping", "weight_based"),
           "dry fruit shop", "nuts", "dryfruits"),
        _s("spices", "Spices", "grocery", GROCERY | _t("shipping", "weight_based"), "masala",
           "spice shop", "masala shop"),
        _s("rice_store", "Rice store", "grocery", GROCERY | _t("weight_based"), "rice mandi",
           "rice shop", "arisi kadai"),
        _s("dairy", "Dairy / milk", "dairy_subscription",
           _t("b2c", "sells_products", "subscription_led", "order_led", "local_delivery", "perishable"),
           "milk", "milk delivery", "dairy shop", "paal", "milk booth"),
        _s("eggs", "Eggs", "dairy_subscription",
           _t("b2c", "b2b", "sells_products", "order_led", "local_delivery", "perishable"),
           "egg shop", "egg supplier", "egg wholesale"),
    )),
    Category("home_food", "Home food & packaged food", "restaurant", True, (
        _s("home_kitchen", "Home kitchen", "home_food", HOME_FOOD, "home food", "homemade food",
           "home cooked food", "veetu saapadu", "home chef", "homemade meals"),
        _s("pickles_podi", "Pickles & podi", "home_food", SHELF_FOOD, "pickles", "podi", "thokku",
           "achar", "oorugai"),
        _s("snacks", "Snacks", "home_food", SHELF_FOOD, "namkeen", "murukku", "homemade snacks"),
        _s("sweets", "Sweets", "home_food", SHELF_FOOD, "mithai", "homemade sweets", "sweet maker"),
        _s("home_bakery", "Home bakery", "bakery_sweets", HOME_FOOD, "home baker", "homemade cakes",
           "cake maker", "home bakes", "custom cakes"),
        _s("tiffin", "Tiffin / meal subscription", "tiffin", TIFFIN, "tiffin service", "dabba",
           "meal subscription", "mess", "lunch box service", "meal plan", "mess service"),
        _s("cloud_kitchen", "Cloud kitchen", "restaurant", CAFE - _t("walk_in"), "cloudkitchen",
           "delivery kitchen", "dark kitchen"),
        _s("chocolates", "Homemade chocolates", "home_food", SHELF_FOOD, "chocolates", "chocolatier"),
        _s("jams_sauces", "Jams & sauces", "home_food", SHELF_FOOD, "jams", "sauces", "preserves"),
        _s("millet_foods", "Millet foods", "home_food", SHELF_FOOD, "millets", "millet snacks",
           "siruthaniyam"),
        _s("healthy_meals", "Healthy meals", "tiffin", TIFFIN, "diet meals", "salad subscription",
           "healthy food"),
    )),
    Category("food_service", "Restaurants, cafés & catering", "restaurant", True, (
        _s("restaurant", "Restaurant", "restaurant", DINE, "hotel (restaurant)", "eatery",
           "family restaurant", "unavagam", "dhaba"),
        _s("cafe", "Café", "cafe", CAFE, "cafe", "coffee shop", "coffee house", "bistro"),
        _s("tea_shop", "Tea shop", "cafe", CAFE, "tea stall", "chai", "tea kadai", "tea stop"),
        _s("juice_bar", "Juice bar", "cafe", CAFE, "juice shop", "juice center", "smoothies"),
        _s("bakery", "Bakery", "bakery_sweets", BAKERY, "bakery shop", "bakers", "cake shop",
           "patisserie"),
        _s("pizzeria", "Pizzeria", "restaurant", DINE, "pizza", "pizza place"),
        _s("fast_food", "Fast food", "restaurant", CAFE, "burgers", "shawarma", "fast food joint",
           "quick service"),
        _s("fine_dining", "Fine dining", "restaurant", DINE, "fine dine", "premium restaurant"),
        _s("food_truck", "Food truck", "cafe", CAFE - _t("local_delivery"), "food cart", "street food"),
        _s("catering", "Catering", "catering", CATER, "caterer", "caterers", "wedding catering",
           "event catering", "samayal"),
        _s("canteen", "Canteen", "catering", CATER | _t("subscription_led"), "office canteen",
           "industrial canteen", "corporate canteen"),
        _s("pub_bar", "Pub / bar", "restaurant", DINE - _t("local_delivery"), "pub", "bar",
           "brewery", "lounge"),
        _s("ice_cream", "Ice cream", "cafe", CAFE, "ice cream parlour", "gelato"),
        _s("desserts", "Desserts", "bakery_sweets", CAFE, "dessert shop", "dessert parlour"),
        _s("biryani_shop", "Biryani shop", "restaurant", DINE, "biryani", "biryani centre"),
        _s("mess", "Mess", "restaurant", DINE - _t("table"), "meals mess", "mess hall"),
    )),
    Category("retail", "Retail stores", "retail", True, (
        _s("clothing", "Clothing store", "fashion_retail", SHOP_SHIP, "clothes", "garments",
           "textiles", "readymade", "apparel", "saree shop", "dress shop"),
        _s("footwear", "Footwear", "fashion_retail", SHOP_SHIP, "shoes", "chappals", "slippers"),
        _s("jewellery", "Jewellery", "jewellery", _t("b2c", "sells_products", "walk_in", "enquiry_led",
           "made_to_order"), "jewelry", "jewellers", "gold shop", "nagai kadai", "silver jewellery"),
        _s("cosmetics", "Cosmetics", "general_retail", SHOP_SHIP, "beauty products", "makeup store"),
        _s("stationery", "Stationery", "general_retail", SHOP, "stationary", "book depot"),
        _s("gifts", "Gifts", "general_retail", SHOP_SHIP, "gift shop", "return gifts", "gift hampers"),
        _s("toys", "Toys", "general_retail", SHOP_SHIP, "toy shop", "toy store"),
        _s("electronics", "Electronics", "electronics", SHOP | _t("booking_led"), "electronics shop",
           "home appliances", "appliance store"),
        _s("mobile_store", "Mobile store", "electronics", SHOP, "mobile shop", "phone shop",
           "mobile accessories"),
        _s("furniture", "Furniture", "furniture_decor", SHOP | _t("made_to_order", "enquiry_led"),
           "furniture shop", "furniture store", "sofas", "wooden furniture"),
        _s("home_decor", "Home decor", "furniture_decor", SHOP_SHIP, "decor", "home furnishing",
           "curtains"),
        _s("kitchenware", "Kitchenware", "general_retail", SHOP_SHIP, "vessels", "utensils",
           "pathiram kadai", "steel vessels"),
        _s("hardware", "Hardware", "general_retail", SHOP | _t("b2b"), "hardware shop", "paints",
           "tools shop", "sanitaryware"),
        _s("sports_goods", "Sports goods", "general_retail", SHOP_SHIP, "sports shop", "gym equipment",
           "fitness equipment"),
        _s("books", "Books", "general_retail", SHOP_SHIP, "bookshop", "book store"),
        _s("optical", "Optical", "optical", SHOP | _t("booking_led", "appointment"), "opticals",
           "spectacles", "eyewear", "optician"),
        _s("pet_supplies", "Pet supplies", "pet_shop", PET_SHOP, "pet food", "pet store"),
    )),
    Category("fashion_custom", "Fashion, tailoring & handmade", "retail", False, (
        _s("boutique", "Boutique", "boutique", MADE | _t("walk_in"), "designer boutique", "ladies boutique"),
        _s("tailor", "Tailor", "tailoring", TAILOR, "tailoring", "stitching", "alterations", "darzi"),
        _s("bridal_wear", "Bridal wear", "boutique", TAILOR | _t("event_date"), "bridal", "wedding wear",
           "bridal blouse"),
        _s("designer_label", "Designer label", "boutique", MADE, "fashion label", "clothing brand"),
        _s("uniform_supplier", "Uniform supplier", "uniform_b2b", UNIFORM, "uniforms", "school uniforms",
           "corporate uniforms"),
        _s("embroidery", "Embroidery", "boutique", MADE | _t("b2b"), "aari work", "embroidery work"),
        _s("custom_tshirts", "Custom T-shirts", "uniform_b2b", MADE | _t("b2b"), "t-shirt printing",
           "custom merchandise"),
        _s("leather_goods", "Leather goods", "handmade", MADE, "leather bags", "leather products"),
        _s("bags", "Bags", "handmade", MADE, "handbags", "bag maker"),
        _s("handmade_crafts", "Handmade crafts", "handmade", MADE, "handicrafts", "crafts", "artisan"),
    )),
    Category("beauty", "Beauty & personal care", "salon", True, (
        _s("salon", "Salon", "salon", SALON, "beauty salon", "unisex salon", "hair salon", "parlour",
           "beauty parlour"),
        _s("barber", "Barber", "salon", SALON, "barber shop", "barbershop", "men's salon", "saloon"),
        _s("spa", "Spa", "spa", SALON, "day spa", "wellness spa"),
        _s("nail_studio", "Nail studio", "salon", SALON, "nail art", "nail salon"),
        _s("makeup_artist", "Makeup artist", "makeup_artist", ARTIST, "mua", "makeup"),
        _s("bridal_makeup", "Bridal makeup", "makeup_artist", ARTIST, "bridal makeup artist"),
        _s("skincare_clinic", "Skincare clinic", "clinic", CLINIC, "skin clinic", "aesthetic clinic"),
        _s("beauty_academy", "Beauty academy", "institute", INSTITUTE, "beauty course", "makeup course"),
        _s("massage_centre", "Massage centre", "spa", SALON, "massage", "ayurvedic massage"),
        _s("tattoo_studio", "Tattoo studio", "makeup_artist", ARTIST - _t("on_site_service") | _t("appointment"),
           "tattoo", "tattoos"),
        _s("piercing_studio", "Piercing studio", "salon", SALON, "piercing"),
    )),
    Category("fitness", "Fitness & wellness", "gym", True, (
        # "A strength gym" is a gym; powerlifting is a sport it may coach (owner
        # lab: Forge Strength Club was greeted as "a powerlifting gym").
        _s("gym", "Gym", "gym", GYM, "fitness centre", "fitness center", "health club", "workout", "strength gym",
           "strength training"),
        _s("yoga", "Yoga", "studio", STUDIO, "yoga studio", "yoga classes", "yoga centre"),
        _s("pilates", "Pilates", "studio", STUDIO, "pilates studio"),
        _s("crossfit", "CrossFit", "gym", GYM, "cross fit", "functional training", "functional fitness",
           "crossbox"),
        _s("powerlifting", "Powerlifting", "gym", GYM, "powerlifting gym", "weightlifting", "barbell club"),
        _s("martial_arts", "Martial arts", "studio", STUDIO, "karate", "silambam", "taekwondo",
           "kickboxing", "mma", "kalari"),
        _s("dance_fitness", "Dance fitness", "studio", STUDIO, "zumba", "dance workout"),
        _s("personal_trainer", "Personal trainer", "coach", COACH, "pt", "fitness coach", "trainer"),
        _s("nutrition_coach", "Nutrition coach", "coach", COACH, "dietitian", "nutritionist", "diet coach"),
        _s("meditation_centre", "Meditation centre", "studio", STUDIO, "meditation"),
        _s("wellness_studio", "Wellness studio", "studio", STUDIO, "wellness centre"),
    )),
    Category("healthcare", "Healthcare & clinics", "clinic", True, (
        _s("hospital", "Hospital", "hospital", HOSPITAL, "multispeciality hospital", "nursing home",
           "maruthuvamanai"),
        _s("clinic", "Clinic", "clinic", CLINIC, "doctor", "gp clinic", "medical clinic", "family doctor"),
        _s("polyclinic", "Polyclinic", "clinic", CLINIC, "poly clinic", "multi-speciality clinic"),
        _s("dental", "Dental clinic", "clinic", CLINIC, "dentist", "dental care", "teeth", "orthodontist"),
        _s("physiotherapy", "Physiotherapy", "clinic", CLINIC | _t("subscription_led"), "physio",
           "physiotherapist", "physiotherapy centre", "physiotherapy center", "physio clinic",
           "rehab centre", "sports rehab"),
        _s("diagnostic_centre", "Diagnostic centre", "diagnostics", LAB, "diagnostics", "scan centre",
           "blood test", "lab tests", "pathology lab"),
        _s("pharmacy", "Pharmacy", "pharmacy", PHARMACY, "medical shop", "chemist", "medicals",
           "drug store"),
        _s("eye_clinic", "Eye clinic", "clinic", CLINIC, "eye hospital", "ophthalmologist"),
        _s("ent", "ENT clinic", "clinic", CLINIC, "ent"),
        _s("dermatology", "Dermatology", "clinic", CLINIC, "dermatologist", "skin doctor"),
        _s("paediatrics", "Paediatrics", "clinic", CLINIC, "pediatrician", "child specialist"),
        _s("fertility_clinic", "Fertility clinic", "clinic", CLINIC, "ivf", "fertility centre"),
        _s("home_nursing", "Home nursing", "care_service", CARE_HOME, "nursing care", "home care nurse"),
        _s("ambulance", "Ambulance service", "care_service", CARE_HOME, "ambulance"),
    )),
    Category("therapy", "Therapy & counselling", "clinic", False, (
        _s("psychologist", "Psychologist", "therapy", THERAPY, "psychology"),
        _s("counsellor", "Counsellor", "therapy", THERAPY, "counselling", "counseling"),
        _s("therapist", "Therapist", "therapy", THERAPY, "therapy"),
        _s("speech_therapy", "Speech therapy", "therapy", THERAPY, "speech therapist"),
        _s("occupational_therapy", "Occupational therapy", "therapy", THERAPY, "ot"),
        _s("rehab_centre", "Rehabilitation centre", "therapy", THERAPY | _t("stay"), "rehab", "de-addiction"),
    )),
    Category("education", "Education & tutoring", "education", True, (
        _s("school", "School", "school", INSTITUTE, "cbse school", "matriculation school"),
        _s("preschool", "Preschool", "school", INSTITUTE, "play school", "kindergarten", "nursery school"),
        _s("tuition_centre", "Tuition centre", "tuition", INSTITUTE, "tuition", "tuitions",
           "tuition classes", "coaching centre"),
        _s("coaching", "Coaching (NEET / JEE)", "tuition", INSTITUTE, "neet coaching", "jee coaching",
           "competitive exams", "tnpsc coaching", "upsc coaching"),
        _s("language_school", "Language school", "tuition", INSTITUTE, "spoken english", "german classes",
           "hindi classes"),
        _s("music_school", "Music school", "arts_school", INSTITUTE, "music classes", "carnatic music",
           "keyboard classes", "guitar classes"),
        _s("dance_school", "Dance school", "arts_school", INSTITUTE, "dance classes", "bharatanatyam"),
        _s("coding_academy", "Coding academy", "tuition", INSTITUTE | _t("digital"), "coding classes",
           "programming classes"),
        _s("vocational_institute", "Vocational institute", "tuition", INSTITUTE, "iti", "skill training"),
        _s("driving_school", "Driving school", "tuition", INSTITUTE | _t("booking_led"), "driving classes",
           "driving training"),
        _s("tutor", "Individual tutor", "tutor", TUTOR, "home tutor", "maths tutor", "ielts tutor",
           "private tutor", "online tutor"),
        _s("online_educator", "Online educator", "creator", CREATOR, "online courses", "course seller"),
    )),
    Category("professional", "Professional & consulting services", "professional_service", False, (
        _s("ca", "Chartered accountant", "professional_firm", PRO | _t("subscription_led"), "ca firm",
           "auditor", "chartered accountants"),
        _s("accountant", "Accountant", "professional_firm", PRO | _t("subscription_led"), "accounting",
           "bookkeeping", "gst filing", "tax filing"),
        _s("lawyer", "Lawyer", "professional_firm", PRO, "advocate", "law firm", "legal services", "vakil"),
        _s("company_secretary", "Company secretary", "professional_firm", PRO, "cs firm"),
        _s("tax_consultant", "Tax consultant", "professional_firm", PRO, "income tax consultant", "itr filing"),
        _s("consultant", "Management / HR consultant", "consulting", CONSULT, "business consultant",
           "hr consultant", "management consultant"),
        _s("recruitment", "Recruitment agency", "consulting", CONSULT, "placement agency", "manpower consultancy"),
        _s("engineering_consultancy", "Engineering / ISO consultancy", "consulting", CONSULT,
           "iso consultant", "quality consultant", "process consultant"),
    )),
    Category("finance_insurance", "Finance & insurance", "professional_service", False, (
        _s("financial_adviser", "Financial adviser", "finance", PRO, "financial advisor",
           "financial planner", "mutual fund distributor"),
        _s("insurance_agent", "Insurance agent", "finance", PRO, "lic agent", "insurance advisor"),
        _s("loan_consultant", "Loan consultant", "finance", PRO, "loan agent", "home loans"),
        _s("wealth_manager", "Wealth manager", "finance", PRO, "wealth management"),
    )),
    Category("real_estate", "Real estate & property", "professional_service", True, (
        _s("developer", "Property developer", "real_estate_developer", PROPERTY, "builder", "builders",
           "promoters", "construction company", "apartment projects", "villa projects"),
        _s("plots", "Plots & layouts", "real_estate_developer", PROPERTY, "plot", "land", "layout",
           "dtcp plots", "plotted development"),
        _s("broker", "Real estate broker", "real_estate_broker", PROPERTY, "real estate agent",
           "property dealer", "estate agent", "realtor", "real estate agency"),
        _s("rental_agency", "Rental agency", "real_estate_broker", PROPERTY_RENT, "house rentals",
           "rental homes"),
        _s("property_management", "Property management", "real_estate_broker", PROPERTY_RENT,
           "facility rentals"),
        _s("co_living", "Co-living / PG", "stay", PROPERTY_RENT, "pg", "paying guest", "hostel for working",
           "co living"),
        _s("commercial_real_estate", "Commercial real estate", "real_estate_broker", PROPERTY | _t("b2b"),
           "office space", "commercial property"),
    )),
    Category("design_build", "Architecture, interiors & construction", "professional_service", True, (
        _s("architect", "Architect", "design_studio", DESIGN, "architecture firm", "architects",
           "architecture", "architecture practice", "architecture studio", "architectural"),
        _s("interior_designer", "Interior designer", "design_studio", DESIGN, "interiors", "interior design",
           "home interiors", "interior decorator"),
        _s("landscape_architect", "Landscape architect", "design_studio", DESIGN, "landscaping",
           "garden design"),
        _s("modular_kitchen", "Modular kitchens", "design_studio", DESIGN | _t("sells_products"),
           "modular kitchen", "wardrobes"),
        _s("renovation", "Renovation", "contractor", CONTRACTOR, "home renovation", "remodelling"),
        _s("civil_contractor", "Civil contractor", "contractor", CONTRACTOR, "construction contractor",
           "building contractor"),
        _s("electrical_contractor", "Electrical contractor", "contractor", CONTRACTOR, "electrical works"),
        _s("plumbing_contractor", "Plumbing contractor", "contractor", CONTRACTOR, "plumbing works"),
        _s("painting_contractor", "Painting contractor", "contractor", CONTRACTOR, "painters", "painting works"),
        _s("fabrication", "Fabrication", "contractor", CONTRACTOR, "steel fabrication", "welding works"),
        _s("waterproofing", "Waterproofing", "contractor", CONTRACTOR, "leak repair"),
        _s("hvac", "HVAC contractor", "contractor", CONTRACTOR, "ac installation", "ducting"),
    )),
    Category("home_services", "Home, repair & IT services", "professional_service", True, (
        _s("cleaning", "Cleaning service", "home_service", HOME_SERVICE, "home cleaning", "deep cleaning",
           "housekeeping"),
        _s("pest_control", "Pest control", "home_service", HOME_SERVICE, "termite control"),
        _s("plumber", "Plumber", "home_service", HOME_SERVICE, "plumbing"),
        _s("electrician", "Electrician", "home_service", HOME_SERVICE, "electrical repair"),
        _s("appliance_repair", "Appliance repair", "home_service", HOME_SERVICE, "washing machine repair",
           "fridge repair"),
        _s("ac_service", "AC service", "home_service", HOME_SERVICE | _t("subscription_led"), "ac repair",
           "ac servicing"),
        _s("water_purifier", "Water purifier service", "home_service", HOME_SERVICE, "ro service", "ro repair"),
        _s("laundry", "Laundry", "laundry", LAUNDRY, "laundromat", "washing and ironing", "ironing"),
        _s("dry_cleaning", "Dry cleaning", "laundry", LAUNDRY, "dry cleaners"),
        _s("gardening", "Gardening", "home_service", HOME_SERVICE, "gardener", "garden maintenance"),
        _s("repair_shop", "Repair shop", "repair", REPAIR, "watch repair", "shoe repair", "furniture repair"),
        _s("mobile_repair", "Mobile repair", "repair", REPAIR, "phone repair", "mobile service centre"),
        _s("computer_repair", "Computer repair", "repair", REPAIR, "laptop repair", "computer service"),
        _s("cctv", "CCTV installer", "home_service", HOME_SERVICE | _t("quote_led", "b2b"), "cctv",
           "security cameras"),
        _s("networking", "Networking / IT support", "home_service", HOME_SERVICE | _t("b2b"), "it support",
           "networking services"),
    )),
    Category("automotive", "Automotive", "retail", False, (
        _s("car_dealer", "Car dealer", "vehicle_dealer", DEALER, "car showroom", "car sales"),
        _s("used_cars", "Used cars", "vehicle_dealer", DEALER, "second hand cars", "pre-owned cars"),
        _s("bike_dealer", "Bike dealer", "vehicle_dealer", DEALER, "two wheeler showroom", "bike showroom"),
        _s("garage", "Garage / mechanic", "auto_service", GARAGE, "mechanic", "car service",
           "bike service", "workshop", "service centre"),
        _s("car_wash", "Car wash", "auto_service", GARAGE, "car washing", "bike wash"),
        _s("detailing", "Car detailing", "detailing", DETAILING, "detailing studio", "ceramic coating",
           "ppf", "car spa"),
        _s("tyres", "Tyres", "auto_parts", PARTS, "tyre shop", "tyre dealer", "wheel alignment"),
        _s("batteries", "Batteries", "auto_parts", PARTS, "battery shop", "inverter batteries"),
        _s("spare_parts", "Spare parts", "auto_parts", PARTS, "auto parts", "car accessories"),
        _s("car_rental", "Car rental", "rentals", RENTAL, "self drive cars", "car hire"),
        _s("driver_service", "Driver service", "rentals", RIDE, "acting drivers", "call driver"),
    )),
    Category("logistics", "Transport, logistics & storage", "professional_service", False, (
        _s("courier", "Courier", "logistics", FREIGHT, "courier service", "parcel service"),
        _s("packers_movers", "Packers & movers", "logistics", FREIGHT | _t("b2c"), "movers",
           "house shifting", "relocation"),
        _s("trucking", "Trucking", "logistics", FREIGHT, "lorry service", "transport company",
           "truck booking", "transporters"),
        _s("fleet_operator", "Fleet operator", "logistics", FREIGHT, "fleet"),
        _s("last_mile", "Last-mile delivery", "logistics", FREIGHT, "delivery company", "hyperlocal delivery"),
        _s("warehousing", "Warehousing", "logistics", FREIGHT - _t("on_site_service"), "warehouse",
           "godown", "storage"),
        _s("cold_storage", "Cold storage", "logistics", FREIGHT - _t("on_site_service"), "cold chain"),
        _s("freight_forwarding", "Freight forwarding", "logistics", FREIGHT, "freight forwarder",
           "customs clearance", "cha"),
        _s("taxi", "Taxi service", "rentals", RIDE, "cab service", "taxi", "call taxi", "travels"),
        _s("bus_operator", "Bus operator", "rentals", RIDE, "bus service", "omni bus"),
    )),
    Category("travel_stay", "Travel, stays & tourism", "hotel", True, (
        _s("hotel", "Hotel", "hotel", STAY | _t("walk_in"), "lodge", "hotel rooms", "business hotel"),
        _s("resort", "Resort", "hotel", STAY, "resorts", "farm stay resort", "estate stay", "plantation stay",
           "eco resort", "jungle resort", "nature resort"),
        _s("homestay", "Homestay", "homestay", STAY, "home stay", "bnb", "b&b", "cottage"),
        _s("hostel", "Hostel", "homestay", STAY, "backpackers hostel"),
        _s("villa_rental", "Villa rental", "homestay", STAY, "villa", "holiday home"),
        _s("travel_agency", "Travel agency", "travel", TOUR, "travels", "tours and travels", "ticketing"),
        _s("tour_operator", "Tour operator", "travel", TOUR, "tour packages", "holiday packages"),
        _s("adventure_tourism", "Adventure tourism", "travel", TOUR, "trekking", "adventure tours"),
        _s("guide", "Tour guide", "travel", TOUR, "local guide"),
        _s("pilgrimage_tours", "Pilgrimage tours", "travel", TOUR, "yatra", "temple tours"),
    )),
    Category("events", "Events & weddings", "professional_service", True, (
        _s("event_planner", "Event planner", "event_planner", EVENTS, "event management", "event organiser"),
        _s("wedding_planner", "Wedding planner", "event_planner", EVENTS, "wedding management",
           "wedding organiser"),
        _s("decorator", "Decorator", "event_planner", EVENTS, "event decor", "wedding decoration",
           "balloon decoration", "stage decoration"),
        _s("banquet_hall", "Mandapam / banquet hall", "banquet_hall", HALL, "mandapam", "marriage hall",
           "kalyana mandapam", "banquet", "party hall", "convention centre"),
        _s("florist", "Florist", "florist", FLORIST, "flower shop", "flowers", "bouquets", "poo kadai",
           "flower decoration"),
        _s("event_caterer", "Caterer", "catering", CATER, "caterer for events"),
        _s("dj", "DJ", "event_planner", EVENTS - _t("portfolio_led"), "dj services"),
        _s("sound_light_rental", "Sound & light rental", "rentals", RENTAL | _t("event_date"),
           "sound system rental", "lights rental"),
        _s("invitations", "Invitation business", "print_shop", PRINT, "wedding cards", "invitation cards"),
    )),
    Category("creative", "Photography, media & creative", "professional_service", True, (
        _s("wedding_photographer", "Wedding photographer", "photographer", PHOTO, "wedding photography",
           "candid photographer", "wedding shoots"),
        _s("studio_photographer", "Studio photographer", "photographer", PHOTO | _t("walk_in", "appointment"),
           "photo studio", "portrait studio"),
        _s("product_photographer", "Product photographer", "photographer", PHOTO | _t("b2b"),
           "product photography", "ecommerce photography"),
        _s("videographer", "Videographer", "photographer", PHOTO, "video production", "wedding films"),
        _s("filmmaker", "Filmmaker", "photographer", PHOTO | _t("b2b"), "film production", "ad films"),
        _s("drone", "Drone operator", "photographer", PHOTO, "drone shoots"),
        _s("ad_agency", "Ad / digital marketing agency", "creative_agency", AGENCY, "digital marketing",
           "seo agency", "social media agency", "advertising agency", "marketing agency"),
        _s("branding", "Branding studio", "creative_agency", AGENCY, "branding agency", "brand design"),
        _s("pr", "PR agency", "creative_agency", AGENCY, "public relations"),
        _s("content_studio", "Content studio", "creative_agency", AGENCY, "content creation"),
        _s("graphic_designer", "Graphic designer", "maker", MAKER, "logo designer", "designer"),
        _s("illustrator", "Illustrator / artist", "maker", MAKER, "artist", "painter", "illustrations",
           "commission art"),
        _s("ux_designer", "UX designer", "maker", MAKER, "ui designer", "product designer"),
        _s("writer", "Writer", "maker", MAKER, "copywriter", "content writer"),
        _s("musician", "Musician", "maker", MAKER | _t("event_date"), "singer", "band", "live music"),
    )),
    Category("creators", "Creators & personal brands", "professional_service", False, (
        _s("youtuber", "YouTuber / influencer", "creator", CREATOR, "influencer", "content creator",
           "instagrammer"),
        _s("coach", "Coach / speaker", "coach", COACH | _t("event_date"), "life coach", "business coach",
           "motivational speaker", "speaker"),
        _s("author", "Author", "creator", CREATOR, "writer (books)"),
        _s("podcaster", "Podcaster", "creator", CREATOR, "podcast"),
    )),
    Category("technology", "Technology & IT services", "professional_service", False, (
        _s("software_company", "Software company", "software", TECH, "software development",
           "it company", "software services"),
        _s("saas", "SaaS product", "software", TECH | _t("subscription_led", "b2c"), "saas",
           "software product", "app company", "mobile app", "gym app", "fitness app", "tracking app",
           "an app"),
        _s("web_development", "Web / app development", "software", TECH, "website design",
           "web design", "app development"),
        _s("cybersecurity", "Cybersecurity", "software", TECH, "security audit"),
        _s("cloud_data_ai", "Cloud / data / AI consultancy", "software", TECH, "ai consultancy",
           "data analytics", "cloud consulting"),
    )),
    Category("industrial", "Manufacturing & industrial supply", "retail", True, (
        _s("industrial_supplier", "Industrial supplier", "industrial_supplier", SUPPLY,
           "industrial supplies", "pumps", "valves", "motors", "bearings", "instrumentation",
           "safety equipment", "lab equipment", "automation", "machine tools", "pump supplier"),
        _s("chemicals", "Chemicals", "industrial_supplier", SUPPLY, "chemical supplier", "industrial chemicals"),
        _s("manufacturer", "Manufacturer", "manufacturer", FACTORY, "manufacturing", "factory",
           "garment manufacturer", "food manufacturer", "plastics", "auto components"),
        _s("metal_fabrication", "Metal fabrication", "manufacturer", FACTORY, "sheet metal", "cnc machining",
           "machining", "engineering works"),
        _s("process_equipment", "Process equipment / OEM", "manufacturer", FACTORY | _t("project_led"),
           "boilers", "compressors", "conveyors", "water treatment plants"),
        _s("packaging", "Packaging", "manufacturer", FACTORY, "corrugated boxes", "cartons", "labels",
           "packaging materials"),
        _s("printing", "Printing & signage", "print_shop", PRINT, "printing press", "digital printing",
           "flex printing", "signage", "sign boards", "laser cutting"),
    )),
    Category("trade", "Wholesale, distribution & import/export", "retail", False, (
        _s("distributor", "Distributor", "wholesale", TRADE, "distribution", "stockist",
           "dealer (wholesale)", "fmcg distributor", "super stockist"),
        _s("wholesaler", "Wholesaler", "wholesale", TRADE, "wholesale", "wholesale shop", "mandi"),
        _s("exporter", "Exporter", "wholesale", TRADE - _t("local_delivery"), "export house",
           "export", "garment exporter"),
        _s("importer", "Importer / trading company", "wholesale", TRADE, "trading company", "import"),
    )),
    Category("agriculture", "Agriculture & agri services", "retail", False, (
        _s("farm", "Farm", "farm", FARM, "farm fresh", "organic farm", "farmer"),
        _s("nursery", "Plant nursery", "farm", FARM - _t("subscription_led"), "plants", "nursery garden",
           "saplings"),
        _s("dairy_farm", "Dairy farm", "dairy_subscription", FARM, "cow farm", "a2 milk"),
        _s("poultry_farm", "Poultry farm", "farm", FARM | _t("b2b"), "poultry"),
        _s("fish_farm", "Fish farm", "farm", FARM, "aquaculture"),
        _s("mushroom_farm", "Mushroom farm", "farm", FARM, "mushrooms"),
        _s("agri_inputs", "Seeds, fertiliser & agri inputs", "agri_dealer", AGRI, "seeds", "fertiliser",
           "fertilizer", "pesticides", "agri shop"),
        _s("tractor_rental", "Tractor rental", "rentals", RENTAL | _t("on_site_service"), "tractor hire"),
    )),
    Category("energy_env", "Energy & environment", "professional_service", False, (
        _s("solar", "Solar installer", "energy", ENERGY, "solar panels", "solar epc", "rooftop solar"),
        _s("ev_charging", "EV charging", "energy", ENERGY, "ev chargers"),
        _s("generator_rental", "Generator rental", "rentals", RENTAL | _t("b2b"), "genset rental", "dg rental"),
        _s("waste_management", "Waste management", "energy", ENERGY | _t("subscription_led"),
           "recycling", "scrap", "composting"),
        _s("water_treatment", "Water treatment", "energy", ENERGY, "stp", "etp", "ro plants"),
    )),
    Category("pets", "Pets", "retail", False, (
        _s("pet_shop", "Pet shop", "pet_shop", PET_SHOP, "pet store", "aquarium shop", "pet food shop"),
        _s("grooming", "Pet grooming", "pet_care", PET_CARE, "dog grooming", "pet salon"),
        _s("boarding", "Pet boarding", "pet_care", PET_CARE, "dog boarding", "pet hostel"),
        _s("veterinary", "Veterinary clinic", "clinic", CLINIC, "vet", "vet clinic", "pet clinic",
           "animal hospital"),
        _s("pet_training", "Pet training", "pet_care", PET_CARE, "dog training", "dog trainer"),
        _s("dog_walking", "Dog walking", "pet_care", PET_CARE | _t("on_site_service"), "dog walker"),
    )),
    Category("care", "Child, family & senior care", "education", False, (
        _s("daycare", "Daycare", "daycare", DAYCARE, "creche", "day care", "baby care"),
        _s("activity_centre", "Activity centre", "daycare", DAYCARE, "kids activities", "summer camp",
           "hobby classes"),
        _s("kids_sports", "Kids sports", "daycare", DAYCARE, "football academy", "cricket academy",
           "swimming classes", "sports academy"),
        _s("elder_care", "Elder care", "care_service", CARE_HOME | _t("stay"), "old age home",
           "senior living", "assisted living"),
        _s("caregiver_agency", "Caregiver agency", "care_service", CARE_HOME, "caretakers", "nanny agency"),
    )),
    Category("rentals_spaces", "Rentals & spaces", "retail", False, (
        _s("vehicle_rental", "Bike / car rental", "rentals", RENTAL, "bike rental", "bike on rent", "scooter rental"),
        _s("camera_rental", "Camera & equipment rental", "rentals", RENTAL, "camera rental", "lens rental",
           "equipment rental"),
        _s("party_rental", "Party & furniture rental", "rentals", RENTAL | _t("event_date"),
           "party equipment", "chairs rental", "shamiana", "tent house"),
        _s("costume_rental", "Costume & dress rental", "rentals", RENTAL, "dress rental", "costume hire"),
        _s("coworking", "Co-working", "coworking", COWORK, "co working", "shared office", "hot desk"),
        _s("meeting_rooms", "Meeting rooms", "coworking", COWORK, "conference room", "training hall"),
        _s("self_storage", "Self-storage", "coworking", COWORK - _t("booking_led"), "storage units"),
    )),
    Category("security_staffing", "Security, facilities & staffing", "professional_service", False, (
        _s("security_agency", "Security agency", "security_facility", SECURITY, "security guards",
           "security services"),
        _s("fire_safety", "Fire safety", "security_facility", SECURITY, "fire extinguishers", "fire alarm"),
        _s("facility_management", "Facility management", "security_facility", SECURITY,
           "housekeeping contract", "commercial cleaning", "maintenance contracts"),
        _s("manpower", "Manpower supply", "security_facility", SECURITY, "manpower", "staffing",
           "temp staffing", "domestic help agency"),
    )),
    Category("labs", "Testing, research & labs", "professional_service", False, (
        _s("testing_lab", "Testing lab", "testing_lab", TESTLAB, "testing laboratory", "material testing",
           "water testing", "food testing"),
        _s("calibration_lab", "Calibration lab", "testing_lab", TESTLAB, "calibration"),
        _s("research", "R&D / contract research", "testing_lab", TESTLAB, "cro", "research lab"),
        _s("inspection", "Inspection agency", "testing_lab", TESTLAB, "third party inspection"),
    )),
    Category("community", "Clubs, communities & nonprofits", "other", False, (
        _s("club", "Club / association", "community", CLUB, "sports club", "association", "rotary",
           "chamber of commerce"),
        _s("temple_trust", "Temple / trust", "community", NGO | _t("booking_led", "event_date"),
           "temple", "trust", "kovil", "seva"),
        _s("cultural_centre", "Cultural centre", "community", CLUB, "sabha", "community hall"),
        _s("ngo", "NGO / charity", "ngo", NGO, "non profit", "nonprofit", "charity", "foundation",
           "animal rescue"),
    )),
    Category("other", "Something else", "other", False, (
        _s("other", "Something else", "other", _t(), "not sure", "other"),
    )),
)

# ----------------------------------------------------------------------------
# Subcategories the Capability Universe §4.2 lists as individually selectable
# that First Launch had folded into a broader entry (the broad entries stay, so
# nothing already saved changes meaning). Added 2026-09-27 (Phase B, P1-01).
MINORS = _t("minors_involved")
FIN = _t("finance_regulated")
_MORE: dict[str, tuple[Subcategory, ...]] = {
    "education": (
        _s("tutor_maths", "Maths tutor", "tutor", TUTOR | MINORS, "maths tuition", "math tutor"),
        _s("tutor_science", "Science tutor", "tutor", TUTOR | MINORS, "science tuition", "physics tutor",
           "chemistry tutor"),
        _s("tutor_german", "German tutor", "tutor", TUTOR, "german teacher", "german lessons"),
        _s("tutor_ielts", "IELTS tutor", "tutor", TUTOR, "ielts coaching", "ielts classes", "toefl"),
        _s("tutor_music", "Music tutor", "tutor", TUTOR | MINORS, "music teacher", "piano teacher",
           "veena teacher"),
        _s("tutor_art", "Art tutor", "tutor", TUTOR | MINORS, "drawing classes", "art teacher"),
    ),
    "professional": (
        _s("management_consultant", "Management consultant", "consulting", CONSULT, "strategy consultant"),
        _s("hr_consultant", "HR consultant", "consulting", CONSULT, "hr consultancy", "hr services"),
        _s("business_consultant", "Business consultant", "consulting", CONSULT, "business advisory"),
        _s("process_consultancy", "Process consultancy", "consulting", CONSULT, "lean consultant",
           "six sigma"),
        _s("iso_consultancy", "Quality / ISO consultancy", "consulting", CONSULT, "iso certification",
           "quality management"),
        _s("supply_chain_consultancy", "Supply-chain consultancy", "consulting", CONSULT,
           "logistics consultant", "supply chain consultant"),
    ),
    "finance_insurance": (
        _s("mortgage_broker", "Mortgage broker", "finance", PRO | FIN, "home loan broker", "mortgage"),
        _s("investment_adviser", "Investment adviser", "finance", PRO | FIN, "investment advisor",
           "sebi ria", "stock advisor"),
        _s("bookkeeping_service", "Bookkeeping service", "professional_firm", PRO | _t("subscription_led"),
           "bookkeeper", "accounts outsourcing"),
    ),
    "real_estate": (
        _s("real_estate_agency", "Real estate agency", "real_estate_broker", PROPERTY, "property agency"),
        _s("builder", "Builder", "real_estate_developer", PROPERTY, "house builder", "villa builder"),
        _s("apartment_projects", "Apartment projects", "real_estate_developer", PROPERTY, "flats",
           "apartments for sale", "gated community"),
    ),
    "design_build": (
        _s("furniture_designer", "Furniture designer", "design_studio", DESIGN | _t("sells_products",
           "made_to_order"), "custom furniture", "furniture design"),
        _s("roofing_contractor", "Roofing contractor", "contractor", CONTRACTOR, "roofing", "roof sheets"),
        _s("flooring_contractor", "Flooring contractor", "contractor", CONTRACTOR, "flooring", "tiling works"),
    ),
    "home_services": (
        _s("housekeeping", "Housekeeping", "home_service", HOME_SERVICE, "maid service", "house help"),
        _s("watch_repair", "Watch repair", "repair", REPAIR, "watch service"),
        _s("shoe_repair", "Shoe repair", "repair", REPAIR, "cobbler"),
        _s("jewellery_repair", "Jewellery repair", "repair", REPAIR, "jewellery polishing"),
        _s("furniture_repair", "Furniture repair", "repair", REPAIR, "carpenter", "sofa repair"),
        _s("electronics_repair", "Electronics repair", "repair", REPAIR, "tv repair", "electronics service"),
        _s("machinery_repair", "Machinery repair", "repair", REPAIR | _t("b2b", "on_site_service"),
           "machine repair", "motor rewinding"),
        _s("printer_service", "Printer service", "repair", REPAIR | _t("b2b"), "printer repair",
           "photocopier service"),
    ),
    "automotive": (
        _s("mechanic", "Mechanic", "auto_service", GARAGE, "two wheeler mechanic", "car mechanic"),
    ),
    "creative": (
        _s("film_editor", "Editor", "photographer", PHOTO | _t("digital"), "video editor", "film editor"),
        _s("digital_marketing", "Digital marketing", "creative_agency", AGENCY, "performance marketing"),
        _s("seo", "SEO", "creative_agency", AGENCY, "seo services", "search engine optimisation"),
        _s("social_media", "Social media agency", "creative_agency", AGENCY, "social media management"),
        _s("influencer_management", "Influencer management", "creative_agency", AGENCY,
           "influencer agency", "talent management"),
        _s("artist", "Artist", "maker", MAKER, "fine artist", "paintings", "sculptor"),
        _s("animator", "Animator", "maker", MAKER, "animation", "motion graphics"),
        _s("fashion_designer", "Fashion designer", "maker", MAKER | _t("sells_products"), "fashion design"),
    ),
    "creators": (
        _s("influencer", "Influencer", "creator", CREATOR, "instagram influencer"),
        _s("speaker", "Speaker", "coach", COACH | _t("event_date"), "keynote speaker", "trainer (corporate)"),
        _s("newsletter_creator", "Newsletter creator", "creator", CREATOR | _t("subscription_led"),
           "newsletter", "substack"),
    ),
    "technology": (
        _s("it_services", "IT services", "software", TECH, "it outsourcing", "managed it"),
        _s("data_ai_consultancy", "Data & AI consultancy", "software", TECH, "machine learning consultancy",
           "data science"),
    ),
    "industrial": tuple(
        _s(k, label, "industrial_supplier", SUPPLY, *syn) for k, label, *syn in (
            ("pumps", "Pumps", "pump dealer", "submersible pumps"),
            ("valves", "Valves", "valve supplier", "industrial valves"),
            ("motors", "Motors", "electric motors", "motor dealer"),
            ("bearings", "Bearings", "bearing dealer"),
            ("instrumentation", "Instrumentation", "gauges", "sensors", "flow meters"),
            ("lab_equipment", "Lab equipment", "laboratory equipment", "scientific instruments"),
            ("safety_equipment", "Safety equipment", "ppe", "safety shoes", "fire safety equipment"),
            ("electrical_panels", "Panels", "control panels", "electrical panels", "switchgear"),
            ("industrial_automation", "Automation", "plc", "industrial automation", "scada"),
            ("machine_tools", "Machine tools", "lathe", "cnc machines", "power tools"),
        )
    ) + tuple(
        _s(k, label, "manufacturer", FACTORY, *syn) for k, label, *syn in (
            ("food_manufacturer", "Food manufacturer", "food processing", "food factory"),
            ("textile_manufacturer", "Textile manufacturer", "textile mill", "weaving", "spinning mill"),
            ("garment_manufacturer", "Garment manufacturer", "garment factory", "apparel manufacturer"),
            ("plastics_manufacturer", "Plastics manufacturer", "plastic products", "injection moulding"),
            ("chemical_manufacturer", "Chemical manufacturer", "chemical plant"),
            ("pharma_manufacturer", "Pharma manufacturer", "pharmaceutical manufacturer", "drug manufacturer"),
            ("auto_component_manufacturer", "Auto-component manufacturer", "auto parts manufacturer"),
            ("machinery_manufacturer", "Machinery manufacturer", "machine manufacturer"),
            ("furniture_manufacturer", "Furniture manufacturer", "furniture factory"),
            ("packaging_manufacturer", "Packaging manufacturer", "packaging factory"),
        )
    ) + tuple(
        _s(k, label, "manufacturer", FACTORY | _t("project_led", "sells_services", "subscription_led"), *syn)
        for k, label, *syn in (
            ("boilers", "Boilers", "boiler manufacturer", "steam boilers"),
            ("compressors", "Compressors", "air compressors", "compressor dealer"),
            ("water_treatment_equipment", "Water treatment equipment", "ro plant manufacturer",
             "effluent treatment plant"),
            ("conveyors", "Conveyors", "conveyor systems", "material handling"),
        )
    ) + tuple(
        _s(k, label, "manufacturer", FACTORY, *syn) for k, label, *syn in (
            ("corrugated_boxes", "Corrugated boxes", "carton boxes", "corrugated box manufacturer"),
            ("labels", "Labels", "label printing", "stickers"),
            ("bottles", "Bottles", "pet bottles", "bottle manufacturer"),
            ("flexible_packaging", "Flexible packaging", "pouches", "laminated rolls"),
        )
    ) + tuple(
        _s(k, label, "print_shop", PRINT, *syn) for k, label, *syn in (
            ("printing_press", "Printing press", "offset printing", "press"),
            ("digital_printing", "Digital printing", "xerox", "print shop"),
            ("signage", "Signage", "sign boards", "name boards"),
            ("flex_printing", "Flex printing", "flex banners", "vinyl printing"),
            ("engraving", "Engraving", "laser engraving", "trophy engraving"),
            ("laser_cutting", "Laser cutting", "cnc laser", "acrylic cutting"),
        )
    ),
    "trade": tuple(
        _s(k, label, "wholesale", TRADE, *syn) for k, label, *syn in (
            ("fmcg_distributor", "FMCG distributor", "fmcg stockist"),
            ("pharma_distributor", "Pharma distributor", "medical distributor", "pharma stockist"),
            ("food_distributor", "Food distributor", "food wholesale"),
            ("electrical_distributor", "Electrical distributor", "electrical wholesale"),
            ("building_material_distributor", "Building-material distributor", "cement dealer",
             "steel dealer", "tiles wholesale"),
            ("industrial_distributor", "Industrial distributor", "industrial wholesale"),
        )
    ) + tuple(
        _s(k, label, "wholesale", TRADE - _t("local_delivery"), *syn) for k, label, *syn in (
            ("export_house", "Export house", "export company"),
            ("garment_exporter", "Garment exporter", "apparel exporter"),
            ("food_exporter", "Food exporter", "spice exporter", "rice exporter"),
            ("handicraft_exporter", "Handicraft exporter", "handicrafts export"),
            ("machinery_importer", "Machinery importer", "machine importer"),
            ("trading_company", "Trading company", "general trading", "traders"),
        )
    ),
    "agriculture": (
        _s("organic_farm", "Organic farm", "farm", FARM, "natural farming", "organic farming"),
        _s("hydroponics", "Hydroponics", "farm", FARM, "hydroponic farm", "microgreens"),
        _s("irrigation_services", "Irrigation services", "agri_dealer", AGRI | _t("on_site_service",
           "booking_led"), "drip irrigation", "sprinkler installation"),
        _s("farm_consultancy", "Farm consultancy", "agri_dealer", AGRI | _t("booking_led", "appointment"),
           "agri consultant", "farm advisor"),
        _s("seed_supplier", "Seed supplier", "agri_dealer", AGRI, "seed dealer", "seed shop"),
        _s("fertiliser_dealer", "Fertiliser dealer", "agri_dealer", AGRI, "fertilizer dealer", "urea dealer"),
        _s("agri_equipment_dealer", "Agri-equipment dealer", "agri_dealer", AGRI, "farm equipment",
           "tractor dealer", "sprayer dealer"),
    ),
    "energy_env": (
        _s("battery_storage", "Battery storage", "energy", ENERGY, "inverter installation", "battery backup"),
        _s("renewable_consultancy", "Renewable consultancy", "energy", ENERGY, "renewable energy consultant"),
        _s("recycling", "Recycling", "energy", ENERGY | _t("subscription_led"), "recycler", "e-waste"),
        _s("composting", "Composting", "energy", ENERGY | _t("subscription_led"), "compost", "organic waste"),
        _s("environmental_consultancy", "Environmental consultancy", "energy", ENERGY,
           "environmental consultant", "eia consultant"),
    ),
    "pets": (
        _s("pet_food", "Pet food", "pet_shop", PET_SHOP | _t("subscription_led"), "dog food", "cat food"),
        _s("pet_photography", "Pet photography", "photographer", PHOTO, "pet photographer"),
    ),
    "care": (
        _s("babysitting", "Babysitting", "care_service", CARE_HOME | MINORS, "babysitter", "nanny"),
        _s("play_school", "Play school", "daycare", DAYCARE, "playschool", "playgroup"),
        _s("maternity_services", "Maternity services", "care_service",
           _t("b2c", "sells_services", "booking_led", "appointment", "subscription_led", "health_regulated"),
           "prenatal classes", "lactation consultant", "doula"),
        _s("assisted_living", "Assisted living", "care_service", CARE_HOME | _t("stay"), "senior care home"),
    ),
    "rentals_spaces": (
        _s("bike_rental", "Bike rental", "rentals", RENTAL, "cycle rental", "bicycle rental"),
        _s("tool_rental", "Tool rental", "rentals", RENTAL, "tools on rent", "drill rental"),
        _s("construction_equipment_rental", "Construction-equipment rental", "rentals", RENTAL | _t("b2b"),
           "jcb rental", "scaffolding rental", "crane hire"),
        _s("furniture_rental", "Furniture rental", "rentals", RENTAL, "furniture on rent"),
        _s("dress_rental", "Dress rental", "rentals", RENTAL, "bridal lehenga rental", "suit rental"),
        _s("office_rental", "Office rental", "coworking", COWORK, "office space for rent", "serviced office"),
        _s("incubator", "Incubator", "coworking", COWORK, "startup incubator", "accelerator"),
        _s("document_storage", "Document storage", "coworking", COWORK - _t("booking_led"),
           "records storage", "archival storage"),
    ),
    "security_staffing": (
        _s("security_guards", "Guards", "security_facility", SECURITY, "watchman", "bouncers"),
        _s("alarm_systems", "Alarm systems", "security_facility", SECURITY, "burglar alarm", "intrusion alarm"),
        _s("commercial_cleaning", "Commercial cleaning", "security_facility", SECURITY, "office cleaning"),
        _s("maintenance_contracts", "Maintenance contracts", "security_facility", SECURITY,
           "annual maintenance", "building maintenance"),
        _s("building_management", "Building management", "security_facility", SECURITY,
           "apartment management", "society management"),
        _s("temp_staffing", "Temp staffing", "consulting", CONSULT, "temporary staff", "contract staffing"),
        _s("domestic_help_agency", "Domestic-help agency", "consulting", CONSULT, "maid agency",
           "cook agency"),
    ),
    "labs": (
        _s("contract_research", "Contract research", "testing_lab", TESTLAB, "clinical research"),
        _s("material_testing", "Material testing", "testing_lab", TESTLAB, "material testing lab"),
        _s("water_testing", "Water testing", "testing_lab", TESTLAB, "water testing lab"),
        _s("food_testing", "Food testing", "testing_lab", TESTLAB, "food testing lab", "fssai testing"),
        _s("environmental_testing", "Environmental testing", "testing_lab", TESTLAB, "air quality testing"),
    ),
    "community": (
        _s("sports_club", "Sports club", "community", CLUB, "cricket club", "badminton club"),
        _s("hobby_club", "Hobby club", "community", CLUB, "photography club", "book club"),
        _s("association", "Association", "community", CLUB, "residents association", "welfare association"),
        _s("chamber", "Chamber of commerce", "community", CLUB, "trade association", "business chamber"),
        _s("member_network", "Member network", "community", CLUB, "networking group", "alumni network"),
        _s("trust", "Trust", "community", NGO | _t("booking_led", "event_date"), "charitable trust"),
        _s("community_hall", "Community hall", "banquet_hall", HALL, "community centre hall"),
        _s("animal_rescue", "Animal rescue", "ngo", NGO, "animal shelter", "stray rescue"),
        _s("education_ngo", "Education NGO", "ngo", NGO | MINORS, "education charity"),
        _s("social_enterprise", "Social enterprise", "ngo", NGO | _t("sells_products", "order_led"),
           "impact enterprise"),
        _s("charity", "Charity", "ngo", NGO, "charitable organisation"),
    ),
}

# Default-trait corrections for First Launch entries so each family's Core
# modules follow from the traits (MD §2 rule 3); owner edits still win.
_TRAIT_PATCH: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "electronics": (_t("serialised"), _t()),
    "mobile_store": (_t("serialised"), _t()),
    "jewellery": (_t("stock_tracked"), _t()),
    "school": (MINORS, _t()), "preschool": (MINORS, _t()), "tuition_centre": (MINORS, _t()),
    "coaching": (MINORS, _t()), "music_school": (MINORS, _t()), "dance_school": (MINORS, _t()),
    "tutor": (MINORS, _t()), "kids_sports": (MINORS, _t()),
    "online_educator": (_t("order_led", "subscription_led"), _t()),
    "financial_adviser": (FIN, _t()), "insurance_agent": (FIN, _t()), "loan_consultant": (FIN, _t()),
    "wealth_manager": (FIN, _t()),
    "warehousing": (_t("subscription_led", "stock_tracked"), _t()),
    "cold_storage": (_t("subscription_led", "stock_tracked"), _t()),
    "self_storage": (_t("subscription_led"), _t()),
    "process_equipment": (_t("sells_services", "subscription_led"), _t()),
    "garage": (_t("stock_tracked"), _t()), "car_wash": (_t("subscription_led"), _t()),
    "veterinary": (_t("stock_tracked"), _t()),
    "hospital": (_t(), _t()),
    # §21.1 "Fruit, vegetable, dairy, egg sellers": daily subscriptions are Core.
    "fruit_shop": (_t("subscription_led"), _t()), "vegetable_shop": (_t("subscription_led"), _t()),
    "organic_produce": (_t("subscription_led"), _t()), "eggs": (_t("subscription_led"), _t()),
    "cloud_kitchen": (_t("subscription_led"), _t()),
    # §21.2 tailors / bridal / designer labels: fitting appointments.
    "boutique": (_t("booking_led", "appointment"), _t()), "designer_label": (_t("booking_led", "appointment"), _t()),
    # §21.9 CA / CS / tax firms run on retainers.
    "company_secretary": (_t("subscription_led"), _t()), "tax_consultant": (_t("subscription_led"), _t()),
    "renovation": (_t("site_visit"), _t()),
    "mechanic": (_t("stock_tracked"), _t()),
    # §21.8 tyres and batteries are fitted, not only sold.
    "tyres": (_t("sells_services", "booking_led", "appointment"), _t()),
    "batteries": (_t("sells_services", "booking_led", "appointment"), _t()),
    "cultural_centre": (_t("donation_led"), _t()),
}


def _extended() -> tuple[Category, ...]:
    from dataclasses import replace

    out = []
    for c in CATEGORIES:
        subs = []
        for sub in c.subcategories + _MORE.get(c.key, ()):
            add, remove = _TRAIT_PATCH.get(sub.key, (_t(), _t()))
            subs.append(replace(sub, traits=(sub.traits | add) - remove))
        out.append(replace(c, subcategories=tuple(subs)))
    return tuple(out)


CATEGORIES = _extended()

CATEGORIES_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}
SUBCATEGORIES: dict[str, tuple[Category, Subcategory]] = {
    s.key: (c, s) for c in CATEGORIES for s in c.subcategories
}


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s&/+-]", " ", (text or "").casefold())
    text = re.sub(r"\s*[/&+-]\s*", " ", text)
    return " ".join(text.split())


@lru_cache(maxsize=1)
def _index() -> tuple[tuple[str, str, int], ...]:
    """(phrase, subcategory key, weight) for every label and synonym."""
    rows: list[tuple[str, str, int]] = []
    for category in CATEGORIES:
        for sub in category.subcategories:
            rows.append((_norm(sub.label), sub.key, 3))
            rows.extend((_norm(s), sub.key, 2) for s in sub.synonyms)
            rows.append((_norm(category.label), sub.key, 0))
    return tuple(rows)


def _score(query: str, phrase: str) -> float:
    if not phrase:
        return 0.0
    if query == phrase:
        return 1.0
    words = query.split()
    phrase_words = phrase.split()
    ratio = SequenceMatcher(None, query, phrase).ratio()
    scores = [0.0]
    if phrase.startswith(query) and len(query) >= 3:
        scores.append(0.93)
    if all(any(pw.startswith(w) for pw in phrase_words) for w in words) and len(query) >= 3:
        scores.append(0.88)
    if any(w == pw for w in words for pw in phrase_words if len(w) >= 4):
        overlap = sum(1 for w in words if w in phrase_words) / max(len(phrase_words), len(words))
        scores.append(0.6 + 0.3 * overlap)
    # Spelling tolerance ("dentel clinic", "kirane", "biriyani"), word by word,
    # so "meat shop" is not a near-miss of "tea shop".
    if len(words) == len(phrase_words):
        pairs = [SequenceMatcher(None, w, pw).ratio() for w, pw in zip(words, phrase_words)]
        if min(pairs) >= 0.75:
            scores.append(sum(pairs) / len(pairs))
    best_word = max(
        (SequenceMatcher(None, w, pw).ratio() for w in words for pw in phrase_words if len(w) >= 4),
        default=0.0,
    )
    if best_word >= 0.84:
        scores.append(0.7 * best_word)
    # Closeness of the whole phrase breaks ties between equal heuristics:
    # "meat shop" is nearer "chicken shop" than "biryani shop".
    return max(scores) + (0.04 * ratio if max(scores) else 0.0)


def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Subcategories matching what the owner typed, best first. Deterministic."""
    q = _norm(query)
    if len(q) < 2:
        return []
    best: dict[str, float] = {}
    for phrase, key, weight in _index():
        score = _score(q, phrase)
        if score <= 0:
            continue
        score += weight * 0.01
        if score > best.get(key, 0.0):
            best[key] = score
    ranked = sorted(best.items(), key=lambda kv: (-round(kv[1], 4), _ORDER[kv[0]]))
    strong = [key for key, score in ranked if score >= 0.85]
    if not strong:
        return [describe(key) for key, score in ranked[:limit] if score >= 0.6]
    # After the clear matches, the neighbours an owner would also recognise:
    # "meat shop" offers butcher and chicken shop before "tea shop".
    siblings = [s.key for s in SUBCATEGORIES[strong[0]][0].subcategories if s.key not in strong]
    weaker = [key for key, score in ranked if 0.6 <= score < 0.85 and key not in siblings]
    return [describe(key) for key in (strong + siblings + weaker)[:limit]]


# Declared order: when a query only matches a category's name, its
# subcategories come back in the order the registry lists them.
_ORDER: dict[str, int] = {key: index for index, key in enumerate(SUBCATEGORIES)}


def describe(subcategory_key: str) -> dict[str, Any]:
    category, sub = SUBCATEGORIES[subcategory_key]
    return {
        "category_key": category.key,
        "category_label": category.label,
        "subcategory_key": sub.key,
        "subcategory_label": sub.label,
        "template": category.template,
        "playbook": sub.playbook,
    }


def tiles() -> list[dict[str, str]]:
    """The categories shown before the owner types anything."""
    return [{"category_key": c.key, "label": c.label} for c in CATEGORIES if c.tile]


def catalogue() -> dict[str, Any]:
    """Everything the picker, the traits editor and the Modules page need, from
    this one registry (§4.4: the frontend reads it through one endpoint and
    nothing is hard-coded twice)."""
    from platform_core.catalog.modules import MODULES, STOREFRONT
    from platform_core.catalog.recommendation import family_key_for
    from platform_core.services.business_classification import (
        GROUP_LABELS,
        ORG_SHAPE_LABELS,
        TRAIT_LABELS,
    )

    return {
        "version": TAXONOMY_VERSION,
        "tiles": tiles(),
        "categories": [
            {
                "key": c.key,
                "label": c.label,
                "subcategories": [
                    {"key": s.key, "label": s.label, "traits": sorted(s.traits),
                     "family": family_key_for(s.key, s.playbook)}
                    for s in c.subcategories
                ],
            }
            for c in CATEGORIES
        ],
        "trait_groups": [
            {"key": g, "label": GROUP_LABELS[g],
             "traits": [{"key": t, "label": TRAIT_LABELS[t]} for t in keys]}
            for g, keys in TRAIT_GROUPS.items()
        ],
        "org_shapes": [{"key": k, "label": v} for k, v in ORG_SHAPE_LABELS.items()],
        "storefront": list(STOREFRONT),
        "modules": [
            {"key": m.key, "label": m.label, "does": m.does, "phase": m.phase,
             "built": m.built, "future": m.future}
            for m in MODULES.values()
        ],
    }


def resolve(category_key: str | None, subcategory_key: str | None) -> tuple[Category, Subcategory] | None:
    """A validated (category, subcategory) pair, or None."""
    if subcategory_key and subcategory_key in SUBCATEGORIES:
        category, sub = SUBCATEGORIES[subcategory_key]
        if category_key and category_key != category.key:
            return None
        return category, sub
    if category_key and category_key in CATEGORIES_BY_KEY and not subcategory_key:
        category = CATEGORIES_BY_KEY[category_key]
        # A category alone says less than any of its subcategories: its most
        # common playbook as the seed, and no trait priors at all.
        playbooks = [s.playbook for s in category.subcategories]
        seed = max(set(playbooks), key=playbooks.count)
        return category, Subcategory(key=category.key, label=category.label, synonyms=(),
                                     traits=frozenset(), playbook=seed)
    return None


def _singular(text: str) -> str:
    """"wedding photographers" reads as "wedding photographer"; "glass" stays."""
    return " ".join(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
                    for w in text.split())


# What an owner *does* sometimes names the kind of business better than any
# noun they use: "we build villas" is a developer, not a villa rental; "we sell
# chicken, mutton and seafood" is a meat shop. Each is only a prior, shown as
# "Looks like…" and corrected with one tap — never a fact on the website.
_DOING: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (re.compile(r"\b(?:chicken|mutton|meat)\b[^.]{0,30}\b(?:shop|stall)\b", re.I), "meat_shop", 0.95),
    (re.compile(r"\bi (?:help|advise|work with)\b[^.]{0,80}\b(?:businesses|brands|companies|founders|startups|"
                r"owners)\b", re.I), "business_consultant", 0.8),
    (re.compile(r"\b(?:sell|selling|sold|supply)\w*\b[^.]{0,50}\b(?:chicken|mutton|seafood|prawns?|"
                r"fish|meat|crabs?|squid)\b", re.I), "meat_shop", 0.78),
    (re.compile(r"\b(?:chicken|mutton|seafood|meat)\b[^.]{0,40}\b(?:by (?:the )?kg|per kg|kilo)", re.I),
     "meat_shop", 0.78),
    (re.compile(r"\b(?:builds?|building|construct\w*|develop\w*)\b[^.]{0,30}\b(?:villas?|apartments?|"
                r"flats?|homes|houses|gated communit\w*)\b", re.I), "developer", 0.82),
    (re.compile(r"\b(?:sell|selling)\b[^.]{0,30}\b(?:plots?|layouts?)\b", re.I), "plots", 0.8),
    # Ten rooms and more is a hotel, or a resort on an estate or in the hills —
    # never a homestay because it also has cottages (owner lab: a 14-room
    # Coorg coffee-estate retreat was filed and greeted as "a homestay").
    (re.compile(r"\b[1-9]\d\s*-?\s*rooms?\b[^.]{0,80}\b(?:estates?|plantations?|coffee|tea|jungle|forest|valley|"
                r"cottages?|villas?|pool)\b", re.I), "resort", 0.84),
    (re.compile(r"\b[1-9]\d\s*-?\s*rooms?\b", re.I), "hotel", 0.8),
    (re.compile(r"\b(?:supply|supplies|supplying|manufactur\w*)\b[^.]{0,60}\b(?:factories|industr\w*|"
                r"plants?|oems?|fasteners|valves|bearings|pipes|fittings)\b", re.I), "industrial_supplier", 0.8),
    # "Free after-school learning centres for children, scholarships for girls.
    # Need online donations and volunteers" is an education charity, not a
    # school (certification: the NGO was asked which fee plans it sells).
    (re.compile(r"\b(?:free|scholarships?)\b[^.]{0,60}\b(?:learning|tuition|classes|education|study|children|"
                r"girls|kids)\b[^.]*(?:\.[^.]*){0,2}\b(?:donat\w*|donors?|volunteers?|fundrais\w*)\b", re.I),
     "education_ngo", 0.82),
    (re.compile(r"\b(?:donations?|donors?|fundrais\w*|volunteers?)\b", re.I), "charity", 0.74),
)
# "…a physiotherapy centre with a small gym": what comes after "with a small"
# is the lesser part of the business.
_SECONDARY = re.compile(r"\b(?:with|and|plus|also)\s+(?:a\s+|an\s+)?(?:small|little|tiny)?\s*$")
# "…and a small in-house lab for blood tests": a part of the business, not its kind.
_IN_HOUSE = re.compile(r"\b(?:in house|inhouse)\s+(?:\w+\s+){0,3}$")
# What the business works on, sits beside or buys from is not what it is:
# "we design homes and small hotels" is an architect, "near the temple" is
# a place, "from one supplier farm" is a supplier (owner personas, 2026-11-13).
_SOMEONE_ELSES = re.compile(
    r"\b(?:design|designs|designing|designed|build|builds|building|built|near|beside|opposite|behind|"
    r"from|into|supplier|suppliers|including|across)\s+(?:\w+\s+){0,4}$")
# "…is a bakery", "we run a small salon": the plainest way an owner names the kind.
_NAMED_AS = re.compile(
    r"\b(?:is|are|am|run|runs|running|have|own|owns|started|opened)\s+(?:a|an|the|our|my)?\s*(?:\w+\s+){0,3}$")
# A word used for HOW they work, not WHAT they are: "we courier them" is a
# pickle maker that ships, not a courier company.
_MEANS: dict[str, re.Pattern[str]] = {
    # "book a site visit" is a verb, not a bookshop.
    "books": re.compile(r"\bbook(?:s|ed|ing)?\s+(?:a|an|the|your|their|our|now|online|appointments?|slots?|"
                        r"tables?|trials?|site|visits?|sessions?|classes|rooms?|dates?|tickets?)\b", re.I),
    "taxi": re.compile(r"\bwe travel\b|\btravel (?:anywhere|across|all over)", re.I),
    "courier": re.compile(r"\b(?:by|via|through)\s+courier|\bcouriers?\s+(?:them|it|across|to|all|"
                          r"everywhere|anywhere|orders?)\b|\b(?:and|we)\s+courier\b", re.I),
}


# ----------------------------------------------------------------- spelling
# Owners type on a phone, fast, in their second or third language: "kichen",
# "resturant", "bekary", "tution", "mobail shop", "gymm". A trade word spelt
# wrong is still the trade. Found on a real owner run (2026-11-13): "pepper
# vine kichen … we make kerala food biriyani appam" was filed as "other", so
# its dishes were imported as bookable services and its website could not take
# an order. The repair is deliberately narrow — a word is only read as a trade
# word when it is not a word of its own and differs from that trade word the
# way a slip does (vowels, a doubled or dropped letter) — and it is checked
# against every certification persona so clean sentences are left alone.

# The slips owners actually make on the words that name a trade, each one seen
# in an interview or a certification persona. A general spell-checker was tried
# and thrown away the same day: without a dictionary it "corrected" real words
# ("stuff" to "staff", "message" to "massage") and misfiled two businesses.
_SLIPS: dict[str, str] = {
    slip: word
    for word, slips in {
        "restaurant": "resturant restarant restaurent resturent restrant restorent restaraunt resturaunt restraunt",
        "kitchen": "kichen kitchn kithcen kitchan kitchin",
        "bakery": "bekary bakary backery bekery bakry",
        "parlour": "parler parlur parlar",
        "tuition": "tution tutions tuision tutition",
        "grocery": "grocary grosery grossery grocry",
        "boutique": "boutiqe botique butique boutiq botiq",
        "tailoring": "tailering tailoring tailaring",
        "tailor": "tailer taylor tailar",
        "physiotherapy": "physiotherpy phisiotherapy physiotheraphy physiotheropy fisiotherapy",
        "photography": "photografy fotography photograpy photogrphy",
        "photographer": "photografer fotographer photograper",
        "mobile": "mobail mobil moble",
        "dental": "dentel dentl",
        "coaching": "coching coachng",
        "clinic": "clinc clinik clenic",
        "hospital": "hospitel hosptal hospitl",
        "pharmacy": "pharmasy farmacy pharmecy",
        "jewellery": "jewelery jwellery jewellry jwelery",
        "hotel": "hotal hotl",
        "catering": "catring cattering caterng",
        "consultant": "consultent consltant consultnt",
        "consulting": "consultng consalting",
        "architect": "archtect architec archetect",
        "architects": "archtects architecs",
        "beauty": "beuty beauti buety",
        "fitness": "fitnes fittness",
        "furniture": "furnitur furnture furniter",
        "electronics": "electonics electronic electroniks",
        "stationery": "stationry stationary",
        "supermarket": "supermaket supermarkt",
        "textile": "textail textil",
        "garments": "garmets garmants",
        "academy": "acadamy acadmy",
        "institute": "institue instute",
        "coffee": "cofee coffe",
        "cottage": "cotage cottege",
        "vegetables": "vegitables vegetabls",
        "sweets": "sweats",
        "laundry": "laundary londry",
        "nursery": "nursary",
        "accessories": "accesories acessories",
        "cosmetics": "cosmatics",
        "ayurveda": "ayurvedha ayurved",
        "driving": "drivng",
        "repair": "repar repiar",
        "service": "servise",
        "biryani": "biriyani briyani biriani biryni",
    }.items()
    for slip in slips.split()
}
_DOUBLED = re.compile(r"(.)\1+")


def _one_slip(a: str, b: str) -> bool:
    """One letter missing, extra, wrong or swapped — and not near the end
    (where "designed" / "designer" and "properly" / "property" are real words)."""
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if i >= min(len(a), len(b)) - 2:
        return False
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:] or (a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:])
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer[i + 1:] == shorter[i:]


@lru_cache(maxsize=1)
def _trade_words() -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    """(every word of every label and synonym, the long ones by first letter)."""
    words = {w for phrase, _key, weight in _index() if weight for w in _singular(phrase).split()}
    words |= {w for phrase, _key, weight in _index() if weight for w in phrase.split()}
    by_letter: dict[str, list[str]] = {}
    for word in sorted(words):
        if len(word) >= 8 and word.isalpha():
            by_letter.setdefault(word[0], []).append(word)
    return frozenset(words), {k: tuple(v) for k, v in by_letter.items()}


def _respell(token: str) -> str:
    """The trade word a misspelt token is, or the token itself."""
    known, by_letter = _trade_words()
    if token in _SLIPS and token not in known:
        return _SLIPS[token]
    if len(token) < 4 or not token.isalpha() or token in known:
        return token
    collapsed = _DOUBLED.sub(lambda m: m.group(1), token)
    if collapsed != token and collapsed in known and (
            len(collapsed) >= 5 or (len(collapsed) >= 3 and token[-1] == token[-2])):
        return collapsed  # "gymm" — never "noon", which is a word of its own
    if len(token) >= 8:
        # A long word one slip from a long trade word: at this length a real
        # word of its own is rare ("restarant").
        close = [w for w in by_letter.get(token[0], ()) if _one_slip(token, w)]
        if len(close) == 1:
            return close[0]
    return token


def respell(text: str) -> str:
    """An owner's sentence with its misspelt trade words put right; nothing else changes."""
    return " ".join(_respell(token) for token in _norm(text).split())


# What is cooked and served, in the words owners use for it. Two of these in a
# sentence, or one after "we make / cook / serve", is a kitchen — whatever it
# calls itself.
_DISHES = (
    r"biri?yanis?|dosas?|dosai|idl[iy]s?|vadas?|pongal|upma|poori|puri|parottas?|porottas?|"
    r"chapat[ih]i?s?|rotis?|naans?|meals|thalis?|curr(?:y|ies)|appams?|puttu|idiyappam|fried rice|"
    r"noodles|momos?|shawarma|kebabs?|tandoori|pulao|sambar|rasam|kurma|korma|gravy|tiffins?|"
    r"chaats?|pani ?puri|samosas?|pav bhaji|pizzas?|burgers?|sandwich(?:es)?|stew|"
    r"payasam|halwa|mandi|kothu"
)
_COOKS = re.compile(
    r"\b(?:make|makes|making|cook|cooks|cooking|serve|serves|serving|prepare|prepares)\b[^.]{0,60}\b"
    r"(?:food|dishes|lunch|dinner|breakfast|" + _DISHES + r")\b", re.I)
_DISH = re.compile(r"\b(?:" + _DISHES + r")\b", re.I)
_BAKES = re.compile(r"\b(?:make|makes|making|bake|bakes|baking)\b[^.]{0,40}\b(?:cakes?|cupcakes?|brownies|"
                    r"cookies|pastr(?:y|ies)|breads?)\b", re.I)
_FROM_HOME = re.compile(r"\b(?:from|at) (?:my |our )?home\b|\bhome ?made\b|\bhome ?based\b", re.I)
_TIFFIN = re.compile(r"\btiffin (?:cent(?:re|er)|shop|stall|kadai|room)\b", re.I)


_WE_COOK = re.compile(r"\b(?:we|i) cook\b", re.I)


def _kitchen(text: str) -> tuple[str, float] | None:
    """A food business read from what it cooks, when no trade word named it."""
    if _BAKES.search(text):
        return ("home_bakery", 0.78) if _FROM_HOME.search(text) else ("bakery", 0.76)
    dishes = {m.group(0).casefold() for m in _DISH.finditer(text)}
    if _COOKS.search(text) or len(dishes) >= 2 or _TIFFIN.search(text):
        if _FROM_HOME.search(text):
            return "home_kitchen", 0.78
        return "restaurant", 0.76
    return None


def infer_from_text(text: str) -> tuple[str, float] | None:
    """The subcategory an owner's own words most clearly name, with a confidence.

    Used only as a seed when the owner did not pick one — never shown as fact.
    Whole-phrase matches only, so "customers" never reads as "custom". Read as
    written first; if nothing is named, once more with misspelt trade words put
    right, and last from what the business cooks.
    """
    found = _infer(text)
    if found is None:
        fixed = respell(text)
        if fixed != _norm(text):
            found = _infer(fixed)
    kitchen = _kitchen(text or "")
    if kitchen and (found is None or found[1] < 0.72 or (found[1] < kitchen[1] and (
            _is_food(found[0]) or _WE_COOK.search(text or "")))):
        # One dish named among several ("biriyani appam stew meals") is a
        # kitchen that cooks them all, not a biryani shop.
        found = kitchen
    return found


def _is_food(subcategory_key: str) -> bool:
    return SUBCATEGORIES[subcategory_key][0].key in {"home_food", "food_service"}


def _infer(text: str) -> tuple[str, float] | None:
    haystack = f" {_singular(_norm(text))} "
    if len(haystack) < 4:
        return None
    best: tuple[str, float] | None = None
    for phrase, key, weight in _index():
        if weight == 0 or len(phrase) < 3:
            continue
        at = haystack.find(f" {_singular(phrase)} ")
        means = _MEANS.get(key)
        if at >= 0 and not (means and means.search(text or "")):
            # The longer phrase is the more specific reading: "gym app" is a
            # software business, not a gym. Between equals, the first said.
            score = 0.6 + 0.08 * len(phrase.split()) + weight * 0.03
            before = haystack[:at + 1]
            if _SECONDARY.search(before) or _IN_HOUSE.search(before):
                score -= 0.12
            if _SOMEONE_ELSES.search(before):
                score -= 0.15
            elif _NAMED_AS.search(before):
                score += 0.05
            if best is None or score > best[1]:
                best = (key, score)
    for pattern, key, confidence in _DOING:
        if pattern.search(text or "") and (best is None or confidence >= best[1] - 1e-9):
            best = (key, confidence)
    if best is None:
        # Tamil script is not in the latin index: a few trade words an owner
        # writing Tamil actually uses.
        for word, key in _TAMIL_TRADES:
            if word in (text or ""):
                return key, 0.76
    return best


_TAMIL_TRADES: tuple[tuple[str, str], ...] = (
    ("சலூன்", "salon"), ("பியூட்டி பார்லர்", "salon"), ("ஜிம்", "gym"),
    ("கறிக்கடை", "meat_shop"), ("இறைச்சி", "meat_shop"), ("மீன் கடை", "fish_market"),
    ("உணவகம்", "restaurant"), ("ஹோட்டல்", "restaurant"), ("பேக்கரி", "bakery"),
    ("மருத்துவமனை", "hospital"), ("கிளினிக்", "clinic"), ("டியூஷன்", "tuition_centre"),
    ("தையல்", "tailor"), ("மளிகை", "grocery"), ("ஊறுகாய்", "pickles_podi"),
)
