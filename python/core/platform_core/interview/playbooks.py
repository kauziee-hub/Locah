"""Trade knowledge: how an expert in each kind of business would talk to its owner.

This is Locah's memory of many businesses (Capability Universe §21 sector
playbooks, §22 operating models), kept as data:

* the questions an experienced person in the trade would ask, in the trade's
  own words ("Do people choose the cut too — curry cut, boneless?");
* what visitors browse (cuts, dishes, treatments, projects, plans…) and what
  the website calls it;
* what matters on this kind of site: real work photos for a photographer, the
  story for a home kitchen, the RFQ path for an industrial supplier;
* what is never worth asking this trade (delivery for a clinic).

A playbook is a **prior**. It decides which question is worth asking and how
to phrase it; it never becomes a fact about the business. Only what the owner
says is kept as truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from platform_core.catalog.taxonomy import SUBCATEGORIES, infer_from_text, resolve
from platform_core.interview.models import BusinessBlueprint

MediaImportance = str  # "critical" | "high" | "medium" | "low"


@dataclass(frozen=True)
class Playbook:
    key: str
    noun: str  # what visitors choose between, plural, owner-facing
    offer_kind: str  # Capability Universe §6.3
    browse_label: str  # navigation label for the browse section
    browse_title: str  # its heading
    media: MediaImportance = "medium"
    portfolio: bool = False
    story_matters: bool = False
    price_visibility: str = "show"  # show | from | on_request
    families: tuple[str, ...] = ("local_friendly",)
    # Expert phrasing per ask id: {"en": ..., "ta_en": ..., "ta": ...}.
    asks: dict[str, dict[str, str]] = field(default_factory=dict)
    # Discovery targets raised to high value for this trade, or never asked.
    elevate: frozenset[str] = frozenset()
    skip: frozenset[str] = frozenset()
    # What the owner most often means by "the main thing customers do" —
    # used only to phrase a question, never shown as the owner's answer.
    likely_actions: tuple[str, ...] = ()
    # A trade whose website is built around booking time with someone or
    # something (an appointment, a class, a room, a slot) — "book a pickup"
    # from a transporter is not that.
    booking_led: bool = False


# A stay keeps check-in and check-out times, not opening hours.
_STAY_HOURS = {"en": "When can guests check in, and by when should they check out?",
                 "ta_en": "Guests eppo check-in pannalaam, eppo-kulla check-out pannanum?",
                 "ta": "விருந்தினர்கள் எப்போது செக்-இன் செய்யலாம், எப்போதுக்குள் செக்-அவுட் செய்ய வேண்டும்?"}


def _p(
    key: str,
    noun: str,
    offer_kind: str,
    browse_label: str,
    browse_title: str,
    *,
    asks: dict[str, dict[str, str]] | None = None,
    elevate: tuple[str, ...] = (),
    skip: tuple[str, ...] = (),
    **kw: Any,
) -> Playbook:
    return Playbook(key, noun, offer_kind, browse_label, browse_title, asks=asks or {},
                    elevate=frozenset(elevate), skip=frozenset(skip), **kw)


_NO_DELIVERY = ("fulfilment.mode", "fulfilment.area", "fulfilment.operator", "offerings.units",
                "operations.stock")

PLAYBOOKS: dict[str, Playbook] = {p.key: p for p in (
    _p("meat_seafood", "cuts and seafood", "weighed_product", "Shop", "Shop by category",
       media="high", price_visibility="show", families=("modern_commerce", "local_friendly", "premium_dark"),
       likely_actions=("order_whatsapp", "order_online", "call"),
       asks={
           "offer": {"en": "Which meats and seafood do you keep — chicken, mutton, fish, prawns?",
                     "ta_en": "Enna enna meat, seafood vechirukkeenga — chicken, mutton, fish, prawns?"},
           "structure": {"en": "Do people choose the cut too — curry cut, boneless, biryani cut — and do they "
                               "order by the kg or in fixed packs?",
                         "ta_en": "Customers cut select pannuvaangalaa — curry cut, boneless, biryani cut? "
                                  "Kg-la order-aa, illa fixed packs-aa?"},
           "conversion": {"en": "How do people usually order — WhatsApp, a call, or would you like them to "
                                "order on the website?",
                          "ta_en": "Customers eppadi order pannuvaanga — WhatsApp-aa, call-aa, illa "
                                   "website-laye order pannanumaa?"},
           "fulfilment": {"en": "Do you deliver, or do people pick up from the shop — and roughly which areas "
                                "do you deliver to?",
                          "ta_en": "Neenga deliver pannuveengalaa, illa shop-la pickup-aa? Deliver-na endha "
                                   "areas-ku?"},
           "story": {"en": "What should people know about your meat — when stock comes in, how it's cut and "
                           "cleaned?",
                     "ta_en": "Unga meat pathi customers enna theriyanum — stock eppo varum, eppadi cut "
                              "panni clean pannureenga?"},
       }),
    _p("produce", "fruits and vegetables", "weighed_product", "Shop", "Fresh today",
       media="medium", families=("local_friendly", "modern_commerce"),
       likely_actions=("order_whatsapp", "visit"),
       asks={"structure": {"en": "Do people order by the kg, or do you sell fixed packs or baskets?"}}),
    _p("grocery", "products", "product", "Shop", "Shop by category", media="low",
       families=("modern_commerce", "local_friendly"), likely_actions=("order_whatsapp", "visit"),
       asks={
           "offer": {"en": "Which sections of the store should people see first — staples, snacks, dairy, "
                           "household?"},
           "conversion": {"en": "Do regulars send their list on WhatsApp, call, or come in — and would you "
                                "like them to order on the website?"},
           "fulfilment": {"en": "Do you home-deliver, and roughly how far from the store?"},
       }),
    _p("dairy_subscription", "products and plans", "plan", "Plans", "Daily delivery",
       media="low", families=("local_friendly", "modern_commerce"), likely_actions=("subscribe", "whatsapp"),
       elevate=("memberships.plans",),
       asks={"plans": {"en": "Do people take a daily subscription — say half a litre every morning — or "
                             "order when they need?"}}),
    _p("home_food", "dishes", "menu_item", "Menu", "What's cooking", media="high", story_matters=True,
       families=("editorial_warm", "playful_editorial"), likely_actions=("order_whatsapp", "call"),
       elevate=("brand.story",),
       asks={
           "offer": {"en": "What do you cook most — which dishes or items should people see first?",
                     "ta_en": "Neenga adhigama enna samaippeenga — endha dishes first-a kaatanum?"},
           "structure": {"en": "Is it a daily menu, or do people pre-order for a set day?",
                         "ta_en": "Daily menu-aa, illa oru naal munnaadi pre-order pannanumaa?"},
           "conversion": {"en": "How do people order today — WhatsApp, a call, or Instagram?",
                          "ta_en": "Ippo eppadi order varudhu — WhatsApp-aa, call-aa, Instagram-aa?"},
           "fulfilment": {"en": "Do they pick up from your home, or do you deliver — and which areas?",
                          "ta_en": "Veetla vandhu vaanguvaangalaa, illa neenga deliver pannuveengalaa — "
                                   "endha areas?"},
           "story": {"en": "What makes it home-style — whose recipes, what's cooked fresh each day?",
                     "ta_en": "Idhu home-style-nu eppadi solradhu — yaaroda recipes, dhinamum fresh-aa enna "
                              "samaippeenga?"},
       }),
    _p("tiffin", "meals and plans", "plan", "Plans", "Meal plans", media="medium", story_matters=True,
       families=("editorial_warm", "local_friendly"), likely_actions=("subscribe", "order_whatsapp"),
       elevate=("memberships.plans",),
       asks={
           "plans": {"en": "Do people subscribe weekly or monthly — and can they skip days or choose veg / "
                           "non-veg?",
                     "ta_en": "Weekly-aa monthly-aa subscribe pannuvaangalaa — veg / non-veg choose "
                              "pannalaamaa, naal skip pannalaamaa?"},
           "fulfilment": {"en": "Which areas do you deliver lunch or dinner to?"},
       }),
    _p("bakery_sweets", "cakes and bakes", "product", "Menu", "From our oven", media="high",
       story_matters=True, families=("playful_editorial", "editorial_warm"),
       likely_actions=("order_whatsapp", "visit", "call"), elevate=("offerings.customisation",),
       asks={
           "customisation": {"en": "Do you take custom cake orders — for a date, with a message or a photo — "
                                   "and how early should people order?",
                             "ta_en": "Custom cake order edupeengalaa — date, message, photo-voda? Evlo "
                                      "naal munnaadi order pannanum?"},
           "fulfilment": {"en": "Do people collect from the shop, or do you deliver too?"},
       }),
    _p("restaurant", "dishes", "menu_item", "Menu", "Our menu", media="high", story_matters=True,
       families=("editorial_warm", "premium_dark", "local_friendly"), skip=("offerings.units", "operations.stock"),
       likely_actions=("book_table", "order_call", "visit"),
       asks={
           "offer": {"en": "What are you known for — which dishes should people see first?",
                     "ta_en": "Unga special enna — endha dishes first-a kaatanum?"},
           "conversion": {"en": "Do most people come in to eat, book a table, or order takeaway and delivery?",
                          "ta_en": "Adhigama customers vandhu saapiduvaangalaa, table book pannuvaangalaa, "
                                   "illa takeaway / delivery-aa?"},
           "fulfilment": {"en": "Do you deliver yourselves, or is takeaway enough for now?"},
       }),
    _p("cafe", "drinks and bites", "menu_item", "Menu", "On the menu", media="high",
       families=("playful_editorial", "editorial_warm"), skip=("offerings.units", "operations.stock"),
       likely_actions=("visit", "order_call"),
       asks={"conversion": {"en": "Is it mostly people dropping in, or do they order ahead or on delivery apps?"}}),
    _p("catering", "menus and events", "package", "Menus", "Menus for every occasion", media="high",
       story_matters=True, price_visibility="on_request", families=("editorial_warm", "premium_dark"),
       skip=("offerings.units", "operations.stock", "fulfilment.mode"),
       likely_actions=("request_quote", "whatsapp", "call"),
       asks={
           "offer": {"en": "Mostly weddings and family functions, or corporate lunches and events?",
                     "ta_en": "Adhigama kalyaanam, functions-aa, illa corporate lunch / events-aa?"},
           "conversion": {"en": "Do people usually ask for a menu and a per-plate quote first — with the date "
                                "and guest count?",
                          "ta_en": "Mudhalla menu, per-plate quote kepaangalaa — date, guest count-oda?"},
           "fulfilment": {"en": "Which cities or areas do you cater in?"},
       }),
    _p("fashion_retail", "collections", "product", "Shop", "New in", media="high",
       families=("modern_commerce", "editorial_warm"), likely_actions=("visit", "order_whatsapp"),
       asks={"conversion": {"en": "Do people come to the store, ask for photos on WhatsApp, or should they buy "
                                  "on the website?"},
             "fulfilment": {"en": "Do you ship outside the city, or is it store pickup and local delivery?"}}),
    _p("jewellery", "collections", "product", "Collections", "Collections", media="high",
       price_visibility="on_request", families=("premium_dark", "editorial_warm"),
       skip=("offerings.units", "operations.stock", "fulfilment.mode"),
       likely_actions=("visit", "whatsapp"),
       asks={
           "offer": {"en": "Which collections should people see first — bridal, daily wear, gold, silver, "
                           "diamonds?"},
           "conversion": {"en": "Do people come to the store to see pieces, or ask for photos on WhatsApp "
                                "first — and do you take custom orders?",
                          "ta_en": "Customers kadaikku vandhu paarppaangalaa, illa WhatsApp-la photo "
                                   "kepaangalaa? Custom order edupeengalaa?"},
       }),
    _p("general_retail", "products", "product", "Shop", "Shop by category", media="medium",
       families=("modern_commerce", "local_friendly"), likely_actions=("visit", "order_whatsapp")),
    _p("electronics", "products", "product", "Shop", "Shop by category", media="medium",
       families=("modern_commerce", "technical_b2b"), likely_actions=("visit", "call")),
    _p("furniture_decor", "pieces", "product", "Collections", "Collections", media="high",
       price_visibility="from", families=("editorial_warm", "airy_property"),
       likely_actions=("visit", "whatsapp"), elevate=("offerings.customisation",),
       asks={"customisation": {"en": "Is it ready stock, made to order, or both — and do you deliver and fit it?"}}),
    _p("optical", "eyewear", "product", "Shop", "Frames & lenses", media="medium",
       families=("calm_professional", "modern_commerce"), likely_actions=("visit", "book_online")),
    _p("pet_shop", "products", "product", "Shop", "Shop for your pet", media="medium",
       families=("playful_editorial", "local_friendly"), likely_actions=("visit", "order_whatsapp")),
    _p("boutique", "collections", "product", "Collections", "Collections", media="critical",
       story_matters=True, price_visibility="on_request", families=("editorial_warm", "portfolio_sketchbook"),
       skip=("offerings.units", "operations.stock"), likely_actions=("whatsapp", "visit"),
       elevate=("offerings.customisation", "media.photos"),
       asks={"customisation": {"en": "Do people buy ready pieces, or is most of it made to measure — and how "
                                     "long before the date should they come?"},
             "photos": {"en": "Do you have photos of your pieces to show? Real ones make this kind of site."}}),
    _p("tailoring", "services", "service", "Services", "What we stitch", media="medium",
       families=("local_friendly", "editorial_warm"), skip=("offerings.units", "operations.stock", "fulfilment.mode"),
       likely_actions=("visit", "whatsapp"),
       asks={"conversion": {"en": "Do people walk in to give measurements, or book a fitting first?"}}),
    _p("uniform_b2b", "product lines", "product", "Products", "What we make", media="medium",
       price_visibility="on_request", families=("technical_b2b", "modern_commerce"),
       skip=("offerings.units", "operations.stock"), likely_actions=("request_quote", "whatsapp")),
    _p("handmade", "pieces", "product", "Shop", "Made by hand", media="critical", story_matters=True,
       families=("portfolio_sketchbook", "editorial_warm"), likely_actions=("order_whatsapp", "enquire"),
       elevate=("media.photos",)),
    _p("salon", "services", "service", "Services", "Services", media="high",
       booking_led=True,
       families=("premium_dark", "calm_professional", "playful_editorial"), skip=_NO_DELIVERY,
       likely_actions=("book_online", "book_whatsapp", "call"),
       asks={
           "conversion": {"en": "Do people book an appointment first, or mostly walk in — and should they "
                                "book on the website or on WhatsApp?",
                          "ta_en": "Customers appointment book pannuvaangalaa, illa walk-in-aa? Website-laye "
                                   "book pannanumaa, illa WhatsApp-laa?"},
           "bookings": {"en": "Do people usually ask for a particular stylist, or whoever is free?",
                        "ta_en": "Customers oru particular stylist kepaangalaa, illa yaar free-o avangalaa?"},
       }),
    _p("spa", "treatments", "service", "Treatments", "Treatments", media="high",
       booking_led=True,
       families=("calm_professional", "premium_dark"), skip=_NO_DELIVERY, likely_actions=("book_online", "call")),
    _p("makeup_artist", "looks", "portfolio_item", "Work", "Recent work", media="critical", portfolio=True,
       booking_led=True,
       price_visibility="on_request", families=("portfolio_sketchbook", "premium_dark"), skip=_NO_DELIVERY,
       likely_actions=("check_dates", "whatsapp"), elevate=("media.photos",),
       asks={"conversion": {"en": "Do brides usually check your date first and then ask for a package quote?"},
             "photos": {"en": "Can you add photos of your real work? For makeup, that's what decides a booking "
                              "— I won't make any up."}}),
    _p("gym", "plans and programmes", "plan", "Memberships", "Train with us", media="high",
       families=("monumental", "premium_dark"), skip=_NO_DELIVERY, likely_actions=("book_trial", "join", "whatsapp"),
       elevate=("memberships.plans",),
       asks={
           "conversion": {"en": "Do people usually come for a trial first, then join a plan — and should they "
                                "book that trial on WhatsApp or on the website?",
                          "ta_en": "Mudhalla trial-ku vandhu apram plan join pannuvaangalaa? Trial-a WhatsApp-la "
                                   "book pannanumaa, illa website-laa?"},
           "plans": {"en": "Which plans do you offer — monthly, quarterly, personal training packs?",
                     "ta_en": "Enna plans irukku — monthly, quarterly, personal training packs?"},
       }),
    _p("studio", "classes", "class", "Classes", "Classes & timings", media="high",
       booking_led=True,
       families=("calm_professional", "playful_editorial", "monumental"), skip=_NO_DELIVERY,
       likely_actions=("book_trial", "join"), elevate=("memberships.plans",),
       asks={"plans": {"en": "Do people drop in for a class, buy a pack, or join monthly?"},
             "conversion": {"en": "Should people book a trial class on the website, or message you first?"}}),
    _p("coach", "programmes", "service", "Programmes", "Work with me", media="medium", story_matters=True,
       booking_led=True,
       families=("calm_professional", "editorial_warm"), skip=_NO_DELIVERY,
       likely_actions=("book_consultation", "whatsapp")),
    _p("clinic", "treatments", "service", "Treatments", "Treatments", media="low",
       booking_led=True,
       families=("calm_professional",), skip=_NO_DELIVERY + ("commerce.payment",),
       likely_actions=("book_call", "book_whatsapp", "book_online"),
       asks={
           "offer": {"en": "Which treatments should patients see first?",
                     "ta_en": "Patients first-a endha treatments paakanum?"},
           "conversion": {"en": "Should patients book a slot on the website, or call or WhatsApp the clinic to "
                                "book?",
                          "ta_en": "Patients website-la slot book pannanumaa, illa clinic-ku call / WhatsApp "
                                   "panni book pannanumaa?"},
           "bookings": {"en": "Do patients book with a particular doctor — and are walk-ins welcome?",
                        "ta_en": "Patients oru particular doctor-kitta book pannuvaangalaa? Walk-in-um "
                                 "varalaamaa?"},
       }),
    _p("hospital", "departments", "service", "Departments", "Departments & specialities", media="low",
       booking_led=True,
       families=("calm_professional",), skip=_NO_DELIVERY + ("commerce.payment",),
       likely_actions=("book_call", "book_online", "call"),
       asks={
           "offer": {"en": "Which departments and specialities should people find first?"},
           "conversion": {"en": "Should patients book an OP appointment online, or call the front desk? Do you "
                                "have 24-hour emergency?"},
       }),
    _p("diagnostics", "tests", "service", "Tests", "Tests & packages", media="low", families=("calm_professional",),
       booking_led=True,
       skip=("offerings.units", "operations.stock"), likely_actions=("book_online", "call"),
       asks={"fulfilment": {"en": "Do you offer home sample collection — and in which areas?"}}),
    _p("pharmacy", "products", "product", "Shop", "Shop", media="low",
       families=("calm_professional", "modern_commerce"), likely_actions=("order_whatsapp", "visit")),
    _p("care_service", "services", "service", "Services", "How we help", media="low", story_matters=True,
       families=("calm_professional", "editorial_warm"), skip=("offerings.units", "operations.stock"),
       likely_actions=("call", "enquire")),
    _p("therapy", "sessions", "service", "Sessions", "How I can help", media="low", story_matters=True,
       booking_led=True,
       families=("calm_professional",), skip=_NO_DELIVERY, likely_actions=("book_online", "whatsapp")),
    _p("school", "programmes", "class", "Admissions", "Programmes", media="medium",
       families=("calm_professional", "playful_editorial"), skip=_NO_DELIVERY, likely_actions=("enquire", "visit")),
    _p("tuition", "courses", "class", "Courses", "Courses & batches", media="low",
       families=("calm_professional", "playful_editorial"), skip=_NO_DELIVERY,
       likely_actions=("book_trial", "enquire", "call"),
       asks={
           "offer": {"en": "Which classes and subjects do you teach — and for which exams?",
                     "ta_en": "Endha classes, subjects edukkureenga — endha exams-ku?"},
           "conversion": {"en": "Do parents usually enquire first or ask for a demo class before joining?",
                          "ta_en": "Parents mudhalla enquire pannuvaangalaa, illa demo class kepaangalaa?"},
           "plans": {"en": "Are fees monthly or per term — and are there morning and evening batches?"},
       }),
    _p("arts_school", "classes", "class", "Classes", "Classes", media="high",
       families=("playful_editorial", "editorial_warm"), skip=_NO_DELIVERY, likely_actions=("book_trial", "enquire")),
    _p("tutor", "subjects", "class", "Subjects", "What I teach", media="low", story_matters=True,
       families=("calm_professional", "playful_editorial"), skip=_NO_DELIVERY,
       likely_actions=("book_trial", "whatsapp")),
    _p("creator", "work", "digital_product", "Work", "Latest", media="high", portfolio=True, story_matters=True,
       families=("portfolio_sketchbook", "playful_editorial"), skip=_NO_DELIVERY, likely_actions=("enquire",)),
    _p("professional_firm", "services", "service", "Services", "How we help", media="low",
       price_visibility="on_request", families=("calm_professional", "technical_b2b"), skip=_NO_DELIVERY,
       likely_actions=("book_consultation", "call", "enquire"),
       asks={
           "offer": {"en": "Which services should clients find first — GST, income tax, company filings, "
                           "audits?"},
           "conversion": {"en": "Do clients usually call for a consultation first, or send their documents "
                                "on WhatsApp?"},
           "b2b": {"en": "Mostly individuals, or businesses on a monthly retainer?"},
       }),
    _p("consulting", "services", "service", "Services", "What we do", media="low",
       price_visibility="on_request", families=("technical_b2b", "calm_professional"), skip=_NO_DELIVERY,
       likely_actions=("book_consultation", "enquire")),
    _p("finance", "services", "service", "Services", "How we help", media="low",
       price_visibility="on_request", families=("calm_professional",), skip=_NO_DELIVERY,
       likely_actions=("book_consultation", "call")),
    _p("real_estate_developer", "projects", "property_project", "Projects", "Featured projects",
       media="critical", portfolio=True, price_visibility="from", families=("airy_property", "premium_dark"),
       skip=_NO_DELIVERY + ("commerce.payment",), likely_actions=("book_site_visit", "whatsapp", "call"),
       elevate=("offerings.structure",),
       asks={
           "offer": {"en": "Which projects should the website show first — and are they ready to move in, "
                           "under construction, or upcoming?",
                     "ta_en": "Endha projects first-a kaatanum — ready-to-move-aa, construction-la irukkaa, "
                              "illa upcoming-aa?"},
           "structure": {"en": "What's in each project — villas, apartments or plots, and which sizes (2 BHK, "
                               "3 BHK, sq.ft)?"},
           "conversion": {"en": "Do buyers usually call or WhatsApp to book a site visit?",
                          "ta_en": "Buyers site visit-ku call / WhatsApp panni book pannuvaangalaa?"},
           "photos": {"en": "Do you have real photos or renders of the projects? I won't draw a project that "
                            "isn't yours."},
       }),
    _p("real_estate_broker", "listings", "property_project", "Listings", "Properties", media="high",
       price_visibility="from", families=("airy_property", "local_friendly"),
       skip=_NO_DELIVERY + ("commerce.payment",), likely_actions=("whatsapp", "call", "book_site_visit"),
       asks={"offer": {"en": "Mostly rentals or sales — homes, plots or commercial spaces — and in which areas?"}}),
    _p("stay", "rooms", "room_type", "Rooms", "Rooms", media="high",
       booking_led=True,
       families=("airy_property", "local_friendly"), skip=_NO_DELIVERY, likely_actions=("enquire", "call", "visit"),
       asks={"hours": _STAY_HOURS}),
    _p("design_studio", "projects", "portfolio_item", "Work", "Selected work", media="critical", portfolio=True,
       price_visibility="on_request", families=("portfolio_sketchbook", "airy_property"),
       skip=_NO_DELIVERY + ("commerce.payment",), likely_actions=("book_consultation", "whatsapp"),
       elevate=("media.photos",),
       asks={
           "offer": {"en": "Is it mostly full-home interiors, kitchens and wardrobes, or commercial spaces?",
                     "ta_en": "Full home interiors-aa, kitchen / wardrobe-aa, illa commercial spaces-aa?"},
           "conversion": {"en": "Does a project usually start with a consultation or a site visit?",
                          "ta_en": "Project mudhalla consultation-la aarambikkumaa, illa site visit-laa?"},
           "photos": {"en": "Do you have photos of finished projects to show? For design work, real photos "
                            "are the portfolio — I won't invent any.",
                      "ta_en": "Mudichcha projects photos irukkaa? Design work-ku real photos dhaan "
                               "portfolio — naan edhuvum create panna maatten."},
       }),
    _p("contractor", "services", "service", "Services", "What we build", media="high", portfolio=True,
       price_visibility="on_request", families=("technical_b2b", "monumental"),
       skip=_NO_DELIVERY + ("commerce.payment",), likely_actions=("request_quote", "call"),
       asks={"conversion": {"en": "Do clients call for a site visit and an estimate first?"}}),
    _p("home_service", "services", "service", "Services", "Services", media="low",
       booking_led=True,
       families=("local_friendly", "calm_professional"), skip=("offerings.units", "operations.stock"),
       likely_actions=("book_whatsapp", "call"),
       asks={
           "conversion": {"en": "Do people book a visit on WhatsApp or call you — and would they like to book "
                                "a slot on the website?"},
           "fulfilment": {"en": "Which areas do your technicians cover?",
                          "ta_en": "Unga technicians endha areas-ku varuvaanga?"},
       }),
    _p("laundry", "services", "service", "Services", "Services & prices", media="low",
       families=("local_friendly", "modern_commerce"), likely_actions=("whatsapp", "visit"),
       asks={"fulfilment": {"en": "Do you pick up and drop, or do people come to the shop — and which areas?"}}),
    _p("repair", "repairs", "service", "Services", "What we fix", media="low",
       families=("local_friendly", "technical_b2b"), skip=("offerings.units", "operations.stock"),
       likely_actions=("visit", "whatsapp", "call")),
    _p("vehicle_dealer", "vehicles", "vehicle", "Vehicles", "In the showroom", media="critical",
       price_visibility="from", families=("premium_dark", "modern_commerce"),
       skip=("offerings.units", "fulfilment.mode", "fulfilment.area"),
       likely_actions=("book_online", "whatsapp", "visit")),
    _p("auto_service", "services", "service", "Services", "Services", media="medium",
       booking_led=True,
       families=("local_friendly", "technical_b2b"), skip=("offerings.units", "operations.stock"),
       likely_actions=("book_whatsapp", "call", "visit"),
       asks={"conversion": {"en": "Do people book a service slot and bring the vehicle in, or do you pick it up?"}}),
    _p("detailing", "packages", "service", "Packages", "Detailing packages", media="critical", portfolio=True,
       booking_led=True,
       families=("premium_dark", "modern_commerce"), skip=("offerings.units", "operations.stock"),
       likely_actions=("book_whatsapp", "call"), elevate=("media.photos",),
       asks={
           "offer": {"en": "Which packages do people choose most — wash, interior detailing, ceramic coating, "
                           "PPF?"},
           "conversion": {"en": "Do people book a slot and bring the car, or do you come to them?"},
           "photos": {"en": "Do you have before-and-after photos of cars you've done? Real ones sell this — "
                            "I won't make any up."},
       }),
    _p("auto_parts", "products", "product", "Products", "In stock", media="low",
       families=("modern_commerce", "technical_b2b"), likely_actions=("call", "visit", "whatsapp")),
    _p("rentals", "rentals", "rental_resource", "Rent", "Available to rent", media="high",
       booking_led=True,
       families=("modern_commerce", "local_friendly"), skip=("offerings.units", "operations.stock"),
       likely_actions=("book_whatsapp", "call"),
       asks={"conversion": {"en": "Do people check availability for dates first, then pay a deposit?"}}),
    _p("logistics", "services", "service", "Services", "What we move", media="low",
       price_visibility="on_request", families=("technical_b2b", "monumental"),
       skip=("offerings.units", "operations.stock", "offerings.structure"),
       likely_actions=("request_quote", "call", "whatsapp"),
       asks={
           "offer": {"en": "What do you move most — parcels, full truckloads, house shifting, warehousing?"},
           "fulfilment": {"en": "Which routes or regions do you cover?",
                          "ta_en": "Endha routes / regions cover pannureenga?"},
           "conversion": {"en": "Do businesses ask for a quote first, or book a pickup directly?"},
       }),
    _p("hotel", "rooms", "room_type", "Rooms", "Stay with us", media="critical",
       booking_led=True,
       families=("airy_property", "premium_dark", "editorial_warm"), skip=_NO_DELIVERY,
       likely_actions=("book_online", "call", "whatsapp"),
       asks={
           "offer": {"en": "Which room types do you have — and is there a restaurant or anything nearby "
                           "guests come for?"},
           "conversion": {"en": "Do guests book directly with you, or mostly through travel sites — and should "
                                "the website take booking requests?"},
           "hours": _STAY_HOURS,
       }),
    _p("homestay", "rooms", "room_type", "Stay", "The stay", media="critical", story_matters=True,
       booking_led=True,
       families=("editorial_warm", "airy_property"), skip=_NO_DELIVERY, likely_actions=("whatsapp", "book_online"),
       asks={"hours": _STAY_HOURS}),
    _p("travel", "packages", "package", "Packages", "Trips & packages", media="high", price_visibility="from",
       families=("airy_property", "playful_editorial"), skip=("offerings.units", "operations.stock"),
       likely_actions=("request_quote", "whatsapp")),
    _p("event_planner", "events", "portfolio_item", "Work", "Events we've made", media="critical",
       portfolio=True, price_visibility="on_request", families=("portfolio_sketchbook", "premium_dark"),
       skip=("offerings.units", "operations.stock"), likely_actions=("check_dates", "request_quote", "whatsapp"),
       elevate=("media.photos",)),
    _p("banquet_hall", "halls", "rental_resource", "Halls", "The venue", media="critical",
       booking_led=True,
       price_visibility="on_request", families=("premium_dark", "airy_property"),
       skip=_NO_DELIVERY, likely_actions=("check_dates", "call", "visit"),
       asks={"offer": {"en": "How many guests does the hall seat, and is catering or decoration included?"}}),
    _p("florist", "flowers", "product", "Flowers", "Bouquets & arrangements", media="critical",
       story_matters=False, families=("playful_editorial", "editorial_warm"),
       skip=("offerings.units", "operations.stock"), likely_actions=("order_whatsapp", "call"),
       asks={
           "offer": {"en": "Mostly bouquets and gifts, or wedding and event decoration?",
                     "ta_en": "Adhigama bouquets / gifts-aa, illa wedding, event decoration-aa?"},
           "conversion": {"en": "Do people order a bouquet on WhatsApp for the same day, or pre-order for an "
                                "event?"},
           "fulfilment": {"en": "Do you deliver bouquets — and to which areas?"},
       }),
    _p("print_shop", "products", "product", "Products", "What we print", media="medium",
       price_visibility="on_request", families=("technical_b2b", "local_friendly"),
       likely_actions=("request_quote", "whatsapp", "visit")),
    _p("photographer", "work", "portfolio_item", "Work", "Selected work", media="critical", portfolio=True,
       price_visibility="on_request", families=("portfolio_sketchbook", "premium_dark"),
       skip=_NO_DELIVERY + ("commerce.payment",), likely_actions=("check_dates", "request_quote", "whatsapp"),
       elevate=("media.photos",),
       asks={
           "offer": {"en": "What do you shoot most — weddings, pre-weddings, portraits, products?",
                     "ta_en": "Adhigama enna shoot pannureenga — wedding, pre-wedding, portraits, products?"},
           "conversion": {"en": "Do couples usually check your date on WhatsApp first and then ask for a "
                                "package quote?",
                          "ta_en": "Couples mudhalla WhatsApp-la date check panni apram package quote "
                                   "kepaangalaa?"},
           "photos": {"en": "Can you add some of your real work for the gallery? For a photographer the "
                            "photos are the website — I'll never invent any.",
                      "ta_en": "Gallery-ku unga real work photos add pannalaamaa? Photographer-ku photos "
                               "dhaan website — naan edhuvum create panna maatten."},
       }),
    _p("creative_agency", "work", "portfolio_item", "Work", "Selected work", media="high", portfolio=True,
       price_visibility="on_request", families=("portfolio_sketchbook", "technical_b2b"), skip=_NO_DELIVERY,
       likely_actions=("enquire", "book_consultation")),
    _p("maker", "work", "portfolio_item", "Work", "Work", media="critical", portfolio=True,
       price_visibility="on_request", families=("portfolio_sketchbook",), skip=_NO_DELIVERY,
       likely_actions=("enquire", "whatsapp"), elevate=("media.photos",)),
    _p("software", "products and services", "service", "Solutions", "What we build", media="low",
       price_visibility="on_request", families=("technical_b2b", "modern_commerce"), skip=_NO_DELIVERY,
       likely_actions=("book_consultation", "enquire", "get_app"),
       asks={"conversion": {"en": "What should visitors do — download the app, sign up, or book a demo?"}}),
    _p("industrial_supplier", "product families", "product", "Products", "Product range", media="medium",
       price_visibility="on_request", families=("technical_b2b",), skip=("offerings.units", "operations.stock"),
       likely_actions=("request_quote", "call", "whatsapp"),
       asks={
           "offer": {"en": "Which product families should buyers see first — and which brands or specs matter?",
                     "ta_en": "Buyers first-a endha product families paakanum — endha brands, specs?"},
           "b2b": {"en": "Which industries buy from you most — and do they usually send an RFQ with specs "
                         "first?",
                   "ta_en": "Endha industries adhigama vaanguvaanga — mudhalla specs-oda RFQ anuppuvaangalaa?"},
           "conversion": {"en": "Should buyers send an RFQ from the website, or call / WhatsApp your sales "
                                "team?"},
           "fulfilment": {"en": "Do you dispatch across India, or mainly nearby industrial areas?"},
       }),
    _p("manufacturer", "product lines", "product", "Products", "What we make", media="medium",
       price_visibility="on_request", families=("technical_b2b", "monumental"),
       skip=("offerings.units", "operations.stock"), likely_actions=("request_quote", "enquire"),
       asks={"b2b": {"en": "Who buys from you — brands, distributors, other factories — and what's a typical "
                           "order size?"}}),
    _p("wholesale", "products", "product", "Products", "Our range", media="low", price_visibility="on_request",
       families=("technical_b2b", "modern_commerce"), likely_actions=("order_whatsapp", "request_quote", "call"),
       asks={"b2b": {"en": "Do retailers order on WhatsApp or through your salesmen — and do you give credit?"}}),
    _p("farm", "produce", "product", "Produce", "From the farm", media="high", story_matters=True,
       families=("editorial_warm", "local_friendly"), likely_actions=("order_whatsapp", "subscribe", "visit"),
       asks={"plans": {"en": "Do people order as they need, or subscribe to a weekly box?"}}),
    _p("agri_dealer", "products", "product", "Products", "Products", media="low",
       families=("local_friendly", "technical_b2b"), likely_actions=("visit", "call")),
    _p("energy", "solutions", "service", "Solutions", "What we install", media="medium",
       price_visibility="on_request", families=("technical_b2b", "airy_property"),
       skip=("offerings.units", "operations.stock"), likely_actions=("book_site_visit", "request_quote", "call"),
       asks={"conversion": {"en": "Does it usually start with a site survey and then a quote?"}}),
    _p("pet_care", "services", "service", "Services", "Care for your pet", media="high",
       booking_led=True,
       families=("playful_editorial", "local_friendly"), skip=("offerings.units", "operations.stock"),
       likely_actions=("book_whatsapp", "call")),
    _p("daycare", "programmes", "class", "Programmes", "A day with us", media="high", story_matters=True,
       families=("playful_editorial", "calm_professional"), skip=_NO_DELIVERY, likely_actions=("visit", "enquire")),
    _p("coworking", "spaces", "rental_resource", "Spaces", "Spaces", media="high",
       booking_led=True,
       families=("airy_property", "modern_commerce"), skip=_NO_DELIVERY, likely_actions=("book_online", "visit")),
    _p("security_facility", "services", "service", "Services", "Services", media="low",
       price_visibility="on_request", families=("technical_b2b", "monumental"), skip=_NO_DELIVERY,
       likely_actions=("request_quote", "call")),
    _p("testing_lab", "tests", "service", "Tests", "Tests & certifications", media="low",
       price_visibility="on_request", families=("technical_b2b", "calm_professional"), skip=_NO_DELIVERY,
       likely_actions=("request_quote", "enquire")),
    _p("community", "activities", "service", "Activities", "What we do", media="medium", story_matters=True,
       families=("editorial_warm", "local_friendly"), skip=_NO_DELIVERY, likely_actions=("join", "visit")),
    _p("ngo", "causes", "cause", "Our work", "Our work", media="medium", story_matters=True,
       families=("editorial_warm", "calm_professional"), skip=_NO_DELIVERY + ("commerce.payment",),
       likely_actions=("donate", "enquire")),
    _p("other", "products or services", "service", "Services", "What we offer", media="medium",
       families=("local_friendly", "calm_professional"), likely_actions=("call", "whatsapp")),
)}


def playbook_key(bp: BusinessBlueprint) -> str:
    """The trade this business most likely is: the owner's pick, else their words."""
    if bp.category and bp.category.subcategory_key:
        found = resolve(bp.category.category_key, bp.category.subcategory_key)
        if found:
            return str(found[1].playbook)
    if bp.category and bp.category.category_key:
        found = resolve(bp.category.category_key, None)
        if found:
            return str(found[1].playbook)
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    said = " ".join(
        [facts[k].value for k in ("classification", "description", "offerings") if k in facts]
        + [m.text for m in bp.messages if m.role == "user"][:3]
    )
    guess = infer_from_text(said)
    if guess and guess[1] >= 0.7:
        return str(SUBCATEGORIES[guess[0]][1].playbook)
    return "other"


def playbook_for(bp: BusinessBlueprint) -> Playbook:
    return PLAYBOOKS.get(playbook_key(bp), PLAYBOOKS["other"])


# A business guests stay at overnight: rooms by the night, check-in and check-out.
STAY_KINDS = frozenset({"room_type", "accommodation"})


def is_stay(bp: BusinessBlueprint) -> bool:
    """A hotel, resort, homestay or estate stay — whatever it was called."""
    return playbook_for(bp).offer_kind in STAY_KINDS


def phrase_override(playbook: Playbook, ask_id: str, lang: str) -> str:
    """The trade's own wording for a question, in the owner's language if it has one.

    No fallback to English here: a Tamil speaker is better served by the
    generic question in Tamil than by an expert one in English.
    """
    return (playbook.asks.get(ask_id) or {}).get(lang, "")


def trade_noun(bp: BusinessBlueprint) -> str:
    noun = playbook_for(bp).noun
    return re.sub(r"\s+and\s+.*$", "", noun) if len(noun) > 18 else noun
