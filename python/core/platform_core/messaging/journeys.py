"""Structured WhatsApp journeys (Capability Universe §12.3, P1 column; §12.4).

Order, book, enquire, pay / dues, track, reorder, change / cancel — with
buttons and lists, zero model calls. The router (MessagingService.route)
offers every message here first; a journey that does not recognise it says
so, and a person takes over.

Rules kept here (§12.4):
* **The customer confirms every cart or booking with a button.** Nothing is
  placed silently; if a price changed since the summary they confirmed, they
  see the new total and confirm again.
* **Prices and stock come only from LOCAH.** The cart holds what was chosen,
  never a price: every summary and the order itself are priced from the
  catalogue at that moment, and stock and slots are re-checked at confirm
  with alternatives offered.
* **Every path ends in the same order, booking or lead the website creates**
  (CheckoutService.place_for_contact, BookingService, LeadService), marked
  with the channel `whatsapp`.
* **Addresses:** a location pin or a typed address with its PIN code; the
  customer's last delivery address is offered first. Turning a pin into a
  street address needs a maps provider (P2); the pin itself is kept.
* **Payment:** cash on delivery / at pickup where the owner allows it, with
  the owner's first-order COD cap. Online payment links need a payment
  provider (activation required).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import PlatformError
from platform_core.messaging.words import LANGUAGE_ASK, LANGUAGE_NAMES, LANGUAGE_ROW, LANGS, clock, day_words, detect, tr
from platform_core.models import (
    Booking,
    Business,
    BusinessLocation,
    CustomerContact,
    FulfilmentJob,
    InventoryRecord,
    InvoicingDocument,
    LedgerAccount,
    MessagingConversation,
    Offering,
    OfferingCategory,
    OfferingVariant,
    OrderLineItem,
    SalesOrder,
)

IST = ZoneInfo("Asia/Kolkata")
MENU_WORDS = {"hi", "hii", "hello", "hey", "menu", "start", "help", "vanakkam", "வணக்கம்", "மெனு", "namaste", "namaskar",
              "नमस्ते", "नमस्कार", "मेनू", "0"}
LANGUAGE_WORDS = {"language", "lang", "மொழி", "भाषा", "tamil", "hindi", "english", "தமிழ்", "हिंदी"}
# Checked in this order: "cancel my booking" is a cancellation, not a booking.
INTENTS: dict[str, tuple[str, ...]] = {
    "m:cancel": ("cancel", "change my"),
    "m:track": ("where is my order", "where's my order", "track", "status", "எங்கே", "कहाँ"),
    "m:pay": ("how much do i owe", "balance", "dues", "due", "pay", "khata", "bill", "பாக்கி", "बकाया"),
    "m:reorder": ("repeat", "reorder", "same as last", "same again"),
    "m:book": ("book", "appointment", "booking", "slot", "முன்பதிவு", "बुक", "बुकिंग"),
    "m:order": ("order", "buy", "ஆர்டர்", "ऑर्डर", "வாங்க", "खरीद"),
    "m:enquire": ("enquire", "enquiry", "inquiry", "question", "price list", "details"),
}
OPEN_ORDER = ("pending", "accepted", "preparing", "ready")
STATUS_WORDS = {"pending": "waiting for the shop to accept", "accepted": "accepted", "preparing": "being prepared",
                "ready": "ready", "completed": "completed", "cancelled": "cancelled", "rejected": "declined"}
PAGE = 8  # a list holds ten rows: checkout, eight items, more


def _t(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _inr(v: Any) -> str:
    return f"₹{Decimal(str(v or 0)):,.2f}"


def buttons(body: str, items: list[tuple[str, str]]) -> dict[str, Any]:
    """Up to three reply buttons (WhatsApp's limit), titles up to 20 characters."""
    return {"type": "button", "body": {"text": _t(body, 1024)},
            "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": _t(title, 20)}}
                                   for i, title in items[:3]]}}


def listing(body: str, button: str, rows: list[tuple[str, str, str]]) -> dict[str, Any]:
    """A list of up to ten rows (titles 24, descriptions 72 characters)."""
    return {"type": "list", "body": {"text": _t(body, 1024)},
            "action": {"button": _t(button, 20), "sections": [{"title": _t("Choose", 24), "rows": [
                {"id": i, "title": _t(title, 24), **({"description": _t(desc, 72)} if desc else {})}
                for i, title, desc in rows[:10]]}]}}


@dataclass
class Ctx:
    session: AsyncSession
    conv: MessagingConversation
    business: Business
    contact: CustomerContact | None
    live: set[str]
    lang: str = "en"

    def tr(self, text: str, **params: Any) -> str:
        said: str = tr(self.lang, text, **params)
        return said

    def link(self, url: str) -> str:
        """A tracking, bill, payment or statement link that opens in the customer's language (P1-10E6)."""
        if self.lang == "en":
            return url
        return f"{url}{'&' if '?' in url else '?'}lang={self.lang}"

    @property
    def j(self) -> dict[str, Any]:
        return dict(self.conv.journey or {})

    def save(self, **changes: Any) -> None:
        j = self.j
        for k, v in changes.items():
            if v is None:
                j.pop(k, None)
            else:
                j[k] = v
        self.conv.journey = j

    async def say(self, body: str) -> None:
        from platform_core.services.messaging import MessagingService

        await MessagingService.bot_text(self.session, self.conv, body)

    async def ask(self, interactive: dict[str, Any]) -> None:
        from platform_core.services.messaging import MessagingService

        if interactive.get("type") == "list":
            for section in interactive["action"]["sections"]:
                section["title"] = _t(self.tr("Choose"), 24)
        await MessagingService.bot_interactive(self.session, self.conv, interactive)


async def _ctx(session: AsyncSession, conv: MessagingConversation) -> Ctx:
    business = await session.get(Business, conv.business_id)
    assert business is not None
    contact = await session.get(CustomerContact, conv.contact_id) if conv.contact_id else None
    live = {r[0] for r in (await session.execute(text(
        "SELECT module_id FROM business_module_states WHERE business_id = :b "
        "AND activation_state IN ('enabled', 'ready', 'active')"), {"b": str(conv.business_id)})).all()}
    # The same readiness answer the website and Marketplace use (Guide §4):
    # ordering, booking and enquiring are offered only once they are set up.
    from platform_core.services.module_readiness import readiness

    states = await readiness(session, conv.business_id, modules=("orders", "bookings", "leads"))
    live -= {m for m, st in states.items() if not st["ready"]}
    return Ctx(session, conv, business, contact, live, await language_for(session, conv.business_id, contact))


async def language_for(session: AsyncSession, business_id: uuid.UUID, contact: CustomerContact | None) -> str:
    """The customer's language: chosen or written in, else the business's WhatsApp language."""
    if contact is not None and contact.language in LANGS:
        return str(contact.language)
    lang = (await session.execute(text("SELECT language FROM messaging_settings WHERE business_id = :b"),
                                  {"b": str(business_id)})).scalar()
    return str(lang) if lang in LANGS else "en"


# ---------------------------------------------------------------- entry
async def handle(session: AsyncSession, conv: MessagingConversation, kind: str, body: str,
                 extra: dict[str, Any]) -> bool:
    """True when a structured journey answered the message."""
    from platform_core.services.messaging import MessagingService

    if not await MessagingService.bot_may_reply(session, conv):
        return False  # a person is handling this chat (§12.1)
    if kind == "text" and conv.contact_id:
        await _note_language(session, conv, body)
    ctx = await _ctx(session, conv)
    reply_id = str(extra.get("id") or "") if kind in ("button", "list") else ""
    if reply_id:
        return await _dispatch(ctx, reply_id)
    step = ctx.j.get("step")
    if kind == "location" and step == "address":
        return await _address_pin(ctx, extra)
    if kind != "text":
        return False
    said = body.strip().lower()
    if step in TEXT_STEPS:
        if said in MENU_WORDS:
            ctx.save(step=None)
        else:
            return bool(await TEXT_STEPS[step](ctx, body.strip()))
    if said in MENU_WORDS:
        return await menu(ctx)
    if said in LANGUAGE_WORDS:
        return await language_ask(ctx, "")
    for key, words in INTENTS.items():
        if any(said == w or said.startswith(w + " ") or (len(w) > 5 and w in said) for w in words):
            return await _dispatch(ctx, key)
    # A customer rarely types the one word a bot waits for. "menu enna iruku?
    # biriyani rate?" asks two plain things the catalogue can answer; "i want to
    # order" is an order. Read short messages for what they ask before handing
    # them to a person (who may be asleep).
    # Where the owner has switched on the AI receptionist, free text is its
    # job (it answers prices, hours and more, on its own limits and record).
    from platform_core.ai_employees.runtime import AIRuntime

    if await AIRuntime.active(session, conv.business_id, "receptionist") is not None:
        return False
    if await _answer_prices(ctx, body):
        return True
    # A wish, said as a sentence: "i want to order", "can i book for tomorrow",
    # "menu please". A question about something already under way ("is my
    # order coming?") is not a wish to start one — that waits for a person.
    count = len(said.split())
    if count <= 8 and not _UPSET.search(said) and (count <= 3 or _WISH.search(said)):
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", said) for w in MENU_WORDS if len(w) > 3):
            return await menu(ctx)
        for key, words in INTENTS.items():
            if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", said) for w in words if w.isascii()):
                return await _dispatch(ctx, key)
    return False


_WISH = re.compile(r"\b(?:want|wanna|need|like to|can i|could i|may i|please|pls|plz|kindly|send|show|give|venum|vendum|venam|kudunga|anuppunga|chahiye|karna hai|dijiye|bhejo)\b", re.I)


_PRICE_ASK = re.compile(
    r"\b(?:rates?|prices?|cost|costs|how much|evlo|evvalavu|evalavu|vilai|kitna|kitne|kitni|daam|charges?|"
    r"amount|fees?)\b|விலை|எவ்வளவு|कितना|कितने|दाम", re.I)
# Someone unhappy wants a person, not a price list.
_UPSET = re.compile(r"\b(?:refund|complain\w*|worst|bad|cold|late|wrong|missing|not good|cheat\w*|spoil\w*|"
                    r"stale|rude|waiting)\b", re.I)
_PLAIN_WORDS = frozenset({"the", "and", "with", "for", "per", "special", "full", "half", "plate", "combo", "pack",
                          "small", "large", "medium", "regular", "new", "fresh", "our", "your"})


def _same_word(word: str) -> str:
    """A word as customers and owners both spell it: "biriyani" / "biryani" /
    "briyani", "chiken" / "chicken", a plural or a doubled letter."""
    from platform_core.interview.spelling import fix_word

    word = fix_word(word).casefold()
    word = re.sub(r"(.)\1+", r"\1", word)
    word = word.replace("iy", "y").replace("ee", "i").replace("oo", "u")
    word = re.sub(r"^bri?yani$|^biriani$", "biryani", word)
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


async def _answer_prices(ctx: Ctx, body: str) -> bool:
    """Answer "biriyani rate?" or "haircut evlo?" from the live catalogue.

    Only what LOCAH holds is said: the item's own name and today's price. Runs
    for a short message that names something on sale, or asks a price; never
    for a long message or an unhappy one — those are a person's to answer.
    """
    said = " ".join(body.split())
    if not said or len(said.split()) > 14 or _UPSET.search(said):
        return False
    asked = bool(_PRICE_ASK.search(said))
    words = {_same_word(w) for w in re.findall(r"[A-Za-z]{3,}", said)} - _PLAIN_WORDS
    orderable = await _orderable(ctx.session, ctx.business.id) if "orders" in ctx.live else []
    bookable = await _bookable(ctx.session, ctx.business.id) if "bookings" in ctx.live else []
    pool: dict[uuid.UUID, Offering] = {o.id: o for o in [*orderable, *bookable]}
    scored: list[tuple[int, str, Offering]] = []
    for offering in pool.values():
        name = {_same_word(w) for w in re.findall(r"[A-Za-z]{3,}", offering.title or "")} - _PLAIN_WORDS
        hit = len(name & words)
        if hit:
            scored.append((hit, offering.title, offering))
    if not scored:
        if asked and len(said.split()) <= 6 and (orderable or bookable):
            # "rate enna?", "price list please": the whole list, with its prices.
            return await _dispatch(ctx, "m:order" if orderable else "m:book")
        return False
    if not asked and len(said.split()) > 4:
        return False  # it names a dish but is not asking about it ("the biriyani was nice")
    best = max(hit for hit, _, _ in scored)
    chosen = [o for hit, _, o in sorted(scored, key=lambda row: (-row[0], row[1])) if hit == best][:6]
    lines = [f"• {o.title} — {_price_words(ctx, o)}" for o in chosen]
    actions: list[tuple[str, str]] = []
    if any(o.id in {x.id for x in orderable} for o in chosen):
        actions.append(("m:order", ctx.tr("Order")))
    if any(o.id in {x.id for x in bookable} for o in chosen):
        actions.append(("m:book", ctx.tr("Book")))
    actions += [("menu", ctx.tr("Menu")), ("talk_to_person", ctx.tr("Talk to a person"))]
    await ctx.ask(buttons("\n".join(lines), actions))
    return True


async def _note_language(session: AsyncSession, conv: MessagingConversation, body: str) -> None:
    """A customer writing in Tamil or Hindi script is answered in it — unless they chose a language."""
    found = detect(body)
    if found is None:
        return
    contact = await session.get(CustomerContact, conv.contact_id)
    if contact is not None and contact.language_source != "chosen" and contact.language != found:
        contact.language, contact.language_source = found, "detected"
        await session.flush()


async def language_ask(ctx: Ctx, arg: str) -> bool:
    await ctx.ask(buttons(LANGUAGE_ASK, [(f"l:{k}", v) for k, v in LANGUAGE_NAMES.items()]))
    return True


async def language_set(ctx: Ctx, arg: str) -> bool:
    if arg not in LANGS or ctx.contact is None:
        return await language_ask(ctx, "")
    ctx.contact.language, ctx.contact.language_source = arg, "chosen"
    ctx.lang = arg
    await ctx.session.flush()
    await ctx.say(ctx.tr("Done — we'll write to you in English."))
    return await menu(ctx)


async def _dispatch(ctx: Ctx, rid: str) -> bool:
    if rid == "menu":
        return await menu(ctx)
    for prefix, fn in ROUTES:
        if rid == prefix or rid.startswith(prefix + ":"):
            return bool(await fn(ctx, rid[len(prefix) + 1:] if rid != prefix else ""))
    return False


# ---------------------------------------------------------------- menu
async def _orderable(session: AsyncSession, business_id: uuid.UUID) -> list[Offering]:
    from platform_core.catalog.offering_kinds import KINDS

    rows = (await session.execute(select(Offering).where(
        Offering.business_id == business_id, Offering.deleted_at.is_(None), Offering.status == "active",
        Offering.visibility == "public", Offering.title != "Delivery fee").order_by(Offering.title))).scalars()
    return [o for o in rows if (KINDS.get(o.offering_type) is None or KINDS[o.offering_type].flow == "cart")
            and (o.price_amount is not None or o.variant_options)]


async def _bookable(session: AsyncSession, business_id: uuid.UUID) -> list[Offering]:
    return list((await session.execute(select(Offering).where(
        Offering.business_id == business_id, Offering.deleted_at.is_(None), Offering.status == "active",
        Offering.visibility == "public", Offering.offering_type.in_(("service", "experience", "rental")),
    ).order_by(Offering.title))).scalars())


async def _open_orders(ctx: Ctx) -> list[SalesOrder]:
    if ctx.contact is None:
        return []
    return list((await ctx.session.execute(select(SalesOrder).where(
        SalesOrder.business_id == ctx.business.id, SalesOrder.customer_contact_id == ctx.contact.id,
        SalesOrder.deleted_at.is_(None), SalesOrder.status.in_(OPEN_ORDER)).order_by(SalesOrder.created_at.desc())
        .limit(5))).scalars())


async def _upcoming_bookings(ctx: Ctx) -> list[Booking]:
    if ctx.contact is None:
        return []
    return list((await ctx.session.execute(select(Booking).where(
        Booking.business_id == ctx.business.id, Booking.customer_contact_id == ctx.contact.id,
        Booking.deleted_at.is_(None), Booking.status.in_(("pending", "confirmed")),
        Booking.starts_at > datetime.now(timezone.utc)).order_by(Booking.starts_at).limit(5))).scalars())


async def menu(ctx: Ctx) -> bool:
    rows: list[tuple[str, str, str]] = []
    if "orders" in ctx.live and await _orderable(ctx.session, ctx.business.id):
        rows.append(("m:order", ctx.tr("Order"), ctx.tr("See what we have and order here")))
    if "bookings" in ctx.live and await _bookable(ctx.session, ctx.business.id):
        rows.append(("m:book", ctx.tr("Book"), ctx.tr("Pick a service and a time")))
    if "leads" in ctx.live:
        rows.append(("m:enquire", ctx.tr("Ask a question"), ctx.tr("About a product, service or price")))
    open_orders = await _open_orders(ctx)
    if open_orders:
        rows.append(("m:track", ctx.tr("Track my order"), ctx.tr("Where your order is now")))
    if ctx.contact and "orders" in ctx.live and (await ctx.session.execute(select(func.count()).select_from(SalesOrder)
            .where(SalesOrder.business_id == ctx.business.id, SalesOrder.customer_contact_id == ctx.contact.id,
                   SalesOrder.deleted_at.is_(None)))).scalar_one():
        rows.append(("m:reorder", ctx.tr("Repeat my last order"), ctx.tr("Same items, today's prices")))
    if ctx.contact and ({"ledger", "invoicing"} & ctx.live):
        rows.append(("m:pay", ctx.tr("What do I owe"), ctx.tr("Your balance and bills")))
    if any(o.status == "pending" for o in open_orders) or await _upcoming_bookings(ctx):
        rows.append(("m:cancel", ctx.tr("Change or cancel"), ctx.tr("An order or a booking")))
    rows.append(("talk_to_person", ctx.tr("Talk to a person"), ctx.tr("Someone from the team replies here")))
    rows.append(("m:lang", *LANGUAGE_ROW))
    ctx.save(step=None)
    name = (ctx.contact.display_name.split()[0] if ctx.contact and ctx.contact.display_name
            and not ctx.contact.display_name.startswith("+") else None)
    head = (ctx.tr("Hi {name}! This is {business}. What would you like to do?", name=name,
                   business=ctx.business.display_name) if name else
            ctx.tr("Hi there! This is {business}. What would you like to do?", business=ctx.business.display_name))
    await ctx.ask(listing(head, ctx.tr("Menu"), rows))
    return True


# ---------------------------------------------------------------- order
async def order_start(ctx: Ctx, arg: str) -> bool:
    items = await _orderable(ctx.session, ctx.business.id)
    if "orders" not in ctx.live or not items:
        await ctx.say(ctx.tr("Ordering on WhatsApp is not available right now. Tap Talk to a person, or send menu."))
        return True
    cats = {o.category_id for o in items if o.category_id}
    if not ctx.j.get("cart_id"):
        ctx.save(cart_id=uuid.uuid4().hex, cart=[])
    ctx.conv.topic = "order"
    if len(cats) > 1 and not arg:
        names: dict[uuid.UUID, str] = {r[0]: r[1] for r in (await ctx.session.execute(select(
            OfferingCategory.id, OfferingCategory.name).where(OfferingCategory.id.in_(cats)))).all()}
        rows = [*await _checkout_row(ctx),
                *[(f"o:cat:{cid}", names.get(cid, ctx.tr("Other")),
                   _count(ctx, sum(1 for o in items if o.category_id == cid)))
                  for cid in sorted(cats, key=lambda c: names.get(c, ""))][:8]]
        if any(o.category_id is None for o in items):
            rows.append(("o:cat:none", ctx.tr("Other items"), ""))
        await ctx.ask(listing(ctx.tr("What would you like to order?"), ctx.tr("Categories"), rows))
        return True
    ctx.save(cat=None)
    return await order_page(ctx, arg or "0")


async def order_category(ctx: Ctx, arg: str) -> bool:
    ctx.save(cat=arg)
    return await order_page(ctx, "0")


async def order_page(ctx: Ctx, arg: str) -> bool:
    items = await _orderable(ctx.session, ctx.business.id)
    cat = ctx.j.get("cat")
    if cat:
        items = [o for o in items if (str(o.category_id) if o.category_id else "none") == cat]
    page = int(arg or 0)
    chunk = items[page * PAGE:(page + 1) * PAGE]
    rows = [*await _checkout_row(ctx), *[(f"o:item:{o.id}", o.title, _price_words(ctx, o)) for o in chunk]]
    if len(items) > (page + 1) * PAGE:
        rows.append((f"o:page:{page + 1}", ctx.tr("More items…"), ctx.tr("{n} more", n=len(items) - (page + 1) * PAGE)))
    await ctx.ask(listing(ctx.tr("Choose an item — prices are today's."), ctx.tr("Items"), rows))
    return True


async def _checkout_row(ctx: Ctx) -> list[tuple[str, str, str]]:
    cart = list(ctx.j.get("cart") or [])
    if not cart:
        return []
    priced = await _price_cart(ctx, cart)
    n = sum(int(line["quantity"]) for line in cart)
    return [("o:checkout", ctx.tr("Checkout (1 item)") if n == 1 else ctx.tr("Checkout ({n} items)", n=n),
             ctx.tr("{amount} so far", amount=_inr(priced["subtotal"])))]


def _count(ctx: Ctx, n: int) -> str:
    return ctx.tr("1 item") if n == 1 else ctx.tr("{n} items", n=n)


def _price_words(ctx: Ctx, o: Offering) -> str:
    if o.price_amount is None:
        return ctx.tr("Choose an option")
    per = (o.attributes or {}).get("price_per")
    return f"{_inr(o.price_amount)}{f' / {per}' if per else ''}"


async def order_item(ctx: Ctx, arg: str) -> bool:
    offering = await ctx.session.get(Offering, uuid.UUID(arg))
    if offering is None or offering.business_id != ctx.business.id or offering.status != "active":
        await ctx.say(ctx.tr("That item is no longer available."))
        return await order_page(ctx, "0")
    ctx.save(pending={"offering_id": str(offering.id), "options": {}, "title": offering.title}, step=None)
    return await _next_choice(ctx, offering)


async def _next_choice(ctx: Ctx, offering: Offering) -> bool:
    """Ask for what still has to be chosen: option, pack, required choices, then quantity."""
    p = dict(ctx.j.get("pending") or {})
    variants = list((await ctx.session.execute(select(OfferingVariant).where(
        OfferingVariant.offering_id == offering.id, OfferingVariant.status == "active")
        .order_by(OfferingVariant.sort_order))).scalars())
    if variants and not p.get("variant_id"):
        await ctx.ask(listing(ctx.tr("{item}: which one?", item=offering.title), ctx.tr("Options"),
                              [(f"o:var:{v.id}", v.name, _inr(v.price_amount if v.price_amount is not None
                                                            else offering.price_amount)) for v in variants[:10]]))
        return True
    packs = list(offering.sell_units or [])
    opts = dict(p.get("options") or {})
    if packs and not opts.get("pack"):
        await ctx.ask(listing(ctx.tr("{item}: how much?", item=offering.title), ctx.tr("Sizes"),
                              [(f"o:pack:{i}", str(pk["label"]), "") for i, pk in enumerate(packs[:10])]))
        return True
    choices = dict(opts.get("choices") or {})
    notes = dict(opts.get("notes") or {})
    for gi, g in enumerate(offering.option_groups or []):
        if g["name"] in choices or g["name"] in notes or f"skip:{g['name']}" in (p.get("skipped") or []):
            continue
        if g.get("text"):
            # The message on the cake: the customer types it (or skips it when it is optional).
            ctx.save(step="note", note_group=gi)
            ask = ctx.tr("{item}: type the {group} (up to {n} letters).", item=offering.title,
                         group=_group(ctx, g["name"]), n=g["max_length"])
            if g["required"]:
                await ctx.say(ask)
            else:
                await ctx.ask(buttons(ask, [("o:note:-", ctx.tr("No {group}", group=_group(ctx, g["name"])))]))
            return True
        rows = [(f"o:opt:{gi}:{ci}", str(c["label"]),
                 f"+{_inr(c['price_delta'])}" if Decimal(str(c["price_delta"])) else "")
                for ci, c in enumerate(g["choices"][:9])]
        if not g["required"]:
            rows.append((f"o:opt:{gi}:-", ctx.tr("No {group}", group=_group(ctx, g["name"])), ""))
        await ctx.ask(listing(ctx.tr("{item}: {group}?", item=offering.title, group=_group(ctx, g["name"])),
                              _t(g["name"], 20), rows))
        return True
    ctx.save(step="qty")
    await ctx.ask(buttons(ctx.tr("How many {item}?", item=offering.title),
                          [("o:qty:1", "1"), ("o:qty:2", "2"), ("o:qty:3", "3")]))
    await ctx.say(ctx.tr("Or type a number."))
    return True


def _group(ctx: Ctx, name: str) -> str:
    """An owner's choice group name inside a sentence ("the message on the cake")."""
    return name.lower() if ctx.lang == "en" else name


async def order_variant(ctx: Ctx, arg: str) -> bool:
    p = dict(ctx.j.get("pending") or {})
    if not p:
        return await order_page(ctx, "0")
    p["variant_id"] = arg
    ctx.save(pending=p)
    return await _next_choice(ctx, await _pending_offering(ctx))


async def order_pack(ctx: Ctx, arg: str) -> bool:
    p = dict(ctx.j.get("pending") or {})
    offering = await _pending_offering(ctx)
    packs = list(offering.sell_units or [])
    p["options"] = {**(p.get("options") or {}), "pack": packs[int(arg)]["label"]}
    ctx.save(pending=p)
    return await _next_choice(ctx, offering)


async def order_option(ctx: Ctx, arg: str) -> bool:
    p = dict(ctx.j.get("pending") or {})
    offering = await _pending_offering(ctx)
    gi, ci = arg.split(":")
    g = (offering.option_groups or [])[int(gi)]
    if ci == "-":
        p["skipped"] = [*(p.get("skipped") or []), f"skip:{g['name']}"]
    else:
        opts = dict(p.get("options") or {})
        opts["choices"] = {**(opts.get("choices") or {}), g["name"]: [g["choices"][int(ci)]["label"]]}
        p["options"] = opts
    ctx.save(pending=p)
    return await _next_choice(ctx, offering)


async def order_note(ctx: Ctx, arg: str) -> bool:
    """Skip an optional text box."""
    p = dict(ctx.j.get("pending") or {})
    offering = await _pending_offering(ctx)
    g = (offering.option_groups or [])[int(ctx.j.get("note_group") or 0)]
    p["skipped"] = [*(p.get("skipped") or []), f"skip:{g['name']}"]
    ctx.save(pending=p, step=None)
    return await _next_choice(ctx, offering)


async def _note_typed(ctx: Ctx, said: str) -> bool:
    p = dict(ctx.j.get("pending") or {})
    if not p:
        ctx.save(step=None)
        return False
    offering = await _pending_offering(ctx)
    g = (offering.option_groups or [])[int(ctx.j.get("note_group") or 0)]
    value = " ".join(said.split())
    if len(value) > int(g["max_length"]):
        await ctx.say(ctx.tr("That is {count} letters — up to {max}, please. Type it again.", count=len(value),
                             max=g["max_length"]))
        return True
    opts = dict(p.get("options") or {})
    opts["notes"] = {**(opts.get("notes") or {}), g["name"]: value}
    p["options"] = opts
    ctx.save(pending=p, step=None)
    return await _next_choice(ctx, offering)


async def _pending_offering(ctx: Ctx) -> Offering:
    p = ctx.j.get("pending") or {}
    o = await ctx.session.get(Offering, uuid.UUID(str(p.get("offering_id"))))
    assert o is not None
    return o


async def order_qty(ctx: Ctx, arg: str) -> bool:
    return await _add_to_cart(ctx, arg)


async def _qty_typed(ctx: Ctx, said: str) -> bool:
    m = re.fullmatch(r"\s*(\d{1,3})\s*", said)
    if not m or int(m.group(1)) < 1:
        await ctx.say(ctx.tr("Type how many as a number, like 2."))
        return True
    return await _add_to_cart(ctx, m.group(1))


async def _add_to_cart(ctx: Ctx, qty: str) -> bool:
    p = dict(ctx.j.get("pending") or {})
    if not p:
        return await order_page(ctx, "0")
    line = {"offering_id": p["offering_id"], "variant_id": p.get("variant_id"), "options": p.get("options") or {},
            "quantity": max(1, min(999, int(qty)))}
    cart = [*(ctx.j.get("cart") or []), line]
    ctx.save(cart=cart, pending=None, step=None)
    priced = await _price_cart(ctx, cart)
    n = sum(int(ln["quantity"]) for ln in cart)
    added = (ctx.tr("Added. Your cart: 1 item, {amount}.", amount=_inr(priced["subtotal"])) if n == 1 else
             ctx.tr("Added. Your cart: {n} items, {amount}.", n=n, amount=_inr(priced["subtotal"])))
    await ctx.ask(buttons(added, [("o:start", ctx.tr("Add more")), ("o:checkout", ctx.tr("Checkout")),
                                  ("talk_to_person", ctx.tr("Talk to a person"))]))
    return True


async def _stock_location(ctx: Ctx) -> uuid.UUID | None:
    """Orders placed here reserve stock at the primary location (as the website's do)."""
    return (await ctx.session.execute(select(BusinessLocation.id).where(
        BusinessLocation.business_id == ctx.business.id, BusinessLocation.status == "active")
        .order_by(BusinessLocation.is_primary.desc(), BusinessLocation.created_at).limit(1))).scalar()


async def _price_cart(ctx: Ctx, cart: list[dict[str, Any]]) -> dict[str, Any]:
    """Every price from the catalogue now (§12.6: never the cart's)."""
    from platform_core.services.offering_pricing import price_selection

    lines: list[dict[str, Any]] = []
    problems: list[tuple[int, str, int]] = []
    subtotal = Decimal(0)
    demand: dict[tuple[str, str | None], int] = {}
    location_id = await _stock_location(ctx)
    for i, raw in enumerate(cart):
        o = await ctx.session.get(Offering, uuid.UUID(str(raw["offering_id"])))
        if o is None or o.status != "active" or o.deleted_at is not None or o.business_id != ctx.business.id:
            problems.append((i, "gone", 0))
            continue
        v = await ctx.session.get(OfferingVariant, uuid.UUID(str(raw["variant_id"]))) if raw.get("variant_id") else None
        try:
            priced = price_selection(o, v, raw.get("options") or None)
        except PlatformError:
            problems.append((i, "choose", 0))
            continue
        qty = int(raw["quantity"])
        unit = Decimal(str(priced.unit_price))
        label = o.title + (f" — {v.name}" if v else "") + (f" ({priced.title_suffix})" if priced.title_suffix else "")
        if o.track_inventory:
            key = (str(o.id), str(v.id) if v else None)
            record = (await ctx.session.execute(select(InventoryRecord).where(
                InventoryRecord.business_id == ctx.business.id, InventoryRecord.offering_id == o.id,
                InventoryRecord.location_id == location_id, InventoryRecord.owner_customer_id.is_(None),
                InventoryRecord.variant_id == v.id if v else InventoryRecord.variant_id.is_(None))
                .execution_options(populate_existing=True))).scalars().first()
            available = max(record.quantity_on_hand - record.quantity_reserved, 0) if record else 0
            per = max(int(priced.stock_per_unit or 1), 1)
            can = max((available - demand.get(key, 0)) // per, 0)
            if can < qty:
                problems.append((i, "few" if can else "none", can))
            demand[key] = demand.get(key, 0) + min(qty, can) * per
        total = unit * qty
        subtotal += total
        lines.append({"i": i, "label": label, "qty": qty, "unit": unit, "total": total})
    return {"lines": lines, "problems": problems, "subtotal": subtotal}


async def order_checkout(ctx: Ctx, arg: str) -> bool:
    from platform_core.services.fulfilment import FulfilmentService

    cart = list(ctx.j.get("cart") or [])
    if not cart:
        await ctx.say(ctx.tr("Your cart is empty."))
        return await order_start(ctx, "")
    priced = await _price_cart(ctx, cart)
    if priced["problems"]:
        return await _fix_problems(ctx, priced)
    if not ctx.j.get("due") and await _ask_due(ctx, priced):
        return True
    modes = [m for m in await FulfilmentService.active_modes(ctx.session, ctx.business.id)
             if m in ("delivery", "pickup")]
    if not modes:
        await ctx.ask(buttons(ctx.tr("We can't take orders here right now."),
                              [("talk_to_person", ctx.tr("Talk to a person"))]))
        return True
    ctx.save(modes=modes)
    if len(modes) == 1:
        return await order_mode(ctx, modes[0])
    await ctx.ask(buttons(_cart_text(ctx, priced) + "\n\n" + ctx.tr("Delivery or pickup?"),
                          [("o:mode:delivery", ctx.tr("Delivery")), ("o:mode:pickup", ctx.tr("Pickup"))]))
    return True


async def _preorder_plan(ctx: Ctx, priced: dict[str, Any], wanted: Any = None) -> tuple[Any, Any]:
    """The same pre-order answer the website and a phone order get (P1-10D2)."""
    from platform_core.orders import preorder as po

    cart = list(ctx.j.get("cart") or [])
    location = await ctx.session.get(BusinessLocation, await _stock_location(ctx))
    lines = await po.lines_for(ctx.session, ctx.business.id, [
        (uuid.UUID(str(cart[ln["i"]]["offering_id"])), ln["qty"], ln["total"]) for ln in priced["lines"]])
    zone = po.zone_of(location)
    plan = await po.plan(ctx.session, business_id=ctx.business.id, location=location, lines=lines,
                         requested=po.parse_requested(wanted, zone) if wanted else None, require=False)
    return plan, zone


async def _ask_due(ctx: Ctx, priced: dict[str, Any]) -> bool:
    """Items made to order need a day (and a time when there is a choice)."""
    plan, _ = await _preorder_plan(ctx, priced)
    if not plan.offered:
        return False
    rows = [(f"o:due:{d['date']}", _date_label(ctx, d), ", ".join(_hour(t, ctx.lang) for t in d["times"]))
            for d in plan.dates if not d["full"]][:9]
    if not plan.needed:
        rows.insert(0, ("o:due:-", ctx.tr("As soon as possible"), ""))
    if not rows:
        await ctx.ask(buttons(ctx.tr("No day is open for these items right now."),
                              [("talk_to_person", ctx.tr("Talk to a person")), ("o:start", ctx.tr("Change the cart"))]))
        return True
    head = ctx.tr("When do you need it?")
    if plan.earliest:
        from platform_core.messaging.words import when_words

        head += " " + ctx.tr("Earliest: {when}.", when=when_words(plan.earliest.astimezone(_), datetime.now(_).date(),
                                                                   ctx.lang)) if ctx.lang != "en" else \
            f" Earliest: {plan.public(_)['earliest_words']}."
    await ctx.ask(listing(head, ctx.tr("Days"), rows))
    return True


def _hour(hhmm: str, lang: str = "en") -> str:
    said: str = clock(time.fromisoformat(hhmm), lang)
    return said


def _date_label(ctx: Ctx, d: dict[str, Any]) -> str:
    """The pre-order planner's day label, in the customer's language."""
    if ctx.lang == "en":
        return str(d["label"])
    day = date.fromisoformat(d["date"])
    today = datetime.now(IST).date()
    return ctx.tr("Today") if day == today else ctx.tr("Tomorrow") if (day - today).days == 1 else day_words(day, ctx.lang)


async def order_due(ctx: Ctx, arg: str) -> bool:
    if arg == "-":
        ctx.save(due="asap")
        return await order_checkout(ctx, "")
    priced = await _price_cart(ctx, list(ctx.j.get("cart") or []))
    plan, _ = await _preorder_plan(ctx, priced)
    day = next((d for d in plan.dates if d["date"] == arg and not d["full"]), None)
    if day is None:
        await ctx.say(ctx.tr("That day is not open any more."))
        return await _ask_due(ctx, priced)
    if len(day["times"]) == 1:
        ctx.save(due={"date": arg, "time": day["times"][0]})
        return await order_checkout(ctx, "")
    await ctx.ask(listing(ctx.tr("{day}: what time?", day=_date_label(ctx, day)), ctx.tr("Times"),
                          [(f"o:dtime:{arg}T{t}", _hour(t, ctx.lang), "") for t in day["times"][:10]]))
    return True


async def order_due_time(ctx: Ctx, arg: str) -> bool:
    day, _, at = arg.partition("T")
    ctx.save(due={"date": day, "time": at})
    return await order_checkout(ctx, "")


def _cart_text(ctx: Ctx, priced: dict[str, Any], charge: Decimal = Decimal(0)) -> str:
    lines = [f"{ln['qty']} × {ln['label']} — {_inr(ln['total'])}" for ln in priced["lines"]]
    if charge:
        lines.append(ctx.tr("Delivery — {amount}", amount=_inr(charge)))
    lines.append(ctx.tr("Total {amount}", amount=_inr(priced["subtotal"] + charge)))
    return "\n".join(lines)


async def _fix_problems(ctx: Ctx, priced: dict[str, Any]) -> bool:
    cart = list(ctx.j.get("cart") or [])
    i, what, can = priced["problems"][0]
    o = await ctx.session.get(Offering, uuid.UUID(str(cart[i]["offering_id"])))
    name = o.title if o else ctx.tr("An item")
    opts = [("o:drop:" + str(i), ctx.tr("Remove it"))]
    if can:
        opts.insert(0, (f"o:fix:{i}:{can}", ctx.tr("Make it {n}", n=can)))
    opts.append(("talk_to_person", ctx.tr("Talk to a person")))
    said = {"gone": ctx.tr("{name} is no longer available.", name=name),
            "choose": ctx.tr("{name} needs choosing again.", name=name),
            "few": ctx.tr("{name} has only {n} left.", name=name, n=can),
            "none": ctx.tr("{name} is out of stock.", name=name)}[what]
    await ctx.ask(buttons(said, opts))
    return True


async def order_fix(ctx: Ctx, arg: str) -> bool:
    i, n = (int(x) for x in arg.split(":"))
    cart = list(ctx.j.get("cart") or [])
    if 0 <= i < len(cart):
        cart[i] = {**cart[i], "quantity": n}
    ctx.save(cart=cart)
    return await order_checkout(ctx, "")


async def order_drop(ctx: Ctx, arg: str) -> bool:
    cart = list(ctx.j.get("cart") or [])
    i = int(arg)
    if 0 <= i < len(cart):
        cart.pop(i)
    ctx.save(cart=cart)
    return await order_checkout(ctx, "")


async def _last_address(ctx: Ctx) -> dict[str, Any] | None:
    if ctx.contact is None:
        return None
    row = (await ctx.session.execute(select(FulfilmentJob.delivery_address).join(
        SalesOrder, SalesOrder.id == FulfilmentJob.order_id).where(
        FulfilmentJob.business_id == ctx.business.id, SalesOrder.customer_contact_id == ctx.contact.id,
        FulfilmentJob.mode == "delivery", FulfilmentJob.delivery_address.is_not(None))
        .order_by(FulfilmentJob.created_at.desc()).limit(1))).scalar()
    return dict(row) if row else None


async def order_mode(ctx: Ctx, arg: str) -> bool:
    if arg not in (ctx.j.get("modes") or ["pickup"]):
        return await order_checkout(ctx, "")
    ctx.save(mode=arg)
    if arg == "pickup":
        ctx.save(address=None)
        return await _payment(ctx)
    last = await _last_address(ctx)
    if last:
        ctx.save(last_address=last)
        await ctx.ask(buttons(ctx.tr("Deliver to {address}?", address=_t(_address_words(ctx, last), 180)),
                              [("o:addr:last", ctx.tr("Yes, same address")), ("o:addr:new", ctx.tr("New address"))]))
        return True
    return await order_address(ctx, "new")


def _address_words(ctx: Ctx, a: dict[str, Any]) -> str:
    line1 = str(a.get("line1") or "")
    parts = [line1, *(str(a[k]) for k in ("city", "postal_code") if a.get(k) and str(a[k]) not in line1)]
    words = ", ".join(p for p in parts if p)
    return words or (ctx.tr("Location pin") if a.get("lat") is not None else ctx.tr("your address"))


async def order_address(ctx: Ctx, arg: str) -> bool:
    if arg == "last" and ctx.j.get("last_address"):
        return await _use_address(ctx, dict(ctx.j["last_address"]))
    ctx.save(step="address")
    await ctx.say(ctx.tr("Send your location pin (tap + → Location), or type your address with its PIN code."))
    return True


async def _address_pin(ctx: Ctx, extra: dict[str, Any]) -> bool:
    lat, lng = extra.get("latitude"), extra.get("longitude")
    if lat is None or lng is None:
        return False
    return await _use_address(ctx, {"lat": float(lat), "lng": float(lng),
                                    "line1": " ".join(str(x) for x in (extra.get("name"), extra.get("address")) if x)
                                    or None})


async def _address_typed(ctx: Ctx, said: str) -> bool:
    pin = re.search(r"\b(\d{6})\b", said)
    if len(said) < 8:
        await ctx.say(ctx.tr("Type the full address with its PIN code, or send your location pin."))
        return True
    city = None
    parts = [p.strip() for p in re.split(r"[,\n]", said) if p.strip()]
    if len(parts) > 1:
        city = re.sub(r"\d{6}", "", parts[-1]).strip(" -") or (parts[-2] if len(parts) > 2 else None)
    return await _use_address(ctx, {"line1": said[:300], "postal_code": pin.group(1) if pin else None, "city": city})


async def _use_address(ctx: Ctx, address: dict[str, Any]) -> bool:
    from platform_core.services.fulfilment import FulfilmentService

    zone, charge = await FulfilmentService.match_zone(ctx.session, business_id=ctx.business.id, address=address)
    if zone is None:
        ctx.save(step=None)
        opts = [("o:mode:pickup", ctx.tr("Pickup instead"))] if "pickup" in (ctx.j.get("modes") or []) else []
        await ctx.ask(buttons(ctx.tr("Sorry — we don't deliver there yet."),
                              [*opts, ("o:addr:new", ctx.tr("Another address")),
                               ("talk_to_person", ctx.tr("Talk to a person"))]))
        return True
    ctx.save(address=address, charge=str(charge), step=None)
    return await _payment(ctx)


async def _is_first_order(ctx: Ctx) -> bool:
    if ctx.contact is None:
        return True
    return not (await ctx.session.execute(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.business_id == ctx.business.id, SalesOrder.customer_contact_id == ctx.contact.id,
        SalesOrder.deleted_at.is_(None), SalesOrder.status.notin_(("cancelled", "rejected"))))).scalar_one()


async def _payment(ctx: Ctx) -> bool:
    from platform_core.services.fulfilment import FulfilmentService

    rules = await FulfilmentService.payment_rules(ctx.session, ctx.business.id)
    cap = rules["first_order_cap"]
    priced = await _price_cart(ctx, list(ctx.j.get("cart") or []))
    charge = Decimal(str(ctx.j.get("charge") or 0)) if ctx.j.get("mode") == "delivery" else Decimal(0)
    total = priced["subtotal"] + charge
    if not rules["on_delivery"]:
        await ctx.ask(buttons(ctx.tr("Paying online on WhatsApp is not available yet. A person will help you finish "
                                     "this order."),
                              [("talk_to_person", ctx.tr("Talk to a person")), ("menu", ctx.tr("Menu"))]))
        return True
    if cap is not None and await _is_first_order(ctx) and total > Decimal(str(cap)):
        await ctx.ask(buttons(ctx.tr("For a first order, cash on delivery is up to {amount}. A person will help you "
                                     "pay for this one.", amount=_inr(Decimal(str(cap)))),
                              [("talk_to_person", ctx.tr("Talk to a person")), ("o:start", ctx.tr("Change the cart"))]))
        return True
    ctx.save(pay="cod", confirmed_total=str(total))
    delivering = ctx.j.get("mode") == "delivery"
    where = ctx.tr("Deliver to {address}", address=_t(_address_words(ctx, ctx.j.get("address") or {}), 120)) \
        if delivering else ctx.tr("Pickup")
    pay = ctx.tr("Pay on delivery") if delivering else ctx.tr("Pay at pickup")
    wanted = ctx.j.get("due") if isinstance(ctx.j.get("due"), dict) else None
    ahead = ""
    if wanted:
        plan, zone = await _preorder_plan(ctx, priced, wanted)
        from platform_core.messaging import words
        from platform_core.orders.preorder import when_words

        if plan.due_at:
            ready = when_words(plan.due_at, zone) if ctx.lang == "en" else words.when_words(
                plan.due_at.astimezone(zone), datetime.now(zone).date(), ctx.lang)
            ahead = "\n" + ctx.tr("Ready: {when}", when=ready)
        if plan.advance > 0:
            ahead += "\n" + ctx.tr("Advance {amount} now (a link to pay it follows), the rest on delivery." if delivering
                                   else "Advance {amount} now (a link to pay it follows), the rest at pickup.",
                                   amount=_inr(plan.advance))
    await ctx.ask(buttons(f"{_cart_text(ctx, priced, charge)}\n{where} · {pay}{ahead}\n\n{ctx.tr('Place this order?')}",
                          [("o:place", ctx.tr("Place order")), ("o:start", ctx.tr("Change")),
                           ("o:clear", ctx.tr("Cancel"))]))
    return True


async def order_place(ctx: Ctx, arg: str) -> bool:
    from platform_core.services.checkout import CheckoutService

    j = ctx.j
    if not j.get("cart") or not j.get("confirmed_total"):
        if j.get("last_order"):
            await ctx.say(ctx.tr("Your order {number} is already placed.", number=j["last_order"]))
            return True
        return await menu(ctx)
    priced = await _price_cart(ctx, list(j["cart"]))
    if priced["problems"]:
        return await _fix_problems(ctx, priced)
    charge = Decimal(str(j.get("charge") or 0)) if j.get("mode") == "delivery" else Decimal(0)
    total = priced["subtotal"] + charge
    if total != Decimal(str(j["confirmed_total"])):
        # §12.4: prices only from LOCAH, and the customer confirms what they pay.
        ctx.save(confirmed_total=str(total))
        await ctx.ask(buttons(f"{ctx.tr('A price changed since your summary.')}\n{_cart_text(ctx, priced, charge)}"
                              f"\n\n{ctx.tr('Place it at this total?')}",
                              [("o:place", ctx.tr("Place order")), ("o:clear", ctx.tr("Cancel"))]))
        return True
    contact = ctx.contact
    if contact is None:
        return False
    try:
        result = await CheckoutService.place_for_contact(
            ctx.session, business=ctx.business, contact=contact,
            correlation_id=str(uuid.uuid4()), actor_context="whatsapp",
            payload={"items": [{k: v for k, v in line.items() if k in ("offering_id", "variant_id", "options",
                                                                          "quantity")} for line in j["cart"]],
                     "fulfilment_mode": j.get("mode") or "pickup", "payment_method": "cod",
                     "delivery_address": j.get("address") if j.get("mode") == "delivery" else None,
                     "due": j.get("due") if isinstance(j.get("due"), dict) else None,
                     "idempotency_key": f"wa-{ctx.conv.id}-{j.get('cart_id')}", "channel": "whatsapp"})
    except PlatformError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        await ctx.ask(buttons(ctx.tr("That did not go through: {reason}.", reason=detail.get("message") or exc.code),
                              [("o:checkout", ctx.tr("Try again")), ("talk_to_person", ctx.tr("Talk to a person"))]))
        return True
    from platform_core.site_urls import business_site_url

    order = result["order"]
    track = business_site_url(ctx.business.slug, f"/track/{order['id']}?token={result['tracking']['token']}")
    ctx.save(cart=None, cart_id=None, pending=None, confirmed_total=None, charge=None, address=None, mode=None,
             modes=None, last_address=None, pay=None, cat=None, due=None, last_order=order["order_number"])
    await ctx.say(ctx.tr("Order {number} placed for {amount}. {business} will confirm it here. Follow it: {link}",
                         number=order["order_number"], amount=_inr(order["total_amount"]),
                         business=ctx.business.display_name, link=ctx.link(track)))
    if result.get("advance"):
        await ctx.say(ctx.tr("Please pay the {amount} advance here: {link}", amount=_inr(result["advance"]["amount"]),
                             link=ctx.link(result["advance"]["url"])))
    return True


async def order_clear(ctx: Ctx, arg: str) -> bool:
    ctx.save(cart=None, cart_id=None, pending=None, confirmed_total=None, charge=None, address=None, mode=None,
             step=None, due=None)
    await ctx.say(ctx.tr("Cart cleared. Send menu any time."))
    return True


# ---------------------------------------------------------------- book
async def book_start(ctx: Ctx, arg: str) -> bool:
    services = await _bookable(ctx.session, ctx.business.id)
    if "bookings" not in ctx.live or not services:
        await ctx.say(ctx.tr("Booking on WhatsApp is not available right now. Tap Talk to a person, or send menu."))
        return True
    ctx.conv.topic = "booking"
    ctx.save(booking_key=uuid.uuid4().hex, step=None)
    await ctx.ask(listing(ctx.tr("What would you like to book?"), ctx.tr("Services"),
                          [(f"b:svc:{o.id}", o.title, _svc_words(ctx, o)) for o in services[:10]]))
    return True


def _svc_words(ctx: Ctx, o: Offering) -> str:
    mins = (o.attributes or {}).get("duration_minutes")
    return " · ".join(x for x in (_inr(o.price_amount) if o.price_amount is not None else "",
                                  ctx.tr("{n} min", n=mins) if mins else "") if x)


async def book_service(ctx: Ctx, arg: str) -> bool:
    locations = list((await ctx.session.execute(select(BusinessLocation).where(
        BusinessLocation.business_id == ctx.business.id, BusinessLocation.status == "active")
        .order_by(BusinessLocation.is_primary.desc(), BusinessLocation.name))).scalars())
    ctx.save(service=arg)
    if len(locations) > 1 and not ctx.j.get("location"):
        await ctx.ask(listing(ctx.tr("Where?"), ctx.tr("Locations"),
                              [(f"b:loc:{loc.id}", loc.name, "") for loc in locations[:10]]))
        return True
    if locations:
        ctx.save(location=str(locations[0].id))
    return await _days(ctx)


async def book_location(ctx: Ctx, arg: str) -> bool:
    ctx.save(location=arg)
    return await _days(ctx)


async def _days(ctx: Ctx) -> bool:
    today = datetime.now(IST).date()
    rows = []
    for d in range(8):
        day = today + timedelta(days=d)
        rows.append((f"b:day:{day.isoformat()}", ctx.tr("Today") if d == 0 else ctx.tr("Tomorrow") if d == 1
                     else day_words(day, ctx.lang), ""))
    await ctx.ask(listing(ctx.tr("Which day?"), ctx.tr("Days"), rows))
    return True


def _hours_for(location: BusinessLocation, day: date) -> list[tuple[time, time]]:
    """Opening hours saved as {"mon": [["09:00", "18:00"]], ...} (Locations › Opening hours)."""
    hours = location.hours or {}
    key = day.strftime("%a").lower()[:3]
    out = []
    for span in hours.get(key) or []:
        try:
            out.append((time.fromisoformat(span[0]), time.fromisoformat(span[1])))
        except (ValueError, TypeError, IndexError):
            continue
    return out


async def _free(ctx: Ctx, service: Offering, location_id: uuid.UUID, start: datetime) -> list[str] | None:
    """The same check the website's booking page makes: None when the time is
    taken; otherwise the resource to hold (a chair, a room), or [] when the
    business allocates none."""
    from platform_core.services.availability import AvailabilityService
    from platform_core.services.booking_allocation import BookingAllocationService
    from platform_core.validation.booking import validate_availability_query

    mins = int((service.attributes or {}).get("duration_minutes") or 30)
    try:
        params = validate_availability_query({"location_id": str(location_id), "offering_id": str(service.id),
                                              "reservation_mode": "appointment", "starts_at": start.isoformat(),
                                              "ends_at": (start + timedelta(minutes=mins)).isoformat(),
                                              "party_size": 1})
        result = await AvailabilityService.check_availability(ctx.session, business_id=ctx.business.id, params=params)
    except PlatformError:
        return None
    if not result.get("available"):
        return None
    free = await BookingAllocationService.free_resources(
        ctx.session, business_id=ctx.business.id, location_id=location_id, resource_type=None,
        starts_at=params["starts_at"], ends_at=params["ends_at"], party_size=1, mode="appointment",
        offering_id=service.id)
    if free:
        return [str(free[0]["resource_id"])]
    if await BookingAllocationService.has_resources(ctx.session, business_id=ctx.business.id, location_id=location_id,
                                                    mode="appointment"):
        return None
    return []


async def book_day(ctx: Ctx, arg: str) -> bool:
    service = await ctx.session.get(Offering, uuid.UUID(str(ctx.j.get("service"))))
    location = await ctx.session.get(BusinessLocation, uuid.UUID(str(ctx.j.get("location"))))
    if service is None or location is None:
        return await book_start(ctx, "")
    day = date.fromisoformat(arg)
    ctx.save(day=arg)
    spans = _hours_for(location, day)
    if not spans:
        ctx.save(step="time")
        await ctx.say(ctx.tr("What time on {day}? Type it like 5:30 pm.", day=day_words(day, ctx.lang)))
        return True
    mins = int((service.attributes or {}).get("duration_minutes") or 30)
    step = timedelta(minutes=30 if mins <= 60 else 60)  # times on the half hour, or the hour for long ones
    earliest = datetime.now(timezone.utc) + timedelta(minutes=30)
    rows: list[tuple[str, str, str]] = []
    for open_at, close_at in spans:
        at = datetime.combine(day, open_at, IST)
        end = datetime.combine(day, close_at, IST)
        while at + timedelta(minutes=mins) <= end and len(rows) < 10:
            if at >= earliest and await _free(ctx, service, location.id, at) is not None:
                rows.append((f"b:slot:{at.astimezone(timezone.utc).isoformat()}", _slot_time(ctx, at), ""))
            at += step
    if not rows:
        await ctx.ask(buttons(ctx.tr("No free times on {day}.", day=day_words(day, ctx.lang)),
                              [("m:book", ctx.tr("Another day")), ("talk_to_person", ctx.tr("Talk to a person"))]))
        return True
    await ctx.ask(listing(ctx.tr("Free times on {day}:", day=day_words(day, ctx.lang)), ctx.tr("Times"), rows))
    return True


def _slot_time(ctx: Ctx, at: datetime) -> str:
    """"5:30 PM" (as before) / "மாலை 5:30" / "शाम 5:30"."""
    local = at.astimezone(IST)
    return local.strftime("%I:%M %p").lstrip("0") if ctx.lang == "en" else clock(local.time(), ctx.lang)


async def _time_typed(ctx: Ctx, said: str) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*", said.lower())
    if not m or not ctx.j.get("day"):
        await ctx.say(ctx.tr("Type the time like 5:30 pm."))
        return True
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and hour < 12:
        hour += 12
    if m.group(3) == "am" and hour == 12:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        await ctx.say(ctx.tr("Type the time like 5:30 pm."))
        return True
    at = datetime.combine(date.fromisoformat(ctx.j["day"]), time(hour, minute), IST)
    ctx.save(step=None)
    return await book_slot(ctx, at.astimezone(timezone.utc).isoformat())


async def book_slot(ctx: Ctx, arg: str) -> bool:
    service = await ctx.session.get(Offering, uuid.UUID(str(ctx.j.get("service"))))
    location_id = uuid.UUID(str(ctx.j.get("location")))
    at = datetime.fromisoformat(arg)
    if service is None:
        return await book_start(ctx, "")
    if at < datetime.now(timezone.utc) or await _free(ctx, service, location_id, at) is None:
        await ctx.ask(buttons(ctx.tr("That time is not free."),
                              [(f"b:day:{at.astimezone(IST).date().isoformat()}", ctx.tr("Other times")),
                               ("talk_to_person", ctx.tr("Talk to a person"))]))
        return True
    ctx.save(slot=arg)
    local = at.astimezone(IST)
    await ctx.ask(buttons(ctx.tr("{service} on {day} at {time}. Confirm?", service=service.title,
                                 day=day_words(local.date(), ctx.lang), time=_slot_time(ctx, at)),
                          [("b:confirm", ctx.tr("Confirm")), (f"b:day:{local.date().isoformat()}", ctx.tr("Other time")),
                           ("talk_to_person", ctx.tr("Talk to a person"))]))
    return True


async def book_confirm(ctx: Ctx, arg: str) -> bool:
    from platform_core.services.booking import BookingService

    j = ctx.j
    if not (j.get("service") and j.get("slot") and j.get("location")) or ctx.contact is None:
        return await book_start(ctx, "")
    service = await ctx.session.get(Offering, uuid.UUID(str(j["service"])))
    at = datetime.fromisoformat(j["slot"])
    assert service is not None
    hold = await _free(ctx, service, uuid.UUID(str(j["location"])), at)
    if hold is None:
        return await book_slot(ctx, j["slot"])  # §12.4: re-checked at confirm, alternatives offered
    mins = int((service.attributes or {}).get("duration_minutes") or 30)
    try:
        booking = await BookingService.create_booking(
            ctx.session, business_id=ctx.business.id, actor_id=ctx.business.primary_owner_identity_id,
            correlation_id=str(uuid.uuid4()),
            payload={"location_id": str(j["location"]), "customer_contact_id": str(ctx.contact.id),
                     "offering_id": str(service.id), "reservation_mode": "appointment",
                     "starts_at": at.isoformat(), "ends_at": (at + timedelta(minutes=mins)).isoformat(),
                     "party_size": 1, "payment_method": "pay_at_business", "channel": "whatsapp",
                     "resource_ids": hold or None,
                     "idempotency_key": f"wa-{ctx.conv.id}-{j.get('booking_key')}"},
            allow_capacity_override=False, assign_free_resource=True, enforce_opening_hours=True)
    except PlatformError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        await ctx.ask(buttons(ctx.tr("That did not go through: {reason}.", reason=detail.get("message") or exc.code),
                              [("m:book", ctx.tr("Try again")), ("talk_to_person", ctx.tr("Talk to a person"))]))
        return True
    local = at.astimezone(IST)
    ctx.save(service=None, slot=None, day=None, location=None, booking_key=None, step=None)
    day, when = day_words(local.date(), ctx.lang), _slot_time(ctx, at)
    await ctx.say(ctx.tr("Booking {number}: {service} on {day} at {time}. It's confirmed.",
                         number=booking.booking_number, service=service.title, day=day, time=when)
                  if booking.status == "confirmed" else
                  ctx.tr("Booking {number}: {service} on {day} at {time}. {business} will confirm it here.",
                         number=booking.booking_number, service=service.title, day=day, time=when,
                         business=ctx.business.display_name))
    return True


# ---------------------------------------------------------------- enquire
async def enquire_start(ctx: Ctx, arg: str) -> bool:
    if "leads" not in ctx.live:
        return False
    ctx.conv.topic = "lead"
    ctx.save(step="enquiry")
    await ctx.say(ctx.tr("What would you like to know? Type your question and we'll get back to you here."))
    return True


async def _enquiry_typed(ctx: Ctx, said: str) -> bool:
    from platform_core.services.lead import LeadService

    if len(said) < 3:
        await ctx.say(ctx.tr("Type your question in a few words."))
        return True
    contact = ctx.contact
    await LeadService.create_lead(
        ctx.session, business_id=ctx.business.id, actor_id=ctx.business.primary_owner_identity_id,
        correlation_id=str(uuid.uuid4()), actor_context="whatsapp",
        payload={"display_name": contact.display_name if contact else f"+{ctx.conv.wa_id}",
                 "phone": f"+{ctx.conv.wa_id}", "message": said[:1000], "source": "whatsapp",
                 "origin_context": {"channel": "whatsapp", "conversation_id": str(ctx.conv.id)}})
    from platform_core.services.messaging import MessagingService

    ctx.save(step=None)
    first_wait = ctx.conv.waiting_since is None
    ctx.conv.needs_person, ctx.conv.waiting_since = True, ctx.conv.waiting_since or datetime.now(timezone.utc)
    await ctx.say(ctx.tr("Thanks — {business} has your question and will reply here.", business=ctx.business.display_name))
    if first_wait:
        await MessagingService._schedule_waiting(ctx.session, ctx.conv)
    return True


# ---------------------------------------------------------------- pay / dues, track
async def dues(ctx: Ctx, arg: str) -> bool:
    from platform_core.services.invoicing import InvoiceService, share_token
    from platform_core.services.ledger import LedgerService
    from platform_core.site_urls import business_site_url

    if ctx.contact is None:
        return False
    ctx.conv.topic = "payment"
    lines = []
    acct = (await ctx.session.execute(select(LedgerAccount).where(
        LedgerAccount.business_id == ctx.business.id, LedgerAccount.customer_contact_id == ctx.contact.id))).scalars().first()
    if acct is not None and Decimal(str(acct.balance)) > 0 and "ledger" in ctx.live:
        share = await LedgerService.share(ctx.session, ctx.business.id, acct.id)
        lines.append(ctx.tr("Your account: {amount} due. Details and pay: {link}", amount=_inr(acct.balance),
                            link=ctx.link(business_site_url(ctx.business.slug, "/khata/" + share["token"]))))
    if "invoicing" in ctx.live:
        bills = list((await ctx.session.execute(select(InvoicingDocument).where(
            InvoicingDocument.business_id == ctx.business.id, InvoicingDocument.customer_contact_id == ctx.contact.id,
            InvoicingDocument.status == "issued", InvoicingDocument.on_account.is_(False),
            InvoicingDocument.doc_kind.in_(("tax_invoice", "bill_of_supply", "bill")),
            InvoicingDocument.amount_due > InvoicingDocument.amount_paid)
            .order_by(InvoicingDocument.issue_date).execution_options(skip_location_scope=True))).scalars())
        for b in bills[:5]:
            view = await InvoiceService._money_view(ctx.session, b)
            if view["outstanding"] > 0:
                lines.append(ctx.tr("Bill {number}: {amount} — {link}", number=b.number, amount=_inr(view["outstanding"]),
                                    link=ctx.link(business_site_url(ctx.business.slug,
                                                                    "/bill/" + share_token(ctx.business.id, b.id)))))
    await ctx.say("\n".join(lines) if lines else ctx.tr("Nothing is due. Thank you!"))
    return True


async def track(ctx: Ctx, arg: str) -> bool:
    from platform_core.site_urls import business_site_url

    orders = await _open_orders(ctx)
    if not orders:
        await ctx.say(ctx.tr("You have no open orders with us. Send menu to order."))
        return True
    ctx.conv.topic = "order"
    out = []
    for o in orders[:3]:
        job = (await ctx.session.execute(select(FulfilmentJob).where(FulfilmentJob.order_id == o.id))).scalars().first()
        link = ctx.link(business_site_url(ctx.business.slug, f"/track/{o.id}?token={job.tracking_token}")) if job else None
        out.append(f"{o.order_number}: {_status(ctx, o.status)}" + (f" — {link}" if link else ""))
    await ctx.say("\n".join(out))
    return True


async def reorder(ctx: Ctx, arg: str) -> bool:
    if ctx.contact is None:
        return False
    last = (await ctx.session.execute(select(SalesOrder).where(
        SalesOrder.business_id == ctx.business.id, SalesOrder.customer_contact_id == ctx.contact.id,
        SalesOrder.deleted_at.is_(None)).order_by(SalesOrder.created_at.desc()).limit(1))).scalars().first()
    if last is None:
        return await order_start(ctx, "")
    items = list((await ctx.session.execute(select(OrderLineItem).where(OrderLineItem.order_id == last.id))).scalars())
    cart = []
    for it in items:
        o = await ctx.session.get(Offering, it.offering_id) if it.offering_id else None
        if o is None or o.title == "Delivery fee" or o.status != "active":
            continue
        cart.append({"offering_id": str(o.id), "variant_id": str(it.variant_id) if getattr(it, "variant_id", None) else None,
                     "options": dict(getattr(it, "options", None) or {}), "quantity": int(it.quantity)})
    if not cart:
        await ctx.say(ctx.tr("The items from your last order are not available now."))
        return await order_start(ctx, "")
    ctx.save(cart_id=uuid.uuid4().hex, cart=cart, pending=None)
    ctx.conv.topic = "order"
    await ctx.say(ctx.tr("Your last order ({number}) again, at today's prices:", number=last.order_number))
    return await order_checkout(ctx, "")


# ---------------------------------------------------------------- change / cancel
async def cancel_start(ctx: Ctx, arg: str) -> bool:
    if ctx.contact is None:
        return False
    rows: list[tuple[str, str, str]] = []
    for o in await _open_orders(ctx):
        rows.append((f"c:order:{o.id}", ctx.tr("Order {number}", number=o.order_number), _status(ctx, o.status)))
    for b in await _upcoming_bookings(ctx):
        rows.append((f"c:booking:{b.id}", _t(b.title, 24), _booking_when(ctx, b.starts_at)))
    if not rows:
        await ctx.say(ctx.tr("You have nothing open to change or cancel."))
        return True
    await ctx.ask(listing(ctx.tr("Which one?"), ctx.tr("Choose"),
                          [*rows[:9], ("talk_to_person", ctx.tr("Talk to a person"), ctx.tr("To change it"))]))
    return True


async def cancel_pick(ctx: Ctx, arg: str) -> bool:
    kind, rid = arg.split(":", 1)
    ctx.save(cancel={"kind": kind, "id": rid})
    if kind == "order":
        o = await ctx.session.get(SalesOrder, uuid.UUID(rid))
        if o is None or o.customer_contact_id != (ctx.contact.id if ctx.contact else None):
            return await cancel_start(ctx, "")
        why = _why_not_cancel(o, ctx)
        if why:
            await ctx.ask(buttons(why, [("talk_to_person", ctx.tr("Talk to a person")), ("menu", ctx.tr("Menu"))]))
            return True
        await ctx.ask(buttons(ctx.tr("Cancel order {number}?", number=o.order_number),
                              [("c:yes", ctx.tr("Yes, cancel it")), ("menu", ctx.tr("Keep it"))]))
        return True
    b = await ctx.session.get(Booking, uuid.UUID(rid))
    if b is None or b.customer_contact_id != (ctx.contact.id if ctx.contact else None):
        return await cancel_start(ctx, "")
    await ctx.ask(buttons(ctx.tr("{title} on {when}.", title=b.title, when=_booking_when(ctx, b.starts_at)),
                          [("c:yes", ctx.tr("Cancel it")), ("m:book", ctx.tr("Book another time")),
                           ("talk_to_person", ctx.tr("Talk to a person"))]))
    return True


def _status(ctx: Ctx | None, status: str) -> str:
    words = STATUS_WORDS.get(status, status)
    return ctx.tr(words) if ctx is not None else words


def _booking_when(ctx: Ctx, at: datetime) -> str:
    local = at.astimezone(IST)
    if ctx.lang == "en":
        return local.strftime("%a %d %b, %I:%M %p")
    return f"{day_words(local.date(), ctx.lang)}, {clock(local.time(), ctx.lang)}"


def _why_not_cancel(o: SalesOrder, ctx: Ctx | None = None) -> str | None:
    """A customer cancels an order while it waits to be accepted; an order for a
    day (a pre-order) until the notice its terms gave (P1-10D2)."""
    lang = ctx.lang if ctx is not None else "en"
    hours = (o.preorder_terms or {}).get("cancel_hours") if o.due_at else None
    why: str | None = None
    if o.due_at is not None and hours is not None:
        if o.status not in ("pending", "accepted"):
            why = tr(lang, "Order {number} is already {status}, so it can't be cancelled here.",
                     number=o.order_number, status=_status(ctx, o.status))
        elif datetime.now(timezone.utc) > o.due_at - timedelta(hours=int(hours)):
            why = tr(lang, "It's too close to the day to cancel here ({hours} hours' notice).", hours=hours)
    elif o.status != "pending":
        why = tr(lang, "Order {number} is already {status}, so it can't be cancelled here.",
                 number=o.order_number, status=_status(ctx, o.status))
    return why


async def cancel_yes(ctx: Ctx, arg: str) -> bool:
    from platform_core.services.booking import BookingService
    from platform_core.services.booking_lifecycle import BookingLifecycleService
    from platform_core.services.order_lifecycle import OrderLifecycleService

    what = dict(ctx.j.get("cancel") or {})
    ctx.save(cancel=None)
    if not what:
        return await menu(ctx)
    owner = ctx.business.primary_owner_identity_id
    try:
        if what["kind"] == "order":
            o = await ctx.session.get(SalesOrder, uuid.UUID(what["id"]))
            if o is None or _why_not_cancel(o):
                return await cancel_start(ctx, "")
            await OrderLifecycleService.transition_status(
                ctx.session, business_id=ctx.business.id, order_id=o.id, actor_id=owner,
                correlation_id=str(uuid.uuid4()), payload={"status": "cancelled",
                                                             "reason": "Cancelled by the customer on WhatsApp"})
            await ctx.say(ctx.tr("Order {number} is cancelled.", number=o.order_number))
            return True
        b = await ctx.session.get(Booking, uuid.UUID(what["id"]))
        if b is None:
            return await cancel_start(ctx, "")
        policy = await BookingService.get_or_create_policy(ctx.session, ctx.business.id)
        if datetime.now(timezone.utc) > b.starts_at - timedelta(hours=policy.cancel_window_hours):
            await ctx.ask(buttons(ctx.tr("It's too close to the time to cancel here ({hours} hours' notice).",
                                         hours=policy.cancel_window_hours),
                                  [("talk_to_person", ctx.tr("Talk to a person")), ("menu", ctx.tr("Menu"))]))
            return True
        await BookingLifecycleService.transition_status(
            ctx.session, business_id=ctx.business.id, booking_id=b.id, actor_id=owner,
            correlation_id=str(uuid.uuid4()), payload={"status": "cancelled",
                                                         "reason": "Cancelled by the customer on WhatsApp"})
        await ctx.say(ctx.tr("Your booking {number} is cancelled.", number=b.booking_number))
        return True
    except PlatformError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        await ctx.ask(buttons(ctx.tr("That did not go through: {reason}.", reason=detail.get("message") or exc.code),
                              [("talk_to_person", ctx.tr("Talk to a person"))]))
        return True


ROUTES: list[tuple[str, Any]] = [
    ("m:order", order_start), ("o:start", order_start), ("o:cat", order_category), ("o:page", order_page),
    ("o:item", order_item), ("o:var", order_variant), ("o:pack", order_pack), ("o:opt", order_option), ("o:note", order_note), ("o:due", order_due), ("o:dtime", order_due_time),
    ("o:qty", order_qty), ("o:checkout", order_checkout), ("o:fix", order_fix), ("o:drop", order_drop),
    ("o:mode", order_mode), ("o:addr", order_address), ("o:place", order_place), ("o:clear", order_clear),
    ("m:book", book_start), ("b:svc", book_service), ("b:loc", book_location), ("b:day", book_day),
    ("b:slot", book_slot), ("b:confirm", book_confirm),
    ("m:enquire", enquire_start), ("m:pay", dues), ("m:track", track), ("m:reorder", reorder),
    ("m:cancel", cancel_start), ("c:order", lambda c, a: cancel_pick(c, "order:" + a)),
    ("c:booking", lambda c, a: cancel_pick(c, "booking:" + a)), ("c:yes", cancel_yes),
    ("m:lang", language_ask), ("l", language_set),
]
TEXT_STEPS: dict[str, Any] = {"qty": _qty_typed, "address": _address_typed, "time": _time_typed,
                              "enquiry": _enquiry_typed, "note": _note_typed}
