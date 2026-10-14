import type { CSSProperties } from 'react'
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
}

export function StorySection({ variant, anchor, eyebrow, title, body, quote, image, pictures, alt }: StoryProps) {
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
              <img src={image.url} alt={image.alt_text || title} loading="lazy" />
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
              <img src={image.url} alt={image.alt_text || title} loading="lazy" />
            </figure>
            {others.map((pic, i) => (
              <figure
                key={pic.url}
                className={`fx-collage__pic fx-collage__pic--${i + 1}`}
                data-parallax=""
                aria-hidden="true"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={pic.url} alt="" loading="lazy" />
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
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image.url} alt={image.alt_text || title} loading="lazy" />
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
