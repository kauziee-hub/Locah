"""Website quality certification decides publish (WEBSITE_CERTIFICATION).

A weak website must never silently be published: with ``enforce`` a draft
goes live only with a current passing verdict; a failed verdict hands the
owner the gate's requests; an edit after a pass makes it stale. ``off`` keeps
today's behaviour and ``record`` publishes but says it would have held back.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import jwt
import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.db import get_database_url
from platform_testing.db_helpers import ensure_auth_user
from platform_worker.job_runner import poll_and_execute_jobs
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def _run(coro_fn: Any) -> Any:
    async def _go() -> Any:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            return await coro_fn(factory)
        finally:
            await engine.dispose()

    return asyncio.run(_go())


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("WEBSITE_PREVIEW_SECRET", SECRET)
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"

    async def seed(factory: Any) -> None:
        async with factory() as session:
            await ensure_auth_user(session, user_id, email)
            await session.commit()

    _run(seed)
    token = jwt.encode({"sub": str(user_id), "email": email,
                        "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _business_with_draft(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post("/v1/platform/businesses", json={
        "display_name": f"Cert Co {uuid.uuid4().hex[:8]}", "business_type": "retail"}, headers=headers)
    assert resp.status_code == 200, resp.text
    bid = cast(str, resp.json()["data"]["business"]["id"])

    async def drain(factory: Any) -> None:
        from platform_core.services.website_generation import WebsiteGenerationService

        for _ in range(15):
            async with factory() as session:
                await poll_and_execute_jobs(session, "test-cert-worker", business_id=bid)
                job = await WebsiteGenerationService.latest_job(session, business_id=uuid.UUID(bid))
                if job is not None and job.status in {"completed", "fallback_used", "failed", "superseded"}:
                    return

    _run(drain)
    site = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]
    home = next(p for p in site["draft"]["pages"] if p["slug"] == "home")
    hero = next(s for s in home["sections"] if s["section_type_id"] == "hero")
    patched = client.patch(f"/v1/b/{bid}/website/sections/{hero['id']}",
                           json={"content": {"headline": "Ready to publish"}}, headers=headers)
    assert patched.status_code == 200, patched.text
    return bid


def _certify(bid: str, verdict: dict[str, Any]) -> None:
    async def record(factory: Any) -> None:
        from platform_core.services.website_certification import WebsiteCertificationService

        async with factory() as session:
            await WebsiteCertificationService.record(
                session, business_id=uuid.UUID(bid), verdict=verdict, source="test")
            await session.commit()

    _run(record)


FAILED = {"status": "fail_closed", "score": 6.1, "blocked_on": "owner",
          "owner_requests": ["We need 2–3 photographs of your actual clinic and team to finish this site."]}
PASSED = {"status": "pass", "score": 8.9}


def test_enforce_holds_a_draft_that_was_never_checked(owner: dict[str, str], monkeypatch: Any) -> None:
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "enforce")
    client = TestClient(app)
    bid = _business_with_draft(client, owner)
    refused = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"]["reason"] == "certification_missing"
    site = client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]
    assert site["certification"] == {"required": True, "current": None}


def test_enforce_hands_the_owner_the_gate_requests_and_publishes_only_a_pass(
    owner: dict[str, str], monkeypatch: Any,
) -> None:
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "enforce")
    client = TestClient(app)
    bid = _business_with_draft(client, owner)

    _certify(bid, FAILED)
    refused = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert refused.status_code == 422, refused.text
    error = refused.json()["error"]
    assert error["details"]["reason"] == "certification_failed"
    assert error["details"]["owner_requests"] == FAILED["owner_requests"]
    assert "photographs of your actual clinic" in error["message"]
    current = client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]["certification"]["current"]
    assert current["status"] == "fail_closed" and current["stale"] is False and current["score"] == 6.1

    _certify(bid, PASSED)
    published = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert published.status_code == 200, published.text
    assert published.json()["data"]["website"]["status"] == "published"


def test_an_edit_after_a_pass_must_be_checked_again(owner: dict[str, str], monkeypatch: Any) -> None:
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "enforce")
    client = TestClient(app)
    bid = _business_with_draft(client, owner)
    _certify(bid, PASSED)
    site = client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]
    home = next(p for p in site["draft"]["pages"] if p["slug"] == "home")
    hero = next(s for s in home["sections"] if s["section_type_id"] == "hero")
    edited = client.patch(f"/v1/b/{bid}/website/sections/{hero['id']}",
                          json={"content": {"headline": "Changed after it was checked"}}, headers=owner)
    assert edited.status_code == 200, edited.text
    refused = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"]["reason"] == "certification_stale"
    assert client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]["certification"]["current"]["stale"]


def test_off_and_record_still_publish(owner: dict[str, str], monkeypatch: Any) -> None:
    client = TestClient(app)
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "off")
    bid = _business_with_draft(client, owner)
    assert client.post(f"/v1/b/{bid}/website/publish", headers=owner).status_code == 200
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "record")
    other = _business_with_draft(client, owner)
    _certify(other, FAILED)
    assert client.post(f"/v1/b/{other}/website/publish", headers=owner).status_code == 200


def test_a_verdict_is_pass_repair_or_fail_closed(owner: dict[str, str]) -> None:
    client = TestClient(app)
    bid = _business_with_draft(client, owner)
    with pytest.raises(Exception, match="pass, repair or fail_closed"):
        _certify(bid, {"status": "great"})
