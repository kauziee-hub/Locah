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
