#!/usr/bin/env bash
# The owner's Workspace for certification runs, pointed at the certification
# API and the local auth stand-in (supabase.sh). A browser signs in with a
# locally minted session cookie (tools/certify/owner-session.mjs) — the local
# stack has no password sign-in and needs none.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT/apps/workspace"
export NEXT_PUBLIC_API_URL=http://localhost:${API_PORT:-8020}
export NEXT_PUBLIC_WEB_URL=http://localhost:${WEB_PORT:-3200}
export NEXT_PUBLIC_WORKSPACE_URL=http://localhost:${WORKSPACE_PORT:-3201}
export NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:${SUPABASE_PORT:-54331}
export NEXT_PUBLIC_SUPABASE_ANON_KEY=local-anon-key
export NEXT_DIST_DIR=.next-certify
exec pnpm exec next dev -p "${WORKSPACE_PORT:-3201}"
