# Locah

Locah is an operating system for local businesses. A business owner describes
their business in a conversation; Locah builds their website, lists them in the
Marketplace, and gives them a Workspace with the tools their kind of business
needs — catalogue, orders, bookings, payments, memberships, customers, stock and
more — each switched on by the owner, never by business type.

## Repository

| Path | What it is |
|---|---|
| `apps/web` | Public platform, sign-in, Marketplace and every tenant website (`/{slug}`) — Next.js, port 3000 |
| `apps/workspace` | The business Workspace — Next.js, port 3001 |
| `apps/admin` | Super Admin console — Next.js, port 3002 |
| `apps/api` | FastAPI service: every read and write, authorization, public contracts |
| `apps/worker` | Background worker: outbox events, deliveries, generation jobs, sweeps |
| `packages/*` | Shared TypeScript: `auth`, `contracts`, `config`, `permissions`, `ui`, `validation`, `api-client`, `observability` |
| `python/core` | `platform_core`: domain models, services, modules, interview, website, AI |
| `python/domain_events` | Event envelope shared by API and worker |
| `python/testing` | Test helpers and fixtures used by the API and worker suites |
| `infra/supabase` | Migrations (forward-only), seed, auth email templates, local Supabase config |
| `infra/docker` | One Dockerfile per deployed service |
| `tools/acceptance` | Browser acceptance suites and the local acceptance stack |
| `tools/codegen` | Generated catalogue data shared by Python and TypeScript |

More: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), [`docs/SECURITY.md`](docs/SECURITY.md).

## Local development

Requirements: Node 20+, pnpm 9, Python 3.12 with [uv](https://docs.astral.sh/uv/),
PostgreSQL 15+ (or the Supabase CLI).

```bash
pnpm install
uv sync --all-packages
cp .env.example .env          # fill in local values; never commit .env
pnpm db:start                 # local Supabase (or point DATABASE_URL at a local Postgres)
pnpm dev:all                  # web :3000, Workspace :3001, admin :3002
uv run uvicorn platform_api.main:app --app-dir apps/api/src --port 8000
cd apps/worker/src && uv run python -m platform_worker.main
```

Without spending AI credit: set `LOCAH_TEST_NO_EXTERNAL_AI=1` (every paid AI call
is refused before it leaves the process), `AI_PROVIDER=replay` with
`LOCAH_AI_REPLAY_FILE`, and `VOICE_PROVIDER=replay` with `LOCAH_VOICE_REPLAY_FILE`.
`tools/acceptance/README.md` starts a complete local stack that never reaches a
deployed service.

## Checks

```bash
pnpm lint && pnpm typecheck && pnpm test && pnpm build
uv run ruff check . && uv run mypy --explicit-package-bases .
# pytest needs a dedicated local test database; it refuses a remote DATABASE_URL
TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/locah_test \
  pnpm python:test
```

CI (`.github/workflows/ci.yml`) runs the same gates on every push.
