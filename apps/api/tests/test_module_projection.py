"""Module → capability → Workspace → Website projection, end to end.

Each test drives the real API (the same calls the Workspace makes) against a
real database and reads back what the Workspace navigation and the public
website receive. The chain under test:

    Module registry → Entitlement → activation → setup readiness (+ hard
    dependencies) → /v1/me/context navigation state and terms → website
    capabilities, tool sections (module_binding) and navigation → the owning
    module's public read contract.

Pure pieces (catalogue naming, auto sections, navigation filtering, Workspace
terms) are tested without a database at the end.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.services.website_publish import _navigation
from platform_core.services.workspace_projection import navigation_state, workspace_terms
from platform_core.website.capabilities import auto_sections, catalogue_label, decide, flags_for
from platform_testing.phase_b import create_business, new_identity, primary_location, sql

needs_db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)


# ------------------------------------------------------------------ helpers
def _owner(monkeypatch: Any) -> dict[str, str]:
    return cast(dict[str, str], new_identity(monkeypatch)[1])


def _business(owner: dict[str, str], business_type: str = "other") -> str:
    """A business whose website the public can open (unlisted: reachable by its
    address, not yet searchable) — what every public-surface test needs."""
    bid = create_business(client, owner, business_type=business_type)
    r = client.post(f"/v1/b/{bid}/marketplace/visibility", json={"visibility": "unlisted"}, headers=owner)
    assert r.status_code == 200, r.text
    return str(bid)


def _slug(bid: str) -> str:
    return str(sql("select slug from businesses where id = cast(:b as uuid)", b=bid)[0][0])


def _context(headers: dict[str, str], bid: str) -> dict[str, Any]:
    r = client.get("/v1/me/context", headers={**headers, "X-Operating-Context": "business", "X-Business-Id": bid})
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json()["data"])


def _preview(owner: dict[str, str], bid: str) -> dict[str, Any]:
    token = client.get(f"/v1/b/{bid}/website/preview-token", headers=owner).json()["data"]["token"]
    r = client.get(f"/v1/public/websites/{_slug(bid)}", params={"preview_token": token})
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json()["data"])


def _live(bid: str) -> dict[str, Any]:
    r = client.get(f"/v1/public/websites/{_slug(bid)}")
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json()["data"])


def _publish(owner: dict[str, str], bid: str) -> None:
    r = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert r.status_code == 200, r.text


def _offering(owner: dict[str, str], bid: str, title: str, kind: str, price: float | None = 250, **extra: Any) -> str:
    body: dict[str, Any] = {"title": title, "offering_type": kind, "status": "active", "visibility": "public", **extra}
    if price is not None:
        body.update({"price_amount": price, "price_type": "fixed"})
    r = client.post(f"/v1/platform/businesses/{bid}/products", json=body, headers=owner)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["id"])


def _enable(owner: dict[str, str], bid: str, *modules: str) -> None:
    for module in modules:
        r = client.post(f"/v1/b/{bid}/modules/{module}/enable", headers=owner)
        assert r.status_code == 200, f"{module}: {r.text}"


def _deactivate(owner: dict[str, str], bid: str, module: str) -> None:
    r = client.post(f"/v1/b/{bid}/modules/{module}/deactivate", headers=owner)
    assert r.status_code == 200, r.text


def _tool_sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in payload["page"]["sections"] if s.get("is_auto")]


def _public_offerings(bid: str, **params: Any) -> list[dict[str, Any]]:
    r = client.get(f"/v1/public/websites/{_slug(bid)}/offerings", params=params)
    assert r.status_code == 200, r.text
    return cast(list[dict[str, Any]], r.json()["data"]["offerings"])


def _member_with(owner: dict[str, str], bid: str, monkeypatch: Any, permissions: list[str]) -> dict[str, str]:
    person, headers = new_identity(monkeypatch)
    inv = client.post(f"/v1/b/{bid}/team/invitations", json={"identity_id": str(person), "role": "member"},
                      headers=owner)
    assert inv.status_code == 200, inv.text
    membership = inv.json()["data"]["id"]
    assert client.post(f"/v1/b/{bid}/team/members/{membership}/activate", headers=owner).status_code == 200
    granted = client.post(f"/v1/b/{bid}/team/members/{membership}/permissions",
                          json={"permissions": permissions}, headers=owner)
    assert granted.status_code == 200, granted.text
    return cast(dict[str, str], headers)


# ------------------------------------------------------------------ 1. offerings activation
@needs_db
def test_catalogue_activation_projects_into_workspace_and_website(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "restaurant")
    before = _preview(owner, bid)
    assert not before["capabilities"]["catalogue"]
    assert _tool_sections(before) == []

    _enable(owner, bid, "offerings-catalog")
    # Switched on, nothing listed yet: setup required, not a working Menu.
    assert _context(owner, bid)["navigation_modules"]["offerings-catalog"] == "setup_required"
    assert _tool_sections(_preview(owner, bid)) == []

    _offering(owner, bid, "Paneer Biryani", "menu_item", 180)
    context = _context(owner, bid)
    assert context["navigation_modules"]["offerings-catalog"] == "active"
    assert context["terms"]["offerings"] == "Menu"
    preview = _preview(owner, bid)
    [menu] = _tool_sections(preview)
    assert menu["section_type_id"] == "menu_section"
    assert menu["module_binding"] == {"module": "offerings-catalog"}
    assert menu["content"]["title"] == "Menu"
    assert {"label": "Menu", "path": "/#shop"} in preview["navigation"]
    assert preview["capabilities"]["catalogue_label"] == "Menu"


# ------------------------------------------------------------------ 2. real offering data
@needs_db
def test_the_website_lists_the_real_offering_with_its_price_and_stock(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "retail")
    _enable(owner, bid, "offerings-catalog", "inventory")
    product = _offering(owner, bid, "Brass Lamp", "product", 1200, track_inventory=True, low_stock_threshold=2)
    rows = _public_offerings(bid)
    assert [(r["id"], r["title"], r["price_amount"]) for r in rows] == [(product, "Brass Lamp", 1200.0)]
    assert rows[0]["availability"] is None  # stock tracked but not yet recorded: not claimed either way
    loc = primary_location(client, owner, bid)
    r = client.post(f"/v1/platform/businesses/{bid}/inventory/opening-stock",
                    json={"offering_id": product, "location_id": loc, "quantity": 1}, headers=owner)
    assert r.status_code == 200, r.text
    [row] = _public_offerings(bid)
    assert row["availability"] == "low_stock"
    assert "quantity" not in row and "quantity_on_hand" not in row  # never a number


# ------------------------------------------------------------------ 3. bookings
@needs_db
def test_bookings_without_anything_bookable_offer_no_booking(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "salon")
    _enable(owner, bid, "offerings-catalog", "bookings")
    # A menu item is not something the booking engine can schedule.
    _offering(owner, bid, "Filter Coffee", "menu_item", 40)
    assert _context(owner, bid)["navigation_modules"]["bookings"] == "setup_required"
    payload = _preview(owner, bid)
    assert payload["capabilities"]["book"] is False
    assert all(s.get("module") != "bookings" for s in _tool_sections(payload))
    refused = client.get(f"/v1/public/websites/{_slug(bid)}/booking/options")
    assert refused.status_code == 422
    loc = primary_location(client, owner, bid)
    slots = client.post(f"/v1/public/websites/{_slug(bid)}/booking/slots",
                        json={"location_id": loc, "date": "2026-11-14", "mode": "appointment"})
    assert slots.status_code == 422 and slots.json()["error"]["details"]["code"] == "bookings_disabled"

    service = _offering(owner, bid, "Haircut", "service", 300, attributes={"duration_minutes": 45})
    context = _context(owner, bid)
    assert context["navigation_modules"]["bookings"] == "active"
    assert context["terms"]["offerings"] == "Products & services"  # a coffee and a haircut
    payload = _preview(owner, bid)
    assert payload["capabilities"]["book"] is True
    assert any(s.get("module_binding") == {"module": "bookings"} for s in _tool_sections(payload))
    options = client.get(f"/v1/public/websites/{_slug(bid)}/booking/options")
    assert options.status_code == 200, options.text
    slots = client.post(f"/v1/public/websites/{_slug(bid)}/booking/slots",
                        json={"location_id": loc, "offering_id": service, "date": "2026-11-14"})
    assert slots.status_code == 200, slots.text


@needs_db
def test_a_table_makes_a_restaurant_bookable_without_bookable_dishes(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "restaurant")
    _enable(owner, bid, "offerings-catalog", "bookings")
    _offering(owner, bid, "Dosa", "menu_item", 90)
    assert _preview(owner, bid)["capabilities"]["book"] is False
    loc = primary_location(client, owner, bid)
    r = client.post(f"/v1/platform/businesses/{bid}/bookings/resources",
                    json={"location_id": loc, "resource_type": "table", "name": "T1", "allocation_mode": "pooled",
                          "capacity": 4}, headers=owner)
    assert r.status_code == 200, r.text
    assert _preview(owner, bid)["capabilities"]["book"] is True


@needs_db
def test_an_archived_or_private_service_cannot_be_booked_by_its_id(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner)
    _enable(owner, bid, "offerings-catalog", "bookings")
    _offering(owner, bid, "Consultation", "service", 500)
    hidden = _offering(owner, bid, "Staff only", "service", 0, visibility="private")
    loc = primary_location(client, owner, bid)
    r = client.post(f"/v1/public/websites/{_slug(bid)}/booking/slots",
                    json={"location_id": loc, "offering_id": hidden, "date": "2026-11-14"})
    assert r.status_code == 404


# ------------------------------------------------------------------ 4. orders
@needs_db
def test_orders_offer_a_cart_only_when_checkout_can_complete(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "retail")
    _enable(owner, bid, "offerings-catalog", "orders", "fulfilment")
    product = _offering(owner, bid, "Notebook", "product", 60)
    # Fulfilment's defaults (pickup on) are what checkout uses, so ordering is
    # live as soon as Orders and Fulfilment are on.
    assert _preview(owner, bid)["capabilities"]["order"] is True
    # The owner switches pickup off and has no delivery zone: nothing can hand an
    # order over — no cart, no dead "Order now", and a direct checkout is refused.
    r = client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": False}, headers=owner)
    assert r.status_code == 200, r.text
    payload = _preview(owner, bid)
    assert payload["capabilities"]["order"] is False
    assert payload["capabilities"]["catalogue"] is True
    panel = client.get(f"/v1/b/{bid}/website/capabilities", headers=owner).json()["data"]
    order = next(a for a in panel["actions"] if a["key"] == "order")
    assert order["live"] is False and "pickup or delivery" in order["next_step"]

    r = client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": True}, headers=owner)
    assert r.status_code == 200, r.text
    payload = _preview(owner, bid)
    assert payload["capabilities"]["order"] is True
    assert payload["capabilities"]["primary"] == "order"
    placed = client.post(f"/v1/public/websites/{_slug(bid)}/checkout", json={
        "items": [{"offering_id": product, "quantity": 1}], "fulfilment_mode": "pickup",
        "payment_method": "cod", "guest": {"name": "Asha", "email": f"asha-{uuid.uuid4().hex[:6]}@example.com"}})
    assert placed.status_code == 200, placed.text

    _deactivate(owner, bid, "orders")
    assert _preview(owner, bid)["capabilities"]["order"] is False
    refused = client.post(f"/v1/public/websites/{_slug(bid)}/checkout", json={
        "items": [{"offering_id": product, "quantity": 1}], "fulfilment_mode": "pickup",
        "payment_method": "cod", "guest": {"name": "Asha", "email": "asha@example.com"}})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"]["code"] == "orders_unavailable"


# ------------------------------------------------------------------ 5 + 8. disable, re-enable, idempotency
@needs_db
def test_deactivation_hides_without_deleting_and_reactivation_returns_exactly_once(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "salon")
    _enable(owner, bid, "offerings-catalog")
    service = _offering(owner, bid, "Facial", "service", 900)
    _publish(owner, bid)
    version = _live(bid)["version"]["id"]
    assert [s["module"] for s in _tool_sections(_live(bid))] == ["offerings-catalog"]

    _deactivate(owner, bid, "offerings-catalog")
    assert _context(owner, bid)["navigation_modules"]["offerings-catalog"] == "deactivated"
    live = _live(bid)
    assert live["capabilities"]["catalogue"] is False
    assert _tool_sections(live) == []
    assert all(n.get("path") != "/#shop" for n in live["navigation"])
    assert _public_offerings(bid) == []
    # The record is the business's, kept for the day it comes back (never deleted).
    [(kept,)] = sql("select count(*) from offerings_catalog_offerings where id = cast(:o as uuid) "
                    "and deleted_at is null and status = 'active'", o=service)
    assert kept == 1

    for _ in range(2):  # switching on twice adds nothing twice
        _enable(owner, bid, "offerings-catalog")
    live = _live(bid)
    assert live["version"]["id"] == version  # no silent publish
    assert [s["module"] for s in _tool_sections(live)] == ["offerings-catalog"]
    assert [n["path"] for n in live["navigation"]].count("/#shop") == 1
    assert [o["id"] for o in _public_offerings(bid)] == [service]
    [(enabled,)] = sql("select count(*) from platform_outbox_events where business_id = cast(:b as uuid) "
                       "and event_type = 'module.enabled' and payload->>'module_id' = 'offerings-catalog'", b=bid)
    [(deactivated,)] = sql("select count(*) from platform_outbox_events where business_id = cast(:b as uuid) "
                           "and event_type = 'module.deactivated'", b=bid)
    assert enabled >= 3 and deactivated == 1  # every change is a domain fact the subscribers react to


# ------------------------------------------------------------------ 6. permission
@needs_db
def test_a_member_without_the_permission_gets_no_destination_and_no_data(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner)
    _enable(owner, bid, "offerings-catalog")
    _offering(owner, bid, "Tote bag", "product", 300)
    member = _member_with(owner, bid, monkeypatch, ["bookings.read"])
    context = _context(member, bid)
    assert context["navigation_modules"]["offerings-catalog"] == "active"  # the business has it…
    assert "offerings.read" not in context["permissions"]  # …this person may not open it
    denied = client.get(f"/v1/platform/businesses/{bid}/products",
                        headers={**member, "X-Operating-Context": "business", "X-Business-Id": bid})
    assert denied.status_code == 403


# ------------------------------------------------------------------ 7. location
@needs_db
def test_stock_availability_follows_the_selected_location(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "retail")
    _enable(owner, bid, "offerings-catalog", "inventory")
    main = primary_location(client, owner, bid)
    branch = client.post(f"/v1/platform/businesses/{bid}/locations", json={"name": "Branch"},
                         headers=owner).json()["data"]["id"]
    product = _offering(owner, bid, "Ceramic mug", "product", 350, track_inventory=True)
    r = client.post(f"/v1/platform/businesses/{bid}/inventory/opening-stock",
                    json={"offering_id": product, "location_id": main, "quantity": 12}, headers=owner)
    assert r.status_code == 200, r.text
    assert _public_offerings(bid)[0]["availability"] == "available"
    assert _public_offerings(bid, location_id=main)[0]["availability"] == "available"
    # Stocked at the main shop, not at the branch: not falsely offered there.
    assert _public_offerings(bid, location_id=branch)[0]["availability"] == "out_of_stock"


# ------------------------------------------------------------------ 9. draft / published
@needs_db
def test_a_bound_section_is_a_placeholder_in_preview_and_absent_live(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "restaurant")
    _enable(owner, bid, "offerings-catalog")
    _offering(owner, bid, "Idli", "menu_item", 50)
    page = next(p for p in client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]["draft"]["pages"]
                if p["page_type"] == "home")
    added = client.post(f"/v1/b/{bid}/website/pages/{page['id']}/sections",
                        json={"section_type_id": "menu_section", "content": {"title": "Our menu"}}, headers=owner)
    assert added.status_code == 200, added.text
    assert added.json()["data"]["module_binding"] == {"module": "offerings-catalog"}
    _publish(owner, bid)
    assert "menu_section" in [s["section_type_id"] for s in _live(bid)["page"]["sections"]]

    _deactivate(owner, bid, "offerings-catalog")
    preview = _preview(owner, bid)
    stored = next(s for s in preview["page"]["sections"] if s["section_type_id"] == "menu_section")
    assert stored["module_unavailable"] is True and stored["unavailable_reason"] == "module_not_active"
    assert "menu_section" not in [s["section_type_id"] for s in _live(bid)["page"]["sections"]]


@needs_db
def test_archived_items_no_longer_name_the_list(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, "salon")
    _enable(owner, bid, "offerings-catalog")
    old = _offering(owner, bid, "Shampoo", "product", 200)
    _offering(owner, bid, "Haircut", "service", 300)
    assert _context(owner, bid)["terms"]["offerings"] == "Products & services"
    r = client.post(f"/v1/platform/businesses/{bid}/products/{old}/archive", json={}, headers=owner)
    assert r.status_code == 200, r.text
    assert _context(owner, bid)["terms"]["offerings"] == "Services"


# ------------------------------------------------------------------ entitlement (Doc 08 §20.2)
@needs_db
def test_a_stale_activation_without_entitlement_projects_nothing(monkeypatch: Any) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner)
    _enable(owner, bid, "leads")
    assert _preview(owner, bid)["capabilities"]["enquire"] is True
    # The commercial grant goes; the activation row stays behind, stale.
    revoked = client.patch(f"/v1/platform/businesses/{bid}/entitlements/overrides",
                           json={"modules": {"leads": {"entitled": False}}}, headers=owner)
    assert revoked.status_code == 200, revoked.text
    assert _context(owner, bid)["navigation_modules"]["leads"] == "not_entitled"
    assert _preview(owner, bid)["capabilities"]["enquire"] is False
    refused = client.post(f"/v1/public/websites/{_slug(bid)}/enquiries",
                          json={"name": "Ravi", "phone": "+919876543210", "message": "Do you deliver to Adyar?"})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"]["code"] == "enquiries_off"


# ------------------------------------------------------------------ four reference businesses, one architecture
@needs_db
@pytest.mark.parametrize(("business_type", "kind", "label", "bookings_term"), [
    ("restaurant", "menu_item", "Menu", "Reservations"),
    ("salon", "service", "Services", "Bookings"),
    ("retail", "product", "Products", "Bookings"),
    ("professional_service", "service", "Services", "Bookings"),
])
def test_reference_businesses_share_one_projection(monkeypatch: Any, business_type: str, kind: str, label: str,
                                                   bookings_term: str) -> None:
    owner = _owner(monkeypatch)
    bid = _business(owner, business_type)
    _enable(owner, bid, "offerings-catalog")
    _offering(owner, bid, f"First {kind}", kind, 100)
    context = _context(owner, bid)
    assert context["terms"]["offerings"] == label
    assert context["terms"]["bookings"] == bookings_term
    [section] = _tool_sections(_preview(owner, bid))
    assert section["content"]["title"] == label
    assert section["module_binding"] == {"module": "offerings-catalog"}


# ------------------------------------------------------------------ pure pieces
def test_catalogue_is_named_by_what_is_really_listed() -> None:
    assert catalogue_label({"menu_item": 5, "product": 1}) == "Menu"
    assert catalogue_label({"service": 3}) == "Services"
    assert catalogue_label({"product": 2, "weighed_product": 1}) == "Products"
    assert catalogue_label({"product": 2, "service": 2}) == "Products & services"
    assert catalogue_label({"class_session": 2}) == "Classes"
    assert catalogue_label({}) == "What we offer"
    assert catalogue_label({"membership_plan": 3}) == "What we offer"  # plans have their own section


def test_the_catalogue_section_is_the_catalogues_and_appears_once() -> None:
    flags = flags_for({"offerings-catalog": True}, {"menu_item": 2}, [])
    first = auto_sections(flags, {"hero"}, hidden=[], published_reviews=0, traits=[])
    assert first == auto_sections(flags, {"hero"}, hidden=[], published_reviews=0, traits=[])
    assert [(s["module"], s["section_type_id"], s["module_binding"]) for s in first] == [
        ("offerings-catalog", "menu_section", {"module": "offerings-catalog"})]
    # The owner's own menu already shows it; hiding it hides it; "orders" was its old key.
    assert auto_sections(flags, {"menu_section"}, hidden=[], published_reviews=0, traits=[]) == []
    assert auto_sections(flags, set(), hidden=["offerings-catalog"], published_reviews=0, traits=[]) == []
    assert auto_sections(flags, set(), hidden=["orders"], published_reviews=0, traits=[]) == []
    # Not ready: nothing.
    assert auto_sections(flags_for({}, {"menu_item": 2}, []), set(), hidden=[], published_reviews=0,
                         traits=[]) == []


def test_category_tiles_do_not_stand_in_for_the_real_priced_list() -> None:
    flags = {"catalogue": True, "catalogue_label": "Services", "_kinds": {"service": 3}}
    beside_tiles = auto_sections(flags, {"hero", "category_showcase"}, hidden=(), published_reviews=0, traits=())
    assert [(s["module"], s["section_type_id"]) for s in beside_tiles] == [("offerings-catalog", "offerings_list")]
    # A product showcase already renders the live records once the catalogue is ready.
    assert auto_sections(flags, {"hero", "product_showcase"}, hidden=(), published_reviews=0, traits=()) == []


def test_a_rooms_list_from_bookings_is_not_repeated_by_the_catalogue() -> None:
    flags = flags_for({"offerings-catalog": True, "bookings": True}, {"accommodation": 3}, [])
    sections = auto_sections(flags, {"hero"}, hidden=[], published_reviews=0, traits=[])
    assert [s["section_type_id"] for s in sections] == ["rooms_section"]


def test_ordering_needs_a_way_to_hand_the_order_over() -> None:
    assert decide({"orders": True}, {}, [])["order"] is False
    assert decide({"orders": True, "fulfilment": True}, {}, [])["order"] is True


def test_navigation_drops_only_what_a_not_ready_section_filled_and_adds_the_catalogue_once() -> None:
    stored = [{"label": "Home", "path": "/"}, {"label": "Menu", "path": "/menu"},
              {"label": "Shop", "path": "/#shop"}, {"label": "Contact", "path": "/#contact"}]
    nav = _navigation(stored, page_shows={"home": True, "menu": False}, lost_anchors={"shop"}, kept_anchors=set(),
                      catalogue=None)
    assert [n["path"] for n in nav] == ["/", "/#contact"]
    added = _navigation([{"label": "Home", "path": "/"}, {"label": "Contact", "path": "/#contact"}],
                        page_shows={"home": True}, lost_anchors=set(), kept_anchors={"shop"},
                        catalogue=("/#shop", "Menu"))
    assert added == [{"label": "Home", "path": "/"}, {"label": "Menu", "path": "/#shop"},
                     {"label": "Contact", "path": "/#contact"}]
    assert _navigation(added, page_shows={"home": True}, lost_anchors=set(), kept_anchors={"shop"},
                       catalogue=("/#shop", "Menu")) == added


def test_navigation_state_reads_each_gate_separately() -> None:
    base = {"built": True, "entitled": True, "enabled": True, "ready": False, "state": "active"}
    assert navigation_state({**base, "ready": True}) == "active"
    assert navigation_state(base) == "setup_required"
    assert navigation_state({**base, "entitled": False}) == "not_entitled"
    assert navigation_state({**base, "enabled": False, "state": "deactivated"}) == "deactivated"
    assert navigation_state({**base, "enabled": False, "state": "not_enabled"}) == "not_enabled"
    assert navigation_state({**base, "built": False}) == "unavailable"


def test_workspace_terms_follow_records_then_the_business_vocabulary() -> None:
    assert workspace_terms({"menu_item": 1}, {})["offerings"] == "Menu"
    assert workspace_terms({}, {"product": "Menu Item", "appointment": "Reservation", "customer": "Guest"}) == {
        "offerings": "Menu", "bookings": "Reservations", "customers": "Guests"}
    assert workspace_terms({}, {"product": "Service", "appointment": "Appointment", "customer": "Patient"}) == {
        "offerings": "Services", "bookings": "Bookings", "customers": "Patients"}
    assert workspace_terms({}, {})["offerings"] == "Products & services"
