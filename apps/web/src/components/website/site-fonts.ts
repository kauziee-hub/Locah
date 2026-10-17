import {
  Anton,
  Archivo,
  Bricolage_Grotesque,
  Cormorant_Garamond,
  DM_Sans,
  Fraunces,
  IBM_Plex_Mono,
  IBM_Plex_Sans,
  Manrope,
  Newsreader,
  Noto_Sans_Devanagari,
  Noto_Sans_Tamil,
  Outfit,
  Playfair_Display,
  Syne,
  Unbounded,
  DM_Serif_Display,
  Bodoni_Moda,
  Young_Serif,
  Big_Shoulders_Display,
  Space_Grotesk,
  Italiana,
  Caveat,
  Instrument_Serif,
  Inter_Tight,
  Instrument_Sans,
} from 'next/font/google'

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
 * these is LOCAH's own brand face. Noto Sans Tamil and Noto Sans Devanagari sit
 * behind all of them as glyph fallbacks: Tamil and Hindi words — the owner's, or
 * the site's own in a visitor's language (P1-10E6) — render in a real face.
 *
 * Loaded from this module so the files are only requested by pages that
 * render a tenant site.
 */

/* Variable serifs load their optical-size axis: without it next/font draws a
   90px headline from the small-text master (Fraunces opsz 14, Newsreader 16,
   Bodoni 11) — heavy and soft where it should be crisp. Fraunces also brings
   SOFT and WONK, the warm hand-cut italic warm_craft sets its accent in. */
export const fraunces = Fraunces({
  subsets: ['latin'],
  display: 'swap',
  axes: ['opsz', 'SOFT', 'WONK'],
  style: ['normal', 'italic'],
  variable: '--font-site-warm',
})

export const anton = Anton({
  subsets: ['latin'],
  weight: '400',
  display: 'swap',
  variable: '--font-site-bold',
})

export const manrope = Manrope({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-site-clean',
})

export const playfair = Playfair_Display({
  subsets: ['latin'],
  display: 'swap',
  style: ['normal', 'italic'],
  variable: '--font-site-playfair',
})

export const dmSans = DM_Sans({
  subsets: ['latin'],
  display: 'swap',
  axes: ['opsz'],
  style: ['normal', 'italic'],
  variable: '--font-site-dm',
})

// The wdth axis gives the poster concepts a real condensed cut (62–125); the
// italic is Archivo's own, so a leaning kinetic title is never faked.
export const archivo = Archivo({
  subsets: ['latin'],
  display: 'swap',
  axes: ['wdth'],
  style: ['normal', 'italic'],
  variable: '--font-site-archivo',
})

export const outfit = Outfit({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-site-outfit',
})

export const plex = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-site-plex',
})

export const cormorant = Cormorant_Garamond({
  subsets: ['latin'],
  weight: ['500', '600', '700'],
  style: ['normal', 'italic'],
  display: 'swap',
  variable: '--font-site-cormorant',
})

export const bricolage = Bricolage_Grotesque({
  subsets: ['latin'],
  display: 'swap',
  axes: ['opsz', 'wdth'],
  variable: '--font-site-bricolage',
})

export const newsreader = Newsreader({
  subsets: ['latin'],
  axes: ['opsz'],
  style: ['normal', 'italic'],
  display: 'swap',
  variable: '--font-site-newsreader',
})

export const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  display: 'swap',
  variable: '--font-site-mono',
})

export const notoTamil = Noto_Sans_Tamil({
  subsets: ['tamil'],
  display: 'swap',
  variable: '--font-site-tamil',
})

export const notoDevanagari = Noto_Sans_Devanagari({
  subsets: ['devanagari'],
  display: 'swap',
  variable: '--font-site-devanagari',
})

/* Design DNA faces (platform_core/interview/design_dna.py): the display type
   a site may be given beyond its family's own. Not preloaded — a page only
   downloads the one its design uses. */
export const syne = Syne({ subsets: ['latin'], display: 'swap', preload: false, variable: '--font-site-syne' })
export const unbounded = Unbounded({ subsets: ['latin'], display: 'swap', preload: false, variable: '--font-site-unbounded' })
export const dmSerif = DM_Serif_Display({
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  display: 'swap',
  preload: false,
  variable: '--font-site-dmserif',
})
export const bodoni = Bodoni_Moda({
  subsets: ['latin'],
  axes: ['opsz'],
  style: ['normal', 'italic'],
  display: 'swap',
  preload: false,
  variable: '--font-site-bodoni',
})
export const youngSerif = Young_Serif({
  subsets: ['latin'],
  weight: '400',
  display: 'swap',
  preload: false,
  variable: '--font-site-youngserif',
})
export const bigShoulders = Big_Shoulders_Display({
  subsets: ['latin'],
  display: 'swap',
  preload: false,
  variable: '--font-site-bigshoulders',
})
export const spaceGrotesk = Space_Grotesk({
  subsets: ['latin'],
  display: 'swap',
  preload: false,
  variable: '--font-site-spacegrotesk',
})
export const italiana = Italiana({
  subsets: ['latin'],
  weight: '400',
  display: 'swap',
  preload: false,
  variable: '--font-site-italiana',
})
/* The editorial archetypes the draw now leans on: a display serif whose
   italic is also every grotesk headline's accent phrase (data-headline='serif'),
   a neutral tight grotesk, and a grotesk with a width axis to condense on. */
export const instrumentSerif = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  display: 'swap',
  preload: false,
  variable: '--font-site-instrumentserif',
})
export const interTight = Inter_Tight({
  subsets: ['latin'],
  style: ['normal', 'italic'],
  display: 'swap',
  preload: false,
  variable: '--font-site-intertight',
})
export const instrumentSans = Instrument_Sans({
  subsets: ['latin'],
  axes: ['wdth'],
  style: ['normal', 'italic'],
  display: 'swap',
  preload: false,
  variable: '--font-site-instrumentsans',
})
// A handwritten accent (data-headline='script'): one painted word in a headline.
export const caveat = Caveat({
  subsets: ['latin'],
  weight: ['600', '700'],
  display: 'swap',
  preload: false,
  variable: '--font-site-caveat',
})

export const siteFontVariables = [
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
  notoTamil,
  notoDevanagari,
]
  .map((font) => font.variable)
  .join(' ')
