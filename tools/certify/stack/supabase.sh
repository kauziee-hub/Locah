#!/usr/bin/env bash
# Local auth + storage stand-in for certification runs (files under certify-out/storage).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
export PORT=${SUPABASE_PORT:-54331}
export STORAGE_DIR=${STORAGE_DIR:-$ROOT/certify-out/storage}
exec node tools/certify/stack/supabase-local.mjs
