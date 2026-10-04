"""Refunds say what really happened to the money.

* An online payment a provider collected is refunded THROUGH the provider: the
  refund is "processing" once the provider accepts it (its amount reserved),
  and only the provider's outcome (a refund webhook) makes it "succeeded" or
  "failed". A failure releases the amount and flags the payment for the owner.
* A provider that refuses is recorded as a failed refund; nothing is reserved.
* The owner can record an online payment they gave back themselves ("manual"),
  and anything paid offline is a recorded refund — LOCAH moved no money.
* Razorpay's refund call is made with the platform credentials, refusing a
  payment that has no Razorpay payment id and reporting Razorpay's own words.

No real provider is called: the stub provider, and Razorpay behind a mocked
HTTP transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.payments import razorpay
from platform_testing.phase_b import billing_shop, new_identity, sql

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
WEBHOOK_SECRET = "test-payment-webhook-secret"


def _signed(body: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "x-payment-signature": sig}


def _online_paid(monkeypatch: Any, amount: float = 1000) -> tuple[dict[str, str], str, str]:
    """A shop with an online payment the (stub) provider has captured."""
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", WEBHOOK_SECRET)
    _, owner = new_identity(monkeypatch)
    shop = billing_shop(client, owner, modules=("customer-relationships",))
    base = shop["base"]
    cake = client.post(f"{base}/products", json={
        "status": "active", "offering_type": "product", "title": "Cake", "price_amount": amount,
        "hsn_sac": "1905", "tax_rate": 0}, headers=owner).json()["data"]
    order = client.post(f"{base}/orders", json={
        "location_id": shop["loc"], "payment_method": "pay_at_business",
        "items": [{"offering_id": cake["id"], "quantity": 1}]}, headers=owner).json()["data"]
    pid = str(uuid.uuid4())
    sql("INSERT INTO payments_payment_attempts (id, business_id, source_type, source_id, amount, payment_method, "
        "status, provider, purpose) VALUES (CAST(:id AS uuid), CAST(:b AS uuid), 'order', CAST(:o AS uuid), :a, "
        "'online', 'processing', 'stub', 'full')", id=pid, b=shop["bid"], o=order["id"], a=amount)
    raw, headers = _signed({"event_id": str(uuid.uuid4()), "payment_id": pid, "status": "succeeded",
                            "provider_reference": "stub_pay_1"})
    assert client.post("/v1/webhooks/payments/stub", content=raw, headers=headers).status_code == 200
    return owner, base, pid


def _refund(owner: dict[str, str], base: str, pid: str, amount: float, **extra: Any) -> dict[str, Any]:
    r = client.post(f"{base}/payments/{pid}/refunds", headers=owner,
                    json={"amount": amount, "reason": "Customer returned it", **extra})
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _payment(pid: str) -> tuple[str, float, str | None]:
    status, refunded, attention = sql("select status, refunded_amount, attention from payments_payment_attempts "
                                      "where id = cast(:p as uuid)", p=pid)[0]
    return status, float(refunded), attention


@DB
def test_an_online_refund_is_processing_until_the_provider_says_it_is_done(monkeypatch: Any) -> None:
    owner, base, pid = _online_paid(monkeypatch)
    data = _refund(owner, base, pid, 400)
    refund = data["refund"]
    assert (refund["kind"], refund["status"]) == ("provider", "processing")
    assert refund["provider_reference"].startswith("stub_rfnd_") and refund["completed_at"] is None
    assert _payment(pid)[:2] == ("partially_refunded", 400.0)  # reserved: never refund more than was paid
    shown = client.get(f"{base}/payments/{pid}", headers=owner).json()["data"]
    assert shown["status_label"] == "Refund in progress"  # not "refunded" until the provider says so
    over = client.post(f"{base}/payments/{pid}/refunds", headers=owner, json={"amount": 700, "reason": "x"})
    assert over.status_code == 422

    raw, headers = _signed({"event_id": str(uuid.uuid4()), "refund_reference": refund["provider_reference"],
                            "refund_status": "succeeded"})
    done = client.post("/v1/webhooks/payments/stub", content=raw, headers=headers)
    assert done.status_code == 200 and done.json()["data"]["status"] == "processed", done.text
    row = sql("select status, completed_at is not null from payments_refunds where id = cast(:r as uuid)",
              r=refund["id"])[0]
    assert row == ("succeeded", True)
    # The same outcome again changes nothing.
    raw, headers = _signed({"event_id": str(uuid.uuid4()), "refund_reference": refund["provider_reference"],
                            "refund_status": "failed"})
    client.post("/v1/webhooks/payments/stub", content=raw, headers=headers)
    assert sql("select status from payments_refunds where id = cast(:r as uuid)", r=refund["id"]) == [("succeeded",)]


@DB
def test_a_failed_provider_refund_gives_the_amount_back_and_tells_the_owner(monkeypatch: Any) -> None:
    owner, base, pid = _online_paid(monkeypatch)
    refund = _refund(owner, base, pid, 1000)["refund"]
    assert _payment(pid)[0] == "refunded"
    raw, headers = _signed({"event_id": str(uuid.uuid4()), "refund_reference": refund["provider_reference"],
                            "refund_status": "failed", "failure_reason": "Bank account closed"})
    assert client.post("/v1/webhooks/payments/stub", content=raw, headers=headers).status_code == 200
    assert sql("select status, failure_reason from payments_refunds where id = cast(:r as uuid)",
               r=refund["id"]) == [("failed", "Bank account closed")]
    assert _payment(pid) == ("succeeded", 0.0, "refund_failed")
    # The amount is free again: the owner can refund another way.
    again = _refund(owner, base, pid, 1000, manual=True, idempotency_key=str(uuid.uuid4()))["refund"]
    assert (again["kind"], again["status"]) == ("recorded", "succeeded")


@DB
def test_a_provider_that_refuses_moves_nothing(monkeypatch: Any) -> None:
    from platform_core.payments import refunds
    from platform_core.payments.refunds import ProviderRefund

    owner, base, pid = _online_paid(monkeypatch)

    async def refuse(*args: Any, **kwargs: Any) -> ProviderRefund:
        return ProviderRefund(False, "failed", None, "Razorpay refused the refund (400): Insufficient balance")

    monkeypatch.setattr(refunds, "request_refund", refuse)
    import platform_core.services.refund as refund_service

    monkeypatch.setattr(refund_service, "request_refund", refuse)
    refund = _refund(owner, base, pid, 300)["refund"]
    assert (refund["status"], refund["failure_reason"]) == ("failed", "Razorpay refused the refund (400): "
                                                                      "Insufficient balance")
    assert _payment(pid) == ("succeeded", 0.0, None)


@DB
def test_offline_money_given_back_is_a_recorded_refund(monkeypatch: Any) -> None:
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", WEBHOOK_SECRET)
    owner, base, pid = _online_paid(monkeypatch)
    manual = _refund(owner, base, pid, 200, manual=True)["refund"]
    assert (manual["kind"], manual["status"], manual["provider_reference"]) == ("recorded", "succeeded", None)
    assert manual["completed_at"] is not None


# ---------------------------------------------------------------- Razorpay's refund call
def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_razorpay_refund_uses_the_platform_account_and_reports_its_words(monkeypatch: Any) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "not-a-real-secret")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert body["amount"] == 40050 and body["reverse_all"] == 1 and body["speed"] == "normal"
        return httpx.Response(200, json={"id": "rfnd_123", "status": "pending"})

    ok = _run(razorpay.create_refund(payment_reference="pay_abc", amount=Decimal("400.50"), receipt="r1",
                                     transport=httpx.MockTransport(handler)))
    assert (ok.ok, ok.refund_id, ok.status) == (True, "rfnd_123", "pending")
    assert str(seen[0].url) == "https://api.razorpay.com/v1/payments/pay_abc/refund"
    assert seen[0].headers["authorization"].startswith("Basic ")

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "The refund amount is greater than the captured amount"}})

    no = _run(razorpay.create_refund(payment_reference="pay_abc", amount=Decimal("10"), receipt="r2",
                                     transport=httpx.MockTransport(refused)))
    assert not no.ok and "greater than the captured amount" in no.detail

    never = _run(razorpay.create_refund(payment_reference="order_xyz", amount=Decimal("10"), receipt="r3",
                                        transport=httpx.MockTransport(handler)))
    assert not never.ok and "no Razorpay payment id" in never.detail and len(seen) == 1


def test_razorpay_refund_without_platform_credentials_is_refused(monkeypatch: Any) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    result = _run(razorpay.create_refund(payment_reference="pay_abc", amount=Decimal("10"), receipt="r"))
    assert not result.ok and "not configured" in result.detail


def test_razorpay_refund_events_normalise_to_refund_outcomes() -> None:
    from platform_core.payments.provider_adapter import normalize_payment_event

    processed = normalize_payment_event("razorpay", {
        "event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_1", "payment_id": "pay_1"}}}})
    failed = normalize_payment_event("razorpay", {
        "event": "refund.failed",
        "payload": {"refund": {"entity": {"id": "rfnd_2", "error_description": "Account closed"}}}})
    assert (processed["refund_reference"], processed["refund_status"]) == ("rfnd_1", "succeeded")
    assert (failed["refund_reference"], failed["refund_status"], failed["failure_reason"]) == (
        "rfnd_2", "failed", "Account closed")
