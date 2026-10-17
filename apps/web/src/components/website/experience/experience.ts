/**
 * How a site moves: read from the theme's `experience` record, which the
 * creative director writes (platform_core/interview/experience.py).
 *
 * Sites built before that record existed get a language from the design
 * family or reference profile they already have, so every published site
 * moves in a way that suits it without being rebuilt. Only finite values
 * are accepted; anything else falls back.
 */

export type MotionLang = 'silk' | 'snap' | 'float' | 'calm'

export type SiteExperience = {
  motion: MotionLang
  scroll: 'smooth' | 'native'
  intro: boolean
  grain: boolean
  progress: boolean
}

const LANGS: readonly MotionLang[] = ['silk', 'snap', 'float', 'calm']

const BY_FAMILY: Record<string, MotionLang> = {
  premium_dark: 'silk',
  editorial_warm: 'silk',
  airy_property: 'silk',
  portfolio_sketchbook: 'silk',
  monumental: 'snap',
  modern_commerce: 'snap',
  playful_editorial: 'float',
  local_friendly: 'float',
  calm_professional: 'calm',
  technical_b2b: 'calm',
}

const BY_PROFILE: Record<string, MotionLang> = {
  bold_food_commerce: 'snap',
  editorial_home_food: 'silk',
  cinematic_fitness: 'snap',
  airy_real_estate: 'silk',
  calm_care: 'calm',
  technical_b2b: 'calm',
  friendly_local: 'float',
}

/**
 * The site's design DNA (platform_core/interview/design_dna.py): the choices
 * that make two businesses of the same trade look like two brands — type,
 * how headlines carry their accent, texture, section edges, buttons, the
 * header, cards, picture shapes, the pointer. Each value maps to rules in
 * site-dna.css; anything unknown is dropped, so an old site keeps its look.
 */
const DNA_VALUES: Record<string, readonly string[]> = {
  display: [
    'syne', 'unbounded', 'dmserif', 'bodoni', 'youngserif', 'bigshoulders', 'spacegrotesk', 'italiana',
    'fraunces', 'playfair', 'cormorant', 'anton', 'archivo', 'bricolage', 'outfit', 'newsreader', 'plex', 'manrope',
  ],
  body: ['dm', 'manrope', 'outfit', 'plex', 'spacegrotesk', 'bricolage'],
  headline: ['plain', 'italic', 'outline', 'marker', 'gradient', 'caps', 'script'],
  texture: ['none', 'grain', 'paper', 'dots', 'grid', 'pattern'],
  pattern: ['kolam', 'waves', 'rays', 'checks', 'arcs'],
  divider: ['none', 'curve', 'slant', 'wave', 'ticket'],
  button: ['pill', 'sharp', 'outline', 'underline', 'soft'],
  navstyle: ['bar', 'floating', 'centered', 'overlay'],
  cardstyle: ['flat', 'bordered', 'elevated', 'glass', 'offset'],
  shape: ['rect', 'rounded', 'arch', 'blob', 'slant'],
  cursor: ['none', 'dot'],
  invert: ['calm', 'bands', 'bold'],
  // The art direction the traits above were drawn inside, and its brief.
  concept: [
    'noir_editorial', 'warm_craft', 'quiet_luxury', 'fresh_market', 'playful_pop', 'calm_care', 'technical_grid',
    'kinetic_sport',
  ],
  space: ['airy', 'regular', 'dense'],
  photo: ['macro', 'warm', 'full', 'clean'],
  // The motion director's budget: how much may move (motion.ts reads it too).
  budget: ['restrained', 'gentle', 'signature', 'expressive'],
}

export type SiteDna = Partial<Record<keyof typeof DNA_VALUES, string>>

export function siteDna(theme: Record<string, unknown>): SiteDna {
  const raw = theme.dna && typeof theme.dna === 'object' ? (theme.dna as Record<string, unknown>) : {}
  const out: SiteDna = {}
  for (const [key, allowed] of Object.entries(DNA_VALUES)) {
    const value = String(raw[key] ?? '')
    if (allowed.includes(value)) out[key as keyof typeof DNA_VALUES] = value
  }
  return out
}

export function siteExperience(theme: Record<string, unknown>): SiteExperience {
  const raw =
    theme.experience && typeof theme.experience === 'object'
      ? (theme.experience as Record<string, unknown>)
      : {}
  const declared = LANGS.includes(raw.motion as MotionLang) ? (raw.motion as MotionLang) : null
  const motion =
    declared ||
    BY_FAMILY[String(theme.design_family || '')] ||
    BY_PROFILE[String(theme.reference_profile || '')] ||
    (theme.motion_intensity === 'lively' ? 'snap' : 'silk')
  return {
    motion,
    scroll: raw.scroll === 'native' || motion === 'calm' ? 'native' : 'smooth',
    intro: raw.intro === true && motion !== 'calm',
    grain: raw.grain === true,
    progress: raw.progress === false ? false : motion !== 'calm',
  }
}
