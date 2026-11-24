"""An owner's slips of the keyboard never reach their customers.

Owners type on a phone, fast, often in their second or third language:
"chiken biriyani", "duck rost", "hair straitening", "montly membarship". The
interview keeps their words — it must, every fact on the website is theirs —
but a customer reading the menu should see "Chicken biriyani" and "Duck roast".

This is a short list of the slips actually seen on the words that name what a
local business sells, not a spell-checker: a general one was tried on the
trade classifier and "corrected" real words. Regional spellings are left alone
on purpose — "biriyani", "parotta", "porotta", "kabab" are how those kitchens
write them.

Found on a real owner run (2026-11-13): a Kochi kitchen's public menu read
"Chiken biriyani" and "Stew chiken 240 veg".
"""

from __future__ import annotations

import re

_SLIPS: dict[str, str] = {
    slip: word
    for word, slips in {
        # food
        "chicken": "chiken chikken chickn chikn chickan chikan chiiken",
        "mutton": "mutten muton matton mutan",
        "roast": "rost roste",
        "fried": "fride frid",
        "noodles": "noodels noodls nudles noodle's",
        "sandwich": "sandwitch sandwhich sandwitch sanwich sandwic",
        "juice": "juce juic",
        "masala": "masla massala masaala",
        "paneer": "panner panir paner panneer",
        "manchurian": "manjurian manchuriyan manchurien manchuri",
        "vegetable": "vegitable vegetabl vegtable",
        "butter": "buter",
        "coffee": "cofee coffe",
        "chocolate": "choclate chocolet chocklate choclet",
        "pastry": "pastery",
        "biscuit": "biscut biscit",
        "prawns": "prons prawn's",
        "omelette": "omlet omlette omlate omelet",
        "tandoori": "tandori tanduri",
        "shawarma": "shwarma shawrma sharwama",
        "burger": "burgar",
        "pizza": "piza pizaa",
        "lassi": "lasi",
        "milkshake": "milkshak",
        "special": "specal spcl",
        "curry": "curi cury",
        "gravy": "gravey",
        "boneless": "bonless bonles",
        "breakfast": "brekfast breakfst brkfst",
        "sweets": "sweats",
        "cake": "cak",
        "cupcake": "cupcak",
        "brownie": "browni",
        # stays
        "bungalow": "bunglow bunglaw bungalo banglow bunglo",
        "cottage": "cotage cottege cottaj cotege",
        "cottages": "cotages cotteges",
        "villa": "vila villla",
        "villas": "vilas villlas",
        "night": "nite nyt",
        "nights": "nites nyts",
        "deluxe": "delux",
        # beauty and care
        "facial": "fecial facail",
        "keratin": "keratine kertin keratn",
        "haircut": "haircutt hairct",
        "massage": "masage massag",
        "manicure": "menicure manicur",
        "pedicure": "padicure pedicur",
        "bleach": "bleech",
        "threading": "threding thredding",
        "straightening": "straitening straightning straitning",
        "colour": "colur",
        "bridal": "bridel",
        "makeup": "meakup makup",
        "treatment": "treatmnt tretment",
        "consultation": "consultaion consultion consulation",
        # plans and classes
        "monthly": "montly monthy",
        "quarterly": "quaterly quartely quartly quarterley quartrly",
        "classes": "clases classs clasess",
        "annual": "anual annul",
        "weekly": "weekely wekly",
        "yearly": "yerly",
        "membership": "membarship membrship",
        "personal": "personel",
        "training": "traning trainng",
        "strength": "strenth strenght",
        "class": "clas",
        "session": "sesion",
        # everyday
        "delivery": "delivry delevery",
        "service": "servise",
        "repair": "repar repiar",
        "standard": "standerd",
        "premium": "premum",
        "regular": "reguler",
        "family": "famly",
        "double": "doble",
    }.items()
    for slip in slips.split()
}
_WORD = re.compile(r"[A-Za-z']+")


def fix_word(word: str) -> str:
    """One word, put right when it is a known slip; its capital letter kept."""
    right = _SLIPS.get(word.casefold())
    if not right:
        return word
    return right.capitalize() if word[:1].isupper() else right


# How people type in a chat, written out for a page a customer reads. Only for
# an owner's sentence shown as it was said (`for_the_page`) — never for a name.
_SHORTHAND: dict[str, str] = {
    "ppl": "people",
    "shud": "should",
    "shld": "should",
    "cud": "could",
    "wud": "would",
    "u": "you",
    "ur": "your",
    "pls": "please",
    "plz": "please",
    "nd": "and",
    "bcoz": "because",
    "bcz": "because",
    "coz": "because",
    "abt": "about",
    "wat": "what",
    "wen": "when",
    "frm": "from",
    "wid": "with",
    "thru": "through", "incl": "included", "approx": "about",
    "tmrw": "tomorrow",
    "tmrow": "tomorrow",
    "nite": "night",
    "gud": "good",
    "gr8": "great",
    "hv": "have",
    "hav": "have",
    "msg": "message",
    "appt": "appointment",
    "apointment": "appointment",
    "apptmnt": "appointment",
    "blr": "Bengaluru",
    "blore": "Bengaluru",
    "bangalore": "Bengaluru",
    "cbe": "Coimbatore",
    "chn": "Chennai",
    "hyd": "Hyderabad",
    "tvm": "Thiruvananthapuram",
    "ekm": "Ernakulam",
    "mdu": "Madurai",
    "hsr": "HSR",
    "btm": "BTM",
    "omr": "OMR",
    "ecr": "ECR",
}


def for_the_page(text: str, *, capitalise: bool = True) -> str:
    """An owner's sentence as a customer should read it: slips put right, chat
    shorthand written out, a capital to start (unless `capitalise` is off, for a
    fragment such as a price unit: "per nite" is "per night"). The facts are untouched — only
    how they are spelt. ("Ppl shud book trial first then join" and "hsr layout
    blr" were on a gym's live site, 2026-11-14.)"""

    def word(match: re.Match[str]) -> str:
        said = match.group(0)
        full = _SHORTHAND.get(said.casefold())
        if full is None:
            return fix_word(said)
        return full if full[:1].isupper() else (full.capitalize() if said[:1].isupper() else full)

    out = _WORD.sub(word, text or "")
    # "book online n pay": "n" for "and" between two words — never in a name
    # ("Rock n Roll Cafe" keeps its capitals and its n).
    out = re.sub(r"(?<=[a-z]) n (?=[a-z])", " and ", out)
    if not capitalise:
        return out
    return out[:1].upper() + out[1:] if out else out


def fix_words(text: str) -> str:
    """A name or a sentence with the known slips put right; nothing else changes."""
    return _WORD.sub(lambda m: fix_word(m.group(0)), text or "")
