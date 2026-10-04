"""Reading an owner's answer without a model — and checking what a model read.

Two jobs, one set of rules:

1. **Fallback understanding.** When the model cannot be reached, an answer is
   read in the light of the question it answers. "All india" after "which
   areas do you deliver to?" is a delivery area — never opening hours. The old
   fallback filed it under whichever question ranked first, which is how a
   gym's equipment list became "What a customer does".
2. **Semantic validation.** Whatever the model extracts must be the right
   *kind* of thing for the slot it claims: hours are a schedule, a phone
   number has digits, a customer action is something a customer does (order,
   book, call, WhatsApp…), an offering is something sold — not "contact
   section", which is website content.

Everything here is deterministic and quotation-based: it never invents a
fact, it only recognises what the owner's own words already say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ------------------------------------------------------------------ actions

# What a customer can do, canonical. Labels are what the side panel and the
# website say; ids are what the rest of the code compares.
ACTION_LABELS: dict[str, str] = {
    "order_online": "Order online",
    "order_whatsapp": "Order on WhatsApp",
    "order_call": "Call to order",
    "book_online": "Book online",
    "book_whatsapp": "Book on WhatsApp",
    "book_call": "Call to book",
    "book_table": "Book a table",
    "book_trial": "Book a trial",
    "book_site_visit": "Book a site visit",
    "book_consultation": "Book a consultation",
    "check_dates": "Check dates",
    "request_quote": "Ask for a quote",
    "enquire": "Send an enquiry",
    "call": "Call",
    "whatsapp": "WhatsApp",
    "visit": "Visit in person",
    "join": "Sign up",
    "subscribe": "Subscribe",
    "donate": "Donate",
    "get_app": "Get the app",
    "browse": "Browse the range",
}

# Not "purchase": "Purchase teams send us an RFQ" names the buyer, not an order.
_ORDER = re.compile(r"\b(order\w*|buy|buying|pre-?order\w*|cart|checkout|add to cart)\b", re.I)
_BOOK = re.compile(r"\b(book\w*|reserv\w*|appointment\w*|slot\w*|schedul\w*)\b", re.I)
_TABLE = re.compile(r"\btables?\b", re.I)
_TRIAL = re.compile(r"\b(trial|demo (?:class|session)|free (?:class|session)|assessment session|first session)\b", re.I)
_CONSULT = re.compile(r"\b(consultations?|consult)\b", re.I)
# "then we visit the site" is the business going out, not a customer visiting.
_WE_VISIT = re.compile(r"\b(?:we|our (?:team|staff|engineers?))\s+(?:\w+\s+)?visit", re.I)
_SITE_VISIT = re.compile(r"\bsite visits?\b", re.I)
_DATES = re.compile(r"\b(check (?:the )?(?:dates?|availability)|date availability|available dates?)\b", re.I)
_QUOTE = re.compile(r"\b(quot\w*|estimate\w*|rfq|price (?:request|enquiry)|ask (?:for )?(?:the )?(?:price|rates?))\b", re.I)
_ENQUIRE = re.compile(r"\b(enquir\w*|inquir\w*|requirement\w*|get in touch|contact us|reach (?:out|us))\b", re.I)
_CALL = re.compile(r"\b(call\w*|phone|ring|dial)\b", re.I)
_TO_ORDER = re.compile(
    r"\b(?:made|cut|cooked|baked|prepared|stitched|tailored|built|fresh|freshly|packed)\s+(?:fresh\s+|freshly\s+)?"
    r"to\s+order\b", re.I)
_WHATSAPP = re.compile(r"\b(whats\s?app\w*|wa\b|dm\b|message us|text us)|வாட்ஸ்\s?(?:அப்|ஆப்)", re.I)
_ONLINE = re.compile(r"\b(online|website|site|app|internet|on the web)\b", re.I)
_TAMIL_SCRIPT = re.compile(r"[஀-௿]")
_TANGLISH = re.compile(
    r"\b(pannu\w*|panr\w*|pann\w*|illa|irukk\w*|iruk\w*|venum|vendaam|venaam|sollunga|seri|romba|konjam|enna|"
    r"eppadi|enga|naan|neenga|ellaam|ellam|kitta|munnaadi|dhaan|aamaa|vaangu\w*|varuvaanga|podhum|pathi|"
    r"pes(?:a|u|al|un)\w*|vech\w*|vach\w*|naanga|unga|kudunga|vaanga|mudiyum\w*|theriyum\w*|saapadu|sappadu|"
    r"kadai|nalla|ungaluku|enakku|neraya)\b", re.I)


_TA_POSTPOSITION = re.compile(r"\b\w+\s*-?\s*(?:la|le|ku|kku)\b|\b(?:varai\w*|rendum|nadath\w*|kaalai|raathiri)\b", re.I)


def has_tamil_words(text: str) -> bool:
    """Any Tamil at all — a word, a postposition ("Anna Nagar la"), or the script."""
    return bool(_TANGLISH.search(text or "") or _TA_POSTPOSITION.search(text or "") or _TAMIL_SCRIPT.search(text or ""))


def language_of(text: str) -> str:
    """How the owner writes: Tamil script, Tamil in English letters mixed with English, or English."""
    text = text or ""
    letters = [c for c in text if c.isalpha()]
    tamil = sum(1 for c in letters if _TAMIL_SCRIPT.match(c))
    if letters and tamil / len(letters) > 0.4:
        return "ta"
    if len(_TANGLISH.findall(text)) >= 2 or tamil:
        return "ta_en"
    return "en"


# ------------------------------------------------------------------ "can we talk in Tamil?"
# A request to change the conversation's language is about the conversation,
# not the business: it must switch the reply language and keep the question
# that was asked, never be read as an answer to it.
_LANG_NAME = {
    # "தமிழில்" drops the virama before the locative (தமிழ + ில்), so the
    # script name is matched with or without it.
    "ta": r"(?:tamil|tamizh|thamizh|thamil|தமிழ்?)",
    "en": r"(?:english|inglish|ingleesh|ஆங்கில(?:த்தில்|ம்)?|இங்கிலீஷ்)",
}
# The Tamil postposition "in" (Tamil la / தமிழ்ல), English "in", and the verbs a
# person uses to ask (talk, speak, reply, continue — pesalama, pesunga, பேசலாமா).
_IN_AFTER = r"(?:\s*-?\s*(?:la|le|lae|lay|lah|laye|il|ile|ல|லே|லயே|லேயே|ில்|ிலே|ில)\b|ல|லே|லயே|ில்|ிலே)"
# Tamil-script words are matched with the script's range, not \w: Python's \w
# leaves out Tamil vowel signs, which would cut "பேசலாமா" in half.
_VERB = re.compile(
    r"(\b(?:pes\w*|pesu\w*|speak\w*|talk\w*|reply\w*|respond\w*|answer\w*|continu\w*|chat\w*|write\w*|"
    # pann…/panal…/panun… ("continue pannunga", "panalam") — never "paneer" or "panel".
    r"switch\w*|change\w*|use|mathi\w*|maathi\w*|maatru\w*|thodar\w*|sollu\w*|pan(?:n|al|un)\w*|kelu\w*|"
    r"please|pls|plz)\b|(?:பேச|பேசு|தொடர|மாற்ற|மாத்த|சொல்லு|பண்ணு|பதில்)[஀-௿]*)",
    re.I,
)
# Words that carry no business content in a language request.
_FILLER = re.compile(
    r"\b(?:can|could|shall|may|we|i|you|u|let|lets|let's|us|now|from|here|on|onwards|the|a|an|in|to|with|me|"
    r"ok|okay|seri|sir|madam|mam|bro|anna|akka|ji|ah|aa|ma|da|dei|thank|thanks|nandri|yes|no|only|just|also|"
    r"please|pls|plz|more|better|instead|language|mozhi|bhashai|neenga|naama|nambo|nama|ini|ippo|ippa|"
    r"inime|irundhu|script|letters|formal|pure|properly)\b",
    re.I,
)
_NOT_A_REQUEST = re.compile(r"\b(?:tamil|tamizh|thamizh)\s+(?:nadu|nad|food|meals?|movies?|songs?|cuisine|style|"
                            r"brahmin|people|wedding|bride|books?|news|class(?:es)?|tuition)\b", re.I)


def without_language_request(text: str) -> str:
    """The message minus the sentence that asked to switch language, so that
    "Tamil la pesalama? Naan salon vechirukken" is read as "Naan salon
    vechirukken" — the request is about the conversation, not the business."""
    parts = re.split(r"(?<=[.?!।])\s+", (text or "").strip())
    kept = [p for p in parts if language_request(p) is None]
    return " ".join(kept).strip() or (text or "").strip()


def language_request(text: str) -> tuple[str, bool] | None:
    """(target, only) when the owner asks to talk in another language.

    `target` is how to reply: "ta" (Tamil script) when they write Tamil
    script or ask for script / formal Tamil; "ta_en" (Tamil in English
    letters, as they wrote) for a Tanglish request; "en" for English. `only`
    says the message asked nothing else, so it answers no question. Reads the
    shape of a request — a language named with "in" (Tamil la, தமிழ்ல, in
    English) or with a verb (talk, pesalama, continue) — not one fixed phrase;
    "we sell Tamil meals" or "Tamil Nadu" are not requests.
    """
    raw = " ".join((text or "").split())
    if not raw or len(raw) > 240:
        return None
    lowered = raw.casefold()
    found: list[tuple[str, re.Match[str]]] = []
    for target, name in _LANG_NAME.items():
        for m in re.finditer(rf"(?P<pre>\bin\s+)?(?P<name>{name})(?P<post>{_IN_AFTER})?", lowered, re.I):
            found.append((target, m))
    if not found:
        return None
    target, match = found[-1]  # "not English, Tamil la" — the last one named wins
    if target == "ta" and _NOT_A_REQUEST.search(lowered) and not _VERB.search(lowered):
        return None
    # "in Tamil" / "Tamil la" / "தமிழில்" — never the "il" that ends "tamil" itself.
    has_in = bool(match.group("pre") or match.group("post")) or match.group("name").endswith("த்தில்")
    words = re.findall(r"[\w஀-௿]+", lowered)
    if not (has_in or _VERB.search(lowered) or len(words) <= 3):
        return None
    # What is left once the language, the verbs and the politeness are gone.
    rest = lowered
    for _, m in found:
        rest = rest.replace(m.group(0), " ")
    rest = _VERB.sub(" ", rest)
    rest = _FILLER.sub(" ", rest)
    content = re.findall(r"[a-z஀-௿]{3,}", rest)
    only = not content
    # With anything else in the message, it is a request only when it is plainly
    # one — the language with "in" AND a verb ("Tamil la pesalama? Naan salon
    # vechirukken"). "Our customers are mostly Tamil speaking" and "classes in
    # Tamil" are facts about the business, not a change of language.
    if not only and not (has_in and _VERB.search(lowered)):
        return None
    if target == "ta":
        script = sum(1 for c in raw if _TAMIL_SCRIPT.match(c))
        letters = sum(1 for c in raw if c.isalpha())
        wants_script = bool(re.search(r"\b(script|letters|formal|pure|ezhuthu|எழுத்து)\b", lowered))
        target = "ta" if wants_script or (letters and script / letters > 0.4) else "ta_en"
    return target, only
_VISIT = re.compile(r"\b(visit\w*|walk[- ]?in\w*|walk into|come (?:to|over)|drop by|showroom|in person|at the (?:shop|store|counter))\b", re.I)
_JOIN = re.compile(r"\b(join\w*|enrol\w*|enroll\w*|admission\w*|sign(?:ing)? up|register\w*|membership\w*)\b", re.I)
_SUBSCRIBE = re.compile(r"\b(subscri\w*)\b", re.I)
_DONATE = re.compile(r"\b(donat\w*|contribut\w*|sponsor\w*)\b", re.I)
_APP = re.compile(r"\b(download|install)\w*\b.{0,20}\bapp\b|\bget the app\b", re.I)
_BROWSE = re.compile(
    r"\b(view|see|browse|look (?:at|through)|check out|explore)\b.{0,24}\b(products?|menu|catalogue|catalog|"
    r"collections?|range|items|dishes|work|portfolio|gallery|projects?|services|designs?|photos)\b", re.I)
# Tamil / Tanglish verbs for the same things.
# "vaanguvom" / "வாங்குவோம்" is the business taking (payment), not customers buying.
_TA_ORDER = re.compile(r"ஆர்டர்|order\s*pann|vaangu(?!vom|rom|ren|girom|kirom)|வாங்கு(?!வோம்|றோம்|கிறோம்)", re.I)
_TA_BOOK = re.compile(r"புக்|முன்பதிவு|அப்பாயிண்ட்மென்ட்|book\s*pann", re.I)
_TA_CALL = re.compile(r"கால்|call\s*pann|phone\s*pann", re.I)

_NEGATION = re.compile(r"\b(no|not|don'?t|do not|never|without|can'?t|cannot|won'?t)\b", re.I)


def _negated(text: str, match: re.Match[str]) -> bool:
    before = text[max(0, match.start() - 22): match.start()]
    return bool(_NEGATION.search(before))


def _find(pattern: re.Pattern[str], text: str) -> bool:
    return any(not _negated(text, m) for m in pattern.finditer(text))


def _clause_actions(text: str) -> list[str]:
    """Actions in one clause: a channel word belongs to the verb beside it."""
    found: list[str] = []
    # "cut fresh to order", "made to order" describe the product, not how people buy.
    text = _TO_ORDER.sub(" ", text)

    def add(action: str) -> None:
        if action not in found:
            found.append(action)

    whatsapp = _find(_WHATSAPP, text)
    call = _find(_CALL, text) or bool(_TA_CALL.search(text))
    online = _find(_ONLINE, text)
    # In "UPI, cash rendum vaangu…" the verb is about money, not ordering.
    ordering = _find(_ORDER, text) or (bool(_TA_ORDER.search(text)) and not payment_methods(text))
    booking = _find(_BOOK, text) or bool(_TA_BOOK.search(text))
    site_visit = _find(_SITE_VISIT, text)
    if site_visit:
        add("book_site_visit")
    if booking and _find(_TABLE, text):
        add("book_table")
    if _find(_TRIAL, text):
        add("book_trial")
    if _find(_CONSULT, text):
        add("book_consultation")
    if booking and not {"book_table", "book_site_visit", "book_trial", "book_consultation"} & set(found):
        if whatsapp:
            add("book_whatsapp")
        if call:
            add("book_call")
        if online or not (whatsapp or call):
            add("book_online")
    if ordering:
        if whatsapp:
            add("order_whatsapp")
        if call:
            add("order_call")
        if online or not (whatsapp or call):
            add("order_online")
    if _find(_DATES, text):
        add("check_dates")
    if _find(_QUOTE, text):
        add("request_quote")
    if _find(_ENQUIRE, text):
        add("enquire")
    if _find(_JOIN, text):
        add("join")
    if _find(_SUBSCRIBE, text):
        add("subscribe")
    if _find(_DONATE, text):
        add("donate")
    if _APP.search(text):
        add("get_app")
    if _find(_BROWSE, text):
        add("browse")
    if _find(_VISIT, text) and not site_visit and not _WE_VISIT.search(text):
        add("visit")
    # A channel named on its own is an action too ("call or WhatsApp us").
    if whatsapp and not {"order_whatsapp", "book_whatsapp"} & set(found):
        add("whatsapp")
    if call and not {"order_call", "book_call"} & set(found):
        add("call")
    return found


def canonical_actions(text: str) -> list[str]:
    """Customer actions the owner's words name, in a stable order.

    Read clause by clause: in "order equipment, book slots for trainers, call"
    the "call" is its own action, not how the ordering happens.
    """
    text = " ".join((text or "").split())
    found: list[str] = []
    for clause in re.split(r"\s*[,;.!?\n]\s*|\s+then\s+", text):
        for action in _clause_actions(clause):
            if action not in found:
                found.append(action)
    return found


def action_labels(actions: list[str]) -> list[str]:
    return [ACTION_LABELS[a] for a in actions if a in ACTION_LABELS]


def action_sentences(text: str) -> str:
    """Only the owner's sentences that say what a customer does, verbatim.

    Kept as the customer-actions evidence instead of a whole opening
    paragraph. Contiguous when possible, so it remains a real quotation.
    """
    sentences = [s.strip() for s in re.findall(r"[^.!?\n]+[.!?]?", " ".join((text or "").split()))]
    hits = [s for s in sentences if s and canonical_actions(s)]
    if len(hits) == 1:
        return str(hits[0])
    joined = " ".join(hits)
    return joined if joined in " ".join((text or "").split()) else (hits[0] if hits else "")


# --------------------------------------------------------- content & offers

# Parts of a website, not things a business sells or customers do.
_CONTENT = re.compile(
    r"\b(contact(?: us)?(?: section| page| details| form)?|about (?:us|section|page)|gallery|"
    r"testimonials?|reviews? section|faqs?|home ?page|landing page|map|location section|"
    r"blog|footer|header|banner|section|page)\b", re.I)
_VAGUE = re.compile(r"\b(everything|all (?:types|kinds|sorts)|and more|etc\.?|stuff|things)\b", re.I)
_VERB_START = re.compile(
    r"^(?:then\s+|and\s+|they\s+|people\s+|customers\s+)*(?:select|choose|pick|see|add|start|track|view|get|"
    r"give|send|come|go|make|take|call|book|order|visit|check|enter|type|click|tap|scroll|login|log in|"
    r"sign|pay|must|should|can|will|allow)\b", re.I)


def content_wishes(text: str) -> list[str]:
    """Website sections the owner named ("a contact section", "gallery")."""
    wishes: list[str] = []
    for part in split_list(text):
        if _CONTENT.search(part) and not _find(_ORDER, part) and not _find(_BOOK, part):
            label = re.sub(r"\b(a|an|the|our|my)\b", "", part, flags=re.I)
            label = " ".join(label.split()).strip(" .")
            if label and label.casefold() not in {w.casefold() for w in wishes}:
                wishes.append(label[:1].upper() + label[1:])
    return wishes[:6]


def split_list(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|\n|\band\b|&|\bplus\b|/)\s*", " ".join((text or "").split()), flags=re.I)
    return [p.strip(" .-") for p in parts if p.strip(" .-")]


_GROUP_ITEMS = re.compile(r"(?:^|[.;\n]\s*)([A-Za-z][A-Za-z &']{1,30}?)\s*[-:–]\s*([^.;\n]+)")


def group_items(text: str) -> list[tuple[str, list[str]]]:
    """ "Chicken - curry cut, boneless. Mutton - chops" -> [(Chicken, [...]), (Mutton, [...])]."""
    out: list[tuple[str, list[str]]] = []
    for match in _GROUP_ITEMS.finditer(" ".join((text or "").split())):
        group = match.group(1).strip()
        items = [i for i in split_list(match.group(2)) if 1 < len(i) <= 40]
        if items and len(group.split()) <= 3:
            out.append((group[:1].upper() + group[1:], items[:12]))
    return out[:12]


_OFFER_STATEMENT = re.compile(
    r"\b(?:(?:we|i)\s+(?:also\s+|mainly\s+|mostly\s+|only\s+)?(?:sell|make|offer|serve|supply|provide|stock|"
    r"cook|bake|keep|have|do)|(?:we(?:'re| are)\s+)?(?:known|famous)\s+for(?:\s+our)?|"
    r"speciali[sz](?:e|es|ing)\s+in|our\s+special(?:ity|ty|ities)\s+(?:is|are))\s+([^.;!?\n]+)", re.I)


# "…a strength gym in Velachery — powerlifting, strength classes and personal
# training." / "Mostly monthly memberships, personal training and group classes."
_OFFER_LIST = re.compile(
    r"(?:\bis an? [^—–.;!?\n]{2,60}?\s+[—–-]\s+|(?:^|[.!?]\s+)(?:mostly|mainly|primarily)\s+)([^.;!?\n]+)", re.I)


_HOW_ONLY = re.compile(
    r"(?:dine[- ]?in|eat in|take ?away|takeaway|self[- ]?pick ?up|pick ?ups?|home delivery|door ?step delivery|"
    r"deliver(?:y|ies)?|parcel|courier|shipping|cash|upi|g ?pay|cards?|online payments?|cod|cash on delivery)"
    r"(?:\s+(?:only|too|also|available))?", re.I)
_LIST_ENDS = re.compile(
    r"\b(?:dine[- ]?in|eat in|take ?away|takeaway|pick ?up|home delivery|deliver\w*|door ?step|parcel|"
    r"open\w*|closed|timings?|from \d|\d{1,2}\s*(?:am|pm)\b|we (?:are|'re) (?:in|at|on))", re.I)


def offer_statement(text: str) -> list[str]:
    """What an owner says they sell, from "We sell chicken, mutton and fish."."""
    names: list[str] = []
    flat = " ".join((text or "").split())
    matches = list(_OFFER_STATEMENT.finditer(flat)) or list(_OFFER_LIST.finditer(flat))
    for match in matches:
        # "we sell coffee, pasta and cakes, dine-in, pickup and delivery, open
        # 9 to 10" — the list ends where how it reaches people or the hours
        # start ("dine-in" must not split at "in" into an item called "Dine").
        listed = match.group(1)
        stop = _LIST_ENDS.search(listed)
        listed = listed[:stop.start()] if stop else listed
        clause = re.split(r"\b(?:to|for|in|at|from|since|with|which|who|and (?:we|people|customers))\b",
                          listed, maxsplit=1, flags=re.I)[0]
        clause = re.sub(r"\s+(?:now|too|also)\s*$", "", clause, flags=re.I)
        for name in offering_names(clause):
            if name.casefold() not in {n.casefold() for n in names} and len(name.split()) <= 5:
                names.append(name)
    return names[:12]


# Tamil / Tanglish words that *say* "we have it / we do it / it's available"
# around a list, never part of a name: "Haircut, facial and bridal makeup
# iruku" lists three services, "enga kitta dosa, idli iruku" two dishes.
_TA_HAVE_TAIL = re.compile(
    r"(?:\s+(?:iruk+[iu]\w*|irukk?a\w*|irukk?om|pan+(?:u|r)?(?:om|vom)|panrom|pannuvom|kudu(?:k+)?(?:urom|rom|pom)|"
    r"sei(?:y|v)\w*om|venum|vendum|dhaan|thaan|mattum|ellam|kidaik+u\w*|available)"
    r"|\s*(?:இருக்கு\w*|இருக்கும்|உண்டு|செய்வோம்|செய்கிறோம்|பண்றோம்|கொடுக்கிறோம்|தான்|மட்டும்|கிடைக்கும்))+[\s.!]*$",
    re.I)
_TA_HAVE_HEAD = re.compile(r"^(?:enga\s*kitta|namma\s*kitta|engalukku|enga\s+(?:kadai|shop)\s*la|எங்க(?:ிட்ட|\s*கிட்ட))\s+",
                           re.I)


def offering_names(text: str) -> list[str]:
    """Noun phrases that name things sold, from a list answer.

    Website sections and customer actions are removed: "GYm equipment,
    available trainers, dumbells, contact section" names two things sold,
    one service and one website section.
    """
    names: list[str] = []
    for part in split_list(text):
        if _CONTENT.search(part) and len(part.split()) <= 4:
            continue
        # "Select meat and then select kg" describes how people buy, not what is sold.
        if _VERB_START.match(part):
            continue
        if canonical_actions(part) and not re.search(r"\b(trainers?|coaching|classes|sessions)\b", part, re.I):
            continue
        # "dine-in", "pickup", "UPI", "open 9 to 10" are how and when, not what
        # is sold ("Silk saree collection" still is).
        if _HOW_ONLY.fullmatch(part.strip()) or (looks_like_hours(part) and len(part.split()) <= 6):
            continue
        if _VAGUE.fullmatch(part.strip()) or len(part) > 60 or not re.search(r"[A-Za-z஀-௿]", part):
            continue
        part = re.sub(r"^(?:we (?:sell|make|offer|do|have|provide)|mainly|mostly|also)\s+", "", part, flags=re.I)
        part = re.sub(r"^(?:available|our|the|all)\s+", "", part, flags=re.I).strip()
        part = _TA_HAVE_HEAD.sub("", _TA_HAVE_TAIL.sub("", " " + part).strip()).strip(" .-")
        if part and part.casefold() not in {n.casefold() for n in names}:
            names.append(part[:1].upper() + part[1:])
    return names[:12]


# ----------------------------------------------------- fulfilment & payment

_DELIVERY = re.compile(r"\b(deliver\w*|home delivery|door ?step|door delivery|send it|bring it)\b|டெலிவரி", re.I)
_PICKUP = re.compile(r"\b(pick ?up|collect\w*|take ?away|takeaway|carry out)\b|பிக்கப்", re.I)
_SHIPPING = re.compile(r"\b(ship\w*|courier\w*|all over india|pan[- ]india|across india|all india|nationwide|post(?:al)?)\b", re.I)
_DINE_IN = re.compile(r"\b(dine[- ]?in|eat in|sit[- ]down|seating)\b", re.I)
_ON_SITE = re.compile(r"\b(we come to|at your (?:home|place|site|venue)|on[- ]site|doorstep service|home visits?|visit your)\b", re.I)


def fulfilment_modes(text: str) -> list[str]:
    # "Cash on delivery" is how people pay, not how orders reach them.
    text = re.sub(r"\b(?:cash|pay(?:ment)?)\s+on\s+delivery\b|\bcod\b", " ", " ".join((text or "").split()),
                  flags=re.I)
    modes: list[str] = []
    for mode, pattern in (("delivery", _DELIVERY), ("pickup", _PICKUP), ("shipping", _SHIPPING),
                          ("dine_in", _DINE_IN), ("on_site", _ON_SITE)):
        if _find(pattern, text):
            modes.append(mode)
    if re.search(r"\bboth\b", text, re.I) and not modes:
        modes = ["delivery", "pickup"]
    if "shipping" in modes and "delivery" not in modes and re.search(r"\ball (?:over )?india\b", text, re.I):
        modes.insert(0, "delivery")
    return modes


def service_area(text: str) -> str:
    """ "We deliver around Nookampalayam and Perumbakkam" -> the places."""
    raw = " ".join((text or "").split())
    raw = re.sub(r"\b(?:by|through|via)\s+(?:courier|post|parcel)\w*", "", raw, flags=re.I)
    raw = re.sub(r"^\s*(?:yes[,.]?\s*)?(?:we\s+)?(?:only\s+)?(?:deliver|ship|send|courier|serve|cover)\w*\s*", "",
                 raw, flags=re.I)
    raw = re.sub(r"^(?:to|in|around|within|across|all over|throughout|anywhere in)\s+", "", raw.strip(), flags=re.I)
    # "around X and Y, people can also pick up from the shop" — the places only.
    raw = re.split(r"[.;]\s|,\s*(?=(?:people|customers|we|they|but|though|also|and (?:people|we|they)|pick))",
                   raw, maxsplit=1, flags=re.I)[0]
    raw = raw.strip(" .,")
    if not raw or len(raw) > 80 or _HOURS.search(raw) or re.fullmatch(r"(?:yes|no|both|only)", raw, re.I):
        return ""
    # "You can pay by UPI or cash" in reply to "which areas?" is about paying.
    if payment_methods(raw) or phone_number(raw) or re.search(r"\b(pay|payment|price|cost)\b", raw, re.I):
        return ""
    return raw[:1].upper() + raw[1:]


# "…we deliver around Anna Nagar and Mogappair" — a place named right after a
# delivery verb. Used for what the owner volunteers; an answer to "where do
# you deliver?" is read whole by service_area.
_AREA_SAID = re.compile(
    r"\b(?:deliver\w*|ship\w*|courier\w*|serve|cover)\s+(?:only\s+)?(?:to|around|in|within|across|all over|"
    r"throughout|anywhere in)\s+(?P<area>[^.;!?]+)", re.I)


def service_area_said(text: str) -> str:
    """The delivery area when the owner names one after a delivery verb, else ""."""
    found = _AREA_SAID.search(" ".join((text or "").split()))
    if not found:
        return ""
    area = re.split(r",\s*(?=(?:people|customers|we|they|but|though|also|open|and (?:people|we|they)|pick|dine))"
                    r"|\s+(?:and|but)\s+(?:we|people|customers|they)\b", found.group("area"), maxsplit=1,
                    flags=re.I)[0].strip(" .,")
    if not area or len(area) > 80 or _HOURS.search(area) or re.search(r"\b\d+\s*(?:km|kms|minutes|mins)\b", area, re.I) \
            and len(area.split()) > 6:
        return ""
    return area[:1].upper() + area[1:]


_PAYMENT = (
    (re.compile(r"\bupi\b|gpay|google pay|phone ?pe|paytm|bhim", re.I), "UPI"),
    (re.compile(r"cash on delivery|\bcod\b|pay on delivery", re.I), "Cash on delivery"),
    (re.compile(r"\bcash\b", re.I), "Cash"),
    (re.compile(r"\b(?:credit |debit )?cards?\b", re.I), "Card"),
    (re.compile(r"bank transfer|neft|imps|rtgs", re.I), "Bank transfer"),
    (re.compile(r"\bonline\b|net ?banking|payment link", re.I), "Online"),
)


def payment_methods(text: str) -> list[str]:
    """Ways to pay, in the order the owner named them."""
    hits = [(match.start(), label) for pattern, label in _PAYMENT
            for match in [pattern.search(text or "")] if match]
    found = [label for _, label in sorted(hits)]
    if "Cash on delivery" in found and "Cash" in found:
        found.remove("Cash")
    if re.search(r"\bboth\b", text or "", re.I) and not found:
        found = ["Online", "Cash"]
    return found


def units(text: str) -> str:
    if re.search(r"\b(kg|kgs|kilo\w*|grams?|gm|weight|per kilo)\b|கிலோ", text or "", re.I):
        return "weight"
    if re.search(r"\b(packs?|packets?|jars?|bottles?|boxes?|pieces?|pcs|sizes?|fixed)\b", text or "", re.I):
        return "packs"
    return ""


# ------------------------------------------------- contact, hours, places

_HOURS = re.compile(
    r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\b\d{1,2}[:.]\d{2}\b|\b24\s*(?:x|/|\*)\s*7\b|"
    r"\b24 hours\b|\bround the clock\b|\b(?:morning|evening|noon|midnight)\b.{0,20}\b(?:to|till|until)\b|"
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?s?\b.{0,24}\b(?:\d|closed|holiday)", re.I)
_PHONE = re.compile(r"(?:\+?91[\s-]*)?(?:\d[\s-]*){10}")


def phone_number(text: str) -> str:
    """A ten-digit Indian number (with or without +91) the owner typed, digits only."""
    for match in _PHONE.finditer(text or ""):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 10 and digits[0] in "6789":
            return digits
        if len(digits) == 10 or (len(digits) == 11 and digits.startswith("0")):
            return digits[-10:]
    return ""


def looks_like_hours(text: str) -> bool:
    from platform_core.interview.hours import parse

    if phone_number(text or ""):
        return False
    # "open 9 to 10" has no am/pm but is plainly a schedule.
    return bool(_HOURS.search(text or "")) or parse(text or "") is not None


_ANY_WEEK = {d: [["09:00", "21:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def hours_clause(text: str) -> str:
    """The part of a longer message that gives the hours: "open 9 to 10" from
    "I run Nila Cafe…, dine-in, pickup and delivery, open 9 to 10." Exactly as
    the owner wrote it; empty when no part of it is a schedule."""
    from platform_core.interview.hours import parse

    from platform_core.interview.hours import days_named

    def says_hours(p: str) -> bool:
        if phone_number(p):
            return False
        # "We deliver till 11 pm" is about deliveries, not when the place is open.
        if re.search(r"\bdeliver\w*|\bdelivery\b|\bship\w*", p, re.I) and not re.search(
                r"\b(open\w*|clos\w*|timings?)\b", p, re.I):
            return False
        # A whole schedule, or a change to one ("weekend la 11 varaikum open"
        # reads against any week as a later closing time on two days).
        if parse(p) is not None or parse(p, _ANY_WEEK) is not None:
            return True
        # A correction or a closed day: "on weekends we're open till 11", "closed on Sundays".
        cue = re.search(r"\b(open\w*|clos\w*|timings?|hours?)\b", p, re.I)
        return bool(cue and (re.search(r"\b(?:till|until|to|from|at)\s+\d", p, re.I) or _HOURS.search(p)
                             or (re.search(r"\b(closed|holiday|shut)\b", p, re.I) and days_named(p))))

    parts = [p.strip(" .") for p in re.split(r"[,;.!?]\s*|\s+but\s+", " ".join((text or "").split())) if p.strip(" .")]
    found = [p for p in parts if says_hours(p)]
    if not found:
        return ""
    # Neighbouring parts stay together ("10 am to 9 pm, closed on Sundays").
    first, last = parts.index(found[0]), parts.index(found[-1])
    flat = " ".join((text or "").split())
    start = flat.find(parts[first])
    end = flat.find(parts[last], start) + len(parts[last])
    return flat[start:end] if start >= 0 and end > start else found[0]


_PLACE_WORDS = re.compile(
    r"\b(road|rd|street|st|nagar|colony|layout|main|cross|sector|block|phase|avenue|salai|puram|"
    r"pettai|palayam|pakkam|nadu|city|town|village|district|market|bazaar|complex|mall|tower|floor|"
    r"near|opposite|opp|behind|next to|junction|circle|bypass|highway|chennai|coimbatore|madurai|"
    r"trichy|tiruchirappalli|salem|erode|tirupur|vellore|bengaluru|bangalore|mumbai|delhi|hyderabad|"
    r"pune|kochi|kolkata|pondicherry|puducherry|india)\b", re.I)


def looks_like_place(text: str) -> bool:
    """A place, not a sentence about delivery, a product list or a website part."""
    raw = " ".join((text or "").split()).strip(" .,")
    if not raw or _CONTENT.search(raw) or canonical_actions(raw) or fulfilment_modes(raw):
        return False
    if payment_methods(raw) or looks_like_hours(raw) or units(raw):
        return False
    if re.search(r"\b(we|our|people|customers|sell|make|deliver|equipment|products?|services?)\b", raw, re.I):
        return False
    return bool(_PLACE_WORDS.search(raw)) or len(raw.split()) <= 4


# "Anna Nagar la" / "Anna Nagar-la" — a capitalised place before the Tamil
# "in". Never a language ("Tamil la pesalama?") or an app ("WhatsApp la").
_PLACE_TA = re.compile(r"\b(?P<place>[A-Z][\w'.]*(?:\s+[A-Z][\w'.]*){0,3})\s*-?\s*(?:la|le|il|pakkathula|pakkam)\b")
_NOT_PLACE = re.compile(r"^(?:tamil|english|hindi|tanglish|whatsapp|instagram|facebook|google|website|online|"
                        r"naan|naanga|enga|unga|ippo|adhu|idhu)$", re.I)


def place_ta(text: str) -> str:
    for found in _PLACE_TA.finditer(" ".join((text or "").split())):
        place = found.group("place")
        if _NOT_PLACE.match(place.split()[0]) or business_name(text).casefold() == place.casefold():
            continue
        if looks_like_place(place):
            return place
    return ""


# "coffee, pasta, cakes iruku" — a Tanglish list that ends in "we have it".
_TA_LIST_END = re.compile(
    r"\s+(?:iruk+[iu]\w*|irukk?a\w*|kidaik+u\w*|sell\s+pann\w*|vikkir\w*|virkir\w*|kudukk?ir\w*)\s*$", re.I)
_TA_CLAUSE_VERB = re.compile(
    r"\b(?:naan|naanga|nanga|enga|nadath\w*|vech\w*|vach\w*|pann\w*|open|timing|la|le)\b", re.I)


def ta_offer_list(text: str) -> list[str]:
    """What a Tanglish answer lists as sold: the comma parts that run up to "…iruku"."""
    parts = [p.strip(" .!") for p in re.split(r"\s*,\s*", " ".join((text or "").split()))]
    for i, part in enumerate(parts):
        if not _TA_LIST_END.search(part):
            continue
        listed = [_TA_LIST_END.sub("", part)]
        for before in reversed(parts[:i]):
            item = _TA_HAVE_HEAD.sub("", before)  # "Enga kitta dosa" starts the list with dosa
            if len(item.split()) > 3 or _TA_CLAUSE_VERB.search(item) or fulfilment_modes(item) \
                    or re.search(r"[A-Z]", item[1:]):
                break
            listed.insert(0, item)
            if item != before:
                break
        return offering_names(", ".join(listed))
    return []


def location_text(text: str) -> str:
    """The place in a location answer, with any phone number taken out."""
    raw = " ".join((text or "").split())
    raw = _PHONE.sub(" ", raw)
    raw = re.sub(r"\b(?:and\s+)?(?:the\s+)?(?:number|phone|mobile|whatsapp)\b.*$", "", raw, flags=re.I)
    raw = re.sub(r"^\s*(?:we(?:'re| are)\s+)?(?:located\s+|based\s+)?(?:in|at|near|on)\s+", "", raw, flags=re.I)
    raw = " ".join(raw.split()).strip(" .,;:-")
    if not raw or len(raw) > 100 or not looks_like_place(raw):
        return ""
    if re.fullmatch(r"(?:yes|no|fixed|both|only deliver|deliver|all india|all over india)", raw, re.I):
        return ""
    return raw


# ------------------------------------------------------------ the name

# "It's called Grit Barbell Club", "the shop's name is Ishant Proteins".
_NAME_SAID = re.compile(
    r"\b(?:called|named|name is|name's|naming it)\s+[\"“']?(?P<name>[^\"”.,;!?\n]{2,70})", re.I)
# "Grit Barbell Club is a strength gym…", "We are Ishant Proteins, a meat shop".
_NAME_LEADS = re.compile(
    r"^\s*(?:(?i:we are|we're|this is|i run|we run|i own|we own|i'm from|we're from)\s+)?"
    r"(?P<name>(?:[A-Z0-9][\w&'’.-]*)(?:\s+(?:&\s+|of\s+|and\s+)?[A-Z0-9][\w&'’.-]*){0,5})"
    r"(?=\s*(?:,|\s+is\s+an?\b|\s+is\s+the\b|\s+are\s+an?\b|\s+—|\s+-\s|"
    r"\s+(?:builds|makes|sells|runs|serves|offers|supplies|designs|bakes|cooks)\b))")
# "I run Nila Cafe in Anna Nagar, we sell…" — the name after "I run", up to
# where the place or the next clause starts.
_NAME_RUNS = re.compile(
    r"^\s*(?i:i|we)\s+(?i:run|own|started|opened|have)\s+(?:(?i:a|an|the)\s+[\w ]{2,30}?\s+(?i:called|named)\s+)?"
    r"(?P<name>[A-Z0-9][\w&'’.-]*(?:\s+(?:&\s+|of\s+|and\s+)?[A-Z0-9&][\w&'’.-]*){0,5})"
    r"(?=\s+(?i:in|at|near|on|from|since|for)\b|\s*[,.;!—–-]|\s*$)")
# Tanglish: "Naan Nila Cafe nadathuren" (I run Nila Cafe), "Enga kadai per Nila Cafe".
_NAME_TA = re.compile(
    r"^\s*(?i:naan|naanga|nanga|naangal|enga|engaloda)\s+"
    r"(?P<name>[A-Z0-9][\w&'’.-]*(?:\s+(?:&\s+)?[A-Z0-9&][\w&'’.-]*){0,5})"
    r"\s+(?i:nadath\w*|nadatt\w*|vech\w*|vach\w*|run\s+pann\w*|open\s+pann\w*)")
_NAME_TA_SAID = re.compile(
    r"\b(?i:kadai|shop|hotel|cafe|business|company|salon)\s+(?i:per|peru|name)\s+"
    r"(?P<name>[A-Z0-9][^,.;!?]{1,58}?)(?=\s*(?:[,.;!?]|$)|\s+(?i:dhaan|thaan))")
_NAME_END = re.compile(r"\s+(?:and|in|at|near|on|from|which|that|where|—|-|,)\b.*$", re.I)
_NOT_A_NAME = re.compile(
    r"^(?:we|i|our|my|this|it|the|a|an|they|people|customers|yes|no|ok|hi|hello|mostly|mainly|"
    r"chicken|mutton|fish|monthly|daily)$", re.I)


def business_name(text: str) -> str:
    """The business's own name, only when the owner plainly says it."""
    raw = " ".join((text or "").split())
    found = _NAME_SAID.search(raw)
    name = _NAME_END.sub("", found.group("name")) if found else ""
    # "This is Kavya, I make cakes" introduces a person, not the business.
    if not name and not re.match(r"^\s*(?:this is|i'?m|i am)\s+\S+\s*,\s*i\b", raw, re.I):
        lead = _NAME_LEADS.match(raw) or _NAME_RUNS.match(raw) or _NAME_TA.match(raw) or _NAME_TA_SAID.search(raw)
        name = lead.group("name") if lead else ""
        # "Haircut, facial and bridal makeup iruku" starts a list, not a name.
        if lead is not None and lead.re is _NAME_LEADS and re.match(
                r"\s*,\s*[a-z][\w' -]{0,30}?(?:,|\s+and\s+)", raw[lead.end():]):
            name = ""
    name = name.strip(" .,'\"“”")
    words = name.split()
    if not words or len(words) > 6 or len(name) > 60 or _NOT_A_NAME.match(words[0]):
        return ""
    if canonical_actions(name) or looks_like_hours(name) or phone_number(name):
        return ""
    return name


# "No, actually we're mainly a physiotherapy centre" — the owner correcting
# what kind of business it is, not adding a detail.
_KIND_CORRECTION = re.compile(
    # "No, …" / "Actually, …" at the start of the message…
    r"^\s*(?:no|nope|not really|actually)\b"
    # …or a statement of what the business IS: "we're mainly a…", "it's actually a…"
    r"|\b(?:we'?re|we are|it'?s|it is|this is|i'?m|i am)\s+(?:(?:actually|mainly|mostly|primarily|really|"
    r"more of|more like|basically)\s+)+(?:a|an|the)\b"
    r"|\bnot (?:a|an)\s+[\w ]{2,30}?[,;]?\s+(?:but|we'?re|it'?s)\b", re.I)


def corrects_kind(text: str) -> bool:
    return bool(_KIND_CORRECTION.search(text or ""))


# ---------------------------------------------------------- owner signals

_FINISH = re.compile(
    r"\b(build (?:it|the site|the website|my (?:web)?site|now)|go ahead|that'?s (?:all|it|enough)|that is all|"
    r"just this much|nothing (?:else|more)|no more|enough (?:for now|questions)?|create (?:the|my) (?:web)?site|"
    r"make (?:the|my) (?:web)?site|let'?s build|ready to build|done for now|i'?m done|looks good,? (?:please )?build)\b"
    r"|போதும்|\bpo(?:d|th)hum\b|build pannunga|build pannalam",
    re.I,
)
_REFINE = re.compile(r"\b(keep refining|refine (?:it|more)|ask me more|more questions|keep asking|let'?s refine)\b", re.I)
_DECLINE = re.compile(
    r"^\s*(no|nope|nah|skip|later|not now|don'?t know|dont know|no idea|not sure|nothing|none|illa|venaam|"
    r"not needed|not required|n/?a|doesn'?t apply|not applicable|pass)\b"
    r"|\b((?:doesn'?t|does not|don'?t|do not) (?:really )?apply|not (?:relevant|applicable) (?:to|for) us|"
    r"we don'?t (?:have|do) (?:that|any))\b",
    re.I,
)
_REDUNDANT = re.compile(r"\b(already (?:told|said|mentioned|gave)|i (?:just )?said|as i said|obviously|i told you)\b", re.I)


@dataclass
class Reading:
    """What one owner message says, deterministically."""

    actions: list[str] = field(default_factory=list)
    fulfilment: list[str] = field(default_factory=list)
    area: str = ""
    payment: list[str] = field(default_factory=list)
    units: str = ""
    phone: str = ""
    hours: str = ""
    offerings: list[str] = field(default_factory=list)
    content: list[str] = field(default_factory=list)
    finish: bool = False
    refine: bool = False
    decline: bool = False
    redundant: bool = False


def read(text: str) -> Reading:
    text = " ".join((text or "").split())
    return Reading(
        actions=canonical_actions(text),
        fulfilment=fulfilment_modes(text),
        payment=payment_methods(text),
        units=units(text),
        phone=phone_number(text),
        hours=text if looks_like_hours(text) else "",
        content=content_wishes(text),
        finish=bool(_FINISH.search(text)),
        refine=bool(_REFINE.search(text)),
        decline=bool(_DECLINE.search(text)) and len(text) < 90,
        redundant=bool(_REDUNDANT.search(text)),
    )


# ------------------------------------------------------- slot validation

def valid_for(target: str, text: str) -> bool:
    """Whether a quotation is the right kind of thing for a slot.

    Used on every model extraction and every typed correction. A slot with no
    rule accepts any non-empty quotation.
    """
    text = " ".join((text or "").split())
    if not text:
        return False
    if target in {"operations.hours", "opening_hours"}:
        return looks_like_hours(text) or bool(hours_clause(text)) or bool(re.search(
            r"\b(open|closed)\b.{0,30}\b(all days|daily|every day|weekdays|weekends|sundays?)\b", text, re.I))
    if target in {"contact.phone", "phone"}:
        return bool(phone_number(text))
    if target in {"commerce.action", "customer_actions"}:
        return bool(canonical_actions(text))
    if target in {"contact.location", "locations"}:
        return bool(location_text(text)) and not re.fullmatch(r"(?:all|across|over)\s.*india", text, re.I)
    if target in {"offerings.main", "offerings"}:
        return bool(offering_names(text))
    if target in {"fulfilment.mode"}:
        return bool(fulfilment_modes(text))
    if target in {"fulfilment.area"}:
        return bool(service_area(text)) or bool(fulfilment_modes(text))
    if target in {"commerce.payment"}:
        return bool(payment_methods(text))
    if target in {"offerings.units"}:
        return bool(units(text))
    return True
