# Builder product review and refinement

The user's standard: an owner willingly publishes the result, gets a useful
business website and has a reason to choose Locah. A technical pass or a
flattering AI score does not prove that.

## Starting assessment

Manual review of rendered screenshots, not a model-assigned score:

- Crumb's opening already had a clear offer, product, prices and action.
- Cleaver's homepage hid almost all its product photography below a tall
  block of type. Its About page repeated the business name at enormous size
  before saying anything substantive.
- The range introduction occupied nearly the whole first screen. Its
  generic heading described the interface rather than the business.
- Saved Aranya and gym examples were legible; legibility alone does not
  establish a distinct brand or a reason to switch builders.

## Three review cycles

1. **First screen and story.** Long-copy stage heroes now compose words
   beside the photo on desktop, with a bounded photo above the words on
   phones. About moves an existing opening sentence out of the later body
   and into its first screen. Missing-photo sticky stories render as prose
   instead of reserving an empty picture panel.
2. **The visitor's job.** Range openings are shorter than homepage covers.
   A governed `catalogue_title` enables an editorial opening; the fallback
   can name actual categories rather than say "Shop by category". The
   range button leads to its catalogue; About can lead on to the range.
3. **Use the result.** Browser review caught the anchor rewrite turning
   local `#shop` into a reload of `/shop`. The rewrite now respects the
   page on which the target exists. Desktop and phone clicks were verified.

A final motion-enabled review exposed the automatic name curtain: it hid
the business for about 1.95 seconds. Newly generated experiences now leave
that intro off. The before-curtain screenshot is retained, and the final
desktop/phone captures confirm the page has no intro overlay. Existing
stored themes are not migrated by this change.

## Refinement system

The existing screenshot critic now explicitly considers offer clarity,
useful actions, generic copy and whether an inner page earns its space.
Findings requiring a product change remain recorded; rotating a layout
cannot automatically resolve them.

Range repairs now use content-feasible candidates. A service catalogue is
no longer automatically changed into a food menu book. Tried choices are
remembered so repeated complaints cannot cycle indefinitely.

The local vision-loop tool evaluates the original and every proposal. It
requires a complete comparable score gain, no large dimension regression
and no increase in high-severity findings to retain a proposal. Regressions
and critic/render exceptions restore the best reviewed state. It stops
after at most three proposals, leaves no unreviewed final change, and
includes inner pages in phone screenshots. This strengthens the lab tool;
it does not install screenshots into every production generation job.
The existing certification repair system already has its own keep/revert
and repeated-judgment machinery.

## Verification

- **159 Python tests passed** across eight relevant files: new refinement
  regressions, earlier composition tests, copy governance, semantic design,
  renderer contracts and local database section checks. Earlier runs found
  the anchor issue; the final run passed after the correction. One existing
  Starlette/httpx deprecation warning remains.
- Web typecheck and Next lint passed. Ruff passed for all changed Python
  files/tests. Mypy passed for eight changed Python source files with
  `--follow-imports=silent`. Harness syntax and diff whitespace checks passed.
- Review cycle 2: **27/27** responsive captures passed. Cycle 3: **27/27**
  passed for Cleaver, Ishant and Crumb, home/range/about at 390, 768 and
  1440 px. Cycle 3 uses 390x844 for phones. Neither batch recorded overflow,
  broken images, missing/duplicate H1 or browser page exceptions.
- The long-copy home showed 195 px of photo at width 390, 384 px at width
  768 and 755 px at width 1440; the primary action was within the first
  viewport in all three. These are layout metrics, not conversion rates.
- Compact renderer: synthetic public-read response; Add persists in the
  browser basket, sold-out has no Add, pack choice opens/closes, and absent
  story photos leave no empty sticky picture panel. No order was submitted.
- The final range action was clicked at 390 and 1440: it stayed on
  `/shop#shop` and brought the actual catalogue into view. See
  `.site-lab/compare/product-review-r3/range-navigation.json`.
- Motion-enabled home smoke checks at 390 and 1440 passed: runtime enabled,
  no intro overlay, no page exceptions or horizontal overflow. Screenshots
  and `motion-smoke.json` are in the cycle 3 evidence directory.
- No paid generation/vision calls, hosted database writes, production
  changes, pushes or deployments were used for these cycles.

## Evidence

- Starting first screens: `.site-lab/compare/product-review-r1/`.
- Cycle 2 and desktop/phone first-screen views:
  `.site-lab/compare/product-review-r2/`.
- Cycle 3 report, full pages and navigation check:
  `.site-lab/compare/product-review-r3/`.
- Local previews on port 3005: `/site-lab/lab-cleaver`,
  `/site-lab/lab-cleaver/shop`, `/site-lab/lab-cleaver/about`,
  `/site-lab/lab-crumb`.

## Competitive assessment and limits

Published competitor examples were checked for what owners are offered:
[Lovable's restaurant example](https://lovable.dev/templates/websites/services/bellanova-template)
describes multiple pages, menu detail and editing;
[Rocket's restaurant example](https://www.rocket.new/templates/plate-fast-casual-restaurant-landing-page-template)
describes photography-led presentation and an accessible order path.
These are their descriptions, not independently completed competitor
journeys or same-brief generation results.

**Verdict: improved; premium quality and competitive preference remain
unproven.** Observable composition and refinement defects were removed.
This does not prove owner preference, improved conversion, or that fresh
live model responses consistently use the creative contract well.

Saved stock photos still need subject-accuracy review: an expensive-looking
meat image does not establish that its species/cut matches the catalogue.
The current photo judge already has this hard gate; its live accuracy was
not re-evaluated here. Thin content on incomplete real owner inputs and
external image reliability also remain.

The next useful evidence is a blinded same-business comparison using the
same facts/assets, covering minimal/normal/rich inputs and whole sites,
plus owner task completion and willingness-to-publish feedback. Locah must
earn preference through both design and usable operations. No switching
rate should be invented from screenshots.
