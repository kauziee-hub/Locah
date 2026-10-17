"""The business owners of the Website Builder Certification (docs/certification/PLAN.md §1).

Twelve scenarios, each told six ways, plus a distinctness set of 25 further owners:

* ``rich``        — a detailed story, a full priced list (8-20 items in 3-5 groups, each
                    described), positioning, look-and-feel wishes, hours, phone, address and,
                    where real photographs exist on disk, 3-6 owner photos;
* ``normal``      — short answers the way a real owner types them, partial prices;
* ``bad_input``   — misspellings, run-on and vague sentences, Tanglish / Hinglish / Manglish,
                    half-finished descriptions — still the same business, same facts;
* ``minimal``     — only what is genuinely required: what it is, its name, one way to reach it;
* ``no_photos``   — ``normal``, plus the owner saying plainly that they have no photos;
* ``owner_media`` — ``normal``, plus the owner's own photos (they must take precedence).

An :class:`OwnerScript` answers the interview by *ask id* — the planner's question ids
(``platform_core.interview.planner.ASKS``: identity, offer, structure, catalogue, …) — and
says ``fallback`` to anything else. ``confirm_text`` is what the owner says when shown the
summary to confirm.

The truth rule: every variant of a scenario is the same business with the same facts —
the same name, place, phone, prices and offer. Nothing an owner says contradicts it.

Owner photos are real files in ``apps/web/public/site-lab-photos`` (Pixabay copies from the
premium lab). Only a bakery and a meat/seafood shop have photos there that could truthfully
be their own; every other scenario has ``media=()`` and is listed in :data:`MEDIA_GAPS`, so
the harness reports that its ``owner_media`` journey could not test owner-photo precedence
rather than pretending a stranger's photo is the business's.

    from platform_testing.certify.owners import SCENARIOS, DISTINCT, journeys
    for scenario, variant in journeys():          # 72 + 25
        script = scenario.variants[variant]
        script.reply("contact")                   # the owner's answer to that question
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PHOTO_DIR = ROOT / "apps" / "web" / "public" / "site-lab-photos"

VARIANTS: tuple[str, ...] = ("rich", "normal", "bad_input", "minimal", "no_photos", "owner_media")

# The interview's question ids (platform_core.interview.planner.ASKS), in planner order.
ASK_IDS: tuple[str, ...] = (
    "identity", "offer", "structure", "catalogue", "traits", "conversion", "fulfilment", "area",
    "contact", "phone", "b2b", "process", "providers", "units", "plans", "bookings", "story",
    "photos", "payment", "customisation", "pricing", "hours", "team", "logo", "look", "stock",
)

# Reference images in docs/visual-references/BRIEF.md that fit each kind of business.
REFS: dict[str, tuple[str, ...]] = {
    "restaurant": ("ref_05", "ref_06", "ref_07"),
    "gym": ("ref_08",),
    "salon": ("ref_11", "ref_12"),
    "clinic": ("ref_13", "ref_14"),
    "consultant": ("ref_09",),
    "architecture": ("ref_01", "ref_02", "ref_03", "ref_04"),
    "hotel": ("ref_15",),
    "ngo": ("ref_10",),
    "retail": ("ref_04", "ref_05", "ref_07"),  # food- and material-led retail, bakery, meat
}

# Module sets (ids from platform_core.catalog.modules), as in PLAN.md §1.
DELIVERY_KITCHEN = ("offerings-catalog", "orders", "payments", "fulfilment")
TABLE_BOOKING = ("offerings-catalog", "bookings")
COUNTER_ORDERS = ("offerings-catalog", "orders", "fulfilment")
CATALOGUE_ONLY = ("offerings-catalog",)
GYM = ("offerings-catalog", "memberships", "bookings", "payments")
SALON = ("offerings-catalog", "bookings", "payments")
CLINIC = ("offerings-catalog", "bookings", "queue-operations", "workforce")
ADVISORY = ("offerings-catalog", "leads", "customer-relationships", "invoicing")
STORE = ("offerings-catalog", "inventory", "orders", "payments", "fulfilment")
DESIGN_PRACTICE = ("offerings-catalog", "leads", "quotes", "projects")
STAY = ("offerings-catalog", "bookings", "payments")
CAUSE = ("donations", "leads")


@dataclass(frozen=True)
class OwnerScript:
    opening: str
    answers: dict[str, str]
    fallback: str
    media: tuple[str, ...] = ()  # absolute paths of the owner's own photos
    confirm_text: str = ""

    def reply(self, ask_id: str | None) -> str:
        """What this owner says when asked `ask_id`."""
        return self.answers.get(ask_id or "") or self.fallback

    def text(self) -> str:
        """Everything this owner would type, opening first."""
        return "\n".join([self.opening, *self.answers.values()])


@dataclass(frozen=True)
class Scenario:
    key: str
    business_name: str
    category_hint: str  # "<category_key>/<subcategory_key>" of platform_core.catalog.taxonomy
    business_type: str  # the taxonomy category's legacy template (business_types.SUPPORTED_BUSINESS_TYPES)
    modules: tuple[str, ...]  # switched on besides the core website
    variants: dict[str, OwnerScript]
    reference_ids: tuple[str, ...]
    place: str = ""  # "Area, City" — the owner's place, said in every full variant
    phone: str = ""  # the one number this owner gives, in every variant
    kind: str = ""  # restaurant | gym | salon | clinic | consultant | … (a REFS key)

    @property
    def category_key(self) -> str:
        return self.category_hint.split("/", 1)[0]

    @property
    def subcategory_key(self) -> str:
        return self.category_hint.split("/", 1)[1] if "/" in self.category_hint else ""

    def site_key(self, variant: str) -> str:
        return f"{self.key}--{variant}"


# ------------------------------------------------------------------ helpers

Item = tuple[str, int, str, str]  # name, price in rupees, unit ("" | "per kg" | …), description


def inr(rupees: int) -> str:
    """₹1,25,000 — Indian digit grouping."""
    digits = str(rupees)
    if len(digits) <= 3:
        return f"₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join([*groups, tail])


def menu(groups: dict[str, list[Item]]) -> str:
    """A priced list the way an organised owner types it into the chat."""
    lines: list[str] = []
    for group, items in groups.items():
        lines.append(f"{group}:")
        for name, price, unit, note in items:
            cost = inr(price) + (f" {unit}" if unit else "")
            lines.append(f"- {name}, {cost}" + (f" — {note}" if note else ""))
    return "\n".join(lines)


def _photos(folder: str, *names: str) -> tuple[str, ...]:
    return tuple(str(PHOTO_DIR / folder / name) for name in names)


def _variants(
    *, rich: OwnerScript, normal: OwnerScript, bad_input: OwnerScript, minimal: OwnerScript,
    no_photos: str, own_photos: str, media: tuple[str, ...] = (),
) -> dict[str, OwnerScript]:
    """The six tellings; ``no_photos`` and ``owner_media`` are ``normal`` plus one fact."""
    without = replace(normal, opening=f"{normal.opening} {no_photos}",
                      answers={**normal.answers, "photos": no_photos})
    if media:
        with_media = replace(normal, opening=f"{normal.opening} {own_photos}",
                             answers={**normal.answers, "photos": own_photos}, media=media)
    else:  # no real photo of this trade on disk: the owner never claims to attach one
        with_media = replace(normal, answers={**normal.answers, "photos": own_photos})
    return {"rich": rich, "normal": normal, "bad_input": bad_input, "minimal": minimal,
            "no_photos": without, "owner_media": with_media}


# ------------------------------------------------------------------ owner photographs

# What each file shows (checked by eye). Only these could truthfully be the owner's own.
MEAT_PHOTOS: dict[str, str] = {
    "lab-ishant/pixabay-3359248.jpg": "two thick mutton chops with rosemary and peppercorns",
    "lab-ishant/pixabay-6935871.jpg": "a dressed whole chicken on a wooden board",
    "lab-cleaver/pixabay-279849.jpg": "three skinless chicken breast fillets on a white plate",
    "lab-ishant/pixabay-8210152.jpg": "a pile of fresh small silver fish",
    "lab-ishant/pixabay-1261432.jpg": "fresh whole squid",
    "lab-ishant/pixabay-93513.jpg": "hands cleaning a fish with a knife on a stone counter",
}
BAKERY_PHOTOS: dict[str, str] = {
    "lab-crumb/pixabay-2595658.jpg": "a cut sourdough loaf with an open crumb on a wooden board",
    "lab-crumb/pixabay-1051884.jpg": "sprinkle-decorated cut-out butter cookies (stars, gingerbread men)",
    "lab-crumb/pixabay-4887101.jpg": "a plain wheat sandwich loaf",
    "lab-crumb/pixabay-1378049.jpg": "a sliced garlic-herb baguette",
}
# On disk, but not any certification business's own: never offered as owner media.
NOT_THE_OWNERS: dict[str, str] = {
    "lab-cleaver/pixabay-4031589.jpg": "beef ribeye steak — no scenario sells beef",
    "lab-cleaver/pixabay-6565726.jpg": "dry-aged beef — no scenario sells beef",
    "lab-ishant/pixabay-1123286.jpg": "raw salmon texture — not a fish an Indian shop here sells",
    "lab-crumb/pixabay-3082589.jpg": "a child's hands kneading dough in a plastic bowl at home — not a bakery",
    "lab-cleaver/pixabay-3359248.jpg": "duplicate of lab-ishant/pixabay-3359248.jpg",
}

# Scenarios with no truthful owner photographs on disk: their rich and owner_media
# journeys run without media, and the harness reports the gap instead of faking it.
MEDIA_GAPS: dict[str, str] = {
    "restaurant-delivery": "no photos of Kerala dishes or a delivery kitchen on disk",
    "restaurant-reservations": "no photos of coastal dishes or a dining room on disk",
    "gym": "no photos of a strength gym on disk",
    "salon": "no photos of a salon or bridal work on disk",
    "clinic": "no photos of a clinic, doctors or a lab on disk",
    "consultant": "no portrait of the consultant on disk",
    "retail": "no photos of kansa, cast-iron or clay cookware on disk",
    "architecture": "no photos of the studio's built projects on disk",
    "hotel": "no photos of the estate's rooms or the valley on disk",
    "ngo": "no photos of the learning centres (with consent) on disk",
}

# Words misspelt on purpose in bad_input (each one the owner's slip, never a real word
# the clean variants use).
MISSPELLINGS: frozenset[str] = frozenset({
    "kichen", "rost", "ordr", "chiken", "delivry", "whatsap", "colur", "tel", "biriyani",
    "restarant", "indranagar", "shud", "bookng", "fixd", "frm", "nite", "leev",
    "sourdugh", "bred", "baguete", "strenght", "strenth", "clases", "traning", "membrship",
    "quartly", "sesions", "coching", "al", "nd", "bridel", "apointment", "keratine",
    "doctrs", "consultaion", "doctr", "morn", "consultng", "famly", "invoce", "projct",
    "advisry", "coper", "changng", "archtects", "restoraton", "enqury", "qoute", "interors",
    "depnds", "cofee", "vilas", "bunglow", "cotage", "vila", "lerning", "tution", "volunter",
    "schlorship", "reciept", "kadavantra",
})


# ------------------------------------------------------------------ rich catalogues

CATALOGUES: dict[str, dict[str, list[Item]]] = {
    "restaurant-delivery": {
        "Biryanis": [
            ("Malabar chicken dum biryani", 280, "", "Wayanad kaima rice, slow dum, with date pickle and raita"),
            ("Malabar mutton dum biryani", 360, "", "Goat on the bone, fried shallots and ghee"),
            ("Family pack chicken biryani", 1050, "serves 3-4", "Four portions in one sealed tin"),
        ],
        "Appam & stews": [
            ("Appam (2 pcs)", 50, "", "Soft centre, lacy edges, made to order"),
            ("Chicken stew", 240, "", "Coconut milk, whole spices and potato, mild"),
            ("Vegetable stew", 180, "", "Carrot, beans and potato in coconut milk"),
            ("Kuttanad duck roast", 420, "", "Duck slow-roasted with shallots and black pepper"),
        ],
        "Meals": [
            ("Kerala veg meals", 180, "", "Matta rice, sambar, avial, thoran, pachadi and pappadam"),
            ("Fish curry meals", 260, "", "Veg meals with kudampuli fish curry and a fish fry"),
        ],
        "Seafood specials": [
            ("Karimeen pollichathu", 480, "", "Pearl spot in banana leaf with masala, weekends only"),
            ("Prawn roast", 380, "", "Dry-roasted with coconut slivers and curry leaves"),
        ],
        "Desserts": [
            ("Palada payasam", 110, "", "Rice ada slow-cooked in milk"),
            ("Tender coconut pudding", 140, "", "Chilled, with tender coconut flesh"),
        ],
    },
    "restaurant-reservations": {
        "Small plates": [
            ("Chicken ghee roast", 420, "", "Kundapur-style, red chilli and ghee, the masala roasted for two hours"),
            ("Kane rava fry", 520, "", "Ladyfish in a semolina crust, from the Mangalore catch"),
            ("Prawn rava fry", 480, "", "Tiger prawns, rava and recheado spice"),
        ],
        "Curries": [
            ("Pomfret gassi", 560, "", "Coconut and roasted chilli curry, best with neer dosa"),
            ("Kori rotti", 440, "", "Chicken curry poured over crisp rice wafers"),
            ("Goan prawn balchão", 520, "", "Tangy, fiery, pickle-style prawns"),
            ("Mushroom and cashew sukka", 340, "", "Dry coconut masala, our vegetarian favourite"),
        ],
        "Breads & rice": [
            ("Neer dosa (4 pcs)", 120, "", "Thin rice crêpes, made to order"),
            ("Sannas (2 pcs)", 110, "", "Steamed, toddy-leavened rice cakes"),
            ("Kundapur boiled rice", 90, "", "Red boiled rice, the way it is eaten at home"),
        ],
        "Desserts": [
            ("Tender coconut payasam", 220, "", "Cold, light and not too sweet"),
            ("Bebinca", 240, "", "Goan layered coconut cake, contains egg"),
        ],
    },
    "meat-shop": {
        "Chicken": [
            ("Chicken curry cut (with skin)", 240, "per kg", "Cut after you order, washed twice"),
            ("Skinless curry cut", 280, "per kg", "Small or big pieces, as you ask"),
            ("Boneless breast", 380, "per kg", "Trimmed breast fillets"),
            ("Whole chicken", 220, "per kg", "Dressed whole bird, about 1.2 kg"),
            ("Chicken wings", 260, "per kg", "Party wings, tips removed"),
        ],
        "Mutton": [
            ("Mutton curry cut", 850, "per kg", "Goat, mixed pieces from the leg and shoulder"),
            ("Mutton chops", 920, "per kg", "Rib chops, cut thick or thin as you ask"),
            ("Mutton keema", 900, "per kg", "Minced fresh in front of you"),
            ("Liver and boti", 600, "per kg", "Cleaned and cut small"),
        ],
        "Seafood": [
            ("Seer fish (vanjaram)", 950, "per kg", "Slices or whole, cleaned"),
            ("Pomfret", 750, "per kg", "Whole, cleaned and scored"),
            ("Kilanga (small fish)", 380, "per kg", "Whole small fish, cleaned and headed"),
            ("Squid", 420, "per kg", "Cleaned; cut into rings on request"),
            ("Prawns", 560, "per kg", "Medium, peeled and deveined"),
        ],
    },
    "bakery": {
        "Breads": [
            ("Country sourdough", 220, "per loaf", "48-hour ferment, open crumb, crackly crust"),
            ("Whole-wheat sandwich loaf", 90, "per loaf", "100% atta, no maida, soft for sandwiches"),
            ("Multigrain loaf", 130, "per loaf", "Oats, flax and sunflower seeds"),
            ("Milk bread", 60, "per loaf", "Soft white loaf for toast and school tiffin"),
        ],
        "Baguettes & pav": [
            ("Garlic herb baguette", 120, "", "Garlic, parsley and butter, out of the oven at 7 am and 4 pm"),
            ("Classic baguette", 100, "", "Thin crust, light inside"),
            ("Ladi pav (6 pcs)", 45, "", "Soft pav for misal and bhaji"),
        ],
        "Cookies": [
            ("Sprinkle cut-out cookies", 220, "per 250 g", "Butter shortbread stars and gingerbread men, a kids' favourite"),
            ("Nankhatai", 160, "per 250 g", "Ghee and cardamom, melts in the mouth"),
            ("Oat and jaggery cookies", 200, "per 250 g", "No refined sugar"),
        ],
        "Cakes to order": [
            ("Chocolate truffle cake", 950, "per kg", "Order two days ahead"),
            ("Pineapple fresh cream cake", 750, "per kg", "Light sponge, real pineapple"),
            ("Custom photo cake", 1200, "per kg", "Your name and photo, two days' notice"),
        ],
    },
    "gym": {
        "Memberships": [
            ("Open gym, monthly", 3500, "per month", "Full floor access, 6 am to 10 pm"),
            ("Quarterly", 9500, "for 3 months", "Open gym plus two classes a week"),
            ("Annual", 32000, "per year", "All classes included, two months' freeze"),
        ],
        "Class packs": [
            ("12-class pack", 4800, "", "Small-group strength, max 8 people, valid six weeks"),
            ("Drop-in class", 500, "", "One small-group class"),
        ],
        "Personal training": [
            ("PT, 12 sessions", 14400, "", "One-on-one, 60 minutes, programme and diet check-ins"),
            ("PT, 24 sessions", 26400, "", "One-on-one, 60 minutes, priority slots"),
        ],
        "Courses": [
            ("Beginner barbell course", 7500, "for 6 weeks", "Squat, bench and deadlift from zero, three days a week"),
            ("Women's strength 101", 5500, "for 4 weeks", "Coached by Divya, small group"),
        ],
    },
    "salon": {
        "Hair": [
            ("Women's haircut and styling", 900, "", "Consultation, wash, cut and blow-dry"),
            ("Men's haircut", 450, "", "Cut, wash and style, 30 minutes"),
            ("Global colour", 3500, "onwards", "Ammonia-free, priced by hair length"),
            ("Balayage", 6500, "onwards", "Hand-painted, soft grown-out highlights"),
            ("Keratin smoothening", 5500, "onwards", "Frizz-free for about four months"),
        ],
        "Skin": [
            ("Hydrating facial", 2200, "", "60 minutes, for dry and tired skin"),
            ("De-tan clean-up", 1200, "", "45 minutes, after a long summer"),
            ("Pre-bridal glow facial", 3500, "per session", "A series of three before the wedding"),
        ],
        "Bridal & makeup": [
            ("Bridal makeup", 18000, "", "HD makeup, draping and hair, trial included"),
            ("Reception makeup", 12000, "", "Evening look with hairstyling"),
            ("Party makeup", 4500, "", "For guests and family, 60 minutes"),
        ],
        "Nails": [
            ("Gel manicure", 1500, "", "Shaping, cuticle care and gel colour that lasts three weeks"),
            ("Spa pedicure", 1400, "", "Soak, scrub, massage and polish"),
        ],
    },
    "clinic": {
        "Consultations": [
            ("General physician consultation", 500, "", "Dr. Meera Raghavan, about 15 minutes"),
            ("Child specialist consultation", 600, "", "Dr. Arun Prakash, about 15 minutes"),
            ("Follow-up visit", 250, "", "Within 7 days of the first visit"),
        ],
        "Chronic care": [
            ("Diabetes review", 800, "", "Consultation, HbA1c and a diet plan"),
            ("BP and heart check", 700, "", "Consultation and ECG"),
            ("Thyroid review", 650, "", "Consultation and TSH test"),
        ],
        "Lab tests": [
            ("Complete blood count", 350, "", "Results the same evening on WhatsApp"),
            ("HbA1c", 450, "", "Three-month sugar average"),
            ("Lipid profile", 600, "", "12-hour fasting sample"),
            ("Fasting blood sugar", 100, "", "Sample before 10 am"),
        ],
        "Vaccinations": [
            ("Child vaccination visit", 400, "", "Plus the vaccine's cost, as per the IAP schedule"),
            ("Adult flu shot", 1500, "", "Vaccine included"),
        ],
    },
    "consultant": {
        "Audits": [
            ("Growth and margin audit", 45000, "", "3 weeks: your numbers, pricing and channels, with a written plan"),
            ("Pricing health check", 25000, "", "One product line, 10 days"),
        ],
        "Advisory": [
            ("Monthly advisory retainer", 60000, "per month",
             "Two strategy sessions a month and WhatsApp access; 3-month minimum"),
            ("Board meeting preparation", 15000, "per meeting", "Numbers, agenda and a one-page brief"),
        ],
        "Workshops": [
            ("Pricing workshop for teams", 35000, "", "Half a day, up to 15 people, in Kochi"),
            ("Founder 1:1 session", 6000, "", "90 minutes, online or in person"),
        ],
        "Projects": [
            ("D2C launch plan", 90000, "", "6 weeks: pricing, channels and unit economics"),
            ("Family business succession roadmap", 120000, "", "8 weeks, working with the whole family"),
        ],
    },
    "retail": {
        "Kansa (bronze)": [
            ("Kansa thali set (6 pcs)", 6800, "", "Plate, two bowls, glass and spoon, hand-beaten in Odisha"),
            ("Kansa glass", 950, "", "Hand-beaten, about 250 ml"),
            ("Kansa bowl", 1100, "", "For payasam, curd and dal"),
        ],
        "Cast iron": [
            ("Pre-seasoned dosa tawa, 12 inch", 1650, "", "Seasoned with sesame oil, ready to use"),
            ("Cast-iron kadai, 10 inch", 1850, "", "For frying and slow curries"),
            ("Paniyaram pan", 1350, "", "12 pits, pre-seasoned"),
        ],
        "Brass & copper": [
            ("Copper water bottle, 1 litre", 1250, "", "Pure copper, leak-proof lid"),
            ("Brass uruli", 4200, "", "Tin-lined, for payasam and festive cooking"),
            ("Copper jug, 1.5 litre", 1900, "", "Hammered finish"),
        ],
        "Clay & stone": [
            ("Manamadurai clay pot, 2 litre", 650, "", "Pre-cured, for fish curry and curd"),
            ("Mandya clay tawa", 450, "", "Pre-cured, for rotti and dosa"),
            ("Soapstone kal chatti", 1450, "", "Pre-seasoned, for kuzhambu and rasam"),
        ],
    },
    "architecture": {
        "Architecture": [
            ("New home design", 220, "per sq ft onwards", "Concept to construction drawings, site visits included"),
            ("Farmhouse and villa design", 260, "per sq ft onwards", "Plans, landscape and lighting"),
            ("Small hotels and homestays", 280, "per sq ft onwards", "Planning, rooms, guest flow and licence drawings"),
        ],
        "Interiors": [
            ("Full-home interiors, design and build", 1800, "per sq ft onwards",
             "Design and execution with our own carpenters"),
            ("Interior design only", 120, "per sq ft onwards", "Drawings, material boards and site supervision"),
        ],
        "Restoration": [
            ("Heritage restoration study", 75000, "", "Measured drawings, a condition report and a restoration plan"),
            ("Restoration design", 300, "per sq ft onwards", "Lime, laterite and reclaimed timber"),
        ],
        "Consultations": [
            ("Site visit and consultation", 5000, "", "Within Kochi; adjusted in the fee if you go ahead"),
            ("Review of an existing plan", 15000, "", "Written notes and a marked-up drawing"),
        ],
    },
    "hotel": {
        "Rooms": [
            ("Planter's bungalow room", 7500, "per night", "Heritage room in the 1920s bungalow, breakfast included"),
            ("Valley-view cottage", 9500, "per night", "Private sit-out over the valley, breakfast included"),
            ("Family cottage", 12500, "per night", "Two bedrooms, sleeps four, breakfast included"),
            ("Pool villa", 18500, "per night", "Private plunge pool, breakfast and dinner included"),
        ],
        "Packages": [
            ("Coffee estate weekend (2 nights)", 21000, "", "Valley-view cottage, all meals and an estate walk"),
            ("Honeymoon escape (3 nights)", 42000, "", "Pool villa, a candle-lit dinner and a drive to Abbey Falls"),
        ],
        "Experiences": [
            ("Coffee estate walk", 800, "per person", "Two hours through coffee and pepper, ending with a tasting"),
            ("Dawn birding walk", 1000, "per person", "With our naturalist, binoculars provided"),
            ("Kodava cooking class", 1500, "per person", "Pandi curry and kadambuttu with our cook"),
        ],
        "Dining": [
            ("Kodava dinner", 1200, "per person", "Pandi curry, akki rotti and bamboo-shoot curry"),
        ],
    },
    "ngo": {
        "Sponsor a child": [
            ("One child's learning for a year", 6000, "", "Books, a trained teacher and an evening snack"),
            ("Girls' scholarship, Class 11-12", 18000, "per year", "School fees, a bus pass and books"),
        ],
        "Support a centre": [
            ("A library shelf", 3500, "", "Fifty new Tamil and English books"),
            ("A month of evening snacks", 9000, "", "For 140 children at one centre"),
            ("A teacher's monthly stipend", 12000, "", "Most of our teachers are from the neighbourhood"),
            ("Spoken English kit for a class", 4500, "", "Readers, flashcards and audio for 30 children"),
        ],
        "Give monthly": [
            ("Monthly friend", 500, "per month", "Funds a child's reading kit"),
            ("Monthly champion", 1000, "per month", "Funds a child's year of maths workbooks"),
            ("Monthly centre partner", 5000, "per month", "Keeps one centre's lights and fans running"),
        ],
    },
}


def _catalogue(key: str) -> str:
    return "Here is the full list with prices:\n" + menu(CATALOGUES[key])


# ------------------------------------------------------------------ the twelve scenarios

NO_PHOTOS = "No photos with me — you can arrange them."
LATER_PHOTOS = "I have some photos on my phone, I'll add them later from the editor."


def _restaurant_delivery() -> Scenario:
    phone = "98470 21456"
    rich = OwnerScript(
        opening=(
            "Pepper Vine Kitchen is a delivery kitchen in Kadavanthra, Kochi. We cook Kerala home-style "
            "food — Malabar biryanis, appam with stew, Kerala meals and Kuttanad duck roast — and deliver "
            "it hot within about 6 km. My wife Susan and I started it in 2019 after fifteen years cooking "
            "in hotel kitchens in the Gulf. Orders come on WhatsApp now; we want people to order and pay "
            "on the website instead."
        ),
        answers={
            "identity": "A Kerala delivery kitchen: home-style Malabar and Kuttanad dishes, cooked fresh, "
                        "for families and office lunches around Kadavanthra, Panampilly Nagar and MG Road.",
            "offer": "Malabar chicken and mutton biryani, appam with chicken or vegetable stew, Kerala meals, "
                     "Kuttanad duck roast, karimeen pollichathu on weekends, prawn roast and payasam.",
            "structure": "Biryanis, Appam & stews, Meals, Seafood specials and Desserts. Biryani also comes "
                         "as a family pack that serves 3-4.",
            "catalogue": _catalogue("restaurant-delivery"),
            "traits": "Malabar chicken biryani, appam with chicken stew and the duck roast sell the most. "
                      "Vegetable stew, veg meals, appam and the desserts are vegetarian; the rest is non-veg.",
            "conversion": "Order on the website and pay online by UPI or card. WhatsApp only for bulk orders.",
            "fulfilment": "We deliver ourselves within 6 km of Kadavanthra — Panampilly Nagar, Giri Nagar, "
                          "Elamkulam, Vyttila, MG Road and Marine Drive. Pickup from the kitchen is fine too.",
            "area": "Panampilly Nagar, Giri Nagar, Elamkulam, Vyttila, MG Road and Marine Drive — about 6 km "
                    "around Kadavanthra.",
            "contact": f"42/1180 Sahodaran Ayyappan Road, Kadavanthra, Kochi 682020. Call or WhatsApp {phone}.",
            "phone": phone,
            "b2b": "Some offices order lunch for 20-30 people; they WhatsApp us a day before.",
            "process": "For office lunches they send the headcount a day before and we confirm the menu and price.",
            "units": "By the plate; biryani also as a family pack.",
            "bookings": "No table booking — we are delivery and pickup only.",
            "story": "We cook the way Susan's mother does in Kuttanad: coconut oil, masala ground fresh every "
                     "morning, nothing from packets. The biryani rice is kaima from Wayanad. Food leaves the "
                     "kitchen within 25 minutes of cooking, packed in sealed tins.",
            "photos": LATER_PHOTOS,
            "payment": "UPI or card online when they order; cash on delivery is also okay.",
            "customisation": "Spice level mild, medium or Kerala-hot. Family packs for parties with a day's notice.",
            "pricing": "Show the full prices.",
            "hours": "Lunch 11:30 am to 3 pm, dinner 6:30 pm to 10:30 pm. Closed Monday lunch.",
            "team": "I cook with two cooks, Susan handles orders, and two delivery riders.",
            "logo": "No proper logo yet — just set the name nicely.",
            "look": "Warm and appetising, like a Kerala tharavad kitchen — deep green, banana leaf and brass. "
                    "Calm and premium, not fast-food red.",
            "stock": "Duck roast and karimeen are limited each day — show sold out when they finish.",
        },
        fallback="Use your judgement, but keep it honest — only what I told you.",
        confirm_text="Yes, that's right. Please build it.",
    )
    normal = OwnerScript(
        opening=("Pepper Vine Kitchen, Kadavanthra, Kochi. Kerala food delivery — biryani, appam stew, meals, "
                 "duck roast. We deliver around 6 km."),
        answers={
            "offer": "Chicken biryani, mutton biryani, appam with stew, Kerala meals, duck roast, fish curry meals.",
            "catalogue": "Chicken biryani 280, mutton biryani 360, appam 2 pcs 50, chicken stew 240, veg meals "
                         "180, duck roast 420. Others I'll add later.",
            "traits": "Biryani and duck roast sell most. Veg meals and veg stew are veg.",
            "conversion": "Order on the website and pay online. Or WhatsApp.",
            "fulfilment": "We deliver around Kadavanthra, Panampilly Nagar, Vyttila. Pickup also ok.",
            "area": "Kadavanthra, Panampilly Nagar, Vyttila, MG Road.",
            "contact": f"Kadavanthra, Kochi. {phone}",
            "phone": phone,
            "payment": "UPI or card online, cash on delivery also ok.",
            "hours": "11:30 to 3 and 6:30 to 10:30.",
            "story": "Home-style Kerala cooking, fresh masala every day.",
            "pricing": "Show prices.",
        },
        fallback="Not sure. Keep it simple.",
        confirm_text="Yes ok, build it.",
    )
    bad = OwnerScript(
        opening=("hi this is pepper vine kichen in kadavantra kochi, we make kerala food biriyani appam stew "
                 "meals duck rost etc and we deliver also near by areas, ordr online pay online that is what i want"),
        answers={
            "offer": "chiken biriyani mutton biriyani appam stew, meals veg and fish, duck rost, payasam also some days",
            "catalogue": "chiken biriyani 280 mutton 360 appam 50 for 2, stew chiken 240 veg 180, meals 180, "
                         "fish meals 260 duck 420... rest i will tel later",
            "traits": "biriyani is best seller,duck also. veg meals is veg ofcourse",
            "conversion": "online ordr and payment, whatsap also fine for bulk",
            "fulfilment": "we deliver near by 6 km only, pickup also ok no problem",
            "area": "kadavantra, panampilly nagar, vytila, mg road side",
            "contact": f"kadavantra kochi near the junction, {phone} call or whatsap",
            "phone": phone,
            "payment": "upi card online, cash on delivry also",
            "hours": "lunch and dinner, monday lunch closed",
            "story": "home style kerala food, nammal fresh masala daily, no packet masala",
            "look": "green colur, kerala feel, not too flashy",
        },
        fallback="dont know, u decide",
        confirm_text="ok fine go ahead",
    )
    minimal = OwnerScript(
        opening="Pepper Vine Kitchen — Kerala food delivery in Kochi.",
        answers={"identity": "Kerala food, delivered.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Just call {phone}."},
        fallback="Skip that for now.",
        confirm_text="ok",
    )
    return Scenario(
        key="restaurant-delivery", business_name="Pepper Vine Kitchen", category_hint="food_service/restaurant",
        business_type="restaurant", modules=DELIVERY_KITCHEN, reference_ids=REFS["restaurant"],
        place="Kadavanthra, Kochi", phone=phone, kind="restaurant",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal,
                           no_photos=NO_PHOTOS, own_photos=LATER_PHOTOS),
    )


def _restaurant_reservations() -> Scenario:
    phone = "98450 33721"
    rich = OwnerScript(
        opening=(
            "Konkan Table is a 40-seat coastal dining room on 12th Main, Indiranagar, Bengaluru. We cook "
            "Mangalorean and Goan-Konkan food — chicken ghee roast, kane rava fry, pomfret gassi, kori rotti, "
            "Goan prawn balchão — with fish that comes from Mangalore three times a week. Most guests come for "
            "dinner and I want them to reserve a table on the website. I'm Rohan Shenoy; I grew up in my "
            "aunt's kitchen in Kundapur."
        ),
        answers={
            "identity": "A coastal Konkan restaurant for dinners and weekend lunches — couples, families, and "
                        "people who miss home food from Mangalore and Goa.",
            "offer": "Chicken ghee roast, kane rava fry, pomfret gassi, kori rotti, prawn balchão, neer dosa, "
                     "sannas, and tender coconut payasam.",
            "structure": "Small plates, Curries, Breads & rice, and Desserts.",
            "catalogue": _catalogue("restaurant-reservations"),
            "traits": "Chicken ghee roast, kane rava fry and pomfret gassi are what people come back for. The "
                      "mushroom sukka, breads, rice and payasam are vegetarian; bebinca has egg; the rest is non-veg.",
            "conversion": "Reserve a table on the website — date, time and number of guests. Calls are fine, "
                          "but most bookings should come online.",
            "bookings": "Tables for 2, 4 and 6. Dinner seatings at 7, 8:15 and 9:30; weekend lunch at 12:30 "
                        "and 2. Groups above 8 should call us.",
            "providers": "No, any table.",
            "fulfilment": "Dine-in only. No delivery — the fish doesn't travel well.",
            "contact": f"1st floor, 640 12th Main, HAL 2nd Stage, Indiranagar, Bengaluru 560008. "
                       f"Reservations: {phone}.",
            "phone": phone,
            "story": "Fish comes from the Malpe and Mangalore markets three times a week, iced overnight. The "
                     "masalas are roasted and ground by hand every morning — the ghee roast paste alone takes "
                     "two hours. My aunt in Kundapur taught our chef Lavina and me.",
            "photos": LATER_PHOTOS,
            "payment": "Pay at the table — UPI, card or cash. No advance for tables.",
            "customisation": "We can make any dish less spicy. Private dining for up to 18 on the mezzanine — "
                             "call us for that.",
            "pricing": "Show all prices.",
            "hours": "Dinner Tuesday to Sunday, 7 pm to 11 pm; lunch Saturday and Sunday, 12:30 to 3:30. "
                     "Closed Mondays.",
            "team": "Chef Lavina from Mangalore in the kitchen and me on the floor — five of us in all.",
            "logo": "We have a logo, a small fish in a circle — I'll add it later from the editor.",
            "look": "Dark and warm, like an old Mangalore-tiled house at night: deep red oxide, teak and brass "
                    "lamps. Premium but not stiff.",
            "stock": "Some fish run out on busy nights; we tell guests at the table.",
        },
        fallback="Keep it true to what I said — you decide the rest.",
        confirm_text="Yes, perfect. Build the website.",
    )
    normal = OwnerScript(
        opening=("Konkan Table, a Mangalorean and Goan seafood restaurant in Indiranagar, Bengaluru. Dinner "
                 "mainly, people should book a table."),
        answers={
            "offer": "Ghee roast, kori rotti, fish fry, prawn curries, neer dosa.",
            "catalogue": "Chicken ghee roast 420, kane fry 520, pomfret gassi 560, prawn balchao 520, neer dosa "
                         "120. Prices for the rest later.",
            "traits": "Ghee roast and kane fry. Mushroom sukka is veg.",
            "conversion": "Book a table online.",
            "bookings": "Tables for 2, 4, 6. Dinner 7 to 11, weekend lunch also.",
            "fulfilment": "No delivery, dine-in only.",
            "contact": f"12th Main, Indiranagar, Bengaluru. {phone}",
            "phone": phone,
            "hours": "Tue-Sun dinner 7-11, Sat Sun lunch. Monday closed.",
            "payment": "Pay at the table.",
            "story": "Fresh fish from Mangalore three times a week.",
        },
        fallback="Not sure, you decide.",
        confirm_text="Yes, go ahead.",
    )
    bad = OwnerScript(
        opening=("konkan table restarant indranagar blr, mangalore goa type sea food, ghee rost kori roti neer "
                 "dosa all, ppl shud book table online mostly dinner time"),
        answers={
            "offer": "ghee rost, kori roti, kane fry, pomfret gassi, prawns balchao, neer dosa, payasam also",
            "catalogue": "ghee rost 420 kane 520 pomfret 560 balchao 520 neer dosa 120 rest not fixd yet",
            "conversion": "table bookng online, call also ok",
            "bookings": "2 4 6 seater tables, dinner 7 to 11, sat sun lunch bhi",
            "contact": f"12th main indranagar, {phone}",
            "phone": phone,
            "hours": "tue to sun nite, mon holiday",
            "fulfilment": "no delivry, only dine in",
            "story": "fish frm mangalore 3 times week, masala ground daily by hand",
            "look": "dark warm colur, premium but not too much",
        },
        fallback="pls u decide",
        confirm_text="haan ok build",
    )
    minimal = OwnerScript(
        opening="Konkan Table — seafood restaurant in Indiranagar, Bengaluru. Table bookings.",
        answers={"identity": "Mangalorean seafood restaurant.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Book by calling {phone}."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="restaurant-reservations", business_name="Konkan Table", category_hint="food_service/restaurant",
        business_type="restaurant", modules=TABLE_BOOKING, reference_ids=REFS["restaurant"],
        place="Indiranagar, Bengaluru", phone=phone, kind="restaurant",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal,
                           no_photos=NO_PHOTOS, own_photos=LATER_PHOTOS),
    )


def _meat_shop() -> Scenario:
    phone = "98402 61734"
    all_photos = _photos("lab-ishant", "pixabay-3359248.jpg", "pixabay-6935871.jpg") + _photos(
        "lab-cleaver", "pixabay-279849.jpg") + _photos(
        "lab-ishant", "pixabay-8210152.jpg", "pixabay-1261432.jpg", "pixabay-93513.jpg")
    some_photos = (all_photos[0], all_photos[1], all_photos[3], all_photos[5])
    rich = OwnerScript(
        opening=(
            "Velan Fresh Meats is our chicken, mutton and seafood shop on GST Road, Chromepet, Chennai — my "
            "father Velan started it in 1998 and I run it now with my brother Murugan. Chicken comes from one "
            "supplier farm in Padappai every morning, goats from the Kanchipuram markets, and fish from "
            "Kasimedu harbour at 5 am. We cut and clean only after you order. People choose the meat, the cut "
            "and the kg, and order on WhatsApp or the website; we deliver around Chromepet, Pallavaram and "
            "Tambaram."
        ),
        answers={
            "identity": "A fresh meat and fish shop for families around Chromepet and Pallavaram.",
            "offer": "Chicken, goat mutton, seer fish, pomfret, kilanga, squid and prawns.",
            "structure": "Chicken: curry cut, skinless, boneless, whole, wings. Mutton: curry cut, chops, keema, "
                         "liver. Fish: whole or slices, cleaned. Everything by the kg, half kg minimum.",
            "units": "By weight — half a kg upwards.",
            "catalogue": _catalogue("meat-shop"),
            "traits": "Chicken curry cut, mutton curry cut and seer fish slices sell the most.",
            "conversion": "Order on the website or WhatsApp — choose the meat, the cut and the kg. We confirm "
                          "the weight before cutting.",
            "fulfilment": "We deliver ourselves within 5 km — Chromepet, Pallavaram, Nemilichery, "
                          "Hasthinapuram and Tambaram West. Pickup from the shop too.",
            "area": "Chromepet, Pallavaram, Nemilichery, Hasthinapuram and Tambaram West.",
            "contact": f"No. 214 GST Road, Chromepet, Chennai 600044, opposite the bus stand. WhatsApp {phone}.",
            "phone": phone,
            "story": "Three things since my father's time: fresh stock every morning, nothing cut before you "
                     "order, and the weight shown on the scale in front of you. The counter is washed down "
                     "after every order.",
            "photos": "Attaching six photos from our shop: mutton chops, a whole chicken, chicken breast, "
                      "today's small fish, squid, and fish being cleaned at the counter.",
            "payment": "UPI or cash when we deliver, or at the shop.",
            "customisation": "Cut size as you like — small pieces for biryani, big for curry, skin on or off.",
            "pricing": "Show the rate per kg. Fish rates move with the market; I'll update them.",
            "hours": "6 am to 1 pm and 4 pm to 8 pm, Tuesday to Sunday. Monday closed.",
            "team": "Me, my brother Murugan and three cutters.",
            "logo": "No logo, just write the name well.",
            "look": "Clean and fresh — white with deep red, like a hygienic modern shop, not a dark butcher look.",
            "stock": "Yes — fish sells out by noon some days; show sold out.",
        },
        fallback="You decide, but only what I said is true.",
        media=all_photos,
        confirm_text="Correct. Please build it.",
    )
    normal = OwnerScript(
        opening=("Velan Fresh Meats, Chromepet, Chennai. We sell chicken mutton fish, delivery near Chromepet "
                 "and Pallavaram. People order on WhatsApp."),
        answers={
            "structure": "Curry cut, boneless, chops. By kg.",
            "units": "By kg.",
            "catalogue": "Chicken curry cut 240/kg, boneless 380, mutton 850, seer fish 950, prawns 560. "
                         "Squid also.",
            "conversion": "WhatsApp or website order.",
            "fulfilment": "Delivery Chromepet, Pallavaram, Tambaram. Pickup also.",
            "area": "Chromepet, Pallavaram, Tambaram.",
            "contact": f"GST Road, Chromepet. {phone}",
            "phone": phone,
            "hours": "6 am to 1 pm, 4 to 8 pm, Monday leave.",
            "story": "We cut only after the order. Running since 1998.",
            "payment": "UPI or cash.",
        },
        fallback="Not sure.",
        confirm_text="Ok, build it.",
    )
    bad = OwnerScript(
        opening=("velan fresh meats chromepet, chiken mutton fish ellam irukku, we cut after ordr only. delivry "
                 "near by areas pannuvom, whatsap la order pannalam"),
        answers={
            "structure": "curry cut boneless chops keema ellam, kg la thaan",
            "catalogue": "chiken 240 boneless 380 mutton 850 vanjaram 950 eral 560 (prawn) squid 420 kilanga 380",
            "fulfilment": "chromepet pallavaram tambaram delivry, shop la vandhu vaangalam",
            "contact": f"gst road chromepet bus stand opposite, {phone}",
            "phone": phone,
            "hours": "morning 6 to 1 evening 4 to 8, monday leev",
            "story": "1998 la appa start pannaru, fresh daily",
            "payment": "gpay cash both ok",
            "conversion": "whatsap la ordr podunga, website la um",
        },
        fallback="theriyala, neenga paathukonga",
        confirm_text="ok sari, build pannunga",
    )
    minimal = OwnerScript(
        opening="Velan Fresh Meats — chicken, mutton and fish shop in Chromepet, Chennai.",
        answers={"identity": "Chicken, mutton and fish shop.", "contact": f"WhatsApp {phone}.", "phone": phone,
                 "conversion": f"WhatsApp {phone}."},
        fallback="Skip for now.",
        confirm_text="ok",
    )
    return Scenario(
        key="meat-shop", business_name="Velan Fresh Meats", category_hint="fresh_grocery/meat_shop",
        business_type="retail", modules=COUNTER_ORDERS, reference_ids=REFS["retail"],
        place="Chromepet, Chennai", phone=phone, kind="retail",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal, no_photos=NO_PHOTOS,
                           own_photos="I'm attaching my own photos from the shop — mutton, chicken and "
                                      "fish, and our counter.",
                           media=some_photos),
    )


def _bakery() -> Scenario:
    phone = "98220 47153"
    all_photos = _photos("lab-crumb", "pixabay-2595658.jpg", "pixabay-1051884.jpg", "pixabay-4887101.jpg",
                         "pixabay-1378049.jpg")
    rich = OwnerScript(
        opening=(
            "Hearth & Honey is a small neighbourhood bakery on ITI Road, Aundh, Pune. We bake every morning "
            "from 5 — country sourdough and whole-wheat loaves, garlic herb baguettes, cookies and nankhatai, "
            "and cakes to order. I'm Rhea; I trained in a bakery in Goa and opened this in 2021. No online "
            "orders — people call or WhatsApp us to keep bread aside or to order a cake, and pick up from the shop."
        ),
        answers={
            "identity": "A neighbourhood bakery for Aundh and Baner families — daily bread, cookies and cakes to order.",
            "offer": "Breads (sourdough, whole-wheat, multigrain, milk bread), baguettes and pav, cookies, and "
                     "cakes to order.",
            "structure": "Breads, Baguettes & pav, Cookies, Cakes to order. Bread by the loaf, cookies by the "
                         "250 g box, cakes by the kg.",
            "catalogue": _catalogue("bakery"),
            "traits": "Sourdough, the garlic herb baguette and the sprinkle cookies sell most. Everything is "
                      "vegetarian; breads and cookies are eggless, cakes come with egg or eggless.",
            "conversion": "Call or WhatsApp us to keep bread aside or to order a cake. No online orders.",
            "fulfilment": "Pickup from the shop only. No delivery.",
            "contact": f"Shop 3, Sai Chambers, ITI Road, Aundh, Pune 411007. Call or WhatsApp {phone}.",
            "phone": phone,
            "story": "Small batches twice a day, no premixes, no preservatives. Our sourdough starter came with "
                     "me from Goa and is eight years old. Yesterday's bread goes at half price in the morning.",
            "photos": "Attaching four photos: our sourdough on the counter, the sprinkle cookies, a wheat "
                      "sandwich loaf and the garlic herb baguettes.",
            "payment": "UPI or cash at the shop. For cakes, 50% advance on UPI.",
            "customisation": "Cakes: flavour, size, a message, eggless, a photo print. Two days' notice.",
            "pricing": "Show prices.",
            "hours": "7 am to 9 pm every day; fresh bread comes out at 7 am and 4 pm.",
            "team": "Me and two bakers; my mother runs the counter.",
            "logo": "No logo yet.",
            "look": "Warm and calm — cream, flour-white and toasted brown, like the inside of the shop. Simple, "
                    "not cute pink.",
            "stock": "Yes, breads sell out — it would be nice to show what's left.",
        },
        fallback="Up to you, keep it honest.",
        media=all_photos,
        confirm_text="Looks right — build it please.",
    )
    normal = OwnerScript(
        opening=("Hearth & Honey Bakery in Aundh, Pune. Breads, baguettes, cookies and cakes on order. People "
                 "call or WhatsApp, and pick up."),
        answers={
            "catalogue": "Sourdough 220, sandwich loaf 90, herb baguette 120, cookies 220 for 250 g, cakes from "
                         "750 per kg.",
            "traits": "Sourdough and cookies. All veg, cakes eggless on request.",
            "conversion": "Call or WhatsApp.",
            "fulfilment": "Pickup only.",
            "contact": f"ITI Road, Aundh. {phone}",
            "phone": phone,
            "hours": "7 am to 9 pm.",
            "customisation": "Cakes with name, eggless, 2 days before.",
            "story": "Baked fresh twice a day, no premix.",
            "payment": "UPI or cash.",
        },
        fallback="Not sure, you decide.",
        confirm_text="Yes, build it.",
    )
    bad = OwnerScript(
        opening=("hearth n honey bakery aundh pune, bread cookies cake sab milta hai, sourdugh bhi, ppl call or "
                 "whatsap karte hai and come pick up"),
        answers={
            "catalogue": "sourdugh 220 bred 90 baguete 120 cookies 220 (250g) cake 750 kg se start",
            "conversion": "call / whatsap only, online nahi",
            "fulfilment": "pickup only no delivry",
            "contact": f"iti road aundh, {phone}",
            "phone": phone,
            "customisation": "cake pe naam photo eggless sab hoga 2 din pehle bolo",
            "hours": "7 se 9 roz",
            "story": "fresh daily 2 times bake, no premix",
        },
        fallback="pata nahi, aap dekh lo",
        confirm_text="theek hai banao",
    )
    minimal = OwnerScript(
        opening="Hearth & Honey — bakery in Aundh, Pune.",
        answers={"identity": "A bakery.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Call {phone}."},
        fallback="Skip that.",
        confirm_text="ok",
    )
    return Scenario(
        key="bakery", business_name="Hearth & Honey Bakery", category_hint="food_service/bakery",
        business_type="restaurant", modules=CATALOGUE_ONLY, reference_ids=REFS["retail"],
        place="Aundh, Pune", phone=phone, kind="retail",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal, no_photos=NO_PHOTOS,
                           own_photos="I'm attaching my own photos of our breads and cookies.",
                           media=all_photos[:2] + all_photos[3:]),
    )


def _gym() -> Scenario:
    phone = "99860 52418"
    rich = OwnerScript(
        opening=(
            "Forge Strength Club is a strength and conditioning gym in HSR Layout Sector 2, Bengaluru — "
            "6,000 sq ft, eight squat racks, a turf lane and a small recovery room. We coach people properly: "
            "small-group strength classes of at most eight, personal training, and open gym for members. I'm "
            "Karthik, a former state-level weightlifter, and all four of our coaches are certified. People "
            "should book a free trial class, then join a plan and pay online."
        ),
        answers={
            "identity": "A coached strength gym for working adults in HSR Layout, most of them beginners.",
            "offer": "Small-group strength classes, personal training, open gym membership, and a six-week "
                     "beginner barbell course.",
            "structure": "Memberships, Class packs, Personal training and Courses.",
            "catalogue": _catalogue("gym"),
            "plans": "Open gym monthly 3500, quarterly 9500, annual 32000. Class pack of 12 for 4800; PT 12 "
                     "sessions 14400.",
            "traits": "The annual membership and the beginner barbell course.",
            "conversion": "Book a free trial class online, then join a plan and pay online.",
            "bookings": "Trial and group classes, 60 minutes each. PT slots with a chosen coach.",
            "providers": "PT clients choose their coach; classes are with whoever is on the timetable.",
            "contact": f"2nd floor, 27th Main, Sector 2, HSR Layout, Bengaluru 560102. Call or WhatsApp {phone}.",
            "phone": phone,
            "story": "We teach lifting the right way — every new member gets an assessment and a written "
                     "programme. No mirror-selfie culture, no loud bass, no supplements pushed at the desk. "
                     "Most of our members had never touched a barbell before they came.",
            "photos": LATER_PHOTOS,
            "payment": "Online by UPI or card when joining; cash at the desk also.",
            "pricing": "Show all prices.",
            "hours": "Mon-Sat 6 am to 10 pm, Sunday 7 am to 12 pm. Classes at 6:30 am, 7:30 am, 6:30 pm "
                     "and 7:30 pm.",
            "team": "Four coaches: me, Divya (women's strength), Arjun (conditioning) and Sameer (PT, "
                    "rehab-friendly).",
            "logo": "We have an anvil logo, I'll upload it later.",
            "look": "Dark, bold and serious — black, iron grey and one hot orange. Big type. It should feel "
                    "like a real lifting gym, not a spa.",
        },
        fallback="Your call — keep it real.",
        confirm_text="Yes. Build it.",
    )
    normal = OwnerScript(
        opening=("Forge Strength Club, a strength gym in HSR Layout, Bengaluru. Classes, personal training and "
                 "memberships."),
        answers={
            "plans": "Monthly 3500, quarterly 9500, yearly 32000. PT packs too.",
            "catalogue": "Monthly 3500, quarterly 9500, annual 32000, 12 classes 4800, PT 12 sessions 14400.",
            "conversion": "Free trial class booking, then join online.",
            "bookings": "Classes 1 hour, morning and evening.",
            "providers": "For PT people pick a coach.",
            "contact": f"27th Main, HSR Layout Sector 2. {phone}",
            "phone": phone,
            "hours": "6 am to 10 pm, Sunday half day.",
            "payment": "UPI or card online.",
            "story": "Proper coaching, small groups of max 8.",
        },
        fallback="Not sure, keep it simple.",
        confirm_text="Yes, go.",
    )
    bad = OwnerScript(
        opening=("forge strenght club hsr layout blr, we r a strenth gym, clases + personal traning + membrship, "
                 "ppl shud book trial first then join"),
        answers={
            "plans": "monthly 3500 quartly 9500 yearly 32k, pt 12 sesions 14400",
            "catalogue": "monthly 3500, quartly 9500, yearly 32000, 12 clases 4800, pt 14400",
            "conversion": "trial book online then pay n join",
            "bookings": "1 hr clases morning eve both",
            "contact": f"hsr sec 2 27th main, {phone}",
            "phone": phone,
            "hours": "6am-10pm sunday till 12",
            "story": "real coching, small batch max 8 ppl, no bro culture",
            "payment": "upi card",
        },
        fallback="dunno, u decide",
        confirm_text="ok go",
    )
    minimal = OwnerScript(
        opening="Forge Strength Club — strength gym in HSR Layout, Bengaluru.",
        answers={"identity": "A strength gym.", "contact": f"WhatsApp {phone}.", "phone": phone,
                 "conversion": f"WhatsApp {phone}."},
        fallback="Skip for now.",
        confirm_text="ok",
    )
    return Scenario(
        key="gym", business_name="Forge Strength Club", category_hint="fitness/gym", business_type="gym",
        modules=GYM, reference_ids=REFS["gym"], place="HSR Layout, Bengaluru", phone=phone, kind="gym",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal,
                           no_photos=NO_PHOTOS, own_photos=LATER_PHOTOS),
    )


def _salon() -> Scenario:
    phone = "98940 73562"
    rich = OwnerScript(
        opening=(
            "Amber Room is a unisex salon and bridal studio on DB Road, RS Puram, Coimbatore — haircuts and "
            "colour, keratin, facials, nails, and bridal and party makeup. I'm Nithya; I worked twelve years in "
            "salons in Chennai and Dubai before coming home to open this in 2020. Five stylists, appointments "
            "only, so nobody waits. I want it to feel calm and premium — people should book online, and brides "
            "pay a small advance online to block the date."
        ),
        answers={
            "identity": "A calm, appointment-only salon and bridal studio for women and men in Coimbatore.",
            "offer": "Haircuts, colour and balayage, keratin, facials, gel nails, and bridal and party makeup.",
            "structure": "Hair, Skin, Bridal & makeup, and Nails.",
            "catalogue": _catalogue("salon"),
            "traits": "Women's haircut, global colour, keratin and bridal makeup are booked most.",
            "conversion": "Book an appointment online; bridal clients pay ₹2,000 online to block the date.",
            "bookings": "Appointments: a haircut is 45 minutes, colour about 2 hours, a bridal trial 2 hours. "
                        "Many clients ask for a particular stylist.",
            "providers": "Yes — me for bridal, Farhan for colour, Priya for skin, Joseph for men's cuts, Anu "
                         "for nails.",
            "contact": f"First floor, 118 DB Road, RS Puram, Coimbatore 641002. Call or WhatsApp {phone}.",
            "phone": phone,
            "story": "Appointment-only so nobody waits, one client per chair, ammonia-free colours, and every "
                     "tool sterilised between clients. Brides get a trial and a written plan for the day.",
            "photos": LATER_PHOTOS,
            "payment": "UPI, card or cash at the salon. The bridal advance online.",
            "customisation": "Bridal packages can be customised — pre-bridal sessions, family makeup.",
            "pricing": "Show prices; colour and keratin as 'onwards'.",
            "hours": "10 am to 8 pm, Tuesday to Sunday. Monday closed.",
            "team": "Five of us: me (bridal), Farhan (colour), Priya (skin), Joseph (men's cuts), Anu (nails).",
            "logo": "Yes, a gold 'A' monogram — I'll add it later.",
            "look": "Calm and premium — soft beige, ivory and a touch of amber gold, elegant serif type. Not "
                    "loud pink.",
        },
        fallback="Please keep it elegant, you can decide.",
        confirm_text="Yes, lovely — build it.",
    )
    normal = OwnerScript(
        opening=("Amber Room Salon in RS Puram, Coimbatore. Haircut, colour, facials and bridal makeup. "
                 "Customers book appointments."),
        answers={
            "catalogue": "Women's haircut 900, men's 450, global colour from 3500, keratin 5500, facial 2200, "
                         "bridal makeup 18000.",
            "bookings": "Appointments, some ask for a particular stylist.",
            "providers": "Yes, sometimes.",
            "conversion": "Book online.",
            "payment": "UPI, card, cash. Bridal advance online.",
            "contact": f"DB Road, RS Puram, Coimbatore. {phone}",
            "phone": phone,
            "hours": "10 to 8, Monday holiday.",
            "story": "Appointment only, no waiting.",
            "look": "Calm and classy.",
        },
        fallback="Not sure, you decide.",
        confirm_text="Yes, build it.",
    )
    bad = OwnerScript(
        opening=("amber room salon rs puram cbe, we do al types of haircut nd colur, ladies gents both, facial, "
                 "bridel makeup also, apointment booking venum"),
        answers={
            "catalogue": "ladies cut 900 gents 450 colur 3500 onwards keratine 5500 facial 2200 bridel 18000",
            "bookings": "apointment only, some ppl ask particular stylist",
            "conversion": "online booking + advance for bridel",
            "contact": f"db road rs puram, {phone}",
            "phone": phone,
            "hours": "10-8 monday leave",
            "story": "no waiting, one by one only",
            "payment": "gpay card cash",
            "look": "classy, not too pink",
        },
        fallback="neenga decide pannunga",
        confirm_text="ok super, build it",
    )
    minimal = OwnerScript(
        opening="Amber Room — salon in RS Puram, Coimbatore.",
        answers={"identity": "A salon.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Call {phone} for appointments."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="salon", business_name="Amber Room Salon", category_hint="beauty/salon", business_type="salon",
        modules=SALON, reference_ids=REFS["salon"], place="RS Puram, Coimbatore", phone=phone, kind="salon",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal,
                           no_photos=NO_PHOTOS, own_photos=LATER_PHOTOS),
    )


def _clinic() -> Scenario:
    phone = "90030 18452"
    rich = OwnerScript(
        opening=(
            "Nalam Family Clinic is a family practice on OMR, Perungudi, Chennai — general medicine, children's "
            "care, diabetes and BP review, vaccinations, and a small in-house lab for blood tests. Two doctors: "
            "Dr. Meera Raghavan (MD, General Medicine) and Dr. Arun Prakash (MD, Paediatrics). Patients can "
            "book a time online, and walk-ins take a token and wait in the queue — we want the queue on the "
            "website too."
        ),
        answers={
            "identity": "A neighbourhood family clinic for adults and children around Perungudi and Thoraipakkam.",
            "offer": "General consultations, children's consultations, diabetes, BP and thyroid reviews, "
                     "vaccinations and blood tests.",
            "structure": "Consultations, Chronic care, Lab tests and Vaccinations.",
            "catalogue": _catalogue("clinic"),
            "traits": "General consultations, the diabetes review and children's vaccinations.",
            "conversion": "Book an appointment online or take a walk-in token. Call for anything urgent.",
            "bookings": "OP consultations of about 15 minutes with a chosen doctor. Walk-ins get a token.",
            "providers": "Patients choose — Dr. Meera for adults, Dr. Arun for children.",
            "contact": f"No. 5 Rajiv Gandhi Salai (OMR), Perungudi, Chennai 600096, next to the Perungudi "
                       f"signal. Phone or WhatsApp {phone}.",
            "phone": phone,
            "story": "A family doctor for the whole family: we know our patients by name, explain everything "
                     "in Tamil or English, and never order tests that aren't needed. Reports come on WhatsApp "
                     "the same evening.",
            "photos": LATER_PHOTOS,
            "payment": "Pay at the clinic — UPI, card or cash.",
            "pricing": "Show consultation fees and test prices.",
            "hours": "8 am to 1 pm and 5 pm to 9 pm, Monday to Saturday. Sunday 9 am to 12 pm, Dr. Meera only.",
            "team": "Two doctors, two nurses, a lab technician and a front-desk person.",
            "logo": "A green leaf logo — I'll upload it later.",
            "look": "Clean, calm and trustworthy — white and soft blue, rounded and friendly. Not hospital-cold.",
        },
        fallback="Please keep it simple and accurate — no medical claims.",
        confirm_text="Yes, correct. Please build.",
    )
    normal = OwnerScript(
        opening=("Nalam Family Clinic, Perungudi OMR, Chennai. Two doctors — general physician and child "
                 "specialist. Appointments and walk-in tokens."),
        answers={
            "offer": "General consultation, child care, diabetes, BP, vaccinations, blood tests.",
            "catalogue": "Consultation 500, child consultation 600, CBC 350, HbA1c 450.",
            "bookings": "15 min OP, choose the doctor.",
            "providers": "Dr. Meera (general), Dr. Arun (children).",
            "conversion": "Book online or walk in for a token.",
            "contact": f"OMR, Perungudi. {phone}",
            "phone": phone,
            "hours": "8-1 and 5-9, Sunday morning.",
            "payment": "Pay at the clinic.",
            "team": "2 doctors, 2 nurses.",
        },
        fallback="Not sure, keep it simple.",
        confirm_text="Yes, build.",
    )
    bad = OwnerScript(
        opening=("nalam family clinic perungudi omr, 2 doctrs, general + child specialist, apointment and walk "
                 "in token both, sugar bp check, blood test also we have"),
        answers={
            "offer": "general consultaion, children, sugar bp thyroid, vaccines, blood tests lab inside",
            "catalogue": "consultaion 500, child 600, blood test cbc 350 hba1c 450 others varies",
            "bookings": "15 min per patient, they chose the doctr",
            "providers": "meera madam general, arun sir childrens",
            "conversion": "online apointment, walk in token, call also",
            "contact": f"omr perungudi signal near, {phone}",
            "phone": phone,
            "hours": "morn 8-1 eve 5-9 sunday morning only",
            "payment": "gpay card cash at clinic",
        },
        fallback="not sure, keep simple",
        confirm_text="ok fine proceed",
    )
    minimal = OwnerScript(
        opening="Nalam Family Clinic — family doctor clinic in Perungudi, Chennai.",
        answers={"identity": "A family clinic.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Call {phone}."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="clinic", business_name="Nalam Family Clinic", category_hint="healthcare/clinic",
        business_type="clinic", modules=CLINIC, reference_ids=REFS["clinic"], place="Perungudi, Chennai",
        phone=phone, kind="clinic",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal,
                           no_photos=NO_PHOTOS, own_photos=LATER_PHOTOS),
    )


def _consultant() -> Scenario:
    phone = "94470 88213"
    rich = OwnerScript(
        opening=(
            "I'm Anjali Menon and I run Anjali Menon Consulting from Panampilly Nagar, Kochi. I help family-run "
            "businesses and small D2C brands in Kerala fix pricing, margins and growth: growth audits, pricing "
            "projects, monthly advisory retainers and team workshops. Before this I spent eleven years in "
            "strategy and pricing roles in Bengaluru and Dubai. Clients enquire on the website, we have a free "
            "30-minute discovery call, then I send a proposal and a GST invoice."
        ),
        answers={
            "identity": "A pricing and growth consultant for Kerala's family businesses and young D2C brands.",
            "offer": "Growth and margin audits, pricing health checks, monthly advisory, workshops, and "
                     "projects like a D2C launch plan or a family succession roadmap.",
            "structure": "Audits, Advisory, Workshops and Projects.",
            "catalogue": _catalogue("consultant"),
            "traits": "The growth and margin audit, and the monthly advisory that usually follows it.",
            "conversion": "Send an enquiry or book a free 30-minute discovery call. After the call I send a "
                          "proposal.",
            "b2b": "Mostly family businesses — textiles, spices, jewellery, restaurants — and D2C founders. "
                   "They want a proposal first.",
            "process": "Enquiry, discovery call, written proposal, 50% advance invoice, then work starts.",
            "contact": f"2nd floor, Kurishupally Road, Panampilly Nagar, Kochi 682036 — meetings by "
                       f"appointment. WhatsApp {phone}.",
            "phone": phone,
            "story": "I've sat on both sides — big-company strategy, and my family's own textile shop in "
                     "Thrissur. I don't hand over 80-slide decks: every project ends with three numbers to "
                     "watch and a plan your team can actually run. Forty-plus Kerala businesses so far.",
            "photos": "I have a professional portrait; I'll upload it later.",
            "payment": "Bank transfer or UPI against a GST invoice; 50% in advance.",
            "pricing": "Show 'from' prices.",
            "hours": "Monday to Friday, 10 am to 6 pm; calls by appointment.",
            "team": "Mostly me; two analysts join on bigger projects.",
            "logo": "Just my name as a wordmark.",
            "look": "Confident and modern — warm white, deep ink blue and one copper accent. Personal, with my "
                    "photo, not a corporate template.",
        },
        fallback="Keep it crisp and honest.",
        confirm_text="Yes, that's me. Build it.",
    )
    normal = OwnerScript(
        opening=("Anjali Menon Consulting, Kochi. I help family businesses and small brands with pricing and "
                 "growth. Clients enquire and book a call."),
        answers={
            "offer": "Growth audit, pricing projects, monthly advisory, workshops.",
            "catalogue": "Growth audit 45000, pricing check 25000, advisory 60000 a month, workshop 35000.",
            "conversion": "Enquiry or book a free call.",
            "process": "Call, proposal, invoice.",
            "contact": f"Panampilly Nagar, Kochi. {phone}",
            "phone": phone,
            "payment": "Bank transfer or UPI, GST invoice.",
            "story": "11 years in strategy; practical plans, not decks.",
            "team": "Mostly me.",
        },
        fallback="Not sure, keep it simple.",
        confirm_text="Yes, build it.",
    )
    bad = OwnerScript(
        opening=("anjali menon consultng kochi, i help famly businesses and small brands for pricing, margin, "
                 "growth etc. clients enquire then free call then proposal, invoce with gst"),
        answers={
            "offer": "growth audit, pricing projct, monthly advisry, workshops for teams",
            "catalogue": "audit 45k, pricing check 25k, advisry 60k per month, workshop 35k, 1:1 6k",
            "conversion": "enquiry form or book a call, thats it",
            "process": "call -> proposal -> 50% advance invoce",
            "contact": f"panampilly nagar kochi, {phone} whatsapp",
            "phone": phone,
            "story": "11 yrs strategy exp, practical plans, no big decks",
        },
        fallback="angane okke mathi, u decide",
        confirm_text="ok sheri, build",
    )
    minimal = OwnerScript(
        opening="Anjali Menon Consulting — business and pricing consultant in Kochi.",
        answers={"identity": "A business consultant.", "contact": f"WhatsApp {phone}.", "phone": phone,
                 "conversion": f"WhatsApp {phone}."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="consultant", business_name="Anjali Menon Consulting", category_hint="professional/business_consultant",
        business_type="professional_service", modules=ADVISORY, reference_ids=REFS["consultant"],
        place="Panampilly Nagar, Kochi", phone=phone, kind="consultant",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal, no_photos=NO_PHOTOS,
                           own_photos="I have a professional portrait; I'll upload it later."),
    )


def _retail() -> Scenario:
    phone = "98804 61927"
    rich = OwnerScript(
        opening=(
            "Kansa & Clay is a kitchenware store on 11th Main, Jayanagar 4th Block, Bengaluru — traditional "
            "cookware that lasts: kansa (bronze) dinner sets, brass and copper vessels, cast-iron tawas and "
            "kadais, soapstone kal chatti, and clay pots from potters in Mandya and Manamadurai. I'm Shruti; my "
            "grandfather had a vessel shop in Chickpet. We keep about 300 pieces in stock and want people to "
            "order and pay online, with delivery across Bengaluru."
        ),
        answers={
            "identity": "A store for traditional, long-lasting Indian cookware — for home cooks and for gifting.",
            "offer": "Kansa dinner sets, cast-iron tawas and kadais, brass and copper vessels, clay pots and "
                     "soapstone.",
            "structure": "Kansa, Cast iron, Brass & copper, Clay & stone.",
            "units": "By the piece; sets are fixed.",
            "catalogue": _catalogue("retail"),
            "traits": "The kansa thali set, the cast-iron dosa tawa and the copper bottle sell most.",
            "conversion": "Order and pay online, or call or WhatsApp to ask about a piece.",
            "fulfilment": "Delivery across Bengaluru in 1-2 days by our own runner; pickup from the store.",
            "area": "All of Bengaluru within city limits.",
            "contact": f"No. 32, 11th Main, Jayanagar 4th Block, Bengaluru 560011. Call or WhatsApp {phone}.",
            "phone": phone,
            "b2b": "A few restaurants buy clay pots and brass serving ware in bulk — they call us.",
            "story": "Every piece is chosen by hand from the families who make it — kansa from Odisha, clay "
                     "from Mandya and Manamadurai, cast iron from a foundry in Coimbatore. We season the iron "
                     "and cure the clay before it leaves the shop, and show you how to care for it.",
            "photos": LATER_PHOTOS,
            "payment": "Online by UPI or card; cash at the store.",
            "customisation": "Name engraving on kansa and copper for gifts, ₹150 a piece.",
            "pricing": "Show prices.",
            "hours": "10:30 am to 8:30 pm, every day except Tuesday.",
            "team": "Me, my mother and two staff.",
            "logo": "Yes — I'll add it later.",
            "look": "Material-led and warm — dark wood, bronze and terracotta, close-up photos of metal and "
                    "clay. Premium and quiet, not a discount-store look.",
            "stock": "Yes — stock changes every week, and handmade pieces are often one or two only. Show "
                     "sold out.",
        },
        fallback="Keep it true to the craft — you decide.",
        confirm_text="Yes, go ahead and build.",
    )
    normal = OwnerScript(
        opening=("Kansa & Clay, kitchenware store in Jayanagar, Bengaluru. Kansa, brass, copper, cast iron and "
                 "clay pots. Want online orders and delivery in Bengaluru."),
        answers={
            "catalogue": "Kansa thali set 6800, dosa tawa 1650, kadai 1850, copper bottle 1250, clay pot 650.",
            "conversion": "Order online and pay.",
            "fulfilment": "Deliver in Bengaluru, pickup from the store.",
            "stock": "Stock changes, show sold out.",
            "payment": "UPI, card.",
            "contact": f"11th Main, Jayanagar 4th Block. {phone}",
            "phone": phone,
            "hours": "10:30 to 8:30, Tuesday closed.",
            "story": "Handmade cookware from craftspeople.",
        },
        fallback="Not sure, you decide.",
        confirm_text="Yes, build it.",
    )
    bad = OwnerScript(
        opening=("kansa n clay jayanagar blr, kitchen vessels shop - kansa brass copper cast iron tawa kadai clay "
                 "pots all, want online ordr + delivry in bangalore"),
        answers={
            "catalogue": "kansa thali set 6800, tawa 1650 kadai 1850, coper bottle 1250, clay pot 650, kal chatti "
                         "1450 , more items in shop",
            "conversion": "online ordr pay online, whatsap also",
            "fulfilment": "blr delivry 1-2 days, store pickup also",
            "stock": "stock keeps changng, handmade so limited",
            "contact": f"11th main jayanagar 4th blk, {phone}",
            "phone": phone,
            "hours": "10.30 to 8.30 tuesday holiday",
            "story": "handmade only, from artisans, we season iron before giving",
            "payment": "upi card cash",
        },
        fallback="gottilla, nimage bitta (you decide)",
        confirm_text="ok madi, build",
    )
    minimal = OwnerScript(
        opening="Kansa & Clay — kitchenware shop in Jayanagar, Bengaluru.",
        answers={"identity": "A kitchenware shop.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Call {phone}."},
        fallback="Skip for now.",
        confirm_text="ok",
    )
    return Scenario(
        key="retail", business_name="Kansa & Clay", category_hint="retail/kitchenware", business_type="retail",
        modules=STORE, reference_ids=REFS["retail"], place="Jayanagar, Bengaluru", phone=phone, kind="retail",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal,
                           no_photos=NO_PHOTOS, own_photos=LATER_PHOTOS),
    )


def _architecture() -> Scenario:
    phone = "98950 34126"
    rich = OwnerScript(
        opening=(
            "Laterite Studio is an architecture and interiors practice in Fort Kochi, led by me, Ar. Joseph "
            "Mathew, and my partner Ar. Nandita Rao. We design homes, small hotels and restorations across "
            "Kerala — laterite, lime plaster, reclaimed wood, deep verandahs, homes that stay cool without much "
            "AC. 38 projects since 2013, including turning a 1920s Mattancherry warehouse into a homestay. "
            "Clients send an enquiry, we visit the site, then send a fee proposal."
        ),
        answers={
            "identity": "An architecture and interiors studio for families building homes, and for homestay "
                        "and small-hotel owners in Kerala.",
            "offer": "New homes, farmhouses and villas, small hotels and homestays, full-home interiors, and "
                     "heritage restoration.",
            "structure": "Architecture, Interiors, Restoration and Consultations.",
            "catalogue": _catalogue("architecture"),
            "traits": "New home design and restoration of old tharavads.",
            "conversion": "Send an enquiry with the site location and rough size; we call back, visit the "
                          "site, then quote.",
            "b2b": "A few homestay and hotel owners; mostly families building their home.",
            "process": "Enquiry, site visit, fee proposal, then a concept design in 3-4 weeks.",
            "contact": f"Studio at 1/451 Burgher Street, Fort Kochi 682001 — visits by appointment. Call {phone}.",
            "phone": phone,
            "story": "Kerala's climate already has the answers — laterite walls that breathe, deep eaves, "
                     "courtyards for air. We design with local materials and local craftsmen, so homes cost "
                     "less to run and age beautifully.",
            "photos": "I have professional photos of 12 finished projects; I'll upload them later.",
            "customisation": "Everything is designed for the site — we don't sell ready plans.",
            "pricing": "'From' prices — every project is quoted after the site visit.",
            "hours": "Monday to Saturday, 10 am to 6 pm, by appointment.",
            "team": "Two architects, three junior architects, a site engineer and our own carpenters.",
            "logo": "A simple wordmark — later.",
            "look": "Editorial and minimal — big project photographs, lots of white space, earthy laterite "
                    "red and charcoal, large serif headings. Like an architecture monograph.",
        },
        fallback="Use your judgement; keep it understated.",
        confirm_text="Yes, that's us. Build.",
    )
    normal = OwnerScript(
        opening=("Laterite Studio, architects and interior designers in Fort Kochi. Homes, small hotels, "
                 "restorations. Clients enquire and we quote after a site visit."),
        answers={
            "offer": "Home design, interiors, restoration.",
            "catalogue": "Home design from 220 per sq ft, interiors from 1800 per sq ft, site visit 5000 rupees.",
            "conversion": "Enquiry, then site visit and quote.",
            "process": "Enquiry, visit, proposal.",
            "contact": f"Burgher Street, Fort Kochi. {phone}",
            "phone": phone,
            "story": "Local materials, homes that stay cool.",
            "pricing": "From prices.",
        },
        fallback="Not sure, you decide.",
        confirm_text="Yes, build.",
    )
    bad = OwnerScript(
        opening=("laterite studio fort kochi, archtects + interior, we design homes, homestays, old house "
                 "restoraton, mostly kerala style laterite lime etc. clients enqury then site visit then qoute"),
        answers={
            "offer": "new homes, interors, restoraton of old houses, small hotel design",
            "catalogue": "home design 220/sqft onwards, interors 1800/sqft, site visit 5000 , restoration depnds",
            "conversion": "enqury form, we call back",
            "process": "enqury -> site visit -> qoute -> design",
            "contact": f"burgher st fort kochi, {phone}",
            "phone": phone,
            "story": "kerala climate based design, local materials, local craftsmen",
        },
        fallback="ningal decide cheyyu",
        confirm_text="ok, go",
    )
    minimal = OwnerScript(
        opening="Laterite Studio — architects in Fort Kochi.",
        answers={"identity": "Architects.", "contact": f"Call {phone}.", "phone": phone,
                 "conversion": f"Call {phone}."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="architecture", business_name="Laterite Studio", category_hint="design_build/architect",
        business_type="professional_service", modules=DESIGN_PRACTICE, reference_ids=REFS["architecture"],
        place="Fort Kochi, Kochi", phone=phone, kind="architecture",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal, no_photos=NO_PHOTOS,
                           own_photos="I have photos of our finished projects; I'll upload them later."),
    )


def _hotel() -> Scenario:
    phone = "94480 27316"
    rich = OwnerScript(
        opening=(
            "Mistwood Estate Retreat is a 14-room boutique stay inside our family's 60-acre coffee and pepper "
            "estate, 9 km from Madikeri in Coorg. Planter's bungalow rooms, valley-view cottages and two pool "
            "villas; Kodava home cooking, estate walks, birding and a bonfire most nights. My family has farmed "
            "here for four generations, and we opened the rooms in 2016. Guests should check dates and book "
            "online with payment, not call five times."
        ),
        answers={
            "identity": "A boutique estate stay for couples and families who want quiet, coffee and Kodava food.",
            "offer": "Bungalow rooms, valley-view cottages, family cottages, pool villas, packages, estate walks "
                     "and Kodava dinners.",
            "structure": "Rooms, Packages, Experiences and Dining.",
            "catalogue": _catalogue("hotel"),
            "traits": "Valley-view cottages and the coffee estate weekend package.",
            "conversion": "Check availability and book online with full payment; call us for groups.",
            "bookings": "Rooms by the night, check-in 1 pm, check-out 11 am. Two-night minimum on weekends and "
                        "long weekends.",
            "contact": f"Mistwood Estate, Kaggodlu Road, near Madikeri, Kodagu 571201. Call or WhatsApp {phone}.",
            "phone": phone,
            "story": "Four generations on this estate. The rooms look over coffee and silver oak, the food is "
                     "what our family eats, and the estate walks are with people who have worked these slopes "
                     "for thirty years. No TV in the rooms; wifi in the bungalow.",
            "photos": "We have professional photos of every room; I'll upload them later.",
            "payment": "Online by UPI or card, the full amount at booking. Free cancellation up to 7 days before.",
            "customisation": "Small weddings and offsites for up to 40 — call us.",
            "pricing": "Show rates; peak-season dates may cost more.",
            "hours": "Reception 7 am to 10 pm.",
            "team": "My family and 18 staff from the villages around us.",
            "logo": "Yes, later.",
            "look": "Dark, rich and calm — forest green, coffee brown and old brass, big photos of mist over "
                    "the valley. Luxurious but warm, like an old planter's home.",
        },
        fallback="Keep it understated and true, you decide.",
        confirm_text="Yes, all correct. Please build it.",
    )
    normal = OwnerScript(
        opening=("Mistwood Estate Retreat, 14-room estate stay near Madikeri, Coorg. Cottages and pool villas "
                 "in our coffee estate. Guests book online."),
        answers={
            "catalogue": "Bungalow room 7500, valley cottage 9500, family cottage 12500, pool villa 18500 per night.",
            "bookings": "By the night, 2-night minimum on weekends.",
            "conversion": "Book online with payment.",
            "payment": "UPI or card online.",
            "contact": f"Kaggodlu Road, near Madikeri. {phone}",
            "phone": phone,
            "story": "Family coffee estate, Kodava food, estate walks.",
            "hours": "Check-in 1 pm, check-out 11 am.",
        },
        fallback="Not sure, you decide.",
        confirm_text="Yes, build it.",
    )
    bad = OwnerScript(
        opening=("mistwood estate retreat coorg madikeri, 14 rooms in our cofee estate, cottages + pool vilas, "
                 "guests shud book online n pay"),
        answers={
            "catalogue": "bunglow room 7500 valley cotage 9500 family 12500 pool vila 18500 per nite, breakfast incl",
            "bookings": "per nite, weekend min 2 nites",
            "conversion": "online booking n payment, groups call",
            "payment": "upi card online full",
            "contact": f"kaggodlu road madikeri, {phone}",
            "phone": phone,
            "story": "4 generation family estate, kodava food, estate walk birding bonfire",
            "look": "green, calm, luxury but homely",
        },
        fallback="u decide pls",
        confirm_text="ok perfect",
    )
    minimal = OwnerScript(
        opening="Mistwood Estate Retreat — estate stay near Madikeri, Coorg.",
        answers={"identity": "An estate stay.", "contact": f"WhatsApp {phone}.", "phone": phone,
                 "conversion": f"WhatsApp {phone} to book."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="hotel", business_name="Mistwood Estate Retreat", category_hint="travel_stay/resort",
        business_type="hotel", modules=STAY, reference_ids=REFS["hotel"], place="Madikeri, Coorg", phone=phone,
        kind="hotel",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal, no_photos=NO_PHOTOS,
                           own_photos="We have photos of the rooms; I'll upload them later."),
    )


def _ngo() -> Scenario:
    phone = "98410 57322"
    rich = OwnerScript(
        opening=(
            "Thozhi Learning Trust runs three free after-school learning centres in Kannagi Nagar and "
            "Semmenchery, Chennai, for 420 children from Class 1 to 10 — reading, maths and spoken English — "
            "and a scholarship that keeps girls in school after Class 10. A group of teachers started it in "
            "2014; we are a registered trust with 80G. We want people to donate online, one-time or monthly, "
            "and to volunteer — volunteers fill an enquiry form and we call them."
        ),
        answers={
            "identity": "A registered trust running free evening learning centres for children of daily-wage "
                        "families in Kannagi Nagar and Semmenchery.",
            "offer": "Evening classes in reading, maths and spoken English; library time; and girls' "
                     "scholarships for Class 11 and 12.",
            "structure": "Sponsor a child, Support a centre, Give monthly.",
            "catalogue": _catalogue("ngo"),
            "conversion": "Donate online — one-time or monthly — and volunteers fill a form.",
            "b2b": "Some companies give through CSR; they email us for a proposal.",
            "process": "CSR partners ask for our proposal and annual report first.",
            "contact": f"Thozhi Learning Trust, 14, 3rd Cross Street, Kannagi Nagar, Chennai 600097. Call {phone}.",
            "phone": phone,
            "story": "Most of our children's parents are daily-wage workers who were moved here from the "
                     "city's riverbanks. Thozhi means 'friend' — we are the friend who sits with them every "
                     "evening. In 2024, 31 of our girls finished Class 12, and 22 of them joined college.",
            "photos": "We have photos of the centres, taken with parents' consent; I'll upload them later.",
            "payment": "Online donations by UPI or card; 80G receipts by email.",
            "pricing": "Show the amounts for each way to give.",
            "hours": "Centres run 4:30 pm to 7:30 pm, Monday to Saturday.",
            "team": "Twelve teachers, most from the neighbourhood itself, and about 60 volunteers.",
            "logo": "Yes, two hands holding a book — later.",
            "look": "Warm, hopeful and human — real children's faces (with consent), hand-drawn touches, warm "
                    "yellow and deep teal. Not sad charity pictures.",
        },
        fallback="Keep it dignified and true.",
        confirm_text="Yes, please build.",
    )
    normal = OwnerScript(
        opening=("Thozhi Learning Trust, Kannagi Nagar, Chennai. Free after-school learning centres for "
                 "children, scholarships for girls. Need online donations and volunteer sign-ups."),
        answers={
            "offer": "After-school classes, reading, scholarships.",
            "catalogue": "Sponsor a child 6000 a year, girls' scholarship 18000, monthly giving 500 or 1000.",
            "conversion": "Donate online, volunteers enquire.",
            "payment": "UPI, card, 80G receipt.",
            "contact": f"Kannagi Nagar, Chennai. {phone}",
            "phone": phone,
            "story": "Started by teachers in 2014, 420 children now.",
            "team": "12 teachers and volunteers.",
        },
        fallback="Not sure, keep it simple.",
        confirm_text="Yes, build it.",
    )
    bad = OwnerScript(
        opening=("thozhi lerning trust kannagi nagar chennai, free tution centres for kids after school, girls "
                 "scholarship also, we need donation online and volunter form"),
        answers={
            "offer": "evening tution, reading, maths, spoken english, schlorship for girls",
            "catalogue": "1 child 1 year 6000, girl schlorship 18000/yr, monthly 500 or 1000",
            "conversion": "donate button + volunter form",
            "payment": "upi card, 80G reciept",
            "contact": f"kannagi nagar 3rd cross, {phone}",
            "phone": phone,
            "story": "2014 la teachers start pannom, 420 kids now",
        },
        fallback="neenga paathukonga",
        confirm_text="ok, build pannunga",
    )
    minimal = OwnerScript(
        opening="Thozhi Learning Trust — free learning centres for children in Kannagi Nagar, Chennai.",
        answers={"identity": "A trust running free learning centres.", "contact": f"Call {phone}.",
                 "phone": phone, "conversion": f"Call {phone}."},
        fallback="Skip.",
        confirm_text="ok",
    )
    return Scenario(
        key="ngo", business_name="Thozhi Learning Trust", category_hint="community/education_ngo",
        business_type="other", modules=CAUSE, reference_ids=REFS["ngo"], place="Kannagi Nagar, Chennai",
        phone=phone, kind="ngo",
        variants=_variants(rich=rich, normal=normal, bad_input=bad, minimal=minimal, no_photos=NO_PHOTOS,
                           own_photos="We have photos of the centres; I'll upload them later."),
    )


SCENARIOS: dict[str, Scenario] = {s.key: s for s in (
    _restaurant_delivery(), _restaurant_reservations(), _meat_shop(), _bakery(), _gym(), _salon(), _clinic(),
    _consultant(), _retail(), _architecture(), _hotel(), _ngo(),
)}


# ------------------------------------------------------------------ the distinctness set

def _distinct(
    kind: str, slug: str, name: str, hint: str, business_type: str, modules: tuple[str, ...],
    place: str, phone: str, opening: str, answers: dict[str, str],
    fallback: str = "Not sure, you decide.", confirm: str = "Yes, build it.", refs: str = "",
) -> Scenario:
    """One more owner of a category, told the normal way (PLAN §1 distinctness set)."""
    script = OwnerScript(opening=opening, answers={**answers, "phone": phone}, fallback=fallback,
                         confirm_text=confirm)
    return Scenario(
        key=f"distinct-{kind}-{slug}", business_name=name, category_hint=hint, business_type=business_type,
        modules=modules, variants={"normal": script}, reference_ids=REFS[refs or kind], place=place,
        phone=phone, kind=refs or kind,
    )


DISTINCT: dict[str, list[Scenario]] = {
    "restaurant": [
        _distinct(
            "restaurant", "zafrani-handi", "Zafrani Handi", "food_service/biryani_shop", "restaurant",
            DELIVERY_KITCHEN, "Kondapur, Hyderabad", "99490 31245",
            "Zafrani Handi — Hyderabadi dum biryani and kebabs, a delivery kitchen in Kondapur, Hyderabad. "
            "Online order and delivery within 7 km.",
            {"offer": "Chicken dum biryani, mutton dum biryani, paneer biryani, kebabs, double ka meetha.",
             "catalogue": "Chicken dum biryani 320, mutton 420, paneer 280, chicken 65 260, double ka meetha 120.",
             "traits": "Mutton biryani sells most. Paneer biryani and double ka meetha are veg.",
             "conversion": "Order and pay online.",
             "fulfilment": "Delivery within 7 km — Kondapur, Gachibowli, Madhapur, Kothaguda. No dine-in.",
             "contact": "Kondapur main road, Hyderabad. 99490 31245",
             "payment": "UPI, card online.", "hours": "12 pm to 11:30 pm.",
             "story": "Biryani cooked on a wood fire in copper handis — my grandfather's recipe from the Old City."},
        ),
        _distinct(
            "restaurant", "mylapore-tiffin-room", "Mylapore Tiffin Room", "food_service/restaurant", "restaurant",
            COUNTER_ORDERS, "Mylapore, Chennai", "94440 16732",
            "Mylapore Tiffin Room — idli, dosa, pongal and filter coffee, a small tiffin place near the "
            "Kapaleeshwarar temple, Mylapore. People walk in or order parcels for pickup.",
            {"catalogue": "Idli 2 pcs 40, ghee pongal 70, masala dosa 80, podi dosa 75, filter coffee 30.",
             "traits": "Ghee pongal and filter coffee. Everything is pure veg.",
             "conversion": "Order a parcel on the phone or online, and pick it up.",
             "fulfilment": "Pickup only, no delivery.",
             "contact": "East Mada Street, Mylapore. 94440 16732",
             "hours": "6:30 to 11 am and 4:30 to 9 pm.", "payment": "Cash or UPI.",
             "story": "Same family since 1986; the coffee decoction is made fresh every hour."},
        ),
        _distinct(
            "restaurant", "tambda-pandhra-house", "Tambda Pandhra House", "food_service/restaurant", "restaurant",
            TABLE_BOOKING, "Kothrud, Pune", "98230 54619",
            "Tambda Pandhra House, a Kolhapuri non-veg thali restaurant in Kothrud, Pune. Weekends we are full, "
            "so people should book a table.",
            {"catalogue": "Mutton thali 450, chicken thali 380, Kolhapuri misal 120, sukka mutton 360, "
                          "solkadhi 60.",
             "traits": "Mutton thali with tambda and pandhra rassa. Misal and solkadhi are veg.",
             "conversion": "Book a table online for weekends; weekdays just walk in.",
             "bookings": "Tables of 2, 4 and 8. Lunch and dinner.",
             "fulfilment": "No delivery.",
             "contact": "Karve Road, Kothrud, Pune. 98230 54619",
             "hours": "12 to 3:30 and 7 to 11, all days.", "payment": "Pay at the table.",
             "story": "Kolhapur recipes; my mother grinds the masala herself."},
        ),
        _distinct(
            "restaurant", "saltwater-cafe", "Saltwater Café", "food_service/cafe", "restaurant",
            TABLE_BOOKING, "Fort Kochi, Kochi", "97450 62318",
            "Saltwater Café in Fort Kochi, near the beach. Seafood and Kerala-European café food, sunset "
            "dinners. Tourists book tables for dinner.",
            {"catalogue": "Grilled catch of the day 650, prawn moilee 520, fish and chips 480, squid "
                          "ularthiyathu 450, banana fritters with ice cream 220.",
             "traits": "Grilled catch and prawn moilee. Banana fritters are veg.",
             "conversion": "Book a dinner table online.",
             "bookings": "Sunset tables from 6 to 7:30 are the most asked for.",
             "contact": "Bastion Street, Fort Kochi. 97450 62318",
             "hours": "8 am to 10:30 pm.", "payment": "UPI or card.",
             "story": "We buy our fish from the Chinese-net fishermen every morning."},
        ),
        _distinct(
            "restaurant", "moss-and-millet", "Moss & Millet", "food_service/restaurant", "restaurant",
            DELIVERY_KITCHEN, "Koramangala, Bengaluru", "96111 47285",
            "Moss & Millet — plant-based millet bowls and salads, a delivery kitchen in Koramangala, Bengaluru. "
            "People order online.",
            {"catalogue": "Ragi bisibele bowl 260, foxtail millet pulao 240, jowar Buddha bowl 290, quinoa "
                          "salad 270, cold-pressed juice 150.",
             "traits": "The jowar bowl and ragi bisibele. Everything is vegan.",
             "conversion": "Order and pay online.",
             "fulfilment": "We deliver 5 km around Koramangala.",
             "contact": "5th Block, Koramangala. 96111 47285",
             "hours": "11 am to 10 pm.", "payment": "UPI or card.",
             "story": "Planned with a nutritionist — no refined sugar, no maida."},
        ),
    ],
    "gym": [
        _distinct(
            "gym", "pulse-crossbox", "Pulse CrossBox", "fitness/crossfit", "gym", GYM, "Baner, Pune",
            "98901 26473",
            "Pulse CrossBox — a functional-fitness box in Baner, Pune. Group classes and memberships; the "
            "first class is free.",
            {"plans": "Monthly unlimited 4500, 12 classes 3800, quarterly 12000.",
             "bookings": "One-hour classes; book a slot, max 14 people.",
             "conversion": "Book a free class, then buy a membership online.",
             "contact": "Baner-Pashan Link Road, Pune. 98901 26473",
             "hours": "6-10 am and 5-9 pm.", "payment": "UPI or card online.",
             "story": "Certified coaches and a real community — Saturday team workouts."},
        ),
        _distinct(
            "gym", "shakti-womens-fitness", "Shakti Women's Fitness", "fitness/gym", "gym", GYM, "Adyar, Chennai",
            "98848 30619",
            "Shakti Women's Fitness — a women-only gym in Adyar, Chennai, with women trainers. Strength, "
            "Zumba and yoga classes.",
            {"plans": "Monthly 2800, quarterly 7500, half-yearly 13500.",
             "bookings": "45-minute classes; PT with a trainer.",
             "providers": "PT members choose their trainer.",
             "conversion": "Book a trial, then join.",
             "contact": "LB Road, Adyar. 98848 30619",
             "hours": "5:30-11 am and 4-9 pm, Sunday off.", "payment": "UPI or card.",
             "story": "Safe and women-only, with women trainers and a postnatal programme."},
        ),
        _distinct(
            "gym", "ironwood-strength-lab", "Ironwood Strength Lab", "fitness/powerlifting", "gym", GYM,
            "Kakkanad, Kochi", "95390 41827",
            "Ironwood Strength Lab — a powerlifting gym in Kakkanad, Kochi. Competition coaching and memberships.",
            {"plans": "Monthly 2500, coaching plan 5000 a month.",
             "bookings": "Coaching sessions of 90 minutes.",
             "conversion": "Book a trial session.",
             "contact": "Seaport-Airport Road, Kakkanad. 95390 41827",
             "hours": "5 am to 10 pm.", "payment": "UPI.",
             "story": "Calibrated plates and competition benches; we have coached nine state champions."},
        ),
        _distinct(
            "gym", "prana-reformer-pilates", "Prana Reformer Pilates", "fitness/pilates", "gym", GYM,
            "Whitefield, Bengaluru", "99007 38254",
            "Prana Reformer Pilates — a reformer pilates studio in Whitefield, Bengaluru. Small classes of six "
            "on reformers.",
            {"plans": "Intro 3 classes 2400, 8-class pack 7200, monthly unlimited 11000.",
             "bookings": "50-minute classes; book a reformer.",
             "conversion": "Book the intro classes online and pay.",
             "contact": "ITPL Main Road, Whitefield. 99007 38254",
             "hours": "7 am to 9 pm.", "payment": "Card or UPI online.",
             "story": "Physio-led classes, good for back pain."},
        ),
        _distinct(
            "gym", "southpaw-boxing-club", "Southpaw Boxing Club", "fitness/martial_arts", "gym", GYM,
            "Gachibowli, Hyderabad", "90320 58164",
            "Southpaw Boxing Club — a boxing and kickboxing gym in Gachibowli, Hyderabad. Beginner classes up "
            "to the fight team.",
            {"plans": "Monthly 3200, quarterly 8700, kids monthly 2500.",
             "bookings": "One-hour classes; the first trial is free.",
             "conversion": "Book a free trial class online.",
             "contact": "Gachibowli main road, Hyderabad. 90320 58164",
             "hours": "6-9 am and 6-10 pm.", "payment": "UPI or card.",
             "story": "Our head coach boxed at the national level — technique first, always."},
        ),
    ],
    "salon": [
        _distinct(
            "salon", "blade-and-brush", "Blade & Brush Barbers", "beauty/barber", "salon", SALON,
            "Viman Nagar, Pune", "98509 41736",
            "Blade & Brush — a men's barbershop in Viman Nagar, Pune. Haircuts, beard work and hot towel shaves.",
            {"catalogue": "Haircut 400, beard trim 250, hot towel shave 350, hair and beard 600, kids' cut 300.",
             "bookings": "30-minute slots; people choose a barber.",
             "conversion": "Book online.",
             "contact": "Viman Nagar, Pune. 98509 41736",
             "hours": "10 to 9, Tuesday closed.", "payment": "UPI or card at the shop.",
             "story": "Old-school barbering with a straight razor."},
        ),
        _distinct(
            "salon", "nail-nook", "Nail Nook Studio", "beauty/nail_studio", "salon", SALON,
            "Banjara Hills, Hyderabad", "90009 47318",
            "Nail Nook — a nail art studio in Banjara Hills, Hyderabad. Gel polish, extensions and nail art.",
            {"catalogue": "Gel polish 1200, acrylic extensions 2500, nail art 150 per nail, removal 500, "
                          "pedicure 1300.",
             "bookings": "Appointments of one to two hours.",
             "conversion": "Book online with a small advance.",
             "contact": "Road No. 12, Banjara Hills. 90009 47318",
             "hours": "11 to 8.", "payment": "UPI or card.",
             "story": "Hygiene first — sterilised tools — and designs made for you."},
        ),
        _distinct(
            "salon", "mallige-bridal", "Mallige Bridal Studio", "beauty/bridal_makeup", "salon", SALON,
            "Basavanagudi, Bengaluru", "99801 26574",
            "Mallige Bridal Studio — bridal makeup and hair in Basavanagudi, Bengaluru. Weddings, receptions "
            "and engagements.",
            {"catalogue": "Bridal makeup 22000, reception 15000, engagement 12000, saree draping 1500, family "
                          "makeup 3500 per person.",
             "bookings": "Book the date; the trial is two weeks before.",
             "conversion": "Enquire and book the date with an advance.",
             "contact": "Bull Temple Road, Basavanagudi. 99801 26574",
             "payment": "Advance online, balance on the day.",
             "story": "Traditional Kannada bridal looks, with jasmine hair styling."},
        ),
        _distinct(
            "salon", "ayur-glow", "Ayur Glow Spa & Salon", "beauty/spa", "salon", SALON, "Edappally, Kochi",
            "97440 38265",
            "Ayur Glow — an Ayurvedic spa and salon in Edappally, Kochi. Abhyanga, shirodhara, facials and "
            "hair care.",
            {"catalogue": "Abhyanga massage 60 min 2200, shirodhara 2800, herbal facial 1500, hair spa 1200, "
                          "foot reflexology 900.",
             "bookings": "Appointments, with separate therapists for women and men.",
             "providers": "Women are attended by women therapists.",
             "conversion": "Book online.",
             "contact": "Near Edappally toll junction, Kochi. 97440 38265",
             "hours": "9 to 8.", "payment": "UPI or card.",
             "story": "Our oils are prepared in-house by our vaidyan."},
        ),
        _distinct(
            "salon", "curl-theory", "Curl Theory Hair Studio", "beauty/salon", "salon", SALON,
            "Besant Nagar, Chennai", "94449 81627",
            "Curl Theory — a curly and wavy hair specialist salon in Besant Nagar, Chennai. Curl cuts, curl "
            "colour and care.",
            {"catalogue": "Curly cut (dry cut) 1800, curl consultation 500, curl colour from 4000, curl "
                          "treatment 2500.",
             "bookings": "90-minute appointments; choose your stylist.",
             "conversion": "Book online.",
             "contact": "2nd Avenue, Besant Nagar. 94449 81627",
             "hours": "10 to 7, Monday closed.", "payment": "UPI or card.",
             "story": "Dry-cut, curl by curl — we never straighten."},
        ),
    ],
    "professional": [
        _distinct(
            "professional", "raghavan-and-co", "Raghavan & Co, Chartered Accountants", "professional/ca",
            "professional_service", ADVISORY, "T Nagar, Chennai", "98410 26347",
            "Raghavan & Co is a chartered accountants firm in T Nagar, Chennai — GST, income tax, audit and "
            "company compliance for small businesses.",
            {"offer": "GST filing, income tax returns, statutory audit, company incorporation, payroll compliance.",
             "catalogue": "GST monthly filing from 2500 a month, ITR for salaried 1500, business ITR from 5000, "
                          "company incorporation 12000.",
             "conversion": "Send an enquiry or call to book a consultation.",
             "process": "Consultation, quote, then an engagement letter.",
             "contact": "Thanikachalam Road, T Nagar. 98410 26347",
             "hours": "Mon-Sat 10 to 7.", "payment": "Bank transfer or UPI against an invoice.",
             "story": "Since 1994 — three partners and more than 600 clients."},
            refs="consultant",
        ),
        _distinct(
            "professional", "farah-siddiqui-advocate", "Farah Siddiqui, Advocate", "professional/lawyer",
            "professional_service", ADVISORY, "Frazer Town, Bengaluru", "98454 70263",
            "I'm Farah Siddiqui, an advocate in Frazer Town, Bengaluru — family law, property disputes and "
            "documentation.",
            {"offer": "Divorce and custody, property disputes, sale deeds and wills, legal notices.",
             "catalogue": "Consultation 2000, legal notice 5000, will drafting 7500, sale deed review 10000.",
             "conversion": "Book a consultation.",
             "contact": "Mosque Road, Frazer Town. 98454 70263",
             "hours": "Mon-Sat 11 to 7, by appointment.", "payment": "UPI or bank transfer.",
             "story": "Fifteen years of practice; I explain everything in Urdu, Kannada or English."},
            refs="consultant",
        ),
        _distinct(
            "professional", "brickline-interiors", "Brickline Interiors", "design_build/interior_designer",
            "professional_service", DESIGN_PRACTICE, "Wakad, Pune", "97660 41853",
            "Brickline Interiors — home interiors and modular kitchens in Wakad, Pune. Mostly 2 and 3 BHK flats.",
            {"catalogue": "Modular kitchen from 1.8 lakh, wardrobes from 1400 per sq ft, full 2BHK interiors "
                          "from 6 lakh.",
             "conversion": "Enquiry, a free site measurement, then a quote.",
             "process": "Measure, 3D design, quote, then 45 days to finish.",
             "contact": "Wakad, Pune. 97660 41853",
             "story": "Our own factory, and a 10-year warranty on kitchens."},
            refs="architecture",
        ),
        _distinct(
            "professional", "kshetra-landscape", "Kshetra Landscape Studio", "design_build/landscape_architect",
            "professional_service", DESIGN_PRACTICE, "Jubilee Hills, Hyderabad", "99896 52731",
            "Kshetra Landscape Studio — landscape architects in Jubilee Hills, Hyderabad. Gardens for homes, "
            "villas, terraces and campuses.",
            {"catalogue": "Terrace garden design from 60000, villa garden from 1.5 lakh, campus landscapes on "
                          "quote, site visit 3000.",
             "conversion": "Enquiry, then a site visit and a quote.",
             "process": "Site visit, concept, quote, then planting.",
             "contact": "Road No. 36, Jubilee Hills. 99896 52731",
             "story": "Native plants and low-water gardens."},
            refs="architecture",
        ),
        _distinct(
            "professional", "clearpath-hr", "Clearpath HR Consulting", "professional/hr_consultant",
            "professional_service", ADVISORY, "Kakkanad, Kochi", "94460 72815",
            "Clearpath HR Consulting — HR and payroll for startups and small companies, based in Kakkanad, Kochi.",
            {"catalogue": "Payroll 250 per employee a month, HR policy handbook 40000, POSH compliance 25000, "
                          "recruitment at 8.33% of CTC.",
             "conversion": "Send an enquiry or book a call.",
             "b2b": "IT startups at Infopark, clinics and manufacturers.",
             "contact": "Infopark Road, Kakkanad. 94460 72815",
             "payment": "Bank transfer against a GST invoice.",
             "story": "Run by former HR heads from IT companies."},
            refs="consultant",
        ),
    ],
    "retail": [
        _distinct(
            "retail", "neelambari-handlooms", "Neelambari Handlooms", "retail/clothing", "retail", STORE,
            "Mylapore, Chennai", "98400 73519",
            "Neelambari Handlooms — Kanchipuram silk and cotton handloom sarees in Mylapore, Chennai. We want "
            "online orders with payment, and delivery in Chennai.",
            {"catalogue": "Kanchi silk sarees from 18000, Chettinad cotton 1800, Kovai cotton 1500, silk cotton "
                          "4500.",
             "stock": "Each saree is one piece — show sold out.",
             "conversion": "Order and pay online, or a video call to see sarees.",
             "fulfilment": "Delivery in Chennai, and pickup.",
             "contact": "North Mada Street, Mylapore. 98400 73519",
             "hours": "10:30 to 8:30.", "payment": "UPI or card.",
             "story": "Straight from weavers in Kanchipuram and Karaikudi."},
        ),
        _distinct(
            "retail", "pages-and-pencils", "Pages & Pencils", "retail/books", "retail", STORE,
            "Kalyani Nagar, Pune", "98225 61874",
            "Pages & Pencils — an independent bookstore and stationery shop in Kalyani Nagar, Pune. Books, "
            "journals and art supplies.",
            {"catalogue": "New fiction from 299, children's books from 150, dotted journals 650, watercolour "
                          "sets from 900, fountain pens from 450.",
             "stock": "Yes, show what's in stock.",
             "conversion": "Order and pay online.",
             "fulfilment": "Delivery in Pune, and pickup.",
             "contact": "Kalyani Nagar, Pune. 98225 61874",
             "hours": "11 to 9.", "payment": "UPI or card.",
             "story": "A reading corner, and a Saturday story hour for kids."},
        ),
        _distinct(
            "retail", "malabar-spice-house", "Malabar Spice House", "fresh_grocery/spices", "retail", STORE,
            "Mattancherry, Kochi", "94950 38216",
            "Malabar Spice House — spices, tea and cashews in Jew Town, Mattancherry, Kochi. Online orders and "
            "delivery.",
            {"catalogue": "Tellicherry black pepper 250 g 320, green cardamom 100 g 380, cinnamon 100 g 180, "
                          "cashew W240 500 g 650, high-range tea 250 g 290.",
             "stock": "Show stock, some lots sell out.",
             "conversion": "Order and pay online.",
             "fulfilment": "Delivery in Kochi; pickup from the shop.",
             "contact": "Jew Town Road, Mattancherry. 94950 38216",
             "payment": "UPI or card.",
             "story": "Bought straight from Idukki and Wayanad farmers, cleaned and packed here."},
        ),
        _distinct(
            "retail", "mitti-and-glaze", "Mitti & Glaze", "retail/home_decor", "retail", STORE,
            "Sainikpuri, Hyderabad", "98663 52740",
            "Mitti & Glaze — a handmade ceramic and terracotta store in Sainikpuri, Hyderabad. Mugs, plates "
            "and planters.",
            {"catalogue": "Stoneware mug 650, dinner plate 900, serving bowl 1200, terracotta planter from 450.",
             "stock": "Handmade in small batches — show sold out.",
             "conversion": "Order and pay online.",
             "fulfilment": "Delivery in Hyderabad; pickup from the studio.",
             "contact": "Sainikpuri, Hyderabad. 98663 52740",
             "payment": "UPI or card.",
             "story": "Made by our two potters in our own studio kiln."},
        ),
        _distinct(
            "retail", "pedal-point-cycles", "Pedal Point Cycles", "retail/sports_goods", "retail", STORE,
            "JP Nagar, Bengaluru", "99459 31826",
            "Pedal Point Cycles — a bicycle shop in JP Nagar, Bengaluru. Kids' cycles, hybrids, accessories "
            "and servicing.",
            {"catalogue": "Kids' cycles from 6500, hybrids from 18000, helmet 1500, light set 900, basic "
                          "service 499.",
             "stock": "Show what's in stock.",
             "conversion": "Order and pay online; test rides at the store.",
             "fulfilment": "Delivered assembled in south Bengaluru; pickup too.",
             "contact": "JP Nagar 6th Phase, Bengaluru. 99459 31826",
             "payment": "UPI or card.",
             "story": "We fit the cycle to the rider, and the first service is free."},
        ),
    ],
}


# ------------------------------------------------------------------ access


def all_scenarios() -> list[Scenario]:
    return [*SCENARIOS.values(), *(s for group in DISTINCT.values() for s in group)]


def scenario(key: str) -> Scenario:
    found = SCENARIOS.get(key) or next((s for s in all_scenarios() if s.key == key), None)
    if found is None:
        raise KeyError(f"unknown certification scenario: {key}")
    return found


def journeys() -> list[tuple[Scenario, str]]:
    """Every journey of the run: 12 scenarios x 6 variants, then the 25 distinctness owners."""
    matrix = [(s, v) for s in SCENARIOS.values() for v in VARIANTS]
    distinct = [(s, "normal") for group in DISTINCT.values() for s in group]
    return matrix + distinct


def media_gap(s: Scenario, variant: str) -> str | None:
    """Why this journey runs without the owner photos its variant calls for, if it does."""
    if variant in {"rich", "owner_media"} and not s.variants[variant].media:
        return MEDIA_GAPS.get(s.key, "no owner photos on disk")
    return None
