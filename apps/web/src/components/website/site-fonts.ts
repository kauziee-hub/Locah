import localFont from 'next/font/local'
import type { SiteLang } from '@/lib/site-words'

/**
 * Typefaces for tenant websites — and only tenant websites.
 *
 * Every published site used to draw from the same two faces LOCAH's own pages
 * use, so a gym, a hospital and a home kitchen shared one typographic voice
 * and differed mostly by colour. A site's type system is part of its creative
 * direction (see platform_core.interview.creative_director):
 *
 *   editorial_food     Playfair Display over DM Sans — a food brand's serif
 *   bold_commerce      Archivo, heavy, over DM Sans — a shop that means business
 *   cinematic_fitness  Archivo, black and expanded, set in capitals
 *   premium_property   Outfit — confident geometric sans, airy
 *   technical_b2b      IBM Plex Sans — precise, engineered
 *   calm_care          Manrope — plain, calm, clear
 *   friendly_local     Fraunces over Manrope — warm and local
 *
 * Design system v3 adds four faces for families the first seven could not voice:
 *
 *   premium_serif         Cormorant Garamond over Manrope — quiet luxury
 *   playful_grotesk       Bricolage Grotesque — characterful, friendly
 *   portfolio_serif       Newsreader, with IBM Plex Mono captions — a work notebook
 *   technical_mono        IBM Plex Sans with Plex Mono specs
 *   monumental_condensed  Anton over Outfit — poster weight
 *   modern_grotesk        Archivo at normal width over DM Sans
 *   calm_serif            Fraunces (soft) over Manrope
 *
 * Older personalities keep their faces (Fraunces, Anton, Manrope). None of
 * these is LOCAH's own brand face.
 *
 * Self-hosted (2026-11-25). The files in src/fonts are cut by
 * tools/fonts/build_fonts.py from the OFL originals at a pinned commit, so a
 * build never fetches a font: `next/font/google` failed a production build
 * whenever one download did. Each Latin cut carries the rupee sign — Google
 * files ₹ under latin-ext, and a menu with prices downloaded a second ~100 KB
 * file for that one glyph. Nothing is preloaded: a browser downloads a face
 * only when the page draws text in it.
 *
 * Tamil and Devanagari (P1-10E6) are attached per language, never all three
 * scripts at once: a Tamil page gets Noto Sans Tamil behind every face, a
 * Hindi page Noto Sans Devanagari, an English page neither. The odd Tamil or
 * Hindi word on another page — the owner's name, the language switch — is
 * drawn by the phone's own Indic face (Android ships these same Noto faces).
 */

/* Variable serifs keep their optical-size axis: without it a 90px headline is
   drawn from the small-text master (Fraunces opsz 14, Newsreader 16, Bodoni 11)
   — heavy and soft where it should be crisp. Fraunces keeps SOFT on both styles
   and WONK on the italic, the warm hand-cut accent warm_craft sets; its upright
   is cut with WONK pinned to 0, as site-dna.css always sets it. Sans faces keep
   their width axis where a design condenses on it (Archivo, Bricolage,
   Instrument Sans). */

export const fraunces = localFont({
  src: [
    { path: '../../fonts/fraunces-normal.woff2', style: 'normal', weight: '100 900' },
    { path: '../../fonts/fraunces-italic.woff2', style: 'italic', weight: '100 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-warm',
})

export const anton = localFont({
  src: [
    { path: '../../fonts/anton-normal.woff2', style: 'normal', weight: '400' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-bold',
})

export const manrope = localFont({
  src: [
    { path: '../../fonts/manrope-normal.woff2', style: 'normal', weight: '200 800' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-clean',
})

export const playfair = localFont({
  src: [
    { path: '../../fonts/playfairdisplay-normal.woff2', style: 'normal', weight: '400 900' },
    { path: '../../fonts/playfairdisplay-italic.woff2', style: 'italic', weight: '400 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-playfair',
})

export const dmSans = localFont({
  src: [
    { path: '../../fonts/dmsans-normal.woff2', style: 'normal', weight: '100 1000' },
    { path: '../../fonts/dmsans-italic.woff2', style: 'italic', weight: '100 1000' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-dm',
})

export const archivo = localFont({
  src: [
    { path: '../../fonts/archivo-normal.woff2', style: 'normal', weight: '100 900' },
    { path: '../../fonts/archivo-italic.woff2', style: 'italic', weight: '100 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-archivo',
})

export const outfit = localFont({
  src: [
    { path: '../../fonts/outfit-normal.woff2', style: 'normal', weight: '100 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-outfit',
})

export const plex = localFont({
  src: [
    { path: '../../fonts/ibmplexsans-normal.woff2', style: 'normal', weight: '100 700' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-plex',
})

export const cormorant = localFont({
  src: [
    { path: '../../fonts/cormorantgaramond-normal.woff2', style: 'normal', weight: '300 700' },
    { path: '../../fonts/cormorantgaramond-italic.woff2', style: 'italic', weight: '300 700' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-cormorant',
})

export const bricolage = localFont({
  src: [
    { path: '../../fonts/bricolagegrotesque-normal.woff2', style: 'normal', weight: '200 800' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-bricolage',
})

export const newsreader = localFont({
  src: [
    { path: '../../fonts/newsreader-normal.woff2', style: 'normal', weight: '200 800' },
    { path: '../../fonts/newsreader-italic.woff2', style: 'italic', weight: '200 800' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-newsreader',
})

export const plexMono = localFont({
  src: [
    { path: '../../fonts/ibmplexmono-400.woff2', style: 'normal', weight: '400' },
    { path: '../../fonts/ibmplexmono-500.woff2', style: 'normal', weight: '500' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-mono',
})

export const syne = localFont({
  src: [
    { path: '../../fonts/syne-normal.woff2', style: 'normal', weight: '400 800' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-syne',
})

export const unbounded = localFont({
  src: [
    { path: '../../fonts/unbounded-normal.woff2', style: 'normal', weight: '200 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-unbounded',
})

export const dmSerif = localFont({
  src: [
    { path: '../../fonts/dmserifdisplay-normal.woff2', style: 'normal', weight: '400' },
    { path: '../../fonts/dmserifdisplay-italic.woff2', style: 'italic', weight: '400' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-dmserif',
})

export const bodoni = localFont({
  src: [
    { path: '../../fonts/bodonimoda-normal.woff2', style: 'normal', weight: '400 900' },
    { path: '../../fonts/bodonimoda-italic.woff2', style: 'italic', weight: '400 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-bodoni',
})

export const youngSerif = localFont({
  src: [
    { path: '../../fonts/youngserif-normal.woff2', style: 'normal', weight: '400' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-youngserif',
})

export const bigShoulders = localFont({
  src: [
    { path: '../../fonts/bigshouldersdisplay-normal.woff2', style: 'normal', weight: '100 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-bigshoulders',
})

export const spaceGrotesk = localFont({
  src: [
    { path: '../../fonts/spacegrotesk-normal.woff2', style: 'normal', weight: '300 700' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-spacegrotesk',
})

export const italiana = localFont({
  src: [
    { path: '../../fonts/italiana-normal.woff2', style: 'normal', weight: '400' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-italiana',
})

export const instrumentSerif = localFont({
  src: [
    { path: '../../fonts/instrumentserif-normal.woff2', style: 'normal', weight: '400' },
    { path: '../../fonts/instrumentserif-italic.woff2', style: 'italic', weight: '400' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-instrumentserif',
})

export const interTight = localFont({
  src: [
    { path: '../../fonts/intertight-normal.woff2', style: 'normal', weight: '100 900' },
    { path: '../../fonts/intertight-italic.woff2', style: 'italic', weight: '100 900' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-intertight',
})

export const instrumentSans = localFont({
  src: [
    { path: '../../fonts/instrumentsans-normal.woff2', style: 'normal', weight: '400 700' },
    { path: '../../fonts/instrumentsans-italic.woff2', style: 'italic', weight: '400 700' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-instrumentsans',
})

export const caveat = localFont({
  src: [
    { path: '../../fonts/caveat-normal.woff2', style: 'normal', weight: '400 700' },
  ],
  display: 'swap',
  preload: false,
  adjustFontFallback: 'Arial',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-site-caveat',
})

/* Behind every face, per language (see above). Their unicode-range is the
   script's own block, so even on its own page a face downloads only when
   that script is on screen. */
export const notoTamil = localFont({
  src: [{ path: '../../fonts/notosanstamil-normal.woff2', style: 'normal', weight: '100 900' }],
  display: 'swap',
  preload: false,
  adjustFontFallback: false,
  declarations: [{ prop: 'unicode-range', value: 'U+0B80-0BFF' }],
  variable: '--font-site-tamil',
})

export const notoDevanagari = localFont({
  src: [{ path: '../../fonts/notosansdevanagari-normal.woff2', style: 'normal', weight: '100 900' }],
  display: 'swap',
  preload: false,
  adjustFontFallback: false,
  declarations: [{ prop: 'unicode-range', value: 'U+0900-097F, U+1CD0-1CF9, U+A8E0-A8FF' }],
  variable: '--font-site-devanagari',
})

const latinFaces = [
  fraunces,
  anton,
  manrope,
  playfair,
  dmSans,
  archivo,
  outfit,
  plex,
  cormorant,
  bricolage,
  newsreader,
  plexMono,
  syne,
  unbounded,
  dmSerif,
  bodoni,
  youngSerif,
  bigShoulders,
  spaceGrotesk,
  italiana,
  instrumentSerif,
  interTight,
  instrumentSans,
  caveat,
]
  .map((font) => font.variable)
  .join(' ')

/** The classes that define every --font-site-* variable for a page in `lang`. */
export function siteFontVariables(lang: SiteLang = 'en'): string {
  if (lang === 'ta') return `${latinFaces} ${notoTamil.variable}`
  if (lang === 'hi') return `${latinFaces} ${notoDevanagari.variable}`
  return latinFaces
}
