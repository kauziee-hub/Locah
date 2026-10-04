"""P2-02: one recurring-relationship engine (Founder refinement — Memberships & Subscriptions).

Pure tests pin the lifecycle arithmetic. Database tests go through the owner
API and the engine on local PostgreSQL: payment replay never extends twice, a
10-day freeze moves the end by exactly 10 days, early renewal keeps every paid
day, a session is used once per key, subscriptions skip / change one day /
pause and turn tomorrow into real orders once, postpaid deliveries bill once,
fee instalments, AMC visits and dues, the renewal ladder through the real
automation engine and Messaging (sent once, quiet hours, stopped by renewal,
grace → expired, win-back only with consent), front-desk check-in colours,
and tenant isolation of every new table.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.memberships import lifecycle as lc
from platform_testing.phase_b import (
    assert_tenant_isolated,
    create_business,
    db_url,
    drain_events,
    new_identity,
    primary_location,
    run_automation,
    sql,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


# ---------------------------------------------------------------- pure
def _p(pid: str, seq: int, start: datetime, days: int, paid: bool = True, sessions: int | None = None) -> lc.PeriodRow:
    return lc.PeriodRow(pid, seq, start, start + timedelta(days=days), D(1500), D(1500) if paid else D(0),
                        "paid" if paid else "unpaid", sessions)


def test_state_follows_what_happened_not_a_stored_flag() -> None:
    t0 = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)  # 10:00 IST
    one = [_p("a", 1, t0, 30)]
    base = dict(stored_status="active", starts_at=t0, ends_at=None, grace_days=3)
    st = lc.compute("access", now=t0 + timedelta(days=5), periods=one, **base)
    assert (st.status, st.days_remaining, st.expiring_soon) == ("active", 25, False)
    assert lc.compute("access", now=t0 + timedelta(days=25), periods=one, **base).expiring_soon  # derived, not a state
    grace = lc.compute("access", now=t0 + timedelta(days=31), periods=one, **base)
    assert grace.status == "grace" and grace.grace_until == t0 + timedelta(days=33)
    assert lc.compute("access", now=t0 + timedelta(days=34), periods=one, **base).status == "expired"
    assert lc.compute("access", now=t0, periods=[_p("a", 1, t0, 30, paid=False)], **base).status == "pending"
    frozen = lc.compute("access", now=t0 + timedelta(days=12), periods=one,
                        freezes=[lc.FreezeRow(date(2026, 10, 11), date(2026, 10, 20))], **base)
    assert frozen.status == "paused"
    assert lc.compute("access", now=t0, periods=one, stored_status="cancelled", starts_at=t0,
                      ends_at=None).status == "cancelled"


def test_session_packs_count_both_validity_and_sessions() -> None:
    t0 = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
    pack = [_p("a", 1, t0, 60, sessions=10)]
    kw = dict(stored_status="active", starts_at=t0, ends_at=None)
    assert lc.compute("session_pack", now=t0 + timedelta(days=3), periods=pack, sessions_used={"a": 6},
                      **kw).sessions_remaining == 4
    used_up = lc.compute("session_pack", now=t0 + timedelta(days=3), periods=pack, sessions_used={"a": 10}, **kw)
    assert (used_up.status, used_up.reason) == ("expired", "All sessions used")


def test_fee_plans_are_enrolled_while_overdue_and_dues_give_good_standing() -> None:
    t0 = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
    inst = [lc.InstalmentRow(1, D(10000), D(10000), date(2026, 10, 1), "paid"),
            lc.InstalmentRow(2, D(10000), D(0), date(2026, 11, 1), "due"),
            lc.InstalmentRow(3, D(10000), D(0), date(2026, 12, 1), "due")]
    st = lc.compute("fee_plan", now=datetime(2026, 11, 5, 5, 0, tzinfo=UTC), stored_status="active", starts_at=t0,
                    ends_at=t0 + timedelta(days=120), instalments=inst)
    assert (st.status, st.overdue, st.paid, st.outstanding, st.next_due_on) == (
        "active", True, D(10000), D(20000), date(2026, 11, 1))
    dues = [_p("y", 1, t0, 365)]
    assert lc.compute("member_dues", now=t0 + timedelta(days=10), periods=dues, stored_status="active",
                      starts_at=t0, ends_at=None).good_standing is True
    assert lc.compute("member_dues", now=t0 + timedelta(days=400), periods=dues, stored_status="active",
                      starts_at=t0, ends_at=None).good_standing is False


def test_early_renewal_goes_after_the_current_period_and_visits_spread_over_the_contract() -> None:
    t0 = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)
    start, end = lc.next_period_window(now=t0 + timedelta(days=19), periods=[_p("a", 1, t0, 30)], duration_days=31)
    assert start == t0 + timedelta(days=30) and end == start + timedelta(days=31)  # 20 Dec renew → 31 Dec start
    visits = lc.visit_dates(date(2026, 1, 1), date(2027, 1, 1), count=2, every_days=None)
    assert len(visits) == 2 and all(date(2026, 1, 1) < v < date(2027, 1, 1) for v in visits)


# ---------------------------------------------------------------- helpers
def svc(fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
    async def _go() -> Any:
        engine = create_async_engine(db_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as session:
                out = await fn(session)
                await session.commit()
                return out
        finally:
            await engine.dispose()

    return asyncio.run(_go())


def _gym(monkeypatch: Any, *extra: str) -> tuple[dict[str, str], str, str]:
    monkeypatch.setenv("MESSAGING_SANDBOX", "1")
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, business_type="other", modules=(
        "offerings-catalog", "memberships", "payments", "customer-relationships", *extra))
    return owner, bid, f"/v1/platform/businesses/{bid}"


def _plan(owner: dict[str, str], base: str, **kw: Any) -> dict[str, Any]:
    body = {"name": f"Plan {uuid.uuid4().hex[:5]}", "price_amount": 1500, "duration_days": 30, "status": "active",
            "visibility": "public", **kw}
    r = client.post(f"{base}/membership-plans", json=body, headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _customer(owner: dict[str, str], base: str, name: str = "Arun", phone: str | None = None) -> str:
    r = client.post(f"{base}/customers", json={"display_name": name,
                                                "phone": phone or f"+9198{uuid.uuid4().int % 10**8:08d}"},
                    headers=owner)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["id"])


def _enrol(owner: dict[str, str], base: str, plan_id: str, contact: str, **kw: Any) -> dict[str, Any]:
    r = client.post(f"{base}/membership-enrolments", json={
        "plan_id": plan_id, "customer_contact_id": contact, "payment_method": "pay_at_business",
        "idempotency_key": str(uuid.uuid4()), **kw}, headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _pay(owner: dict[str, str], base: str, eid: str, amount: float) -> dict[str, Any]:
    r = client.post(f"{base}/collect/record", json={"source_type": "membership", "source_id": eid,
                                                     "amount": amount, "method": "cash"}, headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _detail(owner: dict[str, str], base: str, eid: str) -> dict[str, Any]:
    r = client.get(f"{base}/membership-enrolments/{eid}", headers=owner)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"]["detail"])


def _iso_days(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400


# ---------------------------------------------------------------- gym: pay, replay, freeze, renew early
@DB
def test_gym_payment_replay_freeze_and_early_renewal(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch)
    plan = _plan(owner, base, grace_days=3, grace_allows_entry=True, freeze_allowed=True, max_freeze_days=30)
    assert plan["plan_kind"] == "access" and plan["kind_label"] == "Membership"
    contact = _customer(owner, base)
    e = _enrol(owner, base, plan["id"], contact)
    assert e["status"] == "pending" and e["checkin_code"]
    paid = _pay(owner, base, e["id"], 1500)
    assert paid["due"]["state"] == "paid"
    d = _detail(owner, base, e["id"])
    assert d["status"] == "active" and len(d["periods"]) == 1 and d["periods"][0]["payment_state"] == "paid"
    first_end = d["valid_until"]

    # A replayed payment (webhook twice, a retried job) applies nothing more.
    pid = sql("select id from payments_payment_attempts where source_id = :e and status = 'succeeded'", e=e["id"])[0][0]

    async def replay(session: AsyncSession) -> bool:
        from platform_core.memberships.service import MembershipCore
        from platform_core.models import PaymentAttempt

        payment = await session.get(PaymentAttempt, pid)
        assert payment is not None
        return bool(await MembershipCore.apply_payment(session, payment))

    assert svc(replay) is False and svc(replay) is False
    assert sql("select count(*) from memberships_payment_applications where payment_attempt_id = :p", p=pid) == [(1,)]
    assert _detail(owner, base, e["id"])["valid_until"] == first_end

    # A 10-day freeze moves the end by exactly 10 days; what was bought stays on record.
    start = (datetime.now(IST) + timedelta(days=3)).date()
    f = client.post(f"{base}/membership-enrolments/{e['id']}/freezes",
                    json={"starts_on": start.isoformat(), "days": 10, "reason": "Travelling"}, headers=owner)
    assert f.status_code == 200, f.text
    d = f.json()["data"]
    assert _iso_days(first_end, d["valid_until"]) == 10
    assert d["periods"][0]["extended_days"] == 10 and d["periods"][0]["base_ends_at"] != d["periods"][0]["ends_at"]
    assert [(x["days"], x["reason"]) for x in d["freezes"]] == [(10, "Travelling")]
    over = client.post(f"{base}/membership-enrolments/{e['id']}/freezes",
                       json={"starts_on": (start + timedelta(days=15)).isoformat(), "days": 25}, headers=owner)
    assert over.status_code == 422 and "20 are left" in over.text
    frozen_end = d["valid_until"]

    # Renewing early queues the next period after the current one — no day lost.
    r = client.post(f"{base}/membership-enrolments/{e['id']}/renew", headers=owner)
    assert r.status_code == 200, r.text
    nxt = r.json()["data"]["period"]
    assert nxt["starts_at"] == frozen_end and nxt["source"] == "early_renewal" and nxt["payment_state"] == "unpaid"
    again = client.post(f"{base}/membership-enrolments/{e['id']}/renew", headers=owner).json()["data"]["period"]
    assert again["id"] == nxt["id"], "asking twice does not stack charges"
    _pay(owner, base, e["id"], 1500)
    d = _detail(owner, base, e["id"])
    assert _iso_days(frozen_end, d["valid_until"]) == 30 and len(d["periods"]) == 2
    assert [p["seq"] for p in d["periods"]] == [1, 2], "history keeps both periods"
    # The renewal ladder follows the new end; steps for the old end are cancelled.
    live = sql("select period_key from automation_steps where entity_id = :e and ladder_key = 'membership.renewal' "
               "and status = 'pending'", e=e["id"])
    assert {r[0] for r in live} == {datetime.fromisoformat(d["valid_until"]).strftime("%Y%m%d%H%M")}


@DB
def test_the_member_page_day_is_the_business_calendar_day_not_utc(monkeypatch: Any) -> None:
    # 00:30 IST on 1 Oct is still 30 Sep in UTC. The member page's "today" (the
    # skip-a-day and freeze forms default from it) is the business's own day.
    import platform_core.memberships.service as membership_service

    owner, bid, base = _gym(monkeypatch)
    e = _enrol(owner, base, _plan(owner, base)["id"], _customer(owner, base))
    monkeypatch.setattr(membership_service, "_now", lambda: datetime(2026, 9, 30, 19, 0, tzinfo=UTC))
    assert _detail(owner, base, e["id"])["today"] == "2026-10-01"
    sql("update business_locations set timezone = 'America/New_York' where business_id = :b", b=bid)
    assert _detail(owner, base, e["id"])["today"] == "2026-09-30"


# ---------------------------------------------------------------- front desk
@DB
def test_checkin_is_green_amber_or_red_from_the_membership(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch)
    plan = _plan(owner, base, grace_days=3, grace_allows_entry=True)
    e = _enrol(owner, base, plan["id"], _customer(owner, base))
    red = client.post(f"{base}/membership-checkin", json={"code": e["checkin_code"]}, headers=owner).json()["data"]
    assert (red["decision"], red["colour"], red["reason"]) == ("denied", "red", "Not paid yet")
    _pay(owner, base, e["id"], 1500)
    green = client.post(f"{base}/membership-checkin", json={"code": e["checkin_code"].lower()},
                        headers=owner).json()["data"]
    assert (green["decision"], green["colour"]) == ("allowed", "green")
    ended = datetime.fromisoformat(green["valid_until"])

    def at(moment: datetime) -> dict[str, Any]:
        from platform_core.memberships.service import MembershipCore

        async def run(session: AsyncSession) -> dict[str, Any]:
            await session.execute(text("select set_config('app.current_business_id', :b, true)"), {"b": bid})
            decision: dict[str, Any] = await MembershipCore.checkin_decision(
                session, uuid.UUID(bid), uuid.UUID(e["id"]), now=moment)
            return decision

        result: dict[str, Any] = svc(run)
        return result

    amber = at(ended + timedelta(days=1))
    assert (amber["decision"], amber["colour"], amber["status"]) == ("warning", "amber", "grace")
    late = at(ended + timedelta(days=5))
    assert (late["decision"], late["colour"], late["renew"]) == ("denied", "red", "Renew membership")


# ---------------------------------------------------------------- session packs and bookings
@DB
def test_session_pack_is_the_count_bookings_ask_and_a_session_is_used_once(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch, "bookings", "workforce")
    loc = primary_location(client, owner, bid)
    yoga = client.post(f"{base}/products", json={"title": "Morning yoga", "offering_type": "class_session",
                                                 "status": "active", "price_amount": 300},
                       headers=owner).json()["data"]["id"]
    plan = _plan(owner, base, plan_kind="session_pack", sessions_included=3, duration_days=60, price_amount=900,
                 consume_on="booked", offering_access=[yoga])
    contact = _customer(owner, base)
    e = _enrol(owner, base, plan["id"], contact)
    _pay(owner, base, e["id"], 900)
    assert _detail(owner, base, e["id"])["sessions_remaining"] == 3

    use = client.post(f"{base}/membership-enrolments/{e['id']}/sessions", json={"idempotency_key": "walkin-0001"},
                      headers=owner)
    assert use.status_code == 200 and use.json()["data"]["sessions_remaining"] == 2
    same = client.post(f"{base}/membership-enrolments/{e['id']}/sessions", json={"idempotency_key": "walkin-0001"},
                       headers=owner)
    assert same.json()["data"]["sessions_remaining"] == 2, "the same key uses one session"

    def book(hours: int) -> Any:
        return client.post(f"{base}/bookings", json={
            "location_id": loc, "offering_id": yoga, "customer_contact_id": contact,
            "reservation_mode": "class_session", "title": "Yoga",
            "starts_at": (datetime.now(UTC) + timedelta(hours=hours)).isoformat(),
            "ends_at": (datetime.now(UTC) + timedelta(hours=hours + 1)).isoformat(), "capacity": 10,
            "payment_method": "cod", "idempotency_key": str(uuid.uuid4())}, headers=owner)

    b1 = book(26)
    assert b1.status_code == 200, b1.text
    bid1 = b1.json()["data"]["id"]
    drain_events(bid)
    drain_events(bid)
    assert _detail(owner, base, e["id"])["sessions_remaining"] == 1, "counted when booked, by this plan's rule"
    drain_events(bid)
    assert sql("select count(*) from memberships_session_uses where idempotency_key = :k",
               k=f"booking:{bid1}") == [(1,)], "a replayed booking event uses nothing more"
    cancel = client.post(f"{base}/bookings/{bid1}/cancel", json={"reason": "Unwell"}, headers=owner)
    assert cancel.status_code == 200, cancel.text
    drain_events(bid)
    drain_events(bid)
    assert _detail(owner, base, e["id"])["sessions_remaining"] == 2, "a cancelled class gives the session back"
    assert book(30).status_code == 200
    drain_events(bid)
    drain_events(bid)
    client.post(f"{base}/membership-enrolments/{e['id']}/sessions", json={"idempotency_key": "walkin-0002"},
                headers=owner)
    d = _detail(owner, base, e["id"])
    assert (d["sessions_remaining"], d["status"], d["reason"]) == (0, "expired", "All sessions used")
    refused = book(50)
    assert refused.status_code == 422 and "session pack with sessions left" in refused.text


# ---------------------------------------------------------------- subscriptions
def _tomorrow() -> date:
    return (datetime.now(IST) + timedelta(days=1)).date()


def _milk(monkeypatch: Any, timing: str = "prepaid") -> tuple[dict[str, str], str, str, dict[str, Any], str]:
    owner, bid, base = _gym(monkeypatch, "orders", "fulfilment", "inventory", "ledger")
    milk = client.post(f"{base}/products", json={"title": "Milk 500 ml", "offering_type": "product",
                                                 "status": "active", "price_amount": 30},
                       headers=owner).json()["data"]
    client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": True, "delivery_enabled": True},
                 headers=owner)
    kw: dict[str, Any] = {"plan_kind": "recurring_delivery", "billing_timing": timing, "price_amount": 900,
                          "delivery": {"offering_id": milk["id"], "quantity": 1, "slot": "Morning",
                                       "window": "06:00-08:00", "cutoff": "21:00", "mode": "pickup"}}
    if timing == "postpaid":
        kw.update(price_amount=0, duration_days=None)
    plan = _plan(owner, base, **kw)
    return owner, bid, base, plan, milk["id"]


async def _generate(session: AsyncSession, bid: str, day: date) -> dict[str, Any]:
    from platform_core.memberships.subscriptions import SubscriptionService
    from platform_core.models import Business

    await session.execute(text("select set_config('app.current_business_id', :b, true)"), {"b": bid})
    b = await session.get(Business, uuid.UUID(bid))
    assert b is not None
    made: dict[str, Any] = await SubscriptionService.generate_day(session, uuid.UUID(bid), day,
                                                  actor_id=b.primary_owner_identity_id,
                                                  correlation_id=str(uuid.uuid4()))
    return made


@DB
def test_milk_tomorrow_skip_one_day_change_and_pause_become_real_orders_once(monkeypatch: Any) -> None:
    owner, bid, base, plan, milk = _milk(monkeypatch)
    contact = _customer(owner, base, "Lakshmi")
    e = _enrol(owner, base, plan["id"], contact,
               starts_at=datetime.combine(date.today(), time(0, 0), IST).isoformat())
    _pay(owner, base, e["id"], 900)
    # From the day after tomorrow: tomorrow is already decided after its 21:00
    # cutoff, so a run in the evening would be refused for the wrong reason.
    t1 = _tomorrow() + timedelta(days=1)
    t2, t3 = t1 + timedelta(days=1), t1 + timedelta(days=2)
    day = client.get(f"{base}/subscriptions/day", params={"on_date": t1.isoformat()}, headers=owner).json()["data"]
    assert day["slots"]["Morning"]["deliver"] == 1 and day["slots"]["Morning"]["quantity"] == 1

    skip = client.post(f"{base}/membership-enrolments/{e['id']}/delivery-day",
                       json={"on_date": t1.isoformat(), "kind": "skip"}, headers=owner)
    assert skip.status_code == 200, skip.text
    assert skip.json()["data"]["slots"]["Morning"] == {"deliver": 0, "quantity": 0.0, "skipped": 1, "paused": 0,
                                                       "not_covered": 0}
    more = client.post(f"{base}/membership-enrolments/{e['id']}/delivery-day",
                       json={"on_date": t2.isoformat(), "kind": "quantity", "quantity": 2}, headers=owner)
    assert more.json()["data"]["slots"]["Morning"]["quantity"] == 2

    gen1 = svc(lambda s: _generate(s, bid, t1))
    assert (gen1["orders"], gen1["not_delivered"]) == (0, 1), "the skipped day makes no order"
    gen2 = svc(lambda s: _generate(s, bid, t2))
    assert gen2["orders"] == 1 and gen2["items"] == {"Milk 500 ml": 2.0}
    assert svc(lambda s: _generate(s, bid, t2))["orders"] == 0, "finalising again creates nothing new"
    order = sql("select o.channel, o.status, o.total_amount, l.quantity from orders_orders o join "
                "orders_order_line_items l on l.order_id = o.id where o.business_id = :b", b=bid)
    assert order == [("subscription", "accepted", D("0.00"), 2)], "a real order; the goods, not the money"
    gen3 = svc(lambda s: _generate(s, bid, t3))
    assert gen3["items"] == {"Milk 500 ml": 1.0}, "the one-day change does not carry over"

    # After the cutoff the day is decided: the policy is said, nothing changes silently.
    late = client.post(f"{base}/membership-enrolments/{e['id']}/delivery-day",
                       json={"on_date": t2.isoformat(), "kind": "skip"}, headers=owner)
    assert late.status_code == 409 and "Call or message the business" in late.text

    p = client.post(f"{base}/membership-enrolments/{e['id']}/freezes",
                    json={"starts_on": (t3 + timedelta(days=1)).isoformat(), "days": 3}, headers=owner)
    assert p.status_code == 200, p.text
    assert p.json()["data"]["freezes"][0]["kind"] == "pause" and p.json()["data"]["freezes"][0]["extends_cover"] is False
    paused = client.get(f"{base}/subscriptions/day", params={"on_date": (t3 + timedelta(days=2)).isoformat()},
                        headers=owner).json()["data"]
    assert paused["slots"]["Morning"]["paused"] == 1
    back = client.get(f"{base}/subscriptions/day", params={"on_date": (t3 + timedelta(days=4)).isoformat()},
                      headers=owner).json()["data"]
    assert back["slots"]["Morning"]["deliver"] == 1, "resumes by itself after the pause"


@DB
def test_a_tiffin_day_reaches_the_kitchen_as_one_ticket_per_delivery(monkeypatch: Any) -> None:
    # Subscription orders are ordinary accepted orders: Kitchen acts on them like any other.
    owner, bid, base = _gym(monkeypatch, "orders", "fulfilment", "inventory", "kitchen")
    # A prepared dish (menu item) goes to the kitchen; packaged goods like milk do not.
    thali = client.post(f"{base}/products", json={"title": "Veg thali", "offering_type": "menu_item",
                                                  "status": "active", "price_amount": 120}, headers=owner).json()["data"]
    client.patch(f"/v1/b/{bid}/fulfilment/settings", json={"pickup_enabled": True, "delivery_enabled": True},
                 headers=owner)
    plan = _plan(owner, base, plan_kind="recurring_delivery", billing_timing="prepaid", price_amount=3000,
                 delivery={"offering_id": thali["id"], "quantity": 2, "slot": "Lunch", "window": "12:00-13:00",
                           "cutoff": "21:00", "mode": "pickup"})
    e = _enrol(owner, base, plan["id"], _customer(owner, base, "Suresh"),
               starts_at=datetime.combine(date.today(), time(0, 0), IST).isoformat())
    _pay(owner, base, e["id"], 3000)
    made = svc(lambda s: _generate(s, bid, _tomorrow()))
    assert made["orders"] == 1
    drain_events(bid)
    drain_events(bid)
    tickets = sql("select t.order_id::text from kitchen_tickets t join orders_orders o on o.id = t.order_id "
                  "where t.business_id = :b and o.channel = 'subscription'", b=bid)
    assert len(tickets) == 1, "one kitchen ticket for the day's delivery"
    items = sql("select sum(i.quantity)::int from kitchen_ticket_lines i where i.ticket_id in "
                "(select id from kitchen_tickets where business_id = :b)", b=bid)
    assert items == [(2,)], "the ticket carries the subscribed quantity"
    assert svc(lambda s: _generate(s, bid, _tomorrow()))["orders"] == 0
    drain_events(bid)
    assert int(sql("select count(*) from kitchen_tickets where business_id = :b", b=bid)[0][0]) == 1


@DB
def test_postpaid_deliveries_are_billed_on_the_khata_once_and_skips_cost_nothing(monkeypatch: Any) -> None:
    owner, bid, base, plan, milk = _milk(monkeypatch, "postpaid")
    contact = _customer(owner, base, "Rafiq")
    e = _enrol(owner, base, plan["id"], contact,
               starts_at=datetime.combine(date.today(), time(0, 0), IST).isoformat())
    assert e["status"] == "active" and e["payment_attempt_id"] is None
    t1 = _tomorrow()
    client.post(f"{base}/membership-enrolments/{e['id']}/delivery-day",
                json={"on_date": (t1 + timedelta(days=1)).isoformat(), "kind": "skip"}, headers=owner)
    for k in range(3):
        on = t1 + timedelta(days=k)

        async def gen(s: AsyncSession, on: date = on) -> dict[str, Any]:
            return await _generate(s, bid, on)

        svc(gen)
    month = t1 + timedelta(days=2)
    bill = client.post(f"{base}/subscriptions/bill", json={"month": month.isoformat()}, headers=owner)
    assert bill.status_code == 200, bill.text
    months = {t1.strftime("%Y-%m"), (t1 + timedelta(days=2)).strftime("%Y-%m")}
    billed = bill.json()["data"]["billed"]
    for m in months - {month.strftime("%Y-%m")}:
        billed += client.post(f"{base}/subscriptions/bill", json={"month": f"{m}-01"},
                              headers=owner).json()["data"]["billed"]
    assert sum(b["deliveries"] for b in billed) == 2 and sum(b["amount"] for b in billed) == 60.0
    again = client.post(f"{base}/subscriptions/bill", json={"month": month.isoformat()}, headers=owner)
    assert again.json()["data"]["billed"] == [], "billing the month again bills nothing"
    balance = sql("select balance from ledger_accounts where business_id = :b and customer_contact_id = :c",
                  b=bid, c=contact)
    assert balance == [(D("60.00"),)]
    link = client.post(f"{base}/collect/requests", json={"source_type": "membership", "source_id": e["id"],
                                                          "amount": 10, "purpose": "full"}, headers=owner)
    assert link.status_code == 422 and "khata" in link.text


# ---------------------------------------------------------------- coaching fees, AMC, club dues
@DB
def test_fee_plan_instalments_paid_outstanding_next_due_and_guardian_payer(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch, "academics")
    plan = _plan(owner, base, plan_kind="fee_plan", price_amount=0, duration_days=120, instalment_template=[
        {"label": "Admission", "amount": 10000, "due_after_days": 0},
        {"label": "Second term", "amount": 10000, "due_after_days": 30},
        {"label": "Third term", "amount": 10000, "due_after_days": 60}])
    student, guardian = _customer(owner, base, "Asha"), _customer(owner, base, "Meera (mother)")
    # The fee plan follows the student's academic enrolment — Academics' own record.
    course = client.post(f"/v1/b/{bid}/academics/courses", json={"title": "Class 10 maths"}, headers=owner)
    assert course.status_code == 200, course.text
    batch = client.post(f"/v1/b/{bid}/academics/batches", json={
        "course_id": course.json()["data"]["id"], "name": "Evening 2026"}, headers=owner)
    assert batch.status_code == 200, batch.text
    enrolled = client.post(f"/v1/b/{bid}/academics/batches/{batch.json()['data']['id']}/enrolments", json={
        "student_contact_id": student, "guardian_contact_id": guardian, "is_minor": True}, headers=owner)
    assert enrolled.status_code == 200, enrolled.text
    academic = enrolled.json()["data"]["id"]
    body = {"plan_id": plan["id"], "payment_method": "pay_at_business", "source_ref_type": "academic_enrolment"}
    made_up = client.post(f"{base}/membership-enrolments", json={
        **body, "customer_contact_id": student, "source_ref_id": str(uuid.uuid4())}, headers=owner)
    assert made_up.status_code == 404, "a reference to no academic enrolment is refused"
    not_the_student = client.post(f"{base}/membership-enrolments", json={
        **body, "customer_contact_id": guardian, "source_ref_id": academic}, headers=owner)
    assert not_the_student.status_code == 422, "the fee plan is for the enrolled student; the guardian pays"
    e = _enrol(owner, base, plan["id"], student, payer_contact_id=guardian,
               source_ref_type="academic_enrolment", source_ref_id=academic)
    assert _detail(owner, base, e["id"])["source_ref"] == {"type": "academic_enrolment", "id": academic}
    assert e["status"] == "pending"
    due = client.get(f"{base}/collect/due", params={"source_type": "membership", "source_id": e["id"]},
                     headers=owner).json()["data"]
    assert (due["total"], due["balance"]) == (30000.0, 30000.0)
    assert sql("select customer_contact_id::text from payments_payment_attempts where source_id = :e",
               e=e["id"]) == [(guardian,)], "the guardian pays"
    _pay(owner, base, e["id"], 10000)
    d = _detail(owner, base, e["id"])
    assert (d["status"], d["paid"], d["outstanding"]) == ("active", 10000.0, 20000.0)
    assert [i["status"] for i in d["instalments"]] == ["paid", "due", "due"]
    assert sql("select status from payments_payment_attempts where source_id = :e and payment_method = "
               "'pay_at_business'", e=e["id"]) == [("cancelled",)], "the admission is paid: nothing left to collect"
    assert d["next_due_on"] == d["instalments"][1]["due_on"] and d["words"]["customer_title"] == "Fees & Enrolment"
    steps = sql("select count(*) from automation_steps where ladder_key = 'membership.instalment' "
                "and status = 'pending' and business_id = :b", b=bid)
    assert steps[0][0] >= 4, "reminders are booked for the two open instalments"
    _pay(owner, base, e["id"], 10000)
    assert [i["status"] for i in _detail(owner, base, e["id"])["instalments"]] == ["paid", "paid", "due"]
    cancelled = sql("select count(*) from automation_steps a join memberships_instalments i on i.id = a.entity_id "
                    "where i.enrolment_id = :e and i.seq = 2 and a.status = 'pending'", e=e["id"])
    assert cancelled == [(0,)], "a paid instalment is no longer reminded"


@DB
def test_amc_visits_are_asked_of_jobs_once_and_dues_decide_good_standing(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch)
    amc = _plan(owner, base, plan_kind="service_contract", price_amount=4000, duration_days=365, visits_included=2)
    kannan, someone_else = _customer(owner, base, "Kannan"), _customer(owner, base, "Latha")

    def asset(customer: str, label: str) -> str:
        made = client.post(f"{base}/customer-assets", json={
            "customer_id": customer, "asset_kind": "ac_unit", "label": label,
            "idempotency_key": f"asset-{uuid.uuid4().hex[:12]}"}, headers=owner)
        assert made.status_code == 200, made.text
        return str(made.json()["data"]["id"])

    hall_ac, latha_ac = asset(kannan, "Hall AC"), asset(someone_else, "Bedroom AC")
    body = {"plan_id": amc["id"], "customer_contact_id": kannan, "payment_method": "pay_at_business",
            "source_ref_type": "customer_asset"}
    assert client.post(f"{base}/membership-enrolments", json={**body, "source_ref_id": latha_ac},
                       headers=owner).status_code == 422, "an AMC covers the customer's own asset"
    assert client.post(f"{base}/membership-enrolments", json={**body, "source_ref_id": str(uuid.uuid4())},
                       headers=owner).status_code == 404
    gym = _plan(owner, base, price_amount=1000, duration_days=30)
    assert client.post(f"{base}/membership-enrolments", json={**body, "plan_id": gym["id"], "source_ref_id": hall_ac},
                       headers=owner).status_code == 422, "only a service contract covers an asset"
    e = _enrol(owner, base, amc["id"], kannan, source_ref_type="customer_asset", source_ref_id=hall_ac)
    _pay(owner, base, e["id"], 4000)
    d = _detail(owner, base, e["id"])
    assert len(d["visits"]) == 2 and d["words"]["customer_title"] == "My Service Plan"
    first_due = date.fromisoformat(d["visits"][0]["due_on"])

    async def sweep(session: AsyncSession, moment: datetime) -> dict[str, Any]:
        from platform_core.memberships.sweep import sweep_business

        await session.execute(text("select set_config('app.current_business_id', :b, true)"), {"b": bid})
        swept: dict[str, Any] = await sweep_business(session, uuid.UUID(bid), now=moment)
        return swept

    when = datetime.combine(first_due - timedelta(days=3), time(10, 0), IST)
    assert svc(lambda s: sweep(s, when))["visits_due"] == 1
    assert svc(lambda s: sweep(s, when + timedelta(hours=1)))["visits_due"] == 0, "asked once"
    events = sql("select payload->>'asset_ref' from platform_outbox_events where business_id = :b "
                 "and event_type = 'membership.service_visit_due'", b=bid)
    assert events == [(hall_ac,)], "the visit names the covered asset"

    club = _plan(owner, base, plan_kind="member_dues", price_amount=2400, duration_days=365)
    m = _enrol(owner, base, club["id"], _customer(owner, base, "Raman"))
    assert _detail(owner, base, m["id"])["good_standing"] is None
    _pay(owner, base, m["id"], 2400)
    dd = _detail(owner, base, m["id"])
    assert dd["good_standing"] is True and dd["words"]["owner_home"] == "Members & dues"


# ---------------------------------------------------------------- the renewal ladder, for real
def _ten_am_after(moment: datetime) -> datetime:
    local = moment.astimezone(IST)
    at = datetime.combine(local.date(), time(10, 0), IST)
    return at if at >= local else at + timedelta(days=1)


def _messages(bid: str, key: str) -> list[Any]:
    return list(sql("select m.status, m.body, m.idempotency_key from messaging_messages m where m.business_id = :b "
                    "and m.template_key = :k order by m.created_at", b=bid, k=key))


@DB
def test_renewal_ladder_sends_once_waits_for_quiet_hours_and_stops_on_payment(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch, "messaging")
    assert client.post(f"{base}/messaging/channel/sandbox", json={"display_phone": "+919840011111",
                                                                  "display_name": "Iron Gym"},
                       headers=owner).status_code == 200
    plan = _plan(owner, base, grace_days=3)
    start = datetime.now(UTC) - timedelta(days=23)
    e = _enrol(owner, base, plan["id"], _customer(owner, base, "Divya", "+919840022222"), starts_at=start.isoformat())
    _pay(owner, base, e["id"], 1500)
    end = datetime.fromisoformat(_detail(owner, base, e["id"])["valid_until"])

    # Due in quiet hours → waits for 8 am, sends nothing yet.
    t7 = end - timedelta(days=7)
    night = datetime.combine((t7 + timedelta(days=1)).astimezone(IST).date(), time(23, 0), IST)
    run_automation(bid, now=night)
    assert _messages(bid, "renewal_due") == []
    waiting = sql("select outcome from automation_steps where entity_id = :e and step_key = 't_minus_7'", e=e["id"])
    assert waiting[0][0] == "Waiting for 8 am (quiet hours)"

    morning = datetime.combine(night.astimezone(IST).date() + timedelta(days=1), time(8, 30), IST)
    run_automation(bid, now=morning)
    run_automation(bid, now=morning + timedelta(minutes=30))
    sent = _messages(bid, "renewal_due")
    assert len(sent) == 1 and sent[0][0] == "sent" and "/pay/" in sent[0][1], "T−7 sent once with a payment link"

    # The member pays the renewal (the link's charge): later reminders stop.
    due = client.get(f"{base}/collect/due", params={"source_type": "membership", "source_id": e["id"]},
                     headers=owner).json()["data"]
    assert due["balance"] == 1500.0
    _pay(owner, base, e["id"], 1500)
    left = sql("select step_key, status from automation_steps where entity_id = :e and period_key = :p "
               "order by due_at", e=e["id"], p=end.strftime("%Y%m%d%H%M"))
    assert dict(left)["t_minus_2"] == "cancelled" and dict(left)["t0"] == "cancelled"
    run_automation(bid, now=_ten_am_after(end))
    assert len(_messages(bid, "renewal_due")) == 1, "no reminder after renewal"
    drain_events(bid)
    drain_events(bid)
    receipts = _messages(bid, "membership_renewed")
    assert [m[0] for m in receipts] == ["sent", "sent"], "one receipt per paid period"
    drain_events(bid)
    assert len(_messages(bid, "membership_renewed")) == 2, "a replayed event sends no second receipt"


@DB
def test_unrenewed_goes_to_grace_then_expires_and_winback_needs_marketing_consent(monkeypatch: Any) -> None:
    owner, bid, base = _gym(monkeypatch, "messaging")
    client.post(f"{base}/messaging/channel/sandbox", json={"display_phone": "+919840011112"}, headers=owner)
    plan = _plan(owner, base, grace_days=3)
    e = _enrol(owner, base, plan["id"], _customer(owner, base, "Suresh", "+919840033333"),
               starts_at=(datetime.now(UTC) - timedelta(days=29)).isoformat())
    _pay(owner, base, e["id"], 1500)
    end = datetime.fromisoformat(_detail(owner, base, e["id"])["valid_until"])
    # The page judges "now"; the automation ran at simulated later moments, so
    # read what it stored (status and its history).
    def stored() -> str:
        return str(sql("select status from memberships_enrolments where id = :e", e=e["id"])[0][0])

    run_automation(bid, now=_ten_am_after(end + timedelta(days=1)))
    assert stored() == "grace"
    assert [m[0] for m in _messages(bid, "membership_grace")] == ["sent"]
    run_automation(bid, now=_ten_am_after(end + timedelta(days=3, hours=1)))
    d = _detail(owner, base, e["id"])
    assert stored() == "expired"
    assert [m[0] for m in _messages(bid, "membership_expired")] == ["sent"]
    assert all(p["payment_state"] != "unpaid" for p in d["periods"]), "the unoffered renewal lapsed; nothing owed"
    history = [h["to"] for h in d["history"]]
    assert "grace" in history and "expired" in history
    run_automation(bid, now=_ten_am_after(end + timedelta(days=15)))
    assert [m[0] for m in _messages(bid, "membership_winback")] == ["blocked"], "marketing needs an opt-in"


# ---------------------------------------------------------------- isolation
@pytest.mark.asyncio
@DB
async def test_membership_history_tables_are_tenant_isolated() -> None:
    async def enrolment(session: AsyncSession, business_id: uuid.UUID) -> uuid.UUID:
        contact = (await session.execute(text(
            "INSERT INTO customer_relationships_contacts (business_id, display_name) VALUES (:b, 'X') RETURNING id"),
            {"b": business_id})).scalar()
        plan = (await session.execute(text(
            "INSERT INTO memberships_plans (business_id, name, duration_days, status) VALUES (:b, 'P', 30, 'active') "
            "RETURNING id"), {"b": business_id})).scalar()
        return uuid.UUID(str((await session.execute(text(
            "INSERT INTO memberships_enrolments (business_id, plan_id, customer_contact_id, starts_at) "
            "VALUES (:b, :p, :c, now()) RETURNING id"), {"b": business_id, "p": plan, "c": contact})).scalar()))

    async def period(session: AsyncSession, business_id: uuid.UUID) -> None:
        e = await enrolment(session, business_id)
        await session.execute(text(
            "INSERT INTO memberships_periods (business_id, enrolment_id, seq, starts_at, base_ends_at, ends_at) "
            "VALUES (:b, :e, 1, now(), now() + interval '30 days', now() + interval '30 days')"),
            {"b": business_id, "e": e})

    async def freeze(session: AsyncSession, business_id: uuid.UUID) -> None:
        e = await enrolment(session, business_id)
        await session.execute(text(
            "INSERT INTO memberships_freezes (business_id, enrolment_id, starts_on, ends_on, days) "
            "VALUES (:b, :e, current_date, current_date + 9, 10)"), {"b": business_id, "e": e})

    async def override(session: AsyncSession, business_id: uuid.UUID) -> None:
        e = await enrolment(session, business_id)
        await session.execute(text(
            "INSERT INTO memberships_delivery_overrides (business_id, enrolment_id, on_date, kind) "
            "VALUES (:b, :e, current_date + 1, 'skip')"), {"b": business_id, "e": e})

    await assert_tenant_isolated("memberships_periods", period)
    await assert_tenant_isolated("memberships_freezes", freeze)
    await assert_tenant_isolated("memberships_delivery_overrides", override)


@pytest.mark.asyncio
@DB
async def test_a_period_is_history_its_start_and_price_cannot_be_rewritten() -> None:
    from sqlalchemy.exc import DBAPIError

    engine = create_async_engine(db_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            b = (await session.execute(text("select id from businesses limit 1"))).scalar()
            contact = (await session.execute(text(
                "INSERT INTO customer_relationships_contacts (business_id, display_name) VALUES (:b, 'H') "
                "RETURNING id"), {"b": b})).scalar()
            plan = (await session.execute(text(
                "INSERT INTO memberships_plans (business_id, name, duration_days, status) "
                "VALUES (:b, 'H', 30, 'active') RETURNING id"), {"b": b})).scalar()
            e = (await session.execute(text(
                "INSERT INTO memberships_enrolments (business_id, plan_id, customer_contact_id, starts_at) "
                "VALUES (:b, :p, :c, now()) RETURNING id"), {"b": b, "p": plan, "c": contact})).scalar()
            pid = (await session.execute(text(
                "INSERT INTO memberships_periods (business_id, enrolment_id, seq, starts_at, base_ends_at, ends_at, "
                "amount) VALUES (:b, :e, 1, now(), now() + interval '30 days', now() + interval '30 days', 100) "
                "RETURNING id"), {"b": b, "e": e})).scalar()
            await session.execute(text("UPDATE memberships_periods SET ends_at = ends_at + interval '10 days' "
                                       "WHERE id = :p"), {"p": pid})
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(text("UPDATE memberships_periods SET amount = 1 WHERE id = :p"), {"p": pid})
            await session.rollback()
    finally:
        await engine.dispose()
