"""DeepSeek is the default model provider; Gemini stays selectable.

No network: each test replaces the HTTP client with a scripted stub. These
check how requests are built and replies parsed — not that DeepSeek accepts them
live, which needs a key and has not been done.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from platform_core.ai_guard import ExternalAICallBlocked
from platform_core.website import ai_provider
from platform_core.website.ai_provider import (
    DEEPSEEK_DEFAULT_MODEL,
    AIProviderBillingError,
    AIProviderPermanentError,
    DeepSeekProvider,
    GeminiProvider,
    ImageInput,
    UnavailableAIProvider,
    get_ai_provider,
)

pytestmark = pytest.mark.usefixtures("stubbed_ai_transport")

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "name": {"type": "string", "maxLength": 5}},
          "required": ["ok"]}


def _answer(content: str, **extra: Any) -> httpx.Response:
    body = {"choices": [{"message": {"content": content, "reasoning_content": "private working"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16,
                      "completion_tokens_details": {"reasoning_tokens": 2}}}
    body.update(extra)
    return httpx.Response(200, json=body)


class Script:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def client(self, *args: Any, **kwargs: Any) -> Any:
        script = self

        class _Client:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *exc: Any) -> bool:
                return False

            async def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:  # noqa: A002
                script.calls.append({"url": url, "headers": headers, "body": json})
                return script.responses.pop(0)

        return _Client()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "DEEPSEEK_INTERVIEW_MODEL", "DEEPSEEK_WEBSITE_MODEL",
                 "DEEPSEEK_DOCUMENT_MODEL", "DEEPSEEK_VISION_MODEL", "AI_PROVIDER", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------- selection
def test_deepseek_is_the_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    provider = get_ai_provider()
    assert isinstance(provider, DeepSeekProvider) and provider.provider_name == "deepseek"
    assert provider.model_name == DEEPSEEK_DEFAULT_MODEL == "deepseek-flash"


def test_the_model_id_is_sent_exactly_as_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", "some-pinned-model")
    assert get_ai_provider().model_name == "some-pinned-model"
    monkeypatch.setenv("DEEPSEEK_MODEL", "  ")
    assert get_ai_provider().model_name == DEEPSEEK_DEFAULT_MODEL  # blank means the default, not nothing


@pytest.mark.parametrize("configured", ["DeepSeek-V4.1-Flash", "deepseek-v4.1-flash", " DEEPSEEK-V4.1-FLASH "])
def test_the_display_name_of_the_requested_model_maps_to_its_api_id(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    """DeepSeek lists the model as id `deepseek-flash`, name `DeepSeek-V4.1-Flash` (GET /models)."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", configured)
    assert get_ai_provider().model_name == "deepseek-flash"
    monkeypatch.setenv("DEEPSEEK_VISION_MODEL", configured)
    assert DeepSeekProvider("k").model_for("image.judge") == "deepseek-flash"


def test_without_a_deepseek_key_there_is_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")  # a Gemini key never switches the default provider on
    assert isinstance(get_ai_provider(), UnavailableAIProvider)


def test_gemini_remains_selectable_by_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    assert isinstance(get_ai_provider(), GeminiProvider)


@pytest.mark.parametrize("leftover", ["xai", "openai", "grok"])
def test_an_unknown_provider_is_never_a_silent_other_vendor(monkeypatch: pytest.MonkeyPatch, leftover: str) -> None:
    monkeypatch.setenv("AI_PROVIDER", leftover)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("GEMINI_API_KEY", "g-present")
    assert isinstance(get_ai_provider(), UnavailableAIProvider)


def test_per_purpose_model_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_WEBSITE_MODEL", "web-model")
    monkeypatch.setenv("DEEPSEEK_VISION_MODEL", "vision-model")
    provider = DeepSeekProvider("k")
    assert provider.model_for("website.personalization") == "web-model"
    assert provider.model_for("image.judge") == "vision-model"
    assert provider.model_for("business.interview") == DEEPSEEK_DEFAULT_MODEL


# ---------------------------------------------------------------- requests
@pytest.mark.asyncio
async def test_a_structured_request_is_built_for_the_chat_completions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(_answer(json.dumps({"ok": True, "name": "abcdefgh"})))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    provider = DeepSeekProvider("ds-secret", base_url="https://api.deepseek.com/")
    result = await provider.generate_structured(
        "hello", SCHEMA, {"purpose": "website.personalization", "system_prompt": "Be brief.",
                          "temperature": 0.4, "max_output_tokens": 500}, timeout_seconds=5)
    call = script.calls[0]
    assert call["url"] == "https://api.deepseek.com/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer ds-secret"
    assert "ds-secret" not in json.dumps(call["body"]) and "ds-secret" not in call["url"]
    body = call["body"]
    assert body["model"] == "deepseek-flash" and body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 500 and body["temperature"] == 0.4 and body["stream"] is False
    system, user = body["messages"]
    assert system["role"] == "system" and system["content"].startswith("Be brief.")
    assert '"properties"' in system["content"] and "json" in system["content"].lower()
    assert user == {"role": "user", "content": "hello"}
    # The website's strategy keeps the model's own reasoning; routine purposes skip it.
    assert "thinking" not in body
    # The answer is held to the limits the model was only told about.
    assert result == {"ok": True, "name": "abcde"}


@pytest.mark.asyncio
async def test_routine_purposes_skip_the_reasoning_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(_answer("{}"), _answer("{}"))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    provider = DeepSeekProvider("k")
    await provider.generate_structured("x", {}, {"purpose": "business.interview"}, 5)
    await provider.generate_structured("x", {}, {"purpose": "image.judge"}, 5)
    assert all(c["body"]["thinking"] == {"type": "disabled"} for c in script.calls)


@pytest.mark.asyncio
async def test_pictures_travel_as_image_url_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(_answer("{}"))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    await DeepSeekProvider("k").generate_structured_with_images(
        "judge", [ImageInput(url="https://images.pexels.com/a.jpg"), ImageInput(data=b"\xff\xd8", mime_type="image/jpeg")],
        {}, {"purpose": "image.judge"}, 5)
    parts = script.calls[0]["body"]["messages"][1]["content"]
    assert parts[0] == {"type": "image_url", "image_url": {"url": "https://images.pexels.com/a.jpg"}}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert parts[-1] == {"type": "text", "text": "judge"}  # the question comes last, after the pictures


@pytest.mark.asyncio
async def test_a_document_photo_is_read_but_a_pdf_is_refused_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(_answer("{}"))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    provider = DeepSeekProvider("k")
    await provider.generate_structured_from_file("read", b"jpg", "image/jpeg", {}, {"purpose": "document.extract"}, 5)
    assert script.calls[0]["body"]["messages"][1]["content"][0]["type"] == "image_url"
    with pytest.raises(AIProviderPermanentError, match="not application/pdf"):
        await provider.generate_structured_from_file("read", b"%PDF", "application/pdf", {},
                                                     {"purpose": "document.extract"}, 5)
    assert len(script.calls) == 1  # nothing was sent for the PDF


# ---------------------------------------------------------------- replies
@pytest.mark.asyncio
async def test_usage_is_recorded_and_reasoning_is_never_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(_answer("```json\n" + json.dumps({"ok": True}) + "\n```"))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    provider = DeepSeekProvider("k")
    assert await provider.generate_structured("x", SCHEMA, {"purpose": "website.generate"}, 5) == {"ok": True}
    usage = provider.last_usage or {}
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["thinking_tokens"], usage["total_tokens"]) \
        == (12, 4, 2, 16)
    assert usage["model"] == DEEPSEEK_DEFAULT_MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "not json at all", "[1, 2]"])
async def test_an_unusable_reply_is_an_error_the_caller_can_fall_back_from(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", Script(_answer(content)).client)
    with pytest.raises(RuntimeError):
        await DeepSeekProvider("k").generate_structured("x", {}, {"purpose": "website.generate"}, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "kind"), [
    (401, AIProviderPermanentError), (400, AIProviderPermanentError), (429, AIProviderPermanentError),
    (402, AIProviderBillingError),
])
async def test_a_refusal_that_retrying_cannot_fix_is_permanent(
    monkeypatch: pytest.MonkeyPatch, status: int, kind: type[Exception]
) -> None:
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient",
                        Script(httpx.Response(status, json={"error": {"message": "nope"}})).client)
    with pytest.raises(kind):
        await DeepSeekProvider("k").generate_structured("x", {}, {"purpose": "website.generate"}, 5)


@pytest.mark.asyncio
async def test_a_server_error_is_transient_and_never_moves_to_another_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(httpx.Response(503, text="busy"))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    with pytest.raises(RuntimeError, match="unavailable"):
        await DeepSeekProvider("k").generate_structured("x", {}, {"purpose": "website.generate"}, 5)
    assert len(script.calls) == 1 and all("deepseek" in c["url"] for c in script.calls)


# ---------------------------------------------------------------- the paid-AI switch
@pytest.mark.asyncio
async def test_the_no_external_ai_switch_blocks_deepseek_before_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.ai_guard import blocked_calls, reset_blocked_calls

    # Leave the stub fixture's suspension: this test is about the real guard.
    from platform_core import ai_guard

    monkeypatch.setattr(ai_guard, "_provider_checks_suspended", False)
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", Script().client)
    with pytest.raises(ExternalAICallBlocked):
        await DeepSeekProvider("k").generate_structured("x", {}, {"purpose": "website.generate"}, 5)
    assert [c.provider for c in blocked_calls()] == ["deepseek"]
    reset_blocked_calls()  # the refusal was the point of this test


def test_the_transport_guard_knows_the_deepseek_host() -> None:
    from platform_core.ai_guard import AI_HOSTS

    assert "api.deepseek.com" in AI_HOSTS


def test_deepseek_and_pexels_keys_are_redacted_from_logs() -> None:
    from platform_core.logging import _redact_value

    assert _redact_value("DEEPSEEK_API_KEY", "sk-live") == "***redacted***"
    assert _redact_value("pexels_key", "abc") == "***redacted***"
