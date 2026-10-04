"""What LOCAH recommends to THIS Business next, and why — from evidence.

`catalog.recommendation` answers "what do businesses like this run" from the
category and traits. This layer ranks that against what is actually known
about this one Business, in order of how much it should count:

1. **The owner's own words** — the conversation with LOCAH recorded which tools
   it suggested and the sentence that showed the need ("we deliver around
   Anna Nagar").
2. **Their records** — what they list and what customers already do (twelve
   menu items and no way to order them; services people book a time for).
3. **How they said they work** — a trait the owner switched on themselves.
4. **Businesses like theirs** — the category's Core and Recommended lists.

A pure function. It recommends only: it never switches anything on. A tool the
owner put off ("Not now") stays out of the list until a NEW piece of evidence
appears — something they said or something in their records that was not there
when they put it off. Businesses-like-yours evidence never brings one back.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# Evidence kinds, strongest first.
SAID, RECORDS, TRAIT, PROFILE = "said", "records", "trait", "profile"
_WEIGHT = {SAID: 100, RECORDS: 70, TRAIT: 50, PROFILE: 0}
# Profile evidence is weighed by tier: Core outranks the family's "usually add".
_TIER_WEIGHT = {"core": 40, "recommended": 25, "optional": 0, "always": 0}
# A profile pick that also fits how this Business works (one of its traits
# switches the tool on) outranks one that is only common for its kind.
_FIT_BONUS = 15
# Only these can bring back a tool the owner put off.
RESURFACING = frozenset({SAID, RECORDS, TRAIT})


@dataclass(frozen=True)
class Evidence:
    key: str  # stable: "said:orders", "records:sellable", "trait:local_delivery", "profile:core"
    kind: str  # said | records | trait | profile
    text: str  # owner-facing, one sentence

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "kind": self.kind, "text": self.text}


@dataclass(frozen=True)
class Signals:
    """Counts from the Business's own records (see services.module_recommendations)."""

    kinds: Mapping[str, int] = field(default_factory=dict)  # offering_type -> live or draft items
    variants: int = 0  # items with sizes or options
    weighed: int = 0
    tracked: int = 0  # items whose stock is tracked
    orders: int = 0
    bookings: int = 0
    leads: int = 0
    customers: int = 0
    team: int = 1  # active members, owner included
    locations: int = 1


_SELLABLE = ("menu_item", "product", "weighed_product", "package", "digital_product")
_BOOKABLE = ("service", "class_session", "accommodation", "rental")
_NOUN = {
    "menu_item": ("menu item", "menu items"), "product": ("product", "products"),
    "weighed_product": ("item sold by weight", "items sold by weight"), "package": ("package", "packages"),
    "digital_product": ("digital product", "digital products"), "service": ("service", "services"),
    "class_session": ("class", "classes"), "accommodation": ("room", "rooms"), "rental": ("rental", "rentals"),
}


def _count(n: int, kind: str) -> str:
    one, many = _NOUN.get(kind, ("item", "items"))
    return f"{n} {one if n == 1 else many}"


def _biggest(kinds: Mapping[str, int], among: Iterable[str]) -> tuple[str, int]:
    best = max(((k, int(kinds.get(k, 0))) for k in among), key=lambda x: x[1])
    return best


def record_evidence(s: Signals) -> dict[str, list[Evidence]]:
    """module -> evidence from what the Business has actually recorded."""
    out: dict[str, list[Evidence]] = {}

    def add(module: str, key: str, text: str) -> None:
        out.setdefault(module, []).append(Evidence(f"records:{key}", RECORDS, text))

    sell_kind, _ = _biggest(s.kinds, _SELLABLE)
    sellable = sum(int(s.kinds.get(k, 0)) for k in _SELLABLE)
    book_kind, _ = _biggest(s.kinds, _BOOKABLE)
    bookable = sum(int(s.kinds.get(k, 0)) for k in _BOOKABLE)
    if sellable:
        what = _count(sellable, sell_kind) if sellable == int(s.kinds.get(sell_kind, 0)) else f"{sellable} items"
        add("orders", "sellable", f"You list {what} — customers could order "
                                  f"{'it' if sellable == 1 else 'them'} from your website.")
    if bookable:
        what = _count(bookable, book_kind) if bookable == int(s.kinds.get(book_kind, 0)) else f"{bookable} services"
        add("bookings", "bookable", f"You list {what} — customers could pick a time for "
                                    f"{'it' if bookable == 1 else 'them'} online.")
    if s.variants or s.weighed or s.tracked:
        parts = []
        if s.variants:
            parts.append(f"{s.variants} {'item comes' if s.variants == 1 else 'items come'} in sizes or options")
        if s.weighed:
            parts.append(f"{s.weighed} {'is' if s.weighed == 1 else 'are'} sold by weight")
        if s.tracked:
            parts.append(f"{s.tracked} {'has' if s.tracked == 1 else 'have'} stock to watch")
        add("inventory", "stockable", f"{'; '.join(parts)[:1].upper()}{'; '.join(parts)[1:]} — know what's left.")
    if s.orders:
        add("payments", "orders", f"Customers have placed {s.orders} {'order' if s.orders == 1 else 'orders'} — "
                                  "let them pay online at checkout.")
        if s.orders >= 5:
            add("customer-relationships", "orders",
                f"{s.orders} orders so far — keep track of who buys and what they like.")
    if s.bookings and s.team >= 2:
        add("workforce", "bookings", f"{s.bookings} {'booking' if s.bookings == 1 else 'bookings'} and "
                                     f"{s.team} people on your team — choose who takes each one.")
    if s.leads >= 3:
        add("quotes", "leads", f"{s.leads} enquiries came in — answer the serious ones with a quotation.")
    if s.customers >= 20:
        add("loyalty", "customers", f"{s.customers} customers on record — reward the ones who come back.")
    if int(s.kinds.get("class_session", 0)):
        add("attendance", "classes", "You run classes — mark who came to each one.")
    if s.team >= 3:
        add("workforce", "team", f"{s.team} people work here — plan who is on and when.")
    return out


def _said(interview: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[Evidence]], set[str]]:
    """module -> evidence from the conversation; and the tools the owner declined there."""
    out: dict[str, list[Evidence]] = {}
    declined: set[str] = set()
    for rec in interview:
        module = str(rec.get("module_id") or "")
        if not module:
            continue
        if rec.get("choice") == "declined":
            declined.add(module)
        if rec.get("strength") == "dependency":
            continue
        quotes = [e for e in rec.get("evidence") or [] if e.get("kind") in ("owner_said", "answer")]
        if quotes:
            text = str(quotes[0].get("text") or "").strip()
            line = f"You said “{text}”." if quotes[0].get("kind") == "owner_said" else text
        else:
            line = str(rec.get("reason") or "").strip()
        if line:
            out.setdefault(module, []).append(Evidence(f"said:{module}", SAID, line))
    return out, declined


def trait_evidence(added_traits: Iterable[str], triggered: Mapping[str, str],
                   labels: Mapping[str, str]) -> dict[str, list[Evidence]]:
    """module -> evidence from traits the OWNER switched on (not the category defaults).

    `triggered` maps module -> the trait that switches it on (from the trait rules)."""
    added = set(added_traits)
    out: dict[str, list[Evidence]] = {}
    for module, trait in triggered.items():
        if trait in added:
            label = labels.get(trait, trait)
            out.setdefault(module, []).append(Evidence(f"trait:{trait}", TRAIT, f"You told LOCAH: “{label}”."))
    return out


def _profile_weight(e: Evidence) -> int:
    if e.kind != PROFILE:
        return 0
    parts = e.key.split(":")
    return _TIER_WEIGHT.get(parts[1], 0) + (_FIT_BONUS if parts[-1] == "fit" else 0)


@dataclass
class Suggestion:
    module: str
    score: int
    evidence: list[Evidence]
    resurfaced: bool = False

    @property
    def reason(self) -> str:
        return self.evidence[0].text if self.evidence else ""


def rank(
    *,
    picks: Iterable[Mapping[str, Any]],
    said: Iterable[Mapping[str, Any]],
    records: Mapping[str, list[Evidence]],
    traits: Mapping[str, list[Evidence]],
    enabled: Iterable[str],
    built: Iterable[str],
    dismissed: Mapping[str, Iterable[str]],
    limit: int | None = None,
) -> tuple[list[Suggestion], dict[str, list[Evidence]], set[str]]:
    """(what to suggest now, best first; every module's evidence; modules put off).

    `picks` are `catalog.recommendation` picks (module, tier, reason);
    `dismissed` maps a module the owner put off to the evidence keys known then.
    """
    said_ev, declined = _said(said)
    evidence: dict[str, list[Evidence]] = {}
    tiers: dict[str, str] = {}
    for p in picks:
        module, tier = str(p["module"]), str(p["tier"])
        tiers[module] = tier
        if tier in ("core", "recommended"):
            key = f"profile:{tier}" + (":fit" if p.get("fit") else "")
            evidence.setdefault(module, []).append(Evidence(key, PROFILE, str(p["reason"])))
    for source in (said_ev, records, traits):
        for module, items in source.items():
            evidence.setdefault(module, []).extend(items)
    on, real = set(enabled), set(built)
    put_off: set[str] = set()
    out: list[Suggestion] = []
    for module, items in evidence.items():
        if module in on or module not in real or tiers.get(module) == "always":
            continue
        items = sorted(items, key=lambda e: -(_WEIGHT[e.kind] + _profile_weight(e)))
        evidence[module] = items
        score = sum(_WEIGHT[e.kind] for e in items) + max((_profile_weight(e) for e in items), default=0)
        if score < _TIER_WEIGHT["recommended"]:
            continue
        resurfaced = False
        known = dismissed.get(module)
        if known is None and module in declined:
            known = [e.key for e in items if e.kind == SAID]  # declined in the conversation
        if known is not None:
            new = [e for e in items if e.kind in RESURFACING and e.key not in set(known)]
            if not new:
                put_off.add(module)
                continue
            resurfaced = True
            items = new + [e for e in items if e not in new]
        out.append(Suggestion(module, score, items, resurfaced))
    # Equal scores: a tool another suggestion builds on first (Pickup & delivery
    # before Dispatch), then one that fits how the Business works before one
    # that is only common for its kind.
    from platform_core.catalog.modules import MODULES

    suggested = {s.module for s in out}
    needed = {m: sum(1 for o in suggested if MODULES.get(o) and m in MODULES[o].depends_on) for m in suggested}
    out.sort(key=lambda s: (-s.score, -needed[s.module], not any(e.key.endswith(":fit") for e in s.evidence),
                            s.module))
    return (out[:limit] if limit else out), evidence, put_off
