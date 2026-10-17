# Design v2 — panel review (2026-10-17)

Three independent design-director reviews of the lab sites (screenshots in the
session scratchpad `photos-before/`) and the renderer code. Proposals only —
see `docs/HANDOFF-web-builder-premium.md` for which were implemented.


## 

### Diagnosis

The first screen fails on composition before it fails on fonts. The lab shots are taken with reduced motion forced on, which means they show each scene hero's still state. That still state is broken in two of the scenes. In lab-ishant/first-screen-desktop.jpg and first-screen-phone.jpg the plane hero sits at --p:1 (the shared `.fx-zoom,.fx-orbit,.fx-plane,.fx-kinetic{--p:1}` rule), so `.fx-plane__scrim` is at opacity 0.1. The headline, the sub and three buttons then sit on a bare wall of 16 tiles that repeats 6–8 stock photos (prawns appear twice), and the sub is unreadable. The current fixture has moved to `kinetic` (my capture hero-lens/ishant-kinetic-still.png). Its still state is the most pulled-apart frame: "Cut only" runs off the left edge, "after you order" runs off the right, and a squid eye is cropped into a red-stroked pill. The red underline the founder hates is not a DNA choice. Ishant's DNA is `headline:'plain'`, but site-families.css:294 (modern_commerce) adds `text-decoration:underline 0.12em` in primary, and `.fx-kinetic__line--b .ls-accent` forces faux italic on Space Grotesk, which has no italic. The same family-over-DNA leak breaks Grit (lab-grit/section-01-statement.jpg). The `outline` rule sets `color:transparent` with `-webkit-text-stroke: … currentColor`, so the stroke is transparent too and "written programme" disappears from the statement. In the hero, the monumental family colour hides this. Cleaver's italic "care" renders upright because DNA selectors only match `:is(h1,h2)`, and the cinematic_zoom's visible white copy is a `<p>`. Each hero also carries an eyebrow pill with a glowing dot, three buttons (Shop now / Call now / WhatsApp), three red tick-circle badges, a red utility bar, a header CTA and a WhatsApp float. On a phone it adds a sticky Call/WhatsApp bar (bakery/first-screen-phone.jpg shows five actions). That reads as a template, not a cover. Down the page (hero-lens/ishant-rest.png), a primary-red marquee with ✦ separators is inserted directly after the hero. Every other section alternates a dotted slab, and the `curve` divider draws a lump. A two-item counter strip ("10 items / 2 areas"), a yellow-on-red three-button closing band and a sparse footer complete the look of stacked cards rather than one editorial page.

### 1. Make every scene hero's still state readable: plane and kinetic still frames at --p:0, with the plane scrim tied to its copy

**Why.** The founder, link-preview crawlers, reduced-motion visitors and the lab all see the still state. Today the plane still state puts copy on a bare photo wall (scrim opacity 0.1). The kinetic still state pushes the headline off both edges. This is the single biggest visible failure and is pure CSS.

**Files.** packages/ui/src/site-experience.css

**Change.**

1) Directly after the shared block at lines 340-349 (`.fx-zoom,.fx-orbit,.fx-plane,.fx-kinetic{--p:1;…}`) add `.fx-plane, .fx-kinetic { --p: 0; }`. Specificity is (0,1,0), so `[data-fx='on'] :is(...) {--p:0}` and the runtime still drive it. The tilted wall and the assembled poster become the designed still frame. A static rotateX is a transform, not motion, so it is fine for prefers-reduced-motion.
2) `.fx-plane__scrim` (lines 674-686): replace `opacity: calc(1 - var(--p) * 0.9);` with `opacity: 1;` and add `[data-fx='on'] .fx-plane__scrim { opacity: clamp(0, calc(1 - (var(--p) - 0.35) * 2.5), 1); }`. That is exactly the `.fx-plane__copy` fade at line 698, so the scrim is never thinner than the copy needs. Make the desktop gradient solid under the copy column: `linear-gradient(96deg, var(--site-bg) 0%, var(--site-bg) 34%, color-mix(in srgb, var(--site-bg) 84%, transparent) 46%, color-mix(in srgb, var(--site-bg) 22%, transparent) 64%, transparent 80%)`.
3) Kinetic (lines 768-775): halve the drift to `.fx-kinetic__line--a{transform:translate3d(calc(var(--p) * -3%),0,0)}` and `.fx-kinetic__line--b{transform:translate3d(calc(var(--p) * 3%),0,0)}`, and add `overflow-wrap:anywhere` to `.fx-kinetic__title`.
4) Phone plane (inside the existing @media (max-width:900px) at line 720, or a new 760px query): stop overlapping copy and tiles. Use `.fx-plane__stage{display:flex;flex-direction:column}`, `.fx-plane__copy{order:-1;padding-bottom:1.25rem}`, `.fx-plane__view{position:relative;inset:auto;flex:1 1 auto;min-height:32svh;-webkit-mask-image:linear-gradient(to bottom,transparent 0,#000 20%);mask-image:linear-gradient(to bottom,transparent 0,#000 20%)}`, `.fx-plane__grid{top:0}`, `.fx-plane__scrim{display:none}`. Copy then sits on clean ground with the wall as a picture band beneath it, at 390px and under reduced motion.

**Risk.** Low. CSS only, and it only changes values the runtime already overrides when [data-fx='on']. Verify by re-running platform_testing.lab_shots for lab-ishant (plane and kinetic fixtures) at 1440 and 390. Also check with motion on (Chrome headless without --force-prefers-reduced-motion) that the scroll choreography still ends with the wall straightened.

### 2. One accent system: DNA owns the headline accent, families and scenes stop overriding it, and broken values are fixed

**Why.** The red underline and faux italic on 'after you order' come from a family rule and a scene rule, not from the DNA (Ishant is headline:'plain'). Outline makes text invisible (Grit statement). Italic never reaches the visible zoom copy (Cleaver). The DNA→CSS contract is the product, and it is currently being overridden.

**Files.** packages/ui/src/site-families.css, packages/ui/src/site-experience.css, packages/ui/src/site-dna.css, python/core/platform_core/interview/design_dna.py

**Change.**

1) site-families.css: delete lines 294-299 (`[data-family='modern_commerce'] .ls-hero__headline .ls-accent{color:primary;text-decoration:underline…}`). Scope the other family accent rules to sites without DNA by inserting `:not([data-headline])` after `[data-locah-site]`: editorial_warm (line 184), monumental (line 385) and local_friendly (line 509).
2) site-experience.css: delete `font-style:italic` and `color` from `.fx-kinetic__line--b .ls-accent` (779-782) and from `.fx-depth .ls-accent` (873-880). Keep only `display:block` for depth.
3) site-dna.css lines 133-185 and 1310: widen every `:is(h1, h2) .ls-accent` to `:is(h1, h2, .ls-hero__headline, .fx-cta__title) .ls-accent`, so the white `<p class=ls-hero__headline>` in cinematic_zoom gets the treatment.
4) Add the missing `plain` rule as a quiet two-tone headline: `[data-locah-site][data-headline='plain'] :is(h1,h2,.ls-hero__headline) .ls-accent { color: color-mix(in srgb, currentColor 56%, transparent); font-style: normal; text-decoration: none; background: none; }`.
5) Fix outline (141-146): `color: inherit; -webkit-text-fill-color: transparent; -webkit-text-stroke: max(1.5px, 0.03em) currentColor;`. currentColor is then the real ink, not transparent.
6) Add `[data-locah-site] :is(h1,h2,h3,.ls-hero__headline,.fx-statement__text) { font-synthesis: none; }` so no face is ever faux-italicised.
7) design_dna.py: after line 226 add `if headline == 'italic' and display not in {'dmserif','bodoni','fraunces','playfair','cormorant','newsreader'}: headline = 'plain'` (Italiana and Young Serif are loaded without italics), and change the calm branch at 227-228 the same way. Change fresh_market's headline tuple (line 129) from ('gradient','marker','plain') to ('plain',). Gradient text and a highlighter band on a dark food site are the cheapest-looking options; marker stays for warm_craft and playful_pop on light grounds.

**Risk.** Medium-low. It changes how monumental, editorial_warm and local_friendly accents look on sites that do have DNA (they will follow their DNA), so re-shoot one lab site per family. The outline fix changes Grit's hero 'WRITTEN DOWN' from solid lime to the hollow line its DNA asked for. Python tests in apps/api/tests/test_website_diversity.py may count headline values per concept; update expectations if fresh_market is pinned.

### 3. Hero CTA discipline: one primary button, one quiet text link, no tick-circle badges in scenes, and an editorial eyebrow

**Why.** A premium hero shows one action and maybe one secondary link. Today the first screen carries the primary, Call and WhatsApp buttons, three red tick circles, a pill eyebrow with a glowing dot, the header CTA and the WhatsApp float, plus the sticky bar on a phone. Clearing this alone gives the headline and the image room.

**Files.** apps/web/src/components/website/SectionRenderer.tsx, packages/ui/src/website.css, packages/ui/src/site-studio.css, packages/ui/src/site-experience.css

**Change.**

1) SectionRenderer.tsx ContactActions (103-140): add props `limit?: number` and `quiet?: boolean`. With `quiet`, render at most `limit` channels as `<a className="ls-hero__link">` instead of `ls-btn` (same href and t('Call now')/'WhatsApp' labels, no new copy). In the hero (line 436) pass `limit={1} quiet={Boolean(ctaLabel && ctaPath)}`. When there is no primary, the first contact channel still renders as a button.
2) website.css: `.ls-hero__link{display:inline-flex;align-items:center;min-height:48px;padding-inline:.25rem;font-weight:600;color:inherit;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:.35em;text-decoration-color:color-mix(in srgb,currentColor 45%,transparent)} .ls-hero__cta{align-items:center;gap:.75rem 1.5rem}`. Add `@media (max-width:760px){[data-locah-site]:has(.ls-mobile-bar) .ls-hero__link{display:none}}`, since the sticky bar already carries Call and WhatsApp.
3) site-experience.css: extend the orbit rule at 624-626 to all scenes: `[data-locah-site] :is(.fx-orbit,.fx-plane,.fx-kinetic,.fx-zoom,.fx-depth,.fx-aurora) .ls-hero__badges{display:none}`. The same facts are repeated in the marquee and the fulfilment strip.
4) site-studio.css 265-288, for the non-scene heroes: `.ls-hero__tick{display:none}`, `.ls-hero__badges{gap:.5rem 1.25rem;margin-top:2rem}`, `.ls-hero__badges li{font-size:.76rem;font-weight:500;letter-spacing:.1em;text-transform:uppercase;opacity:.72}`.
5) website.css 1416-1436, eyebrow as an editorial label rather than a SaaS pill: `.ls-hero__eyebrow{border:0;padding:0;border-radius:0;font-size:.74rem;letter-spacing:.2em;opacity:.8}` and `.ls-hero__eyebrow::before{width:1.75rem;height:1px;border-radius:0;box-shadow:none;background:currentColor}`.
6) site-studio.css 131-136, so the utility bar stops being a primary-red stripe above the hero: `.ls-utility{background:var(--site-bg);color:var(--site-muted);border-bottom:1px solid var(--site-border);font-weight:500;font-size:.78rem}`.

**Risk.** Low-medium. The phone number and WhatsApp stay reachable through the header CTA, the hero link on desktop, and the sticky bar and float. Check any test that asserts both hero contact buttons exist. The tap target stays at 48px. Uses only tenant tokens.

### 4. Hero variant policy: plane and orbit only with enough distinct pictures, kinetic only with a poster face, cinematic_zoom as the default for food

**Why.** The plane needs a wall of distinct, consistently treated photographs. With 6-8 mixed stock shots, fill(pictures,16) repeats them and the result looks like an image search. Kinetic needs a condensed poster face: Space Grotesk at 9rem is just big type. cinematic_zoom is the only scene whose still state already looks premium (lab-cleaver, lab-grit first screens).

**Files.** apps/web/src/components/website/experience/HeroScenes.tsx, python/core/platform_core/interview/experience.py, python/core/platform_core/interview/site_composer.py

**Change.**

1) HeroScenes.tsx sceneFor (40-47): count distinct pictures with `const distinct = new Set(pictures.map(p => p.url)).size`. Require `distinct >= 8` for plane and `>= 6` for orbit, else fall back to cinematic_zoom. In the plane branch (line 145) use `fill(pictures, 12)` and 3 columns (`[0,1,2].map(c => tiles.filter((_, i) => i % 3 === c))`, `.fx-plane__grid{grid-template-columns:repeat(3,1fr)}`), so no picture appears more than about 1.5 times.
2) experience.py hero_options (184-199): add `wall = c.pictures >= 8` and use it in place of `many` for plane and orbit. For menu_commerce/product_commerce with snap use `(['plane'] if wall else []) + ['cinematic_zoom', 'kinetic']`, which puts zoom ahead of kinetic for food. The existing test feeds expected_pictures=8, so test_a_ring_or_a_wall_only_where_there_are_pictures_for_it still passes.
3) site_composer.py after `dna = choose_dna(...)` (line 687): add a reconcile step. If the hero section's layout_variant is 'kinetic', `dna.display not in {'bigshoulders','anton','archivo'}`, and the page has a hero or cover picture, set it to 'cinematic_zoom' and record the reason in experience.reasons. Use 'depth' only for real_estate/portfolio: the white-bordered floating frames read as a scrapbook on a meat or bakery site.
4) Bakery (editorial_split with no photo, bakery/sheet.jpg): when there is no image, render the split hero as a centred typographic hero (`ls-hero--centered ls-hero--noimage`) instead of a gradient blob in a card.

**Risk.** Medium. It shifts which hero some generated sites get, and test_website_experience.py / test_website_premium_site.py pin some scene choices. Run `uv run pytest apps/api/tests/test_website_experience.py apps/api/tests/test_website_premium_site.py` against local TEST_DATABASE_URL. Copy is unchanged.

### 5. Cover composition for cinematic_zoom on desktop: copy anchored bottom-left on a bottom-weighted scrim, a bigger headline and more air before the sub

**Why.** Once open, the zoom is the strongest scene, but its copy floats in the top third (lab-cleaver/first-screen-desktop.jpg) with half the photograph empty below it. The sub sits 1.1rem under 0.95-leading display type, so descenders collide. Premium editorial heroes put the headline low on a full-bleed photograph and give the lede room.

**Files.** packages/ui/src/site-experience.css

**Change.**

Inside a new `@media (min-width: 901px)` block, keeping phones as they are:
- `.fx-zoom__copy{min-height:100vh;min-height:100svh;display:flex;flex-direction:column;justify-content:flex-end;padding-bottom:clamp(2.5rem,1.5rem + 5vh,5.5rem)}`. Both the ink and the white copy share this class, so the split along the frame edge stays aligned.
- `.fx-zoom__scrim{background:linear-gradient(to top,rgba(8,8,8,.8) 0%,rgba(8,8,8,.42) 38%,rgba(8,8,8,.08) 68%),linear-gradient(100deg,rgba(8,8,8,.5) 0%,rgba(8,8,8,0) 58%)}` (neutral black, not a brand colour).
- `[data-locah-site] .fx-zoom .ls-hero__headline{font-size:clamp(3rem,1rem + 6vw,7.5rem);line-height:.92;max-width:min(10ch,40vw)}`
- `[data-locah-site] .fx-zoom .ls-hero__sub,[data-locah-site] .fx-plane .ls-hero__sub{margin-top:clamp(1.5rem,1rem + 1.5vw,2.5rem);max-width:36ch;font-size:clamp(1.05rem,.98rem + .3vw,1.25rem);line-height:1.55}`
- `.fx-zoom .fx-cue{display:none}`, since the copy now occupies the bottom.
Also apply the sub spacing to `.fx-plane .ls-hero__sub` (line 708) on all widths, replacing `margin-top:1.1rem`.

**Risk.** Low-medium. The start state has the frame on the right 45% with the copy on the left, so bottom-anchored copy stays beside the frame. Check at 1280/1440/1920 that the headline never runs under the frame at --p:0 (max-width 40vw guards this). Phone is untouched.

### 6. Section rhythm: one continuous ground with hairline breaks instead of alternating dotted slabs and lumps; marquee moved and outlined; counters only when they earn it

**Why.** In ishant-rest.png the page is a stack of slabs: a red marquee glued to the hero, a dot texture on every other section, a 'curve' hump between sections, and a two-number counter band. Premium pages keep one ground, set rhythm with space and fine rules, and spend at most two full-bleed moments.

**Files.** python/core/platform_core/interview/design_dna.py, packages/ui/src/site-dna.css, packages/ui/src/site-experience.css, python/core/platform_core/interview/site_composer.py, python/core/platform_core/interview/experience.py

**Change.**

1) DNA tuples in design_dna.py: fresh_market texture ('dots','grid','none') becomes ('none','grain') and divider ('none','curve','wave') becomes ('none',). calm_care divider becomes ('none',). warm_craft divider ('ticket','curve') becomes ('none','ticket'). Slant stays only for kinetic_sport and noir_editorial.
2) site-dna.css: make divider='none' a real rendered value, a hairline rhythm on one ground: `[data-locah-site][data-divider='none'] .ls-section--alt{background-color:var(--site-bg);background-image:linear-gradient(var(--site-border),var(--site-border));background-size:min(1120px,calc(100% - 2 * clamp(1.25rem,.5rem + 3vw,3rem))) 1px;background-position:50% 0;background-repeat:no-repeat}`. Keep the existing texture='dots'/'grid' rules for the concepts that still draw them; they are more specific and come earlier in the file, so place this rule before line 194 or add `:not([data-texture='dots']):not([data-texture='grid'])`.
3) site_composer.py line 678: insert the marquee after the first content section, not glued to the hero: `sections.insert(min(2, len(sections)), …)`. In experience.py lines 315-316 use 'band' only for monumental/kinetic families and 'outline' otherwise.
4) site-experience.css 1944-1991: for `.fx-marquee--outline` set font-size `clamp(2.4rem,1rem + 5vw,6rem)`. For every marquee, replace the ✦ separator with `content:'/'; font-weight:300; opacity:.35; font-size:.8em;`.
5) site_composer.py line 661: switch highlights to 'counters' only when `len(section['content'].get('items') or []) >= 3`, else keep 'strip'. Two small numbers set at 5rem look thin, not proud.

**Risk.** Medium. The DNA tuple changes alter draws for existing seeds, so the distinctness tests (test_website_diversity.py) may need updated expectations. The value→CSS contract is kept because divider 'none' now has a rule. Copy is unchanged; marquee words still come from marquee_words().

### 7. Closing band: a single inverted button and a photo when available, no yellow-on-red three-button row

**Why.** lab-ishant section-08-cta_band.jpg puts an accent-yellow button and two outline buttons on a primary-red slab, the loudest and cheapest moment on the page. A premium close is one sentence set huge and one action.

**Files.** packages/ui/src/site-experience.css, apps/web/src/components/website/SectionRenderer.tsx

**Change.**

1) site-experience.css 2055-2064: replace `background:var(--site-accent);color:var(--site-accent-fg,#111)` with `background:var(--site-primary-fg);color:var(--site-primary)` for `.fx-cta:not(.fx-cta--pic) .ls-btn--primary`. Keep the primary fill on `.fx-cta--pic`.
2) In the cta_band giant branch of SectionRenderer.tsx (around line 669 where actions are built), pass the same `limit={1} quiet` to ContactActions as in the hero, so the band shows one button and one underlined link (`.fx-cta .ls-hero__link{color:inherit}`).
3) When the cta_band section has no image of its own, give CtaGiant the last page picture that is not the hero's (`pictures.at(-1)`). `fx-cta--pic` already adds its 0.58 black veil and parallax, and the parallax is gated by [data-fx='on'].

**Risk.** Low. Tenant tokens only. With a picture the band turns dark, and the existing `.fx-cta--pic` rules already handle button contrast.

### 8. Footer as a closing composition: the business name set to the full width at the bottom, for every DNA site

**Why.** Ishant's footer is a left-aligned list with a large empty field (section-01-marquee.jpg). Grit's oversized name sits above the links rather than closing the page. Ending on the name, cropped by the bottom edge, is the standard premium sign-off, and it costs nothing in copy.

**Files.** apps/web/src/components/website/WebsitePageView.tsx, packages/ui/src/site-families.css

**Change.**

1) WebsitePageView.tsx 558-562: render the statement when `family && (footerStyle === 'statement' || dna.concept)`, move the `<p className="ls-foot__statement fx-foot-name">` to after `.ls-foot__bar` (line 655), and give it `style={{ '--name-len': name.length } as React.CSSProperties}`. When the statement renders, hide the duplicate `.ls-foot__name` with CSS.
2) site-families.css 516-527: `.ls-foot__statement{white-space:nowrap;overflow:hidden;max-width:1120px;margin:clamp(2.5rem,2rem + 3vw,4.5rem) auto -0.08em;padding:0;line-height:.78;font-size:min(clamp(3rem,1rem + 9vw,11rem),calc((100vw - 2 * clamp(1.25rem,.5rem + 3vw,3rem)) / (var(--name-len,12) * .56)));color:color-mix(in srgb,var(--site-ink) 92%,transparent)}`. Add `.ls-foot:has(.ls-foot__statement):not(.ls-foot--with-bar){padding-bottom:0}` and `.ls-foot:has(.ls-foot__statement) .ls-foot__name{display:none}`.

**Risk.** Low. The name is still aria-hidden (the real name stays in the © line). The --name-len fit keeps 'GRIT BARBELL CLUB' and 'Ishant Proteins' on one line at 390px without horizontal scroll. Check Tamil names, where the 0.56 ratio may need .7, behind :lang(ta).


## 

### Diagnosis

The type system shows three problems. The faces carry no authority, accent treatments stack on top of each other, and every face is set with the same metrics whatever its proportions.

1. Ishant (lab-ishant/section-00-hero.jpg, first-screen-desktop.jpg) is set in Space Grotesk 600. It is identifiable by the hooked 'y' and 'g' in section-06-statement.jpg and in "Pick your kg." in section-08-cta_band.jpg. Space Grotesk and its neighbours in the draw (Syne, Unbounded) are the 2020–23 Web3 and startup-template faces, and they read generic straight away.

2. Its red accent is not one treatment but three. The DNA marker rule applies first. Then `[data-family='modern_commerce'] .ls-hero__headline .ls-accent` (site-families.css:294) has specificity 0,4,0, beats the DNA rule (0,3,1), and paints the words brand-red with a 0.12em `text-decoration` underline. Because each word is an inline-block `.fx-w`, the underline breaks word by word and its 0.12em offset drops through line-height 0.96 into the subheading.

3. The 'outline' accent is broken outright. `color: transparent` plus `-webkit-text-stroke: … currentColor` resolves to a transparent stroke, so lab-grit/section-01-statement.jpg reads "Every member gets a        , not random workouts."

4. lab-grit/section-02 shows "TRAIN WITH US" in a browser-faked oblique. kinetic_sport sets `.ls-title {font-style: italic}`, and Big Shoulders Display ships no italic (confirmed in next/font's font-data.json). Young Serif, Syne, Unbounded, Space Grotesk and Anton have no italic either, but the italic and accent rules still ask them for one.

5. The serif sites (Cleaver, Crumb & Co) are the best of the four but render below their potential. Fraunces, Newsreader and Bodoni Moda are loaded without their `opsz` axis, so 90px headlines are drawn from the small-text masters (font defaults: opsz 14, 16 and 11). They come out heavy and soft instead of crisp.

6. Metrics ignore the face. Every hero scene hard-codes `letter-spacing: -0.045em` and `line-height: ~0.95` (site-experience.css plane 702–704, zoom 467–469). Condensed caps on a phone stay at about 42px (lab-grit/first-screen-phone.jpg), where a poster face needs about 60px.

7. Several small details add up to the template feel:
   - The hero eyebrow is a bordered pill with a glowing dot ("● NOOKAMPALAYAM ROAD", "● ADYAR"), the signature of SaaS templates.
   - Button rows mix cases: Cleaver's first screen pairs "SHOP NOW →" (uppercase, 0.8rem, pill) with "Call now" (sentence case, square), all at weight 700.
   - Every hero subheading sits flush under its headline. `[data-locah-site] p {margin:0 0 1rem}` (0,1,1) beats `.ls-hero__sub {margin-top:1.1rem}` (0,1,0); see bakery/first-screen-desktop.jpg, where "in Adyar" touches the sub.
   - Cleaver's CTA band breaks "2 / pm".

8. Selection aside: the lab asked for noir_editorial on Ishant, but Space Grotesk is only ever drawn by fresh_market or technical_grid. So `choose_dna` (design_dna.py:220) dropped the requested concept as outside its shortlist, without saying so.

### 1. Replace the headline-accent vocabulary: drop marker, underline, gradient and outline; add a serif-italic accent and a 'tone' accent; let the DNA alone own .ls-accent

**Why.** This is the founder's exact complaint. Ishant's 'after you order' gets three treatments at once (DNA marker, the family's brand-red colour and the family underline), and 'outline' makes words invisible (lab-grit statement). On premium sites, emphasis inside a headline comes from contrast of voice, not decoration: one phrase in a true serif italic (the Framer/Lovable signature of a grotesk headline with one Instrument Serif Italic phrase), or the phrase knocked back in tone. A marker stripe, an underline or a gradient on a 90px headline reads as a template.

**Files.** python/core/platform_core/interview/design_dna.py, apps/web/src/components/website/experience/experience.ts, apps/web/src/components/website/site-fonts.ts, packages/ui/src/site-dna.css, packages/ui/src/site-families.css, packages/ui/src/site-studio.css, packages/ui/src/website.css, apps/api/tests/test_website_premium_site.py

**Change.**

**design_dna.py**
- Set the concept headline tuples to:
  - noir_editorial ("italic","caps")
  - warm_craft ("italic",)
  - quiet_luxury ("italic","plain")
  - fresh_market ("serif","tone","plain")
  - playful_pop ("italic","script")
  - calm_care ("plain","italic")
  - technical_grid ("plain","tone","caps")
  - kinetic_sport ("caps",)
- In choose_dna, right after `if headline == "caps" and serif: headline = "italic"`, add `if headline == "italic" and not serif: headline = "serif"`. Put it before the calm override so calm sites still end on plain or italic, which the test at line 91 expects.

**experience.ts**
- DNA_VALUES.headline becomes ['plain','italic','outline','marker','gradient','caps','script','serif','tone']. Keep the old values so stored themes still parse.

**site-fonts.ts**
- Add `Instrument_Serif({subsets:['latin'], weight:'400', style:['normal','italic'], display:'swap', preload:false, variable:'--font-site-instrumentserif'})` and add it to siteFontVariables.

**site-dna.css**
- Replace lines 140–178 (outline, marker, gradient) with these rules. Old marker and gradient values alias to serif, and outline aliases to tone, so already-published sites improve too and every value still maps to CSS:
  - `[data-locah-site]:is([data-headline='serif'],[data-headline='marker'],[data-headline='gradient']) :is(h1,h2,.ls-hero__headline,.fx-statement__text,.fx-cta__title) .ls-accent, [data-locah-site]:is([data-headline='serif'],[data-headline='marker'],[data-headline='gradient']) .fx-mark { font-family: var(--font-site-instrumentserif), var(--site-tamil), Georgia, serif; font-style: italic; font-weight: 400; font-size: 1.1em; letter-spacing: -0.015em; text-transform: none; color: inherit; background: none; text-decoration: none; -webkit-text-stroke: 0; }`
  - `[data-locah-site]:is([data-headline='tone'],[data-headline='outline']) :is(h1,h2,.ls-hero__headline,.fx-statement__text,.fx-cta__title) .ls-accent, [data-locah-site]:is([data-headline='tone'],[data-headline='outline']) .fx-mark { color: color-mix(in srgb, currentColor 52%, transparent); background: none; text-decoration: none; -webkit-text-stroke: 0; }`
- Italic rule (lines 133–139): keep `font-style: italic`, and set `color: color-mix(in srgb, var(--site-accent) 78%, currentColor)` so the colour stays a warm tint, not a shout.
- Caps rule (lines 180–183): delete `letter-spacing: -0.01em`; face tokens decide (see rank 4).
- Add `.fx-w:has(.ls-accent), .ls-accent .fx-w { padding-right: 0.08em }` so an italic overhang is not clipped by `.fx-w {overflow:hidden}`.

**Family and studio rules: stop overriding the DNA**
- Append `:not([data-headline])` to the `[data-locah-site]` compound in each of these:
  - site-families.css 160–164, 184–187, 294–299, 385–388, 509–512
  - site-studio.css 333–336, 463–467, and the .ls-hero--cinematic .ls-accent rule at 530
  - website.css 1445–1453
- Also delete `text-decoration`, `text-decoration-thickness` and `text-underline-offset` from site-families.css 294–299 outright.

**Result on Ishant:** "Cut only" in the display sans, white; "after you order" in Instrument Serif Italic at 1.1em, same white (serif) or 52% white (tone). No red, no rule.

**Tests:** update test_every_dna_value_is_one_the_renderer_draws if its allowed set is hard-coded.

**Risk.** Low–medium.
- The accent styling becomes the DNA's alone; families still style pre-DNA sites (no data-headline).
- Instrument Serif has no Tamil glyphs. Tamil inside an accent falls back to Noto Sans Tamil upright, which is acceptable.
- 'script' is kept only for playful_pop.

### 2. Re-cast the display library per concept: retire Syne, Unbounded, Anton and Italiana from the draw, keep Space Grotesk only in technical_grid, and add Instrument Serif, Inter Tight and Instrument Sans

**Why.** The face is most of the 'level of quality' gap. Syne, Unbounded and Space Grotesk are the most recognisable template faces of recent years. Anton is single-weight poster type that reads cheap below 6rem. Italiana is a hairline single weight that falls apart on photographs and at 390px. Premium editorial references draw from a small set of archetypes: a neutral tight grotesk (Inter Tight, Instrument Sans), a modern editorial serif (Instrument Serif, Bodoni Moda with optical sizes, Newsreader), and a real condensed grotesk (Archivo on its wdth axis, Big Shoulders). All of these are already on next/font (checked in apps/web/node_modules/next/.../font-data.json).

**Files.** python/core/platform_core/interview/design_dna.py, apps/web/src/components/website/site-fonts.ts, apps/web/src/components/website/experience/experience.ts, packages/ui/src/site-dna.css

**Change.**

**site-fonts.ts**
- Add:
  - `Inter_Tight({subsets:['latin'], style:['normal','italic'], display:'swap', preload:false, variable:'--font-site-intertight'})`
  - `Instrument_Sans({subsets:['latin'], axes:['wdth'], style:['normal','italic'], display:'swap', preload:false, variable:'--font-site-instrumentsans'})`
  - Instrument Serif, from rank 1.
- Push all three into siteFontVariables.

**experience.ts**
- DNA_VALUES.display: add 'instrumentserif', 'intertight', 'instrumentsans'.
- DNA_VALUES.body: add 'instrumentsans', 'intertight'.
- Keep syne, unbounded, anton and italiana so published sites keep rendering.

**design_dna.py**
- Add 'instrumentserif' to SERIF.
- Display and body tuples:

| Concept | Display | Body |
|---|---|---|
| noir_editorial | ("instrumentserif","bodoni","archivo") | ("instrumentsans","dm") |
| warm_craft | ("fraunces","dmserif","youngserif") | ("dm","manrope") |
| quiet_luxury | ("bodoni","instrumentserif","cormorant","newsreader") | ("manrope","instrumentsans") |
| fresh_market | ("intertight","instrumentsans","bricolage") | ("dm","instrumentsans","manrope") |
| playful_pop | ("bricolage","fraunces","youngserif") | ("dm","outfit") |
| calm_care | ("newsreader","fraunces","instrumentsans","manrope") | ("manrope","dm") |
| technical_grid | ("intertight","spacegrotesk","plex") | ("plex","dm") |
| kinetic_sport | ("bigshoulders","archivo") | ("instrumentsans","dm") |

**site-dna.css (new face rules)**
- `[data-display='instrumentserif'] { --site-display-font: var(--font-site-instrumentserif), var(--site-tamil), Georgia, serif; --site-heading-weight: 400; --site-display-tracking: -0.02em; --site-display-leading: 0.94; --site-display-scale: 1.14 }`
- `[data-display='intertight'] { --site-display-font: var(--font-site-intertight), var(--site-tamil), system-ui, sans-serif; --site-heading-weight: 600; --site-display-tracking: -0.045em; --site-display-leading: 0.92; --site-display-scale: 1 }`
- `[data-display='instrumentsans'] { --site-display-font: var(--font-site-instrumentsans), var(--site-tamil), system-ui, sans-serif; --site-heading-weight: 600; --site-display-stretch: 85%; --site-display-tracking: -0.035em; --site-display-leading: 0.92; --site-display-scale: 1.08 }`
- `[data-body='instrumentsans'] { --site-font: var(--font-site-instrumentsans), var(--site-tamil), system-ui, sans-serif }`
- `[data-body='intertight'] { --site-font: var(--font-site-intertight), var(--site-tamil), system-ui, sans-serif }`
- Condensed Archivo for the poster concepts: `[data-locah-site]:is([data-concept='noir_editorial'],[data-concept='kinetic_sport'])[data-display='archivo'] { --site-display-stretch: 72%; --site-heading-weight: 800; --site-display-case: uppercase; --site-display-tracking: -0.005em; --site-display-leading: 0.86; --site-display-scale: 1.28 }`. Archivo's wdth range is 62–125 and the axis is already loaded.

**site-dna.css (existing rule at line 103)**
- Extend `[data-locah-site][data-display] :is(h1,h2)` with `font-stretch: var(--site-display-stretch, 100%); line-height: var(--site-display-leading, 1.02);`.

**What the lab sites would get**
- Ishant: fresh_market gives Inter Tight 600 with an Instrument Serif Italic accent; noir_editorial gives Instrument Serif 400 at hero size.
- Grit: condensed Archivo 800 caps or Big Shoulders 800.

**Risk.** Low.
- Existing sites keep their stored DNA until regenerated: the old keys still map, only the draw changes.
- test_website_premium_site.py:72 needs at least 4 distinct displays across premium_dark butchers; noir has 3 and quiet_luxury has 4, so it still holds.
- Each new face is preload:false, so a page downloads only the face it uses.

### 3. Load optical-size axes and real italics, and forbid synthetic italic and bold

**Why.** Variable serifs are currently drawn from their small-text masters at 90px. next/font defaults the unrequested axis: Fraunces opsz 14, Newsreader 16, Bodoni Moda 11, Bricolage 14, DM Sans 14. That is why the Cleaver and Crumb & Co headlines look thick and soft rather than sharp. Faces without an italic are faked: 'TRAIN WITH US' in Big Shoulders (lab-grit/section-02), and any italic accent on Young Serif, Syne or Space Grotesk. Archivo is loaded without `style: italic`, so its italic is faked too. This fixes every serif site at once, with no layout change.

**Files.** apps/web/src/components/website/site-fonts.ts, packages/ui/src/site-dna.css, packages/ui/src/website.css

**Change.**

**site-fonts.ts**
- Fraunces: add `axes: ['opsz','SOFT','WONK']`.
- Newsreader: add `axes: ['opsz']`.
- Bodoni_Moda: add `axes: ['opsz']`.
- Bricolage_Grotesque: add `axes: ['opsz','wdth']`.
- DM_Sans: add `axes: ['opsz']` and `style: ['normal','italic']`.
- Archivo: keep `axes: ['wdth']` and add `style: ['normal','italic']`.

**website.css, `[data-locah-site]` (line 15)**
- Add `font-synthesis: none; font-optical-sizing: auto; font-kerning: normal; text-rendering: optimizeLegibility; -moz-osx-font-smoothing: grayscale;`.

**site-dna.css**
- `[data-locah-site][data-display='fraunces'] :is(h1,h2,h3,.ls-hero__headline,.fx-statement__text,.fx-cta__title) { font-variation-settings: 'SOFT' 50, 'WONK' 0; }`
- `[data-locah-site][data-concept='warm_craft'][data-display='fraunces'] :is(h1,h2) .ls-accent { font-variation-settings: 'SOFT' 100, 'WONK' 1; }`: the warm, hand-cut italic replaces Caveat.
- `[data-display='youngserif'] { --site-italic-font: var(--font-site-warm) }`, and in the italic accent rule use `font-family: var(--site-italic-font, inherit)`. Young Serif has no italic, so its accent borrows Fraunces italic.
- Kinetic titles (lines 1454–1458): replace `font-style: italic` with `font-style: normal; font-weight: 800;`, and for Archivo only add `[data-concept='kinetic_sport'][data-display='archivo'] .ls-title { font-style: italic }`, since that italic is now real.
- Heading weight per face, so nothing asks a single-weight face for 600: Instrument Serif, DM Serif, Young Serif and Italiana stay 400; Newsreader 450; Bodoni 500; Fraunces 560; Cormorant 500.

**Risk.** Low.
- About 30–60KB more for the Fraunces/Bodoni variable files on sites that use them, and only for those sites.
- With `font-synthesis: none`, any face asked for a weight it lacks renders at its real weight. That is the intent (website.css already complains about smeared fake bold).
- Tamil and Devanagari words inside italic render upright.

### 4. Make every hero and statement scene read the face's own metrics (scale, leading, tracking, measure) instead of one hard-coded set

**Why.** One `-0.045em / 0.95` set is right for a tight grotesk, too tight for condensed caps, wrong for an elegant serif, and too small on phones for poster faces (Grit hero on a phone is about 42px). Premium sites tune each face. Condensed caps run 1.3× larger with leading of about 0.86 and neutral tracking; a display serif runs about 1.14× with tracking of about -0.02em.

**Files.** packages/ui/src/site-experience.css, packages/ui/src/site-dna.css

**Change.**

**Defaults:** set on `[data-locah-site]` in site-dna.css: `--site-display-scale:1; --site-display-leading:0.95; --site-display-tracking:-0.035em; --site-display-measure:11ch`.

**Per-face tokens** (add to the existing face rules; the new faces are covered in rank 2):
- bigshoulders: scale 1.32, leading 0.86, tracking 0.005em, measure 9ch
- anton (legacy): scale 1.2, leading 0.9, tracking 0.01em
- bodoni: scale 1.08, leading 0.95, tracking -0.025em, measure 12ch
- newsreader: 1.05, 0.98, -0.025em, 12ch
- cormorant: 1.15, 0.95, -0.015em, 12ch
- fraunces: 1, 0.96, -0.03em, 12ch
- dmserif: 1, 0.98, -0.025em
- youngserif: 0.96, 1.0, -0.03em
- spacegrotesk: 1, 0.94, -0.035em
- bricolage: 1, 0.92, -0.04em
- syne and unbounded (legacy): 0.9, 0.98, -0.03em

**site-experience.css**
- Replace the fixed size, leading and tracking in each of these rules with `font-size: calc(clamp(2.9rem, 1.4rem + 5.6vw, 7.25rem) * var(--site-display-scale)); line-height: var(--site-display-leading); letter-spacing: var(--site-display-tracking); max-width: var(--site-display-measure);`:
  - .fx-zoom .ls-hero__headline (466–473; keep `min(…, 46vw)` around max-width)
  - .fx-orbit headline (560–563)
  - .fx-plane .ls-hero__headline (701–705)
  - .fx-depth (868–871)
  - .fx-aurora (1026–1029)
- Phone rule at ≤900px (508–513): `font-size: calc(clamp(2.75rem, 1.6rem + 6vw, 4.25rem) * var(--site-display-scale)); max-width: 13ch;`. At 390px this gives about 49px for Inter Tight, 56px for Instrument Serif and 64px for Big Shoulders. 'WRITTEN DOWN' then measures about 320px of the 350px available.
- .fx-cta__title (2035–2041): `font-size: calc(clamp(2.75rem, 1.2rem + 6.4vw, 8rem) * var(--site-display-scale)); line-height: var(--site-display-leading); letter-spacing: var(--site-display-tracking); max-width: 14ch;`.
- Kinetic (753–758): line-height `calc(var(--site-display-leading) - 0.04)`.

**site-dna.css .fx-statement__text (699–707)**
- `font-size: calc(clamp(2rem, 1rem + 3.6vw, 4.75rem) * var(--site-display-scale)); line-height: calc(var(--site-display-leading) + 0.08); letter-spacing: calc(var(--site-display-tracking) * 0.8); max-width: 20ch;`.
- Add `overflow-wrap: break-word` on all display headings as the 390px safety net.

**Risk.** Medium-low.
- Sizes shift for every scene, so the lab sheets need re-shooting at 1440 and 390, with reduced motion.
- The fx-zoom light/dark twin copy depends on identical metrics; both halves read the same tokens, so they stay aligned.

### 5. Typeset eyebrows and labels instead of the pill-with-glowing-dot and the Caveat handwriting

**Why.** The bordered pill with a pulsing dot ('● NOOKAMPALAYAM ROAD, CHENNAI', '● ADYAR', '● VELACHERY') marks every hero as an AI landing-page template. The warm_craft Caveat eyebrow reads as clip-art handwriting. Editorial references use quiet small-caps labels: tracked capitals with a hairline rule, or an italic line in the display serif.

**Files.** packages/ui/src/website.css, packages/ui/src/site-dna.css

**Change.**

**website.css .ls-hero__eyebrow (1416–1436)**
- Set: `padding:0; border:0; border-radius:0; gap:0.75rem; margin:0 0 clamp(1.25rem,0.9rem + 1vw,2rem); font-family:var(--site-font); font-size:0.75rem; font-weight:500; line-height:1.2; letter-spacing:0.16em; text-transform:uppercase;`.
- Its ::before: `width:1.75rem; height:1px; border-radius:0; background:currentColor; box-shadow:none; opacity:0.6;`.
- Apply the same 0.75rem / 500 / 0.16em to `.ls-eyebrow` (1596–1603), weight 600 → 500.

**site-dna.css**
- Replace the warm_craft Caveat block (1395–1404) with `[data-locah-site]:is([data-concept='warm_craft'],[data-concept='calm_care']) :is(.ls-eyebrow,.ls-hero__eyebrow) { font-family:var(--site-display-font); font-style:italic; font-weight:400; font-size:1.0625rem; letter-spacing:0; text-transform:none; transform:none; color:var(--site-accent); }` and its `::before { display:none }`. This follows the editorial_warm precedent at site-families.css:189.
- Extend quiet_luxury (1407–1411) to `.ls-hero__eyebrow`: 0.68rem, 0.32em, muted, `::before{display:none}`.
- Extend noir_editorial (1379–1392) to `.ls-hero__eyebrow`: 0.72rem, 600, 0.22em, with the 2.5rem rule.
- Replace fresh_market's tinted pill (1419–1428) with `padding:0; background:none; border-radius:0; color:var(--site-accent); font-weight:600; font-size:0.72rem; letter-spacing:0.14em; text-transform:uppercase`.
- Keep playful_pop's sticker.

**Nav wordmark (.ls-nav__name)**
- Set it in `var(--site-display-font)` at `font-weight: var(--site-heading-weight); font-size: 1.125rem; letter-spacing: -0.01em; text-transform: none`.
- For caps faces: `text-transform: uppercase; letter-spacing: 0.04em; font-size: 1.25rem`.

**Risk.** Low. CSS only. The playful_pop sticker and the technical_grid mono labels are unchanged.

### 6. One button type spec per concept, applied to every button in a row

**Why.** Cleaver's first screen pairs 'SHOP NOW →' (uppercase 0.8rem pill, from premium_dark primary-only) with 'Call now' (sentence case, square). Ishant and Crumb set three equal buttons in DM Sans 700 (site-studio.css:100). Mixed case and a heavy weight in one row is the clearest cheap tell; premium sites use one label style, medium weight and precise tracking.

**Files.** packages/ui/src/site-dna.css, packages/ui/src/site-families.css, packages/ui/src/site-studio.css

**Change.**

**Base rule (site-dna.css):** `[data-locah-site][data-concept] :is(.ls-btn, .ls-nav__cta, .ls-order, .fx-more__link) { font-family: var(--site-btn-font, var(--site-font)); font-weight: var(--site-btn-weight, 500); font-size: var(--site-btn-size, 0.9375rem); letter-spacing: var(--site-btn-tracking, -0.005em); text-transform: var(--site-btn-case, none); min-height: 52px; padding-inline: 1.5rem; }`.

**Tokens per concept:**
- noir_editorial and kinetic_sport: case uppercase, tracking 0.12em, size 0.75rem, weight 600.
- quiet_luxury: uppercase, 0.18em, 0.72rem, 500.
- technical_grid: font `var(--font-site-mono)`, uppercase, 0.06em, 0.78rem, 500.
- warm_craft, calm_care and fresh_market: none, -0.005em, 0.9375rem, 500.
- playful_pop: none, 0, 0.95rem, 600.

**Remove what fights it:**
- site-dna.css 334–339: delete the letter-spacing, text-transform and font-size lines from the sharp-button rule; keep radius 0.
- site-families.css 254–258 (premium_dark primary uppercase): scope to `:not([data-concept])`.
- site-studio.css 100–104 (`font-weight:700`) and 120–123 (cinematic uppercase): scope to `:not([data-concept])`.

**Arrow:** `.ls-hero__cta .ls-btn--primary::after { font-weight: 400; font-family: var(--site-font); }`.

**Risk.** Low. Pre-DNA sites keep their current buttons through the :not([data-concept]) scoping. Tap targets get bigger (48px → 52px).

### 7. Hero rhythm and reading text: fix the subheading margin bug, size the supporting copy for reading, and glue numbers to units

**Why.** Every hero sub sits flush against its headline. `[data-locah-site] p {margin:0 0 1rem}` at 0,1,1 outranks `.ls-hero__sub {margin-top:1.1rem}` at 0,1,0. Crumb & Co's 'in Adyar' touches its line, and Cleaver's and Grit's subs crowd the last headline line. Meta copy at about 13px muted grey (Cleaver pillars, Ishant steps) feels like a template. 'Order before 2 / pm.' breaks a unit off its number.

**Files.** packages/ui/src/website.css, packages/ui/src/site-dna.css, apps/web/src/components/website/experience/motion.ts

**Change.**

**Hero sub:** add `[data-locah-site] .ls-hero__sub { margin-top: clamp(1.25rem, 0.9rem + 1.2vw, 2rem); font-size: clamp(1.0625rem, 1rem + 0.35vw, 1.25rem); line-height: 1.5; letter-spacing: -0.005em; max-width: 42ch; }`. At 0,2,0 it beats the p reset; keep the plane-scene text-shadow.

**Body text:**
- website.css line 19: body `line-height: 1.6`.
- Floor every meta and description (.ls-category__meta, pillar and step descriptions, .fx-bento__copy p) at `font-size: max(0.9375rem, 1em)` with `line-height: 1.5; color: color-mix(in srgb, var(--site-ink) 72%, var(--site-bg))` for at least 4.5:1 contrast.

**Numerals:** big step and pillar numerals (`.fx-spot__num`, pillar 01/02/03) get `font-variant-numeric: lining-nums proportional-nums; font-weight: 300; letter-spacing: -0.04em`.

**Glue (render time):** in the data-split word splitter (motion.ts) or SiteWords, join with U+00A0:
- a number and its unit: `/(\d)\s+(am|pm|kg|g|km|min|mins|days?|hrs?)\b/gi` and `₹\s+`
- the last two words of any h1, h2 or .fx-cta__title, so no single-word widow

This is typography only; no words are added or changed, so the copy stays governed.

**Risk.** Low.
- The NBSP pass must run before word splitting and only on text nodes.
- The data-split spans must treat 'word NBSP word' as one unit, so check the 390px fit for long pairs like 'Nookampalayam Road'.


## 

### Diagnosis

Most of the cheap look comes from three things: colour that is never held back, photographs that are never graded, and a stack of SaaS-template details. Some of it is also broken rules, not just taste.

1. **Too many saturated colours.** On Ishant (lab-ishant/first-screen-desktop.jpg, section-08-cta_band.jpg) the coral #ff4b3e fills a lot at once:
   - the utility bar and the nav CTA
   - the hero CTA, with a red glow under it
   - three 30px tick discs and the active-link underline
   - the whole marquee band
   - three "Order on WhatsApp" pills, one per category card
   - the whole closing band

   Amber #f2b134 is layered on top (prices, numerals, the amber pill on the red band), and WhatsApp green #25d366 comes on as a float and as half of the phone bar. That is three saturated hues on every screen. The coral also fails AA under white button text (3.32:1).

2. **The red underline the founder hates is not the DNA.** Ishant's DNA says headline='plain', and 'plain' has no CSS rule. So the family layer (site-families.css:294, modern_commerce) paints the accent primary red with a 0.12em underline.

3. **The hero collage has almost no shade behind the words.** The screenshots force reduced motion, so `--p` rests at 1 and `.fx-plane__scrim` drops to 10% opacity. "Cut only after you order" ends up over four stock photos filled out to 16 tiles: prawns and chicken feet each appear twice, on 12px-rounded, drop-shadowed, ungraded tiles. Phone shot: words across five photos.

4. **No unifying photo grade.** photo='clean' also has no CSS rule, so mixed white balance shows raw: fluorescent wet market, white-plate studio mutton, blue-tray prawns (lab-ishant section-02-product_showcase.jpg; lab-cleaver section-02 shows a white plate on a near-black page). The 'macro' grade raises saturation to 1.12, which pushes raw meat toward neon.

5. **SaaS-template details on every site:**
   - a pill eyebrow with a glowing status dot (Ishant, Cleaver, Grit, bakery)
   - filled tick discs
   - 28px-rounded, elevated, bordered cards, each with a hard black gradient and its own pill button
   - a 40px bulging "curve" divider over a dot grid
   - mismatched button groups: Cleaver's hero sets a pill uppercase "SHOP NOW →" beside a square sentence-case "Call now" (lab-cleaver/first-screen-desktop.jpg)
   - lime next to WhatsApp green in Grit's phone bar

6. **The 'outline' accent is invisible.** `color: transparent` also makes `currentColor` transparent, so the stroke disappears. Grit's statement reads "Every member gets a ___, not random workouts." (lab-grit/section-01-statement.jpg).

Premium references do the opposite: one hue on roughly 5–10% of the pixels, tonal chrome, one grade across every photo, tight radii, no coloured glow, consistent controls. The bakery's rust/teal blob art is a test-fixture placeholder (website_fixtures.py), not product output.

### 1. Plane hero: a composed resting state, a real scrim and no repeated tiles

**Why.** This is the founder's exact complaint. With reduced motion (and in every lab screenshot) --p=1, so the scrim fades to 0.1 and the headline sits on four bright stock photos, each repeated up to four times. The fix gives words their own ground and the photos their own field, which is how an editorial split reads. With motion on, nothing visibly changes except that the scrim lasts until the words have gone.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-experience.css, C:/Users/KausikGH/Documents/Locah/python/core/platform_core/interview/experience.py

**Change.**

site-experience.css, .fx-plane block (lines 629-737):

(a) `.fx-plane__scrim { opacity: clamp(0, calc(1.6 - var(--p) * 1.6), 1); }`. It was calc(1 - var(--p) * 0.9). The copy fades out by p≈0.75, and the scrim now stays at 0.4 or more until then.

(b) New rule for when motion is off:
`[data-locah-site]:not([data-fx='on']) .fx-plane__scrim { opacity: 1; background: linear-gradient(96deg, var(--site-bg) 0%, var(--site-bg) 38%, color-mix(in srgb, var(--site-bg) 55%, transparent) 50%, transparent 64%); }`
`@media (min-width: 901px) { [data-locah-site]:not([data-fx='on']) .fx-plane__grid { left: 50%; width: 58%; top: -6%; transform: none; } }`

(c) Phone (max-width 900px), motion off:
`[data-locah-site]:not([data-fx='on']) .fx-plane__stage { display: flex; flex-direction: column; }`
`[data-locah-site]:not([data-fx='on']) .fx-plane__copy { order: -1; }`
`[data-locah-site]:not([data-fx='on']) .fx-plane__view { position: relative; inset: auto; height: clamp(220px, 44svh, 360px); }`
`[data-locah-site]:not([data-fx='on']) .fx-plane__grid { top: 0; left: -4%; width: 120%; transform: none; }`
`[data-locah-site]:not([data-fx='on']) .fx-plane__scrim { display: none; }`
The wall becomes a strip under the words at 390px.

(d) Tiles: `.fx-plane__tile { border-radius: min(var(--site-radius), 6px); box-shadow: none; }`. Grade the wall once on its container, not on 16 images: `.fx-plane__view { filter: saturate(.86) contrast(1.06) brightness(.9); }`.

(e) experience.py line 184: add `wall = c.pictures >= 8` and use `wall` instead of `many` wherever 'plane' is offered (lines 195, 197, 199, 203). With 4–7 pictures the site falls through to kinetic, depth or cinematic_zoom, so fill(pictures, 16) in HeroScenes.tsx:144 never shows the same photo three or four times.

**Risk.** Low. The motion-on scene only changes its scrim curve. The non-fx layout is new CSS that only applies under `:not([data-fx='on'])`. The experience.py threshold changes the scene that new generations draw for businesses with 4–7 photos; stored themes keep their scene until they are regenerated. Re-shoot lab-ishant at 1440 and 390 with reduced motion forced (lab_shots.py already does this).

### 2. Let the DNA own the headline accent: drop the family underline, give 'plain' a rule, fix the invisible outline, refine the marker

**Why.** The red underline comes from a family rule that overrides DNA headline='plain'. 'plain' has no CSS of its own, which breaks the contract in design_dna.py that every value maps to CSS. 'outline' currently erases words, which is a visible bug on Grit. A two-tone headline (ink, then the same ink at about 50%) is what Framer and Lovable-grade templates use instead of underlines.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-families.css, C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-dna.css

**Change.**

site-families.css lines 294-299: delete `[data-locah-site][data-family='modern_commerce'] .ls-hero__headline .ls-accent { color: var(--site-primary); text-decoration: underline; text-decoration-thickness: 0.12em; text-underline-offset: 0.12em; }`. If pre-DNA sites still need it, scope it to `[data-locah-site]:not([data-headline])[data-family='modern_commerce']`.

site-dna.css:

(a) Add after line 186:
`[data-locah-site][data-headline='plain'] :is(h1, h2) .ls-accent, [data-locah-site][data-headline='plain'] .fx-mark { color: color-mix(in srgb, currentColor 50%, transparent); font-style: normal; text-decoration: none; background: none; }`
The specificity (0,3,1) beats `.ls-hero:is(...) .ls-accent` and `.fx-depth .ls-accent`.

(b) Outline, lines 141-146: replace `color: transparent;` with `-webkit-text-fill-color: transparent;` and set `-webkit-text-stroke: max(1.5px, 0.03em) currentColor;`. currentColor then resolves to the accent colour from `.ls-accent` / `.fx-mark` instead of to transparent, so "written programme" becomes visible again.

(c) Marker, lines 151-156: replace the heavy 62%-opacity slab (55%→92% of line height) with a thinner wash:
`linear-gradient(transparent 66%, color-mix(in srgb, var(--site-accent) 42%, transparent) 66%, color-mix(in srgb, var(--site-accent) 42%, transparent) 90%, transparent 90%)`.
The draw-in transition is unchanged.

**Risk.** Low. These are CSS-only, and the outline fix is a pure bug fix. -webkit-text-fill-color is supported in all evergreen browsers. Check any other family hero `.ls-accent` overrides (site-studio.css 333, 463, 530) for the same pattern before relying on DNA alone.

### 3. Palette discipline: one saturated hue per screen, tonal chrome, a passing chilli red

**Why.** Ishant uses coral on six or more chrome surfaces, amber on top of it and WhatsApp green as well. Cleaver does the same with gold (gold utility bar and a gold closing slab). Premium sites keep the brand hue for the one action and a few marks, and draw everything else from ink and ground. #ff4b3e with white text is 3.32:1 and fails AA. #d93a2b is 4.57:1 and still 4.2:1 on the charcoal ground, so the existing primary-vs-surface test (>=3.0) passes.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-studio.css, C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-experience.css, C:/Users/KausikGH/Documents/Locah/python/core/platform_core/interview/design_system.py

**Change.**

site-studio.css:
- `.ls-utility` (line 131) becomes `{ background: color-mix(in srgb, var(--site-ink) 5%, var(--site-bg)); color: var(--site-muted); font-weight: 500; font-size: .76rem; letter-spacing: .02em; border-bottom: 1px solid var(--site-border); }`
- `.ls-price strong` (line 975): `color: var(--site-ink)`. It was the accent. Inside `.fx-bento__cell--pic` it should be `#fff`.
- `.ls-hero__tick` (line 280): `width: auto; height: auto; background: none; color: var(--site-primary); font-size: .85rem;`
- `.ls-hero__badges li`: `font-weight: 500; font-size: .86rem; color: color-mix(in srgb, currentColor 78%, transparent);`

site-experience.css:
- `.fx-marquee` (line 1944): `background: var(--site-bg); color: var(--site-ink); border-block: 1px solid var(--site-border);`
- `.fx-marquee:not(.fx-marquee--outline) .fx-marquee__list li::after` (line 1988): `color: var(--site-primary); opacity: 1;`. The red appears only as the ✦ marks.
- `.fx-cta:not(.fx-cta--pic)` (line 2004): `background: var(--site-bg-alt); color: var(--site-ink);`
- `[data-locah-site] .fx-cta .ls-btn--primary` (line 2055): `background: var(--site-primary); color: var(--site-primary-fg);`. This removes the amber-on-red pill.
- `[data-locah-site] .fx-cta--pic .ls-btn--primary { background: #fff; color: #111; }`

design_system.py line 359: `_pal("charcoal_chili", "dark", "#d93a2b", "#e3d5c1", "#0f0f10", "#18181b", "#f2eee8", "#9e978e", "red")`. The accent goes from a second hue (amber) to a bone tone, so numerals, eyebrows and step lines read tonal. None of these values is LOCAH's #e8622c, #f7f4ef or #1b1f3b.

**Risk.** Medium. The marquee and CTA band lose their colour slab on every site, which is deliberate, but review playful_pop and kinetic_sport, where a loud band is part of the concept. If so, exempt `[data-concept='playful_pop'] .fx-marquee`. The palette edit only reaches new or regenerated themes (stored hex stays). Run test_site_composer.py::test_the_palette_keeps_buttons_readable.

### 4. One photographic grade per concept, and a real rule for photo='clean'

**Why.** Pixabay and Unsplash photos from different cameras and different light are the biggest stock-photo signal. A consistent grade is what makes a set of stock frames read as one shoot. Today 'clean' has no CSS rule, and 'macro' raises saturation (1.12), which turns raw meat neon. On dark grounds, white-plate studio shots glare.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-dna.css

**Change.**

site-dna.css, "the photographs" (lines 1336-1351). Replace the rules with these; the base selector is S = `:is(section, .ls-hero) img:not(.fx-follow, .fx-plane__tile > img)`:
- `[data-locah-site][data-photo='clean'] S { filter: saturate(.94) contrast(1.04); }`
- `[data-locah-site][data-photo='macro'] S { filter: contrast(1.12) saturate(.86) brightness(.94); }`
- `[data-locah-site][data-photo='warm'] S { filter: sepia(.1) saturate(.95) contrast(1.04) brightness(1.02); }`
- `[data-locah-site][data-photo='full'] S { filter: saturate(.8) contrast(1.06); }`. This keeps the existing radius/shadow reset for 'full'.

Dark grounds dim the whites. Filters do not compose across rules, so these replace the above:
- `[data-locah-site][data-palette='dark'][data-photo='clean'] S { filter: saturate(.92) contrast(1.05) brightness(.92); }`
- `[data-locah-site][data-palette='dark'][data-photo='macro'] S { filter: contrast(1.14) saturate(.84) brightness(.9); }`

**Risk.** Low to medium. CSS filters on many images add paint cost on low-end Android. Images inside parallax frames are rasterised once with the filter and their parent's transform is composited, so this is acceptable. The plane wall is graded once on its container (change 1), not per tile. Food must still look appetising: check the Ishant and Cleaver showcases before and after, and do not go below saturate(.84).

### 5. Retire the Dribbble card: tighter radii, no coloured glow, no borders on photos, an eased scrim, a quiet order link

**Why.** 28px corners, a red glow under every button, a 1px border around photos, a hard black gradient and a filled pill CTA in every bento cell (three identical red pills in one view) are the textbook template stack. On a #111 ground, drop shadows do not read as depth; they just muddy.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-dna.css, C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-experience.css

**Change.**

site-dna.css:
- Line 340 `[data-button='soft'] .ls-btn` becomes `{ border-radius: 12px; box-shadow: none; }`, plus `[data-locah-site][data-button='soft'] .ls-btn--primary:hover { box-shadow: 0 10px 22px -16px rgb(0 0 0 / .55); }`
- Line 574 `[data-shape='rounded'] .fx-shape` becomes `{ border-radius: 16px; }` (was 28px).
- Add `[data-locah-site][data-palette='dark'][data-cardstyle='elevated'] :is(.ls-card, .fx-rail__card, .fx-pillar, .ls-fact, .fx-bento__cell) { box-shadow: inset 0 1px 0 rgb(255 255 255 / .06); }`
- Add a quiet order link in tiles, mirroring the existing `.fx-menu__item a.ls-order` rule at line 1618: `[data-locah-site] .fx-bento__cell a.ls-order { min-height: 0; padding: 0; border: 0; border-radius: 0; background: none; box-shadow: none; color: #fff; font-size: .85rem; font-weight: 600; text-decoration: underline; text-underline-offset: 4px; text-decoration-thickness: 1px; }`. The cart's `button.ls-order` stays a button.

site-experience.css:
- `.fx-bento__cell` (line 1561): `border-radius: calc(var(--site-radius) + 2px);`, plus `.fx-bento__cell--pic { border: 0; }`
- `.fx-bento__cell--pic::before` (line 1585) becomes `background: radial-gradient(140% 100% at 50% 30%, transparent 50%, rgb(0 0 0 / .28)), linear-gradient(to top, rgb(0 0 0 / .74) 0%, rgb(0 0 0 / .5) 20%, rgb(0 0 0 / .2) 42%, transparent 64%);`. This is an eased scrim plus a vignette that sits white-plate shots into the dark page.

**Risk.** Low. These are CSS-only. Playful_pop's 'offset' cards keep their character because their rules are separate. Check the bento at 390px (rules at site-dna.css:1950): the order link must stay a 44px tap target, so add `padding-block: .6rem` on coarse pointers.

### 6. WhatsApp float and phone bar drawn in the tenant's palette, not WhatsApp green

**Why.** #25d366 sits next to coral, lime or gold as a third, foreign hue (on Grit's phone, lime beside green). On desktop Ishant shows three WhatsApp affordances in one screen: the nav CTA, the hero ghost button with a green dot, and the float. Premium D2C sites keep the WhatsApp glyph for recognition and drop the green.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/website.css

**Change.**

website.css:
- `.ls-wa-float` (line 1825): `width: 52px; height: 52px; background: var(--site-ink); color: var(--site-bg); border: 1px solid color-mix(in srgb, var(--site-bg) 14%, transparent); box-shadow: 0 12px 28px -12px rgb(0 0 0 / .5);`
- Hide it when the header already says WhatsApp: `@media (min-width: 761px) { [data-locah-site]:has(.ls-nav__cta[href^='https://wa.me']) .ls-wa-float { display: none; } }`
- `.ls-mobile-bar` (line 1858 block): `background: color-mix(in srgb, var(--site-bg) 88%, transparent); backdrop-filter: blur(16px) saturate(140%); box-shadow: none;`
- `[data-locah-site] nav.ls-mobile-bar a[href^='https://wa.me']` (line 1887): `background: transparent; color: var(--site-ink); border: 1px solid color-mix(in srgb, var(--site-ink) 24%, transparent);`. Add a `::before` with the WhatsApp glyph as a `mask-image` filled with `currentColor` (1.1em square), so the main action stays the only filled button.
- `.ls-btn--whatsapp::before` (line 1561): `background: currentColor; opacity: .55;`. This drops the green dot.

**Risk.** Low technically; this is a product call. If the founder believes green converts better, keep #25d366 only on the phone bar's WhatsApp button and make everything else tonal. :has() is supported in all current browsers; older ones simply keep showing the float.

### 7. Strip the hero's status pill, and tone down dot-grid textures and bulging dividers

**Why.** The bordered pill eyebrow with a glowing dot appears on every lab site and reads as a SaaS 'Now in beta' badge. The fresh_market draw (dots texture, 40px curve divider, blob shapes) adds more template ornament. Editorial sites use a hairline rule with small spaced capitals, and plain section edges.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/website.css, C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-dna.css, C:/Users/KausikGH/Documents/Locah/python/core/platform_core/interview/design_dna.py

**Change.**

website.css:
- `.ls-hero__eyebrow` (line 1416): `border: 0; padding: 0; border-radius: 0; font-size: .72rem; font-weight: 500; letter-spacing: .2em;`
- `.ls-hero__eyebrow::before` (line 1429): `width: 1.75rem; height: 1px; border-radius: 0; background: currentColor; box-shadow: none; opacity: .55;`

site-dna.css, dots texture (line 194):
`background-image: radial-gradient(color-mix(in srgb, var(--site-ink) 7%, transparent) 1px, transparent 1.2px); background-size: 28px 28px; -webkit-mask-image: radial-gradient(90% 70% at 50% 0%, #000, transparent); mask-image: radial-gradient(90% 70% at 50% 0%, #000, transparent);`
The dots fade out instead of graph paper running edge to edge.

design_dna.py tuples:
- fresh_market (line 130): texture `("dots","grid","none")` becomes `("none","dots")`; divider `("none","curve","wave")` becomes `("none",)`; shape `("rounded","blob")` becomes `("rounded",)`.
- warm_craft (line 109): divider `("ticket","curve")` becomes `("none","ticket")`.
- calm_care (line 150): divider `("curve","none")` becomes `("none",)`.
- Blob, wave and curve stay with playful_pop, where they belong.

**Risk.** Low. Every value stays in DNA_VALUES, so test_every_dna_value_is_one_the_renderer_draws still passes. Re-run test_two_butchers_with_the_same_answers_do_not_share_a_look: fresh_market is rarely drawn on premium_dark, but confirm the 12 combinations still hold. The tuple edits only affect new DNA draws; the CSS edits apply at once.

### 8. Every button in a group shares shape, case and height

**Why.** Cleaver's hero sets a pill uppercase "SHOP NOW →" beside a square sentence-case "Call now", and its closing band has a square ghost button. Mixed radius and case inside one row is a template tell that premium sites never ship. It happens because the 'outline' DNA rounds only the primary, and premium_dark uppercases only the primary.

**Files.** C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-dna.css, C:/Users/KausikGH/Documents/Locah/packages/ui/src/site-families.css

**Change.**

site-dna.css line 344: change `border-radius: 999px` on `[data-button='outline'] .ls-btn:is(.ls-btn--primary, .ls-nav__cta, .ls-order)` to `border-radius: var(--site-btn-radius, 999px)`. Then add `[data-locah-site][data-button='outline'] :is(.ls-hero__cta, .fx-cta__actions, .ls-contact__actions, .fx-zoom__copy) .ls-btn { border-radius: var(--site-btn-radius, 999px); min-height: 48px; }` and `[data-locah-site][data-concept='quiet_luxury'] { --site-btn-radius: 0; }`, so luxury buttons are crisp rectangles everywhere.

site-families.css line 254: widen `[data-family='premium_dark'] .ls-btn--primary { uppercase; letter-spacing .08em; font-size .8rem }` to `[data-locah-site][data-family='premium_dark'] :is(.ls-hero__cta, .fx-cta__actions, .ls-contact__actions) .ls-btn`, so the secondary button matches the primary.

**Risk.** Very low. CSS only. Check that the hero's primary `::after` arrow (site-studio.css:288) still sits correctly in a 0-radius button.
