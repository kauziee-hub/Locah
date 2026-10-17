#!/usr/bin/env bash
# The public renderer for certification runs, pointed at the certification API.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT/apps/web"
export NEXT_PUBLIC_API_URL=http://localhost:${API_PORT:-8020}
export NEXT_PUBLIC_WEB_URL=http://localhost:${WEB_PORT:-3200}
export NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:${SUPABASE_PORT:-54331}
export NEXT_PUBLIC_SUPABASE_ANON_KEY=local-anon-key
export NEXT_PUBLIC_WORKSPACE_URL=http://localhost:3201
export REVALIDATE_SECRET=local-revalidate-secret-for-certify
export NEXT_DIST_DIR=.next-certify
exec pnpm exec next dev -p "${WEB_PORT:-3200}"
