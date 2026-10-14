#!/usr/bin/env bash
# The site lab: every tenant-site fixture through the real renderer, with no
# API, no database and no AI. Fixtures are written by
# `platform_testing.website_fixtures` (24 businesses, composed exactly as
# "Build my website" composes them) into .site-lab/ on first run.
#
#   tools/site-lab/serve.sh            # http://localhost:3005/site-lab/<fixture>
#   LOCAH_SITE_LAB_DIR=/other/dir tools/site-lab/serve.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
DIR="${LOCAH_SITE_LAB_DIR:-$PWD/.site-lab}"
if [ ! -f "$DIR/index.json" ]; then
  uv run python -m platform_testing.website_fixtures "$DIR" --images
fi
export LOCAH_SITE_LAB_DIR="$DIR" NEXT_DIST_DIR=.next-lab
exec pnpm --filter @platform/web exec next dev -p 3005
