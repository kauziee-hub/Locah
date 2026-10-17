"""The owner's first afternoon in the Workspace, after "Build my website".

    uv run python -m platform_testing.certify.setup <run_dir> <site_key>

Every tool the owner kept is made operational through the same calls the
Workspace makes, so that a customer can really order, book, join or enquire
(customer.py). Nothing is written to the database directly: if a call the
Workspace relies on refuses, that is a finding, recorded in setup.json.

  catalogue    the interview's "Set up my items" (private, unpriced drafts),
               then each item published and priced as the owner priced it
               (owners.CATALOGUES — what this owner would type in)
  orders       pickup on; delivery and one zone when the owner delivers
  inventory    opening stock for every product
  bookings     the owner as the provider, their week, their services; a
               restaurant's tables as bookable resources
  memberships  the owner's plans, live
  invoicing    unregistered profile, a register at the main location

Reads <run>/sites/<site_key>/journey.json, writes setup.json beside it.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

from platform_testing.certify.journey import API, SECRET, WEB

# Weekdays 0 (Monday) to 5 (Saturday), 10:00-19:00: a small business's week.
WEEK = range(0, 6)
OPENS, CLOSES = "10:00", "19:00"


@dataclass
class Setup:
    site_key: str
    business_id: str = ""
    location_id: str = ""
    offerings: list[dict[str, Any]] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)
    provider_id: str = ""
    resources: list[str] = field(default_factory=list)
    fulfilment: dict[str, Any] = field(default_factory=dict)
    stocked: int = 0
    invoicing: bool = False
    ready: dict[str, Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def save(self, folder: Path) -> None:
        (folder / "setup.json").write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1),
                                           encoding="utf-8")


def owner_token(owner_id: str, email: str) -> str:
    """A fresh local session for the journey's own owner (never stored)."""
    exp = datetime.now(timezone.utc) + timedelta(hours=6)
    return jwt.encode({"sub": owner_id, "email": email, "aud": "authenticated", "role": "authenticated",
                       "exp": exp}, SECRET, algorithm="HS256")


class Workspace:
    """The owner's Workspace, as JSON calls; every call is recorded."""

    def __init__(self, token: str, setup: Setup) -> None:
        self.client = httpx.AsyncClient(base_url=API, timeout=120,
                                        headers={"Authorization": f"Bearer {token}"})
        self.setup = setup

    async def call(self, method: str, path: str, body: dict[str, Any] | None = None,
                   *, expect: bool = True) -> tuple[int, Any]:
        res = await self.client.request(method, path, json=body)
        try:
            data: Any = res.json()
        except ValueError:
            data = res.text[:300]
        self.setup.calls.append({"call": f"{method} {path}", "status": res.status_code})
        if expect and res.status_code >= 400:
            message = data.get("error", data) if isinstance(data, dict) else data
            self.setup.findings.append(f"{method} {path} → {res.status_code} {str(message)[:240]}")
        return res.status_code, data

    async def close(self) -> None:
        await self.client.aclose()


def _rows(data: Any) -> list[dict[str, Any]]:
    body = data.get("data") if isinstance(data, dict) else data
    if isinstance(body, dict):
        for key in ("items", "products", "offerings", "members", "plans", "resources", "locations"):
            if isinstance(body.get(key), list):
                return list(body[key])
    return list(body) if isinstance(body, list) else []


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def owner_prices(scenario_key: str) -> dict[str, tuple[int, str, str]]:
    """The owner's own catalogue: name → (price, unit, group)."""
    from platform_testing.certify.owners import CATALOGUES

    out: dict[str, tuple[int, str, str]] = {}
    for group, items in CATALOGUES.get(scenario_key, {}).items():
        for name, price, unit, _note in items:
            out[_norm(name)] = (int(price), unit, group)
    return out


def _price_for(title: str, prices: dict[str, tuple[int, str, str]]) -> tuple[int, str, str] | None:
    key = _norm(title)
    if key in prices:
        return prices[key]
    for name, row in prices.items():
        if name and (name in key or key in name):
            return row
    return None


def _duration(title: str, group: str) -> int:
    text = f"{title} {group}".casefold()
    if re.search(r"\b(consult|review|visit|check|clean|trim|thread)", text):
        return 30
    if re.search(r"\b(facial|colour|color|spa|massage|bridal|treatment|therapy)", text):
        return 60
    return 45


async def setup_offerings(ws: Workspace, setup: Setup, scenario: Any) -> None:
    b = setup.business_id
    # "Set up my items" in the interview: the catalogue the owner described,
    # as private, unpriced drafts the owner then publishes.
    _, current = await ws.call("GET", f"/v1/b/{b}/interview")
    revision = int((((current or {}).get("data") or {}).get("blueprint") or {}).get("revision") or 0)
    status, out = await ws.call("POST", f"/v1/b/{b}/interview", {
        "action": "setup", "revision": revision, "request_id": str(uuid.uuid4())}, expect=False)
    if status >= 400:
        setup.findings.append(f"interview setup action → {status} {str(out)[:200]}")
    _, data = await ws.call("GET", f"/v1/platform/businesses/{b}/products?limit=200")
    rows = _rows(data)
    prices = owner_prices(scenario.key)
    if not rows and prices:
        # Nothing came over from the interview (a minimal owner): they type
        # their items into the Workspace instead.
        setup.findings.append("no catalogue items from the interview; typed into the Workspace")
        for name_key, (amount, _unit, _group) in list(prices.items())[:8]:
            await ws.call("POST", f"/v1/platform/businesses/{b}/products", {
                "title": name_key.title(), "status": "draft", "visibility": "private", "price_type": "fixed",
                "price_amount": amount})
        _, data = await ws.call("GET", f"/v1/platform/businesses/{b}/products?limit=200")
        rows = _rows(data)
    for row in rows:
        title = str(row.get("title") or "")
        found = _price_for(title, prices)
        price = (float(row["price_amount"]) if row.get("price_amount") else None) or (found[0] if found else None)
        kind = str(row.get("offering_type") or "product")
        patch: dict[str, Any] = {"version": row.get("version"), "status": "active", "visibility": "public"}
        if price:
            patch.update({"price_type": "starting_from" if found and "onwards" in found[1] else "fixed",
                          "price_amount": price})
        if kind in {"service", "class_session"}:
            patch["attributes"] = {**(row.get("attributes") or {}),
                                   "duration_minutes": _duration(title, found[2] if found else "")}
        status, out = await ws.call("PATCH", f"/v1/platform/businesses/{b}/products/{row['id']}", patch)
        if status >= 400 and "attributes" in patch:
            patch.pop("attributes")
            status, out = await ws.call("PATCH", f"/v1/platform/businesses/{b}/products/{row['id']}", patch)
        setup.offerings.append({"id": str(row["id"]), "title": title, "type": kind, "price": price,
                                "live": status < 400})


async def setup_orders(ws: Workspace, setup: Setup, delivers: bool) -> None:
    b = setup.business_id
    body = {"pickup_enabled": True, "delivery_enabled": delivers}
    status, _ = await ws.call("PATCH", f"/v1/b/{b}/fulfilment/settings", body)
    setup.fulfilment = {**body, "saved": status < 400}
    if delivers:
        status, _ = await ws.call("POST", f"/v1/b/{b}/fulfilment/zones", {
            "name": "Nearby", "match_type": "postal_prefix", "postal_prefix": "6", "charge_amount": 40})
        setup.fulfilment["zone"] = status < 400


async def setup_inventory(ws: Workspace, setup: Setup) -> None:
    b = setup.business_id
    for row in setup.offerings:
        if row["type"] in {"product", "menu_item"} and row["live"]:
            status, _ = await ws.call("POST", f"/v1/platform/businesses/{b}/inventory/opening-stock", {
                "offering_id": row["id"], "location_id": setup.location_id, "quantity": 25})
            setup.stocked += int(status < 400)


async def setup_bookings(ws: Workspace, setup: Setup, scenario: Any, name: str) -> None:
    b = setup.business_id
    bookable = [o for o in setup.offerings
                if o["live"] and o["type"] in {"service", "class_session", "accommodation"}]
    if scenario.kind == "restaurant" or not bookable:
        # A restaurant books tables, not its dishes.
        for n in range(1, 5):
            status, out = await ws.call("POST", f"/v1/platform/businesses/{b}/bookings/resources", {
                "location_id": setup.location_id, "resource_type": "table", "name": f"Table {n}",
                "capacity": 4, "min_party_size": 1, "max_party_size": 4})
            if status < 400:
                setup.resources.append(str(((out or {}).get("data") or {}).get("id") or ""))
    status, out = await ws.call("POST", f"/v1/platform/businesses/{b}/workforce/members", {
        "display_name": name, "location_ids": [setup.location_id], "primary_location_id": setup.location_id})
    if status >= 400:
        return
    member = str(((out or {}).get("data") or {}).get("id") or "")
    setup.provider_id = member
    for day in WEEK:
        await ws.call("POST", f"/v1/platform/businesses/{b}/workforce/members/{member}/availability", {
            "location_id": setup.location_id, "weekday": day, "start_time": OPENS, "end_time": CLOSES})
    for row in bookable:
        await ws.call("POST", f"/v1/platform/businesses/{b}/workforce/members/{member}/services/{row['id']}")


def _plan_days(name: str) -> int:
    text = name.casefold()
    if "year" in text or "annual" in text:
        return 365
    if "half" in text or "6 month" in text or "six month" in text:
        return 180
    if "quarter" in text or "3 month" in text:
        return 90
    if "week" in text:
        return 7
    if "day" in text or "drop" in text:
        return 1
    return 30


async def setup_memberships(ws: Workspace, setup: Setup, scenario: Any) -> None:
    from platform_testing.certify.owners import CATALOGUES

    b = setup.business_id
    plans = [(name, price) for group, items in CATALOGUES.get(scenario.key, {}).items()
             if re.search(r"member|plan|pass|package", group, re.I) for name, price, _u, _n in items]
    if not plans:
        plans = [("Monthly membership", 1500)]
    for name, price in plans[:4]:
        status, out = await ws.call("POST", f"/v1/platform/businesses/{b}/membership-plans", {
            "name": name, "price_amount": price, "duration_days": _plan_days(name),
            "status": "active", "visibility": "public"})
        setup.plans.append({"name": name, "price": price, "live": status < 400,
                            "id": str(((out or {}).get("data") or {}).get("id") or "")})


async def setup_invoicing(ws: Workspace, setup: Setup, legal_name: str) -> None:
    b = setup.business_id
    status, out = await ws.call("POST", f"/v1/platform/businesses/{b}/invoicing/registrations", {
        "scheme": "unregistered", "legal_name": legal_name, "state_code": "33"})
    registration = str(((out or {}).get("data") or {}).get("id") or "")
    await ws.call("PUT", f"/v1/platform/businesses/{b}/invoicing/profile", {
        "prices_include_tax": True, "round_off": True, "issue_on": "manual"})
    if registration:
        status, _ = await ws.call("POST", f"/v1/platform/businesses/{b}/invoicing/registers", {
            "location_id": setup.location_id, "registration_id": registration, "code": "MAIN1",
            "name": "Front desk"})
        setup.invoicing = status < 400


async def run(run_dir: Path, site_key: str) -> Setup:
    from platform_testing.certify.owners import DISTINCT, SCENARIOS

    folder = run_dir / "sites" / site_key
    journey = json.loads((folder / "journey.json").read_text(encoding="utf-8"))
    setup = Setup(site_key=site_key, business_id=journey["business_id"])
    if not journey.get("owner_id"):
        setup.findings.append("journey.json has no owner_id (journey from before the owner was recorded)")
        setup.save(folder)
        return setup
    scenario = SCENARIOS.get(journey["scenario"]) or next(
        s for group in DISTINCT.values() for s in group if s.key == journey["scenario"])
    modules = set(journey.get("modules_enabled") or [])
    ws = Workspace(owner_token(journey["owner_id"], journey["owner_email"]), setup)
    try:
        b = setup.business_id
        _, data = await ws.call("GET", f"/v1/platform/businesses/{b}/locations")
        locations = _rows(data)
        primary = next((loc for loc in locations if loc.get("is_primary")), locations[0] if locations else None)
        setup.location_id = str((primary or {}).get("id") or "")
        if "offerings-catalog" in modules:
            await setup_offerings(ws, setup, scenario)
        if "orders" in modules:
            # An owner who kept the fulfilment tool delivers; the rest hand over
            # at the counter.
            await setup_orders(ws, setup, "fulfilment" in modules)
        if "inventory" in modules:
            await setup_inventory(ws, setup)
        if "bookings" in modules:
            await setup_bookings(ws, setup, scenario, scenario.business_name.split()[0])
        if "memberships" in modules:
            await setup_memberships(ws, setup, scenario)
        if "invoicing" in modules:
            await setup_invoicing(ws, setup, scenario.business_name)
        _, readiness = await ws.call("GET", f"/v1/b/{b}/modules", expect=False)
        setup.ready = {str(m.get("module_id")): m.get("activation_state")
                       for m in _rows(readiness) if isinstance(m, dict) and m.get("module_id") in modules}
        # Publish again: the live site now offers what can really be done.
        await ws.call("POST", f"/v1/b/{b}/website/publish", expect=False)
        if journey.get("slug"):
            async with httpx.AsyncClient(timeout=30) as web:
                await web.post(f"{WEB}/api/revalidate", json={"slug": journey["slug"]},
                               headers={"x-locah-revalidate-secret": "local-revalidate-secret-for-certify"})
    except Exception as exc:  # noqa: BLE001 — a setup that breaks is a finding
        setup.findings.append(f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        await ws.close()
        setup.save(folder)
    return setup


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m platform_testing.certify.setup <run_dir> <site_key>")
    out = asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps({k: out.__dict__[k] for k in ("site_key", "offerings", "plans", "provider_id",
                                                   "resources", "fulfilment", "stocked", "invoicing",
                                                   "findings")}, indent=1, ensure_ascii=False))
