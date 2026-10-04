"""Empty states written for THIS Business.

"No orders yet" says nothing. "When someone orders Banana Walnut Bread or
Filter Coffee from your website, it lands here — publish your website first"
tells a café owner what will fill the page and what to do now. Each empty
state names the owner's own items, says whether their website can bring the
first one in yet, and offers the one or two actions that would. Read-only;
counts and names come from the same public reads the website uses.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import Business, Offering, Website

SELLABLE = ("product", "weighed_product", "menu_item", "package", "digital_product")
BOOKABLE = ("service", "class_session", "accommodation", "rental")

# {a} {b}: the owner's items; {site}: how the website brings it in (or not yet).
WORDS: dict[str, dict[str, str]] = {
    "en": {
        "orders_title": "No orders yet",
        "orders_body": "When someone orders {items}{site}, it lands here.",
        "orders_none": "Add something people can order, with a price — then orders can come in.",
        "bookings_title": "No bookings yet",
        "bookings_body": "When a customer picks a time for {items}{site}, it appears here for you to confirm.",
        "bookings_none": "Add a service people can book, with how long it takes — then bookings can come in.",
        "customers_title": "No {customers} yet",
        "customers_body": "{Customers} appear here after their first order, booking or enquiry — or add one yourself.",
        "leads_title": "No enquiries yet",
        "leads_body": "When someone asks about {items}{site}, it lands here for you to follow up.",
        "fulfilment_title": "Nothing to pick up or deliver yet",
        "fulfilment_body": "Each order for pickup or delivery becomes a job here, from preparing to handed over.",
        "inventory_title": "No stock being counted yet",
        "inventory_body": "Turn on stock for {items} to see what's left and get told before it runs out.",
        "site_live": " from your website",
        "site_not_live": " — once your website is published",
        "or": " or ",
        "publish": "Publish your website",
        "take_order": "Take an order yourself",
        "add_item": "Add an item",
        "add_service": "Add a service",
        "add_customer": "Add a customer",
        "add_enquiry": "Add an enquiry",
        "see_items": "Open your items",
        "orders_link": "See orders",
        "what_you_offer": "what you offer",
    },
    "ta": {
        "orders_title": "இன்னும் ஆர்டர்கள் இல்லை",
        "orders_body": "யாராவது {items} ஆர்டர் செய்தால்{site}, அது இங்கே வரும்.",
        "orders_none": "விலையுடன் ஆர்டர் செய்யக்கூடிய ஒன்றைச் சேர்க்கவும் — பிறகு ஆர்டர்கள் வரும்.",
        "bookings_title": "இன்னும் முன்பதிவுகள் இல்லை",
        "bookings_body": "வாடிக்கையாளர் {items}-க்கு நேரத்தைத் தேர்ந்தெடுத்தால்{site}, நீங்கள் உறுதிசெய்ய இங்கே வரும்.",
        "bookings_none": "முன்பதிவு செய்யக்கூடிய ஒரு சேவையை, எவ்வளவு நேரம் ஆகும் என்பதுடன் சேர்க்கவும்.",
        "customers_title": "இன்னும் வாடிக்கையாளர்கள் இல்லை",
        "customers_body": "முதல் ஆர்டர், முன்பதிவு அல்லது விசாரணைக்குப் பிறகு வாடிக்கையாளர்கள் இங்கே வருவார்கள் — நீங்களும் சேர்க்கலாம்.",
        "leads_title": "இன்னும் விசாரணைகள் இல்லை",
        "leads_body": "யாராவது {items} பற்றிக் கேட்டால்{site}, பின்தொடர இங்கே வரும்.",
        "fulfilment_title": "இன்னும் பிக்கப் / டெலிவரி இல்லை",
        "fulfilment_body": "பிக்கப் அல்லது டெலிவரிக்கான ஒவ்வொரு ஆர்டரும் இங்கே ஒரு வேலையாக வரும்.",
        "inventory_title": "இன்னும் ஸ்டாக் கணக்கிடப்படவில்லை",
        "inventory_body": "{items}-க்கு ஸ்டாக்கை இயக்கினால் எவ்வளவு மீதம் என்று தெரியும்.",
        "site_live": " (உங்கள் இணையதளத்தில்)",
        "site_not_live": " (இணையதளம் வெளியிட்ட பிறகு)",
        "or": " அல்லது ",
        "publish": "இணையதளத்தை வெளியிடுங்கள்",
        "take_order": "நீங்களே ஆர்டர் எடுங்கள்",
        "add_item": "பொருளைச் சேர்க்கவும்",
        "add_service": "சேவையைச் சேர்க்கவும்",
        "add_customer": "வாடிக்கையாளரைச் சேர்க்கவும்",
        "add_enquiry": "விசாரணையைச் சேர்க்கவும்",
        "see_items": "உங்கள் பொருட்கள்",
        "orders_link": "ஆர்டர்கள்",
        "what_you_offer": "நீங்கள் வழங்குவது",
    },
    "hi": {
        "orders_title": "अभी कोई ऑर्डर नहीं",
        "orders_body": "जब कोई {items} ऑर्डर करेगा{site}, तो वह यहाँ आएगा।",
        "orders_none": "कीमत के साथ कुछ ऐसा जोड़ें जिसे लोग ऑर्डर कर सकें — फिर ऑर्डर आने लगेंगे।",
        "bookings_title": "अभी कोई बुकिंग नहीं",
        "bookings_body": "जब कोई ग्राहक {items} के लिए समय चुनेगा{site}, तो वह पुष्टि के लिए यहाँ आएगा।",
        "bookings_none": "बुक की जा सकने वाली सेवा जोड़ें, उसमें लगने वाले समय के साथ।",
        "customers_title": "अभी कोई ग्राहक नहीं",
        "customers_body": "पहले ऑर्डर, बुकिंग या पूछताछ के बाद ग्राहक यहाँ दिखेंगे — या खुद जोड़ें।",
        "leads_title": "अभी कोई पूछताछ नहीं",
        "leads_body": "जब कोई {items} के बारे में पूछेगा{site}, तो फॉलो-अप के लिए यहाँ आएगा।",
        "fulfilment_title": "अभी कोई पिकअप या डिलीवरी नहीं",
        "fulfilment_body": "पिकअप या डिलीवरी वाला हर ऑर्डर यहाँ एक काम बनता है।",
        "inventory_title": "अभी कोई स्टॉक गिना नहीं जा रहा",
        "inventory_body": "{items} के लिए स्टॉक चालू करें ताकि पता रहे कितना बचा है।",
        "site_live": " (आपकी वेबसाइट से)",
        "site_not_live": " (वेबसाइट प्रकाशित होने के बाद)",
        "or": " या ",
        "publish": "अपनी वेबसाइट प्रकाशित करें",
        "take_order": "खुद ऑर्डर लें",
        "add_item": "आइटम जोड़ें",
        "add_service": "सेवा जोड़ें",
        "add_customer": "ग्राहक जोड़ें",
        "add_enquiry": "पूछताछ जोड़ें",
        "see_items": "अपने आइटम खोलें",
        "orders_link": "ऑर्डर देखें",
        "what_you_offer": "आपकी सेवाओं",
    },
}


def _items(names: list[str], w: dict[str, str]) -> str:
    names = names[:2]
    return w["or"].join(names) if names else ""


def compose(*, sellable: list[str], bookable: list[str], all_items: list[str], site_live: bool,
            customers_word: str, lang: str = "en") -> dict[str, dict[str, Any]]:
    """The empty states, from what this Business has. Pure."""
    w = WORDS.get(lang, WORDS["en"])
    site = w["site_live"] if site_live else w["site_not_live"]
    publish = [] if site_live else [{"label": w["publish"], "href": "/website"}]
    customers = customers_word or "Customers"
    out: dict[str, dict[str, Any]] = {}
    out["orders"] = ({"title": w["orders_title"], "body": w["orders_body"].format(items=_items(sellable, w), site=site),
                      "actions": publish + [{"label": w["take_order"], "href": "/orders/new"}]}
                     if sellable else
                     {"title": w["orders_title"], "body": w["orders_none"],
                      "actions": [{"label": w["add_item"], "href": "/offerings/new"}]})
    out["bookings"] = ({"title": w["bookings_title"],
                        "body": w["bookings_body"].format(items=_items(bookable, w), site=site), "actions": publish}
                       if bookable else
                       {"title": w["bookings_title"], "body": w["bookings_none"],
                        "actions": [{"label": w["add_service"], "href": "/offerings/new"}]})
    out["customers"] = {"title": w["customers_title"].format(customers=customers.lower()),
                        "body": w["customers_body"].format(Customers=customers),
                        "actions": [{"label": w["add_customer"], "href": "/customers#add"}]}
    asked = _items(all_items, w)
    out["leads"] = {"title": w["leads_title"],
                    "body": w["leads_body"].format(items=asked or w["what_you_offer"], site=site),
                    "actions": publish + [{"label": w["add_enquiry"], "href": "/leads#add"}]}
    out["fulfilment"] = {"title": w["fulfilment_title"], "body": w["fulfilment_body"],
                         "actions": [{"label": w["orders_link"], "href": "/orders"}]}
    out["inventory"] = ({"title": w["inventory_title"], "body": w["inventory_body"].format(items=_items(sellable, w)),
                         "actions": [{"label": w["see_items"], "href": "/offerings"}]}
                        if sellable else
                        {"title": w["inventory_title"], "body": w["orders_none"],
                         "actions": [{"label": w["add_item"], "href": "/offerings/new"}]})
    return out


async def empty_states(session: AsyncSession, business: Business, *, lang: str = "en") -> dict[str, dict[str, Any]]:
    from platform_core.services.workspace_projection import terms_for

    # What is on sale first; drafts still name the business's own range.
    rows = (await session.execute(select(Offering.title, Offering.offering_type).where(
        Offering.business_id == business.id, Offering.deleted_at.is_(None), Offering.status.in_(("active", "draft")),
    ).order_by((Offering.status != "active").asc(), Offering.created_at).limit(40))).all()
    sellable = [str(t) for t, k in rows if k in SELLABLE]
    bookable = [str(t) for t, k in rows if k in BOOKABLE]
    site = (await session.execute(select(Website.status).where(Website.business_id == business.id))).scalar()
    terms = await terms_for(session, business)
    return compose(sellable=sellable, bookable=bookable, all_items=[str(t) for t, _ in rows],
                   site_live=site == "published", customers_word=terms.get("customers", "Customers"), lang=lang)
