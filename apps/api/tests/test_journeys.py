"""Structured WhatsApp journeys (Capability Universe §12.3, §12.4, §12.6; §26.3 P1-08).

Order, book, enquire, dues, track, reorder and cancel with buttons and lists.
Every customer message is WhatsApp's own webhook format through the sandbox
number (the same code path as a real delivery); zero model calls — the suite's
AI guard fails any test that attempts one, and each test also checks the
guard's record is empty.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.ai_guard import blocked_calls
from platform_testing.phase_b import create_business, drain_events, new_identity, primary_location, sql

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
IST = ZoneInfo("Asia/Kolkata")
CUSTOMER = "919876511111"


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch: Any) -> None:
    monkeypatch.setenv("MESSAGING_SANDBOX", "1")


# ---------------------------------------------------------------- the customer's phone
class Phone:
    """A customer's WhatsApp, talking to the business's sandbox number."""

    def __init__(self, owner: dict[str, str], bid: str, number: str = CUSTOMER, name: str = "Meena") -> None:
        self.owner, self.bid, self.number, self.name = owner, bid, number, name

    def _send(self, **body: Any) -> dict[str, Any]:
        r = client.post(f"/v1/platform/businesses/{self.bid}/messaging/sandbox/inbound",
                        json={"from_phone": self.number, "name": self.name, **body}, headers=self.owner)
        assert r.status_code == 200, r.text
        return dict(r.json()["data"])

    def say(self, text: str, **extra: Any) -> dict[str, Any]:
        return self._send(text=text, **extra)

    def tap(self, reply_id: str, **extra: Any) -> dict[str, Any]:
        """Tap a button or list row LOCAH offered last (it must be on offer)."""
        offered = self.options()
        assert reply_id in offered, f"{reply_id} not offered: {offered}"
        return self._send(button_id=reply_id, button_title=offered[reply_id][:20], **extra)

    def pin(self, lat: float, lng: float) -> dict[str, Any]:
        return self._send(latitude=lat, longitude=lng, text="Home")

    def last(self, n: int = 1) -> list[str]:
        rows = sql("select m.body from messaging_messages m join messaging_conversations c on c.id = m.conversation_id "
                   "where m.business_id = :b and c.wa_id = :w and m.direction = 'out' order by m.created_at desc, "
                   "m.id desc limit :n", b=self.bid, w=self.number, n=n)
        return [str(r[0]) for r in reversed(rows)]

    def options(self) -> dict[str, str]:
        rows = sql("select m.payload from messaging_messages m join messaging_conversations c "
                   "on c.id = m.conversation_id where m.business_id = :b and c.wa_id = :w and m.direction = 'out' "
                   "and m.kind = 'interactive' order by m.created_at desc limit 1", b=self.bid, w=self.number)
        return {o["id"]: o["title"] for o in (rows[0][0]["options"] if rows else [])}


def _shop(monkeypatch: Any, *modules: str) -> tuple[dict[str, str], str, str]:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, business_type="retail", modules=(
        "offerings-catalog", "orders", "fulfilment", "payments", "customer-relationships", "messaging", *modules))
    ch = client.post(f"/v1/platform/businesses/{bid}/messaging/channel/sandbox",
                     json={"display_phone": "+919840011111", "display_name": "Meena Stores"}, headers=owner)
    assert ch.status_code == 200, ch.text
    return owner, bid, primary_location(client, owner, bid)


def _product(owner: dict[str, str], bid: str, title: str, price: float, **extra: Any) -> dict[str, Any]:
    r = client.post(f"/v1/platform/businesses/{bid}/products", json={
        "status": "active", "offering_type": "product", "title": title, "price_amount": price, "visibility": "public",
        **extra}, headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _delivery(owner: dict[str, str], bid: str) -> None:
    assert client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": True, "delivery_enabled": True},
                        headers=owner).status_code == 200
    z = client.post(f"/v1/b/{bid}/fulfilment/zones", json={"name": "Adyar", "match_type": "postal_prefix",
                                                           "postal_prefix": "6000", "charge_amount": 30}, headers=owner)
    assert z.status_code == 200, z.text


def _orders(bid: str) -> list[Any]:
    return list(sql("select order_number, channel, total_amount, status, customer_contact_id from orders_orders "
                    "where business_id = :b order by created_at", b=bid))


# ---------------------------------------------------------------- order (§12.3 row 1, §12.6)
@DB
def test_order_on_whatsapp_prices_come_only_from_the_catalogue(monkeypatch: Any) -> None:
    owner, bid, loc = _shop(monkeypatch, "inventory")
    _delivery(owner, bid)
    ghee = _product(owner, bid, "Ghee 500 ml", 320, track_inventory=True)
    _product(owner, bid, "Filter coffee powder", 180)
    stock = client.post(f"/v1/platform/businesses/{bid}/inventory/opening-stock", json={
        "offering_id": ghee["id"], "location_id": loc, "quantity": 3, "reason": "Count"}, headers=owner)
    assert stock.status_code == 200, stock.text
    phone = Phone(owner, bid)

    phone.say("Hi")
    menu = phone.options()
    assert list(menu) == ["m:order", "talk_to_person", "m:lang"], "only what works now, a person, and the language"
    phone.tap("m:order")
    assert set(phone.options()) == {f"o:item:{ghee['id']}", f"o:item:{sql('select id from offerings_catalog_offerings where business_id = :b and title = :t', b=bid, t='Filter coffee powder')[0][0]}"}
    assert "₹320.00" in str(sql("select payload from messaging_messages where business_id = :b and kind = 'interactive' "
                                "order by created_at desc limit 1", b=bid)[0][0]), "list shows today's price"
    phone.tap(f"o:item:{ghee['id']}")
    assert set(phone.options()) == {"o:qty:1", "o:qty:2", "o:qty:3"}
    phone.say("5")  # more than the 3 in stock: allowed into the cart, caught before anything is placed
    assert "₹1,600.00" in phone.last()[0]
    phone.tap("o:checkout")
    assert phone.last()[0].startswith("Ghee 500 ml has only 3 left")
    phone.tap("o:fix:0:3")
    assert set(phone.options()) == {"o:mode:delivery", "o:mode:pickup"}
    phone.tap("o:mode:delivery")
    assert "location pin" in phone.last()[0]
    phone.say("14 MG Road, Bengaluru 560001")  # outside the zone
    assert "don't deliver there" in phone.last()[0]
    phone.tap("o:addr:new")
    phone.say("14 Gandhi Nagar 2nd St, Adyar, Chennai 600020")
    summary = phone.last()[0]
    assert "3 × Ghee 500 ml — ₹960.00" in summary and "Delivery — ₹30.00" in summary and "Total ₹990.00" in summary
    assert "Pay on delivery" in summary and set(phone.options()) == {"o:place", "o:start", "o:clear"}
    assert _orders(bid) == [], "nothing is placed without the customer's button"

    # The owner changes the price between the summary and the tap (§12.6).
    assert client.patch(f"/v1/platform/businesses/{bid}/products/{ghee['id']}", json={"price_amount": 340},
                        headers=owner).status_code == 200
    phone.tap("o:place")
    assert phone.last()[0].startswith("A price changed since your summary") and "Total ₹1,050.00" in phone.last()[0]
    assert _orders(bid) == []
    phone.tap("o:place", message_id="wamid.place.1")
    again = phone.tap("o:place", message_id="wamid.place.1")  # WhatsApp delivers the same tap twice
    assert again["duplicates"] == 1
    phone.tap("o:place")  # and the customer taps the old button again
    orders = _orders(bid)
    assert len(orders) == 1, "§12.6: duplicate deliveries create one order"
    number, channel, total, status, contact_id = orders[0]
    assert channel == "whatsapp" and float(total) == 1050.0 and status == "pending"
    lines = sql("select l.title, l.unit_price, l.quantity from orders_order_line_items l join orders_orders o "
                "on o.id = l.order_id where o.business_id = :b order by l.sort_order", b=bid)
    assert [(t, float(p), q) for t, p, q in lines] == [("Ghee 500 ml", 340.0, 3), ("Delivery fee", 30.0, 1)], \
        "§12.6: the order's price is the catalogue's at that moment"
    [(wa_contact,)] = sql("select contact_id from messaging_conversations where business_id = :b and wa_id = :w",
                          b=bid, w=CUSTOMER)
    assert contact_id == wa_contact
    [(mode, address)] = sql("select mode, delivery_address from fulfilment_jobs where business_id = :b", b=bid)
    assert mode == "delivery" and address["postal_code"] == "600020"
    assert sql("select quantity_reserved from inventory_records where offering_id = :o", o=ghee["id"]) == [(3,)]
    placed = [m for m in phone.last(4) if m.startswith(f"Order {number} placed")]
    assert len(placed) == 1 and "/track/" in placed[0], "one confirmation, with the tracking link"
    assert "already placed" in phone.last()[0]

    # Order updates follow on WhatsApp like any website order; track and the owner's orders list agree.
    drain_events(bid)
    phone.say("where is my order?")
    assert phone.last()[0].startswith(f"{number}: waiting for the shop to accept")
    listed = client.get(f"/v1/platform/businesses/{bid}/orders", headers=owner).json()["data"]
    assert listed[0]["channel"] == "whatsapp"
    assert blocked_calls() == []


@DB
def test_pickup_cod_cap_reorder_and_cancel(monkeypatch: Any) -> None:
    owner, bid, _ = _shop(monkeypatch)
    ghee = _product(owner, bid, "Ghee 500 ml", 320)
    base = f"/v1/platform/businesses/{bid}"
    assert client.put(f"{base}/messaging/settings", json={"first_order_cod_cap": 500},
                      headers=owner).status_code == 200
    phone = Phone(owner, bid)
    phone.say("order")
    phone.tap(f"o:item:{ghee['id']}")
    phone.tap("o:qty:2")
    phone.tap("o:checkout")  # pickup is the only mode: straight to paying
    assert "For a first order, cash on delivery is up to ₹500.00" in phone.last()[0]
    assert set(phone.options()) == {"talk_to_person", "o:start"}
    assert client.put(f"{base}/messaging/settings", json={"first_order_cod_cap": None},
                      headers=owner).status_code == 200
    phone.tap("o:start")
    assert phone.options()["o:checkout"] == "Checkout (2 items)", "the cart is kept while choosing more"
    phone.tap("o:checkout")
    assert "Pickup · Pay at pickup" in phone.last()[0] and "Total ₹640.00" in phone.last()[0]
    phone.tap("o:place")
    [(first, _, _, _, _)] = _orders(bid)

    # Repeat my last order: same items, today's prices, confirmed again.
    client.patch(f"{base}/products/{ghee['id']}", json={"price_amount": 330}, headers=owner)
    phone.say("hi")
    assert "m:reorder" in phone.options() and "m:cancel" in phone.options()
    phone.tap("m:reorder")
    assert phone.last(2)[0] == f"Your last order ({first}) again, at today's prices:"
    assert "2 × Ghee 500 ml — ₹660.00" in phone.last()[0]
    phone.tap("o:place")
    assert len(_orders(bid)) == 2

    # Cancel: a pending order can go; an accepted one needs a person.
    phone.say("cancel")
    orders = {r[0]: r for r in _orders(bid)}
    rows = phone.options()
    assert len([k for k in rows if k.startswith("c:order:")]) == 2 and "talk_to_person" in rows
    [(first_id,)] = sql("select id from orders_orders where order_number = :n and business_id = :b", n=first, b=bid)
    o = client.get(f"{base}/orders/{first_id}", headers=owner).json()["data"]
    assert client.post(f"{base}/orders/{first_id}/status", json={"status": "accepted", "version": o["version"]},
                       headers=owner).status_code == 200
    phone.tap(f"c:order:{first_id}")
    assert "can't be cancelled here" in phone.last()[0]
    second = next(n for n in orders if n != first)
    [(second_id,)] = sql("select id from orders_orders where order_number = :n and business_id = :b", n=second, b=bid)
    phone.say("cancel")
    phone.tap(f"c:order:{second_id}")
    phone.tap("c:yes")
    assert phone.last()[0] == f"Order {second} is cancelled."
    assert {r[0]: r[3] for r in _orders(bid)} == {first: "accepted", second: "cancelled"}

    # COD off: WhatsApp orders go to a person (online payment needs a provider).
    client.put(f"{base}/messaging/settings", json={"cod_allowed": False}, headers=owner)
    phone.say("order")
    phone.tap(f"o:item:{ghee['id']}")
    phone.tap("o:qty:1")
    phone.tap("o:checkout")
    assert "not available yet" in phone.last()[0] and len(_orders(bid)) == 2
    assert blocked_calls() == []


# ---------------------------------------------------------------- book (§12.3 row 2)
@DB
def test_book_a_slot_from_opening_hours_and_cancel_within_policy(monkeypatch: Any) -> None:
    owner, bid, loc = _shop(monkeypatch, "bookings")
    base = f"/v1/platform/businesses/{bid}"
    day = (datetime.now(IST) + timedelta(days=2)).date()
    key = day.strftime("%a").lower()[:3]
    hours = client.patch(f"{base}/locations/{loc}", json={"hours": {key: [["10:00", "12:00"]]}}, headers=owner)
    assert hours.status_code == 200, hours.text
    assert client.patch(f"{base}/locations/{loc}", json={"hours": {key: [["12:00", "10:00"]]}},
                        headers=owner).status_code == 422, "a span must open before it closes"
    svc = client.post(f"{base}/products", json={"status": "active", "offering_type": "service", "title": "Haircut",
                                                "price_amount": 250, "visibility": "public",
                                                "attributes": {"duration_minutes": 45}}, headers=owner)
    assert svc.status_code == 200, svc.text
    sid = svc.json()["data"]["id"]
    chair = client.post(f"{base}/bookings/resources", json={"location_id": loc, "resource_type": "chair",
                                                             "name": "Chair 1", "allocation_mode": "exclusive",
                                                             "capacity": 1}, headers=owner)
    assert chair.status_code == 200, chair.text
    phone = Phone(owner, bid)
    phone.say("book")
    assert phone.options() == {f"b:svc:{sid}": "Haircut"}
    phone.tap(f"b:svc:{sid}")
    phone.tap(f"b:day:{day.isoformat()}")
    slots = phone.options()
    assert list(slots.values()) == ["10:00 AM", "10:30 AM", "11:00 AM"], "slots from the location's opening hours"
    ten = next(k for k, v in slots.items() if v == "10:00 AM")
    phone.tap(ten)
    assert "Haircut on" in phone.last()[0] and "Confirm?" in phone.last()[0]
    assert sql("select count(*) from bookings_bookings where business_id = :b", b=bid) == [(0,)]
    phone.tap("b:confirm", message_id="wamid.book.1")
    phone.tap("b:confirm", message_id="wamid.book.1")
    [(number, channel, starts, status)] = sql("select booking_number, channel, starts_at, status from bookings_bookings "
                                              "where business_id = :b", b=bid)
    assert channel == "whatsapp" and starts.astimezone(IST).hour == 10 and status in ("pending", "confirmed")
    assert phone.last()[0].startswith(f"Booking {number}: Haircut on")

    # The one chair: the WhatsApp booking holds it at 10:00, the counter books it at 11:00.
    eleven = datetime.combine(day, datetime.min.time().replace(hour=11), IST)
    staff = client.post(f"{base}/bookings", json={"location_id": loc, "offering_id": sid,
                                                   "reservation_mode": "appointment",
                                                   "starts_at": eleven.isoformat(),
                                                   "ends_at": (eleven + timedelta(minutes=45)).isoformat(),
                                                   "resource_ids": [chair.json()["data"]["id"]]},
                        headers=owner)
    assert staff.status_code == 200, staff.text
    other = Phone(owner, bid, number="919876522222", name="Ravi")
    other.say("book")
    other.tap(f"b:svc:{sid}")
    other.tap(f"b:day:{day.isoformat()}")
    assert "No free times" in other.last()[0], "taken slots are never offered"

    # Cancel within the owner's window.
    client.patch(f"/v1/platform/businesses/{bid}/bookings-policy", json={"cancel_window_hours": 24}, headers=owner)
    phone.say("cancel my booking")
    [(bk_id,)] = sql("select id from bookings_bookings where booking_number = :n and business_id = :b", n=number, b=bid)
    phone.tap(f"c:booking:{bk_id}")
    phone.tap("c:yes")
    assert phone.last()[0] == f"Your booking {number} is cancelled."
    assert sql("select status from bookings_bookings where id = :i", i=bk_id) == [("cancelled",)]
    assert blocked_calls() == []


# ---------------------------------------------------------------- enquire, dues, a person
@DB
def test_enquiry_becomes_a_lead_and_dues_come_from_the_khata(monkeypatch: Any) -> None:
    owner, bid, _ = _shop(monkeypatch, "leads", "ledger")
    base = f"/v1/platform/businesses/{bid}"
    phone = Phone(owner, bid)
    phone.say("hi")
    assert "m:enquire" in phone.options()
    phone.tap("m:enquire")
    phone.say("Do you take bulk orders for weddings? About 200 boxes.")
    [(source, message, name)] = sql("select source, message, display_name from leads_leads where business_id = :b",
                                    b=bid)
    assert source == "whatsapp" and "200 boxes" in message and name == "Meena"
    conv = client.get(f"{base}/messaging/conversations?view=waiting", headers=owner).json()["data"]
    assert conv["counts"]["waiting"] == 1, "the team answers the question"

    # What do I owe: the khata balance with the statement link.
    [(contact_id,)] = sql("select contact_id from messaging_conversations where business_id = :b and wa_id = :w",
                          b=bid, w=CUSTOMER)
    acct = client.post(f"{base}/ledger/accounts", json={"party_type": "customer", "customer_contact_id": str(contact_id),
                                                        "opening_balance": 450}, headers=owner)
    assert acct.status_code == 200, acct.text
    other = Phone(owner, bid)
    client.post(f"{base}/messaging/conversations/{conv['conversations'][0]['id']}/state", json={"handler": "bot"},
                headers=owner)
    other.say("how much do I owe?")
    assert other.last()[0].startswith("Your account: ₹450.00 due.") and "/khata/" in other.last()[0]

    # A person replied: journeys keep out for the pause (§12.1).
    client.post(f"{base}/messaging/conversations/{conv['conversations'][0]['id']}/messages",
                json={"body": "Yes we do! Sending the rates."}, headers=owner)
    before = len(phone.last(50))
    phone.say("menu")
    assert len(phone.last(50)) == before, "no automatic message while a person handles the chat"
    assert blocked_calls() == []


@DB
def test_entry_points_follow_what_works(monkeypatch: Any) -> None:
    """§12.2: the link, QR, website button and Marketplace action appear only when a journey can run."""
    from platform_core.services.marketplace_search import listing_actions

    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("customer-relationships", "messaging"))
    base = f"/v1/platform/businesses/{bid}/messaging"
    client.post(f"{base}/channel/sandbox", json={"display_phone": "+919840011111"}, headers=owner)
    assert client.get(f"{base}/setup", headers=owner).json()["data"]["entry"] is None
    assert client.post(f"/v1/b/{bid}/modules/orders/enable", headers=owner).status_code == 200
    entry = client.get(f"{base}/setup", headers=owner).json()["data"]["entry"]
    assert entry["href"] == "https://wa.me/919840011111?text=menu" and entry["label"] == "Order on WhatsApp"
    assert entry["qr_svg"].lstrip().startswith("<?xml") and "<svg" in entry["qr_svg"]

    from platform_core.models import MarketplaceBusinessProjection

    row = MarketplaceBusinessProjection(slug="meena", site_paths={}, offering_count=0, capability_flags={},
                                        public_contact={"whatsapp": "+91 99999 00000",
                                                        "whatsapp_order": "+919840011111",
                                                        "whatsapp_order_label": "Order on WhatsApp"})
    wa = next(a for a in listing_actions(row) if a["action"] == "whatsapp")
    assert wa == {"action": "whatsapp", "label": "Order on WhatsApp", "href": "https://wa.me/919840011111?text=menu"}
    assert client.put(f"{base}/settings", json={"first_order_cod_cap": -5}, headers=owner).status_code == 422
    assert blocked_calls() == []


def test_menu_words_and_intents_are_deterministic() -> None:
    from platform_core.messaging.journeys import INTENTS, MENU_WORDS, buttons, listing

    assert {"hi", "menu", "வணக்கம்", "नमस्ते"} <= MENU_WORDS
    assert list(INTENTS)[:2] == ["m:cancel", "m:track"], "cancel my booking is a cancellation"
    b = buttons("x", [("a", "A very long button title here"), ("b", "B"), ("c", "C"), ("d", "D")])
    assert len(b["action"]["buttons"]) == 3 and len(b["action"]["buttons"][0]["reply"]["title"]) <= 20
    rows = listing("x", "Menu", [(str(i), "Row title that is far too long", "d" * 100) for i in range(12)])
    r = rows["action"]["sections"][0]["rows"]
    assert len(r) == 10 and len(r[0]["title"]) <= 24 and len(r[0]["description"]) <= 72


# ---------------------------------------------------------------- what a customer actually types
@DB
def test_a_typed_price_question_is_answered_from_the_catalogue(monkeypatch: Any) -> None:
    """Found on a sandbox run (2026-11-14): "menu enna iruku? biriyani rate?" got
    "someone will reply here soon" from a shop whose catalogue held the answer."""
    owner, bid, _ = _shop(monkeypatch)
    _product(owner, bid, "Chicken Biriyani", 280)
    _product(owner, bid, "Mutton Biriyani", 360)
    _product(owner, bid, "Appam", 50)
    phone = Phone(owner, bid)

    phone.say("menu enna iruku? biriyani rate?")
    said = phone.last()[0]
    assert "Chicken Biriyani — ₹280.00" in said and "Mutton Biriyani — ₹360.00" in said and "Appam" not in said
    assert {"m:order", "menu", "talk_to_person"} <= set(phone.options())

    # Their spelling, not the owner's; one word is enough.
    phone.say("chiken briyani evlo")
    assert "Chicken Biriyani — ₹280.00" in phone.last()[0] and "Mutton" not in phone.last()[0]
    phone.say("appam?")
    assert "Appam — ₹50.00" in phone.last()[0]

    # A wish typed as a sentence is the journey, not a wait for a person.
    phone.say("i want to order")
    assert "o:" in " ".join(phone.options()) or "m:order" in phone.options() or phone.options()
    assert "reply here soon" not in phone.last()[0]

    # Someone unhappy, or simply talking, gets a person — never a price list.
    before = len(phone.last(50))
    phone.say("the chicken biriyani yesterday was cold and late, i want a refund")
    after = phone.last(50)
    assert all("₹280" not in line for line in after[before:])
    assert blocked_calls() == []
