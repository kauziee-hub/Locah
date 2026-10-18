# Product E2E certification — state (persistent checkpoint)

Brief: `LOCAH_END_TO_END_OWNER_AND_PREMIUM_DESIGN_MASTER_PROMPT.md` (founder,
2026-10-18). Branch `web-builder-premium`; nothing pushed or deployed.
Evidence: `certify-out/product-e2e/` (git-ignored run artefacts). Website
quality history: `STATE.md` (run1–run9).

Labels used everywhere below: **VERIFIED-BROWSER** (driven in a real browser
against the local stack and checked in DB/API), **VERIFIED-API** (HTTP calls
the UI makes, plus DB/API checks — the UI itself not clicked), **TESTED**
(automated tests only), **CODE** (exists in code, not exercised here),
**DEFERRED** (approved scope), **BLOCKED** (external dependency).

## Environment (local only)

| Piece | Where | Notes |
|---|---|---|
| Postgres | :54329, db `locah_certify` | migrations applied by hand to this db |
| API | :8020 (`tools/certify/stack/api.sh`) | real DeepSeek + Unsplash/Pixabay keys from `.env` (names only read) |
| Worker | `tools/certify/stack/worker.sh` | builds websites |
| Public web | :3200 (`web.sh`) | tenant sites, onboarding `/start` |
| Workspace | :3201 (`workspace.sh`, added 2026-10-18) | owner Business OS |
| Auth stand-in | :54331 (`supabase.sh`) | no password/email sign-in; validates locally minted HS256 tokens |
| Owner lab | `tools/certify/owner-lab/` (Playwright 1.49) | a test owner = the auth user row a sign-up creates (`platform_testing.certify.lab_owner`) + a minted session cookie (`session.mjs`); cookies ignore ports, so one cookie signs into :3200 and :3201 |

Sign-up itself (email OTP / password) cannot run locally — no GoTrue. Every
step after sign-up is driven through the real UI.

## Phase 0 — truthful inventory (first pass, 2026-10-18)

### Inputs

- Premium visual-reference PDF: **MISSING** — not in the repo, Downloads,
  Documents or Desktop. `docs/visual-references/BRIEF.md` (written takeaways
  of 15 references) is the only reference on disk; `ref_*.png` absent. No
  side-by-side visual comparison is claimed until the images are supplied.
- AI provider: DeepSeek (`deepseek-flash`, also the vision critic). Photos:
  Unsplash (demo tier, 50 req/h) + Pixabay.

### Module registries — two exist, and they differ from the brief

- `entitlements/module_registry.py` — 23 optional modules: the brief's 21
  plus `quotes` and `projects`.
- `catalog/modules.py` — the Capability Universe catalogue, 39 entries with a
  `built` honesty switch and phases P0–P5/FUTURE. Built=False: `analytics`,
  `connectors`, `trade-network`, `payroll`, `channel-manager`, `ticketing`.
  Built=True beyond the brief's launch list: `pos`, `ledger`, `compliance`,
  `dispatch`, `tasks`, `attendance`, `kitchen`, `expenses`, `procurement`,
  `recipes`, `jobs`, `academics`, `documents`, `donations`, `ai-employees`.
- `business-passport`, `business-community`, `b2b-network`: registry only
  (no catalogue entry, no Workspace route).
- Reconciling these with the brief's canonical 21 is a founder decision
  (see Blockers); the code's registry key is treated as truth (AGENTS.md).

### AI employees

Three implemented on one runtime (`ai_employees/runtime.py`): receptionist
(T2), collections (T2), procurement (T1), with allowlisted tools, autonomy
tiers, limits, approvals, pause, and a sandbox (`/ai-employees/sandbox`).
The brief's "13 AI employees" are not defined anywhere in the repo → the
other 10 are **not implemented** (no list to audit against).

### Surfaces

- Workspace: 106 business routes under `apps/workspace/src/app/b/[businessId]/`
  (orders, bookings, offerings, inventory, fulfilment, payments, memberships,
  customers, leads, quotes, projects, invoices, kitchen, queue, team, roles,
  invitations, modules, website editor/preview/publish/theme, …), plus `/kds`,
  `/pos`, `/my`, `/join`.
- API: 72 routers. Payments: Razorpay adapter, signed webhook ingestion with
  committed receipts, retries and dead-letter (`webhooks_payments.py`).
  **No Razorpay test account locally → provider-sandbox payments BLOCKED**;
  local signed-webhook fixtures can prove signature/idempotency (labelled).

## Phase 1 — meat shop, one complete order business (DONE for the normal owner)

Scenario `meat-shop/normal` (Velan Fresh Meats, persona from `owners.py`),
driven in the browser by the Owner Simulation Lab
(`node tools/certify/owner-lab/journey.mjs meat-shop normal --run <dir>`).
Payment: offline (pay at pickup), which this business chose — Payments was
recommended and deliberately left off. Evidence:
`certify-out/product-e2e/SCENARIOS/meat-shop-normal-r2/REPORT.md` (64/64
checks; r2 reached that through fixes and re-runs) and `…-r3/` (one clean,
uninterrupted run on the fixed code).

| Step (all VERIFIED-BROWSER + API/DB check) | State |
|---|---|
| Sign-up → Workspace sends a business-less owner to `/start` | PASS |
| Interview in the chat UI (persona answers), Build available | PASS |
| Build my website (AI build, ~2 min), preview step | PASS |
| Tools: recommendation (catalogue, orders, payments) declined in part; owner turns on catalogue, orders, fulfilment, inventory from module pages; payments stays off | PASS |
| Workspace home for a new business: actions, no fake numbers | PASS |
| Catalogue: conversation items → drafts (prices kept) → each made live → one price changed (240 → 260) | PASS after B1, B2 fixes |
| Stock: keep stock of 3 items; morning arrival recorded in kg on the counter | PASS after B2 fix |
| Publish + go live (Marketplace confirm) → public site takes orders | PASS (B6 open: publish alone does not go live) |
| Guest order in a second browser: pack sheet (500 g), pickup, pay at pickup, empty-details refusal, "Order confirmed ORD-…" | PASS |
| Owner: notification names the order → Open → Accept → Start preparing → Mark ready → Complete → cash recorded; 500 g off stock; customer tracking page follows each step ("Collected") | PASS after B3, B4 fixes |
| Team: manager + store keeper join by real join links; manager works orders, refused tool enabling / publishing / adding people (UI + direct API); store keeper sees stock, refused orders (UI no-access page + API 403, by id too); another owner refused (tenant isolation) | PASS |
| Lifecycle: Orders off → website stops selling (no stale cart button), owner sees "switched off, nothing lost"; on again → both past orders kept, website sells again | PASS |
| Return in a new session: home shows real activity, completed orders found, customer page lists her orders | PASS |

Not yet covered for this business: minimal / bad-input owners, a second
meat shop for distinctness, mobile-width owner journey, refund (no gateway),
a manager's own action in the audit trail, website premium-quality review.

Bugs and fixes: `certify-out/product-e2e/BUGS.md` (B1–B16).

## Blockers needing the founder

1. The premium visual-reference images (the PDF or `ref_01..15.png`).
2. Canonical module list: the brief's 21 vs the code's 23-key registry and
   39-key catalogue (which are launch-promised?).
3. The 13 AI employees: no definition exists in the repo.
4. Razorpay test-mode keys for sandbox payments (or confirmation that
   offline completion is the launch path).

## Test runs

- Full API suite 2026-10-18 (before the Phase 1 fixes): 1851 passed, 1 skipped,
  0 failed (22 min); an earlier full run failed one order-dependent test (B16).
- After the fixes: test_business_interview, test_stock_depth,
  test_notifications_kernel, offering tests — 105 + 10 + … passed.

## Next

1. Fix the open Phase 1 items worth it (B5 server render, B6 go-live, B7, B8, B13, B14).
2. Phase 2: salon (appointments, providers, cancel/reschedule), then hotel
   (date ranges), then gym (memberships) — same lab, one at a time.

    node tools/certify/owner-lab/journey.mjs salon normal --run certify-out/product-e2e/SCENARIOS/salon-normal-r1
