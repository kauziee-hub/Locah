import { ImageResponse } from 'next/og'
import type { PublicWebsitePayload } from './public-website'
import { coverImage, locality, tradeWords } from './structured-data'

/**
 * The card a tenant page shows when it is shared (WhatsApp, Instagram DMs,
 * Facebook, X, Google Discover): 1200×630, made per page by next/og.
 *
 * With a cover photograph: the photograph full-bleed, a shade at the bottom
 * deepened with the business's own primary colour, the name large in the
 * site's display face and the trade · town above it. Without one: a
 * typographic card in the theme's colours. Only the business's own brand —
 * never LOCAH's. Cheap and unbreakable: fonts are a few-kilobyte subset of the
 * site's face from Google Fonts (the default face when that fails), the photo
 * is fetched once with a timeout, and anything that fails falls back to type.
 */

export const OG_SIZE = { width: 1200, height: 630 } as const

/** DNA display faces (components/website/site-fonts.ts) as Google Fonts families,
 *  at the weight the site sets its headlines in. */
const DISPLAY: Record<string, [string, number]> = {
  instrumentserif: ['Instrument Serif', 400],
  intertight: ['Inter Tight', 600],
  instrumentsans: ['Instrument Sans', 600],
  syne: ['Syne', 700],
  unbounded: ['Unbounded', 600],
  dmserif: ['DM Serif Display', 400],
  bodoni: ['Bodoni Moda', 600],
  youngserif: ['Young Serif', 400],
  bigshoulders: ['Big Shoulders Display', 800],
  spacegrotesk: ['Space Grotesk', 600],
  italiana: ['Italiana', 400],
  fraunces: ['Fraunces', 600],
  playfair: ['Playfair Display', 600],
  cormorant: ['Cormorant Garamond', 600],
  anton: ['Anton', 400],
  archivo: ['Archivo', 800],
  bricolage: ['Bricolage Grotesque', 700],
  outfit: ['Outfit', 600],
  newsreader: ['Newsreader', 500],
  plex: ['IBM Plex Sans', 600],
  manrope: ['Manrope', 700],
}

/** A site from before the DNA: its type system's display face. */
const BY_TYPE_SYSTEM: Record<string, string> = {
  editorial_food: 'playfair',
  bold_commerce: 'archivo',
  cinematic_fitness: 'archivo',
  premium_property: 'outfit',
  technical_b2b: 'plex',
  technical_mono: 'plex',
  calm_care: 'manrope',
  friendly_local: 'fraunces',
  calm_serif: 'fraunces',
  premium_serif: 'cormorant',
  playful_grotesk: 'bricolage',
  portfolio_serif: 'newsreader',
  monumental_condensed: 'anton',
  modern_grotesk: 'archivo',
}

const BODY: Record<string, [string, number]> = {
  dm: ['DM Sans', 500],
  manrope: ['Manrope', 600],
  outfit: ['Outfit', 500],
  plex: ['IBM Plex Sans', 500],
  spacegrotesk: ['Space Grotesk', 500],
  bricolage: ['Bricolage Grotesque', 500],
  instrumentsans: ['Instrument Sans', 500],
  intertight: ['Inter Tight', 500],
}

const CONDENSED = new Set(['anton', 'bigshoulders'])

type Rgb = [number, number, number]

function rgbOf(value: unknown): Rgb | null {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(String(value || '').trim())
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : null
}

function css([r, g, b]: Rgb, alpha = 1): string {
  return alpha === 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function luminance([r, g, b]: Rgb): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
}

function mix(a: Rgb, b: Rgb, t: number): Rgb {
  return [0, 1, 2].map((i) => Math.round(a[i] * (1 - t) + b[i] * t)) as Rgb
}

/** A few kilobytes of the face: only the letters this card sets. */
async function googleFont(family: string, weight: number, text: string): Promise<ArrayBuffer | null> {
  try {
    const query = `family=${family.replace(/ /g, '+')}:wght@${weight}&text=${encodeURIComponent(text)}`
    const sheet = await fetch(`https://fonts.googleapis.com/css2?${query}`, {
      signal: AbortSignal.timeout(2500),
      next: { revalidate: 86400 },
    })
    if (!sheet.ok) return null
    const src = /src: url\((.+?)\) format\('(?:opentype|truetype)'\)/.exec(await sheet.text())
    if (!src) return null
    const file = await fetch(src[1], { signal: AbortSignal.timeout(2500), next: { revalidate: 86400 } })
    return file.ok ? await file.arrayBuffer() : null
  } catch {
    return null
  }
}

/** The cover as a data URL — JPEG or PNG only (what the renderer draws), at
 *  share-card size when the source can resize (Unsplash). */
async function photo(url: string): Promise<string | null> {
  if (!/^https?:\/\//.test(url)) return null
  try {
    const at = new URL(url)
    if (at.hostname === 'images.unsplash.com') {
      for (const [k, v] of [['w', '1200'], ['h', '630'], ['fit', 'crop'], ['fm', 'jpg'], ['q', '72']]) {
        at.searchParams.set(k, v)
      }
    }
    const res = await fetch(at.toString(), { signal: AbortSignal.timeout(4000), next: { revalidate: 3600 } })
    if (!res.ok) return null
    const bytes = new Uint8Array(await res.arrayBuffer())
    if (bytes.byteLength < 64 || bytes.byteLength > 8_000_000) return null
    const jpeg = bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
    const png = bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47
    if (!jpeg && !png) return null
    return `data:image/${jpeg ? 'jpeg' : 'png'};base64,${Buffer.from(bytes).toString('base64')}`
  } catch {
    return null
  }
}

function nameSize(name: string, condensed: boolean, caps: boolean): number {
  const n = name.length
  const base = n <= 10 ? 136 : n <= 14 ? 120 : n <= 18 ? 104 : n <= 24 ? 92 : n <= 32 ? 78 : 64
  return Math.round(base * (condensed ? 1.15 : 1) * (caps ? 0.9 : 1))
}

/** A plain card for an address with no published site behind it: no name,
 *  no brand — nothing to leak, nothing broken. */
function blank(): ImageResponse {
  return new ImageResponse(
    (
      <div style={{ width: '100%', height: '100%', display: 'flex', background: 'rgb(24, 24, 27)' }} />
    ),
    { ...OG_SIZE }
  )
}

/**
 * The share card for one page. `page` names an inner page ("Menu"); `cover`
 * is a photograph to use when this page has none of its own (the home cover).
 */
export async function shareCard(
  data: PublicWebsitePayload | null,
  opts: { page?: string; cover?: string } = {}
): Promise<ImageResponse> {
  if (!data) return blank()
  const theme = data.theme || {}
  const dna = (theme.dna && typeof theme.dna === 'object' ? theme.dna : {}) as Record<string, unknown>
  const faceKey = String(dna.display || BY_TYPE_SYSTEM[String(theme.type_system || '')] || 'manrope')
  const [displayFamily, displayWeight] = DISPLAY[faceKey] || DISPLAY.manrope
  const [bodyFamily, bodyWeight] = BODY[String(dna.body || '')] || BODY.manrope
  const caps = dna.headline === 'caps'

  const raw = data.business.display_name.trim()
  const name = caps ? raw.toUpperCase() : raw
  const where = locality(data)
  const label = [opts.page || tradeWords(data), where].filter(Boolean).join('  ·  ').toUpperCase()

  const primary = rgbOf(theme.primary_color) || rgbOf(theme.text_color) || [31, 61, 52]
  const accentRaw = rgbOf(theme.accent_color) || primary
  const cover = coverImage(data) || opts.cover || ''

  const [display, body, picture] = await Promise.all([
    googleFont(displayFamily, displayWeight, `${name}${raw.slice(0, 1)}`),
    googleFont(bodyFamily, bodyWeight, label || ' '),
    cover ? photo(cover) : Promise.resolve(null),
  ])
  const fonts: { name: string; data: ArrayBuffer; weight: 400 | 500 | 600 | 700 | 800; style: 'normal' }[] = []
  if (display) fonts.push({ name: 'Display', data: display, weight: 400, style: 'normal' })
  if (body) fonts.push({ name: 'Body', data: body, weight: 400, style: 'normal' })
  const displayFont = display ? 'Display' : undefined
  const bodyFont = body ? 'Body' : displayFont

  const size = nameSize(name, CONDENSED.has(faceKey), caps)
  const nameStyle = {
    display: 'flex',
    fontFamily: displayFont,
    fontSize: size,
    lineHeight: CONDENSED.has(faceKey) ? 0.9 : 0.98,
    letterSpacing: caps ? Math.round(size * 0.01) : -Math.round(size * 0.025),
    maxWidth: 1040,
  } as const
  const labelRow = (color: string, rule: string) =>
    label ? (
      <div style={{ display: 'flex', alignItems: 'center', fontFamily: bodyFont, fontSize: 24, letterSpacing: 4,
        color }}>
        <div style={{ display: 'flex', width: 56, height: 4, background: rule, marginRight: 20 }} />
        <div style={{ display: 'flex' }}>{label}</div>
      </div>
    ) : null

  if (picture) {
    // The shade carries the brand's own deep colour, not a flat black.
    const shade = mix(primary, [0, 0, 0], 0.62)
    const rule = luminance(accentRaw) > 0.18 ? css(accentRaw) : 'rgba(255, 255, 255, 0.9)'
    return new ImageResponse(
      (
        <div style={{ width: '100%', height: '100%', display: 'flex', position: 'relative', background: css(shade) }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws plain <img>, not next/image */}
          <img src={picture} width={1200} height={630} alt=""
            style={{ position: 'absolute', left: 0, top: 0, width: 1200, height: 630, objectFit: 'cover' }} />
          <div style={{ position: 'absolute', left: 0, top: 0, width: 1200, height: 630, display: 'flex',
            backgroundImage: `linear-gradient(180deg, ${css(shade, 0)} 28%, ${css(shade, 0.42)} 52%, ${css(shade, 0.9)} 100%)` }} />
          <div style={{ position: 'absolute', left: 72, right: 72, bottom: 64, display: 'flex',
            flexDirection: 'column', color: '#ffffff' }}>
            {labelRow('rgba(255, 255, 255, 0.88)', rule)}
            <div style={{ ...nameStyle, marginTop: label ? 22 : 0 }}>{name}</div>
          </div>
        </div>
      ),
      { ...OG_SIZE, ...(fonts.length ? { fonts } : {}) }
    )
  }

  // Set in type: the primary colour as the ground, the name in the colour
  // that reads on it, the initial as a quiet watermark.
  const ink: Rgb = luminance(primary) > 0.6 ? [17, 17, 17] : [255, 255, 255]
  const rule = Math.abs(luminance(accentRaw) - luminance(primary)) > 0.2 ? css(accentRaw) : css(ink, 0.7)
  return new ImageResponse(
    (
      <div style={{ width: '100%', height: '100%', display: 'flex', position: 'relative', flexDirection: 'column',
        justifyContent: 'space-between', padding: '68px 72px', background: css(primary), color: css(ink) }}>
        <div style={{ position: 'absolute', right: -30, bottom: -170, display: 'flex', fontFamily: displayFont,
          fontSize: 640, lineHeight: 1, color: css(ink, 0.09) }}>
          {raw.slice(0, 1).toUpperCase()}
        </div>
        {labelRow(css(ink, 0.82), rule) || <div style={{ display: 'flex' }} />}
        <div style={nameStyle}>{name}</div>
      </div>
    ),
    { ...OG_SIZE, ...(fonts.length ? { fonts } : {}) }
  )
}
