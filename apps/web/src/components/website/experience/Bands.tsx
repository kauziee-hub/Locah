import type { CSSProperties, ReactNode } from 'react'
import type { Pic } from './HeroScenes'

/**
 * Bands: a moving line of the business's own words, and a closing call to
 * action set as large as the page allows.
 */

export function Marquee({ items, variant, label }: { items: string[]; variant: string; label: string }) {
  const words = items.map((item) => item.trim()).filter(Boolean).slice(0, 12)
  if (words.length < 2) return null
  // Long lines travel at the same speed as short ones.
  const length = words.join(' ').length
  const style = { '--marquee-dur': `${Math.max(22, Math.min(70, length * 0.55))}s` } as CSSProperties
  const list = (hidden: boolean) => (
    <ul className="fx-marquee__list" aria-hidden={hidden || undefined}>
      {/* Repeated so the band is always wider than the screen. */}
      {[...words, ...words].map((word, i) => (
        <li key={i}>{word}</li>
      ))}
    </ul>
  )
  return (
    <section
      className={`fx-marquee ${variant === 'outline' ? 'fx-marquee--outline' : ''}`}
      aria-label={label}
      style={style}
    >
      <div className="fx-marquee__track">
        {list(false)}
        {list(true)}
      </div>
    </section>
  )
}

export function CtaGiant({
  headline,
  body,
  image,
  actions,
}: {
  headline: string
  body: string
  image?: Pic
  actions: ReactNode
}) {
  return (
    <section className={`fx-cta ${image ? 'fx-cta--pic' : ''}`} data-progress="">
      {image ? (
        <div className="fx-cta__bg" aria-hidden="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={image.url} alt="" loading="lazy" />
        </div>
      ) : null}
      <h2 className="fx-cta__title" data-split="">
        {headline}
      </h2>
      {body ? (
        <p className="fx-cta__body" data-reveal="">
          {body}
        </p>
      ) : null}
      <div className="fx-cta__actions" data-reveal="">
        {actions}
      </div>
    </section>
  )
}

type CategoryRow = { name: string; description: string; meta: string; tags: string[]; image?: Pic }

/**
 * A range known by its categories, as a pinned rail of large picture cards or
 * an asymmetric bento — the same compositions a named catalogue gets.
 */
export function CategoryScene({
  variant,
  anchor,
  title,
  subtitle,
  alt,
  rows,
}: {
  variant: 'rail' | 'bento'
  anchor?: string
  title: string
  subtitle: string
  alt: boolean
  rows: CategoryRow[]
}) {
  const head = (
    <div className="ls-head ls-head--showcase">
      <h2 className="ls-title" data-split="">
        {title}
      </h2>
      {subtitle ? (
        <p className="ls-sub" data-reveal="">
          {subtitle}
        </p>
      ) : null}
    </div>
  )
  const copy = (row: CategoryRow) => (
    <>
      {row.meta ? <span className="fx-rail__kicker">{row.meta}</span> : null}
      <h3>{row.name}</h3>
      {row.description ? <p>{row.description}</p> : null}
      {row.tags.length ? <p className="ls-category__tags">{row.tags.join(' · ')}</p> : null}
    </>
  )
  if (variant === 'rail') {
    return (
      <section id={anchor} className={`ls-section fx-rail ${alt ? 'ls-section--alt' : ''}`} data-rail="">
        <div className="fx-rail__stage">
          <div className="fx-rail__head">
            {head}
            <span className="fx-rail__count" aria-hidden="true">
              {String(rows.length).padStart(2, '0')}
            </span>
          </div>
          <div className="fx-rail__track" data-rail-track="">
            <ul className="fx-rail__list" data-reveal-group="">
              {rows.map((row, i) => (
                <li key={row.name} className="fx-rail__card" data-tilt="">
                  <span className="fx-rail__index">{String(i + 1).padStart(2, '0')}</span>
                  <div className="fx-rail__media">
                    {row.image ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={row.image.url} alt={row.image.alt_text || row.name} loading="lazy" />
                    ) : (
                      <span className="ls-picture__plate" aria-hidden="true">
                        <span>{row.name}</span>
                      </span>
                    )}
                  </div>
                  <div className="fx-rail__body">{copy(row)}</div>
                </li>
              ))}
            </ul>
          </div>
          <div className="fx-rail__bar" aria-hidden="true">
            <span />
          </div>
        </div>
      </section>
    )
  }
  const ordered = [...rows.filter((r) => r.image), ...rows.filter((r) => !r.image)]
  return (
    <section id={anchor} className={`ls-section ${alt ? 'ls-section--alt' : ''}`}>
      <div className="ls-inner">
        {head}
        <ul className="fx-bento" data-reveal-group="">
          {ordered.map((row) => (
            <li key={row.name} className={`fx-bento__cell ${row.image ? 'fx-bento__cell--pic' : ''}`} data-tilt="">
              {row.image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={row.image.url} alt={row.image.alt_text || row.name} loading="lazy" />
              ) : null}
              <div className="fx-bento__copy">{copy(row)}</div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
