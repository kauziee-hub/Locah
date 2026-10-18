import type { CSSProperties } from 'react'
import { srcSetFor } from '../picture'
import { Dissolve } from './gl/GlDissolve'
import type { Pic } from './HeroScenes'

/**
 * The owner's story, told three more ways (about layout_variant):
 *
 *   word_reveal   set large, each word lit as the visitor reads down the page
 *   sticky_split  the picture holds while the story scrolls beside it
 *   collage       the story beside pictures overlapping at different depths
 *
 * Words are always the owner's (or governed copy); pictures are the
 * section's own and, for a collage, others already on the page.
 */

type StoryProps = {
  variant: string
  anchor?: string
  eyebrow: string
  title: string
  body: string
  quote: string
  image?: Pic
  pictures: Pic[]
  alt: boolean
  /** The site's design DNA drew `dissolve`: the held picture turns. */
  dissolve?: boolean
}

/**
 * A story's one held photograph — or, on a site whose design DNA drew the
 * `dissolve` moment, that photograph becoming another of the business's own
 * as the story is read (./gl/GlDissolve; a crossfade without GL). The second
 * is not the cover's picture when the page has any other.
 */
export function HeldPicture({
  image,
  pictures,
  alt,
  dissolve = false,
  sizes,
}: {
  image: Pic
  pictures: Pic[]
  alt: string
  dissolve?: boolean
  sizes?: string
}) {
  const others = dissolve ? pictures.filter((p) => p.url !== image.url) : []
  const second = others.find((p) => p.url !== pictures[0]?.url) || others[0]
  if (second) return <Dissolve from={{ ...image, alt_text: image.alt_text || alt }} to={second} sizes={sizes} range={[0.35, 0.75]} />
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={image.url} srcSet={srcSetFor(image.url)} sizes={sizes} alt={image.alt_text || alt} loading="lazy" />
}

export function StorySection({ variant, anchor, eyebrow, title, body, quote, image, pictures, alt, dissolve }: StoryProps) {
  const ground = alt ? 'ls-section--alt' : ''
  if (variant === 'word_reveal') {
    return (
      <section id={anchor} className={`ls-section fx-read ${ground}`} data-progress="">
        <div className="fx-read__inner">
          <p className="ls-eyebrow" data-reveal="">
            {eyebrow}
          </p>
          {title ? (
            <h2 className="ls-title" data-split="">
              {title}
            </h2>
          ) : null}
          <p className="fx-read__text" data-split="read">
            {body}
          </p>
          {quote ? (
            <blockquote className="fx-read__quote" data-reveal="">
              {quote}
            </blockquote>
          ) : null}
          {image ? (
            <figure className="fx-read__figure" data-reveal="mask">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={image.url} srcSet={srcSetFor(image.url)} alt={image.alt_text || title} loading="lazy" />
            </figure>
          ) : null}
        </div>
      </section>
    )
  }

  if (variant === 'collage' && image) {
    const others = pictures.filter((p) => p.url !== image.url).slice(0, 2)
    return (
      <section id={anchor} className={`ls-section ${ground}`}>
        <div className="fx-collage">
          <div className="fx-collage__stage">
            <figure className="fx-collage__pic fx-collage__pic--0" data-reveal="mask">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={image.url} srcSet={srcSetFor(image.url)} alt={image.alt_text || title} loading="lazy" />
            </figure>
            {others.map((pic, i) => (
              <figure
                key={pic.url}
                className={`fx-collage__pic fx-collage__pic--${i + 1}`}
                data-parallax=""
                aria-hidden="true"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={pic.url} srcSet={srcSetFor(pic.url)} alt="" loading="lazy" />
              </figure>
            ))}
          </div>
          <div className="fx-sticky__copy">
            <p className="ls-eyebrow" data-reveal="">
              {eyebrow}
            </p>
            <h2 className="ls-title" data-split="">
              {title}
            </h2>
            <p className="ls-about__body" data-reveal="">
              {body}
            </p>
            {quote ? (
              <blockquote className="fx-sticky__quote" data-reveal="">
                {quote}
              </blockquote>
            ) : null}
          </div>
        </div>
      </section>
    )
  }

  // sticky_split — and the floor for a collage without a picture.
  return (
    <section id={anchor} className={`ls-section ${ground}`} data-progress="">
      <div className="fx-sticky" style={image ? undefined : ({ gridTemplateColumns: '1fr' } as CSSProperties)}>
        {image ? (
          <figure className="fx-sticky__media" data-reveal="mask">
            <HeldPicture image={image} pictures={pictures} alt={title} dissolve={dissolve} sizes="(min-width: 901px) 46vw, 100vw" />
          </figure>
        ) : null}
        <div className="fx-sticky__copy">
          <p className="ls-eyebrow" data-reveal="">
            {eyebrow}
          </p>
          <h2 className="ls-title" data-split="">
            {title}
          </h2>
          {body.split(/\n{2,}/).map((para, i) => (
            <p key={i} className="ls-about__body" data-reveal="">
              {para}
            </p>
          ))}
          {quote ? (
            <blockquote className="fx-sticky__quote" data-reveal="">
              {quote}
            </blockquote>
          ) : null}
        </div>
      </div>
    </section>
  )
}
