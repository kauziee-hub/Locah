import type { CSSProperties, ReactNode } from 'react'
import { AuroraCanvas } from './AuroraCanvas'

/**
 * Hero scenes: the first screen of a site as a moment, not a banner.
 *
 * Each scene is a platform composition the creative director may choose
 * (`hero` layout_variant). They are built only from the business's own words
 * and pictures — the page's pictures, gathered by WebsitePageView — and every
 * one is a complete, readable hero without JavaScript: the motion runtime only
 * moves what is already there (see ./motion.ts, site-experience.css).
 *
 *   cinematic_zoom  a framed picture that opens to full-bleed as you scroll
 *   orbit           the business's pictures on a turning 3D ring
 *   plane           a tilted wall of pictures that straightens toward you
 *   kinetic         poster type that pulls apart around a growing picture
 *   depth           a picture with floating, layered cards at different depths
 *   aurora          a living gradient in the brand's colours (no photos needed)
 */

export type Pic = { url: string; alt_text?: string | null }

export type HeroParts = {
  eyebrow: ReactNode
  title: ReactNode
  sub: ReactNode
  actions: ReactNode
  badges: ReactNode
  headline: string
  accent: string
}

type Vars = CSSProperties & Record<`--${string}`, string | number>

/** `inert` as React 18 can render it (an empty attribute): nothing inside can be
 *  focused or clicked. React 18's types say boolean; the DOM wants presence. */
const INERT = { inert: '' } as unknown as { inert?: boolean }

/** The scene this hero can really draw with the pictures it has. */
export function sceneFor(variant: string, pictures: Pic[], image?: Pic): string {
  const count = pictures.length
  if ((variant === 'orbit' || variant === 'plane') && count < 4) {
    return image || count ? 'cinematic_zoom' : 'aurora'
  }
  if (['cinematic_zoom', 'depth', 'kinetic'].includes(variant) && !image && !count) return 'aurora'
  return variant
}

/** Repeat a short list of pictures until there are enough to fill a ring or wall. */
function fill(pictures: Pic[], at: number): Pic[] {
  if (!pictures.length) return []
  const out: Pic[] = []
  for (let i = 0; out.length < at; i++) out.push(pictures[i % pictures.length])
  return out
}

function Copy({ parts, late = false }: { parts: HeroParts; late?: boolean }) {
  return (
    <>
      {parts.eyebrow}
      {parts.title}
      <div className={late ? 'fx-late' : undefined}>
        {parts.sub}
        {parts.actions}
        {parts.badges}
      </div>
    </>
  )
}

export function HeroScene({
  variant,
  parts,
  image,
  pictures,
  longest,
}: {
  variant: string
  parts: HeroParts
  image?: Pic
  pictures: Pic[]
  longest: number
}) {
  const lead = image || pictures[0]
  const base: Vars = { '--hero-longest': longest }

  if (variant === 'cinematic_zoom' && lead) {
    // The words sit on the page in ink; the same words in white are drawn
    // inside the growing frame, so the headline is split exactly along the
    // picture's edge and is readable at every point of the scroll. The
    // white copy is a picture of the words: hidden from assistive tech and
    // inert, and clicks pass through the frame to the real buttons beneath.
    const light: HeroParts = {
      ...parts,
      title: (
        <p className="ls-hero__headline" data-split="">
          <AccentText text={parts.headline} accent={parts.accent} />
        </p>
      ),
    }
    return (
      <section className="ls-hero fx-zoom" data-scene="" style={base}>
        <div className="fx-zoom__stage">
          <div className="ls-hero__inner fx-zoom__copy">
            <Copy parts={parts} late />
          </div>
          <div className="fx-zoom__frame">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={lead.url} alt={lead.alt_text || ''} fetchPriority="high" />
            <div className="fx-zoom__scrim" aria-hidden="true" />
            <div className="ls-hero__inner fx-zoom__copy fx-zoom__copy--light" aria-hidden="true" {...INERT}>
              <Copy parts={light} late />
            </div>
          </div>
          <span className="fx-cue" aria-hidden="true" />
        </div>
      </section>
    )
  }

  if (variant === 'orbit') {
    const cards = fill(pictures, Math.min(10, Math.max(8, pictures.length)))
    return (
      <section className="ls-hero fx-orbit" data-scene="" data-pointer="" style={base}>
        <div className="fx-orbit__stage">
          <div className="ls-hero__inner fx-orbit__copy">
            <Copy parts={parts} />
          </div>
          <div className="fx-orbit__view" aria-hidden="true">
            <div className="fx-orbit__ring" style={{ '--n': cards.length } as Vars}>
              {cards.map((pic, i) => (
                <figure key={i} className="fx-orbit__card" style={{ '--i': i } as Vars}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={pic.url} alt="" loading={i < 5 ? 'eager' : 'lazy'} />
                </figure>
              ))}
            </div>
          </div>
        </div>
      </section>
    )
  }

  if (variant === 'plane') {
    const tiles = fill(pictures, 16)
    const columns = [0, 1, 2, 3].map((c) => tiles.filter((_, i) => i % 4 === c))
    return (
      <section className="ls-hero fx-plane" data-scene="" style={base}>
        <div className="fx-plane__stage">
          <div className="fx-plane__view" aria-hidden="true">
            <div className="fx-plane__grid">
              {columns.map((column, c) => (
                <div key={c} className="fx-plane__col">
                  {column.map((pic, i) => (
                    <figure key={i} className="fx-plane__tile">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={pic.url} alt="" loading={c < 2 && i < 2 ? 'eager' : 'lazy'} />
                    </figure>
                  ))}
                </div>
              ))}
            </div>
          </div>
          <div className="fx-plane__scrim" aria-hidden="true" />
          <div className="ls-hero__inner fx-plane__copy">
            <Copy parts={parts} />
          </div>
        </div>
      </section>
    )
  }

  if (variant === 'kinetic') {
    const [first, second] = splitHeadline(parts.headline, parts.accent)
    return (
      <section className="ls-hero fx-kinetic" data-scene="" style={base}>
        <div className="fx-kinetic__stage">
          <div className="ls-hero__inner fx-kinetic__inner">
            {parts.eyebrow}
            <h1 className="ls-hero__headline fx-kinetic__title">
              <span className="fx-kinetic__line fx-kinetic__line--a">
                <span data-split="">{first}</span>
                {lead ? (
                  <span className="fx-kinetic__pill" aria-hidden="true">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={lead.url} alt="" fetchPriority="high" />
                  </span>
                ) : null}
              </span>
              {second ? (
                <span className="fx-kinetic__line fx-kinetic__line--b">
                  <span data-split="" className={parts.accent && second === parts.accent ? 'ls-accent' : undefined}>
                    {second}
                  </span>
                </span>
              ) : null}
            </h1>
            <div className="fx-kinetic__foot" data-reveal="">
              <div>
                {parts.sub}
                {parts.badges}
              </div>
              {parts.actions}
            </div>
          </div>
        </div>
      </section>
    )
  }

  if (variant === 'depth' && lead) {
    const floats = pictures.filter((p) => p.url !== lead.url).slice(0, 3)
    return (
      <section className="ls-hero fx-depth ls-hero--hasimage" data-progress="" data-pointer="" style={base}>
        <div className="fx-depth__bg" aria-hidden="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={lead.url} alt="" fetchPriority="high" />
        </div>
        <div className="ls-hero__inner fx-depth__copy">
          <Copy parts={parts} />
        </div>
        {floats.length ? (
          <div className="fx-depth__floats" aria-hidden="true">
            {floats.map((pic, i) => (
              <figure key={pic.url} className={`fx-depth__float fx-depth__float--${i}`}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={pic.url} alt="" />
              </figure>
            ))}
          </div>
        ) : null}
      </section>
    )
  }

  // aurora — and the floor for any scene without the pictures it needs.
  return (
    <section className="ls-hero fx-aurora" data-progress="" data-pointer="" style={base}>
      <div className="fx-aurora__wash" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <AuroraCanvas />
      <div className="fx-grain" aria-hidden="true" />
      <div className="ls-hero__inner fx-aurora__copy">
        <Copy parts={parts} />
      </div>
    </section>
  )
}

/** The headline with its accent phrase in the brand colour (as the h1 sets it). */
function AccentText({ text, accent }: { text: string; accent: string }) {
  if (!accent || !text.includes(accent)) return <>{text}</>
  const at = text.indexOf(accent)
  let rest = text.slice(at + accent.length)
  let phrase = accent
  if (/^[.!?,]+$/.test(rest.trim())) {
    phrase = accent + rest.trim()
    rest = ''
  }
  return (
    <>
      {text.slice(0, at)}
      <span className="ls-accent">{phrase}</span>
      {rest}
    </>
  )
}

/** Two lines for poster type: the accent phrase on its own line when it ends
 *  the headline, otherwise the words divided near the middle. */
export function splitHeadline(headline: string, accent: string): [string, string] {
  const text = headline.trim()
  if (accent && text.endsWith(accent.replace(/[.!?]+$/, '')) && text.length > accent.length + 2) {
    const at = text.lastIndexOf(accent.replace(/[.!?]+$/, ''))
    return [text.slice(0, at).trim(), text.slice(at).trim()]
  }
  if (accent && text.endsWith(accent) && text.length > accent.length + 2) {
    return [text.slice(0, text.length - accent.length).trim(), accent]
  }
  const words = text.split(/\s+/)
  if (words.length < 2) return [text, '']
  let best = 1
  let bestGap = Infinity
  for (let i = 1; i < words.length; i++) {
    const gap = Math.abs(words.slice(0, i).join(' ').length - words.slice(i).join(' ').length)
    if (gap < bestGap) {
      bestGap = gap
      best = i
    }
  }
  return [words.slice(0, best).join(' '), words.slice(best).join(' ')]
}
