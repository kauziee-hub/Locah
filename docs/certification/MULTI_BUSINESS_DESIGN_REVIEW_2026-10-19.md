# Cross-business builder review — 2026-10-19

The user's request is to improve the builder's own design judgment, then
inspect different businesses rather than polish one butcher demo. This pass
continues the composition/refinement work recorded in the two earlier reviews.

## What changed

- Photographic catalogue cards now have separate photo and caption areas.
  Names, descriptions, prices and actions sit on the business's own surface,
  with consistent footers and no image scrim. Count-aware grids replace fixed
  rows and conflicting span rules that left a three-item catalogue as 2+1.
- The desktop floating action pill is removed, including its observer and CSS.
  The header stays available; tablets retain its action. The phone action bar
  remains. Header and section links now use the same capability contract:
  viewing projects or a menu does not require online ordering.
- Photo-free openings use the owner's actual categories or offerings, with
  distinct ruled-index, editorial and poster structures. An umbrella category
  such as “Projects” gives way to actual project names. These treatments use
  the business's existing fonts, palette and concept. Sparse content retains
  the existing colour-field fallback; no facts or testimonials are invented.
- The long-copy photo-led cover also adapts for seven-word titles such as the
  hotel example; its offer, photo and useful action now share the first screen.
- The service photo brief no longer asks every appointment business for a
  bright interior with plants. It names the actual services, both for the hero
  and supporting story. The calm style describes photographic treatment.
- Image selection has a `decor_only` finding. Generic decor cannot qualify as
  a hero even with a high overall score. Supporting mood details can still be
  suitable; objects actually sold by the business are judged as offerings.

The renderer remains structured content. Cart, checkout, booking and module
permissions still belong to platform code and its public capability contract.
No migration or tenant data write was made.

## Breadth of review

**35 business cases**, comprising two different sources:

| Source | Cases | Pages | Responsive checks | Result |
| --- | ---: | ---: | ---: | --- |
| Previous real generations, read from the local public API and rendered with current code | 12 | 38 | 114 | First batch passed. Later batch: 113 clean, one external restaurant photo failed; that exact page/size passed on recheck. Both reports retained. |
| Fresh current-composer builds from scripted interviews, without photos or paid AI | 23 | 49 | 147 | All passed in the final broad run. |

The 12 saved cases cover architecture, bakery, clinic, consulting, gym, hotel,
meat retail, NGO, restaurant delivery, restaurant reservations, homewares retail
and salon. The fresh set additionally exercises home food, dental, hospital,
property development, tuition, photography, industrial supply, logistics,
floristry, interiors, cafe, yoga, law, preschool and contrasting butcher brands.
These are business cases, not 35 distinct industry types.

Browser checks cover HTTP success, horizontal overflow, one H1, image loading,
browser exceptions, photo/caption overlap, clipped captions and absence of the
old floating pill. Screenshots cover home and available inner pages at 390,
900 and 1440 px. A technical pass is not a premium design score.

Manual inspection included the cross-business first-screen overviews and
individual desktop/phone views of catalogue cards, clinic, hotel, restaurant,
architecture, salon, law, industrial supply, property and preschool examples.
The review found the generic service-photo brief, similar photo-free openings,
the hotel title problem and the property header-action bug.

## Executed verification

- **247 Python tests passed** across ten relevant files, using the local test
  database and scripted provider transports. The added service-photo tests
  initially had an incorrect test-object constructor; it was corrected and the
  complete targeted batch rerun successfully. One existing Starlette/httpx
  deprecation warning remains.
- Web TypeScript check and Next lint passed. Ruff passed for changed Python
  sources/tests; mypy passed for the changed sources, including the three
  image-planning/selection files after their final edits.
- **27 focused responsive page captures passed** for Cleaver, Ishant and Crumb
  at 390, 768 and 1440 px after the catalogue footer change.
- Synthetic public-read responses verified Add persists in the browser basket,
  sold-out items have no Add, and pack choice opens/closes in both compact and
  photographic layouts. Photographic controls were exercised at 390, 900 and
  1440 px. No order was submitted.
- Five-, seven-, eight- and ten-item photographic grids were checked at the
  900 px breakpoint: all items present and captions fit.
- The optional WebGL ribbon was exercised with eight synthetic photographed
  items: all eight drawn, no caption overlap or horizontal overflow, captions
  retained their opaque brand surface, and no browser exception occurred.
- **13 final focused checks passed**: property/hotel/Cleaver first-screen
  actions and scrolling at three widths, plus motion-enabled Cleaver and
  preschool at phone/desktop widths. No overflow or page exception was found.
  The property header action remains visible without online ordering.
- Headers for **all 35 cases** were checked again at 768 px after the shared
  action change: no horizontal overflow or collision between brand and actions.
- No full repository verification or production build was run. No paid
  generation/vision calls, hosted database writes, push or deployment occurred.

## Evidence and local previews

- `.site-lab/compare/multi-business-2026-10-19/`: 12 saved cases, manifest,
  broad reports, `recheck.json`, full-page captures and `overview.jpg`.
- `.site-lab/compare/fresh-business-2026-10-19/`: 23 current-composer cases,
  manifest, report, screenshots and `overview.jpg`.
- `.site-lab/compare/catalogue-review-final-2026-10-19/`: final card controls,
  uneven counts, first-screen/scrolled-action and motion evidence, including
  `first-screen-and-motion.json` and its local `smoke.mjs`.
- Reusable harnesses: `tools/site-lab/business-matrix.mjs` (`--fresh`,
  `--render-only`, `--recheck-failures`) and `composition-review.mjs`.

Local examples: [butcher](http://localhost:3005/site-lab/lab-cleaver),
[dental](http://localhost:3005/site-lab/fresh-dental),
[preschool](http://localhost:3005/site-lab/fresh-play-school),
[property](http://localhost:3005/site-lab/fresh-real-estate),
[industrial supplier](http://localhost:3005/site-lab/fresh-industrial),
[restaurant](http://localhost:3005/site-lab/audit-restaurant-delivery).

## Remaining quality work

Older saved stock images still include weak or inaccurate subjects: the clinic
plant and hotel piano were not replaced by this code change. The new brief and
decor gate are tested with scripted judgments; live selection accuracy remains
unverified. Stock photo species/cut accuracy and external image reliability
still need review. Thin owner inputs also produce repetitive, sparse copy even
when the hierarchy is cleaner.

This pass does not establish owner preference, conversion improvement or
competitive superiority. Fresh live-model output, whole owner journeys and
same-brief competitor/owner comparisons were not run here. The implementation
and broad regression evidence improved; “extraordinary across businesses”
remains a product standard to demonstrate, not a certificate from these checks.
