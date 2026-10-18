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
| 6 | Repair | not built — the generator/renderer is being fixed from real critiques first (see below) |
| 7 | Gate | done, `certify/gate.py`; **publish enforcement wired** (`services/website_certification.py`, migration 20261018150000, `WEBSITE_CERTIFICATION=off/record/enforce`; the stack runs `record`); the harness records every verdict |
| 8 | Distinctness | done, `certify/distinct.py`; not yet run on a 25-site set |
| 9 | Edits & lifecycle | regenerate one section / page exists (`ce2369a`); the 12 owner-edit and module-lifecycle tests are not built |
| 10 | Report | not built |

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
