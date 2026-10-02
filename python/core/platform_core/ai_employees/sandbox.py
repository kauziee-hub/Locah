"""AI Employee Sandbox — see how an AI employee would work, without it working.

First Launch keeps AI employees as a later layer (Doc 11 §6.4; Doc 08 §16:
Entitlement is not authority; Doc 09 §11.3). This sandbox lets an owner watch
one handle a customer on top of their *real* business — real offerings and
prices, real stock words, real locations and hours, the booking engine's real
free times, the real AI employee settings — while nothing leaves the sandbox:

* **Reads are real.** Each one goes through the owning module's public read
  path (the catalogue's public offerings, Inventory's public availability, the
  booking engine's day slots, the location record) and is shown in the trace.
* **Decisions are real.** Module readiness (`module_readiness.readiness`) and
  the AI runtime's own tier/allowlist decision (`AIRuntime.decide`) are asked,
  exactly as a live employee would be.
* **Actions are simulated.** An order, a booking or an enquiry is only ever a
  *proposal* that needs the owner's approval; approving it re-checks the live
  records and returns a sandbox reference. No row is written, no message is
  sent, no money moves. The trace says so on every step.
* **No model is called.** Understanding is the receptionist's deterministic
  ladder (intent words, the business's own item names, day/time words), so the
  sandbox costs nothing and cannot invent a price or a slot.

One reusable engine, two presentations: the WhatsApp manager (a chat) and the
receptionist (a call transcript). Not fourteen bots.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.ai_employees.receptionist import (
    BOOKABLE,
    OWNER_ONLY,
    STEERING,
    _price,
    address_text,
    deterministic_intent,
    hours_text,
    match_offering,
)
from platform_core.ai_employees.runtime import DEFAULTS, KIND_TOOLS, TOOLS, AIRuntime
from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.models import AIEmployee, Business, BusinessLocation, Offering

SCENARIOS: dict[str, dict[str, str]] = {
    "whatsapp_manager": {
        "label": "AI WhatsApp Manager",
        "channel": "WhatsApp chat (simulated)",
        "employee": "receptionist",
        "about": "Answers customers on WhatsApp from your records and proposes orders, bookings and enquiries.",
    },
    "receptionist": {
        "label": "AI Receptionist",
        "channel": "Phone call transcript (simulated — no voice, no call)",
        "employee": "receptionist",
        "about": "Takes a call, checks what you offer and when you are free, and proposes a booking.",
    },
}
SIMULATION_NOTICE = "Sandbox simulation — no external message was sent and nothing was saved."

CART_KINDS = ("product", "weighed_product", "menu_item", "package", "digital_product")
_QTY = re.compile(r"\b(\d{1,2})\s*(?:x\s*)?(?=[a-z])", re.I)
_WORD_QTY = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "oru": 1, "rendu": 2, "moonu": 3}
# Tanglish the way customers type on WhatsApp: "available ah?", "slot iruka?", "venum".
_TANGLISH = re.compile(r"\b(ah|aa|iruka\w*|iruk\w*|venum|vendum|kidaikkuma|kidaikum\w*|evvalavu|enna|"
                       r"pannunga|sollunga|naalaiku|naalai|inniku|indru|saayangalam|kaalai|madhiyam)\b", re.I)
_AVAILABLE = re.compile(r"\b(available|availab\w*|in stock|iruka\w*|kidaikkuma|kidaikum\w*|have|got|left)\b", re.I)
_ORDER_WORDS = re.compile(r"\b(order|buy|want|need|venum|vendum|send|deliver\w*|parcel|takeaway|pack)\b", re.I)
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WINDOWS = {
    "morning": (8, 12), "kaalai": (8, 12), "afternoon": (12, 16), "madhiyam": (12, 16),
    "evening": (16, 21), "saayangalam": (16, 21), "night": (19, 23),
}


def enabled() -> bool:
    """A feature flag, on unless switched off for a deployment."""
    return os.getenv("AI_SANDBOX_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _tanglish(said: str) -> bool:
    return bool(_TANGLISH.search(said))


def _quantity(said: str) -> int:
    m = _QTY.search(said)
    if m:
        return max(1, min(int(m.group(1)), 50))
    for word, n in _WORD_QTY.items():
        if re.search(rf"\b{word}\b", said, re.I):
            return n
    return 1


def _day_and_window(said: str, today: date) -> tuple[date | None, tuple[int, int] | None]:
    """"Saturday evening" / "naalaiku kaalai" / "tomorrow" — read by rule, nothing guessed."""
    s = said.lower()
    day: date | None = None
    if re.search(r"\b(today|inniku|indru|tonight)\b", s):
        day = today
    elif re.search(r"\b(tomorrow|naalaiku|naalai)\b", s):
        day = today + timedelta(days=1)
    else:
        for i, name in enumerate(_DAYS):
            if re.search(rf"\b{name[:3]}\w*\b", s):
                ahead = (i - today.weekday()) % 7 or 7
                day = today + timedelta(days=ahead)
                break
    window = next((w for word, w in _WINDOWS.items() if re.search(rf"\b{word}\b", s)), None)
    return day, window


class _Trace:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, kind: str, label: str, detail: str = "", **extra: Any) -> None:
        self.steps.append({"kind": kind, "label": label, "detail": detail, **extra})


async def _employee(session: AsyncSession, business_id: uuid.UUID, kind: str) -> AIEmployee:
    """The business's real employee settings when it has them; the platform
    defaults (switched off) otherwise. Read only — the roster is not created."""
    emp = (await session.execute(select(AIEmployee).where(
        AIEmployee.business_id == business_id, AIEmployee.kind == kind))).scalars().first()
    if emp is not None:
        return emp
    spec = DEFAULTS[kind]
    return AIEmployee(business_id=business_id, kind=kind, display_name=spec["display_name"],
                      autonomy=spec["autonomy"], tools=list(KIND_TOOLS[kind]), limits=dict(spec["limits"]),
                      enabled=False)


def _decision(emp: AIEmployee, tool: str, trace: _Trace) -> None:
    """What the live runtime would decide for this tool, under the owner's settings."""
    decision, why = AIRuntime.decide(emp, tool)
    if decision == "refused" and why == "This AI employee is switched off":
        # The sandbox shows what the employee *would* be allowed to do once on.
        decision, why = AIRuntime.decide(_switched_on(emp), tool)
        off = "it is switched off today, so in real use nothing would run"
        why = f"{why} — {off}" if why else off[:1].upper() + off[1:]
    words = {"run": "Would act within its limits", "approval": "Would need your approval",
             "refused": "Would not be allowed"}[decision]
    t = TOOLS.get(tool)
    trace.add("permission", f"AI settings: {t.label if t else tool}", f"{words}. {why}".strip(),
              tool=tool, tier=t.tier if t else None, decision=decision)


def _switched_on(emp: AIEmployee) -> AIEmployee:
    return AIEmployee(business_id=emp.business_id, kind=emp.kind, display_name=emp.display_name,
                      autonomy=emp.autonomy, tools=list(emp.tools or []), limits=dict(emp.limits or {}),
                      enabled=True)


async def _context(session: AsyncSession, business_id: uuid.UUID) -> dict[str, Any]:
    from platform_core.services.module_readiness import readiness

    business = await session.get(Business, business_id)
    if business is None:
        raise ResourceNotFound("Business")
    locations = list((await session.execute(select(BusinessLocation).where(
        BusinessLocation.business_id == business_id, BusinessLocation.status == "active",
        BusinessLocation.deleted_at.is_(None)).order_by(BusinessLocation.is_primary.desc(),
                                                        BusinessLocation.name))).scalars())
    states = await readiness(session, business_id,
                             modules=("offerings-catalog", "orders", "bookings", "inventory", "leads", "fulfilment"))
    offerings: list[Offering] = []
    if states["offerings-catalog"]["ready"]:
        offerings = list((await session.execute(select(Offering).where(
            Offering.business_id == business_id, Offering.deleted_at.is_(None), Offering.status == "active",
            Offering.visibility == "public").order_by(Offering.title).limit(200))).scalars())
    return {"business": business, "locations": locations, "states": states, "offerings": offerings}


def _pick_location(locations: list[BusinessLocation], said: str) -> BusinessLocation | None:
    low = said.lower()
    named = next((loc for loc in locations if loc.name and loc.name.lower() in low), None)
    return named or (locations[0] if locations else None)


async def overview(session: AsyncSession, business_id: uuid.UUID) -> dict[str, Any]:
    """What the sandbox can show for this business, with try-it suggestions made
    from its own records (never a stock example)."""
    ctx = await _context(session, business_id)
    cart = [o for o in ctx["offerings"] if o.offering_type in CART_KINDS]
    bookable = [o for o in ctx["offerings"] if o.offering_type in BOOKABLE]
    loc = ctx["locations"][0] if ctx["locations"] else None
    suggestions: dict[str, list[str]] = {"whatsapp_manager": [], "receptionist": []}
    if cart:
        suggestions["whatsapp_manager"].append(f"2 {cart[0].title.lower()} available ah?")
        suggestions["whatsapp_manager"].append(f"How much is {cart[0].title.lower()}?")
    if bookable:
        suggestions["receptionist"].append(f"Saturday evening {bookable[0].title.lower()} slot iruka?")
        suggestions["receptionist"].append(f"Can I book {bookable[0].title.lower()} tomorrow morning?")
        suggestions["whatsapp_manager"].append(f"Can I book {bookable[0].title.lower()} on Saturday?")
    for key in suggestions:
        suggestions[key] += ["What time do you close today?", "Can you give me a discount?"]
    return {
        "scenarios": [{"key": k, **v} for k, v in SCENARIOS.items()],
        "notice": SIMULATION_NOTICE,
        "business": {"name": ctx["business"].display_name},
        "location": loc.name if loc else None,
        "ready": {k: bool(v["ready"]) for k, v in ctx["states"].items()},
        "suggestions": suggestions,
    }


async def simulate(session: AsyncSession, business_id: uuid.UUID, *, scenario: str, message: str,
                   today: date | None = None) -> dict[str, Any]:
    """One customer message, handled the way the AI employee would — read-only."""
    if scenario not in SCENARIOS:
        raise ValidationError("Unknown sandbox scenario", details={"field": "scenario"})
    said = " ".join((message or "").split())[:500]
    if not said:
        raise ValidationError("Type what the customer says", details={"field": "message"})
    trace = _Trace()
    ctx = await _context(session, business_id)
    business: Business = ctx["business"]
    states = ctx["states"]
    emp = await _employee(session, business_id, SCENARIOS[scenario]["employee"])
    ta = _tanglish(said)
    name = business.display_name
    loc = _pick_location(ctx["locations"], said)
    trace.add("receive", f"Customer message ({SCENARIOS[scenario]['channel']})", said)

    if OWNER_ONLY.search(said) or STEERING.search(said):
        trace.add("guardrail", "Owner's decision, not the AI's",
                  "Discounts, refunds, complaints and attempts to change the rules always go to a person.")
        _decision(emp, "escalate", trace)
        return _result(trace, scenario, reply=("Ungalukku oru person reply pannuvaanga." if ta else
                                               "I'll pass this to someone at the business who can help."),
                       proposal=None)

    intent = deterministic_intent(said)
    offering = match_offering(said, ctx["offerings"])
    day, window = _day_and_window(said, today or datetime.now(timezone.utc).date())
    wants_order = bool(offering and offering.offering_type in CART_KINDS and
                       (_AVAILABLE.search(said) or _ORDER_WORDS.search(said)))
    wants_booking = bool(offering and offering.offering_type in BOOKABLE and
                         (intent == "book" or day or window or re.search(r"\bslot\b", said, re.I)))
    understood = "booking" if wants_booking else "availability / order" if wants_order else intent or "other"
    trace.add("understand", "Understood the message (rule-based, no AI model called)",
              "; ".join(p for p in (f"intent: {understood}",
                                    f"item: {offering.title}" if offering else "",
                                    f"quantity: {_quantity(said)}" if wants_order else "",
                                    f"day: {day.isoformat()}" if day else "",
                                    f"time of day: {window[0]:02d}:00–{window[1]:02d}:00" if window else "",
                                    f"location: {loc.name}" if loc else "") if p))

    if wants_order and offering is not None:
        return await _order(session, trace, scenario, emp, states, business, loc, offering, _quantity(said), ta)
    if wants_booking and offering is not None:
        return await _booking(session, trace, scenario, emp, states, business, loc, offering, day, window, ta)
    if intent == "hours" and loc is not None:
        _read(trace, "business_info", "Location record (Locations, Platform Core)",
              hours_text(loc.hours) or "no hours saved")
        told = hours_text(loc.hours)
        if told:
            _decision(emp, "business_info", trace)
            return _result(trace, scenario, reply=f"{name} is open {told}.", proposal=None)
    if intent == "address" and loc is not None:
        told = address_text(loc.address)
        _read(trace, "business_info", "Location record (Locations, Platform Core)", told or "no address saved")
        if told:
            _decision(emp, "business_info", trace)
            return _result(trace, scenario, reply=f"{name} is at {told}.", proposal=None)
    if intent in ("price", "services") or (offering is not None and not wants_booking):
        _module(trace, "offerings-catalog", states)
        if offering is not None and _price(offering):
            _read(trace, "list_services", "Offerings Catalog public read", f"{offering.title} · {_price(offering)}")
            _decision(emp, "list_services", trace)
            return _result(trace, scenario, reply=f"{offering.title}: {_price(offering)}.", proposal=None)
        if ctx["offerings"]:
            lines = [f"• {o.title}" + (f" — {_price(o)}" if _price(o) else "") for o in ctx["offerings"][:6]]
            _read(trace, "list_services", "Offerings Catalog public read", f"{len(ctx['offerings'])} live items")
            _decision(emp, "list_services", trace)
            return _result(trace, scenario, reply=f"Here is what {name} offers:\n" + "\n".join(lines), proposal=None)

    # Not answerable from records: keep it as an enquiry for a person.
    _module(trace, "leads", states)
    if states["leads"]["ready"]:
        _decision(emp, "capture_lead", trace)
        return _result(trace, scenario, reply=("Note pannikitten — business-la irundhu ungaluku reply varum."
                                               if ta else "I've noted your question — someone from the business "
                                               "will get back to you."),
                       proposal={"action": "lead", "summary": f"Save as an enquiry: “{said[:120]}”",
                                 "message": said[:500]})
    _decision(emp, "escalate", trace)
    return _result(trace, scenario, reply=("Oru person ungaluku reply pannuvaanga." if ta else
                                           "I'll pass this to someone at the business."), proposal=None)


def _module(trace: _Trace, module: str, states: dict[str, Any]) -> bool:
    from platform_core.catalog.modules import MODULES

    state = states.get(module) or {}
    ok = bool(state.get("ready"))
    label = MODULES[module].label if module in MODULES else module
    why = "" if ok else next((s["label"] for s in state.get("steps") or [] if not s["done"]), None) or (
        "not switched on" if not state.get("enabled") else "not ready")
    trace.add("module_check", f"{label}: {'ready' if ok else 'not ready'}", why, module=module, ok=ok)
    return ok


def _read(trace: _Trace, tool: str, contract: str, result: str) -> None:
    t = TOOLS.get(tool)
    trace.add("read", f"Read: {t.label if t else tool}", result, tool=tool, tier=t.tier if t else "T0",
              contract=contract)


async def _order(session: AsyncSession, trace: _Trace, scenario: str, emp: AIEmployee, states: dict[str, Any],
                 business: Business, loc: BusinessLocation | None, offering: Offering, qty: int,
                 ta: bool) -> dict[str, Any]:
    from platform_core.stock.public import public_availability

    _module(trace, "offerings-catalog", states)
    price = _price(offering)
    stock = None
    if states["inventory"]["ready"]:
        stock = (await public_availability(session, business.id, [offering],
                                           location_id=loc.id if loc else None)).get(str(offering.id))
    where = f" at {loc.name}" if loc else ""
    _read(trace, "list_services", "Offerings Catalog public read" + (" + Inventory public availability"
                                                                      if stock else ""),
          f"{offering.title} · {price or 'price on request'}" + (f" · {stock.replace('_', ' ')}{where}" if stock else ""))
    if stock == "out_of_stock":
        return _result(trace, scenario, reply=(f"Sorry, {offering.title}{where} ippo stock-la illa." if ta else
                                               f"Sorry, {offering.title} is out of stock{where} right now."),
                       proposal=None)
    orders_ok = _module(trace, "orders", states)
    fulfil_ok = _module(trace, "fulfilment", states)
    _decision(emp, "send_link", trace)
    yes = (f"Aama, {offering.title}{where} iruku — {price}." if ta else
           f"Yes, {offering.title} is available{where} for {price}.") if price else (
        f"Aama, {offering.title}{where} iruku." if ta else f"Yes, {offering.title} is available{where}.")
    if not (orders_ok and fulfil_ok):
        trace.add("note", "Ordering is not set up, so the AI would not take an order",
                  "It would share your menu or ask the customer to call.")
        return _result(trace, scenario, reply=yes + (" Order panna call pannunga." if ta else " Please call us to order."),
                       proposal=None)
    total = float(offering.price_amount or 0) * qty
    ask = (f" {qty} order-la add pannattuma?" if ta else
           f" Would you like me to add {qty} to an order{f' (₹{total:,.0f})' if total else ''}?")
    trace.add("propose", "Proposed: an order (needs your approval in the sandbox)",
              f"{qty} × {offering.title}" + (f" = ₹{total:,.0f}" if total else ""), action="order")
    return _result(trace, scenario, reply=yes + ask, proposal={
        "action": "order", "offering_id": str(offering.id), "quantity": qty,
        "location_id": str(loc.id) if loc else None,
        "summary": f"Order {qty} × {offering.title}" + (f" (₹{total:,.0f})" if total else "")})


async def _booking(session: AsyncSession, trace: _Trace, scenario: str, emp: AIEmployee, states: dict[str, Any],
                   business: Business, loc: BusinessLocation | None, offering: Offering, day: date | None,
                   window: tuple[int, int] | None, ta: bool) -> dict[str, Any]:
    from platform_core.messaging.words import clock, day_words
    from platform_core.services.booking_slots import BookingSlotService, mode_for, zone

    if not _module(trace, "bookings", states) or loc is None:
        return _result(trace, scenario, reply=(f"{offering.title}-ku booking ippo online-la illa — call pannunga."
                                               if ta else f"Online booking for {offering.title} isn't set up — "
                                               "please call us."), proposal=None)
    day = day or (datetime.now(timezone.utc).date() + timedelta(days=1))
    mode = mode_for(offering)
    if mode not in ("appointment", "class_session", "site_visit", "table"):
        trace.add("note", "Booked by dates, not a time slot", "The AI would send the booking page.")
        return _result(trace, scenario, reply=f"You can pick your dates for {offering.title} on our booking page.",
                       proposal=None)
    found = await BookingSlotService.day_slots(session, business_id=business.id, location=loc, mode=mode,
                                               offering=offering, provider_id=None, party_size=1, day=day)
    tz = zone(loc)
    free = [s for s in found["slots"] if not s.get("full")]
    if window:
        free = [s for s in free if window[0] <= datetime.fromisoformat(s["starts_at"]).astimezone(tz).hour
                < window[1]]
    _decision(emp, "check_availability", trace)
    _read(trace, "check_availability", "Bookings engine (day slots, read only)",
          "closed that day" if found.get("closed") else
          f"{len(free)} free time(s) on {day.isoformat()}" + (f" between {window[0]}:00 and {window[1]}:00"
                                                              if window else ""))
    # Tanglish replies keep roman day names ("Sat 03 Oct"); Tamil script would not match the reply.
    when = day_words(day, None)
    if not free:
        return _result(trace, scenario, reply=(f"{when} {offering.title}-ku slot illa. Vera naal paakkalaama?" if ta
                                               else f"There's no free time for {offering.title} on {when}"
                                               f"{' then' if window else ''}. Shall I check another day?"),
                       proposal=None)
    first = free[0]
    start = datetime.fromisoformat(first["starts_at"]).astimezone(tz)
    options = ", ".join(clock(datetime.fromisoformat(s["starts_at"]).astimezone(tz).time(), None) for s in free[:3])
    _decision(emp, "start_booking", trace)
    trace.add("propose", "Proposed: a booking (needs your approval in the sandbox)",
              f"{offering.title} · {when} {clock(start.time(), None)} · {loc.name}", action="booking")
    reply = (f"{when} {options} free-aa iruku. {clock(start.time(), None)}-ku book pannattuma?" if ta else
             f"{when} has {options} free for {offering.title} at {loc.name}. "
             f"Shall I book {clock(start.time(), None)}?")
    return _result(trace, scenario, reply=reply, proposal={
        "action": "booking", "offering_id": str(offering.id), "location_id": str(loc.id),
        "starts_at": first["starts_at"], "ends_at": first["ends_at"], "mode": mode,
        "summary": f"Book {offering.title} — {when} {clock(start.time(), None)} at {loc.name}"})


def _result(trace: _Trace, scenario: str, *, reply: str, proposal: dict[str, Any] | None) -> dict[str, Any]:
    trace.add("sandbox", "Nothing sent, nothing saved", SIMULATION_NOTICE)
    return {"scenario": scenario, "reply": reply, "trace": trace.steps, "proposal": proposal,
            "simulated": True, "notice": SIMULATION_NOTICE}


async def approve(session: AsyncSession, business_id: uuid.UUID, proposal: dict[str, Any]) -> dict[str, Any]:
    """The owner approves a proposal *in the sandbox*: the live records are
    checked again and a sandbox reference is returned. Nothing is created."""
    action = str(proposal.get("action") or "")
    trace = _Trace()
    if action not in ("order", "booking", "lead"):
        raise ValidationError("Nothing to approve", details={"field": "action"})
    trace.add("approval", "You approved this in the sandbox", str(proposal.get("summary") or ""))
    ref = f"SANDBOX-{uuid.uuid4().hex[:6].upper()}"
    if action == "lead":
        trace.add("simulate", "Would save an enquiry for a person to follow up", "Leads — not saved in the sandbox")
        return {"ok": True, "reference": ref, "trace": trace.steps, "simulated": True, "notice": SIMULATION_NOTICE,
                "result": "An enquiry would have been saved for your team."}
    offering = await session.get(Offering, uuid.UUID(str(proposal.get("offering_id"))))
    if (offering is None or offering.business_id != business_id or offering.deleted_at is not None
            or offering.status != "active" or offering.visibility != "public"):
        raise ResourceNotFound("Offering")
    if action == "order":
        qty = max(1, min(int(proposal.get("quantity") or 1), 50))
        total = float(offering.price_amount or 0) * qty
        trace.add("recheck", "Checked the item and its price again (live)", f"{offering.title} · {_price(offering)}")
        trace.add("simulate", "Would create the order through Orders (the same path staff use)",
                  "Not created in the sandbox")
        return {"ok": True, "reference": ref, "trace": trace.steps, "simulated": True, "notice": SIMULATION_NOTICE,
                "result": f"Order {ref}: {qty} × {offering.title}" + (f" — ₹{total:,.0f}" if total else "")}
    from platform_core.services.booking_slots import BookingSlotService, zone

    loc = (await session.execute(select(BusinessLocation).where(
        BusinessLocation.business_id == business_id,
        BusinessLocation.id == uuid.UUID(str(proposal.get("location_id")))))).scalars().first()
    if loc is None:
        raise ResourceNotFound("Location")
    starts = datetime.fromisoformat(str(proposal.get("starts_at")))
    still = await BookingSlotService.day_slots(session, business_id=business_id, location=loc,
                                               mode=str(proposal.get("mode") or "appointment"), offering=offering,
                                               provider_id=None, party_size=1,
                                               day=starts.astimezone(zone(loc)).date())
    free = any(s["starts_at"] == proposal.get("starts_at") and not s.get("full") for s in still["slots"])
    trace.add("recheck", "Checked the time is still free (live)", "still free" if free else "no longer free")
    if not free:
        return {"ok": False, "reference": None, "trace": trace.steps, "simulated": True, "notice": SIMULATION_NOTICE,
                "result": "That time was taken meanwhile — the AI would offer the next free time."}
    trace.add("simulate", "Would create the booking through Bookings (the same path staff use)",
              "Not created in the sandbox")
    return {"ok": True, "reference": ref, "trace": trace.steps, "simulated": True, "notice": SIMULATION_NOTICE,
            "result": f"Booking {ref}: {proposal.get('summary')}"}
