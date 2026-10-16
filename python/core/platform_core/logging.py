"""Structured logging for the API and worker (AUD-11).

Before this, the codebase had no application logging at all — every gate
denial, auth failure, payment failure and webhook rejection was silent, and
the plumbed `correlation_id` had nowhere to land. §21.1 gate 10 ("security
logging excludes tokens, secrets and payment-sensitive credentials") passed
only vacuously.

`configure()` sets up structlog once at process start. `bind_request_context`
/ `clear_request_context` push `correlation_id` / `identity_id` / `business_id`
into contextvars so every log line in a request carries them without threading
them through call signatures.

**Redaction runs before any renderer.** `_redact` scrubs values for keys that
name a credential or a raw payment/webhook payload, at any depth. It is the
first processor after the context merge, so nothing sensitive reaches stdout
even if a caller logs a whole request or event dict.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import structlog

# Keys whose VALUE is always a secret / sensitive, case-insensitive substring
# match on the key name.
_REDACT_KEY_SUBSTRINGS: tuple[str, ...] = (
    "authorization",
    "password",
    "secret",
    "token",
    "jwt",
    "api_key",
    "apikey",
    "key_id",
    "private_key",
    "card",
    "cvv",
    "pan",
    "raw_payload",
    "raw_body",
    "signature",
    "encrypted_password",
    "service_role",  # SUPABASE_SERVICE_ROLE_KEY, service_role_key
    "service_key",
    "credential",  # encrypted_credentials, provider_credentials, key_secret is covered by "secret"
    "xai",  # a leftover XAI_API_KEY in an old environment (also caught by "api_key")
    "gemini",  # GEMINI_API_KEY and anything else named after the provider
    "deepseek",  # DEEPSEEK_API_KEY and anything else named after the provider
    "pexels",  # PEXELS_API_KEY, the stock-photo search key
)
_REDACTED = "***redacted***"


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(s in lowered for s in _REDACT_KEY_SUBSTRINGS):
        return _REDACTED
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(key, v) for v in value)
    return value


def _redact(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {k: _redact_value(k, v) for k, v in event_dict.items()}


_configured = False


def configure() -> None:
    """Idempotent. Call once at process start (API lifespan / worker main)."""
    global _configured
    if _configured:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    json_logs = os.getenv("LOG_FORMAT", "json").lower() != "console"

    logging.basicConfig(format="%(message)s", level=level)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _redact,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)


def bind_request_context(
    *,
    correlation_id: str | None = None,
    identity_id: str | None = None,
    business_id: str | None = None,
) -> None:
    data: dict[str, str] = {}
    if correlation_id:
        data["correlation_id"] = correlation_id
    if identity_id:
        data["identity_id"] = identity_id
    if business_id:
        data["business_id"] = business_id
    if data:
        structlog.contextvars.bind_contextvars(**data)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
