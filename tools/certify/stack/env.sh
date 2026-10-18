#!/usr/bin/env bash
# Shared environment for the certification stack: LOCAL database and storage,
# REAL AI + photo providers (only their keys are read from .env). Sourced by
# api.sh and worker.sh. Never point this at staging or the hosted project.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
export CERTIFY_DB=${CERTIFY_DB:-locah_certify}
export DATABASE_URL=postgresql+asyncpg://postgres@localhost:54329/$CERTIFY_DB
case "$DATABASE_URL" in *@localhost:*|*@127.0.0.1:*) ;; *) echo "local databases only" >&2; exit 1 ;; esac
export API_DATABASE_URL=$DATABASE_URL
export API_PORT=${API_PORT:-8020}
export WEB_PORT=${WEB_PORT:-3200}
export SUPABASE_PORT=${SUPABASE_PORT:-54331}
export SUPABASE_URL=http://127.0.0.1:$SUPABASE_PORT
export SUPABASE_ANON_KEY=local-anon-key
export SUPABASE_SERVICE_ROLE_KEY=local-service-role
export SUPABASE_JWT_SECRET=local-acceptance-secret-with-at-least-32-characters
export WEBSITE_PREVIEW_SECRET=local-preview-secret-with-at-least-32-characters
export PAYMENT_WEBHOOK_SECRET=local-certify-webhook-secret
export MESSAGING_SANDBOX=1
export RATE_LIMIT_ENABLED=0
export CORS_ALLOWED_ORIGINS=http://localhost:$WEB_PORT
export REVALIDATE_SECRET=local-revalidate-secret-for-certify
export WEB_REVALIDATE_URL=http://localhost:$WEB_PORT/api/revalidate
export WEB_REVALIDATE_SECRET=$REVALIDATE_SECRET
export WORKER_POLL_INTERVAL_SECONDS=1
# Quality certification is recorded, not enforced, here: a run still drives
# every customer flow on the published site, and the report says which sites
# enforce would have held back (tests prove enforce itself).
export WEBSITE_CERTIFICATION=${WEBSITE_CERTIFICATION:-record}
# Real photographs, judged; the images are the Unsplash/Pixabay pipeline's.
export IMAGE_PROVIDER=stock
unset LOCAH_TEST_NO_EXTERNAL_AI LOCAH_JOBS_INERT VOICE_PROVIDER LOCAH_AI_REPLAY_FILE || true
# Only the provider keys from .env (never its database or storage settings).
eval "$(cd "$ROOT" && uv run --no-env-file python tools/certify/stack/provider_env.py .env)"
