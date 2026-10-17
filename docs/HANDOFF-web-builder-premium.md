# Handoff — premium website builder: real photography + design v2

Branch `web-builder-premium` (tracks `origin/gowtham`; nothing pushed from it).
Read this first if you are a new session continuing the work. Update the
"State" table as you finish things — the next session trusts it.

## The founder's two asks (2026-10-17)

1. **Real photography from Unsplash + Pixabay** (no Pexels, no Commons in the
   product): business context → section intent → photo art direction → several
   searches → one candidate pool from BOTH providers → cheap filters → vision
   judge → one photo per slot, with a selection reason, varied across the site,
   art-directed with the site's DNA concept, never inventing business facts
   (a bakery that never mentions cakes gets no cake hero). Compliance: Unsplash
   hotlink + attribution + `download_location` on selection only; Pixabay
   24 h cache + no permanent hotlinking (copy chosen files into our storage).
   Single-image regeneration ("change this image") must be possible from the
   kept brief, excluding photos already used.
2. **The sites still look far below the founder's references** — type, font
   pairing, layout. Ishant Proteins' hero ("Cut only after you order" with an
   underline) was called out as the worst. The reference images were never
   available on disk; work from the written brief: editorial, premium,
   Lovable-level, not template-y.

Keys: `.env` has `IMAGE_SEARCH_PROVIDER=multi`, `UNSPLASH_ACCESS_KEY`,
`UNSPLASH_SECRET_KEY` (unused — OAuth only), `PIXABAY_API_KEY` all SET. Never
print them. Unsplash demo tier = 50 requests/hour: cache, and spend Unsplash on
hero/story/statement slots. The Pixabay key in the founder's pasted docs should
be rotated (it appeared in chat).

## State

| Piece | State |
|---|---|
| `website/image_search.py` — `UnsplashSearch`, `PixabaySearch`, `MultiSearch`, normalised `ImageCandidate` (credit, download_location, must_store), 24 h `MemoryCache`, `fresh=` bypass, host allowlist | done (previous session) |
| `website/image_retrieval.py` — PhotoBrief, section intents, multi-query, pool, judge rubric, selection reason, rhythm, regenerate | in progress (this session) |
| Pixabay chosen file → copied into storage; Unsplash → hotlink + track download | in progress |
| Attribution reaching the rendered site | not started |
| `.env.example` still documents Pexels/Commons | to fix |
| Design v2 (type, hero, Ishant) | not started this session |
| Real-API lab run (bakery, meat shop, gym, +1) with screenshots | not started |

## How to see results

Site lab: launch config `site-lab` (port 3005) renders `.site-lab/*.json`.
Vision loop: `python -m platform_testing.site_vision_loop <keys> --dry-run`.
Tests run on local Postgres: `PGPORT=54329 tools/acceptance/stack/db.sh locah_test`,
then `TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:54329/locah_test`.
Write patch scripts containing backslashes with the Write tool, not heredocs.
