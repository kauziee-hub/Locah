"""Website creative v4 — the owner path, against a real database.

Build through the ordinary interview; talk to LOCAH while personalization is
still pending; then run the real worker job with Gemini stubbed only at its
boundary (the creative plan, the image bytes, the storage upload). What must
hold:

* pictures are planned and drawn by default (no photos ≠ no pictures);
* the page is composed after the model chose its direction, so every picture
  is drawn in that direction's world;
* an owner change made during personalization is kept — never discarded as
  "superseded" — and untouched sections take the personalized version;
* an owner who asked for a text-led site gets no drawn pictures.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from platform_core.interview.draft_merge import base_fingerprints, merge, section_fingerprint
from platform_core.website.image_generation import GeneratedImage
from platform_testing.phase_b import db_url, sql
from test_start_conversation import owner  # noqa: F401 — the signed-in owner fixture
from test_website_conversation import Talk, every_section, of

PNG = GeneratedImage(mime_type="image/png", bytes=b"\x89PNG draft", model="stub", latency_ms=1, prompt="")


# ------------------------------------------------------------------ pure merge


def _draft(sections_: list[dict[str, Any]], theme: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"pages": [{"slug": "home", "sections": sections_}], "theme": theme or {"a": 1}, "navigation": []}


def _s(kind: str, **content: Any) -> dict[str, Any]:
    return {"section_type_id": kind, "content": content, "layout_variant": "x", "is_visible": True}


def test_merge_keeps_what_the_owner_changed_and_takes_the_rest() -> None:
    built = _draft([_s("hero", headline="Ishant Proteins"), _s("product_showcase", items=[1]), _s("contact")])
    base = base_fingerprints(built)
    live = _draft([_s("hero", headline="Ishant Proteins"), _s("product_showcase", items=[1, "prawns"]),
                   _s("contact")], theme={"a": 2})
    personalized = {"pages": [{"slug": "home", "sections": [
        _s("hero", headline="Fresh cuts, closer to home."), _s("product_showcase", items=[1]),
        _s("about", body="story"), _s("contact")]}], "navigation": [], "theme_hints": {"a": 3}}
    merged, kept = merge(personalized, live, base)
    assert merged is not None
    got = {s["section_type_id"]: s["content"] for s in merged["pages"][0]["sections"]}
    assert got["hero"]["headline"] == "Fresh cuts, closer to home."  # untouched → personalized
    assert got["product_showcase"]["items"] == [1, "prawns"]  # owner's change stands
    assert "about" in got  # new in personalization
    assert merged["theme_hints"]["a"] == 2 and set(kept) == {"product_showcase", "theme"}


def test_merge_respects_a_section_the_owner_removed_or_added() -> None:
    built = _draft([_s("hero"), _s("fulfilment_strip"), _s("contact")])
    base = base_fingerprints(built)
    live = _draft([_s("hero"), _s("contact"), _s("gallery", title="Our shop")])
    personalized = {"pages": [{"slug": "home", "sections": [_s("hero", headline="New"), _s("fulfilment_strip"),
                                                            _s("contact")]}], "navigation": [], "theme_hints": {}}
    merged, _ = merge(personalized, live, base)
    assert merged is not None
    kinds = [s["section_type_id"] for s in merged["pages"][0]["sections"]]
    assert "fulfilment_strip" not in kinds and "gallery" in kinds and kinds.index("gallery") < kinds.index("contact")


def _site(**pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"pages": [{"slug": slug, "title": slug.title(), "page_type": "custom", "sections": secs}
                      for slug, secs in pages.items()],
            "theme": {"dna": {"display": "Fraunces"}}, "navigation": [{"label": "Menu", "path": "/menu"}]}


def test_regenerating_one_section_takes_only_that_section() -> None:
    from platform_core.interview.draft_merge import replace_scope, section_key

    live = _site(home=[{**_s("hero", headline="Owner's own words"), "id": "h"},
                       {**_s("statement", text="old"), "id": "s1"},
                       {**_s("statement", text="old too"), "id": "s2", "module_binding": {"m": 1}},
                       {**_s("contact"), "id": "c"}],
                 menu=[{**_s("menu_section", title="Menu, as edited"), "id": "m"}])
    fresh = {"pages": [{"slug": "home", "sections": [_s("hero", headline="Fresh"), _s("statement", text="new"),
                                                     _s("statement", text="new too"), _s("contact")]},
                       {"slug": "menu", "sections": [_s("menu_section", title="Fresh menu")]}],
             "navigation": [], "theme_hints": {"dna": {"display": "Other"}, "generation": {"stage": "x"}}}
    key = section_key(live["pages"][0]["sections"], "s2")
    assert key == "statement#1"
    merged, why = replace_scope(fresh, live, {"page": "home", "section": key})
    assert merged is not None and not why
    home = merged["pages"][0]["sections"]
    assert [s["content"].get("text") or s["content"].get("headline") for s in home[:3]] == [
        "Owner's own words", "old", "new too"]  # only the asked-for section is new
    assert merged["pages"][1]["sections"][0]["content"]["title"] == "Menu, as edited"
    assert merged["theme_hints"]["dna"]["display"] == "Fraunces"  # the site keeps its look
    assert merged["navigation"] == live["navigation"]
    assert home[2].get("module_binding") is None  # the fresh section stands on its own


def test_regenerating_a_page_takes_that_page_and_keeps_every_other() -> None:
    from platform_core.interview.draft_merge import replace_scope

    live = _site(home=[{**_s("hero", headline="Kept"), "id": "h", "module_binding": {"k": 1}}],
                 menu=[{**_s("menu_section", title="Old menu"), "id": "m"}])
    fresh = {"pages": [{"slug": "home", "sections": [_s("hero", headline="Fresh")]},
                       {"slug": "menu", "sections": [_s("menu_section", title="Fresh menu"), _s("cta_band")]}],
             "navigation": [], "theme_hints": {}}
    merged, _ = replace_scope(fresh, live, {"page": "menu"})
    assert merged is not None
    assert merged["pages"][0]["sections"][0]["content"]["headline"] == "Kept"
    assert merged["pages"][0]["sections"][0]["module_binding"] == {"k": 1}
    assert [s["section_type_id"] for s in merged["pages"][1]["sections"]] == ["menu_section", "cta_band"]
    # A page the fresh composition does not have cannot be regenerated: nothing changes.
    none, why = replace_scope(fresh, live, {"page": "visit"})
    assert none is None and "visit" in why


def test_a_fingerprint_ignores_ids_and_asset_urls() -> None:
    a = {**_s("hero", headline="x"), "id": "1", "assets": {"image_asset_id": {"url": "u"}}}
    assert section_fingerprint(a) == section_fingerprint(_s("hero", headline="x"))


# ------------------------------------------------------------ the owner path

pytestmark_db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")


def _run_job(job_id: str) -> None:
    from platform_core.services.website_generation import WebsiteGenerationService

    async def _go() -> None:
        engine = create_async_engine(db_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as session:
                await WebsiteGenerationService.execute_job(
                    session, generation_job_id=uuid.UUID(job_id), correlation_id=str(uuid.uuid4()))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_go())


@pytest.fixture
def gemini_stubbed(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Gemini at its boundary only: a creative plan, image bytes, a storage upload."""
    from unittest.mock import AsyncMock

    import platform_core.interview.creative_director as cd
    import platform_core.interview.media_director as md
    import platform_core.media.supabase_storage as storage
    import platform_core.website.image_generation as images
    from platform_core.interview.website_copy import WebsiteCopy

    seen: dict[str, list[str]] = {"prompts": [], "order": []}
    monkeypatch.setattr(images, "image_generation_available", lambda: True)

    async def plan(bp: Any, business_type: str | None = None, *, provider: Any = None,
                   media_expected: bool | None = None) -> Any:
        seen["order"].append("creative")
        direction = cd.direct(bp, business_type, cd.CreativeChoices(), media_expected=media_expected)
        direction.model_choices = cd.CreativeChoices().model_dump()
        copy = WebsiteCopy(headline="Fresh cuts, closer to home.", headline_accent="closer to home",
                           about_body="Cut to order in Nookampalayam.")
        return direction, copy, None, 5

    async def draw(prompt: str, *, aspect_ratio: str = "16:9", timeout_seconds: int = 60) -> Any:
        seen["order"].append("image")
        seen["prompts"].append(prompt)
        return PNG, ""

    monkeypatch.setattr(cd, "generate_creative_plan", plan)
    monkeypatch.setattr(md, "generate_image", draw)
    monkeypatch.setattr(storage, "put_generated_object", AsyncMock())
    monkeypatch.setattr(storage, "public_url", lambda bucket, key: f"https://storage.test/{bucket}/{key}")
    return seen


def _meat_shop(client: TestClient, owner: dict[str, str]) -> Talk:  # noqa: F811
    started = client.post("/v1/platform/businesses/start", headers=owner, json={
        "category_key": "fresh_grocery", "subcategory_key": "meat_shop"}).json()["data"]
    business_id = started["business"]["id"]
    headers = {**owner, "X-Business-Id": business_id, "X-Operating-Context": "business"}
    talk = Talk(client, headers, business_id)
    talk.say("Ishant Proteins is a meat shop. We sell chicken, mutton and fish by the kg and people "
             "order on WhatsApp.")
    talk.send("correct", slot="name", values=[], text="Ishant Proteins")
    talk.say("We deliver around Nookampalayam and Perumbakkam, people can also pick up from the shop.")
    talk.say("Nookampalayam Road, Chennai. WhatsApp 8754722026.")
    talk.send("catalogue", catalogue=[{"group": "Chicken", "price": "240", "unit": "per kg"}])
    return talk


@pytestmark_db
def test_owner_changes_during_personalization_are_kept_and_pictures_are_drawn(
    owner, gemini_stubbed,  # noqa: F811
) -> None:
    with TestClient(app) as client:
        talk = _meat_shop(client, owner)
        data = talk.send("build")
        bp = data["blueprint"]
        assert bp["visual_consent"] != "none"
        # Pictures were planned before the design: an image-led composition.
        assert any(p["key"] == "hero" and p["source"] == "gemini_generated" for p in bp["media_plan"])
        built = talk.site()
        assert built["theme"]["hero_style"] in {"commerce_split", "editorial_overlay", "cinematic",
                                                "airy_split", "full_width", "editorial_split"}
        job_id = bp["completion_state"]["generation_job_id"]

        # The owner keeps talking while personalization is still queued.
        talk.say("Can you make the website warmer?")
        talk.say("We also sell prawns.")
        mine = talk.site()

        _run_job(job_id)
        status, usage = sql("select status, provider_usage from website_generation_jobs where id = :j",
                            j=job_id)[0]
        assert status == "completed", usage
        assert "theme" in usage["owner_edits_kept"]
        after = talk.site()
        hero = of(after, "hero")
        assert hero["content"]["headline"] == "Fresh cuts, closer to home."  # untouched: personalized
        assert hero["content"].get("image_asset_id")  # drawn, in the site's world
        # Provenance: a LOCAH draft says so, and records its slot, job and prompt version.
        asset_id = hero["content"]["image_asset_id"]
        source, slot, gen_job, version, approval = sql(
            "select source_type, generated_for, generation_job_id, prompt_version, approval_state "
            "from media_assets where id = :a", a=asset_id)[0]
        assert (source, slot, str(gen_job), approval) == ("gemini_generated", "hero", job_id, "draft")
        assert version.startswith("media-v4")
        assert hero["assets"]["image_asset_id"]["draft"] is True
        kept = talk.client.post(f"/v1/b/{talk.id}/media/{asset_id}/approve", headers=talk.headers)
        assert kept.status_code == 200, kept.text
        assert of(talk.site(), "hero")["assets"]["image_asset_id"]["draft"] is False
        assert after["theme"]["palette_key"] == mine["theme"]["palette_key"]  # the owner's "warmer" stands
        assert "Prawns" in str(after)
        # Model first, then pictures — every drawing in one site look (light and
        # grade), and none showing what the shop sells (the drawing rule).
        assert gemini_stubbed["order"][0] == "creative"
        from platform_core.website.media_prompts import unsafe_drawing

        looks = {p.split("Light: ", 1)[1].split(" Wide,")[0] for p in gemini_stubbed["prompts"]}
        assert len(looks) == 1
        assert all(unsafe_drawing(p) == "" for p in gemini_stubbed["prompts"])
        story = [s for s in every_section(after) if s["section_type_id"] == "about"]
        assert story and story[0]["content"].get("image_asset_id")


@pytestmark_db
def test_a_text_led_owner_gets_no_drawn_pictures(owner, gemini_stubbed) -> None:  # noqa: F811
    with TestClient(app) as client:
        talk = _meat_shop(client, owner)
        talk.say("Please keep the website text only, no pictures at all.")
        data = talk.send("build")
        assert data["blueprint"]["visual_consent"] == "none"
        _run_job(data["blueprint"]["completion_state"]["generation_job_id"])
        assert gemini_stubbed["prompts"] == []
        assert not of(talk.site(), "hero")["content"].get("image_asset_id")
