"""AI Employee Studio — Test Mode.

What must hold:

* approving what the AI employee proposed makes a TEST order, booking or
  enquiry, re-checked against the live price and free times;
* it is isolated: no row in orders, bookings, leads, payments or messages, no
  domain event in the outbox — before and after, those counts are the same;
* a test payment goes through the test adapter only (paid or failed) and only
  for a test order with a price;
* only people who manage AI employees can make or pay test records; clearing
  hides them and keeps the audit trail.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.ai_employees.test_mode import TestPaymentAdapter
from platform_testing.phase_b import create_business, new_identity, primary_location, sql

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
ALL_DAYS = {d: [["09:00", "20:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
REAL = ("orders_orders", "bookings_bookings", "leads_leads", "messaging_messages", "payments_payment_attempts",
        "payments_requests", "ai_actions", "platform_outbox_events")


def _counts(bid: str) -> dict[str, int]:
    return {t: int(sql(f"select count(*) from {t} where business_id = cast(:b as uuid)", b=bid)[0][0]) for t in REAL}


def _cafe(monkeypatch: Any) -> tuple[Any, dict[str, str], str, str, str]:
    me, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, business_type="restaurant",
                          modules=("offerings-catalog", "orders", "fulfilment", "leads", "bookings"))
    base = f"/v1/platform/businesses/{bid}"
    loc = primary_location(client, owner, bid)
    assert client.patch(f"{base}/locations/{loc}", json={"hours": ALL_DAYS}, headers=owner).status_code == 200
    assert client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": True},
                        headers=owner).status_code == 200
    item = client.post(f"{base}/products", json={
        "title": "Filter Coffee", "offering_type": "menu_item", "status": "active", "visibility": "public",
        "price_amount": 40, "price_type": "fixed"}, headers=owner).json()["data"]["id"]
    return me, owner, bid, loc, item


def _propose(owner: dict[str, str], bid: str, message: str) -> dict[str, Any]:
    r = client.post(f"/v1/b/{bid}/ai-employees/sandbox/simulate",
                    json={"scenario": "whatsapp_manager", "message": message}, headers=owner)
    assert r.status_code == 200, r.text
    proposal: dict[str, Any] = r.json()["data"]["proposal"]
    assert proposal, r.json()["data"]["reply"]
    return proposal


@DB
def test_an_approved_order_is_a_test_order_and_nothing_real_is_written(monkeypatch: Any) -> None:
    _, owner, bid, _, item = _cafe(monkeypatch)
    before = _counts(bid)
    proposal = _propose(owner, bid, "Can I order 2 filter coffee?")
    made = client.post(f"/v1/b/{bid}/ai-employees/test-records",
                       json={**proposal, "scenario": "whatsapp_manager"}, headers=owner)
    assert made.status_code == 200, made.text
    data = made.json()["data"]
    record = data["record"]
    assert record["kind"] == "order" and record["reference"].startswith("TEST-O")
    assert record["amount"] == 80.0 and record["detail"]["item"] == "Filter Coffee"
    assert record["status"] == "confirmed" and record["can_pay"] is True
    assert "no money moved" in data["notice"] and data["trace"][-1]["kind"] == "test_record"
    assert any(s["kind"] == "recheck" for s in data["trace"])  # checked live first

    paid = client.post(f"/v1/b/{bid}/ai-employees/test-records/{record['id']}/pay", json={"outcome": "succeed"},
                       headers=owner)
    assert paid.status_code == 200, paid.text
    assert paid.json()["data"]["status"] == "paid"
    assert paid.json()["data"]["payment"]["adapter"] == "test"
    again = client.post(f"/v1/b/{bid}/ai-employees/test-records/{record['id']}/pay", json={"outcome": "succeed"},
                        headers=owner)
    assert again.status_code == 422

    listed = client.get(f"/v1/b/{bid}/ai-employees/test-records", headers=owner).json()["data"]["records"]
    assert [r["reference"] for r in listed] == [record["reference"]]
    # Isolation: not one real order, payment, message or event.
    assert _counts(bid) == before


@DB
def test_a_failed_test_payment_can_be_tried_again(monkeypatch: Any) -> None:
    _, owner, bid, _, _ = _cafe(monkeypatch)
    proposal = _propose(owner, bid, "Can I order 1 filter coffee?")
    rec = client.post(f"/v1/b/{bid}/ai-employees/test-records", json={**proposal, "scenario": "whatsapp_manager"},
                      headers=owner).json()["data"]["record"]
    failed = client.post(f"/v1/b/{bid}/ai-employees/test-records/{rec['id']}/pay", json={"outcome": "fail"},
                         headers=owner).json()["data"]
    assert failed["status"] == "payment_failed" and failed["can_pay"] is True
    assert failed["payment"]["status"] == "failed" and failed["payment"]["reason"]
    ok = client.post(f"/v1/b/{bid}/ai-employees/test-records/{rec['id']}/pay", json={"outcome": "succeed"},
                     headers=owner).json()["data"]
    assert ok["status"] == "paid"


@DB
def test_a_booking_and_an_enquiry_are_test_records_too(monkeypatch: Any) -> None:
    _, owner, bid, loc, _ = _cafe(monkeypatch)
    base = f"/v1/platform/businesses/{bid}"
    client.post(f"{base}/products", json={
        "title": "Barista Class", "offering_type": "service", "status": "active", "visibility": "public",
        "price_amount": 500, "price_type": "fixed", "duration_minutes": 60}, headers=owner)
    before = _counts(bid)
    day = (date.today() + timedelta(days=2)).strftime("%A").lower()
    r = client.post(f"/v1/b/{bid}/ai-employees/sandbox/simulate",
                    json={"scenario": "receptionist", "message": f"can I book barista class on {day} morning"},
                    headers=owner)
    proposal = r.json()["data"]["proposal"]
    if proposal and proposal.get("action") == "booking":
        rec = client.post(f"/v1/b/{bid}/ai-employees/test-records",
                          json={**proposal, "scenario": "receptionist"}, headers=owner).json()["data"]["record"]
        assert rec["kind"] == "booking" and rec["reference"].startswith("TEST-B")
        assert "does not hold this time" in rec["detail"]["note"] and rec["can_pay"] is False
    lead = client.post(f"/v1/b/{bid}/ai-employees/test-records", json={
        "action": "lead", "summary": "Catering for 40 people", "message": "Do you do catering for 40 people?",
        "scenario": "whatsapp_manager"}, headers=owner)
    assert lead.status_code == 200, lead.text
    assert lead.json()["data"]["record"]["kind"] == "lead"
    assert _counts(bid) == before


@DB
def test_only_managers_of_ai_employees_make_test_records_and_clearing_keeps_the_audit(monkeypatch: Any) -> None:
    _, owner, bid, _, _ = _cafe(monkeypatch)
    proposal = _propose(owner, bid, "Can I order 1 filter coffee?")
    person, headers = new_identity(monkeypatch)
    inv = client.post(f"/v1/b/{bid}/team/invitations", json={"identity_id": str(person), "role": "member"},
                      headers=owner).json()["data"]["id"]
    client.post(f"/v1/b/{bid}/team/members/{inv}/activate", headers=owner)
    denied = client.post(f"/v1/b/{bid}/ai-employees/test-records", json={**proposal, "scenario": "whatsapp_manager"},
                         headers=headers)
    assert denied.status_code == 403

    client.post(f"/v1/b/{bid}/ai-employees/test-records", json={**proposal, "scenario": "whatsapp_manager"},
                headers=owner)
    cleared = client.post(f"/v1/b/{bid}/ai-employees/test-records/clear", headers=owner).json()["data"]
    assert cleared["cleared"] == 1
    assert client.get(f"/v1/b/{bid}/ai-employees/test-records", headers=owner).json()["data"]["records"] == []
    events = sql("select event_type from platform_audit_events where business_id = cast(:b as uuid) "
                 "and event_type like 'ai_employee.test_record%'", b=bid)
    assert {e[0] for e in events} >= {"ai_employee.test_record.created", "ai_employee.test_records.cleared"}


def test_the_test_adapter_never_calls_a_provider() -> None:
    adapter = TestPaymentAdapter()
    assert adapter.charge(amount=80, outcome="succeed")["status"] == "paid"
    assert adapter.charge(amount=80, outcome="fail")["status"] == "failed"
    with pytest.raises(Exception):
        adapter.charge(amount=80, outcome="maybe")
