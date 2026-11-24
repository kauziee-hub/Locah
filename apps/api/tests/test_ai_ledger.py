"""Every model call and drawing of one build — counted, metered and capped.

A hotel build once ran 320 model calls and 48 drawings in a rebuild loop, and
only 1 of a normal build's 25 calls was metered (2026-11-24). Each build (and
each interview turn) now opens a ledger; past its cap a call is refused before
it reaches the network, with one alert.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_deepseek_provider import SCHEMA, Script, _answer

from platform_core import ai_ledger
from platform_core.website import ai_provider, image_generation
from platform_core.website.ai_provider import DeepSeekProvider

pytestmark = pytest.mark.usefixtures("stubbed_ai_transport")


@pytest.mark.asyncio
async def test_a_build_past_its_cap_refuses_the_call_before_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(_answer(json.dumps({"ok": True})), _answer(json.dumps({"ok": True})),
                    _answer(json.dumps({"ok": True})))
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", script.client)
    alerts: list[dict[str, Any]] = []
    monkeypatch.setattr(ai_ledger._log, "error", lambda event, **kw: alerts.append({"event": event, **kw}))
    provider = DeepSeekProvider("ds-key")
    config = {"purpose": "image.judge", "system_prompt": "x"}
    with ai_ledger.ledger("build:test", max_calls=2, max_drawings=1) as led:
        await provider.generate_structured("a", SCHEMA, config, timeout_seconds=5)
        await provider.generate_structured("b", SCHEMA, {**config, "purpose": "image.query"}, timeout_seconds=5)
        for _ in range(2):
            with pytest.raises(ai_ledger.CapReached):
                await provider.generate_structured("c", SCHEMA, config, timeout_seconds=5)
    assert len(script.calls) == 2  # the refused calls never left the process
    assert led.summary()["model_calls"] == 2
    assert led.by_purpose["image.judge"] == {"calls": 1, "prompt_tokens": 12, "completion_tokens": 4}
    assert led.tokens() == {"prompt_tokens": 24, "completion_tokens": 8, "total_tokens": 32}
    assert [a["event"] for a in alerts] == ["ai.cap_reached"]  # one alert, not one per refusal
    assert alerts[0]["work"] == "build:test" and led.refused == ["model:image.judge", "model:image.judge"]


@pytest.mark.asyncio
async def test_drawings_stop_at_their_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def drew(prompt: str, *, timeout_seconds: int) -> tuple[Any, str]:
        calls.append(prompt)
        return object(), ""

    monkeypatch.setenv("IMAGE_FALLBACK", "cloudflare")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(image_generation, "_generate_cloudflare", drew)
    safe = "A calm editorial landscape photograph. Subject: misty green hills. Light: soft. Colour grade: calm."
    with ai_ledger.ledger("build:test", max_calls=10, max_drawings=2) as led:
        results = [await image_generation.draw_fallback(safe) for _ in range(3)]
    assert [r[1] for r in results] == ["", "", "quota"] and len(calls) == 2
    assert led.drawings == 2 and led.refused == ["drawing"]


def test_without_an_open_ledger_nothing_is_counted_or_refused() -> None:
    ai_ledger.before_call("anything")
    ai_ledger.after_call("anything", 5, 5)
    ai_ledger.before_drawing()
    assert ai_ledger.current() is None


def test_caps_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAX_MODEL_CALLS_PER_BUILD", "40")
    monkeypatch.setenv("AI_MAX_DRAWINGS_PER_BUILD", "3")
    with ai_ledger.ledger("build:env") as led:
        assert (led.max_calls, led.max_drawings) == (40, 3)
    monkeypatch.setenv("AI_MAX_MODEL_CALLS_PER_BUILD", "not a number")
    assert ai_ledger.max_calls_per_build() == ai_ledger.DEFAULT_MAX_CALLS_PER_BUILD
