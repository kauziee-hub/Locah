"""One business owner, end to end, through the same HTTP paths the owner's browser uses.

    uv run python -m platform_testing.certify.journey <run_dir> <scenario> <variant>

Against the certification stack (tools/certify/stack: API :8020 with the real
AI and photo providers, local database `locah_certify`, local storage). The
owner is a fresh local identity with a locally signed token; everything after
that is the product's own API:

  POST /v1/platform/businesses/start
  POST /v1/b/{id}/interview  {action: turn}         — the owner's own words, question by question
  POST /v1/b/{id}/media/upload-url → PUT → /complete, {action: media}   — owner photographs
  POST /v1/b/{id}/interview  {action: keep_tools | choices}             — the tools the owner keeps
  POST /v1/b/{id}/modules/{module}/enable           — tools the owner switches on in the Workspace
  POST /v1/b/{id}/interview  {action: review, build} — "Build my website"
  GET  /v1/b/{id}/website (poll) → POST /v1/b/{id}/website/publish

Nothing is seeded into the website: if the interview does not understand the
owner, the site shows it. Writes <run_dir>/sites/<site_key>/journey.json.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

API = os.getenv("CERTIFY_API", "http://localhost:8020")
WEB = os.getenv("CERTIFY_WEB", "http://localhost:3200")
DB = os.getenv("CERTIFY_DB", "locah_certify")
SECRET = "local-acceptance-secret-with-at-least-32-characters"
MAX_TURNS = int(os.getenv("CERTIFY_MAX_TURNS", "12"))
BUILD_TIMEOUT = int(os.getenv("CERTIFY_BUILD_TIMEOUT", "900"))


@dataclass
class Journey:
    site_key: str
    scenario: str
    variant: str
    business_id: str = ""
    slug: str = ""
    # The local owner identity (never its token): the setup step signs in as
    # the same owner to make the kept tools operational.
    owner_id: str = ""
    owner_email: str = ""
    modules_wanted: list[str] = field(default_factory=list)
    modules_enabled: list[str] = field(default_factory=list)
    modules_failed: dict[str, str] = field(default_factory=dict)
    turns: list[dict[str, Any]] = field(default_factory=list)
    media: list[dict[str, Any]] = field(default_factory=list)
    build: dict[str, Any] = field(default_factory=dict)
    pages: list[str] = field(default_factory=list)
    published: bool = False
    publish_error: str = ""
    public_url: str = ""
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "journey.json").write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1),
                                             encoding="utf-8")


async def new_owner(label: str) -> tuple[str, str, str]:
    """A fresh local owner identity and its locally signed session token."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from platform_testing.db_helpers import ensure_auth_user

    user_id = uuid.uuid4()
    email = f"certify-{label}-{user_id.hex[:6]}@locah.test"
    engine = create_async_engine(f"postgresql+asyncpg://postgres@localhost:54329/{DB}")
    async with AsyncSession(engine) as session:
        await ensure_auth_user(session, user_id, email)
        await session.commit()
    await engine.dispose()
    exp = datetime.now(timezone.utc) + timedelta(hours=12)
    token = jwt.encode({"sub": str(user_id), "email": email, "aud": "authenticated", "role": "authenticated",
                        "exp": exp}, SECRET, algorithm="HS256")
    return str(user_id), email, token


class Owner:
    """The owner's browser: authenticated JSON calls to the API."""

    def __init__(self, token: str) -> None:
        self.client = httpx.AsyncClient(base_url=API, timeout=180,
                                        headers={"Authorization": f"Bearer {token}"})

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        response = await self.client.request(method, path, json=body)
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:400]}
        return response.status_code, data


def _ask_of(data: dict[str, Any]) -> str:
    """The question the interview is asking now (the planner's ask id)."""
    bp = data.get("blueprint") or {}
    asks = bp.get("asks") or []
    if asks and isinstance(asks[-1], dict):
        return str(asks[-1].get("ask") or "")
    return str(bp.get("last_asked_target") or "")


def _last_reply(data: dict[str, Any]) -> str:
    messages = (data.get("blueprint") or {}).get("messages") or []
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return str(message.get("text") or "")[:600]
    return ""


async def interview(owner: Owner, journey: Journey, business_id: str, script: Any,
                    business_name: str = "") -> dict[str, Any]:
    """The conversation: the opening, then an answer to each question, in the owner's own words."""
    status, body = await owner.call("GET", f"/v1/b/{business_id}/interview")
    data = body.get("data") or {}
    said: set[str] = set()
    answered: dict[str, int] = {}
    text = script.opening
    for turn in range(MAX_TURNS):
        revision = int((data.get("blueprint") or {}).get("revision") or 0)
        status, body = await owner.call("POST", f"/v1/b/{business_id}/interview", {
            "action": "turn", "text": text, "revision": revision, "request_id": str(uuid.uuid4())})
        if status >= 400:
            journey.errors.append(f"turn {turn}: {status} {str(body)[:200]}")
            status, body = await owner.call("GET", f"/v1/b/{business_id}/interview")
            data = body.get("data") or {}
            continue
        data = body.get("data") or {}
        ask = _ask_of(data)
        ready = _ready(data)
        journey.turns.append({"said": text, "reply": _last_reply(data), "next_ask": ask, "ready": ready})
        # A real owner answers what they are asked until the interview has
        # nothing left to ask: a question they have no new words for gets
        # their fallback ("not sure, keep it simple") and the interview moves
        # on. Only the review summary, or the same question coming back after
        # it was answered, ends the conversation.
        if ready and (not ask or ask == "free" or answered.get(ask, 0) >= 1):
            break
        answer = _answer(script, ask, business_name)
        if answer is None or answer in said:
            answer = script.fallback
        answered[ask] = answered.get(ask, 0) + 1
        said.add(answer)
        text = answer
    return data


def _ready(data: dict[str, Any]) -> bool:
    """The interview offers Build (or is showing its summary for review)."""
    state = ((data.get("blueprint") or {}).get("completion_state") or {})
    return bool(data.get("build_available") or state.get("ready_at") or state.get("status") in {"review", "ready"})


# The interview's own question ids are the planner's ask ids, plus "name" for the
# business's name (asked before anything else when it was not said).
_ALIASES = {"name": ("name", "identity"), "contact": ("contact", "phone"), "offer": ("offer", "catalogue"),
            "structure": ("structure", "catalogue", "offer"), "catalogue": ("catalogue", "structure", "offer")}


def _answer(script: Any, ask: str, business_name: str) -> str | None:
    if not ask:
        return None
    for key in _ALIASES.get(ask, (ask,)):
        if script.answers.get(key):
            return str(script.answers[key])
    if ask == "name" and business_name:
        return f"It's called {business_name}."
    return None


async def upload_media(owner: Owner, journey: Journey, business_id: str, paths: tuple[str, ...]) -> None:
    """Owner photographs, uploaded the way the interview's attach button does."""
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            journey.errors.append(f"media missing: {raw}")
            continue
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        status, start = await owner.call("POST", f"/v1/b/{business_id}/media/upload-url", {
            "purpose": "website", "mime_type": mime, "size_bytes": len(body), "original_filename": path.name})
        if status >= 400:
            journey.errors.append(f"upload-url {path.name}: {status} {str(start)[:160]}")
            continue
        asset_id = start["data"]["asset"]["id"]
        upload_url = start["data"]["upload"]["upload_url"]
        async with httpx.AsyncClient(timeout=60) as raw_client:
            put = await raw_client.put(upload_url, content=body, headers={"content-type": mime, "x-upsert": "false"})
        if put.status_code >= 400:
            journey.errors.append(f"upload {path.name}: {put.status_code}")
            continue
        status, done = await owner.call("POST", f"/v1/b/{business_id}/media/{asset_id}/complete")
        if status >= 400:
            journey.errors.append(f"complete {path.name}: {status} {str(done)[:160]}")
            continue
        current = (await owner.call("GET", f"/v1/b/{business_id}/interview"))[1].get("data") or {}
        revision = int((current.get("blueprint") or {}).get("revision") or 0)
        role = "hero" if not journey.media else "business"
        status, out = await owner.call("POST", f"/v1/b/{business_id}/interview", {
            "action": "media", "revision": revision, "request_id": str(uuid.uuid4()),
            "media": {"asset_id": asset_id, "role": role, "label": path.name, "source": "USER_UPLOAD"}})
        journey.media.append({"file": path.name, "asset_id": asset_id, "role": role, "status": status})


async def choose_tools(owner: Owner, journey: Journey, business_id: str, wanted: tuple[str, ...]) -> None:
    """Keep the recommended tools this owner wants, decline the rest, switch on the others in the Workspace."""
    data = (await owner.call("GET", f"/v1/b/{business_id}/interview"))[1].get("data") or {}
    bp = data.get("blueprint") or {}
    recommended = [m.get("module_id") for m in bp.get("recommended_modules") or [] if m.get("module_id")]
    choices = {m: ("approved" if m in wanted else "declined") for m in recommended}
    if choices:
        status, out = await owner.call("POST", f"/v1/b/{business_id}/interview", {
            "action": "choices", "revision": int(bp.get("revision") or 0), "request_id": str(uuid.uuid4()),
            "choices": choices})
        if status >= 400:
            journey.errors.append(f"choices: {status} {str(out)[:200]}")
    for module in wanted:
        status, out = await owner.call("POST", f"/v1/b/{business_id}/modules/{module}/enable")
        if status < 400:
            journey.modules_enabled.append(module)
        else:
            error = (out.get("error") or {}) if isinstance(out, dict) else {}
            journey.modules_failed[module] = f"{status} {error.get('code', '')} {str(error.get('message', out))[:160]}"


JOB_DONE = frozenset({"completed", "fallback_used", "failed", "cancelled", "superseded"})
USAGE_KEPT = ("composer", "archetype", "reference_profile", "model", "strategy_source", "media_drawn",
              "media_failed", "image_latency_ms", "creative_latency_ms", "owner_edits_kept", "photo_audit")


async def build_and_wait(owner: Owner, journey: Journey, business_id: str) -> dict[str, Any]:
    """'Build my website', then wait for the draft the build job writes."""
    data = (await owner.call("GET", f"/v1/b/{business_id}/interview"))[1].get("data") or {}
    revision = int((data.get("blueprint") or {}).get("revision") or 0)
    status, out = await owner.call("POST", f"/v1/b/{business_id}/interview", {
        "action": "review", "revision": revision, "request_id": str(uuid.uuid4())})
    if status < 400:
        revision = int(((out.get("data") or {}).get("blueprint") or {}).get("revision") or revision)
    started = time.monotonic()
    status, out = await owner.call("POST", f"/v1/b/{business_id}/interview", {
        "action": "build", "revision": revision, "request_id": str(uuid.uuid4())})
    journey.build["request_status"] = status
    if status >= 400:
        journey.build["error"] = str(out)[:400]
        return {}
    draft: dict[str, Any] = {}
    job: dict[str, Any] = {}
    bp: dict[str, Any] = {}
    # The build writes an immediate draft, then a worker job personalises it
    # (AI direction, copy, pictures). The owner's real site is the second one.
    while time.monotonic() - started < BUILD_TIMEOUT:
        await asyncio.sleep(6)
        bp = ((await owner.call("GET", f"/v1/b/{business_id}/interview"))[1].get("data") or {}).get("blueprint") or {}
        state = (bp.get("completion_state") or {}).get("status")
        job = (await owner.call("GET", f"/v1/b/{business_id}/website/generation"))[1].get("data") or {}
        if state == "built" and job.get("status") in JOB_DONE:
            break
    status, site = await owner.call("GET", f"/v1/b/{business_id}/website")
    draft = ((site.get("data") or {}).get("draft") or {}) if status < 400 else {}
    usage = job.get("provider_usage") or {}
    journey.build.update(status=(bp.get("completion_state") or {}).get("status"),
                         seconds=round(time.monotonic() - started, 1),
                         generated_by=draft.get("generated_by"),
                         job_status=job.get("status"), fallback_reason=job.get("fallback_reason"),
                         error=job.get("error_detail"),
                         **{k: usage.get(k) for k in USAGE_KEPT if usage.get(k) is not None})
    return draft


async def run(run_dir: Path, scenario_key: str, variant: str) -> Journey:
    from platform_testing.certify.owners import DISTINCT, SCENARIOS

    scenario = SCENARIOS.get(scenario_key) or next(
        (s for group in DISTINCT.values() for s in group if s.key == scenario_key), None)
    if scenario is None:
        raise SystemExit(f"unknown scenario {scenario_key}")
    script = scenario.variants[variant]
    site_key = f"{scenario.key}--{variant}"
    journey = Journey(site_key=site_key, scenario=scenario.key, variant=variant,
                      modules_wanted=list(scenario.modules))
    folder = run_dir / "sites" / site_key
    started = time.monotonic()
    journey.owner_id, journey.owner_email, token = await new_owner(scenario.key[:12])
    owner = Owner(token)
    try:
        status, out = await owner.call("POST", "/v1/platform/businesses/start", {})
        if status >= 400:
            journey.errors.append(f"start: {status} {str(out)[:200]}")
            return journey
        business = out["data"]["business"]
        journey.business_id = business_id = str(business["id"])
        await interview(owner, journey, business_id, script, scenario.business_name)
        if script.media:
            await upload_media(owner, journey, business_id, script.media)
        await choose_tools(owner, journey, business_id, scenario.modules)
        draft = await build_and_wait(owner, journey, business_id)
        journey.pages = [str(p.get("slug")) for p in draft.get("pages") or []]
        (folder / "draft.json").parent.mkdir(parents=True, exist_ok=True)
        (folder / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
        status, out = await owner.call("POST", f"/v1/b/{business_id}/website/publish")
        journey.published = status < 400
        if status >= 400:
            journey.publish_error = str(out)[:400]
        status, site = await owner.call("GET", f"/v1/b/{business_id}/website")
        journey.slug = str(((site.get("data") or {}).get("website") or {}).get("slug") or "")
        if not journey.slug:
            status, b = await owner.call("GET", f"/v1/b/{business_id}")
            journey.slug = str(((b.get("data") or {}).get("business") or b.get("data") or {}).get("slug") or "")
        journey.public_url = f"{WEB}/{journey.slug}" if journey.slug else ""
        if journey.slug:
            async with httpx.AsyncClient(timeout=30) as web:
                await web.post(f"{WEB}/api/revalidate", json={"slug": journey.slug},
                               headers={"x-locah-revalidate-secret": "local-revalidate-secret-for-certify"})
    except Exception as exc:  # noqa: BLE001 — a journey that breaks is a finding, not a crash
        journey.errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        await owner.close()
        journey.seconds = round(time.monotonic() - started, 1)
        journey.save(folder)
    return journey


if __name__ == "__main__":  # pragma: no cover — a tool
    result = asyncio.run(run(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
    print(json.dumps({k: result.__dict__[k] for k in ("site_key", "slug", "published", "pages", "modules_enabled",
                                                      "modules_failed", "errors", "seconds")}, indent=1))
