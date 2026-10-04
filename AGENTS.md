# Working in this repository

Read `README.md` and `docs/ARCHITECTURE.md` first. The code, migrations and tests
are the source of truth.

- **Business is the tenant.** Locations belong to a Business. Every Business-scoped
  API route goes through the gate chain in `apps/api/src/platform_api/dependencies.py`;
  never authorize in the client.
- **Modules pass independent gates** — Entitlement, activation, readiness,
  permission. Never collapse them into one boolean, never let business type grant or
  activate a module, and never read another module's tables: use its public read
  functions or domain events.
- **Websites are structured content.** AI writes words and chooses allowed layouts;
  platform code owns cart, checkout, booking, payment and permissions.
- **Apps do not import other apps.** Shared code goes in `packages/*` or `python/core`.
- **Migrations are forward-only.** Never edit an applied migration.
- **Secrets never enter Git, logs, `NEXT_PUBLIC_*` or test output.** Tests must use a
  local `TEST_DATABASE_URL` and never reach a deployed database or a paid AI provider.
- Three visual contexts stay separate: the public platform, the Workspace, and a
  tenant website (styled only from that business's own theme).
- Report what was actually run. "Written" and "typechecked" are not "tested".
