"""Generated hero artwork and logos: drawn only on request, never over the owner's own.

No provider network and no database: the image adapter, storage and branding
writes are stand-ins, so what is asserted is the decision logic around them.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from platform_core.interview import media
from platform_core.interview.models import (
    BusinessBlueprint,
    Fact,
    InterviewCommand,
    MediaGenerationRequest,
    MediaReference,
)
from platform_core.models import Business
from platform_core.services.business_interview import BusinessInterviewService as Service
from platform_core.services.business_settings import BusinessSettingsService
from platform_core.services.media import MediaService
from platform_core.exceptions import ValidationError
from platform_core.website.image_generation import GeneratedImage
from test_business_interview import entitlements


def blueprint(*roles: str) -> BusinessBlueprint:
    bp = BusinessBlueprint(business_id=uuid4(), identity={
        "display_name": Fact(value="Teakwood Furniture Co", source="PLATFORM", confirmation="confirmed")})
    bp.known_facts["description"] = Fact(
        value="A furniture workshop making custom wardrobes and sofas.", source="USER_STATEMENT")
    bp.template_preferences.template_id = None
    bp.completion_state.generation_job_id = uuid4()
    bp.media_generation_requests = [MediaGenerationRequest(role=r, status="queued") for r in roles]
    return bp


class Adapter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, *, aspect_ratio: str = "16:9") -> GeneratedImage | None:
        self.calls.append((prompt, aspect_ratio))
        if self.fail:
            return None
        return GeneratedImage(mime_type="image/png", bytes=b"png", model="m", latency_ms=1, prompt=prompt)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    def wire(bp: BusinessBlueprint, job_status: str = "completed"):
        business = Business(id=bp.business_id, metadata_={"interview": bp.model_dump(mode="json")})
        saved: list[BusinessBlueprint] = []
        monkeypatch.setattr(Service, "load_business", AsyncMock(return_value=business))
        monkeypatch.setattr(Service, "save", AsyncMock(side_effect=lambda s, b, x: saved.append(x)))
        persist = AsyncMock(side_effect=lambda *a, **k: {"id": str(uuid4())})
        monkeypatch.setattr(MediaService, "persist_generated", persist)
        branding = AsyncMock()
        monkeypatch.setattr(BusinessSettingsService, "patch_branding", branding)
        place = AsyncMock(return_value=True)
        monkeypatch.setattr(media, "place_ready_artwork", place)
        session = AsyncMock()
        session.get.return_value = SimpleNamespace(status=job_status)
        return SimpleNamespace(session=session, saved=saved, persist=persist, branding=branding,
                               place=place, business=business)
    return wire


def test_prompts_carry_the_trade_and_colours_not_the_business():
    bp = blueprint("hero", "logo")
    hero, hero_aspect = media.prompt_for(bp.media_generation_requests[0], bp)
    logo, logo_aspect = media.prompt_for(bp.media_generation_requests[1], bp)
    # The cover is framed for the composition that will hold it, in the site's
    # own shoot brief (media_prompts) — the same as every other picture.
    assert hero_aspect in {"16:9", "4:3"} and logo_aspect == "1:1"
    assert "Part of one editorial series for this brand" in hero
    assert "Teakwood" not in hero
    assert "letter T" in logo  # the build-time monogram prompt


async def test_artwork_waits_for_personalization_instead_of_touching_the_draft(wired):
    bp = blueprint("hero")
    w = wired(bp, job_status="running")
    await media.generate_interview_media(w.session, business_id=bp.business_id, actor_id=uuid4(),
        generation_job_id=bp.completion_state.generation_job_id, adapter=Adapter())
    final = w.saved[-1]
    assert final.media_generation_requests[0].status == "ready"
    assert final.media_assets[-1].source == "AI_GENERATED" and final.media_assets[-1].role == "hero"
    w.place.assert_not_awaited()  # personalization places it when it finishes


async def test_artwork_is_placed_once_personalization_is_done(wired):
    bp = blueprint("hero")
    w = wired(bp, job_status="completed")
    await media.generate_interview_media(w.session, business_id=bp.business_id, actor_id=uuid4(),
        generation_job_id=bp.completion_state.generation_job_id, adapter=Adapter())
    w.place.assert_awaited_once()
    assert w.persist.call_args.kwargs["alt_text"] == "AI-generated decorative artwork"


def _drawer(image: GeneratedImage | None = None, reason: str = ""):
    calls: list[tuple[str, str]] = []

    async def draw(prompt: str, aspect: str):
        calls.append((prompt, aspect))
        return image, reason

    draw.calls = calls  # type: ignore[attr-defined]
    return draw


PNG = GeneratedImage(mime_type="image/png", bytes=b"png", model="m", latency_ms=1, prompt="p")


async def test_a_requested_logo_becomes_the_brand_logo_marked_generated(wired):
    bp = blueprint("logo")
    w = wired(bp)
    draw = _drawer(PNG)
    outcome = await media.generate_interview_logo(w.session, business_id=bp.business_id,
                                                  actor_id=uuid4(), draw=draw)
    assert outcome == "ready"
    prompt, aspect = draw.calls[0]
    # Brand context only: the name and the colours, never the conversation.
    assert aspect == "1:1" and "Teakwood Furniture Co" in prompt and "wardrobes" not in prompt
    asset_id = w.branding.call_args.kwargs["raw"]["logo_asset_id"]
    final = w.saved[-1]
    assert final.logo_state == "generated"
    assert final.revision == bp.revision  # a logo arriving never makes the owner's next message stale
    assert final.media_assets[-1] == MediaReference(
        asset_id=asset_id, role="logo", label="AI-generated logo", source="AI_GENERATED")


async def test_an_uploaded_logo_is_never_replaced(wired):
    bp = blueprint("logo")
    bp.media_assets = [MediaReference(asset_id=uuid4(), role="logo", source="USER_UPLOAD")]
    w = wired(bp)
    await media.generate_interview_logo(w.session, business_id=bp.business_id, actor_id=uuid4(),
                                        draw=_drawer(PNG))
    w.branding.assert_not_awaited()
    assert w.saved[-1].media_generation_requests[0].status == "failed"


async def test_a_provider_failure_leaves_a_reason_not_a_broken_site(wired):
    bp = blueprint("hero")
    w = wired(bp)
    await media.generate_interview_media(w.session, business_id=bp.business_id, actor_id=uuid4(),
        generation_job_id=bp.completion_state.generation_job_id, adapter=Adapter(fail=True))
    hero = w.saved[-1].media_generation_requests[0]
    assert hero.status == "failed" and "usable without it" in (hero.reason or "")
    w.persist.assert_not_awaited()


@pytest.mark.parametrize("reason,words", [
    ("quota", "reached its limit"),
    ("billing", "isn't enabled"),
    ("unavailable", "isn't available"),
])
async def test_a_failed_logo_says_why_in_plain_words(wired, reason, words):
    """A quota refusal must never sound like Locah misunderstood the owner."""
    bp = blueprint("logo")
    w = wired(bp)
    await media.generate_interview_logo(w.session, business_id=bp.business_id, actor_id=uuid4(),
                                        draw=_drawer(None, reason))
    logo = w.saved[-1].media_generation_requests[0]
    assert logo.status == "failed" and words in (logo.reason or "")
    w.persist.assert_not_awaited()


async def test_the_build_job_never_draws_the_logo_a_second_time(wired):
    bp = blueprint("hero", "logo")
    w = wired(bp)
    adapter = Adapter()
    await media.generate_interview_media(w.session, business_id=bp.business_id, actor_id=uuid4(),
        generation_job_id=bp.completion_state.generation_job_id, adapter=adapter)
    assert len(adapter.calls) == 1 and adapter.calls[0][1] in {"16:9", "4:3"}


async def test_a_stale_job_does_nothing(wired):
    bp = blueprint("hero")
    w = wired(bp)
    adapter = Adapter()
    await media.generate_interview_media(w.session, business_id=bp.business_id, actor_id=uuid4(),
        generation_job_id=uuid4(), adapter=adapter)
    assert adapter.calls == [] and w.saved == []


async def test_the_owner_can_ask_for_a_logo_but_not_over_their_own(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")  # a logo can only be drawn, and drawing is opt-in
    bp = blueprint()
    business = Business(id=bp.business_id, version=1, metadata_={"interview": bp.model_dump(mode="json")})
    monkeypatch.setattr(Service, "load_business", AsyncMock(return_value=business))
    monkeypatch.setattr(
        "platform_core.services.business_interview.BusinessEntitlementResolver.resolve",
        AsyncMock(return_value=entitlements()))
    monkeypatch.setattr(Service, "response", AsyncMock(return_value={}))
    monkeypatch.setattr("platform_core.services.business_interview.AuditService.record", AsyncMock())
    saved: list[BusinessBlueprint] = []
    monkeypatch.setattr(Service, "save", AsyncMock(side_effect=lambda s, b, x: saved.append(x)))
    await Service.execute(AsyncMock(), bp.business_id, InterviewCommand(
        action="image", image_role="logo", revision=0, request_id=uuid4()),
        actor_id=uuid4(), correlation_id="c")
    # Queued at once, drawn in the background while the owner carries on.
    assert [(r.role, r.status) for r in saved[-1].media_generation_requests] == [("logo", "queued")]
    assert saved[-1].logo_state == "generation_requested"

    bp.media_assets = [MediaReference(asset_id=uuid4(), role="logo", source="USER_UPLOAD")]
    business.metadata_ = {"interview": bp.model_dump(mode="json")}
    with pytest.raises(ValidationError):
        await Service.execute(AsyncMock(), bp.business_id, InterviewCommand(
            action="image", image_role="logo", revision=0, request_id=uuid4()),
            actor_id=uuid4(), correlation_id="c")


class _Rows:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _Session:
    """Answers the two reads `_theme_with_logo` makes: the profile's logo id, then the asset."""

    def __init__(self, logo_id, asset):
        self.answers = [logo_id, asset]

    async def execute(self, _stmt):
        return _Rows(self.answers.pop(0))


async def test_the_business_logo_reaches_the_site_header():
    """Live: a drawn logo sat on the profile and never reached the site."""
    from types import SimpleNamespace

    from platform_core.services.website_publish import _theme_with_logo

    logo = uuid4()
    asset = SimpleNamespace(public_url="https://cdn.example/logo.png")
    theme = await _theme_with_logo(_Session(logo, asset), uuid4(), {"primary_color": "#123"})
    assert theme == {"primary_color": "#123", "logo_url": "https://cdn.example/logo.png"}
    # A logo already chosen for the site is left alone; no logo, no key.
    kept = await _theme_with_logo(_Session(None, None), uuid4(), {"logo_url": "https://x/own.png"})
    assert kept["logo_url"] == "https://x/own.png"
    assert "logo_url" not in await _theme_with_logo(_Session(None, None), uuid4(), {})
