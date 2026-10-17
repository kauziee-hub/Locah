#!/usr/bin/env bash
# The API for certification runs: local database + storage, real AI and photo providers.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
exec uv run --no-env-file uvicorn platform_api.main:app --app-dir apps/api/src --port "$API_PORT"
