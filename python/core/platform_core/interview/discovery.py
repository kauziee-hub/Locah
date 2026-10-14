"""Business discovery: what Locah still needs to understand, and what to ask next.

The old interview completed three fields and then asked for a location, a phone
number and a logo — for every business. "We sell all types of meat" filled
`offerings`, so Locah never asked which meats, how they are sold, or how they
reach the customer; and because `description` was still empty it asked "what
do people come to you for?" again. The questions were a fixed list.

Here the question space is a catalogue of *discovery targets* — concepts such
as "how products are sold" or "delivery or pickup" — each declaring which
kinds of business it matters for, in the vocabulary of Document 07 §11.1
(sells products, accepts orders, delivers, has a team...). Nothing branches on
a business type. A business's characteristics come from two places:

* what the owner actually said (operating patterns, answers) — strong;
* the Business-Type Profile of its likely type — a prior, weaker.

The planner ranks the targets that are relevant, not yet known and not already
asked, and hands the model a short list to phrase from. The model proposes one;
the planner accepts it only if it is still worth asking. Asking is tracked by
concept, so a reworded version of a known question is still a known question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from platform_core.business_type_profiles.registry import BusinessTypeProfileRegistry
from platform_core.interview.models import BusinessBlueprint, Readiness, TargetState

# ---------------------------------------------------------------- characteristics

# Document 07 §11.1 characteristics, plus the few this conversation needs to
# tell a quote-led supplier from a shop.
CHARACTERISTICS = frozenset({
    "sells_products", "provides_services", "accepts_appointments", "accepts_orders",
    "has_physical_locations", "delivers", "pickup", "has_team", "has_memberships",
    "runs_classes", "online_only", "serves_businesses", "quote_led", "made_to_order",
    "stock_based", "walk_in", "enquiry_led", "sells_property", "on_site", "portfolio_led",
})

# Capability Universe §4.3 operating traits -> the characteristics above. Used
# for the category the owner picked: a prior of the same strength as a
# Business-Type Profile, never "observed".
TRAIT_CHARACTERISTICS: dict[str, tuple[str, ...]] = {
    "sells_products": ("sells_products",), "sells_services": ("provides_services",),
    "sells_access": ("has_memberships",), "order_led": ("accepts_orders",),
    "booking_led": ("accepts_appointments",), "quote_led": ("quote_led",),
    "enquiry_led": ("enquiry_led",), "subscription_led": ("has_memberships",),
    "project_led": ("made_to_order",), "class": ("runs_classes",),
    "walk_in": ("walk_in", "has_physical_locations"), "pickup": ("pickup",),
    "local_delivery": ("delivers",), "shipping": ("delivers",), "on_site_service": ("on_site",),
    "made_to_order": ("made_to_order",), "provider_based": ("has_team",), "field_team": ("has_team",),
    "portfolio_led": ("portfolio_led",), "stay": ("accepts_appointments",),
}

CHARACTERISTICS_BY_PATTERN: dict[str, tuple[str, ...]] = {
    "b2b": ("serves_businesses",),
    "b2b2c": ("serves_businesses",),
    "service_led": ("provides_services",),
    "retail": ("sells_products",),
    "wholesale": ("sells_products", "serves_businesses"),
    "appointment_led": ("accepts_appointments",),
    "quote_led": ("quote_led",),
    "lead_generation": ("enquiry_led",),
    "catalogue_led": ("sells_products",),
    "order_led": ("accepts_orders",),
    "membership_led": ("has_memberships",),
    "subscription_like": ("has_memberships",),
    "multi_location": ("has_physical_locations",),
    "provider_based": ("has_team", "provides_services"),
    "project_based": ("made_to_order",),
    "made_to_order": ("made_to_order",),
    "custom_made": ("made_to_order",),
    "delivery": ("delivers",),
    "local_delivery": ("delivers",),
    "shipping": ("delivers",),
    "pickup": ("pickup",),
    "walk_in": ("has_physical_locations", "walk_in"),
    "online_first": ("online_only",),
    "product_led": ("sells_products",),
    "stock_based": ("stock_based",),
    "has_team": ("has_team",),
    "runs_classes": ("runs_classes",),
}

# What an answer or a stated customer action implies, read from the owner's
# words. Deliberately small: the model supplies patterns with quotations; this
# only catches the plain cases so the planner is not blind when it forgets.
# People the owner works with. Shared with the recommendation evidence.
TEAM = re.compile(
    r"\b(staff|team|doctors?|dentists?|therapists?|nurses?|stylists?|trainers?|coaches|"
    r"instructors?|teachers?|tutors?|chefs?|drivers?|butchers?|employees)\b", re.I)

_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("accepts_orders", re.compile(r"\b(order|orders|ordering|buy|cart|checkout)\b", re.I)),
    ("accepts_appointments", re.compile(r"\b(book|booking|appointment|reserve|reservation|slot)\w*\b", re.I)),
    ("delivers", re.compile(r"\b(deliver|delivery|delivers|door ?step|home delivery|ship|shipping)\w*\b", re.I)),
    ("pickup", re.compile(r"\b(pick ?up|collect from|takeaway|take away)\b", re.I)),
    ("quote_led", re.compile(r"\b(quote|quotation|estimate|rfq)\w*\b", re.I)),
    ("has_team", TEAM),
    ("has_memberships", re.compile(r"\b(membership|monthly plan|subscription)s?\b", re.I)),
    # "Morning batch" is a class; "small batches" of pickles is how food is made.
    ("runs_classes", re.compile(
        r"\b(class|classes|sessions)\b|\b(?:morning|evening|weekend|weekday|new|next|kids'?|ladies'?)"
        r"\s+batch(?:es)?\b|\bbatch\s+(?:timings?|starts?|schedule)\b", re.I)),
    ("serves_businesses", re.compile(r"\b(factories|companies|businesses|wholesale|b2b|corporate|retailers|dealers)\b", re.I)),
    ("walk_in", re.compile(r"\b(walk[- ]?in|visit (?:the|our) (?:shop|store|showroom)|showroom|come to (?:the|our) (?:shop|store))\b", re.I)),
    # The whole word only: "custom\w*" matched "customers", the word every owner uses.
    ("made_to_order", re.compile(
        r"\b(custom|custom[- ]made|customi[sz]\w*|made[- ]to[- ]order|bespoke|tailor[- ]made)\b", re.I)),
    ("enquiry_led", re.compile(r"\b(enquir|inquir|whatsapp us|send (?:us )?(?:an? )?requirement)\w*\b", re.I)),
    # A developer, builder or plot seller: what visitors choose between are projects.
    ("sells_property", re.compile(
        r"\b(real estate|villas?|apartments?|flats|plots?|plotted|bhk|properties|developer|"
        r"builders?|gated communit\w*|residential projects?)\b", re.I)),
    ("sells_products", re.compile(r"\b(we sell|we are selling|we're selling|selling|our shop|our store)\b", re.I)),
)
_BUILT = r"(?:projects?|homes?|houses?|flats?|villas?|apartments?|units?|buildings?|sites?|towers?)"
# "14 projects delivered", "14 delivered projects", "delivered 14 homes".
_TRACK_RECORD = re.compile(
    rf"\b{_BUILT}(?:\s+\w+){{0,2}}\s+delivered\b|\bdelivered(?:\s+\w+){{0,2}}\s+{_BUILT}\b", re.I)
_NEGATED = re.compile(r"\b(no|not|don't|dont|do not|never|without)\b[^.]*$", re.I)


def profile_type(bp: BusinessBlueprint, business_type: str | None = None) -> str:
    """The Business-Type Profile to use as a prior."""
    from platform_core.interview.capabilities import classification_seed

    stored = (business_type or "").strip().lower()
    seed = classification_seed(bp)
    if seed != "other":
        return str(seed)
    return stored or "other"


def _category_priors(bp: BusinessBlueprint) -> tuple[str, ...]:
    """What the business's kind usually means — the more specific prior.

    The owner's pick first; else the kind their own words most clearly name
    ("a gym app" is software, not a gym). Still only a prior.
    """
    from platform_core.catalog.taxonomy import SUBCATEGORIES, infer_from_text

    key = bp.category.subcategory_key if bp.category and bp.category.subcategory_key else ""
    if not key and not bp.category:
        facts = {**bp.known_facts, **bp.unconfirmed_facts}
        said = " ".join([facts[k].value for k in ("classification", "description", "offerings") if k in facts]
                        + [m.text for m in bp.messages if m.role == "user"][:2])
        guess = infer_from_text(said)
        key = guess[0] if guess and guess[1] >= 0.7 else ""
    found = SUBCATEGORIES.get(key) if key else None
    if not found:
        return ()
    traits = found[1].traits
    chars: list[str] = []
    for trait in sorted(traits):
        chars.extend(TRAIT_CHARACTERISTICS.get(trait, ()))
    # Only a business that sells to businesses alone is "B2B" by default; a
    # caterer who also does corporate lunches is asked, not assumed.
    if "b2b" in traits and "b2c" not in traits:
        chars.append("serves_businesses")
    if found[1].playbook in {"real_estate_developer", "real_estate_broker"}:
        chars.append("sells_property")
    return tuple(dict.fromkeys(chars))


def characteristics(
    bp: BusinessBlueprint, business_type: str | None = None
) -> dict[str, str]:
    """characteristic -> "observed" | "profile"."""
    found: dict[str, str] = {}
    for item in _category_priors(bp) or BusinessTypeProfileRegistry.get_or_default(
        profile_type(bp, business_type)
    ).characteristics:
        if item in CHARACTERISTICS:
            found[item] = "profile"
    for evidence in bp.operating_patterns:
        for item in CHARACTERISTICS_BY_PATTERN.get(evidence.pattern, ()):
            found[item] = "observed"
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    spoken = [facts[key].value for key in ("description", "offerings", "customer_actions",
                                           "operational_characteristics", "operating_model")
              if key in facts]
    spoken += [state.summary + " " + state.quote for state in bp.discovery.values()
               if state.status in {"answered", "partial"}]
    for text in spoken:
        # "Cash on delivery" is how people pay, not a delivery service.
        text = re.sub(r"\b(?:cash|pay(?:ment)?)\s+on\s+delivery\b|\bcod\b", " ", text, flags=re.I)
        for name, pattern in _SIGNALS:
            for match in pattern.finditer(text):
                before = text[max(0, match.start() - 25): match.start()]
                if _NEGATED.search(before):
                    continue  # "we don't deliver" is not delivery
                if name == "delivers" and _TRACK_RECORD.search(text[max(0, match.start() - 40): match.end() + 40]):
                    continue  # "14 projects delivered" is a track record, not delivery
                found[name] = "observed"
                break
    # Owners who sell things name products; owners who serve name services.
    # Selling and ordering go together unless they said otherwise.
    if "accepts_orders" in found and "provides_services" not in found:
        found.setdefault("sells_products", found["accepts_orders"])
    return found


# --------------------------------------------------------------------- targets


@dataclass(frozen=True)
class Target:
    id: str
    label: str  # owner-facing: "Still worth knowing: Delivery or pickup"
    learn: str  # for the model: what a good answer tells Locah
    value: int
    relevant: frozenset[str] = frozenset()  # any of these (empty: every business)
    requires: frozenset[str] = frozenset()  # all of these
    unless: frozenset[str] = frozenset()  # none of these (observed)
    after: tuple[str, ...] = ()  # asked only once these are addressed
    essential: bool = False  # always essential when relevant
    essential_when: frozenset[str] = frozenset()  # essential when any is present
    fact: str | None = None  # the business-truth field that answers it
    once: bool = False  # worth asking at most once
    fallback: dict[str, str] = field(default_factory=dict)
    # 0 shapes the website (what is sold and how it is organised, how people
    # buy, pictures, story); 1 shapes operations (delivery, payment, prices,
    # contact); 2 is secondary (hours, team, look). A lower tier is asked first.
    tier: int = 1
    # Relevant only while this predicate holds (see PREDICATES).
    when: str = ""


def _t(
    target_id: str,
    label: str,
    learn: str,
    value: int,
    *,
    fallback: dict[str, str],
    relevant: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
    unless: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
    essential: bool = False,
    essential_when: tuple[str, ...] = (),
    fact: str | None = None,
    once: bool = False,
    when: str = "",
) -> Target:
    return Target(target_id, label, learn, value, frozenset(relevant), frozenset(requires),
                  frozenset(unless), after, essential, frozenset(essential_when), fact, once,
                  fallback, TIERS.get(target_id, 1), when)


# What a question is for. Opening hours matter, but not before Locah knows
# whether "fish" is one product, a category, or fifteen varieties.
TIERS: dict[str, int] = {
    "business.identity": 0, "offerings.main": 0, "offerings.structure": 0, "offerings.catalogue": 0,
    "offerings.traits": 1,
    "commerce.action": 0, "offerings.units": 0, "media.photos": 0, "brand.story": 0,
    "offerings.customisation": 0, "services.providers": 0, "b2b.customers": 0,
    "bookings.format": 0, "memberships.plans": 0,
    "fulfilment.mode": 1, "fulfilment.area": 1, "commerce.payment": 1, "offerings.pricing": 1,
    "b2b.process": 1, "contact.location": 1, "contact.phone": 1, "media.logo": 1,
    "operations.hours": 2, "operations.stock": 2, "operations.team": 2,
    "fulfilment.operator": 2, "brand.feel": 2,
}


TARGETS: tuple[Target, ...] = (
    _t("business.identity", "What the business is",
       "what kind of business this is and who it serves", 100, essential=True,
       fact="description",
       fallback={"en": "Tell me a little about {name} — what kind of business is it?",
                 "ta_en": "{name} pathi konjam sollunga — enna business idhu?",
                 "ta": "{name} பத்தி கொஞ்சம் சொல்லுங்க — என்ன பிசினஸ்?"}),
    _t("offerings.main", "Exactly what you sell or offer",
       "the main products or services by name — specific enough to list on a website "
       "(categories or items, not 'everything')", 95, essential=True, fact="offerings",
       fallback={"en": "Which ones should customers see first? Just list the main {things}.",
                 "ta_en": "Customers first-a enna paakanum? Main {things} mattum sollunga.",
                 "ta": "கஸ்டமர்ஸ் முதல்ல எதை பார்க்கணும்? முக்கியமானதை மட்டும் சொல்லுங்க."}),
    _t("offerings.structure", "Varieties, cuts or sizes",
       "how the range is organised: the varieties inside a group ('which fish'), whether "
       "customers choose cuts or sizes — what the website's categories and product cards need",
       92, essential=True, after=("offerings.main",), when="catalogue_open",
       fallback={"en": "{structure}", "ta_en": "{structure}", "ta": "{structure}"}),
    # The real list, not three words in a sentence: every dish, service,
    # product, plan or room with its price — from a photo or PDF of the menu
    # or price list, or typed out (catalogue_capture).
    _t("offerings.catalogue", "Your full menu or price list",
       "every item with its price, as on the owner's menu, rate card or price list — a photo or PDF "
       "of it, or typed out ('Idli 40, Dosa 70') — so the website lists everything, priced",
       90, relevant=("sells_products", "provides_services", "has_memberships"),
       after=("offerings.main",), once=True,
       fallback={"en": "Can you send me your full list with prices — a photo or PDF, or typed out?",
                 "ta_en": "Unga full list price-oda anuppa mudiyumaa — photo, PDF illa type pannalaamaa?",
                 "ta": "உங்க முழு பட்டியலை விலையோட அனுப்ப முடியுமா — படம், PDF அல்லது டைப் பண்ணலாமா?"}),
    _t("offerings.traits", "Favourites, veg or non-veg",
       "which items sell the most (to feature them), and for food which dishes are veg or non-veg",
       55, relevant=("sells_products", "provides_services"), after=("offerings.catalogue",), once=True,
       fallback={"en": "Which ones sell the most? I'll feature them.",
                 "ta_en": "Edhu adhigama sell aagudhu?",
                 "ta": "எது அதிகம் விற்கும்?"}),
    _t("offerings.units", "How products are sold (weight, size or packs)",
       "how customers choose quantity or variant — by weight, size, pieces, fixed packs, "
       "cuts, or custom", 72, requires=("sells_products",), unless=("made_to_order",),
       after=("offerings.main",),
       essential_when=("accepts_orders",),
       fallback={"en": "When someone orders{about}, can they choose any quantity or weight, "
                       "or do you sell fixed packs?",
                 "ta_en": "Order pannumbodhu customers edhu venumnaalum kg-la select pannalaama, "
                          "illa fixed packs-aa?",
                 "ta": "ஆர்டர் பண்ணும்போது எவ்வளவு வேணும்னு தேர்ந்தெடுக்கலாமா, இல்ல ஃபிக்ஸ்ட் பேக்கா?"}),
    _t("offerings.pricing", "Prices or price range",
       "prices, or how pricing works (per kg, per item, starting from)", 60,
       relevant=("sells_products", "provides_services", "has_memberships"),
       after=("offerings.main",), once=True,
       fallback={"en": "Do you already have prices{per}, or should I leave those for you to "
                       "fill in later?",
                 "ta_en": "Website-la price podalaamaa? Per item-aa, per kg-aa?",
                 "ta": "வெப்சைட்ல விலை போடலாமா? ஒரு பொருளுக்கா, கிலோவுக்கா?"}),
    _t("offerings.customisation", "What can be customised",
       "what customers can customise and how custom work is agreed", 45,
       requires=("made_to_order",), unless=("sells_property",), after=("offerings.main",),
       once=True,
       fallback={"en": "What can customers customise when they order from you?",
                 "ta_en": "Customers enna customise panna mudiyum?",
                 "ta": "கஸ்டமர்ஸ் என்ன மாற்றி ஆர்டர் பண்ண முடியும்?"}),
    _t("services.providers", "Who provides the service",
       "who serves customers (doctors, stylists, trainers) and whether customers pick a person",
       42, requires=("provides_services",), relevant=("accepts_appointments", "has_team"),
       unless=("sells_property",), after=("offerings.main",), once=True,
       fallback={"en": "Do customers choose a particular person, or whoever is available?",
                 "ta_en": "Customers oru specific aala select pannuvaangalaa, illa yaar free-o avangalaa?",
                 "ta": "கஸ்டமர்ஸ் ஒருத்தரை தேர்ந்தெடுப்பாங்களா, இல்ல யார் ஃப்ரீயோ அவங்களா?"}),
    _t("commerce.action", "How customers order, book or get in touch",
       "what a customer should be able to do — order, book, send an enquiry, call or WhatsApp, "
       "visit", 88, essential=True, fact="customer_actions",
       fallback={"en": "When someone finds {name} online, what should they be able to do — "
                       "order, book, send an enquiry, or call you?",
                 "ta_en": "Online-la {name} paathaanga-na avanga enna pannanum — order, book, "
                          "illa call?",
                 "ta": "ஆன்லைன்ல பார்த்தவங்க என்ன செய்யணும் — ஆர்டர், புக்கிங், இல்ல கால்?"}),
    _t("commerce.payment", "How customers pay",
       "whether customers pay online, cash or pay on delivery, or both", 50,
       relevant=("accepts_orders", "has_memberships"), essential_when=("accepts_orders",),
       fallback={"en": "How would you like customers to pay — online, cash on delivery, or both?",
                 "ta_en": "Customers eppadi pay pannanum — online-aa, cash on delivery-aa, "
                          "illa rendum-aa?",
                 "ta": "கஸ்டமர்ஸ் எப்படி பணம் கட்டணும் — ஆன்லைன், கேஷ் ஆன் டெலிவரி, இல்ல ரெண்டும்?"}),
    _t("fulfilment.mode", "Delivery or pickup",
       "whether orders are delivered, picked up, shipped — or both", 56,
       relevant=("accepts_orders", "delivers"), requires=("sells_products",),
       essential_when=("accepts_orders",),
       fallback={"en": "Do you deliver orders, offer pickup from the shop, or both?",
                 "ta_en": "Neenga deliver pannuveengalaa, shop-la pickup-aa, illa rendum-aa?",
                 "ta": "நீங்க டெலிவரி பண்ணுவீங்களா, கடையில பிக்கப்பா, இல்ல ரெண்டுமா?"}),
    _t("fulfilment.area", "Where you deliver",
       "the delivery area or radius", 48, requires=("delivers",), after=("fulfilment.mode",),
       essential_when=("delivers",),
       fallback={"en": "Roughly which areas do you deliver to?",
                 "ta_en": "Endha area-la ellaam deliver pannuveenga?",
                 "ta": "எந்த ஏரியாக்களுக்கு டெலிவரி பண்ணுவீங்க?"}),
    _t("fulfilment.operator", "Who delivers",
       "own delivery staff or a delivery partner", 18, requires=("delivers",),
       after=("fulfilment.area",), once=True,
       fallback={"en": "Do you deliver with your own staff or through a delivery partner?",
                 "ta_en": "Unga staff deliver pannuvaangalaa, illa delivery partner-aa?",
                 "ta": "உங்க ஆட்கள் டெலிவரி பண்ணுவாங்களா, இல்ல டெலிவரி பார்ட்னரா?"}),
    _t("operations.stock", "Daily availability",
       "whether what is available changes day to day or sells out", 22,
       requires=("sells_products", "accepts_orders"), after=("offerings.units",), once=True,
       fallback={"en": "Does what you have change day to day — should customers see when "
                       "something is sold out?",
                 "ta_en": "Stock daily maarumaa — sold out-na customers-ku theriyanumaa?",
                 "ta": "தினமும் ஸ்டாக் மாறுமா — தீர்ந்தா கஸ்டமர்ஸுக்கு தெரியணுமா?"}),
    _t("operations.hours", "Opening hours",
       "when customers can visit, order or book", 10,
       relevant=("has_physical_locations", "accepts_appointments", "walk_in", "accepts_orders"),
       fact="opening_hours", once=True, after=("brand.story", "media.photos"),
       fallback={"en": "What are your usual opening hours?",
                 "ta_en": "Usual-aa eppo open irukkum?",
                 "ta": "வழக்கமா எப்போ திறந்திருக்கும்?"}),
    _t("operations.team", "Your team",
       "who works in the business, if staff matter to customers", 15,
       requires=("has_team",), once=True,
       fallback={"en": "Is it mostly you, or is there a team customers will meet?",
                 "ta_en": "Neenga mattum-aa, illa team irukkaa?",
                 "ta": "நீங்க மட்டுமா, இல்ல டீம் இருக்கா?"}),
    _t("b2b.customers", "Which businesses you supply",
       "which businesses or industries they serve", 58, requires=("serves_businesses",),
       essential_when=("serves_businesses",),
       fallback={"en": "Which kinds of businesses usually buy from you?",
                 "ta_en": "Endha maadhiri businesses unga kitta vaanguvaanga?",
                 "ta": "எந்த மாதிரி நிறுவனங்கள் உங்ககிட்ட வாங்குவாங்க?"}),
    _t("b2b.process", "How businesses order from you",
       "how a business buyer orders: quote request, purchase order, delivery terms", 52,
       relevant=("quote_led", "serves_businesses"), after=("b2b.customers",), once=True,
       fallback={"en": "How does a business usually order from you — do they ask for a quote first?",
                 "ta_en": "Oru company eppadi order pannuvaanga — first quote kepaangalaa?",
                 "ta": "ஒரு நிறுவனம் எப்படி ஆர்டர் பண்ணுவாங்க — முதல்ல கொட்டேஷன் கேப்பாங்களா?"}),
    _t("bookings.format", "How bookings work",
       "what is booked (appointments, tables, classes), how long it lasts, and walk-ins", 50,
       relevant=("accepts_appointments", "runs_classes"), essential_when=("accepts_appointments",),
       fallback={"en": "What do people usually book with you, and roughly how long does it take?",
                 "ta_en": "Usual-aa enna book pannuvaanga, evlo neram aagum?",
                 "ta": "வழக்கமா என்ன புக் பண்ணுவாங்க, எவ்வளவு நேரம் ஆகும்?"}),
    _t("memberships.plans", "Membership plans",
       "what plans exist (monthly, yearly) and what they include", 46,
       requires=("has_memberships",),
       fallback={"en": "What membership plans do you offer — monthly, yearly, something else?",
                 "ta_en": "Enna membership plans irukku — monthly, yearly?",
                 "ta": "என்ன மெம்பர்ஷிப் பிளான்கள் இருக்கு — மாதம், வருடம்?"}),
    _t("contact.location", "Where you are",
       "area/street and city, or the area served", 40, essential=True, fact="locations",
       fallback={"en": "Where is {name}? The area and city is enough.",
                 "ta_en": "{name} enga irukku? Area, city sonna podhum.",
                 "ta": "{name} எங்க இருக்கு? ஏரியா, ஊர் சொன்னா போதும்."}),
    _t("contact.phone", "Phone or WhatsApp number",
       "the number customers can call or WhatsApp", 38, essential=True, fact="phone",
       fallback={"en": "What number should customers call or WhatsApp?",
                 "ta_en": "Customers endha number-ku call illa WhatsApp pannanum?",
                 "ta": "கஸ்டமர்ஸ் எந்த நம்பருக்கு கால் பண்ணணும்?"}),
    _t("brand.story", "What people should remember about you",
       "what the website should make people remember or trust — freshness, where things come "
       "from, experience, speed, a family story", 50,
       after=("offerings.main", "commerce.action"), once=True,
       fallback={"en": "For the website, what should people remember about {name}? Freshness, "
                       "where things come from, your experience — or something else?",
                 "ta_en": "Website-la {name} pathi people enna nyabagam vachukkanum? "
                          "Freshness, experience — illa vera edhaavadhu?",
                 "ta": "வெப்சைட்ல {name} பத்தி மக்கள் எதை நினைவில் வைக்கணும்?"}),
    _t("brand.feel", "Look and feel",
       "how the website should feel — colours or style", 12, fact="brand", once=True,
       after=("brand.story",),
       fallback={"en": "Any colours or a style you'd like the website to have?",
                 "ta_en": "Website-ku edhaavadhu colour illa style venumaa?",
                 "ta": "வெப்சைட்டுக்கு ஏதாவது கலர் இல்ல ஸ்டைல் வேணுமா?"}),
    _t("media.logo", "Logo",
       "whether they have a logo to upload, or want Locah to create one", 24, once=True,
       after=("commerce.action",),
       fallback={"en": "Do you have a logo you can upload, or should I create a simple one for you?",
                 "ta_en": "Logo irukkaa, upload pannureengalaa — illa naan oru simple logo "
                          "ready pannattumaa?",
                 "ta": "லோகோ இருக்கா? இல்லன்னா நான் ஒன்னு ரெடி பண்ணட்டுமா?"}),
    _t("media.photos", "Photos for your website",
       "whether they have real photos of their products/place to upload — and if not, whether "
       "Locah may create draft visuals so the website does not look empty", 66, once=True,
       after=("offerings.main",),
       fallback={"en": "Do you have photos of your {things}? If not, I can create draft visuals "
                       "so the website doesn't look empty.",
                 "ta_en": "Unga {things} photos irukkaa? Illa-na website-ku naan draft visuals "
                          "ready pannattumaa?",
                 "ta": "உங்க பொருட்களோட போட்டோ இருக்கா? இல்லன்னா நான் மாதிரி படங்கள் ரெடி பண்ணட்டுமா?"}),
)
TARGETS_BY_ID: dict[str, Target] = {t.id: t for t in TARGETS}

# "All types of meat" names a category but not what goes on a menu.
_VAGUE = re.compile(
    r"\b(all (?:types|kinds|sorts|varieties)|every(?:thing| kind| type)|various|many things|"
    r"lots of|and more|etc)\b", re.I,
)

_DONE = {"answered", "declined", "deferred"}


def _catalogue_open(bp: BusinessBlueprint) -> bool:
    from platform_core.interview.taxonomy import open_structure

    return bool(open_structure(bp))


# Predicates a target can depend on (Target.when).
PREDICATES = {"catalogue_open": _catalogue_open}


def _live(target: Target, bp: BusinessBlueprint) -> bool:
    return not target.when or PREDICATES[target.when](bp)


def _addressed(bp: BusinessBlueprint, target_id: str) -> bool:
    state = bp.discovery.get(target_id)
    return bool(state and (state.status in _DONE or state.asked > 0 or state.status == "partial"))


def sync_from_facts(bp: BusinessBlueprint) -> None:
    """Targets answered by business truth held elsewhere count as answered."""
    from platform_core.interview.taxonomy import ensure_taxonomy

    ensure_taxonomy(bp)
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    for target in TARGETS:
        state = bp.discovery.setdefault(target.id, TargetState())
        if state.status in _DONE:
            continue
        fact = facts.get(target.fact) if target.fact else None
        if target.id == "business.identity":
            fact = fact or facts.get("classification") or facts.get("offerings")
        if target.id == "offerings.main" and fact:
            items = [part for part in re.split(r",|\band\b|;|/", fact.value) if part.strip()]
            if _VAGUE.search(fact.value) and len(items) < 3:
                state.status = "partial"
                state.quote = state.quote or fact.value[:600]
                continue
        if target.id == "media.logo" and (
            bp.logo_state != "not_supplied" or any(m.role == "logo" for m in bp.media_assets)
        ):
            state.status = "answered"
            continue
        if target.id == "media.photos" and (
            bp.visual_consent != "unknown"
            or any(m.role in {"business", "offering", "gallery", "hero"} and m.source == "USER_UPLOAD"
                   for m in bp.media_assets)
        ):
            state.status = "answered"
            continue
        if fact:
            state.status = "answered"
            if not state.quote:
                state.quote = fact.value[:600]


# ----------------------------------------------------------------------- planner


@dataclass(frozen=True)
class RankedTarget:
    target: Target
    score: float
    essential: bool
    observed: bool


def _relevance(target: Target, chars: dict[str, str]) -> tuple[bool, bool]:
    """(relevant, backed by what the owner said rather than only the profile)."""
    if target.requires and not target.requires <= set(chars):
        return False, False
    if target.unless & {c for c, how in chars.items() if how == "observed"}:
        return False, False
    if target.relevant and not target.relevant & set(chars):
        return False, False
    needed = (target.requires | target.relevant) & set(chars)
    observed = not needed or any(chars[c] == "observed" for c in needed)
    return True, observed


def _essential(target: Target, chars: dict[str, str]) -> bool:
    if target.essential:
        return True
    return bool(target.essential_when & {c for c, how in chars.items() if how == "observed"})


def rank(bp: BusinessBlueprint, business_type: str | None = None) -> list[RankedTarget]:
    """Open targets worth asking now, most valuable first."""
    chars = characteristics(bp, business_type)
    ranked: list[RankedTarget] = []
    for target in TARGETS:
        state = bp.discovery.get(target.id) or TargetState()
        if state.status in _DONE:
            continue
        relevant, observed = _relevance(target, chars)
        if not relevant:
            continue
        if target.once and state.asked >= 1:
            continue
        if state.asked >= 2:
            continue
        if target.after and not all(_addressed(bp, dep) for dep in target.after):
            continue
        if not _live(target, bp):
            continue
        essential = _essential(target, chars)
        # Tier first: what shapes the website before what shapes operations,
        # and both before secondary details like opening hours.
        score = (2 - target.tier) * 200 + float(target.value) * (1.0 if observed else 0.65)
        if essential:
            score += 30
        if state.status == "partial":
            score += 8  # a deeper follow-up on something half-answered
        score -= 40 * state.asked
        if bp.last_asked_target == target.id and state.status != "partial":
            continue  # never the same concept twice in a row
        ranked.append(RankedTarget(target, score, essential, observed))
    ranked.sort(key=lambda item: -item.score)
    return ranked


def readiness(bp: BusinessBlueprint, business_type: str | None = None) -> Readiness:
    """Enough for a strong first website — judged for THIS business, by coverage.

    One notion of readiness only: see `coverage.assess`.
    """
    from platform_core.interview.coverage import assess

    return assess(bp, business_type)


def _checklist_readiness(bp: BusinessBlueprint, business_type: str | None = None) -> Readiness:
    """The old checklist rule, kept only to show what it asked for (see coverage.py)."""
    chars = characteristics(bp, business_type)
    floor = ("business.identity", "offerings.main", "commerce.action")
    missing: list[str] = []
    for target in TARGETS:
        relevant, _ = _relevance(target, chars)
        if not relevant or not _essential(target, chars) or not _live(target, bp):
            continue
        state = bp.discovery.get(target.id) or TargetState()
        if state.status in _DONE:
            continue
        # Asked twice without an answer: the owner has chosen not to say.
        if state.asked >= 2:
            continue
        if target.id == "offerings.main" and state.status == "partial" and state.asked >= 1:
            continue
        missing.append(target.id)
    # Worth asking once before the first version even though neither blocks
    # it: the story the site tells, and whether there is a logo (or one to make).
    soft_pending = [
        target_id for target_id in ("brand.story", "media.photos", "media.logo")
        if (lambda t, s: _relevance(t, chars)[0] and s.status not in _DONE and s.asked == 0)(
            TARGETS_BY_ID[target_id], bp.discovery.get(target_id) or TargetState())
    ]
    story_pending = bool(soft_pending)
    floor_met = all(
        (bp.discovery.get(t) or TargetState()).status in {"answered", "partial"} for t in floor
    )
    owner_turns = sum(1 for m in bp.messages if m.role == "user")
    website = website_readiness(bp)
    if floor_met and not missing and not story_pending:
        return Readiness(ready=True, missing=[], website=website,
                         reason="Everything essential for this business is known.")
    if floor_met and owner_turns >= 14:
        return Readiness(ready=True, missing=missing, website=website,
                         reason="Enough for a first version; the rest can follow.")
    pending = missing + soft_pending
    reason = "Still worth knowing: " + ", ".join(TARGETS_BY_ID[t].label.lower() for t in pending[:3])
    return Readiness(ready=False, missing=pending, website=website, reason=reason[:200])


def website_readiness(bp: BusinessBlueprint) -> dict[str, bool]:
    """Can the first website be DESIGNED well? Separate from operational completeness."""
    state = bp.discovery

    def done(target_id: str) -> bool:
        s = state.get(target_id)
        return bool(s and (s.status in {"answered", "partial"} or s.asked > 0))

    content = done("offerings.main") and not _catalogue_open(bp) or bool(
        state.get("offerings.structure") and state["offerings.structure"].asked > 0)
    return {
        "content": bool(content),
        "conversion": done("commerce.action"),
        "visuals": bp.visual_consent != "unknown" or any(
            m.role != "logo" for m in bp.media_assets),
        "story": done("brand.story"),
        "structure": bool(bp.taxonomy.groups),
    }


def candidates(bp: BusinessBlueprint, business_type: str | None = None, limit: int = 6) -> list[dict[str, str]]:
    """The short list the model may phrase its next question from."""
    return [
        {"id": item.target.id, "learn": item.target.learn,
         "why": "essential for this business" if item.essential else "useful"}
        for item in rank(bp, business_type)[:limit]
    ]


def choose(
    bp: BusinessBlueprint, proposed: str, business_type: str | None = None, window: int = 4
) -> str | None:
    """The model's proposal if it is still worth asking, else the planner's own.

    The model hears the conversation; the ranking only knows what is missing.
    So the model may follow the flow — "they book tables" leads naturally to
    how bookings work — as long as what it proposes is relevant, open, not
    just asked, and either essential or near the top.
    """
    ranked = rank(bp, business_type)
    if not ranked:
        return None
    # The model follows the conversation, but only within the tier that
    # matters now: it may not ask about delivery while the range is unknown.
    tier = ranked[0].target.tier
    for index, item in enumerate(ranked):
        if item.target.id == proposed and item.target.tier <= tier and (
            item.essential or index < window
        ):
            return proposed
    return ranked[0].target.id


# ------------------------------------------------------------------ phrasing


def _short_list(text: str, limit: int = 3) -> str:
    items = [p.strip(" .") for p in re.split(r",|;|\band\b", text) if p.strip(" .")]
    items = [i for i in items if not _VAGUE.search(i)][:limit]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def fallback_question(target_id: str, bp: BusinessBlueprint, style: str) -> str:
    """Emergency phrasing for one target, filled from what is already known."""
    target = TARGETS_BY_ID[target_id]
    if target_id == "offerings.structure":
        from platform_core.interview.taxonomy import structure_question

        return structure_question(bp, style) or "Which ones do customers usually ask for?"
    lang = style if style in target.fallback else ("ta_en" if style.startswith("ta") else "en")
    template = target.fallback.get(lang) or target.fallback["en"]
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    name = bp.identity["display_name"].value if "display_name" in bp.identity else "your business"
    offerings = facts["offerings"].value if "offerings" in facts else ""
    chars = characteristics(bp)
    # The words the owner would use: "projects", "products", "services" —
    # never the placeholder "things you offer".
    things = (
        "projects" if "sells_property" in chars
        else "products" if "sells_products" in chars
        else "services" if "provides_services" in chars
        else "work"
    )
    listed = _short_list(offerings)
    about = f" {listed}" if listed and len(listed) < 60 else ""
    units = (bp.discovery.get("offerings.units") or TargetState()).summary.lower()
    per = " per kg" if re.search(r"\b(kg|kilo|weight)", units) else ""
    return str(template.format(name=name, things=things, about=about, per=per)).strip()
