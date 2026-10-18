# Signature moments — the catalogue

A *signature moment* is the one thing on a page a visitor remembers and would
describe to a friend. Each site gets one or two (DNA `signature`, chosen per
concept and seeded per business), never all of them. Everything here is a
platform composition: still state complete without JS, motion only under
`[data-fx='on']`, WebGL only as enhancement over a real `<img>`.

Status column: **live** = in the renderer today; **build** = specified, to build.

## Covers (the first screen) — `experience/Covers.tsx`, `HeroScenes.tsx`

| Cover | What it is | Its move | Status |
|---|---|---|---|
| `arch` | words beside a tall arched photo, round inset over its edge | arch rises open, drawn line slides out, photo drifts | live |
| `window` | headline across the page, photo seen through a band between its lines | band opens, lines part (pinned scene) | live |
| `gallery` | editorial collage, three photos, three sizes | masks open in turn, three parallax speeds | live |
| `ledger` | ruled sheet: headline, photo, owner's hours/address/phone | rules draw cell by cell | live |
| `signature` | food photo + priced dishes worth coming for | photo settles, list arrives line by line | live |
| `stage` | centred headline, photo matted beneath | frame rises toward you | live |
| `cinematic_zoom` | framed photo opens to full bleed, words split on its edge | scrubbed clip-path open | live |
| `kinetic` | poster type pulling apart around a picture (poster faces only) | lines part | live |
| `orbit` / `plane` | 3D ring / tilted wall of 6–8+ distinct photos | ring turns / wall straightens | live |
| `depth` | photo with floating framed pictures (homes, project work) | layers drift | live |
| `aurora` | living gradient for sites with no photo | slow flow | live |

## WebGL — `experience/gl/` (raw WebGL2, no library, dynamic import)

**`living` — the living photograph** (live: `gl/living.ts`, `GlLiving.tsx`). The cover's photo drawn on a
canvas laid exactly over its `<img>` (the img stays for SEO/fallback; it hides
only once the first GL frame is painted). Uniforms: `u_progress` (scene `--p`),
`u_velocity` (scroll velocity, smoothed), `u_pointer` + `u_hover`, `u_time`.
Fragment: cover-fit UV; a soft *liquid* displacement around the pointer
(radius ~0.34, lens push 0.26, ripple 0.0075 — tuned until a pixel diff showed a visible bend, ~31k px; decays over 600 ms); a vertical *stretch* with scroll velocity
(max ~2% of height, eased back); chromatic split = velocity × 0.002; film grain
(DNA texture grain); an arrival *dissolve* (noise threshold 0 → 1 over 1.2 s).
DPR capped at 1.75. Only 1–2 instances per page. Respect the concept: quiet_luxury
and calm_care → no chroma, half displacement; noir/kinetic → full. The pointer's
colour fringe follows the brand's chroma, so a calm brand never gets a rainbow.

**`ribbon` — the curved gallery** (live: `gl/ribbon.ts`, `useGlRibbon`). A strip of the range's / gallery's
photos on a bent plane (cylinder radius ~3× viewport width) inside a pinned
section; scroll moves the strip sideways, velocity bends it more and tilts the
cards; hovered card un-bends and its caption rises in DOM. Fallback: the
existing `rail` (CSS horizontal scroll). For ranges with ≥ 6 pictured items.
The pinned rail's stage sits in a `.fx-rail__pin` exactly as tall as its travel
(progress is measured over `--track`, not the section) so the range's other
things never scroll up under the cards.

**`dissolve` — image to image** (live: `gl/dissolve.ts`, `GlDissolve.tsx`,
`Story.tsx` `HeldPicture`). A story's held picture (sticky split, story split,
about split) becomes another of the business's own as the story is read — a
noise front over `--p` 0.35→0.75; a CSS crossfade without GL. Never name a
component so it differs from its renderer only in case (Windows resolved
`import('./dissolve')` to `Dissolve.tsx` itself).

Device gate for all GL: WebGL2 present, `deviceMemory >= 4` (when known),
not `saveData`, not reduced motion. One shared loader; contexts released on
unmount; `IntersectionObserver` pauses offscreen canvases.

## Scroll choreography — `motion.ts` + CSS

| Moment | Spec | Status |
|---|---|---|
| `ground_morph` | as each section crosses 50% of the viewport the page ground eases to that section's ground: one continuous colour story instead of slabs, 700 ms. Only between `bg` and `alt` — an ink or accent ground under dark text is unreadable | live |
| variable type | display faces with axes move on scroll: Fraunces `SOFT`/`WONK`, Archivo `wdth` 62→100, Instrument Sans `wdth` — the title's axis eased in as it arrives (`--vk`) | live |
| line mask reveal | headings rise line by line behind a mask (`data-split`) | live |
| statement read | long statement lit word by word as read (`data-split='read'`) | live |
| image curtain | `data-reveal='mask'` clip-path open + 1.22→1 scale | live |
| zoom-through | a statement/story photo scales to fill the viewport, then the next section slides over it (`--p`, clip-path `--open`) | live |
| pinned rail | horizontal travel of large cards while the section holds (`data-rail`) | live |
| stacked cards | plans/services stick and stack | live |
| marquee | the business's own words, velocity-skewed | live |
| velocity skew | images skew ≤ 2.6° with `--mv`; never on restrained budgets | live |

## Interaction

| Moment | Spec | Status |
|---|---|---|
| contextual cursor | ring cursor grows over `[data-cursor-label]` and shows the label ("View", "Add", "Book", "Call"); blend difference on dark; fine pointers only; DNA `cursor_label` | live |
| hover image reveal | on menu/service lists, the item's photo follows the pointer (`hover_list`) | live |
| magnetic buttons | primary CTAs pulled toward pointer (`data-magnetic`) | live |
| tilt + light | cards lean, a light slides (`data-tilt`) | live |
| page transitions | cross-document View Transitions: the site name and header persist, content fades/slides; `@view-transition { navigation: auto }` + `view-transition-name` on the wordmark; same-site links via `startViewTransition` | live |
| intro | the business's name once per visit, curtain lifts (premium/heritage) | live |

## Conversion surfaces — see conversion-seo.md

Action dock (desktop after the cover; phone always), open-now chip, signature
list in the cover, booking summary card, WhatsApp prefilled per item/plan.

## Choosing (the `signature` DNA trait)

| Concept | Signatures it may draw (seeded per business) |
|---|---|
| noir_editorial | living (full), ribbon, velocity skew, ground_morph to ink |
| warm_craft | ground_morph (paper ↔ warm), variable type (Fraunces SOFT/WONK), living (gentle) |
| quiet_luxury | dissolve, zoom-through, living (no chroma) |
| fresh_market | ribbon, contextual cursor "Add", hover image reveal |
| playful_pop | variable type, contextual cursor, velocity skew |
| calm_care | ground_morph (soft), dissolve |
| technical_grid | variable type (width), ledger rules, contextual cursor |
| kinetic_sport | variable type (Archivo wdth), velocity skew, living (full) |

**Material decides too.** A moment is only drawn where the pages have
something to show it on (`site_composer.unshowable_moments`): `living` a cover
photograph, `ribbon` six pictured things in a rail or bento, `dissolve` a
story picture and another to become, `zoom_through` a statement over a photo,
`velocity_skew` three leaning pictures. Otherwise the DNA draws again without
it and nothing else about the brand changes.

Budgets gate them: `restrained` → one signature, no velocity effects;
`gentle` → one; `signature` → two; `expressive` → two plus velocity.
