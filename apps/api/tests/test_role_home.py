"""Home answers the role's question, from real data within the viewer's scope
(Business OS Guide §3; Capability Universe §7.2; Build Spec §8)."""

from __future__ import annotations

import os
import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_testing.phase_b import create_business, new_identity, primary_location, sql

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)


def _member(owner: dict[str, str], bid: str, monkeypatch: Any, role: str, locations: list[str]) -> dict[str, str]:
    person_id, headers = new_identity(monkeypatch)
    inv = client.post(f"/v1/b/{bid}/team/invitations", json={"identity_id": str(person_id), "role": "member"},
                      headers=owner).json()["data"]["id"]
    client.post(f"/v1/b/{bid}/team/members/{inv}/activate", headers=owner)
    r = client.put(f"/v1/platform/businesses/{bid}/members/{inv}/role",
                   json={"role": role, "location_ids": locations}, headers=owner)
    assert r.status_code == 200, r.text
    return cast(dict[str, str], headers)


def _home(bid: str, headers: dict[str, str]) -> dict[str, Any]:
    r = client.get(f"/v1/platform/businesses/{bid}/home", headers=headers)
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json()["data"])


def _band(home: dict[str, Any], key: str) -> dict[str, Any]:
    return next(b for b in home["bands"] if b["key"] == key)


def _shop(owner: dict[str, str]) -> tuple[str, str, str, str]:
    bid = create_business(client, owner, modules=("offerings-catalog", "inventory", "orders", "payments", "leads"))
    a = primary_location(client, owner, bid)
    b = client.post(f"/v1/platform/businesses/{bid}/locations", json={"name": "Branch"}, headers=owner).json()["data"]["id"]
    product = client.post(f"/v1/platform/businesses/{bid}/products", json={
        "title": "Sugar 1 kg", "sku": f"S-{uuid.uuid4().hex[:6]}", "track_inventory": True, "low_stock_threshold": 5,
        "status": "active", "price_amount": 50}, headers=owner).json()["data"]["id"]
    for loc, qty in ((a, 3), (b, 40)):  # low at A, fine at B
        client.post(f"/v1/platform/businesses/{bid}/inventory/opening-stock",
                    json={"offering_id": product, "location_id": loc, "quantity": qty}, headers=owner)
    return bid, a, b, product


def _order(owner: dict[str, str], bid: str, loc: str, product: str) -> str:
    r = client.post(f"/v1/platform/businesses/{bid}/orders", json={
        "location_id": loc, "payment_method": "cod", "items": [{"offering_id": product, "quantity": 1}]}, headers=owner)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["id"])


def test_a_new_owner_sees_three_bands_with_honest_empty_states(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog", "orders"))
    home = _home(bid, owner)
    assert home["role"] == {"key": "owner", "label": "Owner", "question": "Needs you now · Today · Your business"}
    assert [b["key"] for b in home["bands"]] == ["now", "today", "business"]
    assert _band(home, "now")["items"] == [] and _band(home, "now")["empty"] == "Nothing needs you right now."
    today = {s["label"]: s["value"] for s in _band(home, "today")["stats"]}
    assert today["Order value today"] == "₹0"
    business = {i["label"]: i["detail"] for i in _band(home, "business")["items"]}
    assert business["Website"] == "Not published yet"
    assert "setup left in" in business["Tools"]  # Orders is on but has no priced product yet
    header = home["header"]
    assert header["greeting"] in ("Good morning", "Good afternoon", "Good evening")
    assert header["open"] == {"state": "unknown", "text": "Opening hours not set"} and header["website"] is False
    assert [a["label"] for a in home["quick_actions"]][:2] == ["New order", "Add an item"]


def test_home_header_reads_the_primary_location_hours(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog",))
    loc = primary_location(client, owner, bid)
    every_day = {d: [["00:00", "23:59"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    r = client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}", json={
        "hours": every_day, "timezone": "Asia/Kolkata", "address": {"locality": "Anna Nagar", "city": "Chennai"}},
        headers=owner)
    assert r.status_code == 200, r.text
    header = _home(bid, owner)["header"]
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # 23:59 is the one closed minute.
    assert header["open"]["state"] == "open" or datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M") == "23:59"
    assert header["place"] == "Anna Nagar" and header["name"]


def test_owner_needs_you_now_counts_real_records(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid, a, b, product = _shop(owner)
    _order(owner, bid, a, product)
    _order(owner, bid, b, product)
    client.post(f"/v1/platform/businesses/{bid}/leads", json={"display_name": "Walk-in", "phone": "+919000000123"},
                headers=owner)
    now = {i["label"]: i for i in _band(_home(bid, owner), "now")["items"]}
    assert now["orders waiting to be accepted"]["count"] == 2
    assert now["items low or out of stock"]["count"] == 1 and "Sugar 1 kg" in now["items low or out of stock"]["detail"]
    assert now["new enquiries to answer"]["count"] == 1
    today = {s["label"]: s for s in _band(_home(bid, owner), "today")["stats"]}
    assert today["Order value today"]["note"] == "2 orders"


def test_store_keeper_home_is_what_is_low_and_what_arrived_at_their_location(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid, a, b, _ = _shop(owner)
    keeper_b = _member(owner, bid, monkeypatch, "store_keeper", [b])
    keeper_a = _member(owner, bid, monkeypatch, "store_keeper", [a])
    home_b = _home(bid, keeper_b)
    assert home_b["role"]["question"] == "What is low, what arrived" and home_b["location_scoped"] is True
    assert [x["key"] for x in home_b["bands"]] == ["low", "arrived"]
    assert _band(home_b, "low")["items"] == []  # 40 at the branch
    assert [(i["label"], i["count"]) for i in _band(home_b, "arrived")["items"]] == [("Sugar 1 kg", 40)]
    home_a = _home(bid, keeper_a)
    assert [(i["label"], i["detail"]) for i in _band(home_a, "low")["items"]] == [("Sugar 1 kg", "3 left")]
    assert [(i["label"], i["count"]) for i in _band(home_a, "arrived")["items"]] == [("Sugar 1 kg", 3)]


def test_manager_sees_what_is_late_at_their_location_only(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid, a, b, product = _shop(owner)
    late_a = _order(owner, bid, a, product)
    _order(owner, bid, b, product)  # fresh, not late
    sql("update orders_orders set created_at = now() - interval '45 minutes' where id = :id", id=late_a)
    manager_a = _member(owner, bid, monkeypatch, "manager", [a])
    manager_b = _member(owner, bid, monkeypatch, "manager", [b])
    late = {i["label"]: i["count"] for i in _band(_home(bid, manager_a), "late")["items"]}
    assert late["orders waiting over 30 minutes"] == 1 and late["items low or out of stock"] == 1
    assert _band(_home(bid, manager_b), "late")["items"] == []
    assert _band(_home(bid, manager_b), "late")["empty"] == "Nothing is late or stuck."
    assert "business" not in [x["key"] for x in _home(bid, manager_a)["bands"]]


def test_accountant_sees_unpaid_money(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid, a, _, product = _shop(owner)
    _order(owner, bid, a, product)
    accountant = _member(owner, bid, monkeypatch, "accountant", [])
    home = _home(bid, accountant)
    assert home["role"]["question"] == "Unpaid, unsynced, due"
    unpaid = {i["label"]: i for i in _band(home, "unpaid")["items"]}
    assert unpaid["orders not paid yet"]["count"] == 1 and unpaid["orders not paid yet"]["detail"] == "₹50 outstanding"
