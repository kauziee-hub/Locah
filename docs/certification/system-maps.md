# Map: 

**Short answer.** LOCAH has two critics. Both change only the composed payload's `layout_variant`, the order of sections, whether a section is kept, and `image_asset_id`. Neither writes copy, DNA, palette, motion budget or pages.

The deterministic critic (`site_critic.review`) runs once inside every `compose_site`, and its result is stored at `theme.quality.critic`. The vision critic (`site_vision_critic`) is not wired into production. Only the lab tool `python/testing/platform_testing/site_vision_loop.py` calls it, and that tool writes back to `.site-lab/*.json` files, never to the database.

**1. Critics**

*Deterministic critic: `python/core/platform_core/interview/site_critic.py`*
- `critique(payload) -> list[Finding]`, where `Finding(code, page, where, note, fixable)` and `where` is a section type id or "page".
- Codes:
  - `repeated_picture` (fixable for cta_band, media_text, statement or about)
  - `card_after_card` (fixable for pillars and feature_grid)
  - `wall_of_text`
  - `repeated_layout`
  - `thin_page` (not fixable)
  - `motion_overload`: more moving sections than `_ALLOWANCE` allows (restrained 2, gentle 4, signature 5, expressive 99, budget read from `theme_hints.dna.budget`)
  - `no_centrepiece` (not fixable: it means "ask the owner")
- `polish(payload, findings) -> list[str]` changes things in place:
  - pops `content.image_asset_id` and switches cta_band→centered, statement→giant, about→text_only;
  - pillars→numbered, feature_grid→list;
  - moves a section with a picture up to break a run of text sections, or sets pillars→cards;
  - drops a repeated layout (`_drop`);
  - `_quiet()` turns moving layouts still (marquee dropped; sticky→alternating; word_reveal or collage→sticky_split or text_only; rail or stack→spotlight; category rail→bento).
- `review()` loops for at most `ROUNDS=3` and returns `{rounds, fixed:[str], open:[Finding.as_dict()]}`.

*Vision critic: `python/core/platform_core/interview/site_vision_critic.py`*
- Input is `Shot(png, page, viewport "desktop"|"phone", sections=((index, type),...))` plus the payload.
- `critique(provider, shots, payload, model=None, timeout_seconds=90)` makes one call: `provider.generate_structured_with_images(json_context, [ImageInput(png,"image/png")], SCHEMA, {purpose:"website.critique", system_prompt:PROMPT, max_output_tokens:2500, temperature:0.2[, model]}, 90)`.
  - `json_context` is `{business: theme_hints.site_archetype, art_direction: dna.concept, manifest}`.
  - SCHEMA asks for `scores{hierarchy, imagery, rhythm, distinctness, mobile: 1-10}` and at most 12 `findings{code enum, page, section int -1..40, severity, note ≤240}`.
- `to_findings` keeps only codes in CODES and pages that exist. It builds `Finding("vision:"+code, page, f"{type}#{i}" or "page", note, fixable)`. Severity is dropped; it survives only in `Review.raw`.
- Fixable codes: generic_hero, excessive_cards, repetitive_layout, underdesigned_range, poor_image, thin_section. Recorded-only codes: weak_hierarchy, awkward_spacing, bland_mobile, ai_generated_feel, weak_contrast. Nothing consumes the recorded codes; they appear only in the lab report.json.
- Returns `Review{scores, findings, raw}`.
- `revise(payload, findings, tried)` changes:
  - **generic_hero** (home page hero only): the next of `_HEROES`. "aurora" is the only choice without a picture; plane, orbit and kinetic are skipped for a restrained budget.
  - **excessive_cards / repetitive_layout**: the next variant from `_ALTERNATIVE` (pillars, product_showcase, category_showcase, faq, media_text, statement, fulfilment_strip, cta_band).
  - **underdesigned_range**: product_showcase→chapters (2 or more categories with pictures), else menu_book.
  - **poor_image**: drops the picture only in statement, cta_band, media_text or pillars. It never fetches a replacement photo; hero and item photos are untouched.
  - **thin_section**: drops a marquee or highlights section with no pictures.
- `tried` is a set of `(page, index, layout)` so no layout is used twice. Bounds: 12 findings per call; the loop CLI defaults to `--rounds 2` and stops when nothing changes.
- Write-back happens only in `site_vision_loop.save()`, into lab JSON files. Rendering is headless Chrome against the site lab on :3005 (`?from=i&to=i`), with every home section at 1440px and the first 3 at 390px.
- `--dry-run` uses `CannedCritic`. The docstring says the loop is "never part of the test suite".

**2. Repair levers, one layer at a time**

- **Copy**
  - Fields: `WebsiteCopy` (website_copy.py:66).
  - `govern_copy(copy, bp)` drops any field with numbers or claim words the owner never used, and stock phrases. Steps and pillars must quote an owner sentence; named lines must name a real group or item.
  - `with_draft(bp, copy)` (website.py:309): the owner's draft headline, subheadline, about and offerings win.
  - The only production producer is `generate_creative_plan` (creative_director.py:721): one `generate_structured` call with purpose `website.personalization` and temperature 0.5.
  - To fix one site:
    - An owner path: `POST /v1/b/{id}/interview {action:"turn", text:"change the headline to …"}`, which goes through `website_edits.read/apply` → `talk_to_website` → `_apply_to_draft` and patches the hero.
    - Or `PATCH /v1/b/{id}/website/sections/{sid} {content}`. This bypasses `govern_copy`: the owner's words are treated as truth.
- **Photo**
  - `PhotoBrief` (image_retrieval.py:293) built by `brief_for_slot(slot, direction, trade, bp, concept)` (:421). `regenerate(brief, exclude)` (:1306) gives `Outcome.found: FoundImage`.
  - Owner path: `POST /v1/b/{id}/website/sections/{sid}/generate-image {list_key?, index?}` → `WebsiteImageService.generate_section_image`.
  - That service checks `image_policy` (hero, cta_band, about are drawable; showcase rows only when the business is not evidence-led), reuses `MediaAsset.provenance.brief`, excludes every stock photo the business already uses, persists the photo and sets `content.image_asset_id`.
- **Section composition**
  - Lever: `layout_variant` per section. `section_registry.py` holds content schemas only, with no variant allow-list. `validate_section_patch` accepts any string.
  - Variants the renderer draws: product_showcase {commerce_grid, menu_grid, compact_list, hover_list, category_boards, bento, rail, spotlight, stack, menu_book, chapters, plan_cards, project_cards, service_cards}; hero scenes {cinematic_zoom, orbit, plane, kinetic, depth, aurora} plus `page`; about {story_split, text_only, word_reveal, sticky_split, collage}; statement {giant, image, split}; pillars {numbered, strip, cards}; faq {split, accordion}; media_text {alternating, sticky}; cta_band {giant, centered, image_banner}; marquee {band, outline}; fulfilment_strip {icons, steps}; highlights {strip, counters}.
  - Owner path: `PATCH .../sections/{sid} {layout_variant}`.
- **Section order**
  - `page_architecture(archetype, direction.page_order)` (site_composer.py:895, using `ARCHITECTURE`).
  - Then `website_prefs.lead_section`, the home assembly in `site_pages.build`, and `arrange(sections, concept, lead)` (site_pages.py:404, using `_RHYTHM` per concept). `arrange` is skipped when the AI chose `page_order`.
  - Owner paths: `POST .../pages/{pid}/sections/reorder {section_ids}`, or chat "put delivery higher".
- **Visual styling (DNA)**
  - `choose_dna(dims, family, archetype, motion, seed, concept)` (design_dna.py:208) writes `theme.dna` = `{version:"dna-v2", display, body, headline, texture, pattern, divider, button, navstyle, cardstyle, shape, cursor, invert, concept, space, photo, budget}`.
  - The renderer drops unknown values (`DNA_VALUES` in experience.ts) and emits `data-*` attributes.
  - To force one trait after the build: edit `theme.dna.<trait>` and `PATCH /v1/b/{id}/website/theme {theme:<full theme>}`. `update_draft_chrome` replaces the whole theme.
  - At compose time: set `direction.model_choices["concept"]`, as premium_lab.py:304 does. It is honoured only if the concept is on the shortlist (≥45% of the best weight).
  - Changing the concept after the build leaves `_RHYTHM` order, statement variant, motion budget edits and photo art direction (`ART[concept]`) inconsistent.
- **Motion**
  - `motion_director.direct(sections, budget, range_variant)` rewrites hero, marquee, range and story layouts in place.
  - The renderer reads `dna.budget` and `theme.experience.motion` (silk/snap/float/calm).
  - Neither is reachable through an endpoint as logic: change them through the theme and section PATCH routes.
- **Responsive**
  - Only CSS media queries in `packages/ui/src/site-*.css`, plus `theme.mobile = mobile_strategy(archetype, hero)` = `{sticky_primary, hero_focus, picture_first}`.
  - The renderer reads only `sticky_primary` and `hero_focus`.
- **Page architecture**
  - `site_pages.build(...)` (:453) adds:
    - the range page when product_showcase has 6 or more items;
    - the about page when there is a story plus passages, steps (feature_grid) or numbers (highlights);
    - the visit page when there is contact plus 3 or more FAQs or an address.
  - Navigation is built there too. There is no create-page endpoint, so page architecture changes only by recomposing.

**3. Distinctness (`distinctness.py`)**
- `SIGNATURE_FIELDS` = family, variant, hero (home hero layout_variant), type_system, palette (palette_key), hue, cards (card_style), rhythm.
- `report(sites, max_family_share=0.3)` flags:
  - a family used by more than `max(2, n*0.3)` sites;
  - a (family, hue) pair used too often;
  - pairs with different evidence and 0 signature differences.
- Same evidence is never flagged.
- Present versus needed axes:

| Needed axis | In the signature? |
|---|---|
| Section sequence | No (only a home-skeleton check in test_website_diversity.py) |
| Hero structure | Partly (hero layout variant, not `hero_style`) |
| Typography | Partly (`type_system`, not dna.display/body/headline) |
| Palette | Yes, as key and hue (not hex; owner colours are invisible) |
| Layout primitives | Partly (card_style and rhythm, not DNA cardstyle/shape/divider/button/navstyle or section variants) |
| Image treatment | No (`image_treatment` and `dna.photo` exist but are not included) |
| Motion vocabulary | No (`experience.motion`, `dna.budget`, marquee) |
| DNA concept | No |

**4. Seeding**
- `seed = str(bp.business_id)` throughout. Variety comes from these draws:
  - `design_system.choose`: the business id only breaks ties between families and picks a palette when no evidence rule (`_PALETTE_BY_EVIDENCE`) or positioning lean applies.
  - `_variant` is fully decided by the business's dimensions.
  - `experience._pick(options, seed, role)` weights options 5/3/2/1… for hero, catalogue and story; the cta coin is used for float only.
  - `choose_dna` draws the concept from the shortlist and each trait from a ranked weighting.
  - `site_pages` uses `dna_seed = sha256(f"{seed}:pages")` with mod 2 or 3 for the statement, pillars, teaser, faq and hover_list variants.
  - The model's concept, experience and page_order choices (validated) add more.
- Where similarity comes from:
  - The same dimensions give the same family, variant, type_system, hero_style and cards, and often the same palette.
  - Often a single-concept shortlist: measured, a butcher on editorial_warm → only warm_craft (200 of 200 seeds); a clinic → only calm_care. That fixes the same `_RHYTHM`, space, photo, budget and photo ART.
  - Variety then lives only in fonts and edges.

**5. Quality fields**
- `theme.quality` = `{valid, issues:[{code, path}], repair_count, semantic:[{code, severity fail|flag, where, text, repaired}], critic:{rounds, fixed, open}}`.
  - `issues` comes from `quality_issues` (generic_commerce_heading, vague_item_name, dead_anchor, dead_page_link).
- Related keys: `theme.motion_direction{budget, notes}`, `theme.experience{…, reasons}`, `theme.creative_direction` (with reasons, repairs, model_choices, dimensions) and `theme.generation` (meta).
- All of these can be read through `GET /v1/b/{id}/website` → `data.draft.theme`. They are computed once, when the site is composed, and go stale after any PATCH.

## Facts
- site_critic.py:27 ROUNDS = 3; :45 _ALLOWANCE = {restrained:2, gentle:4, signature:5, expressive:99}; :48-57 Finding(code, page, where, note, fixable) with as_dict()
- site_critic.py:73-111 critique() codes: repeated_picture, card_after_card, wall_of_text, repeated_layout, thin_page (unfixable), motion_overload, no_centrepiece (unfixable)
- site_critic.py:133-184 polish() only pops image_asset_id, changes layout_variant, moves a pictured section, or drops sections via _drop; :187-199 review() returns {rounds, fixed, open}
- site_composer.py:820-828: critic = site_critic.review(payload); theme_hints.quality = {valid, issues, repair_count, semantic, critic}
- site_vision_critic.py:34-37 FIXABLE = generic_hero, excessive_cards, repetitive_layout, underdesigned_range, poor_image, thin_section; RECORDED = weak_hierarchy, awkward_spacing, bland_mobile, ai_generated_feel, weak_contrast
- site_vision_critic.py:57-73 SCHEMA: scores{hierarchy,imagery,rhythm,distinctness,mobile 1-10}, findings maxItems 12 {code,page,section -1..40,severity,note<=240}
- site_vision_critic.py:126-144 critique(): one provider.generate_structured_with_images call, purpose 'website.critique', max_output_tokens 2500, temperature 0.2, timeout 90; context {business: site_archetype, art_direction: dna.concept, manifest}
- site_vision_critic.py:105-123 to_findings drops severity; where = '<type>#<index>' or 'page'; fixable = (code in FIXABLE and where != 'page') or code == 'underdesigned_range'
- site_vision_critic.py:151-161 _ALTERNATIVE variant ladders and _HEROES = (cinematic_zoom, depth, plane, orbit, kinetic, aurora)
- site_vision_critic.py:171-236 revise(payload, findings, tried) changes only layout_variant, drops pictures (statement/cta_band/media_text/pillars), drops marquee/highlights; restrained budget blocks plane/orbit/kinetic heroes; returns notes
- site_vision_critic is imported only by python/testing/platform_testing/site_vision_loop.py:33 (no production caller)
- site_vision_loop.py:101-105 save() writes revisions back to .site-lab/<key>.json lab files; :108-123 shots_for: every home section desktop 1440x1000, inner pages first 3, phone 390x844 first 3 of home; :161-191 run() loops rounds and stops when revise returns nothing; :126-136 CannedCritic for --dry-run
- SectionRenderer.tsx:384-385 resolves the section picture from section.assets.image_asset_id, not content; site_vision_loop never rebuilds 'assets', so a lab 'picture dropped' revision still renders the picture
- website_copy.py:167-220 govern_copy drops ungrounded fields (_grounded: owner digits and claim words only, no _STOCK phrases); pillars/steps need quote in owner corpus; named lines need a real group/item name
- creative_director.py:721-799 generate_creative_plan: one generate_structured call, purpose 'website.personalization', temperature 0.5, returns (direction, govern_copy(words), provider, latency)
- website.py:309-333 with_draft: owner draft hero_headline/subheadline/about/offerings override model copy
- image_retrieval.py:293-364 PhotoBrief (key, subject, purpose, section, truth_class, aspect, trade, world, light, grade, palette, framing, avoid, role, business, locality, offerings, concept, atmosphere, style) with to_dict/from_dict; :1306-1313 regenerate(brief, exclude) = retrieve_for_slot(fresh=True) with SiteMemory(used=exclude)
- website_images.py:94-133 _obtain uses PhotoBrief.from_dict(prior_brief) + regenerate when replacing a stock photo; generate_section_image writes content.image_asset_id (or items[i]/categories[i])
- v1_website.py:175 POST /v1/b/{business_id}/website/sections/{section_id}/generate-image body {list_key?, index? 0..47}
- v1_website.py:145 PATCH /v1/b/{business_id}/website/sections/{section_id} body {content?, layout_variant?, is_visible?, sort_order?}; validation/website.py:277-298 validate_section_patch accepts any layout_variant string
- v1_website.py:195 PATCH /v1/b/{business_id}/website/theme {navigation?, theme?}; services/website.py:273-276 update_draft_chrome replaces draft.theme wholesale after assert_no_unsafe_content
- v1_website.py:355 POST /v1/b/{business_id}/website/pages/{page_id}/sections/reorder {section_ids: [UUID] 1..40}; :290 POST .../pages/{page_id}/sections AddSectionRequest {section_type_id, content?, layout_variant?, position?}
- v1_business_interview.py:34 POST /v1/b/{business_id}/interview InterviewCommand {revision, request_id, action:'turn', text}; website_edits.py:89-115 read() parses feel/prices/lead/add_items/story_reset/photo_first/headline
- business_interview.py:905-909 the feel edit's design_keys omit 'dna', 'experience', 'motion_direction' and 'mobile', so 'make it calmer' changes palette/family keys but not DNA or motion budget; :914-918 then re-patches hero/product_showcase/category_showcase layout_variant from a deterministic fresh compose
- business_interview.py:855 _apply_to_draft recomposes with direct(bp, business_type) without model choices (AI concept/experience choices are not reapplied)
- design_dna.py:208-248 choose_dna: shortlist = concepts with weight >= 0.45*best; model concept honoured only if in shortlist; traits drawn by _draw(_ranked(values), seed, salt); space/photo/budget fixed per concept; calm forces restrained
- design_dna.py:92-174 eight CONCEPTS: noir_editorial, warm_craft, quiet_luxury, fresh_market, playful_pop, calm_care, technical_grid, kinetic_sport
- site_composer.py:684-687 seed = str(bp.business_id); dna = choose_dna(..., seed=seed, concept=model_choices.concept); experience = fit_to_dna(...)
- site_composer.py:726 motion_director.direct(sections, dna.budget, range_variant=...); :737 dna_seed = int(sha256(f'{seed}:pages')[:8],16); :740 keep_order = bool(direction.page_order) and direction.source == 'ai'; :783 theme['dna'] = dna.theme()
- site_composer.py:882-902 ARCHITECTURE per archetype and page_architecture(): hero, catalogue, cta, contact fixed; the model may reorder or drop the middle roles
- site_pages.py:382-391 _RHYTHM home order per concept; :404-427 arrange(sections, concept, lead); :641-643 arrange applied only when not keep_order
- site_pages.py:495-497 range page needs product_showcase with >=6 items; about page needs a story plus (rows or feature_grid or highlights); visit page needs contact plus (>=3 faqs or address)
- site_pages.py:507-528, 586, 618, 663 dna_seed % 3 / % 2 choose statement split vs giant, pillars numbered vs strip, teaser spotlight vs bento, faq split vs accordion, hover_list on the range page
- experience.py:108-118 _pick weights [5,3,2,1,1,1] seeded by business id + role; :160-174 motion_for is deterministic from dims; :287 seed defaults to str(bp.business_id)
- design_system.py:565 family ranking ties broken by _stable(seed + key); :677-704 _palette: feel, then _PALETTE_BY_EVIDENCE, then positioning lean, else seeded by business id; :619-656 _variant has no seed
- distinctness.py:19 SIGNATURE_FIELDS = family, variant, hero, type_system, palette, hue, cards, rhythm; :51-72 report flags family share > max(2, n*0.3), (family, hue) overuse, and identical signatures only when evidence differs
- Measured (uv run python -c over choose_dna, 200 seeds): butcher dims on editorial_warm -> only warm_craft (200/200); on premium_dark -> noir_editorial 140 / quiet_luxury 60; clinic on calm_professional -> only calm_care; gym on monumental -> kinetic_sport 104 / noir_editorial 96
- experience.ts:57-84 DNA_VALUES renderer allow-list; WebsitePageView.tsx:352-367 emits data-display ... data-budget; :229-231 reads theme.mobile.sticky_primary and hero_focus only (picture_first is never read)
- creative_director.py:524-541 mobile_strategy -> {sticky_primary, hero_focus, picture_first}
- website.py:571-574 legacy build_preview path stores theme.quality = QualityReport {valid, issues, repair_count} and raises when invalid
- test_website_premium_site.py:185-230 and 398-456 cover polish and revise (fake vision provider); test_website_diversity.py:134-148 home-skeleton dominance plus distinctness report over fixtures
- premium_lab.py:304 forces a concept via direction.model_choices['concept'] before compose_site

## Gaps
- The vision critic is not wired into production: no service, endpoint or job calls site_vision_critic.critique/revise. Only the lab CLI does, writing to .site-lab JSON files, and there is no production screenshot renderer.
- There is no API to run or re-run a critic for a business. theme.quality.critic is computed once inside compose_site and goes stale after any section, theme or reorder PATCH.
- revise() cannot touch copy, DNA, palette, motion budget, page architecture or photos. poor_image only removes pictures (statement/cta_band/media_text/pillars) and never calls image_retrieval.regenerate; a poor hero or item photo is a no-op.
- RECORDED vision codes (weak_hierarchy, awkward_spacing, bland_mobile, ai_generated_feel, weak_contrast) have no consumer or persistent store; to_findings also drops severity.
- The lab loop's revise drops content.image_asset_id but leaves section.assets.image_asset_id, which is what the renderer reads, so a 'picture dropped' revision still renders in the lab.
- revise's `tried` set is keyed by section index, so after a thin_section removal later rounds' indices shift and the no-repeat memory points at the wrong sections.
- No function recomposes a single layer. compose_site is monolithic, and the concept drives _RHYTHM order, the statement variant, motion_director edits and photo ART, so swapping theme.dna.concept after the build leaves them inconsistent; the only safe forcing point is direction.model_choices before compose.
- layout_variant is a free string server-side (no allow-list in section_registry or validate_section_patch); a harness or critic can PATCH a variant the renderer does not draw.
- The theme PATCH replaces the whole theme object (no per-key merge), so forcing one DNA trait means read, modify and resend the full theme.
- The owner feel edit ('make it calmer/bolder') does not update theme.dna, theme.experience or theme.motion_direction, and it re-applies deterministic hero/showcase variants, which can overwrite AI- or harness-chosen variants.
- Responsive repair is CSS-only: theme.mobile.picture_first is never read by the renderer, there are no per-section mobile variants, and bland_mobile is unfixable.
- There is no create-page endpoint, so page architecture (range/about/visit pages) changes only through a full recompose.
- The distinctness signature lacks section sequence, DNA (concept, display/body/headline, shape, divider, button, navstyle, cardstyle), image treatment (theme.image_treatment, dna.photo), motion vocabulary (experience.motion, dna.budget, marquee), section layout variants and actual colour hex.
- report() never flags two same-evidence businesses with identical signatures, and it runs only over test fixtures, not across live businesses in a category.
- For many trades the concept shortlist has one entry (butcher on editorial_warm -> warm_craft only; clinic -> calm_care only), so two same-category businesses share home rhythm, space, photo grade, budget and photo art direction; variety is only in seeded fonts and edges.
- Real vision-critic runs need a paid provider (guard_external_ai). Tests must use CannedCritic or a fake provider, as test_website_premium_site.py does.

---

# Map: 

This is a read-only map. Nothing was built, run or served. The only things executed were greps, file reads, directory listings and one `uv run python -c` that checked which packages are installed.

## 1. Public renderer (the real owner path)

**Routes.** The home page is `apps/web/src/app/[slug]/page.tsx` and inner pages are `apps/web/src/app/[slug]/[pageSlug]/page.tsx`. Both use `revalidate = 60` and accept `?preview_token=&lang=`. Both call `fetchPublicWebsite(slug, pageSlug?, previewToken?)` in `apps/web/src/lib/public-website.ts`, which fetches:
- `GET {NEXT_PUBLIC_API_URL}/v1/public/websites/{slug}` for the home page
- `GET .../v1/public/websites/{slug}/pages/{page_slug}` for an inner page

Without a token the fetch is cached under tag `website:{slug}` for 60 s. With a token it is `no-store`. The page is rendered by `WebsitePageView`.

**Action pages.** These are `book`, `checkout`, `enquire`, `reviews` and `account` (plus the token pages `bill`, `pay`, `khata`, `track`, `waitlist`, `review/[token]`). They are static segments, so they take precedence over `[pageSlug]`, and they are wrapped in `SiteFrame`. They call `fetchPublicWebsite(slug)` without a token, so they need a **published** site. Checkout and book also 404 unless `/checkout/options` or `/booking/options` succeed, which means the module has to be ready.

**API.** `apps/api/src/platform_api/routers/v1_public_websites.py` hands off to `WebsitePublishService.load_public_page(session, slug=, page_slug=, preview_token=)` in `python/core/platform_core/services/website_publish.py:216`. That function is the single producer of `PublicWebsitePayload`. The response is `{data, meta}`. `data` holds:
- `business{id, slug, display_name, business_type, contact, place}`
- `capabilities` (order, book, join, enquire, reviews, catalogue, primary_path, primary_label, show_address and others)
- `whatsapp`
- `website{status, languages...}`
- `version`
- `page{title, slug, seo_*, sections[{id, section_type_id, layout_variant, content, assets{key: {url, alt_text, credit}}, is_visible, module_unavailable?}]}`
- `navigation[{label, path}]`
- `theme`, `is_preview`, `cache_control`

It also adds auto sections for modules that are ready, merges the live address, hours and phone into the contact section, and filters navigation with `_navigation`.

**Enumerating pages.** The payload does not list the site's pages. Two sources:
- `GET /v1/b/{id}/website` (Bearer token, WEBSITE_READ) returns `data.draft.pages[]` with `{slug, page_type, is_published, sort_order}`. `publish()` copies the draft pages one to one into the published version, so right after publishing the two lists match.
- The non-`#` paths in `navigation` from the public home payload.

**Preview.** `GET /v1/b/{id}/website/preview-token` returns `{token, expires_at, preview_path}`, and tokens live 600 s. A preview render differs from what a visitor sees:
- a "Preview — this is a draft" banner at the top
- no intro curtain
- no "My account" links
- placeholder sections where a module is not ready

**Local servers.** Start them with `tools/acceptance/stack/`:
- `db.sh`: Postgres on 54329
- `api.sh`: API on 8010, with `NO_EXTERNAL_AI`, replay providers and `LOCAH_JOBS_INERT=1`
- `web.sh`: web on 3100, with `NEXT_PUBLIC_API_URL=http://localhost:8010` and `REVALIDATE_SECRET`
- optionally `worker.sh`, which revalidates the site after publish

Mock auth is not needed for anonymous public pages: the middleware only refreshes a session from cookies. The API checks the HS256 tokens from `owner.py` against its local secret. After publishing, call `POST {WEB}/api/revalidate` with header `x-locah-revalidate-secret` and body `{slug}`, run the worker, or wait out the 60 s cache.

## 2. Site lab

The route is `apps/web/src/app/site-lab/[fixture]/page.tsx` and `.../[fixture]/[page]/page.tsx`. Your question said `(page)`; the folder is actually `[page]`. Both are force-dynamic.

`readLabPage(fixture, page?, {from, to})` in `apps/web/src/lib/site-lab.ts`:
- returns null unless `LOCAH_SITE_LAB_DIR` is set
- requires the fixture name to match `^[a-z0-9-]{2,40}$` and the page name `^[a-z0-9-]{1,40}$`
- reads `<fixture>.json` or `<fixture>~<page>.json` as a plain `PublicWebsitePayload`
- applies the inclusive `from`/`to` section slice
- rewrites `business.slug` to `site-lab/<fixture>`

`/site-lab-frame?src=&w=&h=` wraps a lab page in a 390 px iframe. That only exists because the Chrome CLI `--window-size` will not go below about 500 px. CDP emulation does not have that limit.

`tools/site-lab/serve.sh` serves the lab on port 3005 with `NEXT_DIST_DIR=.next-lab`. `web.sh` on 3100 does not set `LOCAH_SITE_LAB_DIR`.

`website_fixtures.lab_payload()` is **not** equivalent to the public payload. It builds from composer output with:
- `capabilities: {}`
- `business_type: None`
- no place, WhatsApp or auto sections
- SVG placeholder pictures

**Can a DB-built draft go through the lab?** Yes, mechanically. Write the `data` from `/v1/public/websites/{slug}[/pages/{p}]` (with a preview token or published) to `$LOCAH_SITE_LAB_DIR/<key>.json` and `<key>~<page>.json`; extra keys are ignored. But the rendering is not faithful:
- `LiveItemsSection`, `ProductShowcase` and `OfferingsListSection` fetch `/v1/public/websites/{businessSlug}/offerings` or `/plans` from the browser, and `ReviewsSection` and `PublicLicences` fetch reviews and licences on the server. All of them use `businessSlug = "site-lab/<key>"`, so they get a 404 and the catalogue, plans, reviews and licences come out empty.
- The basket storage key changes.
- A preview payload keeps `is_preview: true`.

So the lab is fine for design review and per-section slices. Certification shots should come from `/{slug}`.

## 3. Screenshot tooling

**`tools/acceptance/cdp.mjs`.** No dependencies; drives the installed `C:/Program Files/Google/Chrome/Application/chrome.exe` headless.
- `launch({width, height, mobile})` returns a page object.
- Methods: `viewport(w, h, isMobile)` (sets device metrics, DSF 2 on mobile, touch), `goto(url)` (waits for the load event, up to 40 s, then 600 ms), `eval(expr)` (awaits promises), `waitFor(selector | {text})`, `waitGone`, `type`, `click`, `text`, `cookie`, `offline`, `media(type)`, `shot(out, {full})`, `close`, plus the `consoleErrors` array.
- Any viewport size works, including 390 mobile.
- `shot({full: true})` grows the viewport height to `scrollHeight` (capped at 12000) and then clips. That puts 100vh/100svh elements at the wrong height, and the height is measured before the resize.
- There is no reduced-motion option: `media()` sets only the media type, not features.
- It does not use `captureBeyondViewport`.

**Existing shooters.**
- `owner_sites.mjs` already shoots the real `/{slug}` route and has two useful helpers, `heroPainted()` and `viewportPainted()` (waits for `fonts.ready` and the images in view).
- `sites.mjs` shoots the lab.
- Both fake a full page with `viewport(w, h*N)`.

**Python.**
- `platform_testing/site_vision_loop.shoot(url, 'desktop' | 'phone')` runs the Chrome CLI with `--headless=new --force-prefers-reduced-motion --window-size --virtual-time-budget=6000 --screenshot`. It only knows two sizes (1440×1000 and 390×844 through the frame), shoots only the viewport, and returns a JPEG of at most 960 px. It has no full-page mode.
- `lab_shots.py` builds contact sheets from per-section slices with Pillow.

**Playwright.** It is not installed in the project (`node_modules`), in global npm, or in `.venv`; the Python check found playwright False and PIL True. Browsers exist under `%LOCALAPPDATA%/ms-playwright`, and the npm package exists only in the npx cache that the MCP uses. `phase_b/pw.mjs` would fail to import it here. Use `cdp.mjs`.

**Reduced motion and load waits.**
- Send `Emulation.setEmulatedMedia({features: [{name: 'prefers-reduced-motion', value: 'reduce'}]})` before the first `goto`, or add `--force-prefers-reduced-motion` to the launch args. `MOTION_BOOT` reads matchMedia while the HTML is being parsed.
- Check that the root has no `data-fx`.
- Wait on `document.fonts.ready`.
- About 20 `<img loading="lazy">` tags in the renderer: set `loading = 'eager'` (or step-scroll), then wait for `img.complete && naturalWidth` and `img.decode()`, plus the hero CSS background as in `heroPainted`.

## 4. Motion

`SiteMotion.tsx` runs `MOTION_BOOT` inline. It sets `data-fx="on"` unless reduced motion is on or `data-motion="none"`, and drops it again after 4 s if the runtime never started. It also stores intro-seen in sessionStorage under `fx-intro:<first path segment>`. `motion.ts start(root)` adds:
- `IntersectionObserver` reveals (`.is-in`)
- `--p` for `data-scene` and `data-rail`
- pinned rails
- counters, pointer tilt and magnetic effects
- Lenis smooth scroll (desktop with a fine pointer only)

All the hiding CSS is gated on `[data-fx='on']` (`packages/ui/src/site-experience.css`). With motion on:
- scenes are 190–240vh tall with a sticky 100svh stage
- pinned rails get `height: calc(100vh + track)`
- content stays hidden until it is revealed
- the `.fx-intro` curtain covers the screen for about 2 s

With motion on, a full-page shot will show blank areas and scenes stopped at their start state. With reduced motion every scene falls back to a complete still state with `min-height: 100svh`.

## Recommended tool: `tools/acceptance/site_shots.mjs`, plus a small extension of `cdp.mjs`

**Changes to `cdp.mjs`:**
- a `launch({reducedMotion})` option that sets `setEmulatedMedia` features
- `shotFull(out)`: scroll to (0,0), wait two animation frames, read `h = scrollHeight`, then call `Page.captureScreenshot({captureBeyondViewport: true, clip: {0, 0, w, h, scale: 1}})` **without resizing the viewport**. If `h × DSF` is above about 16000, capture 4000 px tiles and stitch them with Pillow.
- a network-idle counter built from `Network.requestWillBeSent`, `loadingFinished` and `loadingFailed`

**Flow:**
1. Refuse any origin that is not localhost, as `release_survey.mjs` does.
2. Inputs are `business_id`, `slug` and the bearer token from `session.json`.
3. Enumerate pages from `/v1/b/{id}/website` `draft.pages` where `is_published`, combined with the nav paths.
4. Add action pages from `capabilities`: `book`, `order` (gives `/checkout`), `enquire`, and `/reviews` when there are reviews.
5. Fetch each page's public payload to confirm it returns 200 and to record a section manifest: type, variant, `module_unavailable`.
6. Revalidate.
7. Viewports:
   - 1920×1080, DSF 1
   - 1440×900, DSF 1
   - 768×1024, mobile, which sits in the 761–899 CSS band; add 1024×1366 if wanted
   - 390×844, mobile, DSF 2, tiled
8. For each (page, viewport):
   1. Run `goto`, then `waitFor('[data-locah-site]')`, and check that `data-fx` is absent.
   2. Wait for fonts, make lazy images eager, step-scroll, wait for the network to go idle and for images to decode, then scroll back to the top.
   3. Take the first-screen shot.
   4. Inject `.ls-mobile-bar, .ls-wa-float {visibility: hidden}` and record that in the manifest. Both are `position: fixed`, and the mobile bar only appears at 760 px and below.
   5. Run `shotFull`.
   6. Optionally take per-section clips from `main > [data-emphasis] > *`.
   7. Record console errors, responses with status 400 or above, broken images (`complete && !naturalWidth`), and horizontal overflow (`scrollWidth > innerWidth`).
9. Take one supplementary motion-on first screen at desktop and mobile. Preset `sessionStorage['fx-intro:<slug>']` or wait at least 2.2 s for the curtain. Never take full-page shots with motion on.
10. Write `<out>/<slug>/<page>/<vp>-{first,full}.png`, `manifest.json`, and an HTML contact sheet like `sites.mjs` makes. Shoot the published route for what visitors see, and `?preview_token=` only for draft checks: re-mint the token about every 8 minutes and expect the banner and placeholder sections.

## Facts
- Tenant home route: apps/web/src/app/[slug]/page.tsx (revalidate=60; searchParams preview_token, lang; renders WebsitePageView). Inner page: apps/web/src/app/[slug]/[pageSlug]/page.tsx.
- fetchPublicWebsite(slug, pageSlug?, previewToken?) in apps/web/src/lib/public-website.ts calls `${apiUrl}/v1/public/websites/${slug}` or `/pages/${pageSlug}`; with a token `{cache:'no-store'}`, else `{next:{revalidate:60, tags:[`website:${slug}`]}}`; returns json.data typed PublicWebsitePayload (same file).
- API routes: apps/api/src/platform_api/routers/v1_public_websites.py — GET /v1/public/websites/{slug}, GET /{slug}/pages/{page_slug}, GET /{slug}/plans; all return {data, meta}.
- Single payload producer: WebsitePublishService.load_public_page(session, *, slug, page_slug=None, preview_token=None) at python/core/platform_core/services/website_publish.py:216; returns business, capabilities, whatsapp, website, version, page, navigation, theme, is_preview, cache_control (lines ~421-445).
- PREVIEW_TTL_SECONDS = 600 (website_publish.py:26); owner mint endpoint GET /v1/b/{business_id}/website/preview-token (apps/api/src/platform_api/routers/v1_website.py:216) returns {token, expires_at, preview_path, draft_version_id}.
- Page list: GET /v1/b/{business_id}/website -> WebsiteService.get_aggregate -> data.draft.pages[] with slug/page_type/is_published/sort_order (python/core/platform_core/services/website.py:101; serialize_page in resolvers/website_resolver.py:137). publish() copies draft pages 1:1 into the published version (website_publish.py ~150-180).
- Navigation is filtered at read time by _navigation() (website_publish.py:465): drops links to pages/anchors filled only by not-ready modules; adds a catalogue link.
- Preview render differences in WebsitePageView.tsx: intro curtain only when `experience.intro && !data.is_preview` (line 378); preview banner aside (line 386); account links hidden when previewToken; client filters sections by is_visible !== false (line 247).
- Sections render as <main> > <div style=display:contents data-emphasis> > SectionRenderer (WebsitePageView.tsx:499-507); no data-section-id attribute exists.
- Action pages ([slug]/checkout, book, enquire, reviews, account) call fetchPublicWebsite(slug) with no preview token; checkout notFound() if fetchCheckoutOptions fails; book notFound() if fetchBookingOptions (/booking/options, no-store) fails (apps/web/src/lib/booking-api.ts:19).
- Basket lives in localStorage key `platform.cart.${slug}` (apps/web/src/lib/checkout-api.ts:172).
- platformUrl defaults: web localhost:3000, api 127.0.0.1:8000 unless NEXT_PUBLIC_API_URL etc. set (packages/config/src/platform-origins.ts:74-79).
- Acceptance stack: api.sh -> uvicorn on 8010 with local DB postgres@localhost:54329/locah_accept, LOCAH_TEST_NO_EXTERNAL_AI=1, IMAGE_PROVIDER=none, LOCAH_JOBS_INERT=1, WEBSITE_PREVIEW_SECRET local; web.sh -> next dev on 3100 with NEXT_PUBLIC_API_URL=http://localhost:8010 and REVALIDATE_SECRET; worker.sh posts to WEB_REVALIDATE_URL /api/revalidate.
- POST /api/revalidate (apps/web/src/app/api/revalidate/route.ts) needs header x-locah-revalidate-secret and body {slug}; revalidates tag website:{slug} and path /{slug}.
- apps/web/src/middleware.ts only refreshes a Supabase session via updateSession; anonymous public pages need no auth server. API verifies HS256 tokens locally (apps/api/src/platform_api/jwt_verify.py); owner.py mints such a token.
- Site lab: readLabPage(fixture, page?, slice?) in apps/web/src/lib/site-lab.ts reads `${fixture}.json` / `${fixture}~${page}.json` from LOCAH_SITE_LAB_DIR, applies inclusive from/to slice, rewrites business.slug to `site-lab/${fixture}`. Routes: apps/web/src/app/site-lab/[fixture]/page.tsx and [fixture]/[page]/page.tsx (folder is [page], not (page)).
- apps/web/src/app/site-lab-frame/page.tsx: iframe frame w 320-480 (default 390), h 480-1200 (default 844); src must match /^\/site-lab\/[a-z0-9-~/]+(\?[a-z0-9=&]*)?$/ — cannot frame the real /{slug} route.
- tools/site-lab/serve.sh: LOCAH_SITE_LAB_DIR (default .site-lab), NEXT_DIST_DIR=.next-lab, next dev -p 3005; generates fixtures via website_fixtures --images if index.json missing.
- website_fixtures.lab_payload(f, page_index, pictures) (python/testing/platform_testing/website_fixtures.py:134) sets capabilities {}, business_type None, website.status 'draft', is_preview False, placeholder SVG assets — not equal to load_public_page output. write_lab(root, f, pictures) at line 163.
- Live sections fetch by businessSlug: fetchPublicOfferings -> /v1/public/websites/${slug}/offerings, fetchPublicPlans -> /plans (apps/web/src/lib/checkout-api.ts:76,95); ReviewsSection uses fetchPublicReviews; PublicLicences fetches /licences server-side. In the lab, slug=site-lab/<key> so these return empty.
- tools/acceptance/cdp.mjs: launch({width=1440,height=900,mobile=false}); viewport(w,h,isMobile) uses Emulation.setDeviceMetricsOverride (DSF 2 if mobile) + touch emulation; media(type) sets only Emulation.setEmulatedMedia media type; shot(out,{full}) resizes viewport height to scrollHeight capped at 12000 (lines 188-205) — no captureBeyondViewport, no reduced-motion option.
- tools/acceptance/owner_sites.mjs shoots the real /{slug} route and contains heroPainted(timeoutMs) and viewportPainted(timeoutMs) wait helpers; it and sites.mjs fake full pages via viewport(w, h*N).
- platform_testing/site_vision_loop.shoot(url, viewport) (site_vision_loop.py:50): Chrome CLI --headless=new --force-prefers-reduced-motion --window-size --virtual-time-budget=6000 --screenshot; VIEWPORTS {'desktop':(1440,1000),'phone':(390,844)}; phone via /site-lab-frame at window width 520 then cropped; output JPEG thumbnail <=960px.
- lab_shots.main(out_dir, keys) shoots first screens + per-section ?from=i&to=i slices via shoot(); sheet() builds a Pillow contact sheet.
- Playwright is not installed for the project or Python (.venv: playwright False, PIL True); only npx cache (MCP) and %LOCALAPPDATA%/ms-playwright browsers exist; tools/acceptance/phase_b/pw.mjs would fail to import it locally. Chrome exists at C:/Program Files/Google/Chrome/Application/chrome.exe; Node v22.19.0.
- MOTION_BOOT (apps/web/src/components/website/experience/SiteMotion.tsx:52) checks matchMedia('(prefers-reduced-motion: reduce)') during HTML parse, sets data-fx='on', sets data-intro='seen' via sessionStorage key 'fx-intro:'+first path segment, removes data-fx after 4s if runtime not live.
- motion.ts start(root): IntersectionObserver reveals (.is-in, rootMargin -10% bottom), --p for [data-scene]/[data-rail-pinned], rails pinned only at min-width 900px, counters, pointer effects on fine pointers, Lenis on fine pointer + min-width 900px unless calm/native.
- site-experience.css: hiding gated on [data-fx='on'] (header comment lines 18-21); scene heights 230/220/240/190vh with sticky 100svh stage (lines ~356-392); stills min-height 100svh (line 365); pinned rail height calc(100vh + var(--track)*1px) (line 1632); .fx-intro shown only under [data-fx='on']:not([data-intro='seen']) with ~1.95s curtain (lines 236-249).
- Fixed overlays: .ls-wa-float position: fixed (packages/ui/src/website.css:1920); .ls-mobile-bar fixed bottom only at max-width 760px (website.css:1960-1970); .ls-nav is position: sticky top:0 (website.css:1081).
- Many images use loading="lazy" (experience/Bands.tsx, Sections.tsx, Story.tsx, ProductShowcase.tsx, OfferingCard.tsx, LiveItemsSection.tsx); hero scene images eager for first few.
- Dominant CSS breakpoints: min-width 900px (18), max-width 760px (7), min-width 960px (5), max-width 900px (5), max-width 640px (5) — 768 lands in the 761-899 tablet band, 1024 in desktop band.

## Gaps
- No existing tool does 'all pages × 4 viewports × full page' on the real /{slug} route; site_shots.mjs (or equivalent) must be written.
- cdp.mjs full-page mode distorts vh/svh-based heroes and scene stages (resizes viewport to scrollHeight, caps 12000px) and has no reduced-motion or captureBeyondViewport support; needs a small extension (setEmulatedMedia features or --force-prefers-reduced-motion arg; shotFull with captureBeyondViewport; tiling above ~16k device px; network-idle tracking). Whether captureBeyondViewport keeps vh stable on the installed Chrome should be verified once (compare .ls-hero height in image to innerHeight).
- The public payload has no page list; the harness must combine GET /v1/b/{id}/website draft.pages (owner token) with navigation paths, and derive action pages (/book, /checkout, /enquire, /reviews) from capabilities.
- Rendered sections carry no data-section-id/type attribute (only data-emphasis on a display:contents wrapper), and some renderers return null (e.g. ReviewsSection with no reviews), so per-section clips cannot be reliably mapped to payload sections without a small renderer change.
- The real route has no ?from=&to= slicing; slicing exists only in the site lab.
- Rendering a DB-built site through the lab is not faithful: live sections (offerings, plans, reviews, licences) fetch by slug 'site-lab/<key>' and come back empty; lab_payload() is a different, composer-based payload, not load_public_page output.
- Playwright is not installed for the project (Node) or the Python venv; pw.mjs-based tooling won't run locally without installing it.
- Action pages need published state and ready modules; a populated checkout needs a real add-to-basket click (localStorage platform.cart.{slug}); /account, track, bill, pay, khata, waitlist and review pages need customer sessions or tokens from real flows.
- Preview tokens expire after 600s; a long multi-viewport run in preview mode must re-mint tokens. Published mode needs cache revalidation (POST /api/revalidate with REVALIDATE_SECRET, or worker.sh) or a 60s wait after publish.
- Fixed overlays (.ls-mobile-bar at <=760px, .ls-wa-float) paint once at the viewport position in a captureBeyondViewport full-page image; the tool must hide or reposition them for the full-page pass and record that it did.