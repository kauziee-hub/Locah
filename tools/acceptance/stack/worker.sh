#!/usr/bin/env bash
# The worker for acceptance runs: drains domain events, deliveries, automation
# steps and jobs from the LOCAL acceptance database only. No provider keys;
# paid AI refused (LOCAH_TEST_NO_EXTERNAL_AI=1); WhatsApp in sandbox.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
export DATABASE_URL=${ACCEPT_DATABASE_URL:-postgresql+asyncpg://postgres@localhost:54329/locah_accept}
case "$DATABASE_URL" in *@localhost:*|*@127.0.0.1:*) ;; *) echo "local databases only" >&2; exit 1 ;; esac
export LOCAH_TEST_NO_EXTERNAL_AI=1
export AI_PROVIDER=replay
export VOICE_PROVIDER=replay
export IMAGE_PROVIDER=none
export MESSAGING_SANDBOX=1
export WORKER_POLL_INTERVAL_SECONDS=1
# Drop the local web app's cached site when something it renders changes.
export WEB_REVALIDATE_URL=${WEB_REVALIDATE_URL:-http://localhost:${WEB_PORT:-3100}/api/revalidate}
export WEB_REVALIDATE_SECRET=${REVALIDATE_SECRET:-local-revalidate-secret-for-acceptance}
unset GEMINI_API_KEY XAI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY || true
# platform_worker lives in apps/worker/src; run from there so it imports.
cd "$ROOT/apps/worker/src"
exec uv run --no-env-file python -m platform_worker.main
