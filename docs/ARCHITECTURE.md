# Architecture

This describes the system as it is built. The code, migrations and tests are
the source of truth; comments citing "Doc NN §x" refer to the historical
specification, kept in Git history (and the offline backup), not in this tree.

## Services

```
 browser ──► apps/web (Next.js)        public platform, auth, Marketplace, tenant sites /{slug}
         ──► apps/workspace (Next.js)  the business Workspace
         ──► apps/admin (Next.js)      Super Admin
                     │  HTTPS + Supabase JWT
                     ▼
              apps/api (FastAPI) ──► Postgres (Supabase) ◄── apps/worker
                     │                                     outbox, deliveries, jobs, sweeps
                     └── Supabase Auth (JWKS) · Supabase Storage · Gemini · payment provider
```

- The Next.js apps never touch the database. They call the API with the user's
  token (server components and server actions), or public endpoints for tenant
  websites. They do not import each other; shared code lives in `packages/*`.
- `apps/api` is the only writer for user actions. It connects as the RLS-enforcing
  `platform_api` role (`API_DATABASE_URL`).
- `apps/worker` uses the owner role (`DATABASE_URL`) because it does legitimate
  cross-tenant work (outbox fan-out, scheduled sweeps, generation jobs).

## Tenancy and access

- **Business** is the tenant. **Locations** belong to a Business. People belong
  through **memberships** with a role (`primary_owner`, `manager`, `member`) and
  explicit permissions (`platform_core/permissions.py`, mirrored in
  `packages/permissions`; a test keeps the two identical).
- Every Business-scoped request runs the gate chain in
  `platform_api/dependencies.py::resolve_business_actor`: membership active →
  Business exists → Entitlement → module state → permission. Location scope
  (`authorization/location_scope.py`) and assignment scope narrow reads further.
- RLS on every tenant table is defence in depth behind those checks.

## Modules

`platform_core/catalog/modules.py` is the module registry (key, label, phase,
dependencies, setup steps, what customers and staff can do). Platform Core
groups are always on. Optional modules pass independent gates — none implies
another:

```
Entitlement (plan / overrides)  →  activation (owner switched it on)
  →  readiness (setup steps true in real data, hard dependencies ready)
  →  permission (the person may use it)  →  the action
```

- `services/entitlement.py` resolves Entitlement and owns enable / deactivate.
  Deactivation is non-destructive: data stays, actions stop, re-enabling restores.
  Both publish `module.enabled` / `module.deactivated` events.
- `services/module_readiness.py::readiness()` answers "can this be used right now,
  and if not, which step is missing" — the same answer for the Workspace and
  every public surface.
- `services/workspace_projection.py` turns readiness into the Workspace
  navigation (`/v1/me/context` → `navigation_modules`, plus the business's own
  words: Menu / Services / Products, Bookings / Reservations, Customers / Clients /
  Guests). Business type only supplies vocabulary and recommendations, never
  behaviour.
- Modules talk to each other through public read functions (for example
  `stock/public.py::public_availability`, `offering_public.py`) and domain events,
  never through another module's tables.

## Website

- Websites are structured content: `website_versions` (one working **draft**, one
  **published**) → pages → sections of registered section types. AI writes words
  and chooses among allowed layouts; it never writes markup or platform mechanics.
- `website/capabilities.py` derives what a visitor can do from module readiness
  (browse the catalogue, order, book, join, enquire) and adds tool sections bound
  to a module (`module_binding`) where the design has none. Bound sections read
  live records through the owning module's public contract; when a module is not
  ready a bound section shows a placeholder in preview and is omitted live.
- **Experience layer.** Each site also gets a composition and motion of its own
  (`interview/experience.py`, `theme.experience`): a motion language (silk, snap,
  float, calm), a hero *scene* (a picture that opens to full-bleed, the business's
  pictures on a turning 3D ring, a tilted wall of pictures, poster type, floating
  layers, a moving gradient for sites without photos), a catalogue layout (a real
  menu book, a pinned rail, bento, spotlight, stacked cards), a story layout and a
  moving band of the business's own words. Choices are limited to what the
  business's content can carry (a ring needs pictures, a menu needs dishes); the
  model may pick among them, `choose_experience` decides. The renderer side is
  `apps/web/.../website/experience` plus `packages/ui/src/site-experience.css`: a
  small in-house runtime (no animation library — GSAP's licence excludes website
  builders) feeds CSS a scroll-progress variable; every scene has a complete still
  state for reduced motion or no JavaScript. `tools/site-lab/serve.sh` renders
  fixtures through the real renderer with no API or database.
- **A site, not a page.** `compose_site` runs a small design pipeline after the
  creative direction: `design_dna.py` picks one art-direction *concept* (noir
  editorial, warm craft, quiet luxury, fresh market, playful, calm care, technical,
  kinetic) that fits the family and the business, then draws the type, headline
  accent, ground, edges, buttons, header, cards and picture shapes inside it
  (`theme.dna`, stable per business; the model's creative director may name the
  concept from a fitting shortlist). `motion_director.py` spends the concept's
  motion budget (restrained / gentle / signature / expressive) — one moving moment
  for a quiet brand, never every card. `site_pages.py` then grows inner pages where
  there is enough to fill them — the range on its own page (`/menu`, `/shop`,
  `/services`…, home keeps a teaser — a picture tile per category with its items and
  starting price — that links to it), `/about`, `/visit` — with a statement,
  pillars beside a picture, how ordering works as steps, a band of numbers that are
  facts or counts of what the owner listed (the year they started, items on the
  counter, areas served, when they open), passages beside pictures and questions
  answered only from the owner's facts. `site_critic.py` reviews the result like an art director (same
  picture twice, box after box, walls of text, too much motion, thin pages) and
  polishes what it can by moving, re-laying or removing — never by writing — for up
  to three rounds; what it cannot fix stays in `theme_hints.quality.critic`. Each
  art direction tells the home page in its own order (`site_pages.arrange`; a page
  order the model chose stands). The range's own-page layout is checked against
  actual content (`composition.py`): unique photos, description depth, size and
  brand concept. Independent opening, category-treatment and range-layout
  choices and reasons persist in `theme.composition`. Photo-free hero fallbacks
  typeset the business's actual range using its concept and theme; photographic
  catalogue cards keep captions on a separate readable surface. Service media
  briefs name the actual offerings rather than prescribe generic interior decor;
  a decor-only image cannot qualify as the hero. `site_vision_critic.py` adds a critic that *sees* the
  rendered site: screenshots go to the configured provider's image call with an art
  director's rubric, and its findings map onto the same safe revisions (layouts,
  order, pictures — never words). `platform_testing/site_vision_loop.py` runs
  render → screenshot → critique → revise over the site lab with headless Chrome
  (reduced motion; phones through `/site-lab-frame`); `--dry-run` costs nothing.
  Personalization merges per page (`draft_merge.py`): owner edits win on every page.
- **The owner personalises; the design stays.** A theme edit is laid over the
  stored theme, never in place of it (`website/owner_style.py::merge_theme`): the
  design pipeline's keys (`dna`, `experience`, `composition`, the family and type
  system) cannot be dropped, colours must be hex, and `theme.owner_style` holds only
  what the renderer can draw — a lettering pairing, heading and reading-text size,
  corners. The renderer applies it last (`experience.ts::ownerStyle`,
  `packages/ui/src/site-owner.css`); a test keeps the Python registry and the
  renderer's lists identical. The Workspace editor
  (`apps/workspace/.../website/preview`) has three tabs on that same API —
  **Sections** (reword, re-picture, drag to reorder, hide, copy, remove, add),
  **Design** (colours, lettering, sizes, corners) and **Ask LOCAH** — and shows the
  real draft at a true desktop width, scaled to fit. Clicking a section in the
  preview opens it in the editor (`apps/web/.../EditorBridge.tsx`, preview only).
- **Composed sections (the layout engine).** Besides fixed variants, a site has
  `composition` sections: blocks (words, quote, list, number, action, label, picture)
  placed on a 12-column grid (6 on a phone) with layers, plates, frames (rounded,
  arch, circle, slant, inset, bleed), grounds, heights and motion
  (`website/composition_grammar.py`; `normalize()` is the one rule-keeper and runs
  on every save, so no layout can overlap words or lose its phone order).
  `interview/layout_engine.py` composes one from a business's own material with
  seeded parametric recipes per role (story, statement, pillars, numbers,
  featured): the same business always gets the same arrangement, two businesses
  rarely do, and the DNA's shape and motion budget decide frames and movement.
  `site_pages.py` composes the statement, the story's start, the featured range,
  the About passages and pillars (on the home when there is no About page). The
  owner can flip a composed section, ask for another arrangement (the same words
  and pictures placed differently; `POST …/sections/{id}/arrange`, or "try another
  layout" in Ask LOCAH) and edit each block in place. Rendered by
  `apps/web/.../experience/Composition.tsx` and `packages/ui/src/site-compose.css`
  (display type fitted to its column, so a long title never overruns its block).
- **A design the owner likes is a direction, not a template.** In Design, "Match a
  design you like" takes a screenshot; one vision call reads it into the governed
  vocabulary only — palette, light or dark, a lettering pairing, corners, heading
  scale, and for composed sections the reference's *geometry* (where pictures and
  words sit), re-bound to the owner's own material (`layout_engine.from_geometry`)
  (`website/reference_style.py`). A dark or light ground is set with its alternate
  band and muted text (`owner_style.ground_family`). Unreadable colours are replaced
  and said so; the reference's pictures and words are never taken. Undo restores
  the draft exactly.
- **A stay is a stay.** Hotels, resorts and homestays (`playbooks.is_stay`) get the
  booking archetype, check-in/check-out instead of opening hours (asked as such;
  "u decide" gets 2 pm / 11 am, said back and set on every room type), and photo
  slots briefed as the place: the property in its landscape in the owner's words
  ("on a coffee estate near Coorg"), the setting, a guest's morning, a close detail
  — never "the counter, the tools"; its own place name is searched as such. An
  empty photo slot logs why (`website.image_retrieval.slot_empty`) and the build
  job keeps the full audit.
- **Drawn only when no photograph fits.** `IMAGE_FALLBACK=cloudflare` draws a
  *mood* slot (cover, story, passages) the photo search left empty with FLUX.1
  schnell on Cloudflare Workers AI (`image_generation.draw_fallback`; ~170 free a
  day). Never a product, a room or a dish — those are the owner's or stay empty —
  and every drawing is labelled a draft visual. A stay's cover is drawn as the
  land, outdoors (a drawn bedroom would pass for the guest's room).
- **Photo credits** read in each library's words ("Photo by … on Unsplash", "Image
  by … from Pixabay"), both names linked, Unsplash links carrying the registered
  app's `utm_source` (`locah_website_builder`).
- **A headline speaks in one voice.** `design_dna.py` draws `headline: none` most
  often; a coloured italic phrase is an exception a concept must offer, and the
  italic label of warm_craft / calm_care follows it. A tool's section (plans,
  catalogue, booking band) is placed inside the page, beside the range it
  completes, never under the closing band (`services/website_publish.py`).
- **Changing the site by saying so.** `website/site_assistant.py` reads an owner's
  words ("chnge colur to maroon", "move the menu above our story", "make the text
  bigger") into the same governed changes, rules first; the model is asked only
  for what the rules could not read and its answer is held to the same vocabulary
  (`from_model`). `services/website_assistant.py` applies them through the
  editor's own services and replies with what was done and, plainly, what was not.
- **The catalogue is captured, not summarised.** For trades whose website is their
  catalogue, the interview asks for the real list early (`offerings.catalogue`:
  a photo/PDF of the menu or price list, or typed out) and then what a visitor
  looks for (`offerings.traits`: bestsellers, veg / non-veg).
  `interview/catalogue_capture.py` reads a typed list by rule ("Idli 40, Dosa 70",
  headings, `/kg`, durations, sizes) so it works with the model down; items carry
  diet, spice and the owner's tag to the site and, on setup, to the Offerings
  catalogue with their categories.
- The public page (`services/website_publish.py::load_public_page`) is projected
  per request from the published version plus current capabilities, so switching a
  tool on or off changes the site without republishing content. `apps/web` caches
  it (`website:{slug}` tag); the worker's `website.revalidate` subscriber calls the
  web app's `/api/revalidate` (shared secret) whenever something the site renders
  changes.

## Events and background work

- Services write domain events to `platform_outbox_events` in the same
  transaction as the change. The worker fans each event out to its subscribers
  (`platform_core/events/subscribers/`) as `platform_event_deliveries`, runs them
  with retries and backoff, and processes async jobs (website generation, document
  reading, image drawing). `/health/worker` reports outbox lag.

## Conversation and AI

- **Talk to Locah** (`platform_core/interview/`): a coverage-driven conversation
  that fills a structured `BusinessBlueprint` (facts, catalogue, actions, language
  preference). The model proposes; deterministic readers and planners decide what
  is stored and what is asked next. It works with the model down. English, Tamil
  and Tanglish are supported in the same conversation.
- **An owner's slips never reach their customers, or their records.** Trade words
  spelt wrong still name the trade (`catalog/taxonomy.py::respell`, a curated list —
  a general spell-checker "corrected" real words); what a business mentions is not
  what it is ("we design small hotels" is an architect; "near the temple" is a
  place); a kitchen is read from what it cooks. A price list typed in one breath
  ("chiken biriyani 280 mutton 360 appam 50 for 2") is every item with its price
  (`catalogue_capture._run_on`), and dish and service names are put right
  (`interview/spelling.py`; regional spellings such as "biriyani" are kept).
- Website generation and document reading go through the provider abstraction
  (`AI_PROVIDER`: DeepSeek by default, Gemini selectable, `replay` locally; voice is
  separate, `VOICE_PROVIDER`, Gemini). Provider calls live in
  `website/ai_provider.py`; the Creative Director never names a vendor.
- **The creative plan must arrive.** DeepSeek's `max_tokens` counts reasoning as
  well as the answer: a purpose that thinks gets headroom and low effort, the
  creative plan (`website.personalization`) answers without the reasoning pass,
  an answer missing its last bracket is read (`loads_lenient`), a top-level part
  written inside its sibling is put back (`_rehome`), and an empty or unreadable
  answer is asked for once more without thinking. A build that still falls back to
  the deterministic direction logs `interview.creative_plan_failed` with the reason.
- **A site's photographs are its own.** A photo another business already shows is
  never offered to the judge (`SiteMemory.elsewhere`), and each item is also
  searched by its plain name.
- **Website pictures are found, not drawn.** For each picture slot the
  MediaDirector plans (hero, categories, items, story), `website/image_retrieval.py`
  asks the provider for search queries, queries a photo API
  (`website/image_search.py`: Pexels when keyed, otherwise keyless Wikimedia Commons
  limited to freely licensed files), filters candidates without a model, shows the best
  few to a vision-capable model in one call, applies LOCAH's own acceptance rule,
  checks the winner's URL serves an image, and otherwise retries with the rejection
  reasons (bounded by `IMAGE_MAX_ROUNDS`). Nothing is stored: the vision check sees a small preview held in memory,
  and a verified photo is a `media_assets` row whose `public_url` is the photo URL (`source_type
  stock_photo`, bucket `external`), referenced by id like any picture. Factual
  slots are never filled, and a slot that finds nothing stays empty — never an
  unchecked picture. Gemini drawing remains only as the explicit
  `IMAGE_PROVIDER=gemini` opt-in (and the only way to draw a logo).
- **AI employees** (`platform_core/ai_employees/`) run on one runtime with tool
  tiers (T0 read … T3 owner approval), an allowlist per employee, limits and a kill
  switch; every decision is an `ai_actions` row. The AI Employee Sandbox simulates
  an employee on the business's real records without writing or sending anything.

## WhatsApp

`messaging/journeys.py` is a structured chatbot — order, book, enquire, dues,
track, reorder, cancel — with buttons and lists and zero model calls; every path
ends in the same order, booking or lead the website creates. A short typed
question is answered from the live catalogue ("biriyani rate?" → the biriyanis and
their prices, in the customer's spelling); a wish typed as a sentence starts its
journey; an unhappy or long message waits for a person. `MESSAGING_SANDBOX=1`
(development only) connects a sandbox number whose inbound messages take the real
webhook path (`tools/certify/owner-lab/whatsapp-check.mjs`). Meta's Cloud API,
Embedded Signup and template approval need LOCAH's own Meta app and have not been
exercised from this repository.

## Payments

Merchant collection (what a business charges its customers) is separate from
platform billing. The payments kernel owns attempts, refunds and webhook
receipts; provider specifics sit behind the provider adapter (`stub`, `razorpay`).
State only moves on a verified webhook, never on a browser callback. Pay at
pickup / on delivery stays "to collect" until money is recorded.

## Data

- Migrations: `infra/supabase/migrations/*.sql`, forward-only, keyed by version.
- Seed: `infra/supabase/seed/00_platform.sql` (module and section-type registries;
  idempotent, required).
