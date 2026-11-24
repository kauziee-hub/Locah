"""Every model call and drawing one piece of work makes — counted, and capped.

A build (or an interview turn) opens a ledger; every provider call and every
drawing is charged to it *before* it is made. Past the cap the call is refused
(``CapReached``), one alert is logged (``ai.cap_reached``, error level) and the
work carries on along its existing no-model paths — a slot stays empty, a
creative step falls back. The ledger's totals are what the build records as its
usage (tokens per purpose) instead of one call's.

Found 2026-11-24: one hotel build ran 320 model calls and 48 drawings (a rebuild
loop), and only 1 of a normal build's 25 calls was metered.

    with ai_ledger.ledger(f"build:{job.id}") as led:
        ...                      # every call made here is charged to `led`
    led.summary()                # {"model_calls": 25, "by_purpose": {...}, "drawings": 4, ...}
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from platform_core.logging import get_logger

_log = get_logger("ai.ledger")

DEFAULT_MAX_CALLS_PER_BUILD = 60
DEFAULT_MAX_DRAWINGS_PER_BUILD = 6
DEFAULT_MAX_CALLS_PER_TURN = 6


class CapReached(RuntimeError):
    """A model call or drawing refused because its work reached its cap."""


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "").strip() or default))
    except ValueError:
        return default


def max_calls_per_build() -> int:
    return _int_env("AI_MAX_MODEL_CALLS_PER_BUILD", DEFAULT_MAX_CALLS_PER_BUILD)


def max_drawings_per_build() -> int:
    return _int_env("AI_MAX_DRAWINGS_PER_BUILD", DEFAULT_MAX_DRAWINGS_PER_BUILD)


def max_calls_per_turn() -> int:
    return _int_env("AI_MAX_MODEL_CALLS_PER_TURN", DEFAULT_MAX_CALLS_PER_TURN)


@dataclass
class Ledger:
    work: str
    max_calls: int
    max_drawings: int
    by_purpose: dict[str, dict[str, int]] = field(default_factory=dict)
    drawings: int = 0
    refused: list[str] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return sum(row["calls"] for row in self.by_purpose.values())

    def tokens(self) -> dict[str, int]:
        prompt = sum(row["prompt_tokens"] for row in self.by_purpose.values())
        completion = sum(row["completion_tokens"] for row in self.by_purpose.values())
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}

    def summary(self) -> dict[str, Any]:
        return {"model_calls": self.calls, "by_purpose": {k: dict(v) for k, v in self.by_purpose.items()},
                **self.tokens(), "drawings": self.drawings, "refused": self.refused[:20],
                "caps": {"model_calls": self.max_calls, "drawings": self.max_drawings}}


_current: ContextVar[Ledger | None] = ContextVar("ai_ledger", default=None)


def current() -> Ledger | None:
    return _current.get()


@contextmanager
def ledger(work: str, *, max_calls: int | None = None, max_drawings: int | None = None) -> Iterator[Ledger]:
    led = Ledger(work=work,
                 max_calls=max_calls_per_build() if max_calls is None else max_calls,
                 max_drawings=max_drawings_per_build() if max_drawings is None else max_drawings)
    token = _current.set(led)
    try:
        yield led
    finally:
        _current.reset(token)


def _refuse(led: Ledger, what: str) -> None:
    if not led.refused:
        # The alert: once per piece of work, at error level, with what was spent.
        _log.error("ai.cap_reached", work=led.work, refused=what, model_calls=led.calls,
                   drawings=led.drawings, max_calls=led.max_calls, max_drawings=led.max_drawings)
    led.refused.append(what)
    raise CapReached(f"{led.work}: {what} refused — cap reached")


def before_call(purpose: Any) -> None:
    """Charge one model call to the open ledger, or refuse it past the cap."""
    led = _current.get()
    if led is None:
        return
    key = str(purpose or "unknown")
    if led.calls >= led.max_calls:
        _refuse(led, f"model:{key}")
    row = led.by_purpose.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    row["calls"] += 1


def after_call(purpose: Any, prompt_tokens: Any, completion_tokens: Any) -> None:
    """Add a finished call's tokens to the open ledger."""
    led = _current.get()
    if led is None:
        return
    row = led.by_purpose.setdefault(str(purpose or "unknown"),
                                    {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    row["prompt_tokens"] += prompt_tokens if isinstance(prompt_tokens, int) else 0
    row["completion_tokens"] += completion_tokens if isinstance(completion_tokens, int) else 0


def before_drawing() -> None:
    """Charge one drawing to the open ledger, or refuse it past the cap."""
    led = _current.get()
    if led is None:
        return
    if led.drawings >= led.max_drawings:
        _refuse(led, "drawing")
    led.drawings += 1
