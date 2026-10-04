"""The next question: the one that teaches Locah most about THIS business.

A question is an *ask*: a short, natural question that can fill one or two
related pieces at once ("Do you deliver, or do people pick up — and which
areas?"). Asks are ranked by information gain — how much the pieces they
could fill matter to this business (see `coverage.importance`) times how
unknown those pieces still are — never by which field happens to be empty.

Before the first version only essentials and high-value pieces are asked,
within a budget; enrichment (prices, hours, photos for most trades, logo)
is offered at the checkpoint and asked only if the owner keeps refining.

Wording comes from the trade's playbook when it has one ("Do people choose
the cut too — curry cut, boneless?"), else from a plain generic question in
the owner's language.
"""

from __future__ import annotations

from dataclasses import dataclass

from platform_core.interview.coverage import (
    WEIGHT,
    Profile,
    coverage,
    importance,
    profile,
    relevant,
    resolved,
)
from platform_core.interview.discovery import TARGETS_BY_ID
from platform_core.interview.models import AskRecord, BusinessBlueprint
from platform_core.interview.playbooks import phrase_override


@dataclass(frozen=True)
class Ask:
    id: str
    targets: tuple[str, ...]  # the lead piece first
    text: dict[str, str]  # generic wording: en / ta_en / ta


ASKS: tuple[Ask, ...] = (
    # Only when the opening answer did not say what the business is.
    Ask("identity", ("business.identity",), {
        "en": "Tell me a little more about {name} — what kind of business is it, and who is it for?",
        "ta_en": "{name} pathi konjam sollunga — enna maadhiri business, yaarukkaaga?",
        "ta": "{name} பத்தி கொஞ்சம் சொல்லுங்க — என்ன மாதிரி பிசினஸ், யாருக்காக?",
    }),
    Ask("offer", ("offerings.main",), {
        "en": "What are the main things you sell or offer — the ones people should see first?",
        "ta_en": "Neenga enna sell / offer pannureenga — customers first-a edhai paakanum?",
        "ta": "நீங்க என்ன விற்கிறீங்க அல்லது தர்றீங்க — முதல்ல எதை காட்டணும்?",
    }),
    Ask("structure", ("offerings.structure", "offerings.units"), {
        "en": "{structure}",
        "ta_en": "{structure}",
        "ta": "{structure}",
    }),
    Ask("conversion", ("commerce.action",), {
        "en": "When someone finds {name} online, what should they be able to do — order, book, ask for a "
              "quote, or call or WhatsApp you?",
        "ta_en": "Online-la {name} paathaanga-na enna pannanum — order, book, quote kekkaradhu, illa call / "
                 "WhatsApp?",
        "ta": "ஆன்லைன்ல {name}-ஐ பார்த்தவங்க என்ன செய்யணும் — ஆர்டர், புக்கிங், கொட்டேஷன், அல்லது கால் / "
              "வாட்ஸ்அப்?",
    }),
    Ask("fulfilment", ("fulfilment.mode", "fulfilment.area"), {
        "en": "Do you deliver, or do people pick up from you — and if you deliver, roughly which areas?",
        "ta_en": "Neenga deliver pannuveengalaa, illa customers pickup pannuvaangalaa? Deliver-na endha areas?",
        "ta": "நீங்க டெலிவரி பண்ணுவீங்களா, இல்ல வாடிக்கையாளர்களே வந்து வாங்குவாங்களா? டெலிவரின்னா எந்த ஏரியா?",
    }),
    Ask("area", ("fulfilment.area",), {
        "en": "Roughly which areas do you cover?",
        "ta_en": "Endha areas cover pannureenga?",
        "ta": "எந்த ஏரியாக்களை கவர் பண்றீங்க?",
    }),
    Ask("contact", ("contact.location", "contact.phone"), {
        "en": "Where are you, and which number should customers call or WhatsApp?",
        "ta_en": "Neenga enga irukeenga, customers endha number-ku call / WhatsApp pannanum?",
        "ta": "நீங்க எங்க இருக்கீங்க? வாடிக்கையாளர்கள் எந்த நம்பருக்கு கால் / வாட்ஸ்அப் பண்ணணும்?",
    }),
    Ask("phone", ("contact.phone",), {
        "en": "Which number should customers call or WhatsApp?",
        "ta_en": "Customers endha number-ku call / WhatsApp pannanum?",
        "ta": "வாடிக்கையாளர்கள் எந்த நம்பருக்கு கால் / வாட்ஸ்அப் பண்ணணும்?",
    }),
    Ask("b2b", ("b2b.customers", "b2b.process"), {
        "en": "Which kinds of businesses buy from you most — and do they usually ask for a quote first?",
        "ta_en": "Endha maadhiri businesses unga kitta adhigama vaanguvaanga — mudhalla quote kepaangalaa?",
        "ta": "எந்த மாதிரி நிறுவனங்கள் அதிகமா வாங்குவாங்க — முதல்ல கொட்டேஷன் கேப்பாங்களா?",
    }),
    # The second half of a pair, asked alone when the first half is already known.
    Ask("process", ("b2b.process",), {
        "en": "How does a business usually order from you — do they send a requirement and ask for a quote first?",
        "ta_en": "Oru company eppadi order pannuvaanga — mudhalla requirement anuppi quote kepaangalaa?",
        "ta": "ஒரு நிறுவனம் எப்படி ஆர்டர் பண்ணுவாங்க — முதல்ல கொட்டேஷன் கேப்பாங்களா?",
    }),
    Ask("providers", ("services.providers",), {
        "en": "Do customers ask for a particular person, or whoever is free?",
        "ta_en": "Customers oru particular aala kepaangalaa, illa yaar free-o avangalaa?",
        "ta": "வாடிக்கையாளர்கள் குறிப்பிட்ட ஒருத்தரை கேப்பாங்களா, இல்ல யார் ஃப்ரீயோ அவங்களா?",
    }),
    Ask("units", ("offerings.units",), {
        "en": "Do people order by weight, or in fixed packs or pieces?",
        "ta_en": "Kg-la order pannuvaangalaa, illa fixed packs / pieces-aa?",
        "ta": "எடைக்கு ஆர்டர் பண்ணுவாங்களா, இல்ல ஃபிக்ஸ்ட் பேக் / பீஸா?",
    }),
    Ask("plans", ("memberships.plans",), {
        "en": "Which plans can people choose from — monthly, yearly, packs of sessions?",
        "ta_en": "Enna plans irukku — monthly, yearly, session packs?",
        "ta": "என்ன பிளான்கள் இருக்கு — மாதம், வருடம், செஷன் பேக்?",
    }),
    Ask("bookings", ("bookings.format", "services.providers"), {
        "en": "What do people usually book — and do they ask for a particular person, or whoever is free?",
        "ta_en": "Usual-aa enna book pannuvaanga — oru particular aala kepaangalaa, illa yaar free-o avangalaa?",
        "ta": "வழக்கமா என்ன புக் பண்ணுவாங்க — குறிப்பிட்ட ஒருத்தரை கேப்பாங்களா, இல்ல யார் ஃப்ரீயோ அவங்களா?",
    }),
    Ask("story", ("brand.story",), {
        "en": "What should people remember about {name} — what makes you different?",
        "ta_en": "{name} pathi customers enna nyabagam vechukkanum — ungala vera maadhiri aakkaradhu enna?",
        "ta": "{name} பத்தி மக்கள் எதை நினைவில் வைக்கணும் — உங்களை தனித்துவமாக்குவது என்ன?",
    }),
    Ask("photos", ("media.photos",), {
        "en": "Do you have photos of your {things}, or {material}, you'd like me to use? "
              "Attach them here — or I'll create draft visuals for you.",
        "ta_en": "Unga {things} photos illa {material} irukkaa? Inga attach pannunga — illa-na naan "
                 "draft visuals ready pannuren.",
        "ta": "உங்க பொருட்களோட படங்கள், இல்ல {material} இருக்கா? இங்க இணைங்க — இல்லன்னா நான் "
              "மாதிரி படங்கள் ரெடி பண்றேன்.",
    }),
    Ask("payment", ("commerce.payment",), {
        "en": "How do customers pay — UPI, cash, card, or online when they order?",
        "ta_en": "Customers eppadi pay pannuvaanga — UPI, cash, card, illa order pannumbodhe online-aa?",
        "ta": "வாடிக்கையாளர்கள் எப்படி பணம் கட்டுவாங்க — UPI, கேஷ், கார்டு, அல்லது ஆன்லைன்?",
    }),
    Ask("customisation", ("offerings.customisation",), {
        "en": "What can customers ask you to make or change for them?",
        "ta_en": "Customers enna customise panni kekkalaam?",
        "ta": "வாடிக்கையாளர்கள் என்ன மாற்றி செய்ய சொல்லலாம்?",
    }),
    Ask("pricing", ("offerings.pricing",), {
        "en": "Would you like prices on the website, a 'starting from' price, or 'price on request'?",
        "ta_en": "Website-la price podalaamaa, 'starting from' podalaamaa, illa 'price on request'-aa?",
        "ta": "வெப்சைட்ல விலை போடலாமா, 'தொடக்க விலை' போடலாமா, இல்ல 'விலைக்கு கேளுங்க'-ஆ?",
    }),
    Ask("hours", ("operations.hours",), {
        "en": "What are your usual opening hours?",
        "ta_en": "Usual-aa eppo open irukkum?",
        "ta": "வழக்கமா எப்போ திறந்திருக்கும்?",
    }),
    Ask("team", ("operations.team",), {
        "en": "Is it mostly you, or a team customers will meet?",
        "ta_en": "Neenga mattum-aa, illa customers paakura team irukkaa?",
        "ta": "நீங்க மட்டுமா, இல்ல டீம் இருக்கா?",
    }),
    Ask("logo", ("media.logo",), {
        "en": "Do you have a logo you'd like on the website? You can attach it here.",
        "ta_en": "Logo irukkaa? Inga attach pannalaam.",
        "ta": "லோகோ இருக்கா? இங்க இணைக்கலாம்.",
    }),
    Ask("look", ("brand.feel",), {
        "en": "Any colours or a feel you'd like the website to have?",
        "ta_en": "Website-ku edhaavadhu colour illa feel venumaa?",
        "ta": "வெப்சைட்டுக்கு ஏதாவது நிறம் அல்லது உணர்வு வேணுமா?",
    }),
    Ask("stock", ("operations.stock",), {
        "en": "Does what you have change day to day — should people see when something is sold out?",
        "ta_en": "Stock dhinamum maarumaa — sold out-na customers-ku theriyanumaa?",
        "ta": "தினமும் ஸ்டாக் மாறுமா — தீர்ந்தா தெரியணுமா?",
    }),
)
ASKS_BY_ID: dict[str, Ask] = {a.id: a for a in ASKS}


def ask_for_target(target_id: str) -> Ask | None:
    """The ask that leads with a target, else one that covers it."""
    lead = next((a for a in ASKS if a.targets[0] == target_id), None)
    return lead or next((a for a in ASKS if target_id in a.targets), None)


@dataclass(frozen=True)
class Ranked:
    ask: Ask
    score: float
    lead_importance: str


def rank(bp: BusinessBlueprint, business_type: str | None = None, *, prof: Profile | None = None) -> list[Ranked]:
    """Asks worth asking now, most informative first."""
    prof = prof or profile(bp, business_type)
    ready = bp.completion_state.ready_at is not None or bp.readiness.ready
    allowed = {"blocking", "high_value"} if not ready or not bp.refining else {
        "blocking", "high_value", "enrichment", "optional"}
    asked_before = {a.ask for a in bp.asks}
    last = bp.asks[-1].ask if bp.asks else ""
    out: list[Ranked] = []
    for ask in ASKS:
        lead = ask.targets[0]
        target = TARGETS_BY_ID[lead]
        if not relevant(target, prof, bp):
            continue
        lead_imp = importance(lead, prof, bp)
        if lead_imp not in allowed or resolved(bp, lead, lead_imp):
            continue
        if ask.id == last:
            continue  # never the same question twice in a row
        if ask.id == "structure" and not _offer_started(bp):
            continue  # varieties only once the range is named
        if ask.id == "contact" and not relevant(TARGETS_BY_ID["contact.location"], prof, bp):
            continue
        if ask.id == "area" and "fulfilment" not in asked_before and \
                (bp.discovery.get("fulfilment.mode") is None or bp.discovery["fulfilment.mode"].status != "answered"):
            continue  # asked inside "deliver or pickup?" unless that was already answered
        score = 0.0
        for index, target_id in enumerate(ask.targets):
            t = TARGETS_BY_ID[target_id]
            if not relevant(t, prof, bp):
                continue
            imp = importance(target_id, prof, bp)
            if resolved(bp, target_id, imp):
                continue
            level = coverage(bp, target_id)
            uncertainty = 1.0 if level == "unknown" else 0.6 if level == "partial" else 0.1
            # A paired question is worth a little more than its lead alone —
            # not so much that "where + number" outranks "delivery or pickup?".
            score += WEIGHT[imp] * uncertainty * (t.value / 100) * (1.0 if index == 0 else 0.35)
        if ask.id in asked_before:
            score *= 0.35
        if ask.id == "photos" and any(
            t != "media.photos" and importance(t, prof, bp) in {"blocking", "high_value"}
            and relevant(TARGETS_BY_ID[t], prof, bp) and not resolved(bp, t, importance(t, prof, bp))
            for t in TARGETS_BY_ID
        ):
            # Understand the business first; "what pictures or menu do you
            # have?" is the last question before the first version.
            score *= 0.05
        # Follow the thread the owner started: "all types of meat" is best
        # followed by "which meats?", not by an unrelated question.
        if (bp.discovery.get(lead) and bp.discovery[lead].status == "partial"):
            score *= 1.6
        if score > 0:
            out.append(Ranked(ask, score, lead_imp))
    out.sort(key=lambda r: -r.score)
    return out


def _offer_started(bp: BusinessBlueprint) -> bool:
    s = bp.discovery.get("offerings.main")
    return bool(bp.taxonomy.groups) or bool(s and s.status in {"answered", "partial"})


def choose(bp: BusinessBlueprint, proposed: str, business_type: str | None = None) -> Ranked | None:
    """The model's proposal if it is nearly as informative as the best, else the best.

    The model hears the conversation and may follow its flow ("they book
    tables" leads to how bookings work) — but never to something low-value
    while an essential is still open.
    """
    ranked = rank(bp, business_type)
    if not ranked:
        return None
    wanted = ASKS_BY_ID.get(proposed) or ask_for_target(proposed)
    if wanted:
        for item in ranked[:3]:
            if item.ask.id == wanted.id and item.score >= 0.75 * ranked[0].score:
                return item
    return ranked[0]


# When the rest of a paired question is already known, ask only for what is open:
# "Do you deliver or do people pick up — and which areas?" becomes "Which areas?".
NARROW: dict[tuple[str, str], str] = {
    ("fulfilment", "fulfilment.area"): "area",
    ("contact", "contact.phone"): "phone",
}
LEAD_ONLY: dict[str, dict[str, str]] = {
    "contact": {"en": "Where is {name}? The area and city is enough.",
                "ta_en": "{name} enga irukku? Area, city sonna podhum.",
                "ta": "{name} எங்க இருக்கு? ஏரியா, ஊர் சொன்னா போதும்."},
    "fulfilment": {"en": "Do you deliver, or do people pick up from you?",
                   "ta_en": "Neenga deliver pannuveengalaa, illa customers pickup pannuvaangalaa?",
                   "ta": "நீங்க டெலிவரி பண்ணுவீங்களா, இல்ல வாடிக்கையாளர்களே வந்து வாங்குவாங்களா?"},
    "b2b": {"en": "Which kinds of businesses buy from you most?",
            "ta_en": "Endha maadhiri businesses unga kitta adhigama vaanguvaanga?",
            "ta": "எந்த மாதிரி நிறுவனங்கள் அதிகமா வாங்குவாங்க?"},
    "bookings": {"en": "What do people usually book with you, and roughly how long does it take?",
                 "ta_en": "Usual-aa enna book pannuvaanga, evlo neram aagum?",
                 "ta": "வழக்கமா என்ன புக் பண்ணுவாங்க, எவ்வளவு நேரம் ஆகும்?"},
}


CONVERSION_CHANNEL = {
    "en": "When people order for {modes}, how do they reach you — WhatsApp, a call, or ordering on your website?",
    "ta_en": "{modes}-ku customers eppadi order pannuvaanga — WhatsApp, call, illa website-la order-aa?",
    "ta": "{modes}-க்கு வாடிக்கையாளர்கள் எப்படி ஆர்டர் பண்ணுவாங்க — வாட்ஸ்அப், கால், இல்ல வெப்சைட்ல ஆர்டர்-ஆ?",
}


def phrase(ask: Ask, bp: BusinessBlueprint, lang: str, *, prof: Profile | None = None) -> str:
    """The question in the owner's language, in the trade's words when it has them.

    Only what is still open is asked: a paired question whose second half is
    already known is narrowed to its first half.
    """
    from platform_core.interview.taxonomy import open_structure, structure_question

    prof = prof or profile(bp)
    name = bp.identity["display_name"].value if "display_name" in bp.identity else "your business"
    things = prof.playbook.noun
    open_parts = [t for t in ask.targets
                  if not resolved(bp, t, importance(t, prof, bp)) and relevant(TARGETS_BY_ID[t], prof, bp)]
    complete = len(open_parts) == len(ask.targets)
    template = ""
    from platform_core.interview.understanding import fulfilment

    modes = [m for m in fulfilment(bp) if m in ("pickup", "delivery")]
    if ask.id == "structure" and open_structure(bp):
        # The owner's own groups, named: "For chicken and mutton, do people choose cuts too?"
        template = "{structure}"
    elif ask.id == "conversion" and modes:
        # They already said people collect or get it delivered; what is still
        # open is how those orders reach them — never "do they order ahead?".
        how = {"en": " or ".join(modes), "ta_en": " / ".join(modes),
               "ta": " / ".join({"pickup": "பிக்கப்", "delivery": "டெலிவரி"}[m] for m in modes)}
        template = CONVERSION_CHANNEL.get(lang, CONVERSION_CHANNEL["en"]).replace("{modes}", how.get(lang, how["en"]))
        template = template[:1].upper() + template[1:]
    elif complete:
        template = phrase_override(prof.playbook, ask.id, lang)
    elif open_parts and open_parts[0] == ask.targets[0]:
        template = phrase_override(prof.playbook, f"{ask.id}.lead", lang) or LEAD_ONLY.get(ask.id, {}).get(lang, "")
    elif open_parts:
        narrow = NARROW.get((ask.id, open_parts[0]))
        if narrow:
            ask = ASKS_BY_ID[narrow]
    template = template or ask.text.get(lang) or ask.text["en"]
    structure = ""
    if "{structure}" in template:
        structure = structure_question(bp, lang if lang != "ta" else "ta") or (
            f"Which {things} do people ask for most?" if lang == "en"
            else f"Customers adhigama endha {things} kepaanga?")
    return template.format(name=name, things=things, structure=structure,
                           material=material_word(prof.playbook.offer_kind, lang)).strip()


# What an owner already has that lists what they sell, in their words.
_MATERIAL = {
    "menu_item": {"en": "a menu", "ta_en": "menu", "ta": "மெனு"},
    "plan": {"en": "a timetable or price list", "ta_en": "timetable / price list", "ta": "நேர அட்டவணை / விலைப்பட்டியல்"},
    "class": {"en": "a timetable or price list", "ta_en": "timetable / price list", "ta": "நேர அட்டவணை / விலைப்பட்டியல்"},
    "property_project": {"en": "a brochure", "ta_en": "brochure", "ta": "ப்ரோஷர்"},
    "service": {"en": "a price list or brochure", "ta_en": "price list / brochure", "ta": "விலைப்பட்டியல் / ப்ரோஷர்"},
    "package": {"en": "a price list or brochure", "ta_en": "price list / brochure", "ta": "விலைப்பட்டியல் / ப்ரோஷர்"},
}
_DEFAULT_MATERIAL = {"en": "a price list or brochure", "ta_en": "price list / brochure",
                     "ta": "விலைப்பட்டியல் / ப்ரோஷர்"}


def material_word(offer_kind: str, lang: str) -> str:
    words = _MATERIAL.get(offer_kind, _DEFAULT_MATERIAL)
    return words.get(lang) or words["en"]


def record(bp: BusinessBlueprint, ask: Ask) -> None:
    """Remember that this ask was put to the owner, by concept."""
    from platform_core.interview.models import TargetState

    turn = bp.turn_count + 1
    bp.asks = (bp.asks + [AskRecord(ask=ask.id, targets=list(ask.targets), turn=turn)])[-60:]
    for target_id in ask.targets:
        state = bp.discovery.setdefault(target_id, TargetState())
        state.asked += 1
        state.last_asked_turn = turn
        if state.status == "open":
            state.status = "asked"
    bp.last_asked_target = ask.targets[0]


def last_ask(bp: BusinessBlueprint) -> Ask | None:
    return ASKS_BY_ID.get(bp.asks[-1].ask) if bp.asks else None


# ------------------------------------------------------------- what Locah says

CHECKPOINT = {
    "en": "I've got enough to make a strong first version.{so_far} Build it now, or keep refining — "
          "a little more detail only makes it more yours.",
    "ta_en": "Oru nalla first version build panna podhumaana details irukku.{so_far} Ippove build pannalaam, "
             "illa innum konjam refine pannalaam — innum details sonna innum personal-aa irukkum.{more}",
    "ta": "நல்ல முதல் வெர்ஷன் உருவாக்க போதுமான தகவல் இருக்கு.{so_far} இப்போவே உருவாக்கலாம், இல்ல இன்னும் "
          "கொஞ்சம் சேர்க்கலாம்.{more}",
}
# Said at the checkpoint when the pictures question was not reached: the owner
# learns the site will have pictures, and that theirs will replace them.
PICTURES = {
    "en": " I'll create draft pictures for the site — attach your own photos or {material} any time "
          "and they'll take their place.",
    "ta_en": " Website-ku naan draft pictures ready pannuren — unga photos illa {material} eppo "
             "venaalum attach pannunga, adhu replace aagum.",
    "ta": " வெப்சைட்டுக்கு நான் மாதிரி படங்கள் ரெடி பண்றேன் — உங்க படங்கள் அல்லது {material} எப்போ "
          "வேணாலும் இணைக்கலாம்.",
}
MORE = {
    "en": " If you like, I can also ask about {items}.",
    "ta_en": " Venumna {items} pathiyum kekkalaam.",
    "ta": " வேணும்னா {items} பத்தியும் கேக்கலாம்.",
}
SO_FAR = {"en": " So far: {text}.", "ta_en": " Ippo varaikkum: {text}.", "ta": " இதுவரை: {text}."}
AFTER_READY = {
    "en": "Added. Build whenever you're ready — or tell me anything else you'd like on the site.",
    "ta_en": "Seri, add pannitten. Ready-na build pannalaam — vera edhaavadhu venumnaalum sollunga.",
    "ta": "சேர்த்துட்டேன். தயாரா இருந்தா உருவாக்கலாம் — வேற ஏதாவது வேணும்னாலும் சொல்லுங்க.",
}
NOTHING_LEFT = {
    "en": "That's everything I'd want to know — build whenever you're ready.",
    "ta_en": "Enakku therinjukka vendiyadhu ellaam therinjiduchu — ready-na build pannalaam.",
    "ta": "தெரிஞ்சுக்க வேண்டியது எல்லாம் தெரிஞ்சுடுச்சு — தயாரா இருந்தா உருவாக்கலாம்.",
}
TO_CONFIRM = {
    "en": "Here's what I'll build from — have a look, change anything that's off, then press Build my website.",
    "ta_en": "Idhai vechu dhaan build pannuven — oru thadava paarunga, thappu irundha maathunga, apram Build "
             "my website press pannunga.",
    "ta": "இதை வைத்துதான் உருவாக்குவேன் — ஒருமுறை பாருங்க, தவறு இருந்தா மாத்துங்க, பிறகு உருவாக்கு அழுத்துங்க.",
}
NEED_ONE_MORE = {
    "en": "Happy to build — I just need one thing first so the site isn't empty. ",
    "ta_en": "Build pannalaam — site empty-aa irukka koodaadhu-nu oru vishayam mattum venum. ",
    "ta": "உருவாக்கலாம் — ஒரு விஷயம் மட்டும் முதல்ல வேணும். ",
}


def checkpoint_message(bp: BusinessBlueprint, lang: str, worth: list[str]) -> str:
    from platform_core.interview.understanding import read_back, synthesis

    so_far = ""
    if lang == "en":
        said = read_back(bp, "checkpoint")
        so_far = f" {said}" if said else ""
    if not so_far:
        text = synthesis(bp, lang)
        so_far = SO_FAR[lang].format(text=text) if text else ""
    items = list(worth[:3])
    joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1] if items else ""
    text = CHECKPOINT[lang].format(so_far=so_far, more=MORE[lang].format(items=joined) if joined else "")
    photos = bp.discovery.get("media.photos")
    if bp.visual_consent == "unknown" and not (photos and photos.asked):
        from platform_core.interview.playbooks import playbook_for

        text += PICTURES[lang].format(material=material_word(playbook_for(bp).offer_kind, lang))
    return text


def so_far_line(bp: BusinessBlueprint, lang: str, *, first_shape: bool = False) -> str:
    """The "here's what I understand" line: the shape of the business the first
    time, a short "so far" after that."""
    from platform_core.interview.understanding import read_back, synthesis

    if lang == "en":
        said = str(read_back(bp, "shape" if first_shape else "so_far"))
        if said:
            return said
    text = synthesis(bp, lang)
    return SO_FAR[lang].format(text=text).strip() if text else ""


# After the website exists: the conversation keeps going, and changes it.
UPDATED = {
    "en": "I've updated your website with that — have a look.",
    "ta_en": "Website-la update pannitten — oru thadava paarunga.",
    "ta": "வெப்சைட்டில் சேர்த்துட்டேன் — ஒருமுறை பாருங்க.",
}
HELP_EDIT = {
    "en": "Tell me what to change — for example “make it warmer”, “don't show prices”, “put delivery "
          "higher”, or “we also sell prawns”.",
    "ta_en": "Enna maathanum-nu sollunga — “konjam warm-aa pannunga”, “price kaatta vendaam”, maadhiri.",
    "ta": "என்ன மாத்தணும்னு சொல்லுங்க — “விலை காட்ட வேண்டாம்” மாதிரி.",
}

# Asked once, when the business was started by talking and has no name yet.
NAME_QUESTION = {
    "en": "What's the {noun} called? That's the name the website will use.",
    "ta_en": "{noun}-oda per enna? Website-la adha dhaan podanum.",
    "ta": "உங்க {noun} பெயர் என்ன? வெப்சைட்ல அதைத்தான் போடுவோம்.",
}
