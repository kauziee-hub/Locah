"""The owner changes their published website the way the Workspace does.

    uv run python -m platform_testing.certify.edits <run_dir> <site_key>

Run after the other steps (it changes the site). Each edit goes through the
same API the Workspace uses, is published, and is then read back from the
PUBLIC website payload — what a visitor gets — never from the draft alone:

  headline       the hero's words
  button         the hero's call to action
  theme          the site's main colour
  hours          the main location's opening hours (the website's "Find us")
  location       a second branch added
  add offering   a new priced item in the catalogue
  remove         that item taken off sale
  module off/on  a tool the site uses switched off, then on again: the site
                 stops offering it and offers it again
  gate failures  a future tool, an unknown tool and a storefront tool that
                 cannot be switched off are each refused, each for its own
                 reason
  replace image  the owner's own photograph as the hero picture
  regenerate     one section, then one page, written anew — the owner's
                 own headline edit survives both
  new picture    "change this image" on the hero

Writes edits.json beside journey.json: every check with ok/detail.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from platform_testing.certify.journey import API
from platform_testing.certify.owners import ROOT
from platform_testing.certify.setup import Setup, Workspace, _rows, owner_token

HEADLINE = "Certified by the owner's own hand"
BUTTON = "Plan your visit"
PRIMARY = "#1f4b99"
PHOTO = ROOT / "apps/web/public/site-lab-photos/lab-crumb/pixabay-2595658.jpg"
# The capability each tool gives the website, in the public payload.
CAPABILITY = {"bookings": "book", "orders": "order", "leads": "enquire", "memberships": "join"}


@dataclass
class Edits:
    site_key: str
    checks: list[dict[str, Any]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: Any = "") -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:400]})
        return bool(ok)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    def save(self, folder: Path) -> None:
        (folder / "edits.json").write_text(json.dumps({"site_key": self.site_key, "ok": self.ok,
                                                       "checks": self.checks}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")


def _data(body: Any) -> Any:
    return body.get("data") if isinstance(body, dict) else body


def _sections(page: dict[str, Any]) -> list[dict[str, Any]]:
    return list(page.get("sections") or [])


def _hero(page: dict[str, Any]) -> dict[str, Any]:
    return next((s for s in _sections(page) if s.get("section_type_id") == "hero"), {})


class Site:
    """The owner's draft and the visitor's public site, side by side."""

    def __init__(self, ws: Workspace, business_id: str, slug: str) -> None:
        self.ws, self.b, self.slug = ws, business_id, slug
        self.public_client = httpx.AsyncClient(base_url=API, timeout=60)

    async def draft(self) -> dict[str, Any]:
        _, body = await self.ws.call("GET", f"/v1/b/{self.b}/website")
        return dict((_data(body) or {}).get("draft") or {})

    async def publish(self) -> int:
        status, _ = await self.ws.call("POST", f"/v1/b/{self.b}/website/publish", expect=False)
        return int(status)

    async def public(self, page: str = "") -> dict[str, Any]:
        path = f"/v1/public/websites/{self.slug}" + (f"/pages/{page}" if page else "")
        res = await self.public_client.get(path)
        return dict(_data(res.json()) or {}) if res.status_code < 400 else {}

    async def offerings(self) -> str:
        """The live catalogue as the site's own pages fetch it in the visitor's browser."""
        res = await self.public_client.get(f"/v1/public/websites/{self.slug}/offerings")
        return res.text if res.status_code < 400 else ""

    async def public_text(self) -> str:
        home = await self.public()
        texts = [json.dumps(home.get("page") or {}, ensure_ascii=False)]
        for item in home.get("navigation") or []:
            path = str(item.get("path") or "").strip("/")
            if path and not path.startswith("#"):
                texts.append(json.dumps((await self.public(path)).get("page") or {}, ensure_ascii=False))
        return "\n".join(texts)

    async def wait_job(self, started: float, timeout: float = 600) -> dict[str, Any]:
        job: dict[str, Any] = {}
        while time.monotonic() - started < timeout:
            await asyncio.sleep(5)
            _, body = await self.ws.call("GET", f"/v1/b/{self.b}/website/generation", expect=False)
            job = dict(_data(body) or {})
            if job.get("status") in {"completed", "fallback_used", "failed", "cancelled", "superseded"}:
                break
        return job

    async def close(self) -> None:
        await self.public_client.aclose()


async def upload(ws: Workspace, business_id: str, path: Path) -> str:
    body = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    status, start = await ws.call("POST", f"/v1/b/{business_id}/media/upload-url", {
        "purpose": "website", "mime_type": mime, "size_bytes": len(body), "original_filename": path.name})
    if status >= 400:
        return ""
    data = _data(start) or {}
    async with httpx.AsyncClient(timeout=60) as raw:
        put = await raw.put(data["upload"]["upload_url"], content=body,
                            headers={"content-type": mime, "x-upsert": "false"})
    if put.status_code >= 400:
        return ""
    asset_id = str(data["asset"]["id"])
    status, _ = await ws.call("POST", f"/v1/b/{business_id}/media/{asset_id}/complete")
    return asset_id if status < 400 else ""


async def run(run_dir: Path, site_key: str) -> Edits:
    folder = run_dir / "sites" / site_key
    journey = json.loads((folder / "journey.json").read_text(encoding="utf-8"))
    edits = Edits(site_key)
    if not journey.get("owner_id") or not journey.get("slug"):
        edits.check("journey has an owner and a published site", False, "missing owner_id or slug")
        edits.save(folder)
        return edits
    ws = Workspace(owner_token(journey["owner_id"], journey["owner_email"]), Setup(site_key))
    b = str(journey["business_id"])
    site = Site(ws, b, str(journey["slug"]))
    try:
        await steps(site, ws, b, journey, edits)
    except Exception as exc:  # noqa: BLE001 — an edit that breaks is a finding
        edits.check("edits ran to the end", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        await site.close()
        await ws.close()
        edits.save(folder)
    return edits


async def steps(site: Site, ws: Workspace, b: str, journey: dict[str, Any], edits: Edits) -> None:
    draft = await site.draft()
    pages = {str(p.get("slug")): p for p in draft.get("pages") or []}
    home = pages.get("home") or {}
    hero = _hero(home)
    if not edits.check("the draft has a home hero", bool(hero.get("id")), list(pages)):
        return
    hero_path = f"/v1/b/{b}/website/sections/{hero['id']}"

    # 1-2. The hero's words and its button.
    # The editor sends the section's whole content with the change in it (a
    # PATCH replaces the content; sending two fields would wipe the rest).
    status, _ = await ws.call("PATCH", hero_path, {"content": {**(hero.get("content") or {}),
                                                               "headline": HEADLINE, "cta_label": BUTTON}})
    await site.publish()
    shown = _hero((await site.public()).get("page") or {}).get("content") or {}
    edits.check("headline edit is on the public site", status < 400 and shown.get("headline") == HEADLINE,
                shown.get("headline"))
    edits.check("button edit is on the public site", shown.get("cta_label") == BUTTON, shown.get("cta_label"))

    # 3. The main colour.
    theme = dict((await site.draft()).get("theme") or {})
    theme["primary_color"] = PRIMARY
    status, _ = await ws.call("PATCH", f"/v1/b/{b}/website/theme", {"theme": theme})
    await site.publish()
    public_theme = (await site.public()).get("theme") or {}
    edits.check("colour change is on the public site", status < 400 and public_theme.get("primary_color") == PRIMARY,
                public_theme.get("primary_color"))

    # 4-5. Opening hours, and a second branch.
    _, data = await ws.call("GET", f"/v1/platform/businesses/{b}/locations")
    locations = _rows(data)
    primary = next((loc for loc in locations if loc.get("is_primary")), locations[0] if locations else {})
    if primary:
        week = {d: [["09:00", "20:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat")}
        status, _ = await ws.call("PATCH", f"/v1/platform/businesses/{b}/locations/{primary['id']}",
                                  {"version": primary.get("version"), "hours": week})
        await site.publish()
        place = ((await site.public()).get("business") or {}).get("place") or {}
        edits.check("new opening hours are on the public site",
                    status < 400 and "9 am" in str(place.get("hours_summary") or ""), place.get("hours_summary"))
    status, _ = await ws.call("POST", f"/v1/platform/businesses/{b}/locations", {
        "name": "Second branch", "timezone": "Asia/Kolkata", "address": {"line1": "12 Market Road", "city": "Chennai",
                                                                         "country": "IN"}})
    _, data = await ws.call("GET", f"/v1/platform/businesses/{b}/locations")
    edits.check("a second branch can be added", status < 400 and len(_rows(data)) == len(locations) + 1,
                f"{len(locations)} → {len(_rows(data))}")

    # 6-7. A new item, then taken off sale.
    modules = set(journey.get("modules_enabled") or [])
    if "offerings-catalog" in modules:
        _, data = await ws.call("GET", f"/v1/platform/businesses/{b}/products?limit=200")
        existing = _rows(data)
        kind = str((existing[0] if existing else {}).get("offering_type") or "product")
        status, made = await ws.call("POST", f"/v1/platform/businesses/{b}/products", {
            "title": "Certification Special", "status": "active", "visibility": "public", "price_type": "fixed",
            "price_amount": 199, "offering_type": kind})
        item = _data(made) or {}
        await site.publish()
        edits.check("a new item appears on the public site", status < 400 and "Certification Special" in
                    await site.offerings() + await site.public_text(), f"{status} {kind}")
        if item.get("id"):
            status, _ = await ws.call("PATCH", f"/v1/platform/businesses/{b}/products/{item['id']}", {
                "version": item.get("version"), "status": "archived"})
            await site.publish()
            edits.check("an item taken off sale leaves the public site", status < 400 and "Certification Special"
                        not in await site.offerings() + await site.public_text(), status)

    # 8. A tool switched off and on: the site stops offering it, then offers it again.
    tool = next((m for m in ("bookings", "orders", "leads", "memberships") if m in modules), "")
    if tool:
        cap = CAPABILITY[tool]
        before = ((await site.public()).get("capabilities") or {}).get(cap)
        off, _ = await ws.call("POST", f"/v1/b/{b}/modules/{tool}/deactivate")
        await site.publish()
        during = ((await site.public()).get("capabilities") or {}).get(cap)
        on, _ = await ws.call("POST", f"/v1/b/{b}/modules/{tool}/enable")
        await site.publish()
        after = ((await site.public()).get("capabilities") or {}).get(cap)
        edits.check(f"switching {tool} off takes '{cap}' off the site", off < 400 and bool(before) and not during,
                    f"before={before} during={during}")
        edits.check(f"switching {tool} back on offers '{cap}' again", on < 400 and bool(after), f"after={after}")

    # 9. Each refusal for its own reason.
    refusals: dict[str, str] = {}
    for label, method, path in (("future tool", "POST", f"/v1/b/{b}/modules/payroll/enable"),
                                ("unknown tool", "POST", f"/v1/b/{b}/modules/not-a-tool/enable"),
                                ("storefront tool off", "POST", f"/v1/b/{b}/modules/reviews/deactivate")):
        status, body = await ws.call(method, path, expect=False)
        error = (body or {}).get("error") if isinstance(body, dict) else None
        refusals[label] = f"{status} {(error or {}).get('code', '')}"
        edits.check(f"{label} is refused", status >= 400, f"{refusals[label]} {(error or {}).get('message', '')}")
    edits.check("each refusal has its own code", len(set(refusals.values())) == len(refusals), refusals)

    # 10. The owner's own photograph as the hero picture.
    if PHOTO.exists():
        asset = await upload(ws, b, PHOTO)
        current = _hero(next((p for p in (await site.draft()).get("pages") or [] if p.get("slug") == "home"), {}))
        status, _ = await ws.call("PATCH", hero_path, {"content": {**(current.get("content") or {}),
                                                                   "image_asset_id": asset}}) if asset else (0, None)
        await site.publish()
        shown_hero = _hero((await site.public()).get("page") or {})
        edits.check("the owner's photograph is the public hero picture", bool(asset) and status < 400 and
                    asset in json.dumps(shown_hero), asset or "upload failed")

    # 11-12. One section, then one page, written anew: the owner's headline stays.
    draft = await site.draft()
    pages = {str(p.get("slug")): p for p in draft.get("pages") or []}
    target = next((s for s in _sections(pages.get("home") or {})
                   if s.get("section_type_id") in {"statement", "about", "media_text", "feature_grid"}), None)
    if target:
        before_content = json.dumps(target.get("content"), sort_keys=True)
        started = time.monotonic()
        status, _ = await ws.call("POST", f"/v1/b/{b}/website/sections/{target['id']}/regenerate")
        job = await site.wait_job(started) if status < 400 else {}
        draft = await site.draft()
        home_now: dict[str, Any] = next((p for p in draft.get("pages") or [] if p.get("slug") == "home"), {})
        regenerated = next((s for s in _sections(home_now) if s.get("section_type_id") == target["section_type_id"]),
                           {})
        edits.check("regenerate one section completes", status < 400 and job.get("status") in {"completed",
                                                                                                "fallback_used"},
                    job.get("status") or status)
        edits.check("the owner's headline survives a section regeneration",
                    (_hero(home_now).get("content") or {}).get("headline") == HEADLINE,
                    (_hero(home_now).get("content") or {}).get("headline"))
        edits.check("the regenerated section has new words",
                    json.dumps(regenerated.get("content"), sort_keys=True) != before_content,
                    target["section_type_id"])
    # The section's regeneration wrote a new draft: page ids are read again.
    pages = {str(p.get("slug")): p for p in (await site.draft()).get("pages") or []}
    inner = next((p for slug, p in pages.items() if slug in {"about", "visit"} and p.get("id")), None)
    if inner:
        started = time.monotonic()
        status, _ = await ws.call("POST", f"/v1/b/{b}/website/pages/{inner['id']}/regenerate")
        job = await site.wait_job(started) if status < 400 else {}
        draft = await site.draft()
        home_now = next((p for p in draft.get("pages") or [] if p.get("slug") == "home"), {})
        edits.check(f"regenerate the {inner.get('slug')} page completes",
                    status < 400 and job.get("status") in {"completed", "fallback_used"}, job.get("status") or status)
        edits.check("the owner's headline survives a page regeneration",
                    (_hero(home_now).get("content") or {}).get("headline") == HEADLINE,
                    (_hero(home_now).get("content") or {}).get("headline"))

    # 13. "Change this image" on the hero.
    status, body = await ws.call("POST", f"/v1/b/{b}/website/sections/{hero['id']}/generate-image", {},
                                 expect=False)
    edits.check("change this image answers", status < 400 or status in {409, 422, 429},
                f"{status} {str(_data(body) if status < 400 else body)[:200]}")
    await site.publish()


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m platform_testing.certify.edits <run_dir> <site_key>")
    result = asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps({"ok": result.ok, "checks": result.checks}, indent=1, ensure_ascii=False))
