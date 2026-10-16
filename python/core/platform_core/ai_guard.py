"""The switch that makes every paid AI call fail loudly, before it leaves the process.

`LOCAH_TEST_NO_EXTERNAL_AI=1` turns it on. With it on:

* every provider path — DeepSeek and Gemini text, Gemini images and Live voice credentials —
  calls :func:`guard_external_ai`
  immediately before its network request, and the call raises
  :class:`ExternalAICallBlocked` instead of spending anything;
* :func:`install_transport_guard` additionally refuses any httpx request to a
  known AI host, so a path added later without its own guard is still caught;
* every refused attempt is recorded (:func:`blocked_calls`) and logged at ERROR.

Callers keep their existing deterministic fallbacks: an interview turn whose
model call is refused degrades exactly as it would with no key. That is why the
record exists — the test suite's autouse check fails any test that attempted a
paid call, so a missing stub can never pass quietly or spend credits.

Nothing here reads, logs or stores a key.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from platform_core.logging import get_logger

ENV = "LOCAH_TEST_NO_EXTERNAL_AI"

# Hosts that only ever answer paid model requests. Storage, payments and maps
# are not here: the switch is about AI spend, not about the network.
AI_HOSTS = frozenset({
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "api.deepseek.com",
    "api.x.ai",
    "api.openai.com",
    "api.anthropic.com",
})

_log = get_logger("ai.guard")
_lock = threading.Lock()


class ExternalAICallBlocked(RuntimeError):
    """A paid AI call was attempted while LOCAH_TEST_NO_EXTERNAL_AI is set."""


@dataclass(frozen=True)
class BlockedCall:
    kind: str  # "text" | "image" | "voice" | "http"
    provider: str
    purpose: str


_blocked: list[BlockedCall] = []
# Set only by `stubbed_transport_only()`: a unit test that has replaced the HTTP
# client itself may exercise a provider's request/response handling.
_provider_checks_suspended = False


def external_ai_disabled() -> bool:
    return os.getenv(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def stubbed_transport_only() -> Iterator[None]:
    """Let provider code run while its HTTP client is a test stub.

    Only the named provider checks are suspended. The transport backstop stays
    on, so a test that forgot its stub still cannot reach a paid host.
    """
    global _provider_checks_suspended
    previous = _provider_checks_suspended
    _provider_checks_suspended = True
    try:
        yield
    finally:
        _provider_checks_suspended = previous


def guard_external_ai(kind: str, provider: str, purpose: str = "") -> None:
    """Raise instead of calling out, when the switch is on. A no-op otherwise."""
    if not external_ai_disabled():
        return
    if _provider_checks_suspended and kind != "http":
        return
    call = BlockedCall(kind=kind, provider=provider, purpose=str(purpose or ""))
    with _lock:
        _blocked.append(call)
    _log.error("ai.external_call_blocked", kind=kind, provider=provider, purpose=call.purpose)
    raise ExternalAICallBlocked(
        f"External AI call blocked by {ENV}: {kind} via {provider}"
        + (f" ({call.purpose})" if call.purpose else "")
    )


def blocked_calls() -> list[BlockedCall]:
    with _lock:
        return list(_blocked)


def reset_blocked_calls() -> None:
    with _lock:
        _blocked.clear()


def _host(url: Any) -> str:
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


_installed = False


def install_transport_guard() -> None:
    """Refuse httpx requests to AI hosts while the switch is on. Idempotent.

    Provider code guards itself by name; this is the backstop for a path that
    forgot to. It checks the switch per request, so installing it is harmless
    in a process where the switch is off.
    """
    global _installed
    if _installed:
        return
    import httpx

    original_async_send = httpx.AsyncClient.send
    original_send = httpx.Client.send

    def _check(request: httpx.Request) -> None:
        host = _host(request.url)
        if host in AI_HOSTS:
            guard_external_ai("http", host, request.url.path)

    async def guarded_async_send(self: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any) -> Any:
        _check(request)
        return await original_async_send(self, request, *args, **kwargs)

    def guarded_send(self: httpx.Client, request: httpx.Request, *args: Any, **kwargs: Any) -> Any:
        _check(request)
        return original_send(self, request, *args, **kwargs)

    httpx.AsyncClient.send = guarded_async_send  # type: ignore[method-assign]
    httpx.Client.send = guarded_send  # type: ignore[method-assign]
    _installed = True
