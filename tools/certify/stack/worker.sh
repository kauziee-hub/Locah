#!/usr/bin/env bash
# The worker for certification runs: builds websites (real providers) from the local database.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT/apps/worker/src"
exec uv run --no-env-file python -m platform_worker.main
