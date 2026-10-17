# Locah Premium Website Builder - Claude Visual Reference Brief

## Purpose

The images in this pack define the **visual quality bar** for Locah. They are **not templates to copy**. They are references for composition, typography, art direction, image treatment, section rhythm, interaction quality, and overall professionalism.

The target is not “a nice generated website.” The target is a **premium, art-directed, agency/Figma-level website that feels like a $10k custom build**.

## Non-negotiables

- Work on the current Locah repo/branch as it exists now.
- **Do not disturb the current DeepSeek/OpenRouter setup.**
- Preserve existing Business OS behavior, routes, auth, payments, booking/order logic, and data contracts.
- `.env` has been updated, so image-aware workflows / image sourcing / vision routing can now be used where already supported.
- Improve the current Creative Director + design DNA + experience/rendering system rather than replacing the project with a second unrelated architecture.
- These references are for **quality and design language**, not exact copying.

## What must improve

### 1. Entire-site quality, not just the homepage
Home, menu/shop, services, about, gallery/portfolio, contact/visit, booking/reservation and other inner pages must all feel intentionally designed.

### 2. Menu/shop/service pages are currently too blunt
Do not dump plain lists. Build category-led, editorial, image-rich pages with featured/special items, meaningful descriptions, hierarchy, signature offerings, process/sourcing/trust content, and strong visual rhythm.

### 3. Premium composition
Avoid repetitive card grids and predictable section stacks. Use:
- large typography
- asymmetry
- overlapping compositions
- editorial grids
- image-led storytelling
- framed and masked media
- split layouts
- sticky sections where justified
- varied section densities
- strong whitespace and spacing rhythm
- immersive closing CTAs

### 4. Business-specific design
Two businesses in the same category should still feel different in:
- mood
- layout rhythm
- section order
- type personality
- image treatment
- motion intensity
- color strategy
- signature moments

### 5. Motion and interaction
Where appropriate, use polished motion:
- hero reveals
- subtle parallax/depth
- sticky storytelling
- scroll-linked line/progress animation
- kinetic typography
- image mask reveals
- premium hover states
- section transitions

Do not animate everything. Motion must feel art-directed.

### 6. Visual self-critique
If practical, implement or use:
**render -> desktop/mobile screenshot -> vision critique -> revise -> render again**

Critique specifically for:
- generic-looking hero
- weak hierarchy
- repetitive section patterns
- under-designed menu/service pages
- poor image choices/crops
- bland mobile composition
- awkward spacing
- excessive cards
- pages that feel “AI generated”

## Expected standard

A viewer should think:

> “This looks expensive. A real designer worked on this.”

Not:

> “This is a polished template.”

## Reference image takeaways


### Reference 01 - Architecture / Editorial Minimalism

Use oversized typography, strong whitespace, asymmetric composition, image-text overlap, restrained monochrome palette, and a portfolio-like rhythm.

![Reference 01](ref_01.png)

### Reference 02 - Architecture / Cinematic Hero

Use full-bleed imagery, giant display type behind/around the subject, sparse navigation, layered annotations, and a strong single-screen identity.

![Reference 02](ref_02.png)

### Reference 03 - Luxury Interiors / Dark Editorial

Use dark tonal depth, framed image panels, precise grid lines, subtle borders, vertical type, and editorial storytelling rather than generic cards.

![Reference 03](ref_03.png)

### Reference 04 - Furniture / Material-Led Luxury

Let texture and product photography drive the page. Use rich brown/black palettes, modular editorial grids, tactile close-ups, and restrained typography.

![Reference 04](ref_04.png)

### Reference 05 - Fine Dining / Warm Editorial

Use a premium serif/sans pairing, warm cream tones, elegant hero framing, menu imagery as composition, and spatially varied content blocks.

![Reference 05](ref_05.png)

### Reference 06 - Restaurant / Dark Green Food-First

Use dramatic food photography, deep brand colors, generous negative space, editorial ingredient storytelling, and large photographic sections.

![Reference 06](ref_06.png)

### Reference 07 - Restaurant / Dark Premium Menu

Use immersive hero photography, richer menu narratives, highlighted signature dishes, category-led sections, and strong contrast. Avoid plain price-list dumping.

![Reference 07](ref_07.png)

### Reference 08 - Fitness / Cinematic Energy

Use bold condensed typography, motion-ready hero composition, cut-out subjects, dark high-contrast sections, powerful CTAs, and transformation-focused content.

![Reference 08](ref_08.png)

### Reference 09 - Coaching / Modern Service Brand

Use a clear service narrative, confident typography, premium cards only where justified, social-proof cues, generous spacing, and a strong personal-brand hero.

![Reference 09](ref_09.png)

### Reference 10 - NGO / Cause Storytelling

Use emotional imagery, distinctive masking/crops, strong mission-led hierarchy, program storytelling, restrained accents, and human-centered section flow.

![Reference 10](ref_10.png)

### Reference 11 - Nail Salon / Dark Luxury

Use premium beauty photography, elegant serif + script accents, black/rose palette, editorial service cards, strong booking CTA, and polished brand details.

![Reference 11](ref_11.png)

### Reference 12 - Beauty Studio / Soft Editorial

Use warm neutrals, large refined serif type, circular/arched image framing, airy layouts, soft luxury, and consistent visual geometry.

![Reference 12](ref_12.png)

### Reference 13 - Medical / Friendly Modern Illustration

Use clean white/blue space, soft rounded geometry, approachable illustrations, clear service hierarchy, and a polished appointment-oriented flow.

![Reference 13](ref_13.png)

### Reference 14 - Medical / Photographic Trust

Use real clinical photography, a strong booking surface, clear departments/services, soft blue depth, rounded containers, and confident trustworthy typography.

![Reference 14](ref_14.png)

### Reference 15 - Hotel / Dark Luxury Hospitality

Use immersive room imagery, elegant serif headlines, luxurious dark tones, booking UI integrated into the hero, editorial room offers, and long-form hospitality storytelling.

![Reference 15](ref_15.png)

## Implementation instruction to Claude

Study every reference above before changing the renderer. Extract the underlying design principles rather than copying the exact screens.

Then:
1. Audit the currently generated Locah sites at full desktop and mobile size.
2. Identify what still feels template-like or unfinished.
3. Improve the renderers and composition grammar first.
4. Upgrade menu/shop/service pages as aggressively as the homepage.
5. Use professional imagery through the already-supported image pipeline where available.
6. Preserve all existing backend/business behavior.
7. Run typecheck/lint/tests and render comparison screenshots.
8. Show before/after examples and explain what changed.

The end goal is **premium, custom-feeling, highly differentiated websites across every business type**.
