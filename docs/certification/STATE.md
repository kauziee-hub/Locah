# Certification — state (update as components land)

Plan and contracts: `PLAN.md`. Run artefacts: `certify-out/<run>/` (git-ignored).

## Stack (local only)

Postgres 54329 db `locah_certify` (apply every new migration to it by hand:
`psql -p 54329 -d locah_certify -f infra/supabase/migrations/<new>.sql`),
API 8020 and worker (`tools/certify/stack/api.sh`, `worker.sh` — no
auto-reload: restart after Python changes), web 3200 (`web.sh`, next dev),
storage stand-in 54331 (`supabase.sh`). Real DeepSeek + Unsplash/Pixabay keys
come from `.env` through `provider_env.py` (never the hosted database).

## Components

| # | Component | State |
|---|---|---|
| 1 | Stack | up (2026-10-18) |
| 2 | Owners — 12 scenarios × 6 variants + distinctness set | done, `certify/owners.py`, tests |
| 3 | Journey — owner over HTTP, records owner identity | done, `certify/journey.py` |
| 3b | Setup — the owner's Workspace afternoon: items live + priced, pickup/delivery, stock, staff week + services, tables, plans, invoicing | done, `certify/setup.py`; passes for all 12 normal scenarios (run2–run4) |
| 3c | Customer — guest order / book / join / enquire up to payment through the site's own public endpoints; owner sees it; browser order + booking on desktop and phone (`shop.mjs`, `book.mjs`) | done; all 12 normal scenarios pass (run2–run4, 2026-10-18 07:08) |
| 4 | Render — 4 viewports, full page, technical gates (fixed phone bar pinned at the page end for the shot) | done, `tools/certify/render.mjs` |
| 5 | Critic | done, `certify/critic.py` (vision call per page group); `certify/loop.py` renders + critiques chosen pages in minutes |
| 6 | Repair | done, `certify/repair.py` + `run --repair` rounds (re-render touched pages, re-judge, gate; ≤ 3 rounds, then pass or fail closed with owner requests). Real run on run7 retail/hotel 2026-10-18 — see below |
| 7 | Gate | done, `certify/gate.py`; **publish enforcement wired** (`services/website_certification.py`, migration 20261018150000, `WEBSITE_CERTIFICATION=off/record/enforce`; the stack runs `record`); the harness records every verdict |
| 8 | Distinctness | done, `certify/distinct.py`; not yet run on a 25-site set |
| 9 | Edits & lifecycle | done, `certify/edits.py` — 13 owner edits read back from the PUBLIC site + module off/on + three distinct refusals; first run (clinic) found the refusal-order bug (`30ab177`) |
| 10 | Report | done, `certify/report.py` → report.json, REPORT.md, contact sheets (`python -m platform_testing.certify.report certify-out/report certify-out/run*`) |

## Measured quality (vision critic, weighted /10, pass = 8.5)

- run1 restaurant-delivery (before the page/renderer fixes): 4.96, 4 critical.
- run4 clinic home/about/visit (loop c1, before 78b9177/edcc254): 5.15
  (home 5.71, about 4.95, visit 4.65). Real defects fixed since: hours
  contradiction (a split day read back as evenings only), duplicate "How a
  visit works", empty picture plates on doctor cards, a clinic FAQ asking about
  custom orders, footer stacked in one column (invalid grid CSS), cropped
  closing name, dead space under the statement. Input defects remain honestly:
  stock reception-desk photos, no doctor names or portraits — owner requests.

## Product fixes from certification (2026-10-18)

- Pixabay copies stored under `generated/`; a storage failure never fails a build (`d3e58f2`).
- The name heard after a greeting; publish refuses a nameless placeholder (`959e60f`).
- No provider key in library logs; a bakery is not a portfolio (`c9ac382`).
- Pickup-only never shows "Home delivery" (`4707e28`).
- Closing band line centred; paragraph reset made `:where()`; menu dishes as large plates (`13bd5f5`).
- Six hero covers chosen by design concept — trades stop opening alike (`c33e74f`).
- Booking flows: owners keep answering until the review (the salon was never
  asked its hours); the check asks for the chosen person's free times and sends
  the table title the Book page sends (`f326380`).
- A name before its place is heard ("Amber Room Salon in RS Puram"); a trade
  word ending the name stays as evidence of the kind (the salon had become a
  makeup artist's portfolio with 0 photos); each build keeps a photo audit per
  slot in `provider_usage.photo_audit` (`f539c51`).
- Split-day hours read back whole; one "How a visit works"; FAQ answers are
  sentences (`78b9177`).
- Footers in columns, photo-less ranges set in type, room above the phone bar,
  "My bookings" / "My orders" (`edcc254`).
- Publish gate (`0492958`).

## Scores after the fixes (vision critic, weighted /10)

| Site | run5 | run6 (new build) | run6b (re-render only) |
|---|---|---|---|
| bakery | 5.59 | 6.03 (home 6.88) | pending |
| clinic | 4.47 | 4.70 | 5.02 |
| salon | 4.39 | 4.02 | 5.24 |

## run7 (2026-10-18): nine more trades, every flow to payment

All 12 normal scenarios now pass the owner's setup and the customer flows up
to payment (run6: bakery, clinic, salon; run7: architecture, consultant, gym,
hotel, meat shop, NGO, restaurant delivery, restaurant reservations, retail).
Vision critic, weighted /10 (pass 8.5): architecture 3.20, retail 3.90,
hotel 4.18, consultant 4.47, gym 4.63, meat shop 4.54, NGO 4.35, restaurant
reservations 4.35, restaurant delivery 5.46. None passes; the gate fails
closed or asks for repair, as it must.

Of 49 critical defects, most are input the owner has not given yet (no
photographs of the place or the work, a visit page with only a locality,
stock pictures) — those become owner requests. The platform ones were fixed
(`145f373`, `d922877`): a blank page judged as design (dev server mid-compile
— render now retries and records `blank`), accent lines muddy over a wash,
a booking form with no visible confirm step, the owner's "people should book
a table" quoted as site copy, a contact label floating far above its value,
a pull quote repeating its own title.

### Repair, for real (run7 retail and hotel, `--repair --no-photos`)

- First run (09:33) kept nothing: improving fixes were refused because the
  critical-defect baseline was missing (fixed in `bdf655e`).
- Second run: retail 3.90 → 4.12 (home 3.95 → 5.13 kept, visit 4.20 → 4.47
  kept); hotel 4.18 unchanged — no fix cleared the margin.
- **Critic noise is wider than the keep margin.** The same "hide the repeat"
  fix on the hotel home scored 5.52 in one run and 4.61 in the next; a page
  re-judged unchanged moves ±0.3–0.9. The 0.25 margin is honest (it refuses
  more than it should, never keeps noise as progress), but a fix's worth is
  only knowable from repeated judgments — next: judge a candidate twice (or
  median of three) before keeping it, and report the spread.

## run8 (2026-10-18 14:45): the same twelve, re-rendered and re-judged

Journeys, owners and customers as they were; today's renderer (signature
moments, blank-render retry, booking confirm step, accent legibility).
Every customer flow passes again — browser order on desktop and phone for
the four shops, browser booking for gym, hotel and restaurant.

| Site | run7/6b | run8 | critical |
|---|---|---|---|
| architecture | 3.20 | 4.73 | 5 |
| bakery | 5.53 | 5.68 | 3 |
| clinic | 5.02 | 4.92 | 5 |
| consultant | 4.47 | 4.09 | 1 |
| gym | 4.63 | 4.66 | 3 |
| hotel | 4.18 | 4.05 | 4 |
| meat shop | 4.54 | 4.25 | 6 |
| NGO | 4.35 | 4.18 | 5 |
| restaurant delivery | 5.46 | 5.43 | 2 |
| restaurant reservations | 4.35 | 4.77 | 8 |
| retail | 4.12 | 4.15 | 6 |
| salon | 5.24 | 4.55 | 5 |

Mean 4.59 → 4.62: flat within the critic's noise, except architecture (its
About page is no longer judged blank). Rendering fixes alone do not move a
vision critic whose heaviest complaints are input — no photographs of the
real place or work, a visit page with only a locality — and depth (one-line
item descriptions, thin stories). Those are owner requests, which the gate
records; the platform defects it named were fixed the same afternoon
(`dd2ab95` action pages, `fa3abed` home pages, `5ffb66a` a learning trust
built as a gym).

## run9 (2026-10-18 15:05): after the action-page and home-page fixes

The NGO rebuilt from a fresh owner journey on the restarted stack; the other
eleven re-rendered and re-judged. Every customer flow passes again.

| Site | run8 | run9 |
|---|---|---|
| architecture | 4.73 | 5.06 |
| bakery | 5.68 | 5.68 |
| clinic | 4.92 | 5.21 |
| consultant | 4.09 | 4.36 |
| gym | 4.66 | 4.77 |
| hotel | 4.05 | 4.12 |
| meat shop | 4.25 | 4.48 |
| NGO (rebuilt) | 4.18 | 5.23 |
| restaurant delivery | 5.43 | 5.06 |
| restaurant reservations | 4.77 | 4.66 |
| retail | 4.15 | 4.00 |
| salon | 4.55 | 5.01 |

Mean 4.62 → 4.80. The rebuilt NGO is `local_service`, not a gym: its photo
briefs ask for a learning room, craft tables and exercise books, and three
were placed (was one kettlebell rack). Enquire pages moved most
(architecture 4.27 → 5.11, NGO 3.18 → 4.90). No site passes 8.5; the gate
holds every one at `repair` with the owner requests in REPORT.md. What still
separates these sites from the bar, by the critic's own weights, is imagery
(1.8–3.7 on every site: stock or none), page depth (one-line descriptions,
thin stories) and visit pages with only a locality — the owner's photographs,
words and street address, which the gate now asks for by name.

## Open findings (next)

- Photo yield is low: most builds place 0–3 photos ("none_qualified" on
  story/process/detail mood slots, restaurants 0 of 7). Read
  `journey.build.photo_audit` of run5+ before changing the judge or briefs.
- "a strength gym" infers powerlifting, not gym (pre-existing).
- The NGO's first question is "plans".

## Known external limits

- Unsplash demo key: 50 requests/hour → about 2–3 photo-complete builds an
  hour. The full matrix (72 + 25 journeys) needs Unsplash production access
  or runs over days; Pixabay carries the rest.
- No payment gateway merchant account locally: customer flows stop at
  payment (pay at pickup, cash on delivery, UPI to the business).

## Resolved questions

- Donate: online gifts go through checkout (Orders ready + a live `cause`
  offering); publish resolves the donate landing to the section listing the
  causes (`website_publish.landing`). The matrix's NGO (donations + leads)
  records gifts offline and takes enquiries, so its site offers Enquire, not a
  Donate button it could not honour.
