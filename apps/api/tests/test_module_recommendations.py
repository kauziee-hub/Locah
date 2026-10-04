"""Recommended for your Business: evidence-ranked, explained, never switched on.

Six reference businesses, each with the records a real one would have after
setup. The same ranking serves all of them — there is no per-industry branch —
and what it says differs because what each business said, lists and does
differs. Plus the rules that make it trustworthy: it never enables anything,
"Not now" sticks until a new reason appears, and the owner's own words rank
first.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.catalog.recommendation_evidence import Evidence, Signals, rank, record_evidence
from platform_testing.phase_b import create_business, new_identity, primary_location, sql

needs_db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)


def _offering(owner: dict[str, str], bid: str, title: str, kind: str, **extra: Any) -> str:
    body = {"title": title, "offering_type": kind, "status": "active", "visibility": "public",
            "price_amount": 200, "price_type": "fixed", **extra}
    r = client.post(f"/v1/platform/businesses/{bid}/products", json=body, headers=owner)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["id"])


def _for_you(owner: dict[str, str], bid: str) -> dict[str, Any]:
    r = client.get(f"/v1/platform/businesses/{bid}/module-recommendations/for-you", headers=owner)
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json()["data"])


def _modules(data: dict[str, Any]) -> list[str]:
    return [c["module"] for c in data["recommended"]]


def _card(data: dict[str, Any], module: str) -> dict[str, Any]:
    return next(c for c in data["recommended"] if c["module"] == module)


def _business(monkeypatch: Any, category: str, subcategory: str, *modules: str) -> tuple[dict[str, str], str]:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, category_key=category, subcategory_key=subcategory, modules=modules)
    return owner, bid


# ------------------------------------------------------------------ six reference businesses
@needs_db
def test_restaurant_with_a_menu_is_told_to_take_orders_because_of_its_menu(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "food_service", "restaurant", "offerings-catalog")
    for dish in ("Idli", "Dosa", "Filter coffee"):
        _offering(owner, bid, dish, "menu_item")
    data = _for_you(owner, bid)
    order = _card(data, "orders")
    assert order["reason"].startswith("You list 3 menu items")  # their records, not their category
    assert order["evidence"][0]["kind"] == "records"
    assert "a cart on your website" in order["unlocks"]
    assert order["state"] == "not_enabled" and order["included"] is True
    assert "bookings" in _modules(data)  # a restaurant with tables
    assert "offerings-catalog" not in _modules(data)  # already on


@needs_db
def test_salon_with_services_is_told_to_take_bookings_and_plan_its_people(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "beauty", "salon", "offerings-catalog")
    for service in ("Haircut", "Facial", "Bridal makeup"):
        _offering(owner, bid, service, "service")
    data = _for_you(owner, bid)
    assert _modules(data)[0] == "bookings"
    assert _card(data, "bookings")["reason"].startswith("You list 3 services")
    assert "online booking" in _card(data, "bookings")["unlocks"]
    assert "workforce" in _modules(data)  # served by a named person
    assert "orders" not in _modules(data)  # nothing to put in a cart


@needs_db
def test_home_service_is_told_to_book_visits_and_run_field_jobs(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "home_services", "ac_service", "offerings-catalog")
    for service in ("AC gas refill", "AC deep cleaning", "AC installation"):
        _offering(owner, bid, service, "service", attributes={"duration_minutes": 60})
    data = _for_you(owner, bid)
    names = _modules(data)
    assert names[0] == "bookings" and _card(data, "bookings")["reason"].startswith("You list 3 services")
    assert {"jobs", "dispatch", "workforce"} <= set(names)  # work happens at the customer's place
    assert "the customer's place" in _card(data, "jobs")["reason"]
    assert not {"orders", "kitchen", "pos"} & set(names)  # no cart, no kitchen, no counter


@needs_db
def test_clothing_shop_with_sizes_is_told_to_track_stock(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "retail", "clothing", "offerings-catalog")
    _offering(owner, bid, "Cotton kurta", "product", track_inventory=True)
    _offering(owner, bid, "Silk saree", "product", track_inventory=True)
    data = _for_you(owner, bid)
    stock = _card(data, "inventory")
    assert stock["evidence"][0]["kind"] == "records"
    assert "stock to watch" in stock["reason"]
    assert {"orders", "inventory"} <= set(_modules(data))
    assert "bookings" not in _modules(data)


@needs_db
def test_accountant_is_told_to_capture_enquiries_not_to_open_a_shop(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "professional", "accountant", "offerings-catalog")
    _offering(owner, bid, "GST filing", "service")
    data = _for_you(owner, bid)
    assert "leads" in _modules(data)
    assert "orders" not in _modules(data) and "inventory" not in _modules(data)


@needs_db
def test_yoga_studio_with_classes_is_told_to_book_classes_sell_plans_and_mark_attendance(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "fitness", "yoga", "offerings-catalog")
    _offering(owner, bid, "Morning Hatha", "class_session")
    _offering(owner, bid, "Evening Vinyasa", "class_session")
    data = _for_you(owner, bid)
    assert {"bookings", "memberships"} <= set(_modules(data))
    assert _card(data, "bookings")["reason"].startswith("You list 2 classes")
    assert "attendance" in _modules(data)
    assert "orders" not in _modules(data)


@needs_db
def test_interior_designer_is_told_to_quote_and_run_projects(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "design_build", "interior_designer", "leads")
    for n in range(3):
        r = client.post(f"/v1/platform/businesses/{bid}/leads", headers=owner,
                        json={"display_name": f"Client {n}", "phone": f"+9198765432{n:02d}",
                              "message": "Need a 2BHK interior done"})
        assert r.status_code in (200, 201), r.text
    data = _for_you(owner, bid)
    assert {"quotes", "projects"} <= set(_modules(data))
    assert "orders" not in _modules(data) and "inventory" not in _modules(data)
    assert _card(data, "quotes")["reason"].startswith("3 enquiries came in")


# ------------------------------------------------------------------ the rules
@needs_db
def test_recommendations_never_switch_anything_on(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "beauty", "salon", "offerings-catalog")
    _offering(owner, bid, "Haircut", "service")
    before = sql("select module_id, activation_state from business_module_states "
                 "where business_id = cast(:b as uuid) order by 1", b=bid)
    _for_you(owner, bid)
    after = sql("select module_id, activation_state from business_module_states "
                "where business_id = cast(:b as uuid) order by 1", b=bid)
    assert before == after


@needs_db
def test_not_now_sticks_until_a_new_reason_appears(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "retail", "clothing", "offerings-catalog")
    _offering(owner, bid, "Kurta", "product")
    assert "orders" in _modules(_for_you(owner, bid))
    r = client.post(f"/v1/platform/businesses/{bid}/module-recommendations/orders/not-now", headers=owner)
    assert r.status_code == 200, r.text
    data = _for_you(owner, bid)
    assert "orders" not in _modules(data)
    assert {"module": "orders", "label": "Orders"} in data["put_off"]
    # Another item of the same kind is not a new reason.
    _offering(owner, bid, "Dupatta", "product")
    assert "orders" not in _modules(_for_you(owner, bid))
    # A first order is a reason that did not exist when it was put off… but Orders
    # is not on, so it cannot have orders: what brings it back is a new kind of
    # evidence — here the owner switching on delivery themselves.
    traits = client.patch(f"/v1/platform/businesses/{bid}/traits", headers=owner,
                          json={"traits": {"order_led": True}})
    assert traits.status_code == 200, traits.text
    # order_led is already a clothing default, so it is not new either.
    assert "orders" not in _modules(_for_you(owner, bid))
    # The owner can bring it back themselves.
    back = client.delete(f"/v1/platform/businesses/{bid}/module-recommendations/orders/not-now", headers=owner)
    assert back.status_code == 200
    assert "orders" in _modules(_for_you(owner, bid))
    [(audits,)] = sql("select count(*) from platform_audit_events where business_id = cast(:b as uuid) "
                      "and event_type like 'module.recommendation.%'", b=bid)
    assert audits == 2


@needs_db
def test_putting_off_needs_the_permission_to_enable(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "beauty", "salon")
    person, member = new_identity(monkeypatch)
    inv = client.post(f"/v1/b/{bid}/team/invitations", json={"identity_id": str(person), "role": "member"},
                      headers=owner).json()["data"]["id"]
    client.post(f"/v1/b/{bid}/team/members/{inv}/activate", headers=owner)
    client.post(f"/v1/b/{bid}/team/members/{inv}/permissions", json={"permissions": ["modules.read"]},
                headers=owner)
    headers = {**member, "X-Operating-Context": "business", "X-Business-Id": bid}
    assert client.get(f"/v1/platform/businesses/{bid}/module-recommendations/for-you",
                      headers=headers).status_code == 200
    assert client.post(f"/v1/platform/businesses/{bid}/module-recommendations/bookings/not-now",
                       headers=headers).status_code == 403


# ------------------------------------------------------------------ pure ranking
def _rank(**kw: Any) -> list[str]:
    base: dict[str, Any] = {"picks": [], "said": [], "records": {}, "traits": {}, "enabled": [],
                            "built": ["orders", "bookings", "leads", "inventory"], "dismissed": {}}
    suggestions, _, _ = rank(**{**base, **kw})
    return [s.module for s in suggestions]


def test_what_the_owner_said_outranks_businesses_like_theirs() -> None:
    said = [{"module_id": "leads", "choice": "pending", "strength": "strong",
             "evidence": [{"kind": "owner_said", "text": "people message us for custom cakes first"}],
             "reason": ""}]
    picks = [{"module": "bookings", "tier": "core", "reason": "Most cafés rely on this"}]
    assert _rank(said=said, picks=picks) == ["leads", "bookings"]


def test_declining_in_the_conversation_counts_as_not_now() -> None:
    said = [{"module_id": "leads", "choice": "declined", "strength": "strong",
             "evidence": [{"kind": "owner_said", "text": "no enquiries, people just walk in"}], "reason": ""}]
    assert _rank(said=said) == []
    records = {"leads": [Evidence("records:leads", "records", "4 enquiries came in")]}
    assert _rank(said=said, records=records) == ["leads"]  # a new kind of reason brings it back


def test_record_evidence_reads_like_the_business() -> None:
    ev = record_evidence(Signals(kinds={"menu_item": 12}, variants=2, tracked=3))
    assert ev["orders"][0].text.startswith("You list 12 menu items")
    assert "2 items come in sizes or options; 3 have stock to watch" in ev["inventory"][0].text
    assert "bookings" not in ev


# ------------------------------------------------------------------ one tool's setup, in words
def _setup(owner: dict[str, str], bid: str, module: str) -> dict[str, Any]:
    r = client.get(f"/v1/b/{bid}/modules/{module}/setup", headers=owner)
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json()["data"])


@needs_db
def test_setup_says_why_a_tool_is_not_working_yet(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "food_service", "restaurant")
    s = _setup(owner, bid, "orders")
    assert (s["status"], s["status_label"], s["enabled"]) == ("not_enabled", "Not switched on", False)
    assert "a cart on your website" in s["website"]

    client.post(f"/v1/b/{bid}/modules/offerings-catalog/enable", headers=owner)
    client.post(f"/v1/b/{bid}/modules/orders/enable", headers=owner)
    s = _setup(owner, bid, "orders")
    # Paying at the counter is always possible; a priced item is not there yet.
    assert s["status"] == "partial"
    step = next(x for x in s["steps"] if x["key"] == "priced_product")
    assert step["done"] is False and step["action"] == {"label": "Price an item", "href": "/offerings"}
    assert s["remaining"] == 2  # the priced item, and the catalogue it is waiting on
    assert any(d["module"] == "offerings-catalog" and d["holding_back"] for d in s["dependencies"])

    _offering(owner, bid, "Masala dosa", "menu_item")
    s = _setup(owner, bid, "orders")
    assert (s["status"], s["remaining"], s["home"]) == ("ready", 0, "/orders")

    client.post(f"/v1/b/{bid}/modules/orders/deactivate", headers=owner)
    assert _setup(owner, bid, "orders")["status"] == "deactivated"


@needs_db
def test_setup_names_a_plan_restriction_and_a_waiting_dependency(monkeypatch: Any) -> None:
    owner, bid = _business(monkeypatch, "beauty", "salon", "leads")
    assert _setup(owner, bid, "leads")["status"] == "ready"  # nothing to set up
    client.patch(f"/v1/platform/businesses/{bid}/entitlements/overrides", headers=owner,
                 json={"modules": {"leads": {"entitled": False}}})
    s = _setup(owner, bid, "leads")
    assert (s["status"], s["included"]) == ("restricted", False)
    assert client.get(f"/v1/b/{bid}/modules/not-a-tool/setup", headers=owner).status_code == 404


@needs_db
def test_bookings_working_without_hours_says_customers_cannot_pick_a_time(monkeypatch: Any) -> None:
    """Hours are advice, not a setup step: classes and staff schedules carry their
    own times. Without them an appointment has no times, and the page says so."""
    owner, bid = _business(monkeypatch, "beauty", "salon", "offerings-catalog", "bookings")
    _offering(owner, bid, "Haircut", "service", attributes={"duration_minutes": 30})
    s = _setup(owner, bid, "bookings")
    assert s["status"] == "ready"
    assert s["tips"] and s["tips"][0]["href"] == "/locations" and "opening hours" in s["tips"][0]["text"]
    loc = primary_location(client, owner, bid)
    client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}", headers=owner,
                 json={"hours": {"mon": [["10:00", "19:00"]]}})
    assert _setup(owner, bid, "bookings")["tips"] == []
