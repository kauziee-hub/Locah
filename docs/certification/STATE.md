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
| 3b | Setup — the owner's Workspace afternoon: items live + priced, pickup/delivery, stock, staff week + services, tables, plans, invoicing | written 2026-10-18, `certify/setup.py`; first real run pending |
| 3c | Customer — guest order / book / join / enquire up to payment through the site's own public endpoints; owner sees it | written 2026-10-18, `certify/customer.py`; first real run pending |
| 4 | Render — 4 viewports, full page, technical gates | done, `tools/certify/render.mjs` |
| 5 | Critic | done, `certify/critic.py` (vision call per page group) |
| 6 | Repair | not built |
| 7 | Gate | done, `certify/gate.py`; publish enforcement not wired |
| 8 | Distinctness | done, `certify/distinct.py` |
| 9 | Edits & lifecycle | not built |
| 10 | Report | not built |

## Product fixes from certification (2026-10-18)

- Pixabay copies stored under `generated/`; a storage failure never fails a build (`d3e58f2`).
- The name heard after a greeting; publish refuses a nameless placeholder (`959e60f`).
- No provider key in library logs; a bakery is not a portfolio (`c9ac382`).
- Pickup-only never shows "Home delivery" (`4707e28`).
- Closing band line centred; paragraph reset made `:where()`; menu dishes as large plates (`13bd5f5`).
- Six hero covers chosen by design concept — trades stop opening alike (`c33e74f`).

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
