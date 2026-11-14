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

### Checkpoint — 2026-11-14, "anyone can use it": messy owners, the editor, WhatsApp

Driven with owners who type fast and wrong (`bad_input` personas), real DeepSeek
and photo providers, local stack. Nothing pushed or deployed: **staging still runs
`origin/main` (2026-10-14), 89 commits behind this branch** — the premium site
pipeline is not what the founder sees there.

Why sites came out "template-like" — three causes found and fixed:

1. The creative plan never arrived. DeepSeek spent the call's whole allowance
   reasoning, or wrote `copy` inside `creative` with a bracket missing; either way
   the build silently used the deterministic direction (`strategy_source:
   deterministic`, `fallback_reason: RuntimeError`). Now `strategy_source: ai`, ~7 s.
2. The Workspace Theme page replaced the whole theme with two colours, erasing
   `dna` / `experience` / `composition`. Theme edits now merge; design keys cannot
   be dropped.
3. "pepper vine kichen … we make kerala food" was filed as `other`: dishes became
   bookable services and the live site could not take an order.

| Run | Result |
|---|---|
| `restaurant-delivery bad_input` r1 (before) | menu read "Chiken biriyani", "Stew chiken 240 veg"; appam and duck roast lost their prices; **0 Add buttons**, the guest could not order |
| `restaurant-delivery bad_input` r2 (after) | VERIFIED-BROWSER: 8 priced items, guest orders Appam + Duck roast (ORD-CF6F4342, ₹470), owner fulfils, cash recorded, team, lifecycle, return. One lab-only miss (a store keeper's page is titled "Ingredients and supplies") |
| `salon bad_input` r1 | VERIFIED-BROWSER: 96/97 — services with prices and durations from "ladies cut 900 gents 450 colur 3500 onwards…", booking with a stylist, conflicts, guest cancel, team, lifecycle. The miss is the lab looking for the word "haircut" |
| Editor (`editor-check.mjs`) | VERIFIED-BROWSER 21/21: click-to-select, drag and arrow reorder, hide/show, add/remove, Design (pair, lettering, size), Ask LOCAH with typos, refusal of what it cannot do, design keys untouched, Look & menu page |
| WhatsApp sandbox (`whatsapp-check.mjs`) | VERIFIED-API: connect, inbound "hi" → menu, conversation in the inbox, customer record. Price questions answered from the catalogue: TESTED (`test_journeys`) |

Found on the salon and fixed: "ladies gents **both**" put "Home delivery" and
"Pickup" on a salon's website; "Ladies gents both" and "Bridal makeup also" were
catalogue shelves. Found in the suite and fixed: LOCAH said "that's your story on
the website now" on a site whose story lives in a statement, and nothing changed.

Later the same day (founder: "the AI slop design of italics text and colouring…
it makes this as template"): the coloured italic accent is now the exception
(`headline: none` in most draws); `gym bad_input` r1 VERIFIED-BROWSER 42 checks,
with fixes for "quartly" plans, "6am-10pm sunday till 12" (the live site said
Mon–Sat closed), owner shorthand on the page ("Ppl shud…", "hsr layout blr") and
the Plans section sitting under the closing band; "Match a design you like"
VERIFIED with one live vision call (`reference-check.mjs`: applied, design keys
untouched, undo exact). The 15 reference images named in
`LOCAH_CLAUDE_VISUAL_REFERENCE_BRIEF.md` are still not on disk — only its text
was read.

Still open: photo slots stay empty where the libraries have no honest picture
(6 of 10 on the Kerala kitchen) and there is no working image generator to fall
back on (Gemini image quota is 0); the Unsplash demo key allows 50 requests an
hour; gym / hotel / clinic / retail / NGO have not been re-run with `bad_input`;
Meta's real API, Razorpay sandbox and email/password sign-up remain unexercised;
the editor changes fonts, sizes, colours and order, not free positioning.

### Resumption checkpoint — 2026-10-19, design composition

Latest cross-business pass: **35 cases** (12 previous real generations and
23 fresh scripted-interview builds), **261 broad responsive page checks**,
plus final targeted catalogue/action/motion checks. Card captions now have
their own surface; the desktop pill is removed; photo-free openings use
the actual range; service photo briefs name the actual work. A property
browsing link no longer incorrectly depends on online ordering. **247
relevant Python tests passed**. One external restaurant photo failed once
and passed the recorded recheck. See
[`MULTI_BUSINESS_DESIGN_REVIEW_2026-10-19.md`](MULTI_BUSINESS_DESIGN_REVIEW_2026-10-19.md)
for exact sources, evidence and remaining image/copy limitations. This is
visual/renderer verification, not a rerun of the owner journeys below.

Follow-up product review: three render/review cycles improved the long-copy
home, story openings, range browsing and local anchors. The lab screenshot
loop now retains reviewed improvements and restores the best state on
regression/failure. **159 relevant Python tests passed**; two successive
27-capture browser batches passed. Current evidence and limits:
[`BUILDER_PRODUCT_REVIEW_2026-10-19.md`](BUILDER_PRODUCT_REVIEW_2026-10-19.md).
Owner preference and conversion are not inferred from those checks.

Current user priority: substantially better, coherent and personalised
website design; references establish a quality bar rather than a screen
to reproduce. Implemented content-aware inner-page composition and removed
the override that forced pictured categories into one layout. Full changes,
executed checks, screenshots and limitations:
[`COMPOSITION_REVIEW_2026-10-19.md`](COMPOSITION_REVIEW_2026-10-19.md).
No premium certification or new owner-flow pass is claimed.

Saved journals were inspected, not rerun: hotel r2 **73/73**; gym r2
**43/46**; architecture r1 **32/33**; consultant r1 **32/32**. NGO r1
stopped after six steps (**12/12 recorded checks**, one interruption), with
`items.map is not a function` at `enquiry-journey.mjs:69`. The lab file
already had uncommitted changes when this session began; they are preserved.
The older Phase 2/Next text below predates this checkpoint.

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

## Phase 2 — appointment and stay businesses (2026-10-19)

### Salon (Amber Room Salon) — DONE for the normal owner

Run r2 from a fresh sign-up, after the fixes: **16/16 steps, 121/121 checks pass**
(`certify-out/product-e2e/SCENARIOS/salon-normal-r2/REPORT.md`).

| Step (VERIFIED-BROWSER + API check) | State |
|---|---|
| Services from the conversation → drafts → time given → live → one price changed; unpriced duplicate archived | PASS |
| Hours from "10 to 8, Monday holiday"; address added on the place | PASS |
| A stylist with his services, his week, a day off | PASS |
| Guest books on /book with the stylist, pays at the salon; empty details refused; page states the real status | PASS after S2 |
| Conflicts: a taken time is gone; two guests race, one wins, the other is told and the time disappears; "anyone available" never double-books the only stylist; off-hours, day off, closed day refused (UI and crafted API) | PASS after S3, S7 |
| Owner: notification names the booking → Open → Confirm → move to another day; the guest's link follows | PASS after S4, S8 |
| Guest cancels from her link (asked first); recorded as the customer's; the owner is told; the time frees | PASS after S5, S9 |
| Team: manager works bookings, refused tools/publish/people; accountant refused bookings (UI + API, by id); another owner refused | PASS |
| Lifecycle: Bookings off → no Book anywhere; on → nothing lost | PASS |
| Return in a new session | PASS |

### Hotel (Mistwood Estate Retreat, 14-room Coorg estate)

New lab model `stay` (`tools/certify/owner-lab/stay-journey.mjs`): rooms → room list → publish →
stay → overlap → arrival → guest cancel → return. Run r1 (resumed after the build): 59/60 checks,
the one failure fixed since (H6). Full re-run r2 from sign-up: see BUGS.md (in progress at the
time of writing). Findings H1–H8 (`BUGS.md`): rooms tied to room types (critical), check-in /
check-out and shortest-stay rules from the chat, resort vs homestay, room and total shown to the
owner and the guest, the place and number from the chat on the location.

### Gym (Forge Strength Club)

New lab model `membership` (`tools/certify/owner-lab/membership-journey.mjs`): plans → publish →
join → enrol → check-in → freeze → return. In progress.

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

1. Gym (memberships) to a clean run; then Phase 3: architecture, consultant, NGO (enquiry businesses).
2. Open Phase 1 items: B5 server render, B6 go-live, B7, B10–B12, B15.
3. Founder decision MC-03: who may change a business's plan and entitlements (today the owner can, through the API).

    node tools/certify/owner-lab/journey.mjs salon normal --run certify-out/product-e2e/SCENARIOS/salon-normal-r1
