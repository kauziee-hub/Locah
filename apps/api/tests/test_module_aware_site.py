"""P1-10C: the website and the Marketplace offer what a business's tools can
actually do (Founder §14–16; Guide §4).

Pure tests pin the decision (`decide`, `auto_sections`). Database tests build a
business through the owner API, switch tools on and set them up, and read the
public site, the Marketplace listing and the Workspace panel back — the same
paths a visitor and the owner take.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.events.registry import load_subscribers, subscribers_for
from platform_core.services.marketplace_indexing import MarketplaceIndexingService
from platform_core.website.capabilities import auto_sections, decide
from sqlalchemy.ext.asyncio import AsyncSession
from test_marketplace_discovery import (  # noqa: F401 — `owner` is a fixture, registered by import
    _create_business,
    _publish_sections,
    _run_db,
    _search,
    needs_db,
    owner,
)

# ---------------------------------------------------------------------------
# Pure: which actions are real, and which one leads
# ---------------------------------------------------------------------------


def test_actions_come_from_readiness_not_from_the_category() -> None:
    nothing = decide({}, {}, ["booking_led"], has_phone=True)
    assert not any(nothing[k] for k in ("order", "book", "join", "enquire", "request_quote"))
    assert (nothing["primary"], nothing["primary_label"]) == ("call", "Call")
    assert decide({}, {}, [], has_whatsapp=True)["primary"] == "whatsapp"
    assert decide({}, {}, [])["primary"] is None

    gym = decide({"bookings": True, "memberships": True}, {"class": 2}, ["booking_led", "subscription_led"])
    assert gym["book"] and gym["join"] and not gym["order"]
    assert (gym["primary"], gym["primary_path"]) == ("book", "/book")
    # The same tools, a business that leads with its plans.
    assert decide({"bookings": True, "memberships": True}, {}, ["subscription_led"])["primary"] == "join"


def test_quote_and_site_visit_need_their_tools_and_something_to_visit() -> None:
    fabricator = decide({"quotes": True, "leads": True}, {}, ["quote_led"])
    assert fabricator["request_quote"] and fabricator["primary"] == "request_quote"
    assert fabricator["primary_path"] == "/enquire?purpose=quote_request"
    # Quotes switched on but nowhere for the request to land: no quote button.
    assert not decide({"quotes": True}, {}, ["quote_led"])["request_quote"]

    builder = decide({"leads": True}, {"property_project": 1}, ["project_led"])
    assert builder["site_visit"] and not builder["test_drive"]
    assert not decide({"leads": True}, {"product": 3}, [])["site_visit"]
    assert decide({"leads": True}, {"vehicle": 2}, [])["test_drive"]
    assert decide({"orders": True}, {"cause": 1}, ["donation_led"])["primary"] == "donate"
    assert not decide({"orders": True}, {"product": 1}, [])["donate"]


def test_digital_only_publishes_no_address() -> None:
    assert decide({}, {}, ["digital_only"])["show_address"] is False
    assert decide({}, {}, ["walk_in"])["show_address"] is True


def test_a_ready_tool_adds_its_section_only_where_the_design_has_none() -> None:
    # The catalogue section is the catalogue's (a menu can be browsed without
    # online ordering); Orders only decides whether it carries an Add button.
    flags = {**decide({"memberships": True, "offerings-catalog": True, "orders": True, "reviews": True},
                      {"product": 2}, []), "catalogue_label": "Products"}
    types = {s["section_type_id"]: s for s in auto_sections(flags, {"hero", "contact"}, hidden=[],
                                                            published_reviews=0, traits=[])}
    assert set(types) == {"plans_section", "offerings_list"}
    assert types["plans_section"]["content"]["anchor"] == "plans"
    assert types["offerings_list"]["module_binding"] == {"module": "offerings-catalog"}
    assert all(s["is_auto"] for s in types.values())
    # The owner's own menu already shows the shop; their own plans already show plans.
    assert auto_sections(flags, {"menu_section", "plans_section"}, hidden=[], published_reviews=0, traits=[]) == []
    # Hidden by the owner stays hidden.
    assert [s["module"] for s in auto_sections(flags, set(), hidden=["memberships"], published_reviews=0,
                                               traits=[])] == ["offerings-catalog"]
    # Reviews appear once there is a review to show.
    with_reviews = auto_sections(flags, {"menu_section", "plans_section"}, hidden=[], published_reviews=2, traits=[])
    assert [s["section_type_id"] for s in with_reviews] == ["reviews_section"]


def test_booking_sections_follow_what_is_bookable() -> None:
    # site_capabilities hands auto_sections the live offering counts as `_kinds`.
    classes = {**decide({"bookings": True}, {"class": 1}, []), "_kinds": {"class": 1}}
    [section] = auto_sections(classes, set(), hidden=[], published_reviews=0, traits=[])
    assert section["section_type_id"] == "classes_section"
    assert section["content"]["offering_types"] == ["class", "class_session"]
    rooms = {**decide({"bookings": True}, {"room_type": 1}, []), "_kinds": {"room_type": 1}}
    assert auto_sections(rooms, set(), hidden=[], published_reviews=0, traits=[])[0]["section_type_id"] == "rooms_section"
    salon = {**decide({"bookings": True}, {"service": 4}, []), "_kinds": {"service": 4}}
    [band] = auto_sections(salon, set(), hidden=[], published_reviews=0, traits=[])
    assert (band["section_type_id"], band["content"]["cta_url"]) == ("cta_band", "/book")


def test_an_enquiry_form_is_added_for_businesses_that_lead_with_enquiries() -> None:
    shop = decide({"leads": True}, {"product": 1}, [])
    assert auto_sections(shop, set(), hidden=[], published_reviews=0, traits=[]) == []
    fabricator = decide({"leads": True, "quotes": True}, {}, ["quote_led"])
    [form] = auto_sections(fabricator, set(), hidden=[], published_reviews=0, traits=["quote_led"])
    assert (form["section_type_id"], form["content"]["title"]) == ("enquiry_form", "Get a quote")


def test_what_makes_a_tool_ready_reindexes_the_listing() -> None:
    load_subscribers()
    for event in ("membership.plan.created", "membership.plan.archived", "workforce.member_created",
                  "fulfilment.settings_updated", "business.traits.changed", "website.auto_sections.changed",
                  "module.enabled"):
        assert "marketplace.index" in {s.subscriber_id for s in subscribers_for(event)}, event


# ---------------------------------------------------------------------------
# Database: a gym turns Memberships on and the site and listing follow
# ---------------------------------------------------------------------------


def _reindex(business_id: str) -> None:
    """What the marketplace.index subscriber does when one of its events lands."""

    async def _go(session: AsyncSession) -> None:
        await MarketplaceIndexingService.reindex_business(
            session, business_id=uuid.UUID(business_id), correlation_id=str(uuid.uuid4()), trigger="test")

    _run_db(_go)


def _home(client: TestClient, slug: str) -> dict[str, Any]:
    resp = client.get(f"/v1/public/websites/{slug}")
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json()["data"])


def _section_types(page: dict[str, Any]) -> list[str]:
    return [s["section_type_id"] for s in page["page"]["sections"]]


def _listing(client: TestClient, tag: str, business_id: str) -> dict[str, Any]:
    return next(b for b in _search(client, q=tag)["businesses"] if b["business_id"] == business_id)


@needs_db
def test_memberships_become_a_plans_section_and_a_join_action_without_a_rebuild(owner: dict[str, str]) -> None:  # noqa: F811
    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]
    business = _create_business(client, owner, name=f"Iron Temple {tag}", description="Strength gym and classes")
    bid, slug = business["id"], business["slug"]
    _publish_sections(bid, [{"type": "contact", "content": {"address": "12, MG Road, Bengaluru 560001"}}],
                      contact={"phone": "+91 98450 12345"})

    before = _home(client, slug)
    assert not before["capabilities"]["join"]
    assert "plans_section" not in _section_types(before)
    assert before["capabilities"]["primary"] == "call"

    # Switched on is not ready: no plan is published yet.
    assert client.post(f"/v1/b/{bid}/modules/memberships/enable", headers=owner).status_code == 200
    assert not _home(client, slug)["capabilities"]["join"]
    panel = client.get(f"/v1/b/{bid}/website/capabilities", headers=owner).json()["data"]
    waiting = {a["key"]: a for a in panel["actions"]}
    assert waiting["join"]["live"] is False and waiting["join"]["next_step"]

    plan = client.post(f"/v1/platform/businesses/{bid}/membership-plans", headers=owner, json={
        "name": f"Monthly {tag}", "price_amount": 1500, "duration_days": 30, "status": "active",
        "visibility": "public"})
    assert plan.status_code == 200, plan.text
    hidden_plan = client.post(f"/v1/platform/businesses/{bid}/membership-plans", headers=owner, json={
        "name": "Staff only", "price_amount": 0, "duration_days": 30, "status": "active", "visibility": "private"})
    assert hidden_plan.status_code == 200, hidden_plan.text
    assert client.patch(f"/v1/platform/businesses/{bid}/traits", headers=owner,
                        json={"traits": {"subscription_led": True}}).status_code == 200

    after = _home(client, slug)
    assert after["capabilities"]["join"] is True
    assert (after["capabilities"]["primary"], after["capabilities"]["primary_path"]) == ("join", "/#plans")
    types = _section_types(after)
    # The tool's section sits above the contact details, marked as the tool's.
    assert types.index("plans_section") < types.index("contact")
    auto = next(s for s in after["page"]["sections"] if s["section_type_id"] == "plans_section")
    assert auto["is_auto"] and auto["module"] == "memberships"
    # The Plans section is filled from real, public plans only.
    plans = client.get(f"/v1/public/websites/{slug}/plans").json()["data"]["plans"]
    assert [p["title"] for p in plans] == [f"Monthly {tag}"]

    # The Marketplace listing offers the same thing, landing on the same place.
    _reindex(bid)
    listing = _listing(client, tag, bid)
    join = next(a for a in listing["actions"] if a["action"] == "join")
    assert join["href"] == f"/{slug}#plans"
    assert listing["actions"][0]["action"] == "join"  # a subscription-led gym leads with its plans

    # The owner hides the section: gone from the site, and the listing loses
    # the action that would have landed there.
    hide = client.patch(f"/v1/b/{bid}/website/auto-sections", headers=owner,
                        json={"module": "memberships", "hidden": True})
    assert hide.status_code == 200, hide.text
    hidden_home = _home(client, slug)
    assert "plans_section" not in _section_types(hidden_home)
    # The header's main button never points at a section that is not there.
    assert hidden_home["capabilities"]["primary"] != "join"
    panel = client.get(f"/v1/b/{bid}/website/capabilities", headers=owner).json()["data"]
    assert {s["module"]: s["state"] for s in panel["auto_sections"]}["memberships"] == "hidden"
    _reindex(bid)
    assert "join" not in {a["action"] for a in _listing(client, tag, bid)["actions"]}
    assert client.patch(f"/v1/b/{bid}/website/auto-sections", headers=owner,
                        json={"module": "payroll", "hidden": True}).status_code == 422

    # Archiving the only public plan takes the action away again.
    client.patch(f"/v1/b/{bid}/website/auto-sections", headers=owner, json={"module": "memberships", "hidden": False})
    archived = client.post(f"/v1/platform/businesses/{bid}/membership-plans/{plan.json()['data']['id']}/archive",
                           headers=owner, json={})
    assert archived.status_code == 200, archived.text
    gone = _home(client, slug)
    assert gone["capabilities"]["join"] is False and "plans_section" not in _section_types(gone)


@needs_db
def test_a_plan_enquiry_and_a_quote_request_land_as_leads(owner: dict[str, str]) -> None:  # noqa: F811
    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]
    business = _create_business(client, owner, name=f"Steel Works {tag}", description="Gates and grills to order")
    bid, slug = business["id"], business["slug"]
    for module in ("leads", "quotes", "memberships"):
        assert client.post(f"/v1/b/{bid}/modules/{module}/enable", headers=owner).status_code == 200
    assert client.patch(f"/v1/platform/businesses/{bid}/traits", headers=owner,
                        json={"traits": {"quote_led": True}}).status_code == 200

    home = _home(client, slug)
    assert home["capabilities"]["request_quote"] and home["capabilities"]["primary"] == "request_quote"
    form = next(s for s in home["page"]["sections"] if s["section_type_id"] == "enquiry_form")
    assert form["is_auto"] and form["content"]["title"] == "Get a quote"
    _reindex(bid)
    listing = _listing(client, tag, bid)
    assert listing["actions"][0] == {"action": "request_quote", "label": "Get a quote",
                                     "href": f"/{slug}/enquire?purpose=quote_request"}
    assert "enquire" not in {a["action"] for a in listing["actions"]}

    sent = client.post(f"/v1/public/websites/{slug}/enquiries", json={
        "name": "Ravi", "phone": "9840012345", "message": "Main gate, 12 ft, MS", "purpose": "quote_request"})
    assert sent.status_code == 200, sent.text

    plan = client.post(f"/v1/platform/businesses/{bid}/membership-plans", headers=owner, json={
        "name": "Annual maintenance", "price_amount": 6000, "duration_days": 365, "status": "active",
        "visibility": "public"}).json()["data"]
    joined = client.post(f"/v1/public/websites/{slug}/enquiries", json={
        "name": "Meena", "email": "meena@example.com", "purpose": "membership", "plan_id": plan["id"]})
    assert joined.status_code == 200, joined.text
    private = client.post(f"/v1/platform/businesses/{bid}/membership-plans", headers=owner, json={
        "name": "Internal", "price_amount": 1, "duration_days": 30, "status": "active",
        "visibility": "private"}).json()["data"]
    refused = client.post(f"/v1/public/websites/{slug}/enquiries", json={
        "name": "Meena", "email": "meena@example.com", "purpose": "membership", "plan_id": private["id"]})
    assert refused.status_code == 422, refused.text

    leads = client.get(f"/v1/platform/businesses/{bid}/leads", headers=owner)
    assert leads.status_code == 200, leads.text
    origins = [lead.get("origin_context") or {} for lead in leads.json()["data"]]
    assert {"purpose": "quote_request", "purpose_label": "Quote request", "channel": "website"}.items() <= next(
        o for o in origins if o.get("purpose") == "quote_request").items()
    assert next(o for o in origins if o.get("purpose") == "membership")["plan_title"] == "Annual maintenance"


@needs_db
def test_digital_only_business_shows_no_address_anywhere(owner: dict[str, str]) -> None:  # noqa: F811
    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]
    business = _create_business(client, owner, name=f"Pixel Tutor {tag}", description="Online coding classes")
    bid, slug = business["id"], business["slug"]
    _publish_sections(bid, [
        {"type": "location_list", "content": {"locations": [{"name": "Studio", "address": "4 Park St"}]}},
        {"type": "contact", "content": {"address": "4, Park Street, Kolkata 700016", "map_url": "https://maps"}},
    ])
    assert "location_list" in _section_types(_home(client, slug))
    assert client.patch(f"/v1/platform/businesses/{bid}/traits", headers=owner,
                        json={"traits": {"digital_only": True}}).status_code == 200
    home = _home(client, slug)
    assert "location_list" not in _section_types(home)
    contact = next(s for s in home["page"]["sections"] if s["section_type_id"] == "contact")
    assert "address" not in contact["content"] and "map_url" not in contact["content"]
    assert home["capabilities"]["show_address"] is False


def test_the_main_button_skips_an_action_with_nowhere_to_land() -> None:
    from platform_core.website.capabilities import pick_primary

    flags = decide({"memberships": True, "bookings": True}, {}, ["subscription_led"])
    assert pick_primary(flags, ["subscription_led"], landings={"join": "/plans#plans"})["primary_path"] == "/plans#plans"
    fallback = pick_primary(flags, ["subscription_led"], landings={"join": None})
    assert (fallback["primary"], fallback["primary_path"]) == ("book", "/book")
    assert pick_primary({}, [], landings={}, has_phone=True) == {"primary": "call", "primary_label": "Call",
                                                                  "primary_path": None}
