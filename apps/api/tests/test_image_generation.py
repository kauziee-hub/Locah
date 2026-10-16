"""Image prompts and the image provider boundary. No live provider network."""

import base64
from typing import Any

import httpx
import pytest

from platform_core.website import image_generation
from platform_core.website.image_generation import (
    gemini_image_body,
    gemini_image_from,
    generate_image_bytes,
    image_generation_available,
    logo_prompt,
)
from platform_core.website.media_prompts import ShootBrief, build_prompt, shoot_brief

# Image calls here go to a recording stub client; the backstop stays on.
pytestmark = pytest.mark.usefixtures("stubbed_ai_transport")

_DIRECTION = {"image_style": "home-style South Indian food in clay and brass bowls on banana leaf",
              "hero": "editorial_overlay",
              "palette": {"mode": "light", "primary": "#2f5d1f", "accent": "#c8922a"}}


def test_every_picture_of_a_site_shares_one_shoot_brief() -> None:
    brief = shoot_brief(_DIRECTION)
    hero = build_prompt(subject="podis and pickles", purpose="hero", truth_class="mood", brief=brief,
                        trade="home food", hero_style="editorial_overlay")
    item = build_prompt(subject="Idli podi (Podis)", purpose="item", truth_class="representative",
                        brief=brief, trade="home food")
    shared = brief.sentence()
    assert shared in hero and shared in item
    assert "banana leaf" in hero and "#2f5d1f" in hero
    assert "calm darker space on the left" in hero  # framed for the composition that holds it
    for prompt in (hero, item):
        assert "photograph" in prompt and "No text" in prompt and "No people" in prompt


def test_no_picture_carries_a_real_brand() -> None:
    # The first real gym hero printed an equipment maker's name on the rack:
    # realistic equipment is wanted, an accidental endorsement is not.
    brief = shoot_brief({"palette": {"mode": "dark"}, "image_style": "barbell gym, racks and plates"})
    photo = build_prompt(subject="squat racks and bumper plates", purpose="hero", truth_class="mood",
                         brief=brief, trade="gym", hero_style="cinematic")
    graphic = build_prompt(subject="gym", purpose="hero", truth_class="graphic", brief=brief, trade="gym")
    for prompt in (photo, graphic):
        for rule in ("no brand names, trademarks or manufacturer markings on equipment",
                     "no branded logos", "no branded clothing", "no branded product packaging"):
            assert rule in prompt
    assert "squat racks and bumper plates" in photo  # the equipment itself stays


def test_a_dark_site_is_shot_low_key_and_a_light_one_airy() -> None:
    dark = shoot_brief({"palette": {"mode": "dark"}, "image_style": "gym"})
    light = shoot_brief({"palette": {"mode": "light"}, "image_style": "gym"})
    assert "low-key" in dark.light and "daylight" in light.light


def test_a_factual_picture_is_never_drawn() -> None:
    with pytest.raises(ValueError):
        build_prompt(subject="Aranya Greens", purpose="item", truth_class="factual",
                     brief=ShootBrief("x", "y", "z", "w"), trade="developer")


def test_prompts_carry_no_numbers_or_prices() -> None:
    prompt = build_prompt(subject="Chicken curry cut ₹240 per 1 kg", purpose="category",
                          truth_class="representative", brief=shoot_brief(_DIRECTION), trade="meat shop")
    assert "240" not in prompt and "₹" not in prompt
    graphic = build_prompt(subject="waves", purpose="background", truth_class="graphic",
                           brief=shoot_brief(_DIRECTION), trade="spa")
    assert "illustration" in graphic and "Not a photograph" in graphic


def test_logo_is_a_single_letter_monogram() -> None:
    prompt = logo_prompt(initial="teakwood", primary="#6b3e26")
    assert "letter T" in prompt and "#6b3e26" in prompt
    assert "no other letters" in prompt


def test_gemini_request_and_response_shape() -> None:
    body = gemini_image_body("draw", "16:9")
    assert body["generationConfig"] == {
        "responseModalities": ["IMAGE"],
        "imageConfig": {"aspectRatio": "16:9"},
    }
    png = b"\x89PNG fake"
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "here you go"},
                        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}},
                    ]
                }
            }
        ]
    }
    assert gemini_image_from(payload) == ("image/png", png)
    assert gemini_image_from({"candidates": []}) is None


def test_availability_follows_the_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-present")
    # Gemini drawing is an explicit opt-in; an old xAI key switches nothing on.
    assert image_generation_available() is False
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    assert image_generation_available() is False  # named, but no key
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")
    assert image_generation_available() is True
    monkeypatch.delenv("IMAGE_PROVIDER")
    assert image_generation_available() is False  # the default is stock photos, not drawing
    monkeypatch.setenv("IMAGE_PROVIDER", "xai")
    assert image_generation_available() is False
    monkeypatch.setenv("IMAGE_PROVIDER", "none")
    assert image_generation_available() is False


class _Recorder:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def client(self, *args, **kwargs):  # noqa: ANN002, ANN003
        recorder = self

        class _Client:
            async def __aenter__(self):  # noqa: ANN204
                return self

            async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
                return False

            async def post(self, url, headers, json):  # noqa: ANN001, ANN201
                recorder.calls.append((url, headers, json))
                return recorder.response

        return _Client()


@pytest.mark.asyncio
async def test_gemini_generation_sends_the_key_in_a_header_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_IMAGE_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-secret")
    png = b"\x89PNG bytes"
    recorder = _Recorder(
        httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"inlineData": {"mimeType": "image/png",
                                                            "data": base64.b64encode(png).decode()}}]}}
                ]
            },
        )
    )
    monkeypatch.setattr(image_generation.httpx, "AsyncClient", recorder.client)
    result = await generate_image_bytes("draw", aspect_ratio="1:1")
    assert result is not None and result.bytes == png and result.mime_type == "image/png"
    url, headers, body = recorder.calls[0]
    assert url.endswith("/models/gemini-3.1-flash-image:generateContent")
    assert "g-secret" not in url and headers["x-goog-api-key"] == "g-secret"
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "1:1"}


@pytest.mark.asyncio
async def test_a_gemini_failure_does_not_spend_on_the_other_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-secret")
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    recorder = _Recorder(httpx.Response(429, json={"error": {"message": "quota"}}))
    monkeypatch.setattr(image_generation.httpx, "AsyncClient", recorder.client)
    assert await generate_image_bytes("draw") is None
    assert len(recorder.calls) == 1 and "x.ai" not in recorder.calls[0][0]
