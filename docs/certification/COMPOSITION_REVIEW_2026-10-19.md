# Content-led design composition checkpoint

Branch: `web-builder-premium`. Local changes only. No push, deployment, hosted
database changes, paid AI calls or photo searches in this checkpoint.

## What was limiting the design

The inner range page unconditionally selected `chapters` whenever two
categories had photos. This overruled earlier creative decisions and made
different businesses converge on the same alternating picture/list pattern.
Inner-page openings also shared one title-then-wide-picture structure.
The model prompt explicitly favoured the first listed design family.

## Changes

- The existing director now has independent, renderer-backed choices for
  inner-page opening, category treatment and full-range layout. Its brief
  asks it to compare plausible directions using the owner's actual facts
  and record the tradeoff; list order no longer implies a preference.
- `interview/composition.py` checks real content before accepting a layout:
  unique item/category assets, description depth, catalogue size, food-menu
  semantics and existing brand concept. Unsupported choices fall back with
  a recorded reason. Duplicate photo references do not qualify as coverage.
- `theme.composition` carries the chosen axes, candidates and decision
  evidence. Rationale is audit metadata, never customer-facing copy.
- Inner openings can use masthead, offset portrait or oversized type.
  Categories can use alternating, panoramic gallery or compact index
  compositions independently. Existing themes keep their existing layouts.
- Missing-photo catalogues get a typeset, numbered, ruled index with the
  site's own display type, descriptions and prices. Its previously missing
  item actions now reuse the existing basket/pack/sold-out controls.
- No new animation runtime, provider, module gates, business facts,
  transaction mechanism, schema migration or cross-app imports.

## Verification actually completed

- Seven relevant Python test files: **150 passed** after correcting a new
  test's missing `with_draft` argument. Those files cover composition, site
  design, experience, copy and database-backed section contracts.
- New composition file: **18 passed**, included in that final 150-test run,
  including a stub-provider test of the full director-to-composer path.
- Web typecheck and Next lint passed. Ruff passed for all changed Python
  files and the new tests. Mypy passed for the four changed Python source
  files with `--follow-imports=silent`. `git diff --check` passed.
- Chromium, reduced motion: **27/27** page/width captures passed overflow,
  image-load, one-H1 and browser-exception checks: Cleaver Room, Selvam and
  Crumb & Co, home/range/about at 390, 768 and 1440 px. Selvam uses clearly
  illustrative lab placeholder imagery; it is composition evidence only.
- Ishant: **8/9** initial captures passed; the 390 px shop capture had one
  failed Unsplash image. A separate fresh-browser check of that exact page
  had zero broken images and zero failed requests. Preserve the original
  failed report as evidence of external image instability, not a clean pass.
- The actual compact renderer was exercised with an explicitly synthetic
  public catalogue response: Add persists in the browser basket, sold-out
  items expose no Add button, and the pack chooser opens/closes. This is
  renderer integration evidence, not a real order or payment journey.

Commands:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres@127.0.0.1:54329/locah_test'
# From apps/api:
uv run pytest tests/test_content_composition.py tests/test_website_premium_site.py tests/test_site_composer.py tests/test_website_composition.py tests/test_website_design_system.py tests/test_website_experience.py tests/test_website_copy.py -c pyproject.toml --rootdir . -q
# From repository root with local site lab running:
node tools/site-lab/composition-review.mjs
```

## Inspectable local evidence

- Before: `.site-lab/compare/composition-before-cleaver.png`
- After: `.site-lab/compare/composition-after-lab-cleaver.png`
- Initial 27-page batch and interaction capture:
  `.site-lab/compare/composition-review/report.json` and adjacent PNGs.
- Second butcher and original external-image failure:
  `.site-lab/compare/composition-ishant/report.json`.
- Explicit image recheck:
  `.site-lab/compare/composition-ishant/ishant-shop-390-recheck.png`.
- Local preview: `http://localhost:3005/site-lab/lab-cleaver/shop` and
  `http://localhost:3005/site-lab/lab-ishant/shop`.

## Limits and next work

This removes a structural source of sameness; it does not certify the
agency-level visual target. No live-model comparison, repeated vision
scoring, supplied-reference image comparison or fresh owner journey was
performed. The attached brief's referenced `ref_01..15.png` images were not
provided with its text. Do not describe them as visually reviewed.

Next evaluate the new director contract through bounded live generation
with normal/minimal/rich owner inputs, compare the same-industry outcomes
on all pages, and use the existing vision repair loop with repeated review.
Remaining weaknesses include photo provenance/subject accuracy in the saved
fixtures, external image reliability, generic catalogue headings, and
content-poor story sections. Score and repair those rather than expanding
the effects catalogue or announcing a premium certification.
