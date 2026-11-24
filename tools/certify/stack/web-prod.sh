#!/usr/bin/env bash
# The public renderer as a PRODUCTION build (next build + next start), for
# performance baselines: a dev server's on-demand compiles make every page
# look slow. Same certification API and storage as web.sh; its own dist dir.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT/apps/web"
PORT=${WEB_PROD_PORT:-3210}
export NEXT_PUBLIC_API_URL=http://localhost:${API_PORT:-8020}
export NEXT_PUBLIC_WEB_URL=http://localhost:$PORT
export NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:${SUPABASE_PORT:-54331}
export NEXT_PUBLIC_SUPABASE_ANON_KEY=local-anon-key
export NEXT_PUBLIC_WORKSPACE_URL=http://localhost:3201
export REVALIDATE_SECRET=local-revalidate-secret-for-certify
export NEXT_DIST_DIR=.next-perf
if [ "${SKIP_BUILD:-}" != "1" ]; then pnpm exec next build; fi
exec pnpm exec next start -p "$PORT"
