# Judging a site

Score each dimension 0–10 **against the reference class** (Awwwards SOTD,
premium agency work, the founder's reference pack in `docs/visual-references/`),
never against average small-business sites. 8 = belongs beside the references;
5 = a polished template; 3 = amateur. The certification gate passes at a
weighted 8.5 with no dimension under 7 and no critical defect
(`platform_testing/certify/gate.py`) — never lowered to let a site through.

| Dimension | 9–10 looks like | 5 looks like |
|---|---|---|
| Hero | a composed cover with one idea, type at display scale, the photo art-directed, one action | photo + dark overlay + centred headline + three buttons |
| Typography | a face with authority, one contrast move, set tight, real hierarchy across 4+ sizes | one weight everywhere, timid sizes, default leading |
| Composition | asymmetric placements, full-bleed moments, varied density, sections that answer each other | stacked card grids, everything centred, equal spacing |
| Imagery | one grade, true subjects, crops per role, no repeats | mixed white balance, stock clichés, the same photo twice |
| Art direction | concept legible in every section (type, colour, shape, motion agree) | each section a different template |
| Motion | one signature moment, quiet everywhere else, reduced-motion still complete | everything fades up the same way, or nothing moves |
| Interaction | cursor/hover/press states that reward attention | default links and buttons |
| Conversion | the live action always within reach, honest urgency, frictionless forms | CTAs that lead nowhere, three equal buttons |
| Range/menu | chapters with plates and prices, the special first | a data dump |
| Mobile | composed for 390 px (not shrunk), thumb-reachable action | desktop squeezed, bar covering content |
| Originality | could not be another business's site | a template recoloured |
| SEO/tech | JSON-LD, OG image, CWV in budget, alt text, one h1 | none of it |

## Severity

- **Critical**: overflow at any viewport, broken image or empty frame, words
  split mid-word, contrast failure on the primary action, an action that leads
  nowhere, invented facts, a photo of the wrong product.
- **Major**: template tells (SKILL.md §3), repeated photos, a section with no
  purpose, a cramped footer, a range as a data dump, a bar covering content.
- **Minor**: spacing, a weak caption, a widow, an eyebrow too loud.

## Before / after discipline

Shoot the same pages at the same viewports (lab_shots or render.mjs) before and
after; compare side by side; say what improved and what got worse. A change is
kept only when the page gets better (the repair loop keeps a fix only when the
page's score rises ≥ 0.25).
