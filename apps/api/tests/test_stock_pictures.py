"""Where a website's pictures come from now: found and verified, not drawn.

No network, no database. A scripted retriever stands in for the search and the
vision check (those are covered in test_image_retrieval.py); what is checked
here is how the MediaDirector, the Blueprint and the composed page use the
result — the truth rules, provenance, caching, the exact URL reaching the
section — and which picture source a server is configured for.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from test_site_composer import compose, meat, sections

from platform_core.exceptions import ValidationError
from platform_core.interview.creative_director import direct
from platform_core.interview.media_director import (
    draw_missing,
    pictures_expected,
    picture_for,
    plan_media,
    plan_slots,
    record,
    retrieve_missing,
    section_image_brief,
)
from platform_core.services.media import MediaService
from platform_core.website import image_generation as images
from platform_core.website.image_retrieval import FoundImage, Outcome

pytestmark = pytest.mark.usefixtures("stubbed_ai_transport")


def found(n: int) -> FoundImage:
    return FoundImage(url=f"https://images.pexels.com/photos/{n}/full.jpeg", page_url=f"https://www.pexels.com/photo/{n}/",
                      photographer="Ada", description="d", width=4000, height=2600, provider="pexels",
                      photo_id=str(n), score=90, reasons=["fits"], query="q", rounds=1, mime_type="image/jpeg")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PEXELS_API_KEY", "IMAGE_PROVIDER", "GEMINI_API_KEY", "AI_PROVIDER", "IMAGE_SEARCH_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")


# ---------------------------------------------------------------- which source a server uses
def test_with_both_keys_pictures_are_found_not_drawn(monkeypatch: pytest.MonkeyPatch) -> None:
    assert images.picture_source() is None and not images.pictures_available()
    monkeypatch.setenv("PEXELS_API_KEY", "px")
    assert images.picture_source() == "stock" and images.pictures_available()
    assert not images.image_generation_available()  # Gemini drawing is not on
    assert images.image_provider() == "stock"


def test_a_gemini_key_alone_never_switches_drawing_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")  # the voice key
    assert images.picture_source() is None


def test_found_pictures_need_a_search_key_and_a_provider_that_can_look(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PEXELS_API_KEY", "px")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert images.picture_source() is None            # nothing could check what was found
    monkeypatch.setenv("AI_PROVIDER", "replay")
    assert images.picture_source() is None            # a recording cannot judge a picture
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert images.picture_source() == "stock"          # Gemini can look, handed the bytes


def test_drawing_is_only_ever_an_explicit_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PEXELS_API_KEY", "px")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert images.picture_source() == "gemini"
    monkeypatch.setenv("IMAGE_PROVIDER", "none")
    assert images.picture_source() is None


def test_a_text_led_owner_still_gets_a_text_led_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PEXELS_API_KEY", "px")
    bp = meat()
    assert pictures_expected(bp)
    bp.visual_consent = "none"
    assert not pictures_expected(bp)


# ---------------------------------------------------------------- slots and the truth rule
@pytest.mark.asyncio
async def test_only_the_slots_the_drawing_path_would_fill_are_searched() -> None:
    bp, seen = meat(), []

    async def retriever(briefs: list[Any], concurrency: int = 3) -> list[tuple[Any, Outcome]]:
        seen.extend(briefs)
        return [(b, Outcome(found(i), "ok")) for i, b in enumerate(briefs, start=1)]

    direction = direct(bp, "other")
    results = await retrieve_missing(bp, direction, "a meat shop", retriever=retriever)
    keys = [s.key for s, _ in results]
    assert keys == [s.key for s in plan_slots(bp, direction) if s.truth_class != "factual"]
    assert keys == [b.key for b in seen]
    hero = next(b for b in seen if b.key == "hero")
    assert hero.truth_class == "mood" and hero.aspect in {"16:9", "4:3"}
    assert hero.world and hero.palette                      # the site's own look travels with the brief
    assert all("people, faces or hands" in " ".join(b.avoid) for b in seen)


@pytest.mark.asyncio
async def test_a_text_led_site_removed_slots_owner_photos_and_cached_slots_are_never_searched() -> None:
    async def retriever(briefs: list[Any], concurrency: int = 3) -> list[Any]:
        raise AssertionError("nothing should be searched")

    bp = meat()
    direction = direct(bp, "other")
    bp.visual_consent = "none"
    assert await retrieve_missing(bp, direction, "a meat shop", retriever=retriever) == []
    bp.visual_consent = "unknown"
    for slot in plan_slots(bp, direction):
        if slot.truth_class != "factual":
            record(bp, slot, uuid4(), stock=True)               # all already filled
    assert await retrieve_missing(bp, direction, "a meat shop", retriever=retriever) == []


@pytest.mark.asyncio
async def test_a_factual_slot_is_listed_but_never_searched_for() -> None:
    from platform_core.interview import media_director as md

    # An evidence-led trade: its catalogue cards are factual.
    factual_bp = meat()
    direction = direct(factual_bp, "other")
    direction.archetype = "project_portfolio"
    todo = [s for s in md.plan_slots(factual_bp, direction) if s.truth_class == "factual"]
    assert todo, "a portfolio trade should have factual slots"

    async def retriever(briefs: list[Any], concurrency: int = 3) -> list[tuple[Any, Outcome]]:
        assert all(b.truth_class != "factual" for b in briefs)
        return [(b, Outcome(None, "none_qualified")) for b in briefs]

    done = await retrieve_missing(factual_bp, direction, "a studio", retriever=retriever)
    assert all(slot.truth_class != "factual" for slot, _ in done)


# ---------------------------------------------------------------- the Blueprint and the page
def test_a_found_picture_is_recorded_as_a_stock_photo_and_cached_by_slot() -> None:
    bp = meat()
    direction = direct(bp, "other")
    plan_media(bp, direction)
    hero = next(s for s in plan_slots(bp, direction) if s.key == "hero")
    asset = uuid4()
    record(bp, hero, asset, stock=True)
    ref = next(m for m in bp.media_assets if m.asset_id == asset)
    assert ref.source == "STOCK_PHOTO" and ref.label.startswith("Stock photo")
    entry = next(p for p in bp.media_plan if p.key == "hero")
    assert (entry.source, entry.status, entry.asset_id) == ("stock_retrieved", "ready", asset)
    assert picture_for(bp, "hero") == str(asset)
    # Re-planning keeps the source honest: it was found, not drawn.
    plan_media(bp, direction)
    assert next(p for p in bp.media_plan if p.key == "hero").source == "stock_retrieved"


def test_a_slot_that_found_nothing_is_failed_with_its_reason_and_stays_empty() -> None:
    bp = meat()
    direction = direct(bp, "other")
    plan_media(bp, direction)
    story = next(s for s in plan_slots(bp, direction) if s.key == "story")
    record(bp, story, None, "none_qualified", stock=True)
    entry = next(p for p in bp.media_plan if p.key == "story")
    assert entry.status == "failed" and entry.reason == "none_qualified" and entry.asset_id is None
    assert picture_for(bp, "story") is None
    assert not any(m.source == "STOCK_PHOTO" for m in bp.media_assets)


def test_the_composed_page_carries_the_asset_id_never_the_url() -> None:
    bp = meat()
    direction = direct(bp, "other")
    plan_media(bp, direction)
    ids: dict[str, UUID] = {}
    for slot in plan_slots(bp, direction):
        if slot.truth_class != "factual":
            ids[slot.key] = uuid4()
            record(bp, slot, ids[slot.key], stock=True)
    page = compose(bp)
    found_sections = sections(page)
    assert found_sections["hero"]["content"]["image_asset_id"] == str(ids["hero"])
    assert "pexels" not in str(page)            # Doc 12 §12.6: content holds ids; URLs live on the asset


@pytest.mark.asyncio
async def test_drawing_is_unchanged_where_it_was_asked_for() -> None:
    bp = meat()
    direction = direct(bp, "other")
    seen = []

    async def draw(prompt: str, aspect: str) -> tuple[Any, str]:
        seen.append(prompt)
        return None, "quota"

    done = await draw_missing(bp, direction, "a meat shop", draw=draw)
    assert len(done) == len(seen) and all(reason == "quota" for _, _, reason in done)


# ---------------------------------------------------------------- the asset behind a found picture
class _Session:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_a_found_picture_becomes_a_url_backed_asset_with_nothing_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    store = AsyncMock()
    monkeypatch.setattr("platform_core.media.supabase_storage.put_generated_object", store)
    session = _Session()
    result = await MediaService.persist_retrieved(
        session, business_id=uuid4(), actor_id=uuid4(), purpose="website",  # type: ignore[arg-type]
        url="https://images.pexels.com/photos/9/full.jpeg", page_url="https://www.pexels.com/photo/9/",
        mime_type="image/jpeg", alt_text="Photograph: chicken", credit="Ada via Pexels", width=4000, height=2600,
        generated_for="hero", prompt_version="media-v4.2")
    asset = session.added[0]
    assert asset.public_url == "https://images.pexels.com/photos/9/full.jpeg" and asset.bucket == "external"
    assert asset.source_type == "stock_photo" and asset.approval_state == "draft" and asset.status == "ready"
    assert asset.storage_key == "https://www.pexels.com/photo/9/" and asset.original_filename == "Ada via Pexels"
    assert (asset.width, asset.height, asset.generated_for) == (4000, 2600, "hero")
    store.assert_not_called()                       # nothing was uploaded: the URL is the picture
    assert result["url"] == asset.public_url and result["source_type"] == "stock_photo"
    # The renderer's resolver treats it like any other picture.
    assert MediaService._resolved(asset)["url"] == asset.public_url


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://images.pexels.com/a.jpg", "https://evil.example/a.jpg",
                                 "https://user@images.pexels.com/a.jpg"])
async def test_a_picture_url_outside_the_allowlist_is_refused_before_it_can_become_an_asset(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    session = _Session()
    with pytest.raises(ValidationError):
        await MediaService.persist_retrieved(
            session, business_id=uuid4(), actor_id=uuid4(), purpose="website",  # type: ignore[arg-type]
            url=url, page_url="", mime_type="image/jpeg", alt_text=None, credit="x")
    assert session.added == []


# ---------------------------------------------------------------- editor pictures
def test_an_editor_picture_gets_the_same_brief_a_build_would_and_none_for_evidence() -> None:
    theme = {"creative_direction": {"archetype": "menu_commerce", "hero": "cinematic",
                                    "image_style": "rustic clay and brass", "palette": {"mode": "dark", "primary": "#112233"}}}
    hero = section_image_brief(theme, "hero", "a restaurant")
    assert hero is not None and hero.purpose == "hero" and hero.aspect == "16:9" and hero.truth_class == "mood"
    assert "rustic clay and brass" in hero.world and "low-key" in hero.light
    card = section_image_brief(theme, "product_showcase", "a restaurant", subject="Masala dosa")
    assert card is not None and card.subject == "Masala dosa" and card.truth_class == "representative"
    evidence = {"creative_direction": {"archetype": "real_estate_projects"}}
    assert section_image_brief(evidence, "product_showcase", "a developer", subject="Green Meadows") is None
    assert section_image_brief(evidence, "hero", "a developer") is not None   # mood is still fine


@pytest.mark.asyncio
async def test_the_build_places_each_found_picture_and_marks_each_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.services.business_interview import place_found_pictures

    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    bp = meat()
    direction = direct(bp, "other")
    plan_media(bp, direction)
    slots = [s for s in plan_slots(bp, direction) if s.truth_class != "factual"]
    outcomes = [(slots[0], Outcome(found(1), "ok")), (slots[1], Outcome(None, "none_qualified"))]
    session = _Session()
    placed = await place_found_pictures(session, bp, outcomes,  # type: ignore[arg-type]
                                        business_id=uuid4(), actor_id=uuid4(), generation_job_id=uuid4())
    assert placed == 1 and len(session.added) == 1
    asset = session.added[0]
    # The exact verified URL is what the asset serves, tied to the slot it was found for.
    assert asset.public_url == "https://images.pexels.com/photos/1/full.jpeg" and asset.generated_for == slots[0].key
    assert picture_for(bp, slots[0].key) == str(asset.id)
    assert picture_for(bp, slots[1].key) is None
    entries = {p.key: p for p in bp.media_plan}
    assert (entries[slots[0].key].status, entries[slots[0].key].source) == ("ready", "stock_retrieved")
    assert (entries[slots[1].key].status, entries[slots[1].key].reason) == ("failed", "none_qualified")


# ---------------------------------------------------------------- the editor and auto-fill
EDITOR_THEME = {"creative_direction": {"archetype": "menu_commerce", "hero": "cinematic"}}


@pytest.mark.asyncio
async def test_the_editors_generate_a_picture_finds_a_photograph_in_stock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.services import website_images as wi
    from platform_core.website import image_retrieval as ir

    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    monkeypatch.setattr(wi, "picture_source", lambda: "stock")
    briefs: list[Any] = []

    async def retrieve(brief: Any, **kw: Any) -> Outcome:
        briefs.append(brief)
        return Outcome(found(5), "ok")

    monkeypatch.setattr(ir, "retrieve_for_slot", retrieve)
    drew = AsyncMock()
    monkeypatch.setattr(wi, "generate_image_bytes", drew)
    session = _Session()
    asset = await wi.WebsiteImageService._obtain(
        session, business_id=uuid4(), actor_id=uuid4(), theme=EDITOR_THEME,  # type: ignore[arg-type]
        section_type="product_showcase", trade="a restaurant", subject="Masala dosa", planned=("prompt", "4:3"),
        purpose="website", alt_text="Illustrative picture: Masala dosa", original_filename="x.png",
        generated_for="editor:product_showcase:items.1")
    assert asset is not None and asset["url"] == "https://images.pexels.com/photos/5/full.jpeg"
    assert briefs[0].subject == "Masala dosa" and briefs[0].truth_class == "representative"
    drew.assert_not_called()                                  # nothing was drawn
    assert session.added[0].generated_for == "editor:product_showcase:items.1"


@pytest.mark.asyncio
async def test_no_photograph_found_means_no_picture_and_no_drawing_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.services import website_images as wi
    from platform_core.website import image_retrieval as ir

    monkeypatch.setattr(wi, "picture_source", lambda: "stock")

    async def retrieve(brief: Any, **kw: Any) -> Outcome:
        return Outcome(None, "none_qualified")

    monkeypatch.setattr(ir, "retrieve_for_slot", retrieve)
    drew = AsyncMock()
    monkeypatch.setattr(wi, "generate_image_bytes", drew)
    session = _Session()
    assert await wi.WebsiteImageService._obtain(
        session, business_id=uuid4(), actor_id=uuid4(), theme=EDITOR_THEME,  # type: ignore[arg-type]
        section_type="hero", trade="a restaurant", subject="", planned=("p", "16:9"), purpose="website",
        alt_text="a", original_filename="x.png") is None
    drew.assert_not_called()
    assert session.added == []


@pytest.mark.asyncio
async def test_gemini_drawing_still_works_where_it_is_the_chosen_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.services import website_images as wi
    from platform_core.website.image_generation import GeneratedImage

    monkeypatch.setattr(wi, "picture_source", lambda: "gemini")
    monkeypatch.setattr(wi, "generate_image_bytes",
                        AsyncMock(return_value=GeneratedImage("image/png", b"png", "m", 1, "p")))
    persisted = AsyncMock(return_value={"id": str(uuid4())})
    monkeypatch.setattr(wi.MediaService, "persist_generated", persisted)
    asset = await wi.WebsiteImageService._obtain(
        _Session(), business_id=uuid4(), actor_id=uuid4(), theme=EDITOR_THEME,  # type: ignore[arg-type]
        section_type="hero", trade="x", subject="", planned=("prompt", "16:9"), purpose="website",
        alt_text="a", original_filename="generated-section.png", generated_for="editor:hero")
    assert asset is not None and persisted.await_args.kwargs["body"] == b"png"


@pytest.mark.asyncio
async def test_the_cover_artwork_job_finds_a_photograph_in_stock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.interview import media as m
    from platform_core.website import image_retrieval as ir

    seen: list[Any] = []

    async def retrieve(brief: Any, **kw: Any) -> Outcome:
        seen.append(brief)
        return Outcome(found(8), "ok")

    monkeypatch.setattr(ir, "retrieve_for_slot", retrieve)
    photo = await m.find_hero_photo(meat())
    assert photo is not None and photo.photo_id == "8"
    assert seen[0].key == "hero" and seen[0].truth_class == "mood"


@pytest.mark.asyncio
async def test_a_found_cover_is_recorded_on_the_request_and_handed_to_placement(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.interview import media as m
    from platform_core.interview.models import MediaGenerationRequest

    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    placed = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "place_ready_artwork", placed)

    class _S(_Session):
        async def get(self, model: Any, ident: Any) -> None:   # no personalization job still running
            return None

    bp, session = meat(), _S()
    request = MediaGenerationRequest(role="hero", status="queued")
    await m._apply_hero_found(session, uuid4(), uuid4(), uuid4(), bp, request, found(8))  # type: ignore[arg-type]
    assert request.status == "ready" and request.asset_id == session.added[0].id
    ref = next(x for x in bp.media_assets if x.asset_id == request.asset_id)
    assert (ref.role, ref.source) == ("hero", "STOCK_PHOTO")
    placed.assert_awaited_once()
