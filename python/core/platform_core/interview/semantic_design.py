"""Does the website say what this business is? Checked before anything renders.

A florist with a "Programmes" menu, an industrial supplier inviting visitors
to "Book a class", a restaurant talking about procurement: each is a website
that looks finished and means the wrong thing. The composer is careful, and
the model's words are governed — this is the last deterministic check, over
the whole payload, of business semantics against:

* navigation labels,
* calls to action (hero, bar, closing band, ordering label),
* section titles,
* media (the truth policy: no drawn picture in a factual slot — a project, a work),
* treatment (a photographer's site must present work).

Each finding is FAIL (meaning is wrong: repaired, never shipped as is) or
FLAG (worth a human look; left as is). Repairs are deterministic and use the
trade's own words (the playbook's browse label and title) or a call to action
built from what customers actually do; a label with no honest replacement is
removed rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from platform_core.interview.creative_director import CreativeDirection
from platform_core.interview.models import BusinessBlueprint


@dataclass
class Finding:
    code: str
    severity: str  # fail | flag
    where: str
    text: str
    repaired: str = ""  # what it became ("" = removed, or not repaired)

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


# Language that only belongs to some kinds of business. (pattern, allowed-when)
_CLASSES = re.compile(r"\b(programmes?|programs?|classes|batch(?:es)?|memberships?|train with us|"
                      r"workouts?|coaching)\b", re.I)
_CLASS_BOOKING = re.compile(r"\bbook (?:a |your |an )?(?:class|session|trial|slot)\b", re.I)
_PROCUREMENT = re.compile(r"\b(rfq|procurement|bulk orders?|request (?:a |for )?quotation|oem|"
                          r"specifications?|industrial supply|purchase teams?)\b", re.I)
_MENU = re.compile(r"\bmenu\b", re.I)
_CART = re.compile(r"\b(add to cart|cart|checkout|buy now)\b", re.I)
_ROOMS = re.compile(r"\b(rooms?|stay with us|check[- ]in)\b", re.I)
_PROJECTS = re.compile(r"\b(projects?|site visits?)\b", re.I)
_TABLE = re.compile(r"\bbook (?:a )?table\b", re.I)
# "Services" is right for a salon or a repair shop; for a menu, a range, plans,
# projects or rooms it hides what people come for.
_GENERIC_SERVICES = re.compile(r"^\s*(?:our\s+)?services\s*$", re.I)

_FOOD_PLAYBOOKS = frozenset({"meat_seafood", "restaurant", "home_food", "bakery_sweets", "cafe", "tiffin",
                             "catering", "produce", "grocery", "dairy_subscription", "farm"})
# Programmes, classes, batches and plans are right for these (a play school's
# "Programmes", a coach's "Programmes", a gym's plans, a studio's classes).
_CLASS_PLAYBOOKS = frozenset({"gym", "studio", "coach", "tuition", "school", "arts_school", "tutor", "daycare",
                              "tiffin", "dairy_subscription"})
_PROJECT_PLAYBOOKS = frozenset({"real_estate_developer", "real_estate_broker", "design_studio", "contractor",
                                "event_planner", "photographer", "creative_agency", "maker", "software",
                                "industrial_supplier", "manufacturer", "energy", "ngo"})

# A call to action from what customers do, when one must be replaced.
_CTA = {
    "order_online": "Order online", "order_whatsapp": "Order on WhatsApp", "order_call": "Call to order",
    "book_online": "Book now", "book_whatsapp": "Book on WhatsApp", "book_call": "Call to book",
    "book_table": "Book a table", "book_trial": "Book a free trial", "book_site_visit": "Book a site visit",
    "book_consultation": "Book a consultation", "check_dates": "Check dates",
    "request_quote": "Ask for a quote", "enquire": "Send an enquiry", "call": "Call us",
    "whatsapp": "Message us", "visit": "Visit us", "join": "Join now",
}


def _kind(bp: BusinessBlueprint, direction: CreativeDirection) -> dict[str, Any]:
    from platform_core.interview.playbooks import playbook_for

    pb = playbook_for(bp)
    dims = direction.dimensions or {}
    return {"pb": pb, "offering": dims.get("offering", ""), "journey": dims.get("journey", ""),
            "audience": dims.get("audience", "b2c"), "transaction": dims.get("transaction", ""),
            "portfolio": dims.get("portfolio", "none"), "primary": dims.get("primary_action", "")}


def _wrong(text: str, k: dict[str, Any]) -> tuple[str, str] | None:
    """(code, severity) when `text` says something this business isn't."""
    pb = k["pb"]
    food = pb.key in _FOOD_PLAYBOOKS or k["offering"] in {"menu", "weighed_product"}
    classy = pb.key in _CLASS_PLAYBOOKS or k["offering"] in {"plan", "class"}
    if (_CLASSES.search(text) or _CLASS_BOOKING.search(text)) and not classy:
        return "class_language_for_non_class_business", "fail"
    if _PROCUREMENT.search(text) and k["audience"] == "b2c":
        return "procurement_language_for_consumer_business", "fail"
    if _MENU.search(text) and not food:
        return "menu_for_non_food_business", "fail"
    if _MENU.search(text) and k["offering"] == "weighed_product":
        # A meat shop's "menu" can be right (a cuts menu) or odd: a human look, not a repair.
        return "menu_for_weighed_products", "flag"
    if _CART.search(text) and not (k["journey"] == "order" and k["transaction"] == "online"):
        return "cart_without_online_ordering", "fail"
    if _ROOMS.search(text) and k["offering"] != "stay":
        return "rooms_for_non_stay_business", "fail"
    if _TABLE.search(text) and not food:
        return "table_booking_for_non_food_business", "fail"
    if _PROJECTS.search(text) and pb.key not in _PROJECT_PLAYBOOKS and k["offering"] not in {
            "property", "portfolio", "b2b_catalogue"}:
        # "Featured projects" on a law firm or a clinic is the wrong business.
        severity = "fail" if k["offering"] in {"service", "menu", "plan", "class", "stay"} else "flag"
        return "projects_for_non_project_business", severity
    if _GENERIC_SERVICES.match(text) and k["offering"] in {"menu", "weighed_product", "product", "plan", "class",
                                                           "property", "stay", "portfolio"}:
        return "generic_services_heading", "fail"
    return None


def validate(
    payload: dict[str, Any], bp: BusinessBlueprint, direction: CreativeDirection
) -> tuple[dict[str, Any], list[Finding]]:
    """Check the whole payload and repair what fails. Returns (payload, findings)."""
    k = _kind(bp, direction)
    pb = k["pb"]
    findings: list[Finding] = []
    # Every page of the site, not only its home.
    every_section = [s for page in payload["pages"] for s in page["sections"]]
    # Where "talk to us" lives: its own page on a multi-page site.
    contact_href = next((str(n.get("path")) for n in payload.get("navigation", [])
                         if str(n.get("path")) in {"/visit", "/contact"}), "#contact")

    def check(where: str, text: str, replacement: str | None) -> str | None:
        """The text to keep: itself, a replacement, or None to remove."""
        if not text:
            return text
        wrong = _wrong(text, k)
        if not wrong:
            return text
        code, severity = wrong
        if severity == "flag":
            findings.append(Finding(code, severity, where, text))
            return text
        fixed = replacement if replacement and not _wrong(replacement, k) else None
        findings.append(Finding(code, severity, where, text, fixed or ""))
        return fixed

    primary_cta = _CTA.get(k["primary"], "")

    # Navigation: the trade's own label for the browse section.
    kept_nav = []
    for item in payload.get("navigation", []):
        label = check("navigation", str(item.get("label", "")), pb.browse_label)
        if label:
            kept_nav.append({**item, "label": label})
    payload["navigation"] = kept_nav

    theme = payload.get("theme_hints") or {}
    nav_cta = theme.get("nav_cta")
    if isinstance(nav_cta, dict):
        before = str(nav_cta.get("label", ""))
        label = check("nav_cta", before, primary_cta)
        if label:
            nav_cta["label"] = label
            if label != before and nav_cta.get("href") == "#shop":
                nav_cta["href"] = contact_href
        else:
            theme.pop("nav_cta", None)

    for section in every_section:
        content = section.get("content") or {}
        sid = section["section_type_id"]
        for key in ("title", "headline"):
            if isinstance(content.get(key), str) and key == "title":
                replacement = pb.browse_title if content.get("anchor") == "shop" else None
                title = check(f"{sid}.title", content["title"], replacement)
                if title is None:
                    content["title"] = pb.browse_title if content.get("anchor") == "shop" else ""
                else:
                    content["title"] = title
        for key in ("cta_label", "order_label"):
            if isinstance(content.get(key), str) and content[key]:
                before = content[key]
                label = check(f"{sid}.{key}", content[key], primary_cta)
                if label:
                    content[key] = label
                    if label != before and key == "cta_label" and content.get("cta_url") == "#shop":
                        # A button that now says what customers do goes to where they do it.
                        content["cta_url"] = contact_href
                else:
                    content.pop(key, None)
                    if key == "cta_label":
                        content.pop("cta_url", None)

    # The media truth policy, enforced on the payload: a drawn picture may set a
    # mood (hero, story, closing band) but never stand in for a factual thing —
    # a developer's project, a photographer's or a studio's work.
    from platform_core.interview.media_director import evidence_led

    drawn = {str(m.asset_id) for m in bp.media_assets if m.source == "AI_GENERATED"}
    if drawn and evidence_led(bp, direction):
        for section in every_section:
            if section["section_type_id"] not in {"product_showcase", "category_showcase", "gallery"}:
                continue
            content = section.get("content") or {}
            for holder in [content, *[r for key in ("items", "categories") for r in content.get(key) or []
                                      if isinstance(r, dict)]]:
                if str(holder.get("image_asset_id", "")) in drawn:
                    findings.append(Finding("drawn_picture_as_evidence", "fail", section["section_type_id"],
                                            str(holder.get("name") or "image")))
                    holder.pop("image_asset_id", None)

    # A portfolio-led trade must present its work.
    if k["portfolio"] == "heavy":
        shows_work = any(s["section_type_id"] in {"gallery", "product_showcase", "category_showcase"}
                         for s in every_section)
        if not shows_work:
            findings.append(Finding("portfolio_without_work", "flag", "page",
                                    "no section presents the work yet — owner photos needed"))
    return payload, findings
