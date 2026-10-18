import type { CSSProperties, ReactNode } from 'react'
import type { Words } from '@/lib/site-words'
import { srcSetFor } from '../picture'
import { GlLiving } from './gl/GlLiving'
import { balanceWords, splitHeadline, type HeroParts, type Pic } from './HeroScenes'

/**
 * Covers: first screens composed like a designer's cover, each with its own
 * art direction AND its own movement — so a bakery, a butcher, a clinic and a
 * studio do not all open on the same scene doing the same thing.
 *
 *   arch       the words on the ground beside a tall arched photograph, a
 *              second picture overlapping its edge — the arch rises open,
 *              the small picture drifts at its own speed
 *   window     the headline set across the page with the photograph seen
 *              through a band between its lines — the band opens and the two
 *              lines part as the page scrolls
 *   gallery    an editorial collage: three photographs at three sizes and
 *              three speeds around the words — masks open one after another
 *   ledger     a ruled sheet: the headline, the photograph and the owner's
 *              own facts (hours, address, phone) each in its cell — the rules
 *              draw themselves, cell after cell
 *   signature  the food's photograph and, beside it, the dishes worth coming
 *              for with their prices — the photograph settles, the list
 *              arrives line by line
 *   stage      the headline centred and the photograph on a mat beneath it,
 *              rising toward the visitor as the page moves
 *
 * Like the scenes in ./HeroScenes.tsx they are platform compositions built
 * only from the business's own words, pictures and facts; every one is a
 * finished, readable cover without JavaScript or with reduced motion (the
 * still state is the designed state), and the motion runtime only moves what
 * is already there. Buttons stay the platform's (parts.actions).
 */

export const COVERS = new Set(['arch', 'window', 'gallery', 'ledger', 'signature', 'stage'])

/** A dish or product worth coming for, as the owner priced it. */
export type Signature = { name: string; price: string; unit?: string; diet?: string }

/** What a cover may draw on besides the hero's own words and pictures. */
export type CoverContext = {
  /** Where and when, as the owner keeps it (the main location). */
  place?: { address?: string; hours_summary?: string; phone?: string }
  /** Priced things from this page's own range, best first. */
  signatures?: Signature[]
  /** The range's own page, as the range section links to it. */
  more?: { label: string; href: string }
}

type Vars = CSSProperties & Record<`--${string}`, string | number>

/** The cover this hero can really draw: a collage needs three photographs, a
 *  signature list three priced things; otherwise the arch, which needs one. */
export function coverFor(variant: string, pictures: Pic[], image: Pic | undefined, ctx: CoverContext): string {
  const distinct = new Set(pictures.map((p) => p.url)).size
  if (!image && !distinct) return 'aurora'
  if (variant === 'gallery' && distinct < 3) return 'arch'
  if (variant === 'signature' && (ctx.signatures?.length || 0) < 3) return 'arch'
  return variant
}

/** A cover's photograph. `living`: the one picture the living photograph
 *  (design DNA signature, ./gl/living) may take over — the <img> stays. */
function Photo({
  pic,
  eager = false,
  sizes,
  decorative = false,
  living = false,
}: {
  pic: Pic
  eager?: boolean
  sizes?: string
  decorative?: boolean
  living?: boolean
}) {
  const img = (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={pic.url}
      srcSet={srcSetFor(pic.url)}
      sizes={sizes}
      alt={decorative ? '' : pic.alt_text || ''}
      {...(eager ? { fetchPriority: 'high' as const } : { loading: 'lazy' as const })}
    />
  )
  if (!living) return img
  return (
    <>
      {img}
      <GlLiving />
    </>
  )
}

function CoverCopy({ parts, children }: { parts: HeroParts; children?: ReactNode }) {
  return (
    <>
      {parts.eyebrow}
      {parts.title}
      {parts.sub}
      {parts.actions}
      {children}
    </>
  )
}

/** One line of a headline split in two, with the accent phrase marked where
 *  the line holds (part of) it — the accent may run across the break. */
function Line({ text, from, accentAt, accentEnd }: { text: string; from: number; accentAt: number; accentEnd: number }) {
  const start = Math.max(accentAt, from) - from
  const end = Math.min(accentEnd, from + text.length) - from
  if (accentAt < 0 || end <= start) return <>{text}</>
  return (
    <>
      {text.slice(0, start)}
      <span className="ls-accent">{text.slice(start, end)}</span>
      {text.slice(end)}
    </>
  )
}

export function Cover({
  variant,
  parts,
  image,
  pictures,
  ctx,
  t,
}: {
  variant: string
  parts: HeroParts
  image?: Pic
  pictures: Pic[]
  ctx: CoverContext
  t: Words
}) {
  const lead = image || pictures[0]
  if (!lead) return null
  const others = pictures.filter((p) => p.url !== lead.url)

  if (variant === 'window') {
    const headline = parts.headline.trim()
    let [first, second] = splitHeadline(headline, parts.accent)
    // One word over the picture and the rest below it reads as a broken page
    // ("Kansa," | photo | "brass, copper and clay for your kitchen"): the
    // window's two lines are balanced by words, the accent marked where it falls.
    if (second && Math.min(first.length, second.length) < Math.max(first.length, second.length) * 0.45) {
      ;[first, second] = balanceWords(headline)
    }
    const secondAt = second ? headline.indexOf(second, Math.max(0, first.length - 1)) : -1
    const accentAt = parts.accent ? headline.indexOf(parts.accent.trim()) : -1
    const accentEnd = accentAt >= 0 ? accentAt + parts.accent.trim().length : -1
    const longest = Math.max(6, first.length, second.length)
    return (
      <section className="ls-hero fx-cover fx-window" data-scene="" style={{ '--line-len': longest } as Vars}>
        <div className="fx-window__stage">
          <div className="fx-window__inner">
            {parts.eyebrow}
            <h1 className="ls-hero__headline fx-window__title">
              <span className="fx-window__line fx-window__line--a">
                <span data-split="">
                  <Line text={first} from={0} accentAt={accentAt} accentEnd={accentEnd} />
                </span>
              </span>
              <span className="fx-window__pane" aria-hidden="true">
                <Photo pic={lead} eager decorative living sizes="(min-width: 901px) 1240px, 100vw" />
              </span>
              {second ? (
                <span className="fx-window__line fx-window__line--b">
                  <span data-split="">
                    <Line text={second} from={secondAt} accentAt={accentAt} accentEnd={accentEnd} />
                  </span>
                </span>
              ) : null}
            </h1>
            <div className="fx-window__foot">
              {parts.sub}
              {parts.actions}
            </div>
          </div>
        </div>
      </section>
    )
  }

  if (variant === 'gallery') {
    const [b, c] = others
    return (
      <section className="ls-hero fx-cover fx-gallery" data-progress="">
        <div className="fx-gallery__grid">
          <div className="ls-hero__inner fx-cover__copy fx-gallery__copy">
            <CoverCopy parts={parts} />
          </div>
          <figure className="fx-gallery__pic fx-gallery__pic--a" data-reveal="mask">
            <Photo pic={lead} eager living sizes="(min-width: 901px) 40vw, 72vw" />
          </figure>
          {b ? (
            <figure
              className="fx-gallery__pic fx-gallery__pic--b"
              data-reveal="mask"
              data-parallax=""
              style={{ '--speed': 0.2 } as Vars}
              aria-hidden="true"
            >
              <Photo pic={b} decorative sizes="(min-width: 901px) 26vw, 52vw" />
            </figure>
          ) : null}
          {c ? (
            <figure
              className="fx-gallery__pic fx-gallery__pic--c"
              data-reveal="mask"
              data-parallax=""
              style={{ '--speed': 0.42 } as Vars}
              aria-hidden="true"
            >
              <Photo pic={c} decorative sizes="(min-width: 901px) 20vw, 40vw" />
            </figure>
          ) : null}
        </div>
      </section>
    )
  }

  if (variant === 'ledger') {
    const phone = ctx.place?.phone
    const facts: { label: string; value: string; href?: string }[] = []
    if (ctx.place?.hours_summary) facts.push({ label: t('Hours'), value: ctx.place.hours_summary })
    if (ctx.place?.address) facts.push({ label: t('Address'), value: ctx.place.address })
    if (phone) facts.push({ label: t('Phone'), value: phone, href: `tel:${phone.replace(/[^\d+]/g, '')}` })
    return (
      <section className="ls-hero fx-cover fx-ledger">
        <div className={`fx-ledger__grid fx-ledger__grid--${facts.length}`} data-reveal="fade">
          <div className="fx-ledger__cell fx-ledger__head" style={{ '--c': 0 } as Vars}>
            {parts.eyebrow}
            {parts.title}
          </div>
          <div className="fx-ledger__cell fx-ledger__pic" style={{ '--c': 1 } as Vars}>
            <figure className="fx-ledger__photo" data-reveal="mask">
              <Photo pic={lead} eager living sizes="(min-width: 901px) 42vw, 100vw" />
            </figure>
          </div>
          <div className="fx-ledger__cell fx-ledger__lede" style={{ '--c': 2 } as Vars}>
            {parts.sub}
            {parts.actions}
          </div>
          {facts.map((fact, i) => (
            <div key={fact.label} className="fx-ledger__cell fx-ledger__fact" style={{ '--c': 3 + i } as Vars}>
              <span className="fx-ledger__idx">{String(i + 1).padStart(2, '0')}</span>
              <span className="fx-ledger__label">{fact.label}</span>
              {fact.href ? (
                <a className="fx-ledger__value" href={fact.href}>
                  {fact.value}
                </a>
              ) : (
                <span className="fx-ledger__value">{fact.value}</span>
              )}
            </div>
          ))}
        </div>
      </section>
    )
  }

  if (variant === 'signature') {
    const list = (ctx.signatures || []).slice(0, 4)
    return (
      <section className="ls-hero fx-cover fx-signature" data-progress="">
        <figure className="fx-signature__pic">
          <Photo pic={lead} eager living sizes="(min-width: 901px) 58vw, 100vw" />
        </figure>
        <div className="fx-signature__panel">
          <div className="ls-hero__inner fx-cover__copy">
            <CoverCopy parts={parts} />
          </div>
          <ol className="fx-signature__list" data-reveal-group="">
            {list.map((dish) => (
              <li key={dish.name}>
                <span className="fx-signature__name">{dish.name}</span>
                <span className="fx-signature__dots" aria-hidden="true" />
                <span className="fx-signature__price">
                  {dish.price}
                  {dish.unit ? <small>{dish.unit}</small> : null}
                </span>
              </li>
            ))}
          </ol>
          {ctx.more ? (
            <a className="fx-signature__more" href={ctx.more.href}>
              {ctx.more.label}
            </a>
          ) : null}
        </div>
      </section>
    )
  }

  if (variant === 'stage') {
    return (
      <section className="ls-hero fx-cover fx-stage" data-progress="">
        <div className="ls-hero__inner fx-stage__copy">
          {parts.eyebrow}
          {parts.title}
          <div className="fx-stage__foot">
            {parts.sub}
            {parts.actions}
          </div>
        </div>
        <figure className="fx-stage__frame">
          <span className="fx-stage__mat">
            <Photo pic={lead} eager living sizes="(min-width: 901px) 1160px, 94vw" />
          </span>
        </figure>
      </section>
    )
  }

  // arch — and the cover for anything a richer one could not draw.
  const second = others[0]
  return (
    <section className="ls-hero fx-cover fx-arch" data-progress="">
      <div className="fx-arch__inner">
        <div className="ls-hero__inner fx-cover__copy fx-arch__copy">
          <CoverCopy parts={parts} />
        </div>
        <div className="fx-arch__media">
          <span className="fx-arch__line" aria-hidden="true" />
          <figure className="fx-arch__main" data-reveal="mask">
            <Photo pic={lead} eager living sizes="(min-width: 901px) 520px, 88vw" />
          </figure>
          {second ? (
            <figure
              className="fx-arch__second"
              data-reveal="scale"
              data-parallax=""
              style={{ '--speed': 0.35 } as Vars}
              aria-hidden="true"
            >
              <Photo pic={second} decorative sizes="240px" />
            </figure>
          ) : null}
        </div>
      </div>
    </section>
  )
}
