"""Where a website's pictures come from now: found and verified, not drawn.

No network, no database. A scripted retriever stands in for the search and the
vision check (those are covered in test_image_retrieval.py); what is checked
here is how the MediaDirector, the Blueprint and the composed page use the
result — the truth rules, provenance, caching, the exact URL reaching the
section — which picture source a server is configured for, and how a chosen
photograph is recorded the way its source requires (Unsplash hotlinked and
credited, Pixabay copied into LOCAH's own storage).
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
from platform_core.models import MediaAsset
from platform_core.services.media import MediaService
from platform_core.website import image_generation as images
from platform_core.website.image_retrieval import FoundImage, Outcome
from platform_core.website.image_search import (
    ImageCandidate,
    MultiSearch,
    UnsplashSearch,
    get_search_provider,
    search_configured,
    search_provider_name,
)

pytestmark = pytest.mark.usefixtures("stubbed_ai_transport")

STORAGE = "https://storage.locah.test"


def _chosen(candidate: ImageCandidate) -> FoundImage:
    """A candidate as the retrieval loop hands over the one it chose."""
    return FoundImage(
        url=candidate.image_url, page_url=candidate.page_url, photographer=candidate.photographer,
        description=candidate.description, width=candidate.width, height=candidate.height,
        provider=candidate.provider, photo_id=candidate.photo_id, score=90, reasons=["fits"],
        query=candidate.query, rounds=1, mime_type="image/jpeg", credit=candidate.credit_line(),
        attribution=candidate.credit(), must_store=candidate.must_store,
        download_location=candidate.download_location, selection_reason="the closest fit for the hero",
        rubric={"business_relevance": 9, "section_fit": 8}, brief={"key": "hero", "subject": "chicken"},
        average_color=candidate.average_color,
    )


def found(n: int) -> FoundImage:
    """An Unsplash photograph: shown from Unsplash's own URL, credited with referral links."""
    return _chosen(ImageCandidate(
        provider="unsplash", photo_id=str(n), image_url=f"https://images.unsplash.com/photo-{n}?ixid=x&w=2400",
        preview_url=f"https://images.unsplash.com/photo-{n}?ixid=x&w=400", page_url=f"https://unsplash.com/photos/{n}",
        width=4000, height=2600, description="d", photographer="Ada", average_color="#aa8866",
        licence="Unsplash License", photographer_url="https://unsplash.com/@ada",
        download_location=f"https://api.unsplash.com/photos/{n}/download?ixid=x", query="q"))


def pixabay(n: int) -> FoundImage:
    """A Pixabay picture: permanent hotlinking is not allowed, so it must be copied into storage."""
    return _chosen(ImageCandidate(
        provider="pixabay", photo_id=str(n), image_url=f"https://cdn.pixabay.com/photo/2024/05/01/chicken-{n}_1280.jpg",
        preview_url=f"https://cdn.pixabay.com/photo/2024/05/01/chicken-{n}_640.jpg",
        page_url=f"https://pixabay.com/photos/chicken-{n}/", width=1280, height=853, description="chicken, meat",
        photographer="Ben", licence="Pixabay Content License",
        photographer_url=f"https://pixabay.com/users/ben-{n}/", query="q"))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("UNSPLASH_ACCESS_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY", "IMAGE_PROVIDER", "GEMINI_API_KEY",
                 "AI_PROVIDER", "IMAGE_SEARCH_PROVIDER", "IMAGE_ALLOWED_HOSTS", "SUPABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    # Most of these tests are about one keyed source; the default (both) has its own test below.
    monkeypatch.setenv("IMAGE_SEARCH_PROVIDER", "unsplash")


def _session() -> Any:
    """The fake session, typed loosely: it stands in for an AsyncSession."""
    return _Session()


# ---------------------------------------------------------------- which source a server uses
def test_with_both_keys_pictures_are_found_not_drawn(monkeypatch: pytest.MonkeyPatch) -> None:
    assert images.picture_source() is None and not images.pictures_available()
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "us-test")
    assert images.picture_source() == "stock" and images.pictures_available()
    assert not images.image_generation_available()  # Gemini drawing is not on
    assert images.image_provider() == "stock"


def test_a_gemini_key_alone_never_switches_drawing_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")  # the voice key
    assert images.picture_source() is None


def test_with_no_photo_key_at_all_real_photographs_are_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for chosen in (None, "auto", "", "multi"):                  # the default, and what auto means
        if chosen is None:
            monkeypatch.delenv("IMAGE_SEARCH_PROVIDER")
        else:
            monkeypatch.setenv("IMAGE_SEARCH_PROVIDER", chosen)
        assert search_provider_name() == "multi"
        # No keyless source is left: no key, no search, no pictures — and nothing drawn instead.
        assert not search_configured() and get_search_provider() is None
        assert images.picture_source() is None and not images.pictures_available()
        assert pictures_expected(meat()) is False
    # One key is enough for the default; both search side by side.
    monkeypatch.setenv("PIXABAY_API_KEY", "pb-test")
    assert search_configured() and images.picture_source() == "stock"
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "us-test")
    both = get_search_provider()
    assert isinstance(both, MultiSearch) and both.names() == ["unsplash", "pixabay"]
    # A key only counts for the source that was configured.
    monkeypatch.setenv("IMAGE_SEARCH_PROVIDER", "unsplash")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY")
    assert not search_configured() and get_search_provider() is None and images.picture_source() is None
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "us-test")
    assert isinstance(get_search_provider(), UnsplashSearch)


def test_found_pictures_need_a_search_key_and_a_provider_that_can_look(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "us-test")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert images.picture_source() is None            # nothing could check what was found
    monkeypatch.setenv("AI_PROVIDER", "replay")
    assert images.picture_source() is None            # a recording cannot judge a picture
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert images.picture_source() == "stock"          # Gemini can look, handed the bytes


def test_drawing_is_only_ever_an_explicit_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "us-test")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert images.picture_source() == "gemini"
    monkeypatch.setenv("IMAGE_PROVIDER", "none")
    assert images.picture_source() is None


def test_a_text_led_owner_still_gets_a_text_led_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "us-test")
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
    assert hero.concept                                     # ...and its design DNA concept
    assert "Chicken" in hero.offerings                      # only what the owner said they offer
    for brief in seen:
        avoid = " ".join(brief.avoid)
        assert "text, letters, numbers or logos" in avoid
        if brief.section_role in {"story", "process"}:
            # The work is done by people: hands may show, faces stay incidental.
            assert "faces as the main subject" in avoid and "people, faces or hands" not in avoid
        else:
            assert "people, faces or hands" in avoid


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
    assert "unsplash" not in str(page) and "pixabay" not in str(page)   # Doc 12 §12.6: ids in content


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
    session = _session()
    result = await MediaService.persist_retrieved(
        session, business_id=uuid4(), actor_id=uuid4(), purpose="website",
        url="https://images.unsplash.com/photo-9?ixid=x&w=2400", page_url="https://unsplash.com/photos/9",
        mime_type="image/jpeg", alt_text="Photograph: chicken", credit="Photo by Ada on Unsplash",
        width=4000, height=2600, generated_for="hero", prompt_version="media-v4.2")
    asset = session.added[0]
    assert asset.public_url == "https://images.unsplash.com/photo-9?ixid=x&w=2400" and asset.bucket == "external"
    assert asset.source_type == "stock_photo" and asset.approval_state == "draft" and asset.status == "ready"
    assert asset.storage_key == "https://unsplash.com/photos/9"
    assert asset.original_filename == "Photo by Ada on Unsplash"
    assert (asset.width, asset.height, asset.generated_for) == (4000, 2600, "hero")
    store.assert_not_called()                       # nothing was uploaded: the URL is the picture
    assert result["url"] == asset.public_url and result["source_type"] == "stock_photo"
    # The renderer's resolver treats it like any other picture.
    assert MediaService._resolved(asset)["url"] == asset.public_url


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://images.unsplash.com/a.jpg", "https://evil.example/a.jpg",
                                 "https://user@images.unsplash.com/a.jpg", "https://images.unsplash.com:8443/a.jpg",
                                 # Former sources are no longer allowed hosts.
                                 "https://images.pexels.com/photos/1/a.jpeg",
                                 "https://upload.wikimedia.org/wikipedia/commons/a.jpg"])
async def test_a_picture_url_outside_the_allowlist_is_refused_before_it_can_become_an_asset(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    session = _session()
    with pytest.raises(ValidationError):
        await MediaService.persist_retrieved(
            session, business_id=uuid4(), actor_id=uuid4(), purpose="website",
            url=url, page_url="", mime_type="image/jpeg", alt_text=None, credit="x")
    assert session.added == []


# ---------------------------------------------------------------- recorded the way each source requires
@pytest.mark.asyncio
async def test_an_unsplash_photo_is_hotlinked_and_keeps_its_provenance_and_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    store = AsyncMock()
    monkeypatch.setattr("platform_core.media.supabase_storage.put_generated_object", store)
    fetch = AsyncMock(side_effect=AssertionError("an Unsplash photo is never downloaded"))
    monkeypatch.setattr("platform_core.website.image_retrieval.fetch_full_image", fetch)
    photo = found(4)
    assert not photo.must_store
    session = _session()
    result = await MediaService.persist_found(
        session, business_id=uuid4(), actor_id=uuid4(), purpose="website", found=photo,
        alt_text="Photograph: chicken", generated_for="hero", prompt_version="media-v4.2")
    asset = session.added[0]
    # Shown from Unsplash's own URL, never re-hosted.
    assert asset.bucket == "external" and asset.public_url == photo.url
    assert asset.storage_key == photo.page_url and asset.size_bytes is None
    assert asset.source_type == "stock_photo" and asset.approval_state == "draft"
    assert asset.original_filename == "Photo by Ada on Unsplash"
    store.assert_not_called()
    fetch.assert_not_called()
    # Provenance: the source, its attribution, why it was chosen, and the brief to find another.
    provenance = asset.provenance
    assert provenance["kind"] == "stock_photo" and provenance["provider"] == "unsplash"
    assert provenance["photo_id"] == "4" and provenance["stored_copy"] is False
    assert provenance["attribution"] == photo.attribution
    assert provenance["attribution"]["line"] == "Photo by Ada on Unsplash"
    assert "utm_source=locah" in provenance["attribution"]["name_url"]       # Unsplash's referral links
    assert "utm_source=locah" in provenance["attribution"]["source_url"]
    assert provenance["selection_reason"] == "the closest fit for the hero"
    assert provenance["brief"] == {"key": "hero", "subject": "chicken"} and provenance["rubric"]["section_fit"] == 8
    # The site credits it: the serialized asset and the renderer's resolver both carry the credit.
    assert result["url"] == photo.url and result["credit"]["line"] == "Photo by Ada on Unsplash"
    assert MediaService._resolved(asset)["credit"] == result["credit"]


@pytest.mark.asyncio
async def test_a_pixabay_picture_is_copied_into_storage_never_hotlinked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    monkeypatch.setenv("SUPABASE_URL", STORAGE)
    body = b"\xff\xd8data"
    fetch = AsyncMock(return_value=(body, "image/jpeg"))
    monkeypatch.setattr("platform_core.website.image_retrieval.fetch_full_image", fetch)
    store = AsyncMock()
    monkeypatch.setattr("platform_core.media.supabase_storage.put_generated_object", store)
    photo = pixabay(7)
    assert photo.must_store and photo.url.startswith("https://cdn.pixabay.com/")
    business_id = uuid4()
    session = _session()
    result = await MediaService.persist_found(
        session, business_id=business_id, actor_id=uuid4(), purpose="website", found=photo,
        alt_text="Photograph: chicken", generated_for="category:chicken")
    fetch.assert_awaited_once_with(photo.url)
    asset = session.added[0]
    assert asset.bucket == "media" and asset.source_type == "stock_photo" and asset.status == "ready"
    assert asset.storage_key == f"generated/stock/{business_id}/{asset.id}.jpg"
    assert asset.size_bytes == len(body) and asset.mime_type == "image/jpeg"
    # The asset serves LOCAH's own copy, not Pixabay's link.
    assert asset.public_url != photo.url and "pixabay" not in asset.public_url
    assert asset.public_url == f"{STORAGE}/storage/v1/object/public/media/{asset.storage_key}"
    store.assert_awaited_once()
    assert store.await_args is not None
    assert store.await_args.kwargs == {"bucket": "media", "storage_key": asset.storage_key, "body": body,
                                       "mime_type": "image/jpeg"}
    assert asset.provenance["stored_copy"] is True and asset.provenance["provider"] == "pixabay"
    assert asset.provenance["page_url"] == photo.page_url              # where it came from is kept
    assert asset.original_filename == "Image by Ben from Pixabay"
    assert result["url"] == asset.public_url and result["credit"]["source"] == "Pixabay"


@pytest.mark.asyncio
async def test_a_pixabay_picture_that_cannot_be_fetched_is_not_stored_or_hotlinked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    monkeypatch.setenv("SUPABASE_URL", STORAGE)
    monkeypatch.setattr("platform_core.website.image_retrieval.fetch_full_image", AsyncMock(return_value=None))
    store = AsyncMock()
    monkeypatch.setattr("platform_core.media.supabase_storage.put_generated_object", store)
    session = _session()
    with pytest.raises(ValidationError):
        await MediaService.persist_found(
            session, business_id=uuid4(), actor_id=uuid4(), purpose="website", found=pixabay(8),
            alt_text="Photograph: chicken", generated_for="hero")
    store.assert_not_called()
    assert session.added == []


def test_a_stock_photo_is_credited_and_an_owner_upload_is_not() -> None:
    photo = found(3)
    stock = MediaAsset(id=uuid4(), business_id=uuid4(), source_type="stock_photo", bucket="external",
                       public_url=photo.url, original_filename=photo.credit, provenance=photo.provenance())
    assert MediaService.credit_of(stock) == photo.attribution
    owner = MediaAsset(id=uuid4(), business_id=uuid4(), source_type="owner_uploaded", bucket="media",
                       original_filename="my-shop.jpg")
    assert MediaService.credit_of(owner) is None
    assert MediaService.serialize(owner)["credit"] is None and "credit" not in MediaService._resolved(owner)
    # A stock photo recorded before provenance existed still credits its photographer.
    legacy = MediaAsset(id=uuid4(), business_id=uuid4(), source_type="stock_photo", bucket="external",
                        original_filename="Ada via Pexels")
    assert MediaService.credit_of(legacy) == {"line": "Ada via Pexels"}


# ---------------------------------------------------------------- editor pictures
def test_an_editor_picture_gets_the_same_brief_a_build_would_and_none_for_evidence() -> None:
    theme: dict[str, object] = {"creative_direction": {"archetype": "menu_commerce", "hero": "cinematic",
                                    "image_style": "rustic clay and brass", "palette": {"mode": "dark", "primary": "#112233"}}}
    hero = section_image_brief(theme, "hero", "a restaurant")
    assert hero is not None and hero.purpose == "hero" and hero.aspect == "16:9" and hero.truth_class == "mood"
    assert "rustic clay and brass" in hero.world and "low-key" in hero.light
    card = section_image_brief(theme, "product_showcase", "a restaurant", subject="Masala dosa")
    assert card is not None and card.subject == "Masala dosa" and card.truth_class == "representative"
    evidence: dict[str, object] = {"creative_direction": {"archetype": "real_estate_projects"}}
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
    session = _session()
    placed = await place_found_pictures(session, bp, outcomes,
                                        business_id=uuid4(), actor_id=uuid4(), generation_job_id=uuid4())
    assert placed == 1 and len(session.added) == 1
    asset = session.added[0]
    # The exact verified URL is what the asset serves, tied to the slot it was found for.
    assert asset.public_url == "https://images.unsplash.com/photo-1?ixid=x&w=2400"
    assert asset.generated_for == slots[0].key and asset.provenance["provider"] == "unsplash"
    assert picture_for(bp, slots[0].key) == str(asset.id)
    assert picture_for(bp, slots[1].key) is None
    entries = {p.key: p for p in bp.media_plan}
    assert (entries[slots[0].key].status, entries[slots[0].key].source) == ("ready", "stock_retrieved")
    assert (entries[slots[1].key].status, entries[slots[1].key].reason) == ("failed", "none_qualified")


@pytest.mark.asyncio
async def test_a_picture_that_could_not_be_stored_leaves_its_slot_failed_and_the_build_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_core.services.business_interview import place_found_pictures

    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    real = MediaService.persist_found
    tried: list[str] = []

    async def persist_found(session: Any, **kw: Any) -> dict[str, Any]:
        tried.append(kw["found"].provider)
        if kw["found"].must_store:
            raise ValidationError("The chosen picture could not be copied into storage")
        stored: dict[str, Any] = await real(session, **kw)
        return stored

    monkeypatch.setattr(MediaService, "persist_found", persist_found)
    bp = meat()
    direction = direct(bp, "other")
    plan_media(bp, direction)
    slots = [s for s in plan_slots(bp, direction) if s.truth_class != "factual"]
    outcomes = [(slots[0], Outcome(pixabay(2), "ok")), (slots[1], Outcome(found(3), "ok"))]
    session = _session()
    placed = await place_found_pictures(session, bp, outcomes,
                                        business_id=uuid4(), actor_id=uuid4(), generation_job_id=uuid4())
    assert tried == ["pixabay", "unsplash"]          # the failure did not stop the next slot
    assert placed == 1 and len(session.added) == 1
    assert session.added[0].generated_for == slots[1].key
    entries = {p.key: p for p in bp.media_plan}
    failed = entries[slots[0].key]
    assert failed.status == "failed" and failed.reason.startswith("store_failed:")
    assert failed.asset_id is None and picture_for(bp, slots[0].key) is None   # empty, never hotlinked
    request = next(r for r in bp.media_generation_requests if r.role == "visual" and r.key == slots[0].key)
    assert request.status == "failed" and (request.reason or "").startswith("store_failed:")
    assert entries[slots[1].key].status == "ready"


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
    session = _session()
    asset = await wi.WebsiteImageService._obtain(
        session, business_id=uuid4(), actor_id=uuid4(), theme=EDITOR_THEME,
        section_type="product_showcase", trade="a restaurant", subject="Masala dosa", planned=("prompt", "4:3"),
        purpose="website", alt_text="Illustrative picture: Masala dosa", original_filename="x.png",
        generated_for="editor:product_showcase:items.1")
    assert asset is not None and asset["url"] == "https://images.unsplash.com/photo-5?ixid=x&w=2400"
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
    session = _session()
    assert await wi.WebsiteImageService._obtain(
        session, business_id=uuid4(), actor_id=uuid4(), theme=EDITOR_THEME,
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
    monkeypatch.setattr(MediaService, "persist_generated", persisted)   # the class website_images calls
    asset = await wi.WebsiteImageService._obtain(
        _session(), business_id=uuid4(), actor_id=uuid4(), theme=EDITOR_THEME,
        section_type="hero", trade="x", subject="", planned=("prompt", "16:9"), purpose="website",
        alt_text="a", original_filename="generated-section.png", generated_for="editor:hero")
    assert asset is not None and persisted.await_args is not None
    assert persisted.await_args.kwargs["body"] == b"png"


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
    assert photo is not None and photo.photo_id == "8" and photo.provider == "unsplash"
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

    bp = meat()
    session: Any = _S()
    request = MediaGenerationRequest(role="hero", status="queued")
    await m._apply_hero_found(session, uuid4(), uuid4(), uuid4(), bp, request, found(8))
    assert request.status == "ready" and request.asset_id == session.added[0].id
    assert session.added[0].public_url == found(8).url               # an Unsplash cover is hotlinked
    ref = next(x for x in bp.media_assets if x.asset_id == request.asset_id)
    assert (ref.role, ref.source) == ("hero", "STOCK_PHOTO")
    placed.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_pixabay_copy_passes_the_real_storage_clients_own_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the copy was keyed `stock/...`, which put_generated_object refuses
    (it only writes under `generated/`) — every Pixabay pick would have raised in
    production. Only the HTTP transport is faked here, never the storage client."""
    import httpx

    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    monkeypatch.setenv("SUPABASE_URL", STORAGE)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "local-service-role")
    monkeypatch.setattr("platform_core.website.image_retrieval.fetch_full_image",
                        AsyncMock(return_value=(b"jpeg", "image/jpeg")))
    posted: list[str] = []

    class _Client:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        async def __aenter__(self) -> Any: return self
        async def __aexit__(self, *e: Any) -> bool: return False

        async def post(self, url: str, **kw: Any) -> httpx.Response:
            posted.append(url)
            return httpx.Response(200, json={"Key": "ok"})

    monkeypatch.setattr("platform_core.media.supabase_storage.httpx.AsyncClient", _Client)
    session = _session()
    await MediaService.persist_found(session, business_id=uuid4(), actor_id=uuid4(), purpose="website",
                                     found=pixabay(8), alt_text="x", generated_for="category:x")
    assert len(posted) == 1 and "/storage/v1/object/media/generated/stock/" in posted[0]


@pytest.mark.asyncio
async def test_storage_being_down_leaves_the_slot_empty_instead_of_failing_the_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform_core.services.media.AuditService.record", AsyncMock())
    monkeypatch.setenv("SUPABASE_URL", STORAGE)
    monkeypatch.setattr("platform_core.website.image_retrieval.fetch_full_image",
                        AsyncMock(return_value=(b"jpeg", "image/jpeg")))
    monkeypatch.setattr("platform_core.media.supabase_storage.put_generated_object",
                        AsyncMock(side_effect=RuntimeError("Storage refused generated upload (503)")))
    with pytest.raises(ValidationError):
        await MediaService.persist_found(_session(), business_id=uuid4(), actor_id=uuid4(), purpose="website",
                                         found=pixabay(9), alt_text="x", generated_for="category:x")
