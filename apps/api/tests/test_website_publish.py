"""Stage 2 — Website publish + preview token lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import jwt
import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from platform_core.db import get_database_url
from platform_core.models import PlatformOutboxEvent
from platform_testing.db_helpers import ensure_auth_user
from platform_worker.job_runner import poll_and_execute_jobs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def _token(sub: uuid.UUID, email: str) -> str:
    return jwt.encode(
        {
            "sub": str(sub),
            "email": email,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _headers(user_id: uuid.UUID, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, email)}"}


def _seed(user_id: uuid.UUID, email: str) -> None:
    async def _run() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await ensure_auth_user(session, user_id, email)
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


@pytest.fixture
def owner(monkeypatch: Any) -> tuple[dict[str, str], uuid.UUID]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("WEBSITE_PREVIEW_SECRET", TEST_JWT_SECRET)
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"
    _seed(user_id, email)
    return _headers(user_id, email), user_id


def _create_business(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Pub Co {uuid.uuid4().hex[:8]}", "business_type": "retail"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    business = cast(dict[str, Any], resp.json()["data"]["business"])
    # A fresh Business defaults to visibility="private" (no public URL) —
    # promote to "unlisted" so public website endpoints can resolve it.
    assert (
        client.post(
            f"/v1/b/{business['id']}/marketplace/visibility",
            json={"visibility": "unlisted"},
            headers=headers,
        ).status_code
        == 200
    )
    return business


def _drain_generation(business_id: str) -> None:
    async def _run() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        from platform_core.services.website_generation import WebsiteGenerationService

        for _ in range(15):
            async with factory() as session:
                await poll_and_execute_jobs(session, "test-publish-worker", business_id=business_id)
                job = await WebsiteGenerationService.latest_job(
                    session, business_id=uuid.UUID(business_id)
                )
                if job is not None and job.status in {
                    "completed",
                    "fallback_used",
                    "failed",
                    "superseded",
                }:
                    break
        await engine.dispose()

    asyncio.run(_run())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_publish_and_public_render(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business = _create_business(client, headers)
    bid = business["id"]
    slug = business["slug"]
    _drain_generation(bid)

    patched = None
    for _ in range(3):
        site = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]
        home = next(p for p in site["draft"]["pages"] if p["slug"] == "home")
        hero = next(s for s in home["sections"] if s["section_type_id"] == "hero")
        patched = client.patch(
            f"/v1/b/{bid}/website/sections/{hero['id']}",
            json={"content": {"headline": "Ready to publish", "subheadline": "Launch ready"}},
            headers=headers,
        )
        if patched.status_code == 200:
            break
        if patched.status_code != 422:
            raise AssertionError(patched.text)
        _drain_generation(bid)
    assert patched is not None and patched.status_code == 200, patched.text if patched else "no patch"
    assert patched.json()["data"]["content"]["headline"] == "Ready to publish"
    refreshed = client.get(f"/v1/b/{bid}/website", headers=headers).json()["data"]
    home = next(p for p in refreshed["draft"]["pages"] if p["slug"] == "home")
    hero = next(s for s in home["sections"] if s["section_type_id"] == "hero")
    assert hero["content"]["headline"] == "Ready to publish"

    preview = client.get(f"/v1/b/{bid}/website/preview-token", headers=headers)
    assert preview.status_code == 200, preview.text
    token = preview.json()["data"]["token"]
    assert preview.json()["data"]["draft_version_id"] == refreshed["draft"]["id"]

    preview_public = client.get(f"/v1/public/websites/{slug}?preview_token={token}")
    assert preview_public.status_code == 200, preview_public.text
    assert preview_public.json()["data"]["is_preview"] is True
    assert preview_public.headers.get("cache-control") == "no-store"
    preview_hero = next(
        s
        for s in preview_public.json()["data"]["page"]["sections"]
        if s["section_type_id"] == "hero"
    )
    assert preview_hero["content"]["headline"] == "Ready to publish"

    publish = client.post(f"/v1/b/{bid}/website/publish", headers=headers)
    assert publish.status_code == 200, publish.text
    assert publish.json()["data"]["website"]["status"] == "published"

    public = client.get(f"/v1/public/websites/{slug}")
    assert public.status_code == 200, public.text
    assert public.json()["data"]["is_preview"] is False
    public_sections = public.json()["data"]["page"]["sections"]
    public_hero = next(s for s in public_sections if s["section_type_id"] == "hero")
    assert public_hero["content"]["headline"] == "Ready to publish", [
        (s["section_type_id"], (s.get("content") or {}).get("headline"))
        for s in public_sections
    ]

    async def _check_outbox() -> None:
        url = get_database_url()
        assert url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            events = await session.execute(
                select(PlatformOutboxEvent).where(
                    PlatformOutboxEvent.business_id == uuid.UUID(bid),
                    PlatformOutboxEvent.event_type == "website.published",
                )
            )
            assert events.scalars().first() is not None
        await engine.dispose()

    asyncio.run(_check_outbox())


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_preview_token_expiry(owner: tuple[dict[str, str], uuid.UUID]) -> None:
    headers, _ = owner
    client = TestClient(app)
    business = _create_business(client, headers)
    slug = business["slug"]
    expired = jwt.encode(
        {
            "typ": "website_preview",
            "business_id": business["id"],
            "website_id": str(uuid.uuid4()),
            "draft_version_id": str(uuid.uuid4()),
            "slug": slug,
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    resp = client.get(f"/v1/public/websites/{slug}?preview_token={expired}")
    assert resp.status_code in (400, 422)


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_preview_resolves_while_business_is_still_private(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """The owner can preview a draft before the Business is public at all.

    `_create_business` promotes to "unlisted" so the public endpoints resolve,
    which is right for the publish tests but hides this case: a Business is
    private from creation until someone deliberately lists it, and previewing
    the draft is what an owner does *before* making that decision. Resolving
    the Business through the anonymous path first made preview 404 for exactly
    that window, so this creates one and leaves it private.
    """
    headers, _ = owner
    client = TestClient(app)
    resp = client.post(
        "/v1/platform/businesses",
        json={"display_name": f"Private Co {uuid.uuid4().hex[:8]}", "business_type": "retail"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    business = cast(dict[str, Any], resp.json()["data"]["business"])
    bid = business["id"]
    slug = business["slug"]
    _drain_generation(bid)

    token = client.get(f"/v1/b/{bid}/website/preview-token", headers=headers).json()["data"][
        "token"
    ]

    preview = client.get(f"/v1/public/websites/{slug}?preview_token={token}")
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["is_preview"] is True

    # Tenant isolation must be unchanged: no token, no public site.
    assert client.get(f"/v1/public/websites/{slug}").status_code == 404


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_a_new_website_never_shows_customers_instructions_for_the_owner(
    owner: tuple[dict[str, str], uuid.UUID],
) -> None:
    """The first draft is customer-facing from the start: publishing it before the
    interview must not show "complete your business interview" to customers."""
    headers, _ = owner
    client = TestClient(app)
    business = _create_business(client, headers)
    site = client.get(f"/v1/b/{business['id']}/website", headers=headers).json()["data"]
    text = json.dumps(site["draft"]["pages"])
    assert "Your website starts here" not in text and "business interview" not in text
