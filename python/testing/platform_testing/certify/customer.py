"""Customers on the published site — order, book, join, enquire — up to payment.

    uv run python -m platform_testing.certify.customer <run_dir> <site_key>

A guest (no sign-in) does what the site's own buttons do, through the same
public endpoints: the range's Add and the checkout, the booking page, a plan's
Join, the enquiry form. The owner's Workspace then has to show what arrived.
No payment gateway is connected on a local stack (no merchant account), so
every flow ends at payment: an order is placed with the business's own way of
being paid (pay at pickup, cash on delivery, UPI to the business), a booking
is requested, a plan asks to be joined. Whether the site OFFERS each action is
checked against the tools the owner kept: a kept, set-up tool with no action
on the site is a failure, and so is an action the business cannot fulfil.

Reads journey.json and setup.json, writes customer.json beside them.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from platform_testing.certify.journey import API
from platform_testing.certify.setup import owner_token

GUEST = {"name": "Priya Raman", "email": "priya.certify@locah.test", "phone": "+919840011223"}
ADDRESS = {"line1": "12, 4th Cross Street", "area": "Besant Nagar", "city": "Chennai", "postal_code": "600090",
           "state": "Tamil Nadu"}


@dataclass
class Flow:
    flow: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True

    def step(self, name: str, ok: bool, detail: Any = "") -> bool:
        self.steps.append({"step": name, "ok": bool(ok), "detail": str(detail)[:400]})
        if not ok:
            self.ok = False
        return bool(ok)


@dataclass
class Customer:
    site_key: str
    slug: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    flows: list[Flow] = field(default_factory=list)

    def save(self, folder: Path) -> None:
        data = {"site_key": self.site_key, "slug": self.slug, "capabilities": self.capabilities,
                "ok": all(f.ok for f in self.flows),
                "flows": [{"flow": f.flow, "ok": f.ok, "steps": f.steps} for f in self.flows]}
        (folder / "customer.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _data(body: Any) -> Any:
    return body.get("data", body) if isinstance(body, dict) else body


def _next_weekday(days_ahead: int = 2) -> date:
    day = datetime.now(timezone.utc).date() + timedelta(days=days_ahead)
    while day.weekday() > 5:
        day += timedelta(days=1)
    return day


async def order_flow(web: httpx.AsyncClient, owner: httpx.AsyncClient, slug: str, business_id: str) -> Flow:
    flow = Flow("order")
    res = await web.get(f"/v1/public/websites/{slug}/checkout/options")
    options = _data(res.json()) if res.status_code < 400 else {}
    if not flow.step("checkout options", res.status_code < 400, options):
        return flow
    res = await web.get(f"/v1/public/websites/{slug}/offerings")
    offerings = (_data(res.json()) or {}).get("offerings") or [] if res.status_code < 400 else []
    priced = [o for o in offerings if o.get("price_amount")]
    if not flow.step("live priced items on the site", len(priced) >= 1, f"{len(priced)} of {len(offerings)}"):
        return flow
    items = [{"offering_id": o["id"], "quantity": 1 + i} for i, o in enumerate(priced[:2])]
    modes = [str(m.get("mode") if isinstance(m, dict) else m) for m in
             (options.get("fulfilment_modes") or options.get("modes") or [])]
    mode = "pickup" if "pickup" in modes or not modes else modes[0]
    delivering = "delivery" in modes
    res = await web.post(f"/v1/public/websites/{slug}/checkout/price", json={"items": items, "fulfilment_mode": mode})
    priced_body = _data(res.json()) if res.status_code < 400 else res.text
    flow.step("basket priced by the server", res.status_code < 400, priced_body)
    if delivering:
        res = await web.post(f"/v1/public/websites/{slug}/checkout/quote", json={"delivery_address": ADDRESS})
        flow.step("delivery quoted for an address", res.status_code < 400, res.text[:300])
    methods = [str(m.get("id") or m.get("method") if isinstance(m, dict) else m)
               for m in (options.get("payment_methods") or options.get("payments") or [])]
    # The business's own ways of being paid; a gateway would need a merchant account.
    method = next((m for m in methods if m in {"pay_at_pickup", "cod", "cash", "upi"}), methods[0] if methods else "cod")
    body = {"items": items, "fulfilment_mode": mode, "payment_method": method, "guest": GUEST,
            "idempotency_key": str(uuid.uuid4())}
    res = await web.post(f"/v1/public/websites/{slug}/checkout", json=body)
    placed = _data(res.json()) if res.headers.get("content-type", "").startswith("application/json") else res.text
    if not flow.step(f"order placed ({mode}, pays by {method})", res.status_code < 400, placed):
        return flow
    order = placed.get("order", placed) if isinstance(placed, dict) else {}
    order_id = str(order.get("id") or order.get("order_id") or "")
    flow.step("order number and amount given back", bool(order_id) and bool(order.get("order_number")) and bool(
        order.get("total_amount") or order.get("total") or order.get("grand_total") or order.get("subtotal")),
        {k: order.get(k) for k in ("order_number", "status", "payment_method", "payment_status", "subtotal")})
    flow.step("payment waits for the business's own method (no gateway)",
              str(order.get("payment_status") or "") in {"pending_offline", "pending", "unpaid", "awaiting"},
              order.get("payment_status"))
    tracking = placed.get("tracking") if isinstance(placed, dict) else None
    token = str((tracking or {}).get("token") or "")
    if order_id:
        res = await web.get(f"/v1/public/orders/{order_id}/tracking", params={"token": token})
        flow.step("customer can track it with the link they were given", res.status_code < 400, res.text[:300])
        res = await owner.get(f"/v1/platform/businesses/{business_id}/orders?limit=20")
        rows = _data(res.json()) if res.status_code < 400 else []
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        flow.step("the owner sees it in Orders", any(str(r.get("id")) == order_id for r in rows or []),
                  f"{len(rows or [])} orders")
    return flow


async def book_flow(web: httpx.AsyncClient, owner: httpx.AsyncClient, slug: str, business_id: str) -> Flow:
    flow = Flow("book")
    res = await web.get(f"/v1/public/websites/{slug}/booking/options")
    options = _data(res.json()) if res.status_code < 400 else {}
    if not flow.step("booking options", res.status_code < 400, options):
        return flow
    locations = options.get("locations") or []
    location_id = str((locations[0] if locations else {}).get("id") or options.get("location_id") or "")
    offerings = options.get("offerings") or options.get("services") or []
    providers = options.get("providers") or []
    modes = [str(m) for m in options.get("modes") or []]
    table = options.get("table") if isinstance(options.get("table"), dict) else None
    offering = offerings[0] if offerings else {}
    mode = "table" if table and not offerings else str(
        offering.get("mode") or offering.get("reservation_mode") or (modes[0] if modes else "appointment"))
    # Like the Book page: a customer may pick one of the people who give this
    # service at this place, and then sees only that person's free times.
    provider_id = next((str(p.get("id")) for p in providers
                        if (not location_id or location_id in (p.get("location_ids") or [location_id]))
                        and (not offering.get("id") or offering["id"] in (p.get("offering_ids") or [offering["id"]]))),
                       "")
    if not flow.step("something bookable", bool(location_id) and (bool(offerings) or bool(modes) or bool(table)),
                     f"{len(offerings)} offerings, modes {modes}, tables {(table or {}).get('tables')}"):
        return flow
    day = _next_weekday()
    if mode in {"rental", "stay", "accommodation"}:
        res = await web.post(f"/v1/public/websites/{slug}/booking/range", json={
            "location_id": location_id, "offering_id": offering.get("id"), "mode": mode,
            "check_in": day.isoformat(), "check_out": (day + timedelta(days=1)).isoformat()})
        ranged = _data(res.json()) if res.status_code < 400 else {}
        flow.step("dates are open", res.status_code < 400, ranged)
        starts, ends = f"{day.isoformat()}T12:00:00+05:30", f"{(day + timedelta(days=1)).isoformat()}T11:00:00+05:30"
    else:
        body = {"location_id": location_id, "mode": mode, "date": day.isoformat(),
                "party_size": 2 if mode in {"table", "reservation"} else 1}
        if offering.get("id"):
            body["offering_id"] = offering["id"]
        if provider_id:
            body["provider_id"] = provider_id
        # A customer looks at the next days until one is open (a salon is shut
        # on Mondays; a restaurant serves dinner only some nights).
        open_slots: list[dict[str, Any]] = []
        tried: list[str] = []
        hours_known = True
        for ahead in range(8):
            date = (day + timedelta(days=ahead)).isoformat()
            body["date"] = date
            res = await web.post(f"/v1/public/websites/{slug}/booking/slots", json=body)
            found = _data(res.json()) if res.status_code < 400 else {}
            hours_known = not (isinstance(found, dict) and found.get("hours_known") is False)
            slots = found.get("slots", found) if isinstance(found, dict) else found
            open_slots = [s for s in slots or [] if isinstance(s, dict) and not s.get("full")
                          and s.get("available", True)]
            tried.append(date)
            if open_slots or not hours_known:
                break
        # A business that never gave its hours shows no slots: the customer
        # asks for a time instead (the Book page's "Pick a time"). It books,
        # but a booking business without hours is a defect of its own.
        flow.step("hours known (slots, not a time to ask for)", hours_known,
                  "opening hours given" if hours_known else "the business gave no opening hours")
        if not hours_known:
            starts, ends = f"{tried[-1]}T11:00:00+05:30", f"{tried[-1]}T11:30:00+05:30"
        else:
            if not flow.step("open slots in the next week", bool(open_slots),
                             f"{len(open_slots)} slots on {tried[-1]} (tried {', '.join(tried)})"):
                return flow
            slot = open_slots[len(open_slots) // 2]
            starts = str(slot.get("starts_at") or slot.get("start"))
            ends = str(slot.get("ends_at") or slot.get("end"))
    booking = {"location_id": location_id, "reservation_mode": mode, "starts_at": starts, "ends_at": ends,
               "party_size": 2 if mode in {"table", "reservation"} else 1, "guest": GUEST}
    if offering.get("id"):
        booking["offering_id"] = offering["id"]
    else:
        booking["title"] = "Reserve a table" if mode == "table" else mode.replace("_", " ").capitalize()
    if provider_id:
        booking["provider_id"] = provider_id
    res = await web.post(f"/v1/public/websites/{slug}/bookings", json=booking)
    made = _data(res.json()) if res.headers.get("content-type", "").startswith("application/json") else res.text
    if not flow.step(f"booking made ({mode})", res.status_code < 400, made):
        return flow
    made = made.get("booking", made) if isinstance(made, dict) else {}
    booking_id = str(made.get("id") or "")
    if booking_id:
        # The link the customer is given carries the booking's management token.
        res = await web.get(f"/v1/public/bookings/{booking_id}",
                            params={"token": str(made.get("management_token") or "")})
        flow.step("customer can see the booking with the link they were given", res.status_code < 400,
                  res.text[:300])
        res = await owner.get(f"/v1/platform/businesses/{business_id}/bookings?limit=20")
        rows = _data(res.json()) if res.status_code < 400 else []
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        flow.step("the owner sees it in Bookings", any(str(r.get("id")) == booking_id for r in rows or []),
                  f"{len(rows or [])} bookings")
    return flow


async def enquiry_flow(web: httpx.AsyncClient, owner: httpx.AsyncClient, slug: str, business_id: str,
                       *, purpose: str, plan_id: str = "", offering_id: str = "") -> Flow:
    flow = Flow({"membership": "join", "enquiry": "enquire"}.get(purpose, purpose))
    body: dict[str, Any] = {"name": GUEST["name"], "phone": GUEST["phone"], "email": GUEST["email"],
                            "purpose": purpose,
                            "message": "Could you tell me more? I would like to start next week."}
    if plan_id:
        body["plan_id"] = plan_id
    if offering_id:
        body["offering_id"] = offering_id
    res = await web.post(f"/v1/public/websites/{slug}/enquiries", json=body)
    sent = _data(res.json()) if res.headers.get("content-type", "").startswith("application/json") else res.text
    flow.step(f"enquiry sent ({purpose})", res.status_code < 400, sent)
    return flow


async def join_by_channel_flow(web: httpx.AsyncClient, slug: str, site: dict[str, Any]) -> Flow:
    """A plan business that takes no online enquiries (no Leads): each live
    plan says "Ask to join" on the business's own WhatsApp or phone — the
    site must have the plans and a channel to send the customer to."""
    flow = Flow("join")
    res = await web.get(f"/v1/public/websites/{slug}/plans")
    plans = (_data(res.json()) or {}).get("plans") or [] if res.status_code < 400 else []
    if not flow.step("live plans listed", bool(plans), [p.get("title") for p in plans]):
        return flow
    contact = ((site.get("business") or {}).get("contact") or {})
    channel = "whatsapp" if contact.get("whatsapp") else "phone" if contact.get("phone") else ""
    flow.step("'Ask to join' reaches the business (enquiries off)", bool(channel), channel or "no WhatsApp or phone")
    return flow


async def run(run_dir: Path, site_key: str) -> Customer:
    folder = run_dir / "sites" / site_key
    journey = json.loads((folder / "journey.json").read_text(encoding="utf-8"))
    setup = json.loads((folder / "setup.json").read_text(encoding="utf-8")) if (folder / "setup.json").exists() else {}
    customer = Customer(site_key=site_key, slug=str(journey.get("slug") or ""))
    business_id = str(journey["business_id"])
    modules = set(journey.get("modules_enabled") or [])
    web = httpx.AsyncClient(base_url=API, timeout=90)
    owner = httpx.AsyncClient(base_url=API, timeout=90, headers={
        "Authorization": f"Bearer {owner_token(journey['owner_id'], journey['owner_email'])}"})
    try:
        res = await web.get(f"/v1/public/websites/{customer.slug}")
        site = _data(res.json()) if res.status_code < 400 else {}
        customer.capabilities = dict(site.get("capabilities") or {})
        caps = customer.capabilities
        offered = Flow("site offers what the owner set up")
        expect = {"order": {"orders", "fulfilment"} <= modules, "book": "bookings" in modules,
                  "join": "memberships" in modules, "enquire": "leads" in modules}
        for action, wanted in expect.items():
            if wanted:
                offered.step(f"{action} is offered", bool(caps.get(action)), caps.get(action))
        for action in ("order", "book", "join"):
            if caps.get(action) and not expect[action]:
                offered.step(f"{action} offered without its tool", False, caps.get(action))
        offered.step("the header's main button leads somewhere",
                     not caps.get("primary") or caps.get("primary") in {"call", "whatsapp"}
                     or bool(caps.get("primary_path")), caps.get("primary"))
        customer.flows.append(offered)
        if caps.get("order"):
            customer.flows.append(await order_flow(web, owner, customer.slug, business_id))
        if caps.get("book"):
            customer.flows.append(await book_flow(web, owner, customer.slug, business_id))
        if caps.get("join") and caps.get("enquire"):
            plan = next((p for p in setup.get("plans") or [] if p.get("live") and p.get("id")), None)
            customer.flows.append(await enquiry_flow(web, owner, customer.slug, business_id,
                                                     purpose="membership", plan_id=str((plan or {}).get("id") or "")))
        elif caps.get("join"):
            customer.flows.append(await join_by_channel_flow(web, customer.slug, site))
        if caps.get("enquire") or caps.get("request_quote"):
            purpose = "quote_request" if caps.get("request_quote") else "enquiry"
            customer.flows.append(await enquiry_flow(web, owner, customer.slug, business_id, purpose=purpose))
        if caps.get("donate"):
            customer.flows.append(await enquiry_flow(web, owner, customer.slug, business_id, purpose="donation"))
    except Exception as exc:  # noqa: BLE001 — a broken flow is a finding
        broken = Flow("customer run")
        broken.step("ran to the end", False, f"{type(exc).__name__}: {exc}")
        customer.flows.append(broken)
    finally:
        await web.aclose()
        await owner.aclose()
        customer.save(folder)
    return customer


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m platform_testing.certify.customer <run_dir> <site_key>")
    out = asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    for f in out.flows:
        print(("PASS " if f.ok else "FAIL ") + f.flow)
        for s in f.steps:
            print(("   ok  " if s["ok"] else "   NO  ") + s["step"] + ("" if s["ok"] else f"  — {s['detail'][:200]}"))
