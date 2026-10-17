# Handoff — premium website builder: real photography + design v2

Branch `web-builder-premium` (tracks `origin/gowtham`; NOTHING pushed from it —
ask the founder before pushing). Read this first if you are a new session
continuing the work, and update "State" as you finish things.

## The founder's two asks (2026-10-17)

1. **Real photography from Unsplash + Pixabay** (no Pexels, no Commons in the
   product): business context → section intent → photo art direction →
   several searches → one pool from BOTH providers → cheap filters → vision
   judge → one photo per slot, with a selection reason, varied across the
   site, art-directed with the site's DNA concept, never inventing business
   facts. Unsplash: hotlink + attribution + `download_location` on selection
   only. Pixabay: 24 h cache, no permanent hotlinking (copy into storage).
   "Change this image" must work from the kept brief.
2. **The sites still look far below the founder's references** — type, fonts,
   layout. Ishant Proteins' hero ("Cut only after you order", red underlined
   accent over a photo collage) was called out as the worst. The reference
   images were never on disk; work from the written brief: editorial,
   premium, Lovable-level, not template-y.

Keys in `.env` (never print them): `IMAGE_SEARCH_PROVIDER=multi`,
`UNSPLASH_ACCESS_KEY`, `UNSPLASH_SECRET_KEY` (unused, OAuth only),
`PIXABAY_API_KEY`, `AI_PROVIDER=deepseek` + `DEEPSEEK_API_KEY`
(`deepseek-flash` can see images). Unsplash demo tier = 50 requests/hour. The
Pixabay key appeared in the founder's pasted docs — suggest rotating it.

## State

| Piece | State | Where |
|---|---|---|
| Providers: Unsplash, Pixabay, Multi; normalised `ImageCandidate`; 24 h cache; `fresh=` | done | `website/image_search.py` |
| PhotoBrief, section intents, DNA art direction, model + fallback queries, pool from both, filters, shortlist keeping both sources, rubric judge, hard gates (text, unoffered subject, AI look), role-weighted score, selection reason, `SiteMemory` rhythm, `regenerate` | done, 44 unit tests | `website/image_retrieval.py`, `tests/test_image_retrieval.py` |
| Pixabay copied to storage, Unsplash hotlinked + tracked; `media_assets.provenance` (migration 20261017140000 — NOT applied to hosted Supabase) | done, 32 tests | `services/media.py: persist_found`, `tests/test_stock_pictures.py` |
| Credits in the tenant footer ("Photography: Name / Unsplash") | done | `WebsitePageView.tsx`, `website.css` |
| "Change this image" reuses the kept brief, excludes the site's photos | done (no UI) | `services/website_images.py: _previous_photo` |
| Story/process/detail of a shop/kitchen show its own goods | done | `image_retrieval.goods_subject` |
| Premium photo lab (real API run, saves picks + audit) | done | `platform_testing/premium_lab.py`, `lab_shots.py` |
| Real run: bakery, Ishant, gym, Cleaver + before/after shots | in progress | scratchpad `photos-before/`, `photos-after/` |
| Design v2 (type, hero legibility, no underline/marker accents) | not started | `design_dna.py`, `site-dna.css`, `site-fonts.ts` |

Commits on this branch this session: `b78f7b5` (checkpoint), `f25cc9b`
(pipeline), `6d3d1a7` (lab, tests, guards).

## How to run things

- Tests: `PGPORT=54329 tools/acceptance/stack/db.sh locah_test`, then from
  `apps/api`: `TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:54329/locah_test uv run pytest tests/... -c pyproject.toml --rootdir . -q`
- Lab compose only: `uv run python -m platform_testing.premium_lab slots`
- Lab with REAL photos (costs Unsplash quota + DeepSeek):
  `IMAGE_EDITORIAL_MINOR_QUERIES=0 uv run --env-file .env python -m platform_testing.premium_lab photos lab-crumb`
  → `.site-lab/photo-report.json` has per-slot queries, pool by source,
  judged rubric and the selection reason.
- Rewrite lab files from saved picks (no API): `... premium_lab write`
- Site lab server: `tools/site-lab/serve.sh` (port 3005);
  shots: `uv run python -m platform_testing.lab_shots <out> lab-crumb lab-ishant`
- Patch scripts with backslashes: Write tool + run as a file (heredocs corrupt `\`).
