# Architecture

This describes the system as it is built. The code, migrations and tests are
the source of truth; comments citing "Doc NN §x" refer to the historical
specification, kept in Git history (and the offline backup), not in this tree.

## Services

```
 browser ──► apps/web (Next.js)        public platform, auth, Marketplace, tenant sites /{slug}
         ──► apps/workspace (Next.js)  the business Workspace
         ──► apps/admin (Next.js)      Super Admin
                     │  HTTPS + Supabase JWT
                     ▼
              apps/api (FastAPI) ──► Postgres (Supabase) ◄── apps/worker
                     │                                     outbox, deliveries, jobs, sweeps
                     └── Supabase Auth (JWKS) · Supabase Storage · Gemini · payment provider
```

- The Next.js apps never touch the database. They call the API with the user's
  token (server components and server actions), or public endpoints for tenant
  websites. They do not import each other; shared code lives in `packages/*`.
- `apps/api` is the only writer for user actions. It connects as the RLS-enforcing
  `platform_api` role (`API_DATABASE_URL`).
- `apps/worker` uses the owner role (`DATABASE_URL`) because it does legitimate
  cross-tenant work (outbox fan-out, scheduled sweeps, generation jobs).

## Tenancy and access

- **Business** is the tenant. **Locations** belong to a Business. People belong
  through **memberships** with a role (`primary_owner`, `manager`, `member`) and
  explicit permissions (`platform_core/permissions.py`, mirrored in
  `packages/permissions`; a test keeps the two identical).
- Every Business-scoped request runs the gate chain in
  `platform_api/dependencies.py::resolve_business_actor`: membership active →
  Business exists → Entitlement → module state → permission. Location scope
  (`authorization/location_scope.py`) and assignment scope narrow reads further.
- RLS on every tenant table is defence in depth behind those checks.

## Modules

`platform_core/catalog/modules.py` is the module registry (key, label, phase,
dependencies, setup steps, what customers and staff can do). Platform Core
groups are always on. Optional modules pass independent gates — none implies
another:

```
Entitlement (plan / overrides)  →  activation (owner switched it on)
  →  readiness (setup steps true in real data, hard dependencies ready)
  →  permission (the person may use it)  →  the action
```

- `services/entitlement.py` resolves Entitlement and owns enable / deactivate.
  Deactivation is non-destructive: data stays, actions stop, re-enabling restores.
  Both publish `module.enabled` / `module.deactivated` events.
- `services/module_readiness.py::readiness()` answers "can this be used right now,
  and if not, which step is missing" — the same answer for the Workspace and
  every public surface.
- `services/workspace_projection.py` turns readiness into the Workspace
  navigation (`/v1/me/context` → `navigation_modules`, plus the business's own
  words: Menu / Services / Products, Bookings / Reservations, Customers / Clients /
  Guests). Business type only supplies vocabulary and recommendations, never
  behaviour.
- Modules talk to each other through public read functions (for example
  `stock/public.py::public_availability`, `offering_public.py`) and domain events,
  never through another module's tables.

## Website

- Websites are structured content: `website_versions` (one working **draft**, one
  **published**) → pages → sections of registered section types. AI writes words
  and chooses among allowed layouts; it never writes markup or platform mechanics.
- `website/capabilities.py` derives what a visitor can do from module readiness
  (browse the catalogue, order, book, join, enquire) and adds tool sections bound
  to a module (`module_binding`) where the design has none. Bound sections read
  live records through the owning module's public contract; when a module is not
  ready a bound section shows a placeholder in preview and is omitted live.
- The public page (`services/website_publish.py::load_public_page`) is projected
  per request from the published version plus current capabilities, so switching a
  tool on or off changes the site without republishing content. `apps/web` caches
  it (`website:{slug}` tag); the worker's `website.revalidate` subscriber calls the
  web app's `/api/revalidate` (shared secret) whenever something the site renders
  changes.

## Events and background work

- Services write domain events to `platform_outbox_events` in the same
  transaction as the change. The worker fans each event out to its subscribers
  (`platform_core/events/subscribers/`) as `platform_event_deliveries`, runs them
  with retries and backoff, and processes async jobs (website generation, document
  reading, image drawing). `/health/worker` reports outbox lag.

## Conversation and AI

- **Talk to Locah** (`platform_core/interview/`): a coverage-driven conversation
  that fills a structured `BusinessBlueprint` (facts, catalogue, actions, language
  preference). The model proposes; deterministic readers and planners decide what
  is stored and what is asked next. It works with the model down. English, Tamil
  and Tanglish are supported in the same conversation.
- Website generation, document reading and image drawing go through the provider
  abstraction (`AI_PROVIDER`, `IMAGE_PROVIDER`, `VOICE_PROVIDER`; Gemini in
  production, `replay` locally). Generated pictures are stored as media assets and
  stay marked as drafts until the owner keeps them.
- **AI employees** (`platform_core/ai_employees/`) run on one runtime with tool
  tiers (T0 read … T3 owner approval), an allowlist per employee, limits and a kill
  switch; every decision is an `ai_actions` row. The AI Employee Sandbox simulates
  an employee on the business's real records without writing or sending anything.

## Payments

Merchant collection (what a business charges its customers) is separate from
platform billing. The payments kernel owns attempts, refunds and webhook
receipts; provider specifics sit behind the provider adapter (`stub`, `razorpay`).
State only moves on a verified webhook, never on a browser callback. Pay at
pickup / on delivery stays "to collect" until money is recorded.

## Data

- Migrations: `infra/supabase/migrations/*.sql`, forward-only, keyed by version.
- Seed: `infra/supabase/seed/00_platform.sql` (module and section-type registries;
  idempotent, required).
