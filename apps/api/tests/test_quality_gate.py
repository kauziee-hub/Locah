"""The static hard gates every built website is checked against (shadow mode).

Founder decision 1 (Website Quality Program, 2026-11-25): beyond the rubric, a
site must never show one photo twice on a page, raw chat-speak, an AI drawing
standing in for the business's own place, people or products, or a first
section without its primary action. Shadow mode records and logs the verdict
on every generated draft; it never holds a site back, never certifies one, and
is not shown to the owner.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from test_website_certification import PASSED, _business_with_draft, _certify, _run, owner  # noqa: F401

from platform_core.website import quality_gate
from platform_core.website.quality_gate import chat_speak, check

PHOTO, OTHER, DRAWN = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
SOURCES = {PHOTO: "stock_unsplash", OTHER: "owner_uploaded", DRAWN: "cloudflare_generated"}


def _home(*sections: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"slug": "home", "page_type": "home",
             "sections": [{"sort_order": i, "is_visible": True, **s} for i, s in enumerate(sections)]}]


HERO: dict[str, Any] = {"section_type_id": "hero", "content": {"headline": "Fresh bakes daily", "cta_label": "Order now",
                                               "cta_url": "/order", "image_asset_id": PHOTO}}


def _gates(verdict: dict[str, Any]) -> list[str]:
    return list(verdict["failed_gates"])


def test_a_clean_draft_passes_and_names_the_gates_only_a_render_can_answer() -> None:
    verdict = check(_home(HERO, {"section_type_id": "about", "content": {"body": "We bake at 5 am.",
                                                                         "image_asset_id": OTHER}}), SOURCES)
    assert verdict["status"] == "pass" and verdict["failures"] == []
    assert set(verdict["gates"]) == {"photo_twice", "chat_speak", "drawn_as_business", "primary_action"}
    assert "lcp_mobile" in verdict["unchecked"] and "axe_serious" in verdict["unchecked"]


def test_the_same_photo_twice_on_one_page_fails() -> None:
    story = {"section_type_id": "about", "content": {"body": "Since 1998.", "image_asset_id": PHOTO}}
    verdict = check(_home(HERO, story), SOURCES)
    assert verdict["status"] == "repair" and _gates(verdict) == ["photo_twice"]
    # The same photo on two different pages is not this gate.
    other_page = {"slug": "about", "page_type": "about", "sections": [{**story, "sort_order": 0}]}
    assert check([*_home(HERO), other_page], SOURCES)["status"] == "pass"


def test_raw_chat_speak_fails_but_initials_names_and_ordinals_do_not() -> None:
    faq = {"section_type_id": "faq", "content": {"items": [
        {"question": "How do I join?", "answer": "Ppl shud book trial first then join."}]}}
    verdict = check(_home(HERO, faq), SOURCES)
    assert _gates(verdict) == ["chat_speak"] and "Ppl" in verdict["failures"][0]["detail"]
    assert chat_speak("hsr layout blr") == ["blr"]
    assert chat_speak("book online n pay") == ["n"]
    assert chat_speak("Dr. U. Lakshmi, 2nd floor, HYD Road, Rock n Roll Cafe") == []
    # Keys that are not words on the page are not read.
    assert check(_home({**HERO, "content": {**HERO["content"], "cta_url": "/u/pls"}}), SOURCES)["status"] == "pass"


def test_a_drawing_never_stands_in_for_the_business() -> None:
    rooms = {"section_type_id": "product_showcase", "content": {"items": [
        {"title": "Garden room", "image_asset_id": DRAWN}]}}
    verdict = check(_home(HERO, rooms), SOURCES)
    assert _gates(verdict) == ["drawn_as_business"]
    gallery = {"section_type_id": "gallery", "content": {"image_asset_ids": [DRAWN]}}
    assert _gates(check(_home(HERO, gallery), SOURCES)) == ["drawn_as_business"]
    # As a mood picture — the land around a stay behind its statement — it may.
    statement = {"section_type_id": "statement", "content": {"text": "Wake to mist.", "image_asset_id": DRAWN}}
    assert check(_home(HERO, statement), SOURCES)["status"] == "pass"
    # A composed section is read by its role: a story's picture block is mood,
    # a featured offering's is the business (mistwood draft, 2026-11-25).
    block = {"kind": "picture", "slot": "picture", "image_asset_id": DRAWN}
    story = {"section_type_id": "composition", "content": {"role": "story", "items": [block]}}
    featured = {"section_type_id": "composition", "content": {"role": "featured", "items": [block]}}
    assert check(_home(HERO, story), SOURCES)["status"] == "pass"
    assert _gates(check(_home(HERO, featured), SOURCES)) == ["drawn_as_business"]


def test_the_home_page_opens_on_its_primary_action() -> None:
    bare = {"section_type_id": "hero", "content": {"headline": "Hello"}}
    verdict = check(_home(bare), SOURCES)
    assert _gates(verdict) == ["primary_action"]
    hidden_hero = {**HERO, "is_visible": False}
    pages = [{"slug": "home", "page_type": "home", "sections": [
        {**hidden_hero, "sort_order": 0}, {**bare, "sort_order": 1}]}]
    assert _gates(check(pages, SOURCES)) == ["primary_action"]


def test_pictures_reads_every_place_a_section_keeps_one() -> None:
    content = {"image_asset_id": "a", "image_asset_ids": ["b"], "gallery_asset_ids": ["c"],
               "items": [{"image_asset_id": "d", "image_asset_ids": ["e"]}, "not-an-item"],
               "logo_asset_id": "logo"}
    assert sorted(a for a, _ in quality_gate.pictures(content)) == ["a", "b", "c", "d", "e"]


# ---------------------------------------------------------------- shadow mode on real drafts


def _generated(client: TestClient, headers: dict[str, str]) -> str:
    """A business whose draft came out of a generation job (the deterministic
    fallback: tests never reach a model)."""
    resp = client.post("/v1/platform/businesses", json={
        "display_name": f"Gate Co {uuid.uuid4().hex[:8]}", "business_type": "restaurant"}, headers=headers)
    assert resp.status_code == 200, resp.text
    bid = str(resp.json()["data"]["business"]["id"])
    queued = client.post(f"/v1/b/{bid}/website/generate", json={}, headers=headers)
    assert queued.status_code == 200, queued.text

    async def drain(factory: Any) -> str:
        from platform_worker.job_runner import poll_and_execute_jobs

        from platform_core.services.website_generation import WebsiteGenerationService

        for _ in range(15):
            async with factory() as session:
                await poll_and_execute_jobs(session, "test-gate-worker", business_id=bid)
                job = await WebsiteGenerationService.latest_job(session, business_id=uuid.UUID(bid))
                if job is not None and job.status in {"completed", "fallback_used", "failed", "superseded"}:
                    return str(job.status)
        return "unfinished"

    assert _run(drain) in {"completed", "fallback_used"}
    return bid


def _verdicts(bid: str) -> list[dict[str, Any]]:
    async def read(factory: Any) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from platform_core.models import WebsiteCertification

        async with factory() as session:
            rows = (await session.execute(select(WebsiteCertification).where(
                WebsiteCertification.business_id == uuid.UUID(bid)))).scalars().all()
            return [{"source": r.source, "status": r.status, "result": r.result} for r in rows]

    return list(_run(read))


@pytest.mark.usefixtures("owner")
def test_every_generated_draft_gets_a_shadow_verdict_that_owners_never_see(
        owner: dict[str, str], monkeypatch: Any) -> None:  # noqa: F811
    monkeypatch.delenv("WEBSITE_CERTIFICATION", raising=False)  # the default is shadow
    client = TestClient(app)
    bid = _generated(client, owner)
    shadow = [v for v in _verdicts(bid) if v["source"].startswith("shadow:")]
    assert shadow, "a generated draft is checked"
    assert shadow[0]["status"] in {"pass", "repair"} and shadow[0]["result"]["shadow"] is True
    assert set(shadow[0]["result"]["gates"]) == set(quality_gate.GATES)
    # Not the owner's to see, and publish goes ahead (shadow never blocks).
    assert client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]["certification"]["current"] is None
    assert client.post(f"/v1/b/{bid}/website/publish", headers=owner).status_code == 200


def test_a_shadow_pass_never_certifies_a_site_under_enforce(owner: dict[str, str], monkeypatch: Any) -> None:  # noqa: F811
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "enforce")
    client = TestClient(app)
    bid = _business_with_draft(client, owner)

    async def shadow_pass(factory: Any) -> None:
        from platform_core.models import WebsiteCertification
        from platform_core.resolvers.website_resolver import WebsiteResolver
        from platform_core.services.website_certification import fingerprint

        async with factory() as session:
            website = await WebsiteResolver.resolve_website(session, business_id=uuid.UUID(bid))
            draft = await WebsiteResolver.resolve_draft_version(
                session, business_id=uuid.UUID(bid), website_id=website.id)
            session.add(WebsiteCertification(
                business_id=uuid.UUID(bid), website_id=website.id, version_id=draft.id,
                fingerprint=await fingerprint(session, version_id=draft.id), status="pass",
                owner_requests=[], result={"shadow": True}, source="shadow:test"))
            await session.commit()

    _run(shadow_pass)
    refused = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"]["reason"] == "certification_missing"
    _certify(bid, PASSED)
    assert client.post(f"/v1/b/{bid}/website/publish", headers=owner).status_code == 200


def test_off_checks_nothing(owner: dict[str, str], monkeypatch: Any) -> None:  # noqa: F811
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "off")
    bid = _generated(TestClient(app), owner)
    assert not [v for v in _verdicts(bid) if v["source"].startswith("shadow:")]
