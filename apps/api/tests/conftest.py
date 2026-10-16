"""Shared pytest setup for the apps/api suite.

Rate limiting is disabled for the whole test session. `RateLimitMiddleware`
keeps its sliding windows keyed by client IP, and every `TestClient(app)`
request arrives from the same synthetic host, so a test file that creates many
businesses / payments / bookings in quick succession would trip the shared
buckets and fail for reasons that have nothing to do with what it is testing.

The rate limiter has its own dedicated coverage in `test_rate_limiting.py`,
which re-enables it explicitly.

This must run before any test module executes `from platform_api.main import
app`, because the middleware reads the flag at import time. conftest.py is
imported by pytest before test collection, so it does.
"""

import os

from platform_testing.ai_guard import (  # noqa: F401 — fixtures registered by import
    enable_no_external_ai,
    no_paid_ai_calls,
    stubbed_ai_transport,
)
from platform_testing.database_guard import configure_test_database

configure_test_database(os.environ)

# No test may spend AI credits. With this switch every Gemini/xAI text, image
# and voice call raises before it leaves the process, and `no_paid_ai_calls`
# fails the test that attempted it. Provider-plumbing tests that replace the
# HTTP client with a stub opt in with the `stubbed_ai_transport` fixture.
enable_no_external_ai(os.environ)

os.environ.setdefault("RATE_LIMIT_ENABLED", "0")

# The suite mints its own HS256 tokens; nothing here exercises the ES256 / JWKS
# path. Drop any real SUPABASE_URL / SUPABASE_JWKS_URL from the environment so
# the API-startup JWKS warm (main.py lifespan) never makes a network call.
# test_jwt_verify.py stubs the JWKS client and manages these vars itself.
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_JWKS_URL", None)

# Website generation must never make a live AI call from the suite. Drop any
# XAI_API_KEY the environment/.env carries so `get_ai_provider()` returns
# `UnavailableAIProvider` by default; the live Grok path is covered with a
# stubbed provider in test_website_generation.py.
os.environ.pop("XAI_API_KEY", None)
# Gemini is the default provider and its key is paid. A test that forgets to
# stub the provider must fail fast into the deterministic path, never spend.
os.environ.pop("GEMINI_API_KEY", None)
# DeepSeek is the default provider and the photo search has a key of its own:
# neither may be live in the suite. A test that wants one sets it and stubs it.
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ.pop("PEXELS_API_KEY", None)
os.environ["IMAGE_PROVIDER"] = "none"

# The suite writes to a database a deployed worker also polls. Every job it
# queues is marked inert, and workers acknowledge inert jobs without running
# them — otherwise a test build would be personalised, and pictures drawn, on
# a paid key by whichever worker happened to claim it.
os.environ["LOCAH_JOBS_INERT"] = "1"

# AUD-11: keep the per-request INFO line ("request.completed") out of the test
# transcript. WARN/ERROR — gate denials, 5xx, webhook signature rejections —
# still print, and the redaction filter is exercised directly by
# test_logging_redaction.py regardless of level.
os.environ.setdefault("LOG_LEVEL", "WARNING")
