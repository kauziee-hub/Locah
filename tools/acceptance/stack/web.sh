#!/usr/bin/env bash
# The web app for acceptance runs, pointed at the local API and mock auth.
# Environment variables win over apps/web/.env.local, so nothing here reaches
# a deployed service.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT/apps/web"
export NEXT_PUBLIC_API_URL=http://localhost:${API_PORT:-8010}
export NEXT_PUBLIC_WEB_URL=http://localhost:${WEB_PORT:-3100}
export NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321
export NEXT_PUBLIC_SUPABASE_ANON_KEY=local-anon-key
export NEXT_PUBLIC_WORKSPACE_URL=http://localhost:${WORKSPACE_PORT:-3101}
# The worker's website.revalidate subscriber calls /api/revalidate with this (local only).
export REVALIDATE_SECRET=${REVALIDATE_SECRET:-local-revalidate-secret-for-acceptance}
exec pnpm exec next dev -p "${WEB_PORT:-3100}"
