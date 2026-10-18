"""Natural-language intent is advisory; only platform registries grant meaning."""

from __future__ import annotations

import re

from platform_core.business_type_profiles.registry import BusinessTypeProfileRegistry
from platform_core.entitlements.capability_registry import CAPABILITIES
from platform_core.entitlements.models import ResolvedEntitlement
from platform_core.entitlements.module_registry import ModuleRegistry
from platform_core.entitlements.resolver import PlatformCapabilityResolver
from platform_core.interview.models import (
    BusinessBlueprint,
    CapabilityGapProposal,
    CapabilityIntent,
    Message,
    ModuleRecommendation,
    RecommendationEvidence,
)

# Recommendation vocabulary, not business-type mechanics. Every value is verified
# against the canonical registry below; registry presence alone is not availability.
INTENTS = {
    "catalog": (
        "offerings-catalog",
        "Show your products or services",
        r"\b(products?|catalog(?:ue)?|menu|services?|browse)\b",
    ),
    "orders": ("orders", "Take orders online", r"\b(orders?|buy|purchase|checkout|pre-?order)\b"),
    "bookings": (
        "bookings",
        "Take bookings and appointments",
        r"\b(book|bookings?|appointments?|reservations?|reserve)\b",
    ),
    # "Call us" is how people reach any business; it is not an enquiry workflow.
    "enquiries": ("leads", "Receive enquiries",
                  r"\b(enquir\w*|inquir\w*|whatsapp us|send (?:us )?(?:an? )?(?:message|requirement)s?)\b"),
    "quotes": (
        "quotes",
        "Send quotations",
        r"\b(quotes?|quotations?|estimates?|rfq|request (?:a |for )?(?:price|quote))\b",
    ),
    "memberships": ("memberships", "Run memberships and subscriptions", r"\b(memberships?|subscriptions?|monthly plans?)\b"),
    "payments": ("payments", "Collect payments online", r"\b(payments?|pay online|upi)\b"),
    "inventory": ("inventory", "Keep track of stock", r"\b(inventory|stock)\b"),
    "delivery": ("fulfilment", "Manage delivery and pickup", r"\b(deliver\w*|pickup|pick up|fulfilment)\b"),
    "projects": ("projects", "Track projects and work orders", r"\b(projects?|work orders?|installations?)\b"),
    "reviews": ("reviews", "Collect customer reviews", r"\b(reviews?|feedback|ratings?)\b"),
    "messaging": ("messaging", "Message customers", r"\b(messag\w+|sms|broadcasts?)\b"),
    "crm": ("customer-relationships", "Keep customer records", r"\b(customer (?:records|list|history)|crm)\b"),
    "loyalty": ("loyalty", "Reward repeat customers", r"\b(loyalty|rewards?|points)\b"),
    "invoicing": ("invoicing", "Send invoices", r"\b(invoices?|invoicing|bills?|gst bill)\b"),
    "donations": ("donations", "Take donations for your causes", r"\b(donat\w*|donors?|fundrais\w*)\b"),
}

# The model names what an owner wants in its own words ("pickup", "courier",
# "upi"). Those are supported intents under another name — telling an owner
# "pickup is not supported" while putting pickup on their website is wrong.
_ALIASES = {
    "pickup": "delivery", "pick_up": "delivery", "store_pickup": "delivery", "takeaway": "delivery",
    "shipping": "delivery", "courier": "delivery", "home_delivery": "delivery",
    "local_delivery": "delivery", "fulfilment": "delivery", "fulfillment": "delivery",
    "online_ordering": "orders", "whatsapp_orders": "orders", "ordering": "orders", "order": "orders",
    "upi": "payments", "online_payment": "payments", "online_payments": "payments",
    "cash_on_delivery": "payments", "payment": "payments",
    "appointments": "bookings", "appointment": "bookings", "reservations": "bookings",
    "booking": "bookings", "trial_booking": "bookings", "table_booking": "bookings",
    "catalogue": "catalog", "menu": "catalog", "products": "catalog", "product_catalog": "catalog",
    "enquiry": "enquiries", "inquiries": "enquiries", "lead": "enquiries", "leads": "enquiries",
    "quotation": "quotes", "quotations": "quotes", "rfq": "quotes", "estimates": "quotes",
    "membership": "memberships", "subscriptions": "memberships",
    "stock": "inventory", "invoice": "invoicing", "billing": "invoicing",
    "review": "reviews", "whatsapp_messaging": "messaging", "sms": "messaging",
    # An NGO's "online donations" is the Donations tool, and volunteers sign up
    # through the enquiry form (both were answered "not supported today").
    "donate": "donations", "donation": "donations", "online_donations": "donations",
    "fundraising": "donations", "donor_management": "donations",
    "volunteer_signups": "enquiries", "volunteer_signup": "enquiries", "volunteers": "enquiries",
    "volunteer": "enquiries", "volunteering": "enquiries",
}


# The website itself — building, previewing, publishing it — is what the
# interview is for, never a missing capability ("please build it" was answered
# with "That request is not supported today").
_THE_PLATFORM = frozenset({
    "website", "site", "web_site", "build", "build_website", "website_build", "build_site",
    "create_website", "make_website", "generate_website", "website_generation", "preview",
    "preview_website", "publish", "publish_website", "launch", "launch_website", "go_live",
    "update_website", "edit_website", "redesign", "rebuild",
})


# Canonical customer actions (interview.reader) -> the supported intent they evidence.
ACTION_INTENTS = {
    "order_online": "orders", "order_whatsapp": "orders", "order_call": "orders",
    "book_online": "bookings", "book_whatsapp": "bookings", "book_call": "bookings",
    "book_table": "bookings", "book_trial": "bookings", "book_site_visit": "bookings",
    "book_consultation": "bookings", "request_quote": "quotes", "enquire": "enquiries",
    "check_dates": "enquiries", "join": "memberships", "subscribe": "memberships",
}


def canonical_intent(intent: str) -> str:
    """The supported intent an owner's wording means, or the wording itself."""
    key = re.sub(r"[^a-z0-9]+", "_", intent.casefold()).strip("_")
    if key in INTENTS:
        return key
    return _ALIASES.get(key, key)
LABELS = {module: label for module, label, _ in INTENTS.values()}
CUSTOMER_FACING = frozenset(
    {"offerings-catalog", "orders", "bookings", "leads", "quotes", "memberships",
     "payments", "fulfilment", "reviews", "loyalty", "donations"}
)

# Classification aliases extend registry data; never grant tools or branch workflow.
CLASSIFICATION_SEEDS = {
    "hospital": "clinic",
    "medical": "clinic",
    "furniture": "retail",
    "meat shop": "retail",
    "clothing": "retail",
    "product seller": "retail",
    "meat": "retail",
    "grocery": "retail",
    "vegetables": "retail",
    "bakery": "cafe",
    "industrial": "professional_service",
    "supplier": "professional_service",
    "home food": "restaurant",
    "home-food": "restaurant",
    "real estate": "professional_service",
    "professional services": "professional_service",
}


def blueprint_text(bp: BusinessBlueprint) -> str:
    """Everything the owner has actually said, as one lowercase haystack.

    Extraction assigns each field one exact quotation from a much longer answer,
    so the sentence that happens to land in `description` is not reliably the
    sentence that says what the business is. A hospital that described itself in
    one paragraph had "we run a 24 hour emergency department" as its description
    and the word "hospital" only in its name and its offerings — and reading two
    fields classified it as "other", which then chose its template and its whole
    website. What the owner said is what they said, wherever it was filed.
    """
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    parts = [fact.value for fact in facts.values()]
    parts += [fact.value for fact in bp.identity.values()]
    parts += [intent.original_request for intent in bp.requested_capabilities]
    return " ".join(parts).lower()


def because(said: str) -> str:
    """Why a tool is recommended, in the owner's own words."""
    quote = " ".join(said.split()).strip(" .")
    if len(quote) > 110:
        quote = quote[:107].rsplit(" ", 1)[0] + "…"
    return f"Because you said “{quote}”."


def classification_seed(bp: BusinessBlueprint) -> str:
    text = blueprint_text(bp)
    candidates = {
        **CLASSIFICATION_SEEDS,
        **{
            row["type_id"].replace("_", " "): row["type_id"]
            for row in BusinessTypeProfileRegistry.list_types()
        },
    }
    for phrase, seed in candidates.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", text):
            return str(seed)
    # Nothing said names a profile: the kind the owner picked (or that their
    # words were read as) still carries its legacy template key.
    if bp.category and bp.category.category_key:
        from platform_core.catalog.taxonomy import resolve

        found = resolve(bp.category.category_key, bp.category.subcategory_key or None)
        if found and found[0].template:
            return str(found[0].template)
    return "other"


# ------------------------------------------------------------------ recommendations
#
# Deterministic and explainable (Document 07 §9): every recommendation names
# its evidence — the owner's words, an answered question, or an observed way of
# working — and a Business-Type Profile alone never recommends anything. The
# model contributes signals; it never names a module.

# Owner-facing names. Canonical ids stay internal.
FRIENDLY: dict[str, str] = {
    "offerings-catalog": "Online catalogue",
    "orders": "Online orders",
    "payments": "Payments",
    "inventory": "Inventory & stock",
    "fulfilment": "Delivery & pickup",
    "bookings": "Bookings & appointments",
    "customer-relationships": "Customer relationships",
    "messaging": "Messaging",
    "workforce": "Staff & schedules",
    "memberships": "Memberships",
    "quotes": "Quotations",
    "leads": "Enquiries",
    "invoicing": "Invoices",
    "projects": "Projects & work orders",
    "reviews": "Reviews",
    "loyalty": "Loyalty rewards",
    "marketing": "Marketing",
    "analytics": "Analytics",
    "queue-operations": "Walk-in queue",
    "b2b-network": "Business network",
    "payroll": "Payroll",
}
WHAT: dict[str, str] = {
    "offerings-catalog": "Show what you sell or offer, with options and prices.",
    "orders": "Let customers choose what they want and place an order.",
    "payments": "Collect payment when customers check out.",
    "inventory": "Track what is in stock and mark items sold out.",
    "fulfilment": "Manage delivery and pickup for each order.",
    "bookings": "Let people book appointments, tables or sessions.",
    "customer-relationships": "Keep customer details and order history in one place.",
    "messaging": "Send order updates and messages to customers.",
    "workforce": "Plan who is working and when.",
    "memberships": "Sell monthly or yearly plans.",
    "quotes": "Send quotations and track which are accepted.",
    "leads": "Collect enquiries and follow them up.",
    "invoicing": "Send invoices and track what is owed.",
    "projects": "Track custom work from order to completion.",
    "reviews": "Collect reviews after an order.",
    "loyalty": "Reward customers who come back.",
    "marketing": "Send offers to your customers.",
}


def _short(text: str, limit: int = 3) -> str:
    parts = [p.strip(" .") for p in re.split(r",|;|\band\b", text) if p.strip(" .")]
    parts = [p for p in parts if not re.search(r"\ball (?:types|kinds)\b|\beverything\b", p, re.I)]
    parts = parts[:limit]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _quote(text: str) -> str:
    quote = " ".join(text.split()).strip(" .")
    return quote if len(quote) <= 110 else quote[:107].rsplit(" ", 1)[0] + "…"


def _evidence_quote(bp: BusinessBlueprint, pattern: str) -> str:
    """The owner's own sentence that shows this, wherever they said it.

    What the owner typed comes first: a model's quotation can be one word
    ("sell"), and a fact built up over several answers is several sentences
    joined with ";" — neither reads as something the owner said.
    """
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    haystack = [m.text for m in bp.messages if m.role == "user"]
    haystack += [facts[k].value for k in ("customer_actions", "operational_characteristics",
                                          "operating_model", "description", "offerings") if k in facts]
    haystack += [s.quote for s in bp.discovery.values() if s.quote]
    haystack += [e.quote for e in bp.operating_patterns]
    rx = re.compile(pattern, re.I)
    for text in haystack:
        for sentence in re.split(r"(?<=[.!?])\s+|\s*;\s*", text):
            if len(sentence.split()) >= 3 and rx.search(sentence):
                return _quote(sentence)
    return ""


def recommend(
    bp: BusinessBlueprint, business_type: str | None = None
) -> dict[str, tuple[str, str, list[RecommendationEvidence], str]]:
    """module -> (strength, reason for the owner, evidence, configuration needed).

    Only modules with evidence appear. Dependencies are added by the caller.
    """
    from platform_core.interview.discovery import TEAM, characteristics

    chars = characteristics(bp, business_type)
    seen = {c for c, how in chars.items() if how == "observed"}
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    state = bp.discovery
    intents = {canonical_intent(i.intent) for i in bp.requested_capabilities}
    # The plain words of what customers should do ("book appointments", "view
    # products") are evidence even when the model returned no intents.
    action_text = facts["customer_actions"].value if "customer_actions" in facts else ""
    if action_text and not re.search(r"\b(no|not|don't|without)\b", action_text, re.I):
        intents |= {name for name, (_, _, pattern) in INTENTS.items()
                    if re.search(pattern, action_text, re.I)}
    # The typed actions (reader-checked) are evidence too: "order on WhatsApp",
    # "book a site visit", "ask for a quote".
    from platform_core.interview.understanding import customer_actions

    intents |= {ACTION_INTENTS[a] for a in customer_actions(bp) if a in ACTION_INTENTS}
    items = _short(facts["offerings"].value) if "offerings" in facts else ""
    units = (state.get("offerings.units").summary if state.get("offerings.units") else "") or ""
    payment = (state.get("commerce.payment").summary if state.get("commerce.payment") else "") or ""
    fulfil = state.get("fulfilment.mode")
    fulfil_text = ((fulfil.summary + " " + fulfil.quote) if fulfil else "").lower()
    out: dict[str, tuple[str, str, list[RecommendationEvidence], str]] = {}

    def said(pattern: str, otherwise: str = "") -> list[RecommendationEvidence]:
        """The owner's own sentence; else the way of working it was read from."""
        quote = _evidence_quote(bp, pattern)
        if quote:
            return [RecommendationEvidence(kind="owner_said", text=quote)]
        return [RecommendationEvidence(kind="operating_model", text=otherwise)] if otherwise else []

    sells = "sells_products" in seen or ("sells_products" in chars and "accepts_orders" in seen)
    orders = "accepts_orders" in seen or "orders" in intents
    # A business buyer asks for a quote and pays an invoice; a consumer
    # checkout is the wrong tool for them.
    quote_b2b = "serves_businesses" in seen and ("quote_led" in seen or "quotes" in intents)
    if sells or orders or "catalog" in intents:
        what = items or "your products"
        low_units = units.lower()
        how = (
            "so buyers can see what you supply before they ask for a quote" if quote_b2b
            else "with photos of past work, so people can ask for their own"
            if "made_to_order" in seen and not orders
            else "with the weights customers can choose" if re.search(r"\b(kg|kilo|weight|gram)", low_units)
            else "with the pack sizes you sell" if re.search(r"\b(pack|size)", low_units)
            else "with the options and prices customers can choose"
        )
        out["offerings-catalog"] = (
            "strong",
            f"Show {what}, {how}.",
            said(r"\b(sell|products?|menu|catalog\w*)\b") or [
                RecommendationEvidence(kind="operating_model", text="You sell products.")],
            "Add your items, and their options and prices.",
        )
    elif "provides_services" in seen:
        out["offerings-catalog"] = (
            "useful",
            "List your services, so people can see what you offer before they get in touch.",
            [RecommendationEvidence(kind="operating_model", text="You offer services.")],
            "Add your services.",
        )
    if orders and quote_b2b:
        out["orders"] = (
            "useful",
            "Once a buyer accepts your quote, track it as an order through to delivery.",
            said(r"\b(order\w*|purchase\w*|po)\b") or [
                RecommendationEvidence(kind="operating_model", text="Business buyers order after a quote.")],
            "",
        )
    elif orders:
        evidence = said(r"\b(order\w*|buy|cart|checkout)\b")
        out["orders"] = (
            "strong",
            ("Because you said “" + evidence[0].text + "”. " if evidence else "")
            + "Customers choose what they want and place an order.",
            evidence or [RecommendationEvidence(kind="operating_model", text="Customers order from you.")],
            "Decide how orders are confirmed.",
        )
        cash_only = re.search(r"\b(cash|cod|pay on delivery)\b", payment, re.I) and not re.search(
            r"\b(online|upi|card|both)\b", payment, re.I)
        if cash_only:
            out["payments"] = (
                "useful",
                "You said customers pay cash on delivery for now — add online payment whenever you want.",
                [RecommendationEvidence(kind="answer", text=payment)],
                "Choose whether to accept online payment.",
            )
        else:
            out["payments"] = (
                "strong",
                "Online orders need a way to pay at checkout — online, cash on delivery, or both."
                if not payment else f"Collect payment at checkout — {payment[:1].lower()}{payment[1:].rstrip('.')}.",
                [RecommendationEvidence(kind="answer", text=payment)] if payment else [
                    RecommendationEvidence(kind="operating_model", text="Customers order online.")],
                "" if payment else "Choose online payment, cash on delivery, or both.",
            )
        # Stock matters when customers pick a quantity of something that can
        # run out — a weight, packs, pieces — not merely because food is sold.
        by_quantity = bool(units) and bool(
            state.get("offerings.units") and state["offerings.units"].status == "answered")
        if sells and (by_quantity or "stock_based" in seen or "inventory" in intents):
            quantity = (
                "the weight" if re.search(r"\b(kg|kilo|weight|gram)", units, re.I)
                else "how many" if units else "what they want"
            )
            out["inventory"] = (
                "strong",
                f"Customers choose {quantity} — keep track of what is available and mark items "
                "sold out, so nobody orders what you don't have.",
                [RecommendationEvidence(kind="answer", text=units)] if units else
                said(r"\b(stock|sold out|availab\w*)\b") or [
                    RecommendationEvidence(kind="operating_model", text="Stock changes day to day.")],
                "Set what is in stock.",
            )
    if "stock_based" in seen and "inventory" not in out:
        out["inventory"] = ("useful", "Track what is in stock and when items sell out.",
                            said(r"\b(stock|sold out|availab\w*)\b", "What is available changes."),
                            "Set what is in stock.")
    delivers = "delivers" in seen or re.search(r"\bdeliver|\bship", fulfil_text)
    pickup = "pickup" in seen or re.search(r"pick ?up|collect", fulfil_text)
    if (delivers or pickup) and orders:
        # The model's summaries are written to the owner ("Delivery covers ...");
        # spliced into a sentence they read as nonsense, so they stay evidence.
        area = state.get("fulfilment.area")
        mode = ("delivery and pickup" if pickup else "delivery") if delivers else "pickup"
        out["fulfilment"] = (
            "useful" if quote_b2b else "strong",
            f"You offer {mode} — manage it order by order.",
            said(r"\b(deliver\w*|pick ?up|ship\w*|take ?away|collect\w*)\b",
                 (fulfil.summary if fulfil and fulfil.summary else f"You offer {mode}."))
            + ([RecommendationEvidence(kind="answer", text=area.summary)]
               if delivers and area and area.status == "answered" and area.summary else []),
            "Set your delivery area and charges." if delivers else "Set pickup times.",
        )
    if "accepts_appointments" in seen or "bookings" in intents:
        evidence = said(r"\b(book\w*|appointment\w*|reserv\w*|slot\w*)\b")
        out["bookings"] = (
            "strong",
            ("Because you said “" + evidence[0].text + "”. " if evidence else "")
            + "Let people book online.",
            evidence or [RecommendationEvidence(kind="operating_model", text="People book with you.")],
            "Set your hours and what can be booked.",
        )
    elif "runs_classes" in seen:
        out["bookings"] = (
            "useful",
            "You run classes — let people reserve a place in each one.",
            said(r"\b(class\w*|batch\w*|sessions?)\b", "You run classes."),
            "Add your class timetable.",
        )
    if "has_team" in seen:
        evidence = said(TEAM.pattern)
        if evidence and evidence[0].kind == "owner_said":
            out["workforce"] = (
                "useful",
                f"You mentioned your team (“{evidence[0].text}”) — plan who is working and when.",
                evidence, "Add your team members.",
            )
    if "has_memberships" in seen or "memberships" in intents:
        out["memberships"] = ("strong", "Sell membership plans and manage renewals.",
                              said(r"\b(membership\w*|monthly|subscription\w*)\b", "You sell plans."),
                              "Create your plans.")
        if "payments" not in out:
            out["payments"] = (
                "strong",
                "Collect membership fees"
                + (f" — {payment[:1].lower()}{payment[1:].rstrip('.')}." if payment else " online."),
                [RecommendationEvidence(kind="answer", text=payment)] if payment else [
                    RecommendationEvidence(kind="operating_model", text="Members pay for plans.")],
                "" if payment else "Choose how members pay.",
            )
    if "quote_led" in seen or "quotes" in intents:
        evidence = said(r"\b(quot\w*|estimate\w*|rfq)\b")
        out["quotes"] = (
            "strong",
            ("Because you said “" + evidence[0].text + "”. " if evidence else "")
            + "Send quotations and see which are accepted.",
            evidence or [RecommendationEvidence(kind="operating_model", text="Customers ask for quotes.")],
            "Set up your quotation details.",
        )
    if "enquiry_led" in seen or "enquiries" in intents or (
        "serves_businesses" in seen and "quote_led" in seen
    ):
        evidence = said(r"\b(enquir\w*|inquir\w*|quot\w*|call us|whatsapp)\b")
        out["leads"] = (
            "useful" if (orders and not quote_b2b) or "bookings" in out else "strong",
            "Collect enquiries in one place and follow each one up.",
            evidence or [RecommendationEvidence(kind="operating_model", text="Customers enquire first.")],
            "",
        )
    if "made_to_order" in seen and ("projects" in intents or _evidence_quote(
        bp, r"\b(install\w*|fit\w*|project\w*)\b"
    )):
        out["projects"] = ("useful", "Track each custom job from order to installation.",
                           said(r"\b(install\w*|fit\w*|project\w*|custom)\b", "You make things to order."),
                           "")
    if "serves_businesses" in seen or "invoicing" in intents:
        out["invoicing"] = ("useful", "Send invoices to business customers and track payment.",
                            said(r"\b(invoice\w*|gst|compan\w*|factor\w*|business\w*)\b",
                                 "You sell to businesses."), "")
    # Tools the owner asked for by name, and only then.
    for intent, module in (("crm", "customer-relationships"), ("messaging", "messaging"),
                           ("reviews", "reviews"), ("loyalty", "loyalty")):
        if intent in intents and module not in out:
            asked = next(i for i in bp.requested_capabilities if canonical_intent(i.intent) == intent)
            out[module] = ("strong", WHAT[module],
                           [RecommendationEvidence(kind="owner_said", text=_quote(asked.original_request))],
                           "")
    return out


def _gaps(bp: BusinessBlueprint) -> list[CapabilityGapProposal]:
    """Requests the platform cannot do, answered wherever the owner said them."""
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    requests = list(bp.requested_capabilities)
    # An unsupported ask must be answered wherever the owner happened to say it,
    # and whether or not extraction kept it. A hospital asked for "live GPS
    # tracking of our ambulances" in the same breath as everything else;
    # extraction has no field for it, so the sentence was dropped, nothing was
    # raised, and the request passed in silence — which reads to the owner as
    # the platform having quietly agreed to build it. Fulfilment gives a
    # customer a status link; it does not track a vehicle live.
    spoken = [fact.value for fact in facts.values()]
    spoken += [message.text for message in bp.messages if message.role == "user"]
    tracking = re.compile(
        r"[^.!?]*\b(?:live\s+\w*\s*track\w*|track\w*\s+live|courier[^.!?]*map|gps)\b[^.!?]*",
        re.I,
    )
    for said in spoken:
        match = tracking.search(said)
        if match:
            requests.append(
                CapabilityIntent(
                    intent="live_courier_tracking",
                    original_request=(match.group(0).strip() or said)[:4000],
                )
            )
            break
    gaps: dict[str, CapabilityGapProposal] = {}
    for request in requests:
        intent = canonical_intent(request.intent)
        if intent in INTENTS or intent in _THE_PLATFORM or request.intent in gaps:
            continue
        gaps[request.intent] = CapabilityGapProposal(
            original_request=request.original_request,
            normalized_intent=request.intent,
            business_classification=classification_seed(bp),
            closest_supported_capabilities=["use_fulfilment"] if "track" in request.intent else [],
            why_unsupported="This specific workflow is not available in the current platform. "
            "It will not be added to your website.",
            required_mechanics=["A separately designed, authorised and tested platform integration"],
            session_reference=bp.session_id,
        )
    return list(gaps.values())[:40]


def _built(module: str) -> bool:
    """Registered is not built. A Capability Universe module whose data, API,
    permissions and UI do not exist yet is never offered as available."""
    from platform_core.catalog.modules import MODULES

    info = MODULES.get(module)
    return info is None or (info.built and not info.future)


def _status(
    module: str, entitlement: ResolvedEntitlement, snapshot: object
) -> tuple[str, str, list[str]]:
    definition = ModuleRegistry.get_or_raise(module)
    if not _built(module):
        caps = [key for key, cap in CAPABILITIES.items() if cap.required_module_id == module]
        return ("NOT_CURRENTLY_AVAILABLE", "Not available on LOCAH yet.", caps)
    state = entitlement.module_states.get(module)
    caps = [key for key, cap in CAPABILITIES.items() if cap.required_module_id == module]
    enabled_features = all(
        entitlement.feature_states.get(feature) and entitlement.feature_states[feature].enabled
        for feature in definition.features[:1]
    )
    capabilities = getattr(snapshot, "capabilities", {})
    if not state or not state.entitled or not enabled_features:
        return ("NOT_CURRENTLY_AVAILABLE",
                "Not included in your current access. Choosing it does not upgrade your plan.", caps)
    if state.activation_state != "active":
        return ("SUPPORTED_NOT_ENABLED",
                "Off until you choose it. Some setup is needed before customers can use it.", caps)
    if (
        not state.configuration_ready
        or not state.dependency_satisfied
        or any(not capabilities.get(cap, False) for cap in caps)
    ):
        return "SUPPORTED_REQUIRES_CONFIGURATION", "On, but still needs setup.", caps
    return "SUPPORTED", "Already on.", caps


def resolve_recommendations(
    bp: BusinessBlueprint, entitlement: ResolvedEntitlement, business_type: str | None = None
) -> None:
    """Rebuild the recommendations from everything known so far.

    Recomputed every turn, so they evolve with the conversation — "we sell
    meat" suggests a catalogue; "select meat, select kg and order" adds orders,
    payments and stock; "we deliver" adds fulfilment. The owner's choices are
    kept by module id and never reset. Nothing here enables anything.
    """
    snapshot = PlatformCapabilityResolver.resolve_from_entitlement(entitlement)
    found = recommend(bp, business_type)
    needed_by: dict[str, list[str]] = {}
    core = ModuleRegistry.platform_core_ids()

    def add_dependencies(module: str) -> None:
        for dep in ModuleRegistry.get_or_raise(module).dependencies:
            if dep in core:
                continue
            needed_by.setdefault(dep, [])
            if module not in needed_by[dep]:
                needed_by[dep].append(module)
            if dep not in found:
                found[dep] = (
                    "dependency",
                    f"Needed for {FRIENDLY.get(module, module)}. {WHAT.get(dep, '')}".strip(),
                    [RecommendationEvidence(kind="dependency", text=f"{FRIENDLY.get(module, module)} "
                                            f"works on top of {FRIENDLY.get(dep, dep)}.")],
                    "",
                )
                add_dependencies(dep)

    for module in list(found):
        if ModuleRegistry.get(module):
            add_dependencies(module)
    order = {"strong": 0, "useful": 1, "dependency": 2}
    # The order an owner thinks in: what I sell, how it is ordered and paid
    # for, what is in stock, how it reaches them — then everything else.
    journey = ["offerings-catalog", "orders", "bookings", "quotes", "leads", "payments",
               "memberships", "inventory", "fulfilment"]
    recommendations: list[ModuleRecommendation] = []
    for module, (strength, reason, evidence, configuration) in sorted(
        found.items(),
        key=lambda kv: (order[kv[1][0]], journey.index(kv[0]) if kv[0] in journey else 99, kv[0]),
    ):
        definition = ModuleRegistry.get(module)
        if definition is None:
            continue
        status, why, caps = _status(module, entitlement, snapshot)
        recommendations.append(
            ModuleRecommendation(
                module_id=module,
                label=FRIENDLY.get(module, definition.display_name),
                reason=reason[:400],
                capability_ids=caps,
                dependencies=list(definition.dependencies),
                status=status,
                availability_reason=why,
                group="customer" if module in CUSTOMER_FACING else "operations",
                strength=strength,
                evidence=[e for e in evidence if e.text][:6],
                configuration_needed=configuration,
                needed_by=[FRIENDLY.get(m, m) for m in needed_by.get(module, [])],
                choice="declined"
                if module in bp.declined_modules
                else "approved"
                if module in bp.approved_modules
                else "pending",
            )
        )
    bp.recommended_modules = recommendations
    bp.unsupported_requests = _gaps(bp)


def available_modules(
    bp: BusinessBlueprint, entitlement: ResolvedEntitlement
) -> list[ModuleRecommendation]:
    """Every optional tool this business could switch on, straight from the registry.

    Available is not recommended, and neither is active. A tool appears here
    because the platform supports it and the business is entitled to it — a
    module added to the registry tomorrow appears here without a code change.
    Recommendation needs evidence from the conversation and lives elsewhere.
    """
    recommended = {item.module_id for item in bp.recommended_modules}
    snapshot = PlatformCapabilityResolver.resolve_from_entitlement(entitlement)
    result: list[ModuleRecommendation] = []
    rows = sorted(
        ModuleRegistry.list_modules(),
        key=lambda row: (row["module_id"] not in CUSTOMER_FACING, row.get("display_name") or ""),
    )
    for row in rows:
        module = row["module_id"]
        if row.get("module_class") != "optional" or module in recommended or not _built(module):
            continue
        definition = ModuleRegistry.get(module)
        state = entitlement.module_states.get(module)
        if not definition or not state or not state.entitled:
            continue
        if definition.features and not all(
            entitlement.feature_states.get(feature)
            and entitlement.feature_states[feature].enabled
            for feature in definition.features[:1]
        ):
            continue
        caps = [key for key, cap in CAPABILITIES.items() if cap.required_module_id == module]
        if state.activation_state != "active":
            status = "SUPPORTED_NOT_ENABLED"
            why = "Available with your current access. Your approval is needed before it can be enabled."
        elif (
            not state.configuration_ready
            or not state.dependency_satisfied
            or any(not snapshot.capabilities.get(cap, False) for cap in caps)
        ):
            status = "SUPPORTED_REQUIRES_CONFIGURATION"
            why = "Available with your current access, but setup or a prerequisite is still needed."
        else:
            status = "SUPPORTED"
            why = "Already switched on."
        result.append(
            ModuleRecommendation(
                module_id=module,
                label=FRIENDLY.get(module, definition.display_name),
                reason=WHAT.get(module) or getattr(definition, "description", "") or definition.display_name,
                capability_ids=caps,
                dependencies=list(definition.dependencies),
                status=status,
                availability_reason=why,
                group="customer" if module in CUSTOMER_FACING else "operations",
                choice="declined"
                if module in bp.declined_modules
                else "approved"
                if module in bp.approved_modules
                else "pending",
            )
        )
    return result


def surface_new_unsupported_requests(
    bp: BusinessBlueprint, previous_intents: set[str]
) -> None:
    """Put a newly detected capability gap into the authoritative reply.

    Capability resolution happens after extraction, so the orchestrator's next
    question cannot mention a gap that did not exist yet. Leaving it only in
    the final build-review section means an early voice turn sounds like Locah
    silently accepted the request. Keep the next question, but lead with the
    deterministic platform answer the owner needs to hear now.
    """
    new_gaps = [
        gap for gap in bp.unsupported_requests if gap.normalized_intent not in previous_intents
    ]
    if not new_gaps:
        return
    for index in range(len(bp.messages) - 1, -1, -1):
        message = bp.messages[index]
        if message.role != "assistant":
            continue
        notice = (
            "That request is not supported today and will not be added to your website. "
        )
        if not message.text.startswith(notice):
            bp.messages[index] = Message(
                role="assistant", text=notice + message.text, at=message.at
            )
        return


def operational_modules(entitlement: ResolvedEntitlement) -> set[str]:
    """A more restrictive input to composition than activation alone."""
    active = {
        mid
        for mid, state in entitlement.module_states.items()
        if state.entitled
        and state.activation_state == "active"
        and state.configuration_ready
        and state.dependency_satisfied
    }
    snapshot = PlatformCapabilityResolver.resolve_from_entitlement(entitlement)
    for cap, definition in CAPABILITIES.items():
        if not snapshot.capabilities.get(cap) and definition.required_module_id:
            active.discard(definition.required_module_id)
    for module in list(active):
        definition = ModuleRegistry.get_or_raise(module)
        if definition.features and not all(
            entitlement.feature_states.get(fid) and entitlement.feature_states[fid].enabled
            for fid in definition.features[:1]
        ):
            active.discard(module)
    changed = True
    while changed:
        removed = {
            mid
            for mid in active
            if not set(ModuleRegistry.get_or_raise(mid).dependencies) <= active
        }
        active -= removed
        changed = bool(removed)
    return active
