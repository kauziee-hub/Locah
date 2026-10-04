"""P1-10D: collect what is due, simply (Founder refinement — Payments; MD §6.1, §12.4).

Pure tests pin the payment state and the UPI/WhatsApp links. Database tests
take real transactions through the owner and public APIs: an advance and a
balance on one order by payment link (UPI to the business, confirmed by the
business), a failed payment retried on the same order, money recorded at the
counter, a bill and a khata balance paid by link and counted once, a replayed
and a late provider success, cash on delivery capped for a first order, split
tender at the counter, and tenant isolation of payment links.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal as D
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.services.payment_collect import payment_state, upi_link, wa_share
from platform_testing.phase_b import (
    assert_tenant_isolated,
    billing_shop,
    create_business,
    new_identity,
    sql,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
WEBHOOK_SECRET = "test-payment-webhook-secret"


# ---------------------------------------------------------------- pure
def test_payment_state_is_separate_from_the_transaction_and_never_guesses() -> None:
    assert payment_state(D(1000), D(0), D(0), pending=False, last_failed=False) == "unpaid"
    assert payment_state(D(1000), D(300), D(0), pending=False, last_failed=False) == "partially_paid"
    assert payment_state(D(1000), D(1000), D(0), pending=False, last_failed=False) == "paid"
    assert payment_state(D(1000), D(0), D(0), pending=True, last_failed=False) == "pending"
    assert payment_state(D(1000), D(0), D(0), pending=False, last_failed=True) == "failed"
    assert payment_state(D(1000), D(1000), D(400), pending=False, last_failed=False) == "partially_refunded"
    assert payment_state(D(1000), D(1000), D(1000), pending=False, last_failed=False) == "refunded"
    # An advance paid while the balance is being confirmed stays honest: pending.
    assert payment_state(D(1000), D(300), D(0), pending=True, last_failed=False) == "pending"


def test_upi_is_for_the_exact_amount_and_whatsapp_goes_to_the_customer() -> None:
    link = upi_link("sweets@okaxis", "Anand Sweets", D("300"), "Order ORD-1 Advance")
    assert link.startswith("upi://pay?pa=sweets@okaxis&pn=Anand%20Sweets&am=300.00&cu=INR")
    assert wa_share("98400 12345", "Pay here") == "https://wa.me/919840012345?text=Pay%20here"
    assert wa_share(None, "x") is None and wa_share("123", "x") is None


# ---------------------------------------------------------------- helpers
def _shop(monkeypatch: Any, *modules: str) -> tuple[dict[str, str], dict[str, Any]]:
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", WEBHOOK_SECRET)
    _, owner = new_identity(monkeypatch)
    shop: dict[str, Any] = dict(billing_shop(client, owner, modules=("pos", "ledger", "customer-relationships",
                                                                      *modules)))
    base = shop["base"]
    cake = client.post(f"{base}/products", json={
        "status": "active", "offering_type": "product", "title": "Custom cake 2 kg", "price_amount": 1000,
        "hsn_sac": "1905", "tax_rate": 0}, headers=owner)
    assert cake.status_code == 200, cake.text
    shop["cake"] = cake.json()["data"]
    r = client.put(f"{base}/pos/settings", json={"upi_vpa": "anand@okaxis", "upi_payee_name": "Anand Sweets"},
                   headers=owner)
    assert r.status_code == 200, r.text
    customer = client.post(f"{base}/customers", json={"display_name": "Kavya", "phone": "+919840012345"},
                           headers=owner)
    assert customer.status_code == 200, customer.text
    shop["customer"] = customer.json()["data"]["id"]
    shop["slug"] = client.get(f"/v1/b/{shop['bid']}", headers=owner).json()["data"]["slug"]
    return owner, shop


def _order(owner: dict[str, str], shop: dict[str, Any], qty: int = 1) -> dict[str, Any]:
    r = client.post(f"{shop['base']}/orders", json={
        "location_id": shop["loc"], "payment_method": "pay_at_business", "customer_contact_id": shop["customer"],
        "items": [{"offering_id": shop["cake"]["id"], "quantity": qty}]}, headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _ask(owner: dict[str, str], shop: dict[str, Any], source_type: str, source_id: str, amount: float,
         purpose: str) -> dict[str, Any]:
    r = client.post(f"{shop['base']}/collect/requests", json={
        "source_type": source_type, "source_id": source_id, "amount": amount, "purpose": purpose}, headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _page(shop: dict[str, Any], link: dict[str, Any]) -> str:
    return f"/v1/public/websites/{shop['slug']}/pay/{link['path'].rsplit('/', 1)[1]}"


def _due(owner: dict[str, str], shop: dict[str, Any], source_type: str, source_id: str) -> dict[str, Any]:
    r = client.get(f"{shop['base']}/collect/due", params={"source_type": source_type, "source_id": source_id},
                   headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


# ---------------------------------------------------------------- advance, balance, retry
@DB
def test_advance_then_balance_by_link_with_a_failed_try_on_the_same_order(monkeypatch: Any) -> None:
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    assert _due(owner, shop, "order", order["id"])["state"] == "unpaid"

    advance = _ask(owner, shop, "order", order["id"], 300, "advance")
    assert advance["url"].endswith(advance["path"].split("/", 2)[2]) and "₹300" in advance["message"]
    assert advance["whatsapp"].startswith("https://wa.me/919840012345?text=")
    page = client.get(_page(shop, advance)).json()["data"]
    assert (page["state"], page["paying_now"], page["already_paid"], page["balance_after"]) == ("open", 300.0, 0.0,
                                                                                                700.0)
    [upi] = page["methods"]  # online stays hidden until the provider is activated
    assert upi["method"] == "upi_direct" and "am=300.00" in upi["upi_link"]

    # "I have paid" is a claim: the order is not paid until the business confirms.
    claim = client.post(_page(shop, advance) + "/paid", json={"reference": "UTR 4471"}).json()["data"]
    assert claim["state"] == "being_confirmed" and claim["state_words"] == "Payment still being confirmed"
    again = client.post(_page(shop, advance) + "/paid", json={}).json()["data"]
    assert again["state"] == "being_confirmed"
    assert sql("select count(*) from payments_payment_attempts where request_id = :r",
               r=advance["id"]) == [(1,)], "no second attempt while one is being confirmed"
    assert _due(owner, shop, "order", order["id"])["paid"] == 0.0
    overview = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]
    [waiting] = overview["to_confirm"]
    assert waiting["reference"] == "UTR 4471" and waiting["for"].startswith("Order ")

    ok = client.post(f"{shop['base']}/collect/payments/{waiting['id']}/confirm", json={"arrived": True},
                     headers=owner)
    assert ok.status_code == 200, ok.text
    due = ok.json()["data"]["due"]
    assert (due["state"], due["paid"], due["balance"]) == ("partially_paid", 300.0, 700.0)
    assert sql("select payment_status from orders_orders where id = :o", o=order["id"]) == [("partially_paid",)]
    assert client.get(_page(shop, advance)).json()["data"]["state_words"] == "Payment received"
    paid_today = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["paid_today"]
    assert paid_today["links_and_recorded"] == 300.0
    too_much = client.post(f"{shop['base']}/collect/requests", json={
        "source_type": "order", "source_id": order["id"], "amount": 800, "purpose": "balance"}, headers=owner)
    assert too_much.status_code == 422 and "700" in too_much.text

    # The balance: the first try did not arrive, the retry did — one order throughout.
    balance = _ask(owner, shop, "order", order["id"], 700, "balance")
    client.post(_page(shop, balance) + "/paid", json={})
    first = sql("select id from payments_payment_attempts where request_id = :r", r=balance["id"])[0][0]
    client.post(f"{shop['base']}/collect/payments/{first}/confirm", json={"arrived": False}, headers=owner)
    failed = client.get(_page(shop, balance)).json()["data"]
    assert failed["state"] == "failed" and failed["state_words"] == "Payment failed — try again"
    assert failed["methods"], "a failed payment can be tried again"
    retry = client.post(_page(shop, balance) + "/paid", json={}).json()["data"]
    assert retry["state"] == "being_confirmed"
    second = sql("select id from payments_payment_attempts where request_id = :r and status = 'pending_offline'",
                 r=balance["id"])[0][0]
    client.post(f"{shop['base']}/collect/payments/{second}/confirm", json={"arrived": True}, headers=owner)
    done = _due(owner, shop, "order", order["id"])
    assert (done["state"], done["paid"], done["balance"]) == ("paid", 1000.0, 0.0)
    assert sql("select count(*) from orders_orders where business_id = :b", b=shop["bid"]) == [(1,)]
    assert sql("select payment_status from orders_orders where id = :o", o=order["id"]) == [("paid",)]
    attention = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["needs_attention"]
    assert not attention, "the failed try was fixed by the retry on the same link"


@DB
def test_the_customer_can_withdraw_a_claim_and_a_cancelled_link_takes_nothing(monkeypatch: Any) -> None:
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    link = _ask(owner, shop, "order", order["id"], 1000, "full")
    client.post(_page(shop, link) + "/paid", json={})
    busy = client.post(f"{shop['base']}/collect/requests/{link['id']}/cancel", headers=owner)
    assert busy.status_code == 409  # confirm or reject what is waiting first
    back = client.post(_page(shop, link) + "/not-paid").json()["data"]
    assert back["state"] == "open" and back["last_attempt"]["status"] == "cancelled"
    assert client.post(f"{shop['base']}/collect/requests/{link['id']}/cancel", headers=owner).status_code == 200
    gone = client.post(_page(shop, link) + "/paid", json={}).json()["data"]
    assert gone["state"] == "cancelled" and gone["methods"] == []
    assert client.get(f"/v1/public/websites/{shop['slug']}/pay/not-a-real-token").status_code == 404


# ---------------------------------------------------------------- money taken by the business
@DB
def test_money_recorded_at_the_counter_against_an_order(monkeypatch: Any) -> None:
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop, qty=2)
    cash = client.post(f"{shop['base']}/collect/record", json={
        "source_type": "order", "source_id": order["id"], "amount": 500, "method": "cash"}, headers=owner)
    assert cash.status_code == 200, cash.text
    assert cash.json()["data"]["due"]["balance"] == 1500.0
    over = client.post(f"{shop['base']}/collect/record", json={
        "source_type": "order", "source_id": order["id"], "amount": 1600, "method": "card"}, headers=owner)
    assert over.status_code == 422
    card = client.post(f"{shop['base']}/collect/record", json={
        "source_type": "order", "source_id": order["id"], "amount": 1500, "method": "card",
        "reference": "Terminal slip 0092"}, headers=owner)
    assert card.status_code == 200, card.text
    due = card.json()["data"]["due"]
    assert due["state"] == "paid" and [a["method_label"] for a in due["attempts"]] == ["Card (own terminal)", "Cash"]
    assert sql("select payment_status from orders_orders where id = :o", o=order["id"]) == [("paid",)]


@DB
def test_one_money_book_per_sale_after_an_advance(monkeypatch: Any) -> None:
    """Found in the P1-10D1 browser run: a failed balance try, the bill issued
    from the order, the pay-at-pickup choice and a refund must all agree with
    what was actually paid on the order."""
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop, qty=2)  # ₹2,000
    base = shop["base"]
    # the customer chose "pay at pickup" at checkout: an intent, not money
    intent = str(uuid.uuid4())
    sql("INSERT INTO payments_payment_attempts (id, business_id, source_type, source_id, amount, payment_method, "
        "status, provider, customer_contact_id) VALUES (CAST(:id AS uuid), CAST(:b AS uuid), 'order', "
        "CAST(:o AS uuid), 2000, 'pay_at_business', 'pending_offline', 'offline', CAST(:c AS uuid))",
        id=intent, b=shop["bid"], o=order["id"], c=shop["customer"])
    advance = _ask(owner, shop, "order", order["id"], 800, "advance")
    client.post(_page(shop, advance) + "/paid", json={"reference": "UTR 1"})
    first = sql("select id from payments_payment_attempts where request_id = :r", r=advance["id"])[0][0]
    client.post(f"{base}/collect/payments/{first}/confirm", json={"arrived": True}, headers=owner)

    # the bill issued from the order knows about the advance, and takes no money of its own
    bill = client.post(f"{base}/invoices/from-order/{order['id']}", json={}, headers=owner)
    assert bill.status_code == 200, bill.text
    doc = client.get(f"{base}/invoices/{bill.json()['data']['id']}", headers=owner).json()["data"]
    assert (doc["payment_status"], doc["paid_on_order"], doc["outstanding"]) == ("part_paid", 800.0, 1200.0)
    direct = client.post(f"{base}/invoices/{doc['id']}/payments", json={"amount": 100, "method": "cash"},
                         headers=owner)
    assert direct.status_code == 409 and "record the money on the order" in direct.text

    # a failed balance try never undoes the advance
    balance = _ask(owner, shop, "order", order["id"], 1200, "balance")
    client.post(_page(shop, balance) + "/paid", json={})
    second = sql("select id from payments_payment_attempts where request_id = :r", r=balance["id"])[0][0]
    client.post(f"{base}/collect/payments/{second}/confirm", json={"arrived": False}, headers=owner)
    assert sql("select payment_status from orders_orders where id = :o", o=order["id"]) == [("partially_paid",)]
    due = _due(owner, shop, "order", order["id"])
    [row] = [a for a in due["attempts"] if a["id"] == intent]
    assert row["amount"] == 1200.0, "the pay-at-pickup choice stands for what is still to collect"

    # collecting cash at pickup takes the balance, not the whole order again
    settled = client.post(f"{base}/payments/{intent}/record-settlement", json={}, headers=owner)
    assert settled.status_code == 200, settled.text
    due = _due(owner, shop, "order", order["id"])
    assert (due["paid"], due["balance"], due["state"]) == (2000.0, 0.0, "paid")
    again = client.post(f"{base}/payments/{intent}/record-settlement", json={}, headers=owner)
    assert again.status_code in (409, 422)
    doc = client.get(f"{base}/invoices/{doc['id']}", headers=owner).json()["data"]
    assert doc["payment_status"] == "paid" and doc["paid_via_order"] is True

    # the customer's page shows each payment in words
    kinds = [r[0] for r in sql("select activity_type from customer_relationships_timeline_entries where business_id = :b "
                               "and contact_id = :c order by occurred_at", b=shop["bid"], c=shop["customer"])]
    assert kinds.count("payment.received") == 2, kinds

    # a refund is given back on purpose: it never reopens a balance to chase
    cash_id = sql("select id from payments_payment_attempts where id = :i", i=intent)[0][0]
    refund = client.post(f"{base}/payments/{cash_id}/refunds", json={"amount": 200, "reason": "Broken"}, headers=owner)
    assert refund.status_code == 200, refund.text
    due = _due(owner, shop, "order", order["id"])
    assert (due["refunded"], due["balance"], due["state"], due["collectable"]) == (200.0, 0.0, "partially_refunded",
                                                                                   True)
    assert sql("select payment_status from orders_orders where id = :o", o=order["id"]) == [("paid",)]


@DB
def test_an_order_paid_by_link_closes_the_pay_on_delivery_choice(monkeypatch: Any) -> None:
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    intent = str(uuid.uuid4())
    sql("INSERT INTO payments_payment_attempts (id, business_id, source_type, source_id, amount, payment_method, "
        "status, provider) VALUES (CAST(:id AS uuid), CAST(:b AS uuid), 'order', CAST(:o AS uuid), 1000, 'cod', "
        "'pending_offline', 'offline')", id=intent, b=shop["bid"], o=order["id"])
    client.post(f"{shop['base']}/collect/record", json={"source_type": "order", "source_id": order["id"],
                                                        "amount": 1000, "method": "upi"}, headers=owner)
    assert sql("select status, failure_reason from payments_payment_attempts where id = :i", i=intent) == [
        ("cancelled", "Paid another way")]
    assert client.post(f"{shop['base']}/payments/{intent}/record-settlement", json={},
                       headers=owner).status_code in (409, 422)


@DB
def test_cash_on_delivery_rules_live_with_pickup_and_delivery(monkeypatch: Any) -> None:
    """A business without WhatsApp sets the rule where it sets pickup and delivery;
    the WhatsApp page edits the same rule."""
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog", "orders", "fulfilment", "payments"))
    r = client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"first_order_cod_cap": 700}, headers=owner)
    assert r.status_code == 200, r.text
    assert (r.json()["data"]["first_order_cod_cap"], r.json()["data"]["pickup_enabled"]) == (700.0, True)
    slug = client.get(f"/v1/b/{bid}", headers=owner).json()["data"]["slug"]
    client.post(f"/v1/b/{bid}/marketplace/visibility", json={"visibility": "unlisted"}, headers=owner)
    assert client.post(f"/v1/b/{bid}/website/publish", headers=owner).status_code == 200
    options = client.get(f"/v1/public/websites/{slug}/checkout/options").json()["data"]
    assert options["cod"] == {"on_delivery": True, "first_order_cap": 700.0}
    off = client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"cod_allowed": False, "first_order_cod_cap": None},
                       headers=owner).json()["data"]
    assert (off["cod_allowed"], off["first_order_cod_cap"], off["pickup_enabled"]) == (False, None, True)
    bad = client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"first_order_cod_cap": 0}, headers=owner)
    assert bad.status_code == 422


@DB
def test_a_link_is_sent_from_the_business_number_only_by_whoever_holds_it(monkeypatch: Any) -> None:
    monkeypatch.setenv("MESSAGING_SANDBOX", "1")
    owner, shop = _shop(monkeypatch, "messaging")
    order = _order(owner, shop)
    no_number = _ask(owner, shop, "order", order["id"], 400, "advance")
    assert no_number["from_number"] is False, "not offered before WhatsApp is connected"
    r = client.post(f"{shop['base']}/messaging/channel/sandbox", json={"display_phone": "+919840000001"},
                    headers=owner)
    assert r.status_code == 200, r.text
    link = _ask(owner, shop, "order", order["id"], 400, "advance")
    assert link["from_number"] is True
    token = link["path"].rsplit("/", 1)[1]
    wrong = client.post(f"{shop['base']}/collect/requests/{link['id']}/whatsapp", json={"token": "x" * 24},
                        headers=owner)
    assert wrong.status_code == 404, "a guessed token sends nothing"
    sent = client.post(f"{shop['base']}/collect/requests/{link['id']}/whatsapp", json={"token": token}, headers=owner)
    assert sent.status_code == 200, sent.text
    body = sent.json()["data"]["body"]
    assert "₹400 (advance for Order" in body and f"/pay/{token}" in body


# ---------------------------------------------------------------- bills and khata, counted once
@DB
def test_a_bill_and_a_khata_balance_paid_by_link_are_counted_once(monkeypatch: Any) -> None:
    owner, shop = _shop(monkeypatch)
    bill = client.post(f"{shop['base']}/invoices", json={
        "lines": [{"offering_id": shop["cake"]["id"], "quantity": 1}], "customer_contact_id": shop["customer"]},
        headers=owner)
    assert bill.status_code == 200, bill.text
    bill_id = bill.json()["data"]["id"]
    due = _due(owner, shop, "invoice", bill_id)
    assert due["collectable"] and due["balance"] == 1000.0
    link = _ask(owner, shop, "invoice", bill_id, 1000, "full")
    client.post(_page(shop, link) + "/paid", json={})
    [waiting] = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["to_confirm"]
    client.post(f"{shop['base']}/collect/payments/{waiting['id']}/confirm", json={"arrived": True}, headers=owner)
    detail = client.get(f"{shop['base']}/invoices/{bill_id}", headers=owner).json()["data"]
    assert detail["payment_status"] == "paid" and detail["payments"][0]["method"] == "upi"

    acct = client.post(f"{shop['base']}/ledger/accounts", json={
        "party_type": "customer", "display_name": "Murugan Traders", "phone": "+919811100001",
        "opening_balance": 400}, headers=owner).json()["data"]
    dues = _ask(owner, shop, "khata", acct["id"], 400, "dues")
    client.post(_page(shop, dues) + "/paid", json={})
    [waiting] = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["to_confirm"]
    client.post(f"{shop['base']}/collect/payments/{waiting['id']}/confirm", json={"arrived": True}, headers=owner)
    after = client.get(f"{shop['base']}/ledger/accounts/{acct['id']}", headers=owner).json()["data"]
    assert after["balance"] == 0.0

    paid = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["paid_today"]
    # 1000 on the bill (its own payment row) + 400 on the khata (its receipt) — each rupee once.
    assert (paid["bills_and_counter"], paid["khata"], paid["links_and_recorded"], paid["total"]) == (
        1000.0, 400.0, 0.0, 1400.0)


# ---------------------------------------------------------------- provider truth
def _webhook(payment_id: str, status: str) -> Any:
    raw = json.dumps({"event_id": str(uuid.uuid4()), "payment_id": payment_id, "status": status,
                      "provider_reference": "stub-ref"}).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/v1/webhooks/payments/stub", content=raw,
                       headers={"Content-Type": "application/json", "x-payment-signature": sig})


def _online_attempt(shop: dict[str, Any], order_id: str, request_id: str, amount: float) -> str:
    """An online attempt on a link, as the provider adapter will create it once
    activated (it is not: there is no online button today)."""
    pid = str(uuid.uuid4())
    sql("INSERT INTO payments_payment_attempts (id, business_id, source_type, source_id, amount, payment_method, "
        "status, provider, request_id, purpose) VALUES (CAST(:id AS uuid), CAST(:b AS uuid), 'order', "
        "CAST(:o AS uuid), :a, 'online', 'processing', 'stub', CAST(:r AS uuid), 'full')",
        id=pid, b=shop["bid"], o=order_id, a=amount, r=request_id)
    return pid


@DB
def test_a_replayed_success_pays_once_and_a_late_success_is_flagged_for_refund(monkeypatch: Any) -> None:
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    link = _ask(owner, shop, "order", order["id"], 1000, "full")
    first = _online_attempt(shop, order["id"], link["id"], 1000)
    older = _online_attempt(shop, order["id"], link["id"], 1000)
    assert _webhook(older, "failed").status_code == 200  # the customer's first try failed…
    assert _webhook(first, "succeeded").status_code == 200  # …the retry succeeded
    assert _webhook(first, "succeeded").status_code == 200  # replayed under a new event id
    due = _due(owner, shop, "order", order["id"])
    assert (due["paid"], due["state"]) == (1000.0, "paid"), "a replay never pays twice"
    assert sql("select count(*) from platform_outbox_events where event_type = 'payment.completed' "
               "and payload->>'payment_id' = :p", p=first) == [(1,)]

    # The provider later settles the try it had failed: the money moved, so it
    # is recorded — and flagged, because the link was already paid.
    assert _webhook(older, "succeeded").status_code == 200
    flagged = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["needs_attention"]
    assert [(a["id"], a["attention"]) for a in flagged] == [(older, "paid_twice")]
    # A written-off UPI payment cannot be revived by a webhook-shaped call.
    upi = _ask(owner, shop, "order", _order(owner, shop)["id"], 1000, "full")
    client.post(_page(shop, upi) + "/paid", json={})
    upi_attempt = sql("select id from payments_payment_attempts where request_id = :r", r=upi["id"])[0][0]
    client.post(f"{shop['base']}/collect/payments/{upi_attempt}/confirm", json={"arrived": False}, headers=owner)
    assert _webhook(str(upi_attempt), "succeeded").status_code >= 400


# ---------------------------------------------------------------- cash on delivery (PY-07)
@DB
def test_website_cash_on_delivery_follows_the_first_order_cap(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog", "orders", "fulfilment", "payments",
                                                  "customer-relationships", "messaging"))
    base = f"/v1/platform/businesses/{bid}"
    slug = client.get(f"/v1/b/{bid}", headers=owner).json()["data"]["slug"]
    item = client.post(f"{base}/products", json={"status": "active", "offering_type": "product",
                                                 "title": "Sweets box", "price_amount": 600,
                                                 "visibility": "public"}, headers=owner).json()["data"]
    client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": True, "delivery_enabled": True},
                 headers=owner)
    client.post(f"/v1/b/{bid}/fulfilment/zones", json={"name": "Adyar", "match_type": "postal_prefix",
                                                       "postal_prefix": "6000", "charge_amount": 0}, headers=owner)
    assert client.post(f"/v1/b/{bid}/website/publish", headers=owner).status_code == 200
    client.post(f"/v1/b/{bid}/marketplace/visibility", json={"visibility": "unlisted"}, headers=owner)
    capped = client.put(f"{base}/messaging/settings", json={"first_order_cod_cap": 1000}, headers=owner)
    assert capped.status_code == 200, capped.text
    options = client.get(f"/v1/public/websites/{slug}/checkout/options").json()["data"]
    assert options["cod"] == {"on_delivery": True, "first_order_cap": 1000.0}

    def checkout(qty: int, mode: str = "delivery") -> Any:
        body: dict[str, Any] = {"items": [{"offering_id": item["id"], "quantity": qty}], "fulfilment_mode": mode,
                                "payment_method": "cod", "guest": {"name": "Ravi", "phone": "+919840099887", "email": "ravi@example.com"}}
        if mode == "delivery":
            body["delivery_address"] = {"line1": "4 Anna St", "city": "Chennai", "postal_code": "600020"}
        return client.post(f"/v1/public/websites/{slug}/checkout", json=body)

    big = checkout(2)
    assert big.status_code == 422 and "cod_first_order_cap" in big.text
    assert sql("select count(*) from orders_orders where business_id = :b", b=bid) == [(0,)]
    assert checkout(2, mode="pickup").status_code == 200  # pay at pickup is not cash on delivery
    assert checkout(2).status_code == 200, "no longer a first order"
    client.put(f"{base}/messaging/settings", json={"cod_allowed": False}, headers=owner)
    off = checkout(1)
    assert off.status_code == 422 and "cod_off" in off.text


# ---------------------------------------------------------------- the counter: split tender (PY-05, PY-06)
@DB
def test_split_tender_settles_one_bill_and_each_method_counts_in_the_shift(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    shop: dict[str, Any] = dict(billing_shop(client, owner, modules=("pos",)))
    item = client.post(f"{shop['base']}/products", json={
        "status": "active", "offering_type": "product", "title": "Pressure cooker", "price_amount": 1000,
        "hsn_sac": "7615", "tax_rate": 0}, headers=owner).json()["data"]
    opened = client.post(f"{shop['base']}/pos/shifts", json={"register_id": shop["register"]["id"],
                                                              "device_id": "tab-1", "opening_cash": 0},
                         headers=owner).json()["data"]
    sale = {"client_mutation_id": str(uuid.uuid4()), "kind": "pos.sale", "payload": {
        "shift_id": opened["shift"]["id"], "client_bill_id": str(uuid.uuid4()),
        "lines": [{"offering_id": item["id"], "quantity": 1, "unit_price": 1000}],
        "tenders": [{"method": "cash", "amount": 400}, {"method": "upi", "amount": 300},
                    {"method": "card", "amount": 300, "reference": "Terminal 7781"}],
        "number": {"block_id": opened["block"]["id"], "value": opened["block"]["next"]},
        "catalogue_version": datetime.now(timezone.utc).isoformat()}}
    r = client.post(f"{shop['base']}/sync", json={"device_id": "tab-1", "mutations": [sale]}, headers=owner)
    assert r.status_code == 200, r.text
    [res] = r.json()["data"]["results"]
    assert res["status"] == "applied", res
    bill = client.get(f"{shop['base']}/invoices/{res['document_id']}", headers=owner).json()["data"]
    assert bill["payment_status"] == "paid"
    assert sorted((p["method"], p["amount"]) for p in bill["payments"]) == [("card", 300.0), ("cash", 400.0),
                                                                             ("upi", 300.0)]
    assert any(p.get("reference") == "Terminal 7781" for p in bill["payments"] if p["method"] == "card")
    summary = client.get(f"{shop['base']}/pos/shifts/{opened['shift']['id']}", headers=owner).json()["data"]["summary"]
    assert (summary["cash_sales"], summary["card"]) == (400.0, 300.0)


# ---------------------------------------------------------------- isolation
@pytest.mark.asyncio
@DB
async def test_payment_links_are_tenant_isolated() -> None:
    async def insert(session: AsyncSession, business_id: uuid.UUID) -> None:
        await session.execute(text(
            "INSERT INTO payments_requests (business_id, source_type, source_id, purpose, amount, token_hash, "
            "expires_at) VALUES (:b, 'order', gen_random_uuid(), 'full', 10, :h, now() + interval '1 day')"),
            {"b": business_id, "h": uuid.uuid4().hex})

    await assert_tenant_isolated("payments_requests", insert)


@DB
def test_the_workspace_reads_each_payment_in_plain_words(monkeypatch: Any) -> None:
    """The payment list and a payment's page say what it was for, how it was paid
    and where it stands — never a source type, method code or status code."""
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    paid = client.post(f"{shop['base']}/collect/record", json={
        "source_type": "order", "source_id": order["id"], "amount": 400, "method": "cash"}, headers=owner)
    assert paid.status_code == 200, paid.text
    rows = client.get(f"{shop['base']}/payments?source_id={order['id']}", headers=owner).json()["data"]
    cash = next(r for r in rows if r["payment_method"] == "cash")
    assert cash["for"].startswith("Order ") and order["order_number"] in cash["for"]
    assert (cash["method_label"], cash["status_label"]) == ("Cash", "Received")
    one = client.get(f"{shop['base']}/payments/{cash['id']}", headers=owner).json()["data"]
    assert one["for"] == cash["for"] and one["refundable_amount"] == 400
    assert client.get(f"{shop['base']}/payments?limit=0", headers=owner).status_code == 422


@DB
def test_a_business_without_the_counter_sets_its_upi_id_from_payments(monkeypatch: Any) -> None:
    """Payment links pay to the business's UPI ID. A café that never switches on
    counter billing must still be able to give one — from Payments."""
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, business_type="cafe", modules=("offerings-catalog", "orders", "payments"))
    base = f"/v1/platform/businesses/{bid}/payments/upi"
    assert client.get(base, headers=owner).json()["data"] == {"upi_vpa": None, "upi_payee_name": None}
    bad = client.put(base, json={"upi_vpa": "not a upi id"}, headers=owner)
    assert bad.status_code == 422 and "name@bank" in bad.text
    ok = client.put(base, json={"upi_vpa": "nilacafe@okicici", "upi_payee_name": "Nila Cafe"}, headers=owner)
    assert ok.status_code == 200, ok.text
    assert client.get(base, headers=owner).json()["data"]["upi_vpa"] == "nilacafe@okicici"
    assert sql("select upi_vpa from pos_settings where business_id = cast(:b as uuid)", b=bid) == [("nilacafe@okicici",)]


# ---------------------------------------------------------------- webhooks are kept and retried
def _signed(body: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "x-payment-signature": sig}


def _receipt(event_id: str) -> dict[str, Any]:
    rows = sql("select status, attempt_count, last_error, cast(payment_attempt_id as text) "
               "from payments_webhook_receipts where provider_event_id = :e", e=event_id)
    assert rows, f"no receipt kept for {event_id}"
    status, attempts, error, payment = rows[0]
    return {"status": status, "attempts": attempts, "error": error, "payment": payment}


def _retry_due(event_id: str) -> int:
    """Make the receipt due now and run the worker's retry lane once."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from platform_core.services.payment_webhook import PaymentWebhookService
    from platform_testing.phase_b import db_url

    sql("update payments_webhook_receipts set next_attempt_at = now() - interval '1 second' "
        "where provider_event_id = :e", e=event_id)
    receipt = uuid.UUID(str(sql("select id from payments_webhook_receipts where provider_event_id = :e",
                                e=event_id)[0][0]))

    async def run() -> int:
        engine = create_async_engine(db_url(), poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                # Only this test's receipt: the test database is shared by parallel tests.
                return int(await PaymentWebhookService.run_due(session, "test-worker", only=[receipt]))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _paid_attempt(monkeypatch: Any) -> tuple[dict[str, str], dict[str, Any], str]:
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    link = _ask(owner, shop, "order", order["id"], 1000, "full")
    return owner, shop, _online_attempt(shop, order["id"], link["id"], 1000)


@DB
def test_a_webhook_is_kept_applied_once_and_a_bad_signature_keeps_nothing(monkeypatch: Any) -> None:
    _, _, payment = _paid_attempt(monkeypatch)
    event = str(uuid.uuid4())
    raw, headers = _signed({"event_id": event, "payment_id": payment, "status": "succeeded",
                            "provider_reference": "pay_123"})
    first = client.post("/v1/webhooks/payments/stub", content=raw, headers=headers)
    assert first.status_code == 200 and first.json()["data"]["status"] == "processed", first.text
    again = client.post("/v1/webhooks/payments/stub", content=raw, headers=headers)
    assert again.status_code == 200 and again.json()["data"]["status"] == "duplicate"
    assert _receipt(event)["status"] == "processed" and _receipt(event)["attempts"] == 1
    assert sql("select status from payments_payment_attempts where id = cast(:p as uuid)", p=payment) == [("succeeded",)]

    forged = client.post("/v1/webhooks/payments/stub", content=raw.replace(b"succeeded", b"failed"),
                         headers=headers)
    assert forged.status_code in (400, 422)
    assert sql("select count(*) from payments_webhook_receipts where provider_event_id = :e", e=event) == [(1,)]


@DB
def test_an_event_that_arrives_before_its_payment_is_retried_until_it_applies(monkeypatch: Any) -> None:
    """Out of order: the provider's success lands before LOCAH saved the attempt."""
    owner, shop = _shop(monkeypatch)
    order = _order(owner, shop)
    link = _ask(owner, shop, "order", order["id"], 1000, "full")
    early = str(uuid.uuid4())
    event = str(uuid.uuid4())
    raw, headers = _signed({"event_id": event, "payment_id": early, "status": "succeeded"})
    r = client.post("/v1/webhooks/payments/stub", content=raw, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["status"] == "retrying", r.text  # kept, not bounced
    assert _receipt(event)["status"] == "retrying"
    sql("INSERT INTO payments_payment_attempts (id, business_id, source_type, source_id, amount, payment_method, "
        "status, provider, request_id, purpose) VALUES (CAST(:id AS uuid), CAST(:b AS uuid), 'order', "
        "CAST(:o AS uuid), 1000, 'online', 'processing', 'stub', CAST(:r AS uuid), 'full')",
        id=early, b=shop["bid"], o=order["id"], r=link["id"])
    assert _retry_due(event) == 1
    assert _receipt(event)["status"] == "processed" and _receipt(event)["attempts"] == 2
    assert sql("select payment_status from orders_orders where id = cast(:o as uuid)", o=order["id"]) == [("paid",)]


@DB
def test_a_transient_failure_is_retried_and_succeeds(monkeypatch: Any) -> None:
    from platform_core.services.payment_attempt import PaymentAttemptService

    _, _, payment = _paid_attempt(monkeypatch)
    real = PaymentAttemptService.apply_status

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database briefly unavailable")

    monkeypatch.setattr(PaymentAttemptService, "apply_status", flaky)
    event = str(uuid.uuid4())
    raw, headers = _signed({"event_id": event, "payment_id": payment, "status": "succeeded"})
    r = client.post("/v1/webhooks/payments/stub", content=raw, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["status"] == "retrying", r.text
    kept = _receipt(event)
    assert kept["status"] == "retrying" and "briefly unavailable" in kept["error"]
    assert sql("select status from payments_payment_attempts where id = cast(:p as uuid)", p=payment) == [("processing",)]

    monkeypatch.setattr(PaymentAttemptService, "apply_status", real)
    assert _retry_due(event) == 1
    assert _receipt(event)["status"] == "processed"
    assert sql("select status from payments_payment_attempts where id = cast(:p as uuid)", p=payment) == [("succeeded",)]


@DB
def test_a_webhook_that_keeps_failing_is_dead_lettered_and_shown(monkeypatch: Any) -> None:
    from platform_core.services.payment_attempt import PaymentAttemptService

    owner, shop, payment = _paid_attempt(monkeypatch)
    real = PaymentAttemptService.apply_status

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider payload not understood")

    monkeypatch.setattr(PaymentAttemptService, "apply_status", broken)
    event = str(uuid.uuid4())
    raw, headers = _signed({"event_id": event, "payment_id": payment, "status": "succeeded"})
    assert client.post("/v1/webhooks/payments/stub", content=raw, headers=headers).status_code == 200
    sql("update payments_webhook_receipts set max_attempts = 3 where provider_event_id = :e", e=event)
    _retry_due(event)
    assert _receipt(event)["status"] == "retrying"
    _retry_due(event)
    assert _receipt(event)["status"] == "dead_letter"
    assert _retry_due(event) == 0  # given up: no retry storm
    dead = sql("select event_type, attempt_count from platform_dead_letter_events "
               "where source_table = 'payments_webhook_receipts' and payload->>'event_id' = :e", e=event)
    assert dead == [("payment.webhook.stub", 3)]
    flagged = client.get(f"{shop['base']}/collect/overview", headers=owner).json()["data"]["needs_attention"]
    assert [(a["id"], a["attention"]) for a in flagged] == [(payment, "provider_update_failed")]

    # Once the cause is fixed, a platform admin puts it back into the retry lane.
    receipt_id = sql("select cast(id as text) from payments_webhook_receipts where provider_event_id = :e", e=event)[0][0]
    assert client.post(f"/v1/admin/payment-webhooks/{receipt_id}/retry", headers=owner).status_code == 403
    admin_id, admin = new_identity(monkeypatch)
    sql("insert into platform_admin_grants (identity_id, granted_by, reason) values "
        "(cast(:i as uuid), cast(:i as uuid), 'payment webhook test')", i=str(admin_id))
    requeued = client.post(f"/v1/admin/payment-webhooks/{receipt_id}/retry", headers=admin)
    assert requeued.status_code == 200, requeued.text
    monkeypatch.setattr(PaymentAttemptService, "apply_status", real)  # the cause is fixed
    assert _retry_due(event) == 1
    assert _receipt(event)["status"] == "processed"
    assert sql("select status from payments_payment_attempts where id = cast(:p as uuid)", p=payment) == [("succeeded",)]
    assert sql("select resolution_note from platform_dead_letter_events where source_id = cast(:r as uuid)",
               r=receipt_id) == [("Requeued for retry",)]
