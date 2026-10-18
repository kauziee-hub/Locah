import Link from 'next/link'
import { srcSetFor } from '../picture'
import type { CSSProperties, ReactNode } from 'react'
import type { Pic } from './HeroScenes'

/**
 * Section compositions of the premium site (section types statement, pillars,
 * faq, media_text, and the inner-page hero). Server-rendered, complete without
 * JavaScript; the motion runtime only moves what is here.
 *
 * Words are the owner's, or copy that passed governance; FAQ answers are built
 * only from facts the owner gave (site_composer). Pictures are the section's own.
 */

type Vars = CSSProperties & Record<`--${string}`, string | number>

/* ------------------------------------------------------------------ icons */

const ICONS: Record<string, string> = {
  leaf: 'M5 19c6 0 14-4 14-14-10 0-14 8-14 14Zm0 0 7-7',
  truck: 'M3 7h11v9H3zM14 10h4l3 3v3h-7zM7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v5l3 2',
  heart: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z',
  star: 'm12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9Z',
  flame: 'M12 21c4 0 7-2.7 7-6.6 0-3.6-2.5-5.7-4-8.4-.8 2-2 3-3 3.2C12.6 6.8 11.3 4.6 9 3c.4 3-3 5.4-3 10.4C6 18.3 8 21 12 21Z',
  shield: 'M12 3 5 6v6c0 4.4 3 7.7 7 9 4-1.3 7-4.6 7-9V6l-7-3Zm-3 9 2 2 4-4',
  hand: 'M8 13V6a1.5 1.5 0 0 1 3 0v5m0-6V4.5a1.5 1.5 0 0 1 3 0V11m0-5a1.5 1.5 0 0 1 3 0v7c0 4-2.5 8-7 8-3 0-5-2-6.5-5L5 13.5a1.6 1.6 0 0 1 2.6-1.8L8 13',
  sparkle: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18',
  pin: 'M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11ZM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
  chat: 'M4 5h16v11H8l-4 4V5Z',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v5M16 3v5',
  bag: 'M5 8h14l-1 12H6L5 8Zm4 0V6a3 3 0 0 1 6 0v2',
  cut: 'M6 7a3 3 0 1 0 0-.1M6 17a3 3 0 1 0 0 .1M8.5 8.5 20 18M8.5 15.5 20 6',
  home: 'M4 11 12 4l8 7v9H4v-9Zm6 9v-6h4v6',
  drop: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z',
  bolt: 'M13 3 5 14h6l-1 7 8-11h-6l1-7Z',
  check: 'M5 12.5 10 17l9-10',
  scale: 'M12 4v16M5 20h14M5 8h14M5 8l-2.5 6a2.5 2.5 0 0 0 5 0L5 8Zm14 0-2.5 6a2.5 2.5 0 0 0 5 0L19 8Z',
}

export function Icon({ name }: { name: string }) {
  const d = ICONS[name] || ICONS.sparkle
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" className="fx-icon">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/* ------------------------------------------------------------- statement */

/** The highlighted phrase set apart — a painted marker, an outline, an italic. */
function Highlighted({ text, highlight }: { text: string; highlight: string }) {
  if (!highlight || !text.includes(highlight)) return <>{text}</>
  const at = text.indexOf(highlight)
  return (
    <>
      {text.slice(0, at)}
      <span className="fx-mark">{highlight}</span>
      {text.slice(at + highlight.length)}
    </>
  )
}

export function Statement({
  variant,
  eyebrow,
  text,
  highlight,
  image,
  pictures,
  alt,
}: {
  variant: string
  eyebrow: string
  text: string
  highlight: string
  image?: Pic
  pictures: Pic[]
  alt: boolean
}) {
  if (!text) return null
  const ground = alt ? 'ls-section--alt' : ''
  if (variant === 'image' && image) {
    // cinematic — the sentence set huge over one full-bleed photograph that
    // drifts slower than the page.
    return (
      <section className="fx-statement fx-statement--image" data-progress="">
        <div className="fx-statement__bg" aria-hidden="true">
          <div className="fx-statement__bgframe" data-parallax="">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image.url} srcSet={srcSetFor(image.url)} alt="" loading="lazy" />
          </div>
        </div>
        <div className="fx-statement__inner">
          {eyebrow ? (
            <p className="ls-eyebrow" data-reveal="fade">
              {eyebrow}
            </p>
          ) : null}
          <p className="fx-statement__text" data-split="">
            <Highlighted text={text} highlight={highlight} />
          </p>
        </div>
      </section>
    )
  }
  if (variant === 'split' && image) {
    return (
      <section className={`ls-section fx-statement fx-statement--split ${ground}`} data-progress="">
        <div className="fx-statement__inner">
          <div>
            {eyebrow ? (
              <p className="ls-eyebrow" data-reveal="fade">
                {eyebrow}
              </p>
            ) : null}
            <p className="fx-statement__text" data-split="read">
              <Highlighted text={text} highlight={highlight} />
            </p>
          </div>
          <figure className="fx-statement__media fx-shape" data-reveal="mask">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image.url} srcSet={srcSetFor(image.url)} alt="" loading="lazy" />
          </figure>
        </div>
      </section>
    )
  }
  // giant — the words as large as the screen allows, and nothing else: the
  // small pictures once set between them read as emoji and as images that
  // failed to load, and squeezed the line on a phone (three certification
  // critiques), so the sentence stands in type alone.
  const words = text.split(/\s+/)
  void pictures
  return (
    <section className={`ls-section fx-statement fx-statement--giant ${ground}`} data-progress="">
      <div className="fx-statement__inner">
        {eyebrow ? (
          <p className="ls-eyebrow" data-reveal="fade">
            {eyebrow}
          </p>
        ) : null}
        <p className="fx-statement__text" data-split="read">
          {words.map((word, i) => {
            const marked = highlight && highlight.split(/\s+/).includes(word.replace(/[.,!?]$/, ''))
            return (
              <span key={i}>
                <span className={marked ? 'fx-mark' : undefined}>{word}</span>{' '}
              </span>
            )
          })}
        </p>
      </div>
    </section>
  )
}

/* --------------------------------------------------------------- pillars */

export type Pillar = { title: string; body: string; icon: string }

export function Pillars({
  variant,
  eyebrow,
  title,
  subtitle,
  items,
  alt,
  image,
}: {
  variant: string
  eyebrow: string
  title: string
  subtitle: string
  items: Pillar[]
  alt: boolean
  /** A close picture the numbered list sits beside. */
  image?: Pic
}) {
  if (items.length < 2) return null
  const pictured = variant === 'numbered' && image
  return (
    <section
      className={`ls-section fx-pillars fx-pillars--${variant} ${pictured ? 'fx-pillars--pictured' : ''} ${
        alt ? 'ls-section--alt' : ''
      }`}
    >
      <div className="ls-inner fx-pillars__inner">
        {pictured ? (
          <figure className="fx-pillars__media fx-shape" data-reveal="mask">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image.url} srcSet={srcSetFor(image.url)} alt={image.alt_text || ''} loading="lazy" />
          </figure>
        ) : null}
        <div className="fx-pillars__body">
        {title ? (
          <div className="ls-head fx-pillars__head">
            {eyebrow ? (
              <p className="ls-eyebrow" data-reveal="fade">
                {eyebrow}
              </p>
            ) : null}
            <h2 className="ls-title" data-split="">
              {title}
            </h2>
            {subtitle ? (
              <p className="ls-sub" data-reveal="">
                {subtitle}
              </p>
            ) : null}
          </div>
        ) : null}
        <ol className="fx-pillars__list" data-reveal-group="" style={{ '--n': items.length } as Vars}>
          {items.map((item, i) => (
            <li key={item.title} className="fx-pillar" data-tilt={variant === 'cards' ? '' : undefined}>
              {variant === 'numbered' ? (
                <span className="fx-pillar__num" aria-hidden="true">
                  {String(i + 1).padStart(2, '0')}
                </span>
              ) : (
                <span className="fx-pillar__icon">
                  <Icon name={item.icon} />
                </span>
              )}
              <h3 className="fx-pillar__title">{item.title}</h3>
              {item.body ? <p className="fx-pillar__body">{item.body}</p> : null}
            </li>
          ))}
        </ol>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------- faq */

export type Faq = { q: string; a: string }

export function FaqSection({
  variant,
  title,
  subtitle,
  items,
  aside,
  alt,
}: {
  variant: string
  title: string
  subtitle: string
  items: Faq[]
  aside?: ReactNode
  alt: boolean
}) {
  if (!items.length) return null
  const list = (
    <div className="fx-faq__list" data-reveal-group="">
      {items.map((item, i) => (
        // <details> opens and closes without JavaScript, and is announced as such.
        <details key={item.q} className="fx-faq__item" open={i === 0 && variant !== 'split'}>
          <summary className="fx-faq__q">
            <span>{item.q}</span>
            <span className="fx-faq__toggle" aria-hidden="true" />
          </summary>
          <div className="fx-faq__a">
            <p>{item.a}</p>
          </div>
        </details>
      ))}
    </div>
  )
  return (
    <section id="faq" className={`ls-section fx-faq fx-faq--${variant} ${alt ? 'ls-section--alt' : ''}`}>
      <div className="ls-inner fx-faq__inner">
        <div className="fx-faq__head">
          <h2 className="ls-title" data-split="">
            {title}
          </h2>
          {subtitle ? (
            <p className="ls-sub" data-reveal="">
              {subtitle}
            </p>
          ) : null}
          {aside ? (
            <div className="fx-faq__aside" data-reveal="">
              {aside}
            </div>
          ) : null}
        </div>
        {list}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------ media_text */

export type MediaRow = { eyebrow: string; title: string; body: string; image?: Pic }

export function MediaText({
  variant,
  title,
  rows,
  alt,
  more,
}: {
  variant: string
  title: string
  rows: MediaRow[]
  alt: boolean
  /** The way on: a home page's story teaser links to the story's own page. */
  more?: { label: string; href: string }
}) {
  if (!rows.length) return null
  const moreLink = more ? (
    <div className="fx-more" data-reveal="fade">
      <Link className="fx-more__link" href={more.href}>
        <span>{more.label}</span>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>
    </div>
  ) : null
  const ground = alt ? 'ls-section--alt' : ''
  if (variant === 'sticky') {
    // The pictures hold still and change as each passage is read beside them.
    const pictured = rows.filter((r) => r.image)
    return (
      <section className={`ls-section fx-mtext fx-mtext--sticky ${ground}`} data-scene="">
        <div className="fx-mtext__grid" style={{ '--n': rows.length } as Vars}>
          <div className="fx-mtext__pin" aria-hidden="true">
            {pictured.map((row, i) => (
              <figure key={row.title} className="fx-mtext__frame fx-shape" style={{ '--i': i } as Vars}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={row.image!.url} srcSet={srcSetFor(row.image!.url)} alt="" loading="lazy" />
              </figure>
            ))}
          </div>
          <div className="fx-mtext__rows">
            {title ? (
              <h2 className="ls-title fx-mtext__title" data-split="">
                {title}
              </h2>
            ) : null}
            {rows.map((row, i) => (
              <article key={row.title} className="fx-mtext__row" data-reveal="">
                <span className="fx-mtext__num">{String(i + 1).padStart(2, '0')}</span>
                {row.eyebrow ? <p className="ls-eyebrow">{row.eyebrow}</p> : null}
                <h3>{row.title}</h3>
                {row.body ? <p className="fx-mtext__body">{row.body}</p> : null}
              </article>
            ))}
            {moreLink}
          </div>
        </div>
      </section>
    )
  }
  return (
    <section className={`ls-section fx-mtext fx-mtext--alternating ${ground}`}>
      <div className="ls-inner">
        {title ? (
          <div className="ls-head">
            <h2 className="ls-title" data-split="">
              {title}
            </h2>
          </div>
        ) : null}
        <div className="fx-mtext__list">
          {rows.map((row, i) => (
            <article key={row.title} className={`fx-mtext__item ${row.image ? '' : 'fx-mtext__item--text'}`} data-progress="">
              {row.image ? (
                <figure className="fx-mtext__media fx-shape" data-reveal="mask">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={row.image.url} srcSet={srcSetFor(row.image.url)} alt="" loading="lazy" />
                </figure>
              ) : null}
              <div className="fx-mtext__copy" data-reveal={i % 2 ? 'left' : 'right'}>
                {rows.length > 1 ? (
                  <span className="fx-mtext__num" aria-hidden="true">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                ) : null}
                {row.eyebrow ? <p className="ls-eyebrow">{row.eyebrow}</p> : null}
                {rows.length > 1 ? <h3>{row.title}</h3> : <h2 className="ls-title">{row.title}</h2>}
                {row.body ? <p className="fx-mtext__body">{row.body}</p> : null}
                {rows.length === 1 ? moreLink : null}
              </div>
            </article>
          ))}
        </div>
        {rows.length > 1 ? moreLink : null}
      </div>
    </section>
  )
}

/* -------------------------------------------------------- inner-page hero */

export function PageHero({
  eyebrow,
  title,
  sub,
  actions,
  image,
}: {
  eyebrow: ReactNode
  title: ReactNode
  sub: ReactNode
  actions: ReactNode
  image?: Pic
}) {
  return (
    <section className={`ls-hero fx-pagehero ${image ? 'fx-pagehero--pic' : ''}`} data-progress="">
      <div className="fx-pagehero__inner">
        {eyebrow}
        {title}
        <div className="fx-pagehero__foot">
          {sub}
          {actions}
        </div>
      </div>
      {image ? (
        <figure className="fx-pagehero__media" data-reveal="mask">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={image.url} srcSet={srcSetFor(image.url)} alt={image.alt_text || ''} fetchPriority="high" />
        </figure>
      ) : null}
      <div className="fx-pagehero__pattern" aria-hidden="true" />
    </section>
  )
}
