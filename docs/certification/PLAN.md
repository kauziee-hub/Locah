# Website Builder Certification — plan and contracts

Goal (founder, 2026-10-18): realistic business-owner journeys must reliably end
in websites of the same professional class as the reference pack
(`docs/visual-references/BRIEF.md`). A technically valid website that looks
mediocre is a FAILED test. A weak site must never be silently published: after
bounded repair rounds Locah fails closed with a concrete owner request.

## 0. Ground rules

- Real owner paths only: business start → interview turns → tool choices →
  owner media → build job → editing APIs → module endpoints → publish. No
  seeding of website data. The interview and creative plan use the configured
  AI provider (DeepSeek); photos use Unsplash + Pixabay. Tests (pytest) never
  call real providers — the certification run is a tool, like premium_lab.
- Never lower a threshold to pass. A failure is fixed in the generator,
  composer, renderer or pipeline — or reported as a genuine external blocker.
- Local only: Postgres 54329 db `locah_certify`; never the hosted database or
  hosted storage.

## 1. The matrix (module ids from `platform_core.catalog.modules`, the source of truth)

| # | Scenario | Modules (besides core website) |
|---|---|---|
| 1 | Restaurant — delivery | offerings-catalog, orders, payments, fulfilment |
| 2 | Restaurant — reservations | offerings-catalog, bookings |
| 3 | Meat / butcher shop | offerings-catalog, orders, fulfilment |
| 4 | Bakery — call/WhatsApp | offerings-catalog |
| 5 | Gym | offerings-catalog, memberships, bookings, payments |
| 6 | Salon | offerings-catalog, bookings, payments |
| 7 | Clinic | offerings-catalog, bookings, queue-operations, workforce |
| 8 | Consultant | offerings-catalog, leads, customer-relationships, invoicing |
| 9 | Retail store | offerings-catalog, inventory, orders, payments, fulfilment |
| 10 | Architecture / interiors | offerings-catalog, leads, quotes, projects |
| 11 | Hotel | offerings-catalog, bookings, payments |
| 12 | NGO | donations, leads |

Information variants per scenario: `rich`, `normal`, `bad_input`, `minimal`,
`no_photos` (forces sourcing to carry the site), `owner_media` (owner photos
must take precedence). 12 × 6 = 72 journeys.

Distinctness set: 5 restaurants, 5 gyms, 5 salons, 5 professional services,
5 retail (normal variant, different owners) — 25 journeys.

## 2. Components and contracts

All run artefacts go to `certify-out/<run>/` (git-ignored).

1. **Stack** — `tools/certify/stack/`: `supabase-local.mjs` (auth like
   `tools/acceptance/stack/mock-auth.mjs` + storage: `POST
   /storage/v1/object/<bucket>/<key>` stores to disk, `GET
   /storage/v1/object/public/<bucket>/<key>` serves it, signed upload URLs
   for owner media), `api.sh` / `worker.sh` (local DB + real provider keys
   read from `.env`, nothing else from it), `web.sh` (public renderer on 3200
   → API 8020).
2. **Owners** — `python/testing/platform_testing/certify/owners.py`:
   `Scenario(key, business_name, category, modules, variants{variant: OwnerScript})`;
   `OwnerScript(opening, answers{ask_target: text}, fallback, media[paths])`.
3. **Journey** — `certify/journey.py`: drives one owner over HTTP; writes
   `<run>/sites/<site_key>/journey.json`:
   `{site_key, scenario, variant, business_id, slug, modules_enabled,
     modules_failed{module: reason}, turns[{ask, said, reply}], build{status, seconds},
     pages[slug], published: bool, public_url, preview_url}`.
4. **Render** — `tools/certify/render.mjs <site_dir> <base_url>`: every public
   page (home, nav pages, enabled action pages) × viewports
   `xl 1920×1080, laptop 1440×900, tablet 834×1112, mobile 390×844`, full
   page (CDP captureBeyondViewport, reduced motion emulated, fonts + images
   awaited) → `shots/<page>__<viewport>.png` and `render.json`:
   `{pages[{slug, url, status, title, meta{description, og_image, canonical},
     viewports{vp: {png, height, overflow_x, broken_images, imgs_without_alt,
     lazy_offscreen_missing, lcp_ms, cls, console_errors, axe{violations[{id, impact, nodes}]},
     links[{href, status}]}}}]}`.
5. **Critic** — `certify/critic.py`: one vision call per page group (desktop
   xl+laptop, tablet, mobile) with the page shots, the category's reference
   takeaways (+ `docs/visual-references/ref_XX.png` when present) and the
   site manifest → `critique.json`:
   `{scores{hero, typography, spacing, composition, imagery, art_direction,
     page_depth, originality, relevance, cta_hierarchy, catalog_presentation,
     mobile, consistency, motion, not_template}: 0-10,
     defects[{id, page, section, viewport, severity: critical|major|minor,
     layer: copy|photo|composition|order|styling|motion|responsive|architecture|input,
     text}]}` plus deterministic defects from `render.json` and the payload.
6. **Repair** — `certify/repair.py`: maps each defect to ONE layer lever via
   the owner/editor APIs (section PATCH layout_variant/content, reorder,
   generate-image, theme PATCH of one DNA trait, conversational copy edit),
   never a full rebuild; bounded rounds (3).
7. **Gate** — `certify/gate.py`: PASS = weighted score ≥ 8.5/10, every
   dimension ≥ 7, zero critical, ≤ 2 major. Else after the last round:
   FAIL CLOSED with owner requests generated from the remaining `input`/`photo`
   defects ("We need 2-3 photographs of your actual clinic…", "Please answer
   these three questions…"). The product side: the certification result is
   stored on the draft and publish refuses an uncertified/failed draft
   (feature flag `WEBSITE_CERTIFICATION=enforce|record|off`).
8. **Distinctness** — `certify/distinct.py`: signature per site (section
   sequence per page, hero scene + variant, dna display/body/headline,
   palette hex + hue, layout primitives = section variants + dna
   cardstyle/shape/divider/button/navstyle, image treatment = dna.photo +
   grade, motion = budget + experience.motion + moving sections) → pairwise
   similarity; a category fails when any pair exceeds 0.6 or the category's
   mean exceeds 0.45.
9. **Edits & lifecycle** — `certify/edits.py`: the 12 owner edits on a built
   site, asserting manual edits survive later regeneration; module lifecycle
   enable → configure → activate → deactivate → re-enable with each gate's
   distinct failure (EntitlementRequired, ModuleNotActive, dependency,
   location, permission, workflow state).
10. **Report** — `certify/report.py` → `docs/certification/REPORT.md` +
   comparison sheets (`<run>/sheets/*.jpg`).

## 3. Known weaknesses to re-test (from the photo handoff)

Stock coverage gaps, Unsplash quota (50/h demo key — an external limit),
judge variance, species/cut acceptance, empty premium-photo slots. Fix with
logic (e.g. species rubric line, double-judging finalists), never by lowering
thresholds.

## 4. State

See `docs/certification/STATE.md` (updated as each component lands).
