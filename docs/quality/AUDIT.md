# Website Quality Program — Phase 0 audit

*2026-11-24 · branch `web-builder-premium` · local certification stack only · nothing deployed.*
*Brief: "LOCAH — Website Quality Program" (founder). This audit maps how tenant
websites are built today, measures a baseline, and proposes an ordered plan.
Checkpoint: Pranav reviews this before Phase 1.*

## 0. Summary

LOCAH is already much closer to the brief's **Option D** than the brief assumes.
There are 25 section types with **93 variants**, not about 8 layouts. Each site
gets a design DNA with 8 art-direction concepts. There's a composed-section
layout engine, a WebGL runtime with a device gate, and a 15-dimension vision
critic with a pass gate and a distinctness check. What holds quality back is not
the size of the catalogue:

1. **Same skeleton under every skin.** The restaurant and the salon share one page
   rhythm: arched cover photo with a round inset, ruled 3-column cards, a
   "How it works" row, a giant closing band and a giant wordmark footer. Variant
   use is concentrated: `cta_band/giant` 29×, `statement/giant` 24×,
   `fulfilment_strip/icons` 32× across 39 stored versions.
2. **Slow on the phones that matter.** No baseline site meets the brief's LCP
   ≤ 2.5 s on a throttled mid-range Android. Measured LCP is 2.7–4.7 s,
   main-thread blocking 1.1–3.3 s, and up to **392 KB of fonts** on one page.
3. **Photos are the weakest dimension.** Covers were unrelated (a succulent for a
   clinic, a concrete wall for a coffee-estate hotel), the same photo was used
   twice, and three sites had no photos at all.
4. **Trust is absent everywhere.** None of the six baseline sites shows reviews,
   ratings, credentials or press. Every one scores 2/5 on trust.
5. **Copy leaks and template tells survive.** Raw owner chat-speak ("Ppl shud
   book trial first then join."), lower-case places ("hsr layout blr"), stock
   closers ("Ready when you are."), the coloured-italic accent phrase, outline-text
   marquees and empty grey picture boxes still appear.
6. **Published sites keep old mistakes.** The gym still shows "Mon–Sat closed;
   Sun 6 am–10 pm" (the owner said "6 am to 10 pm, Sunday half day"). Today's
   parser reads that correctly, but nothing re-checks a published site.
7. **Cost isn't measured.** One build makes **25 model calls (about 47k input and
   12k output tokens)**, but only 1 of the 25 is metered.
8. **Hindi and Tamil are only glyph fallbacks.** Noto Sans sits behind every face.
   There are no tone-matched display or serif companions, and no Hindi/Tamil
   renders in the quality matrix.

**Fixed during the audit** (§4): the firm "AI images never pretend to be the
business" rule is now enforced in code and tests, and a build that could loop
forever and repeat its model calls was fixed.

**Proposed order** (§6): define the bar on top of the existing critic
(Phase 1); then performance, trust and copy (highest leverage, cheapest); then
type and personalities, including Hindi and Tamil; then the section library per
vertical, starting with **food and stays**.

## 1. How it works today

### 1.1 Section system — *strong, keep; refactor how variants are chosen*
- Structured content: `website_versions` (draft, published) → pages → sections of
  25 registered types (`website_section_types`: `content_schema` and
  `allowed_variants`, seeded by forward-only migrations). The renderer is
  `apps/web/src/components/website/SectionRenderer.tsx`, which switches on
  `section_type_id` and `layout_variant`.
- 93 variants in all, the hero alone has 17, and `product_showcase` has 14.
  Validation is in `validation/website.py` and the registry mirror in
  `website/section_registry.py`.
- **Composed sections** (`composition`, added 2026-11-22): blocks on a
  12-column grid with layers, frames, grounds and motion. `normalize()` keeps
  every layout legal, and `layout_engine.py` holds seeded recipes per role. This
  is effectively the brief's "knobs" system, already shipped for 5 roles.
- **Versioning:** there's no schema version per section. The content schema lives
  in the DB row, and stored JSON is validated on write, not migrated. Any knob
  extension needs a `schema_version` and a renderer default per version (brief
  §7.3).

### 1.2 Theme system — *strong, keep; add Indic companions*
- `theme` JSON per version: colours, `palette_mode`, `dna` (concept, display and
  body face, shape, button, nav, photo grade, motion budget, signature and
  flourish), `experience`, `composition` and `owner_style`.
- `owner_style.merge_theme` means the owner personalises without erasing the
  design. Scoping is by the `.ls-site` root, so tenant CSS never leaks into the
  platform or the Workspace.
- **Fonts:** 21 display faces and 8 body faces through `next/font/google`
  (`site-fonts.ts`), with Noto Sans Tamil and Devanagari as glyph fallbacks only.
  **Gap:** no tone-matched Indic companions (serif or display), and no
  per-personality Indic pairing.
- **Risk found:** a production build downloads every Google font at build time.
  The first `next build` failed on a transient font fetch and the second passed.
  Self-hosting the font files would make deploys deterministic.

### 1.3 Generation pipeline — *strong, keep; meter it and time-box it*
1. Interview (`orchestrator.py`, rules first with the model as reader).
2. Creative direction (`creative_director.py`; archetype, reference profile,
   palette, type).
3. Design DNA (`design_dna.py`).
4. Copy (model, one structured call).
5. Media plan (`media_director.py`), then photo search (§1.4) and fallback drawing.
6. Compose (`site_composer.py`, `site_pages.py`, `layout_engine.py`).
7. Motion budget (`motion_director.py`).
8. Rule critic and polish (`site_critic.py`, ≤ 3 rounds, layout moves only).
9. Draft saved; publish; optional certification gate.

- **Model:** DeepSeek (`deepseek-flash`) through `AI_PROVIDER`, with OpenRouter
  configured as an alternative.
- **One build, measured from the worker log:** `website.personalization` 1 call,
  3.9k in / 1.0k out; `image.query` 12 calls, 12.3k / 1.1k; `image.judge` 12
  calls, 31.0k / 10.3k. Total **25 calls, about 47k in / 12k out**, before the
  interview's own turns.
- **Metered:** only the personalisation call (`usage_events`, 4,909 tokens for
  that build).
- **Build time:** about 90–100 s with photos, but longer once the full photo
  search, judging and drawings all run (§4.2).

### 1.4 Image pipeline — *strong design, weak results; keep and tune*
- `image_retrieval.py`: brief → model-written queries plus a plain or place query
  → pool from Unsplash and Pixabay → prerank → one vision-judge call → LOCAH's
  own gates (`why_not`) → choice with a reason. Each slot's audit is kept on the
  build job, and an empty slot now logs why (`slot_empty`).
- **Attribution:** "Photo by … on Unsplash" / "Image by … from Pixabay", both
  linked, with `utm_source=locah_website_builder`. Unsplash images are hotlinked
  and their download endpoint is tracked; Pixabay images are copied into storage.
  This was checked against Unsplash's published guidelines on 2026-11-24.
  The **LOCAH Website Builder** app is registered and production is pending.
- **Limits:** Unsplash 50/h in demo and 1,000/h on production; Pixabay
  100/min, with its image host throttling bursts (previews now throttled
  per host, and 429s waited out).
- **Drawing:** Cloudflare FLUX.1 schnell (about 170 free a day) for mood slots no
  photo fits. Gemini drawing stays opt-in only. §4.1 covers the rule.
- **Weak results** (baseline §2): covers that don't depict the business's world,
  one photo reused within a page, and whole sites with no photos.

### 1.5 Quality tooling — *strong, keep; widen what it checks*
- **Site lab** (`tools/site-lab/serve.sh`, :3005): saved fixtures for 13 trades
  rendered through the real renderer with no API. `composition-review`,
  `composition-shots`, `motion-shots` and `business-matrix` all run on it.
- **Certification** (`platform_testing/certify`):
  - `render.mjs` renders 4 viewports with axe, broken-link checks, laptop LCP and
    CLS, and interaction.
  - `critic.py` makes one vision call per page plus a cross-page call. It scores
    15 dimensions from 0 to 10 against a reference class: hero, typography,
    spacing, composition, imagery, art_direction, page_depth, originality,
    relevance, cta_hierarchy, catalog_presentation, mobile, consistency, motion
    and not_template.
  - `gate.py` passes a site at a weighted 8.5 with no dimension below 7.
    `distinct.py` checks that two sites of one trade aren't one template.
  - `WEBSITE_CERTIFICATION=off|record|enforce`.
- **Gaps against the brief:**
  - Speed is measured on a laptop, not a throttled Android phone.
  - No Hindi or Tamil renders.
  - Trust and copy quality aren't scored dimensions.
  - The reference screenshots (`docs/visual-references/`) aren't checked in, so
    the critic judges against written takeaways only.
  - The critic is a tool someone runs, not a step in every build.
  - There's no review grid for Pranav.

### 1.6 Motion and WebGL — *strong, keep; budget it*
- In-house runtime (`experience/motion.ts`, `SiteMotion.tsx`; no GSAP, per its
  licence), plus `lenis` for smooth scroll.
- WebGL2 effects (`gl/living`, `ribbon`, `dissolve`) load through `gl/gate.ts`
  only when the design asks for them. They're skipped on reduced motion, motion
  turned off, data-saver, less than 4 GB of memory or no WebGL2, and a page gets
  at most two.
- Every cover has a still state. **Gap:** the cost isn't in a budget. Main-thread
  blocking at 4× CPU is 1.1–3.3 s per page (§2.2).

### 1.7 The `locah-award-sites` skill — *right taste; code drifts from it*
- The skill prescribes type-led composition, art-directed or absent photography,
  "a section with no true photograph is set in type, never a grey plate", one
  signature moment, designed-in conversion, and two same-trade sites differing on
  at least four axes.
- The code drifts: grey plates (room list fixed today, retail "Our story" still
  has one), the coloured-italic accent, the same skeleton across trades, and
  outline marquees.
- Missing from the skill: composed sections, the drawing rule, Hindi/Tamil type
  and the mobile speed budget. These will be added once Phase 1 sets the bar.

## 2. Baseline

**Sites:**
- restaurant `pepper-vine-kitchen-1`
- salon `amber-room-salon`
- gym `forge-strength-club`
- hotel `mistwood-estate-retreat-2` (built 2026-11-23)
- clinic and retail from site-lab fixtures (`audit-clinic`, `audit-retail`); no
  clinic or retail site is published locally.

Screenshots (1440 and 390, full page, reduced motion) are in
`certify-out/review/baseline-1124/`, with contact sheets `*-sheet.jpg`.

### 2.1 Rubric scores (draft rubric, brief §6.2, 1–5)

Scored by Claude from the screenshots. This is a review, not the vision critic;
Pranav's scores replace these.

| Dimension | Restaurant | Salon | Gym | Hotel | Clinic (lab) | Retail (lab) |
|---|---|---|---|---|---|---|
| Visual hierarchy | 4 | 4 | 4 | 3 | 3 | 3 |
| Typography | 3 | 3 | 4 | 4 | 3 | 2 |
| Spacing rhythm | 4 | 3 | 3 | 3 | 2 | 3 |
| Colour & contrast | 4 | 4 | 4 | 4 | 4 | 3 |
| Coherence with art direction | 4 | 4 | 4 | 3 | 3 | 3 |
| Imagery | 3 | 3 | 2 | 2 | 1 | 3 |
| Conversion | 4 | 4 | 4 | 3 | 4 | 2 |
| Trust signals | 2 | 2 | 2 | 2 | 2 | 2 |
| Speed (§2.2) | 2 | 2 | 2 | 3 | n/a | n/a |
| Accessibility | 3 | 3 | 3 | 3 | 3 | 3 |
| **Total** | **33/50** | **32/50** | **32/50** | **30/50** | **25/45** | **24/45** |

Why the low scores, site by site:

- **Restaurant:**
  - The cover photo is reused as a menu card.
  - Coloured-italic accent phrases.
  - Outline-text marquee (low contrast).
  - No reviews.
- **Salon:**
  - The restaurant's skeleton.
  - Hairline Bodoni at small sizes.
  - Long empty stretches.
  - A stock salon interior on the cover could be read as theirs.
- **Gym:**
  - Distinctive personality, but almost no photos.
  - Raw chat-speak and lower-case places in "Good to know".
  - Wrong hours (stale build).
- **Hotel:**
  - Built as a shop: "Call to order" on rooms. Fixed for new builds today.
  - Two room lists.
  - A concrete-wall cover.
  - Empty grey room pictures. Fixed today.
- **Clinic:**
  - A succulent as the cover.
  - A 10-line statement in a narrow centred column with the italic accent.
  - Sparse.
- **Retail:**
  - Body text falls back to a Times-like face.
  - "Order online" against "Call to order" on every card.
  - A grey "Our story" plate.
  - The closer "Ready when you are."

**Proposed pass bar** (to confirm in Phase 1): an average of 4 or more and no
dimension below 3. **No baseline site passes**, which matches the founder's
impression.

### 2.2 Speed on a mid-range Android

Measured with `tools/site-lab/perf-baseline.mjs` on Slow 4G (150 ms, 1.6 / 0.75
Mbit/s) with the CPU slowed 4×, at 390×844, cache off, median of 2. The site was
a **production** build (`tools/certify/stack/web-prod.sh`, port 3210).

| Site | LCP | FCP | Blocking (TBT) | CLS | JS | Fonts | Images | Total |
|---|---|---|---|---|---|---|---|---|
| Restaurant | 4.1 s | 1.0 s | 1.6 s | 0.02 | 164 KB | **392 KB** | 194 KB | 838 KB |
| Salon | 4.6 s | 1.1 s | 3.3 s | 0 | 171 KB | 120 KB | 166 KB | 545 KB |
| Gym | 4.7 s | 1.0 s | 1.7 s | 0 | 164 KB | 110 KB | 0 | 361 KB |
| Hotel | 2.7 s | 1.4 s | 2.8 s | 0 | 171 KB | 90 KB | 250 KB | 598 KB |

- Layout shift is already good.
- JavaScript (about 165 KB) is reasonable for Next. The cost is CPU time:
  hydration plus the motion runtime blocks the main thread for 1–3 s at 4× CPU.
- Fonts are the biggest download: up to 392 KB, several faces plus Indic
  fallbacks.
- LCP on photo-less pages (gym) is 4.7 s, so the large display type and fonts are
  what gate the first meaningful paint.
- Two runs vary by about ±1 s. Phase 1 should take a median of 3 and also run
  Lighthouse.

## 3. Strong, weak, gaps

| Area | Keep | Refactor | Gap against the brief |
|---|---|---|---|
| Sections | 93 variants, composed sections, `normalize()` | Selection: the same few variants win | Schema version per section, knob metadata (verticals, conversion role, cost) |
| Theme | DNA concepts, `merge_theme`, tenant scoping | — | Indic companions; brand colour → OKLCH contrast-safe ramp |
| Generation | Rules first, model second; owner edits win | — | All calls metered; build time budget |
| Images | Brief → judge → gates; attribution | Cover briefs per trade; one photo once per page | Image treatment presets (grade, duotone, grain) |
| Quality | 15-dimension critic, gate, distinctness, render.mjs | — | Mobile-throttled speed, Hindi/Tamil, trust and copy dimensions, review grid |
| Motion | Gate, budgets, still states | Main-thread cost | Performance budget per effect |
| Skill | Taste rules, tells list | Update for today's system | — |
| Trust | — | — | **Reviews/testimonials section bound to the reviews module** (the module exists: `reviews_section`), plus credentials |

## 4. Fixed during the audit

These are firm rules or broken builds, so they were not left for later. Each one
is tested.

1. **AI images never pretend to be the business** (brief §4, firm rule).
   - Drawings were briefed with the business's own things: a hotel cover came
     back as a bedroom, and the passages asked for breakfast on a veranda.
   - Builds now draw **mood slots only**, from a subject that is either the
     region's open land (place-led businesses) or a texture or abstract image in
     the site's art direction. Owner items, rooms, food, people and buildings
     never reach a drawing prompt.
   - Every drawing for every provider passes `media_prompts.unsafe_drawing` at
     the provider boundary, so the editor and interview draw paths are covered
     too.
   - Tests: `tests/test_drawing_rule.py`, eight trades, plus boundary and logo
     cases.
   - Checked with real drawings for the Coorg hotel (Cloudflare, free tier). The
     cover was misty hills. The first passages were one empty white room three
     times (a "light on a plain wall" texture), so walls, floors and ceilings are
     now forbidden too, and a place-led site's passages are different views of
     its land: a path through green hills, mist over slopes at dawn, dew on
     leaves (`certify-out/review/r6-passages-v2.jpg`).
   - Known wart: the media plan labels these drawings `gemini_generated`
     whichever provider drew them.
   - r6 rebuilt **once** on the fixed worker: 1 min 56 s, 25 model calls, 4 mood
     pictures drawn. The room photo slot stayed empty, as it should.
2. **A build that never finished, and repeated its model calls.**
   - The new drawing step reused a variable name, so the build's summary could
     not be saved. The job runner then couldn't record the retry on the broken
     session, so the job kept its lease and was rebuilt every two minutes: 14
     builds and **320 model calls** for one hotel.
   - Fixed: the name, plus the job runner now settles each job in its own
     transaction, rolls back a failed job's own work only, and gives
     `website.generate` a 15-minute lease.
   - Tests: two new worker tests, worker suite green (19).
   - *Correction (2026-11-25):* this audit first said the worker suite had been
     skipped in earlier local runs. It had not: the test setup turns
     `TEST_DATABASE_URL` into `DATABASE_URL` before the tests load, so it ran.
     What *was* true is worse. CI ran strict mypy before pytest, mypy failed every
     run (25 errors), so **CI never ran pytest at all**. CI also triggers only on
     `main` and on pull requests, so this branch's commits were never checked.
     Fixed: the 25 errors are cleared and CI runs a mypy ratchet with baseline 0
     (`tools/ci/mypy_ratchet.py`). Under CI, or with `LOCAH_REQUIRE_DB=1`, a test
     skipped for want of a database is now a failure
     (`platform_testing/require_db.py`).
3. **Interview:** LOCAH says back the check-in times it chose also when it moves
   straight to "I've got enough to build". This path is verified only in a live
   run, not by a unit test.

## 5. Risks

- **Builds depend on downloading Google Fonts.** Deploys can fail at random;
  self-host the fonts.
- **Unsplash is still on the demo limit** (50/h). Two or three builds an hour
  exhaust it and slots come back empty. Production approval is pending
  (founder's click).
- **Published sites are never re-checked.** Fixes don't reach live sites. Wrong
  hours and chat-speak stay up until the owner rebuilds.
- **The certification gate is `record` locally and `off` by default.** No weak
  site is held back today.
- **Reference screenshots are absent.** The critic judges against prose, not
  pictures.
- **Staging is 89+ commits behind** this branch, so the founder doesn't see this
  work there. The working tree is uncommitted.
- **Build time:** a full photo search plus drawings can exceed two minutes. The
  lease is fixed, but the owner still waits; time-box photo search per build.

## 6. Proposed plan, ordered

Effort: S ≤ 1 day, M 2–4 days, L 1–2 weeks of focused work, including tests and
lab runs.

| # | Phase | Item | Effort | Why first |
|---|---|---|---|---|
| 1 | 1 | **Define the bar on the existing critic:** map brief §6.2 onto the 15 dimensions; add `trust`, `copy` and `speed_mobile`; brief §6.1 section contract as a typed check in the lab; proposed budget LCP ≤ 2.5 s, TBT ≤ 600 ms, fonts ≤ 120 KB, JS ≤ 180 KB on the §2.2 profile | M | One rubric for critic and humans; no second system |
| 2 | 1 | **Verticals:** food (restaurant, café, bakery), stays, salon, clinic, local retail; conversion actions and needed sections per vertical | S | Brief §6.4 |
| 3 | 1 | **Review grid for Pranav:** one page per batch with renders × personality × language × viewport, scores and approve/reject | M | Taste is the bottleneck |
| 4 | 2 | **Performance pass:** self-host and subset fonts, load only the site's own faces, defer motion runtime and Lenis on low-end devices, size images per slot | M | Every site, every visitor; conversion |
| 5 | 2 | **Trust and copy:** bind `reviews_section` into plans when reviews exist (honest empty state otherwise), credentials and years; copy checks for chat-speak, template closers and raw owner sentences; re-validate published sites after fixes | M | Every baseline site scores 2/5 on trust |
| 6 | 2 | **Personalities:** formalise the 8 DNA concepts as personalities with Hindi and Tamil companions (Anek, Noto Serif, Mukta families) and an OKLCH ramp from the owner's brand colour | M | Type is the design; languages are a firm rule |
| 7 | 2 | **Break the shared skeleton:** per-concept page rhythms and more composed roles (offerings, CTA, contact), with a cap on any one variant's share | L | The "template" feeling |
| 8 | 2 | **Image treatment and cover briefs per trade:** grade, duotone and grain presets; one photo once per page; drawn mood covers (allowed land or texture only) before an empty cover | M | Weakest dimension |
| 9 | 3 | **Section library, batch 1: food and stays** (most data, clearest conversion), then salon, clinic, retail | L each | Depth before breadth |
| 10 | 5 | **Cost and build time:** meter every model call per build, time-box photo search, vision critic in the build loop with a capped repair (JSON only) | M | Cost measured, not guessed |
| 11 | 4 | **Effects:** budget per effect and mobile fallback, measured in the lab matrix | M | After the budget exists |
| 12 | 6 | **Measure:** owner replacement rate per section and knob, visitor CTA events per site | M | Retire what fails |

## 7. Decisions for Pranav

1. **Pass bar:** average of 4 or more and no dimension below 3, or the existing
   critic's weighted 8.5 with a 7 floor? (They can be the same scale.)
2. **Verticals and order:** food and stays first?
3. **Stock interiors:** may a stock photo of *a* salon interior be a salon's
   cover, or must covers that look like premises be the owner's own?
4. **Re-validating published sites:** may LOCAH fix factual and copy errors on
   live sites automatically (for example wrong hours or chat-speak), or only
   prompt the owner?
5. **Performance budget:** confirm the §6 item 1 numbers, or set your own.

*Not run in this audit:* the vision critic on the baseline (to avoid model
spend), Lighthouse proper (Playwright with DevTools throttling was used), and
Hindi/Tamil renders. Phase 1 adds all three.
