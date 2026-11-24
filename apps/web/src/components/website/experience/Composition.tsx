import Link from 'next/link'
import type { CSSProperties, ReactNode } from 'react'
import { srcSetFor } from '../picture'

/**
 * A composed section: blocks placed on a 12-column grid (a 6-column grid on a
 * phone), with layers, frames, plates and motion — the arrangement the layout
 * engine (`platform_core/interview/layout_engine.py`) or the reference reader
 * chose for this business, held to `website/composition_grammar.py` before it
 * was stored. Server-rendered and complete without JavaScript; the motion
 * runtime only moves what is here (data-reveal, data-parallax, data-count).
 *
 * Every value used here is one the grammar allows; anything else falls back,
 * so an old or hand-edited section can never break the page.
 */

type Vars = CSSProperties & Record<`--${string}`, string | number>

export type CompositionBlock = {
  kind: string
  col: number
  span: number
  row: number
  rows: number
  layer?: number
  m_col?: number
  m_span?: number
  m_order?: number
  m_ratio?: string
  lift?: boolean
  plate?: boolean
  vertical?: boolean
  size?: string
  tone?: string
  frame?: string
  align?: string
  valign?: string
  motion?: string
  eyebrow?: string
  title?: string
  body?: string
  value?: string
  label?: string
  caption?: string
  cta_label?: string
  cta_url?: string
  price?: string
  points?: { title: string; body?: string; meta?: string }[]
  image?: { url: string; alt_text?: string | null }
}

const KINDS = new Set(['words', 'picture', 'number', 'quote', 'list', 'action', 'label'])
const GROUNDS = new Set(['base', 'alt', 'ink', 'tint'])
const HEIGHTS = new Set(['auto', 'tall', 'screen'])

function clamp(n: unknown, low: number, high: number, fallback: number): number {
  const v = Number(n)
  return Number.isFinite(v) ? Math.max(low, Math.min(high, Math.round(v))) : fallback
}

/** The motion runtime's attributes for a block's arrival. */
function motionOf(motion: string | undefined): Record<string, string> {
  switch (motion) {
    case 'none':
      return {}
    case 'mask':
      return { 'data-reveal': 'mask' }
    case 'scale':
      return { 'data-reveal': 'scale' }
    case 'parallax':
      // The picture drifts inside its frame (Composition's frame carries
      // data-parallax); the block itself arrives like a masked one.
      return { 'data-reveal': 'mask' }
    default:
      return { 'data-reveal': '' }
  }
}

/** A number the owner stated, counted once in view — only a plain integer is. */
function counted(value: string): Record<string, string> {
  return /^\d{1,6}$/.test(value.trim()) ? { 'data-count': value.trim() } : {}
}

function paragraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
}

export function Composition({
  ground,
  height,
  rows,
  anchor,
  blocks,
  alt,
  href,
  firstHeading = true,
}: {
  ground: string
  height: string
  rows: number
  anchor?: string
  blocks: CompositionBlock[]
  /** The page's alternating ground, used when the composition sits on the base. */
  alt: boolean
  /** A section path resolved for this tenant (and the preview token). */
  href: (path: string) => string
  /** The section's first title is its h2; the rest are h3. */
  firstHeading?: boolean
}) {
  const shown = blocks.filter((b) => KINDS.has(b.kind) && (b.kind !== 'picture' || b.image?.url))
  if (!shown.length) return null
  const g = GROUNDS.has(ground) ? ground : 'base'
  const groundClass = g === 'alt' || (g === 'base' && alt) ? 'ls-section--alt' : g === 'base' ? '' : `fx-comp--${g}`
  let headed = !firstHeading
  const gridRows = clamp(rows, 1, 10, Math.max(...shown.map((b) => (b.row || 1) + (b.rows || 1) - 1)))

  return (
    <section
      className={`ls-section fx-comp ${groundClass}`}
      data-height={HEIGHTS.has(height) ? height : 'auto'}
      id={anchor || undefined}
    >
      <div className="fx-comp__grid" style={{ '--rows': gridRows } as Vars}>
        {shown.map((b, i) => {
          const style: Vars = {
            '--c': clamp(b.col, 1, 12, 1),
            '--s': clamp(b.span, 1, 12, 6),
            '--r': clamp(b.row, 1, 10, 1),
            '--rs': clamp(b.rows, 1, 10, 1),
            '--z': clamp(b.layer, 0, 3, 0),
            '--mc': clamp(b.m_col, 1, 6, 1),
            '--ms': clamp(b.m_span, 2, 6, 6),
            '--mo': clamp(b.m_order, 0, 99, i + 1),
          }
          if (b.kind === 'picture' && b.m_ratio) style['--mr'] = b.m_ratio.replace('/', ' / ')
          // The longest word its display type has to hold (see site-compose.css).
          const display = b.kind === 'number' ? b.value || '' : b.kind === 'quote' ? b.title || b.body || '' : b.title || ''
          const longest = Math.max(4, ...display.split(/\s+/).map((w) => w.length))
          style['--longest'] = Math.min(longest, 24)
          const col = clamp(b.col, 1, 12, 1)
          const end = col + clamp(b.span, 1, 12, 6) - 1
          const edge = col === 1 && end === 12 ? 'both' : col === 1 ? 'start' : end === 12 ? 'end' : undefined
          const attrs = {
            className: `fx-comp__b fx-comp__b--${b.kind}`,
            style,
            'data-frame': b.kind === 'picture' ? b.frame || 'none' : undefined,
            'data-edge': b.kind === 'picture' && b.frame === 'bleed' ? edge : undefined,
            'data-wide': b.kind === 'list' && clamp(b.span, 1, 12, 6) >= 8 ? '' : undefined,
            'data-plate': b.plate ? '' : undefined,
            'data-lift': b.lift ? '' : undefined,
            'data-vertical': b.vertical ? '' : undefined,
            'data-size': b.size || 'm',
            'data-tone': b.tone || 'ink',
            'data-align': b.align || 'start',
            'data-valign': b.valign || 'start',
            ...motionOf(b.motion),
          }
          let body: ReactNode = null
          switch (b.kind) {
            case 'picture': {
              const img = (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={b.image!.url}
                  srcSet={srcSetFor(b.image!.url)}
                  sizes={`(min-width: 900px) ${Math.round((clamp(b.span, 1, 12, 6) / 12) * 100)}vw, 100vw`}
                  alt={b.image!.alt_text || b.caption || ''}
                  loading="lazy"
                />
              )
              body = (
                <figure className="fx-comp__pic">
                  {b.motion === 'parallax' ? (
                    <div className="fx-comp__frame" data-parallax="" style={{ '--speed': 0.12 } as Vars}>
                      {img}
                    </div>
                  ) : (
                    <div className="fx-comp__frame">{img}</div>
                  )}
                  {b.caption ? <figcaption className="fx-comp__caption">{b.caption}</figcaption> : null}
                </figure>
              )
              break
            }
            case 'words': {
              const Heading = headed ? 'h3' : 'h2'
              if (b.title) headed = true
              body = (
                <div className="fx-comp__words">
                  {b.eyebrow ? <p className="fx-comp__eyebrow">{b.eyebrow}</p> : null}
                  {b.title ? <Heading className="fx-comp__title">{b.title}</Heading> : null}
                  {b.price ? <p className="fx-comp__price">{b.price}</p> : null}
                  {b.body
                    ? paragraphs(b.body).map((p) => (
                        <p key={p.slice(0, 40)} className="fx-comp__body">
                          {p}
                        </p>
                      ))
                    : null}
                  {b.cta_label && b.cta_url ? (
                    <Link className="fx-comp__more" href={href(b.cta_url)}>
                      <span>{b.cta_label}</span>
                      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                        <path
                          d="M5 12h14M13 6l6 6-6 6"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </Link>
                  ) : null}
                </div>
              )
              break
            }
            case 'quote':
              body = (
                <blockquote className="fx-comp__quote">
                  {b.eyebrow ? <p className="fx-comp__eyebrow">{b.eyebrow}</p> : null}
                  <p>{b.title || b.body}</p>
                </blockquote>
              )
              break
            case 'number':
              body = (
                <div className="fx-comp__number">
                  <span className="fx-comp__value" {...counted(b.value || '')}>
                    {b.value}
                  </span>
                  {b.label ? <span className="fx-comp__label-text">{b.label}</span> : null}
                </div>
              )
              break
            case 'list':
              body = (
                <ol className="fx-comp__list">
                  {(b.points || [])
                    .filter((p) => p && p.title)
                    .map((p, n) => (
                      <li key={`${p.title}-${n}`}>
                        <span className="fx-comp__index" aria-hidden="true">
                          {String(n + 1).padStart(2, '0')}
                        </span>
                        <span className="fx-comp__point">
                          <strong>{p.title}</strong>
                          {p.body ? <span className="fx-comp__point-body">{p.body}</span> : null}
                        </span>
                        {p.meta ? <span className="fx-comp__meta">{p.meta}</span> : null}
                      </li>
                    ))}
                </ol>
              )
              break
            case 'action':
              body = b.cta_label && b.cta_url ? (
                <Link className="ls-btn fx-comp__btn" href={href(b.cta_url)} data-magnetic="">
                  {b.cta_label}
                </Link>
              ) : null
              break
            case 'label':
              body = <span className="fx-comp__label">{b.label}</span>
              break
          }
          if (!body) return null
          return (
            <div key={`${b.kind}-${i}`} {...attrs}>
              {body}
            </div>
          )
        })}
      </div>
    </section>
  )
}
