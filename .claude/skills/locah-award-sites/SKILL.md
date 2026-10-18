---
name: locah-award-sites
description: LOCAH's design brain for tenant websites — the taste, the bar and the build rules for making every business's site look like a $10k, Awwwards-grade custom build (3D/WebGL moments, scroll-driven storytelling, interaction, conversion, local SEO) inside LOCAH's structured-content architecture. Use for ANY work that changes how a tenant site looks, moves or converts — covers/heroes, sections, the design DNA, motion runtime, WebGL, the critic/repair loop, the site lab, certification screenshots — and when reviewing or critiquing a generated site. Not for the LOCAH platform's own UI (Workspace, marketing).
---

# LOCAH award-grade sites

The founder's bar, in his words: *"This looks expensive. A real designer worked on
this."* — beside Lovable, Rocket and Awwwards Site-of-the-Day work; every business
different (two butchers included); 3D, scroll-based, dynamic, interactive, built to
convert and to be found. A technically valid site that looks like a template is a
failed site.

This skill is the taste, made concrete. Read it before designing; read the
reference that matches the task:

| Task | Read |
|---|---|
| Adding or changing a cover, section, effect, 3D or scroll moment | `references/signature-moments.md` |
| Deciding how a trade should look and move | `references/trades.md` |
| Calls to action, booking/ordering surfaces, trust, SEO, JSON-LD, speed | `references/conversion-seo.md` |
| Judging a site (yours or the critic's), before/after, release gate | `references/rubric.md` |

## 1. How the architecture shapes taste (never break these)

- **Structured content, platform components.** The AI writes words and *chooses*
  allowed layouts; platform code owns every component, cart, checkout, booking,
  payment and permission (AGENTS.md). A new look is a new platform composition
  (a cover, a section variant, a DNA value, a signature) the composer can choose —
  never model-written markup.
- **The design DNA is the contract** (`python/core/platform_core/interview/design_dna.py`
  → `theme.dna` → `data-*` on `[data-locah-site]` → `packages/ui/src/site-dna.css`).
  Every value a concept can draw MUST map to CSS (a test enforces it). Concepts:
  noir_editorial, warm_craft, quiet_luxury, fresh_market, playful_pop, calm_care,
  technical_grid, kinetic_sport.
- **CSS load order, later wins:** website.css → site-studio.css → site-families.css →
  site-experience.css → site-covers.css → site-dna.css. Tenant tokens only
  (`--site-*`); never LOCAH's own colours.
- **Motion runtime, no animation library.** `apps/web/src/components/website/experience/motion.ts`
  feeds CSS numbers: `data-reveal` (fade/scale/left/right/mask), `data-reveal-group`,
  `data-split` (words), `data-progress` / `data-scene` (`--p` 0→1), `data-parallax`
  (`--speed`), `data-pointer`, `data-tilt`, `data-magnetic`, `data-count`,
  `data-rail`; root gets `--scroll`, `--mv` (velocity). Lenis (MIT) smooths desktop.
  **No GSAP** (its licence forbids website builders). Motion (MIT) or raw WebGL /
  OGL-style code is allowed; Three.js (MIT) only behind a dynamic import.
- **The still state IS the design.** Everything renders finished with no JS, with
  `prefers-reduced-motion`, in a crawler and in a screenshot. Hide nothing unless
  `[data-fx='on']`. WebGL is progressive enhancement over a real `<img>`.
- **Budgets:** LCP < 2.5 s on a mid phone, CLS < 0.05, INP < 200 ms. Heavy code
  (WebGL, Lenis) loads after interaction-ready, only on capable devices
  (`deviceMemory >= 4`, not `saveData`, pointer fine for pointer effects).

## 2. The taste, as rules you can check

**Type is the design.** One display face with authority (DNA picks it) at real
display sizes — 7–11vw on a cover, never a timid 3rem; leading 0.88–1.0; tracking
tightened for grotesks, opened for caps; one contrast move per headline (serif
italic phrase, a tone shift or caps — never underline, gradient or marker).
Body 16–18 px, 1.55, 60–70ch. Small labels as tracked capitals or mono with a
hairline — never a pill with a glowing dot.

**Composition over components.** A premium page is a sequence of *compositions*,
not a stack of card grids: asymmetric 12-column placement, a full-bleed moment,
type set against image edges, numbered chapters (01/02), captions and metadata,
generous and *varied* whitespace (dense → airy → dense). Never three identical
card grids in a row; never everything centred.

**Photography is art-directed or absent.** One grade per site (DNA `photo`),
subject truth over beauty (`image_retrieval.py` gates), crops chosen per role
(hero wide with room for words; plate 4:5; story portrait). No stock clichés
(handshakes, laptops, smiling headsets). A section with no true photograph is
set in type — never a grey plate or a gradient blob.

**Colour is held back.** One saturated hue on ~5–10% of pixels; everything else
from ink and ground. Tonal chrome (utility bar, marquee, closing band). Section
grounds may *morph* as you scroll (see signature `ground_morph`) instead of
hard slabs.

**Motion is choreography, not decoration.** One signature moment per page that
is unmistakably this brand's; everything else quiet: text lines rise with a
mask, images open like curtains, numbers count once. Easing: expo-out for
arrivals (`cubic-bezier(.16,1,.3,1)`), quart-in-out for scrubs; 700–1100 ms
arrivals, 40–60 ms stagger. The DNA `budget` decides how much moves
(restrained → expressive). Never animate layout properties; transform/opacity/
clip-path/filters only.

**Interaction rewards attention.** A contextual cursor label ("View", "Add",
"Book") on fine pointers; magnetic primary buttons; hover reveals that show
real content (a dish's photo following the pointer on a menu list); state you
can feel (pressed, added, booked). Every hover has a focus equivalent.

**Conversion is designed in, not bolted on.** One primary action per screen,
the business's live tool first (order/book/join), its channel second
(WhatsApp/call). The action is never more than a thumb away on a phone (sticky
dock) and never more than a glance away on desktop (dock after the cover).
Honest urgency only (open now, today's slots, made to order by Friday).

**Personal, not generic.** Every site is a combination nobody else has:
concept × cover × signature moment × display face × palette × grade × section
rhythm × the owner's own words and pictures. Two businesses of one trade must
differ in at least four of these (`certify/distinct.py` measures it).

## 3. Template tells — reject on sight

Pill eyebrow with a status dot · three equal buttons in a row · tick-circle
badges · gradient or marker text · underlined accent words · 28px-rounded cards
with coloured glows · stock "team high-five" photos · emoji in display copy ·
every section centred · the same card grid three times · a hero that is a
photo with a dark overlay and centred text · decorative blobs · a map texture
that is not a map · lorem-ish filler ("quality you can trust") · a footer that
is one cramped column · placeholder image frames.

## 4. Process (every change)

1. **Choose by the business**, not by novelty: read `references/trades.md`, then
   pick the cover, signature and section rhythm the concept owns.
2. **Build as a platform composition**: TSX in `apps/web/src/components/website/…`,
   CSS in the right layer, DNA/composer choice in Python, a forward-only
   migration for any new `layout_variant`, mirrors in tests
   (`test_business_interview.py` variants list, `test_website_premium_site.py`
   CSS-contract test).
3. **Still state first**, then motion, then WebGL; check reduced motion, no-JS
   and phone 390 px. Keep tap targets ≥ 44 px, contrast AA.
4. **See it**: site lab (`tools/site-lab/serve.sh`, :3005; `platform_testing.lab_shots`)
   or the certification stack (`tools/certify/render.mjs` — four viewports, full
   page, reduced motion). Look at 1440 and 390 with your own eyes; then with
   motion on in the browser pane.
5. **Judge it with `references/rubric.md`** and the vision critic
   (`platform_testing.certify.critic` / `loop.py`); fix the layer the defect
   lives in; re-render. Never lower a threshold to pass.
6. **Verify**: `npx tsc --noEmit -p apps/web`, `next lint`, ruff, mypy, the website
   pytest suites on local Postgres (`TEST_DATABASE_URL`, port 54329). Say what
   ran.
