'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { cartStorageKey, fetchPublicOfferings, type CartItem } from '@/lib/checkout-api'
import type { SiteContact } from './SectionRenderer'
import { useWords } from './SiteWords'
import type { Words } from '@/lib/site-words'

/**
 * The things a visitor chooses between — cuts, dishes, plans, projects —
 * presented the way this kind of site browses.
 *
 * Content comes from the owner's own catalogue (names, and prices only where
 * they gave them). Every action is real: a WhatsApp message that names the
 * item, or a call. A basket appears only when ordering is switched on AND the
 * business has live, priced items — then those live items are shown instead,
 * with Add buttons that really add.
 */

type Asset = { url: string; alt_text?: string | null }
type Item = {
  name: string
  category?: string
  description?: string
  price?: string
  unit?: string
  image?: Asset
}
type Category = {
  name: string
  description?: string
  meta?: string
  tags?: string[]
  image?: Asset
}
type Live = {
  id: string
  title: string
  description?: string | null
  price_amount?: number | null
  currency?: string
  image_url?: string | null
  availability?: string | null
}

function money(amount?: number | null, currency?: string) {
  if (amount === null || amount === undefined) return ''
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currency || 'INR',
      maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    }).format(amount)
  } catch {
    return `${currency || 'INR'} ${amount}`
  }
}

function orderHref(contact: SiteContact | undefined, businessName: string, item: string, t: Words) {
  if (contact?.whatsapp) {
    const text = encodeURIComponent(t('Hi {business}, I’d like to order {item}.', { business: businessName, item }))
    return `https://wa.me/${contact.whatsapp.replace(/\D/g, '')}?text=${text}`
  }
  if (contact?.phone) return `tel:${contact.phone}`
  return ''
}

function Price({ item }: { item: Item }) {
  if (!item.price) return null
  return (
    <span className="ls-price">
      <strong>{item.price}</strong>
      {item.unit ? <small>{item.unit}</small> : null}
    </span>
  )
}

function Picture({ image, name, className, plate = name }: { image?: Asset; name: string; className: string; plate?: string }) {
  return (
    <div className={className}>
      {image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={image.url} alt={image.alt_text || name} loading="lazy" />
      ) : (
        // No picture yet (or one that must be a real photo, like a project):
        // a designed plate in the site's own colours — never a giant initial.
        <span className="ls-picture__plate" aria-hidden="true">
          {plate.trim() ? <span>{plate.trim()}</span> : null}
        </span>
      )}
    </div>
  )
}

export function ProductShowcase({
  title,
  subtitle,
  variant,
  items,
  categories,
  filters,
  orderLabel,
  anchor,
  businessSlug,
  businessName,
  contact,
  capabilities,
  alt,
}: {
  title: string
  subtitle?: string
  variant: string
  items: Item[]
  categories: Category[]
  filters: string[]
  orderLabel?: string
  anchor?: string
  businessSlug: string
  businessName: string
  contact?: SiteContact
  capabilities?: Record<string, boolean | string | null>
  alt?: boolean
}) {
  const t = useWords()
  const [active, setActive] = useState('All')
  const [live, setLive] = useState<Live[]>([])
  const [added, setAdded] = useState('')
  const canOrder = Boolean(capabilities?.order)
  // The catalogue is ready: show the business's real items and prices (the
  // Offerings module's public read contract), whether or not ordering is on.
  // The words written into this section at build time are only the fallback
  // for a business with no live catalogue.
  const canBrowse = canOrder || Boolean(capabilities?.catalogue)

  useEffect(() => {
    if (!canBrowse) return
    let gone = false
    fetchPublicOfferings(businessSlug)
      .then((data: { offerings?: Array<Record<string, unknown>> }) => {
        if (gone) return
        const rows = (data?.offerings || [])
          .map((row) => ({
            id: String(row.id || ''),
            title: String(row.title || ''),
            description: (row.description as string) || null,
            price_amount: typeof row.price_amount === 'number' ? row.price_amount : null,
            currency: String(row.currency || 'INR'),
            image_url: typeof row.image_url === 'string' ? row.image_url : null,
            availability: typeof row.availability === 'string' ? row.availability : null,
          }))
          .filter((row) => row.id && row.title && (row.price_amount !== null || !canOrder))
        setLive(rows)
      })
      .catch(() => undefined)
    return () => {
      gone = true
    }
  }, [businessSlug, canOrder, canBrowse])

  const shown = useMemo(
    () => (active === 'All' ? items : items.filter((item) => item.category === active)),
    [active, items]
  )

  function add(row: Live) {
    const key = cartStorageKey(businessSlug)
    let cart: CartItem[] = []
    try {
      cart = JSON.parse(localStorage.getItem(key) || '[]')
    } catch {
      cart = []
    }
    const found = cart.find((line) => line.offering_id === row.id)
    if (found) found.quantity += 1
    else
      cart.push({
        offering_id: row.id,
        title: row.title,
        quantity: 1,
        unit_price: Number(row.price_amount || 0),
        currency: row.currency || 'INR',
      })
    try {
      localStorage.setItem(key, JSON.stringify(cart))
      window.dispatchEvent(new Event('locah-cart'))
    } catch {
      /* storage unavailable — checkout re-reads */
    }
    setAdded(row.title)
  }

  const head = (
    <div className="ls-head ls-head--showcase">
      <h2 className="ls-title">{title}</h2>
      {subtitle ? <p className="ls-sub">{subtitle}</p> : null}
    </div>
  )

  const order = (name: string) => {
    const href = orderHref(contact, businessName, name, t)
    if (!href || !orderLabel) return null
    return (
      <a
        className="ls-btn ls-btn--sm ls-order"
        href={href}
        target={href.startsWith('https') ? '_blank' : undefined}
        rel={href.startsWith('https') ? 'noopener noreferrer' : undefined}
      >
        {t(orderLabel)}
      </a>
    )
  }

  // Real items exist: show them. With ordering on this is a shop.
  if (canBrowse && live.length > 0) {
    return (
      <section id={anchor} className={`ls-section ls-showcase ${alt ? 'ls-section--alt' : ''}`}>
        <div className="ls-inner">
          {head}
          <ul className="ls-shop-grid">
            {live.map((row) => (
              <li key={row.id} className="ls-card ls-card--product">
                {row.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="ls-card__img" src={row.image_url} alt="" loading="lazy" />
                ) : null}
                <div className="ls-card__body">
                  <h3 className="ls-card__title">{row.title}</h3>
                  {row.description ? <p className="ls-card__text">{row.description}</p> : null}
                  {row.availability === 'out_of_stock' ? (
                    <p className="ls-stock ls-stock--out">{t('Out of stock')}</p>
                  ) : row.availability === 'low_stock' ? (
                    <p className="ls-stock ls-stock--low">{t('Only a few left')}</p>
                  ) : null}
                  <div className="ls-card__foot">
                    <span className="ls-price">
                      <strong>{money(row.price_amount, row.currency)}</strong>
                    </span>
                    {canOrder && row.availability !== 'out_of_stock' ? (
                      <button type="button" className="ls-btn ls-btn--sm" onClick={() => add(row)}>
                        + {t('Add')}
                      </button>
                    ) : (
                      order(row.title)
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {added ? (
            <div className="ls-basket-bar" role="status">
              <span>{t('Added {item}', { item: added })}</span>
              <Link className="ls-btn ls-btn--sm" href={`/${businessSlug}/checkout`}>
                {t('View basket')} →
              </Link>
            </div>
          ) : null}
        </div>
      </section>
    )
  }


  const chips =
    filters.length > 1 && variant !== 'category_boards' ? (
      <div className="ls-chips" role="tablist" aria-label={t('Categories')}>
        {['All', ...filters].map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={active === name}
            className="ls-chip"
            onClick={() => setActive(name)}
          >
            {name === 'All' ? t('All') : name}
          </button>
        ))}
      </div>
    ) : null

  if (variant === 'category_boards') {
    return (
      <section
        id={anchor}
        className={`ls-section ls-showcase ls-boards ${alt ? 'ls-section--alt' : ''}`}
      >
        <div className="ls-inner">
          {head}
          <div className="ls-boards__list">
            {categories.map((category, i) => {
              const rows = items.filter((item) => item.category === category.name)
              return (
                <article
                  key={category.name}
                  className={`ls-board ${i % 2 ? 'ls-board--flip' : ''}`}
                >
                  <Picture
                    image={category.image}
                    name={category.name}
                    className="ls-board__media"
                  />
                  <div className="ls-board__body">
                    <div className="ls-board__head">
                      <h3 className="ls-board__title">{category.name}</h3>
                      {category.meta ? (
                        <span className="ls-board__meta">{category.meta}</span>
                      ) : null}
                    </div>
                    {category.description ? (
                      <p className="ls-board__text">{category.description}</p>
                    ) : null}
                    {rows.length > 0 ? (
                      <ul className="ls-board__items">
                        {rows.map((item) => (
                          <li key={item.name} className="ls-board__item">
                            <div>
                              <span className="ls-board__name">{item.name}</span>
                              {item.description ? <small>{item.description}</small> : null}
                            </div>
                            <Price item={item} />
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {order(category.name)}
                  </div>
                </article>
              )
            })}
          </div>
        </div>
      </section>
    )
  }

  if (variant === 'compact_list') {
    const groups = filters.length
      ? filters
      : Array.from(new Set(items.map((i) => i.category || '')))
    return (
      <section
        id={anchor}
        className={`ls-section ls-showcase ls-pricelist ${alt ? 'ls-section--alt' : ''}`}
      >
        <div className="ls-inner">
          {head}
          <div className="ls-pricelist__cols">
            {groups.map((group) => (
              <div key={group} className="ls-pricelist__group">
                {group ? <h3 className="ls-pricelist__title">{group}</h3> : null}
                <ul>
                  {items
                    .filter((item) => (item.category || '') === group)
                    .map((item) => (
                      <li key={item.name} className="ls-pricelist__row">
                        <span className="ls-pricelist__name">{item.name}</span>
                        <span className="ls-pricelist__dots" aria-hidden="true" />
                        <Price item={item} />
                        {item.description ? (
                          <small className="ls-pricelist__desc">{item.description}</small>
                        ) : null}
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>
    )
  }

  // Grids: menu, commerce, projects, plans, services.
  const kind = variant.replace(/_(grid|cards)$/, '')
  // A draft pictures a few items per category, not all of them. The pictured
  // ones are cards; the rest are a clean price list under them — never a
  // photo card next to a letter placeholder.
  const pictured = kind === 'plan' ? [] : shown.filter((item) => item.image)
  const cards = pictured.length > 0 ? pictured : shown
  const rest = pictured.length > 0 ? shown.filter((item) => !item.image) : []
  return (
    <section
      id={anchor}
      className={`ls-section ls-showcase ls-grid-${kind} ${alt ? 'ls-section--alt' : ''}`}
    >
      <div className="ls-inner">
        {head}
        {chips}
        <ul className={`ls-product-grid ls-product-grid--${kind}`} data-count={cards.length}>
          {cards.map((item) => (
            <li key={`${item.category}-${item.name}`} className="ls-card ls-card--product">
              {kind !== 'plan' ? (
                // A project's card already says its name: its plate stays a quiet drawing.
                <Picture image={item.image} name={item.name} className="ls-card__media" plate={kind === 'project' ? '' : item.name} />
              ) : null}
              <div className="ls-card__body">
                {item.category && kind !== 'menu' ? (
                  <span className="ls-card__kicker">{item.category}</span>
                ) : null}
                <div className="ls-card__row">
                  <h3 className="ls-card__title">{item.name}</h3>
                  {kind !== 'plan' ? <Price item={item} /> : null}
                </div>
                {kind === 'plan' ? <Price item={item} /> : null}
                {item.description ? <p className="ls-card__text">{item.description}</p> : null}
                {order(item.name)}
              </div>
            </li>
          ))}
        </ul>
        {rest.length > 0 ? (
          <div className="ls-more">
            <h3 className="ls-more__title">{t('Also available')}</h3>
            <ul className="ls-more__list">
              {rest.map((item) => (
                <li key={`${item.category}-${item.name}`} className="ls-pricelist__row">
                  <span className="ls-pricelist__name">
                    {item.name}
                    {item.category && active === 'All' ? (
                      <small className="ls-more__cat">{item.category}</small>
                    ) : null}
                  </span>
                  <span className="ls-pricelist__dots" aria-hidden="true" />
                  <Price item={item} />
                  {item.description ? (
                    <small className="ls-pricelist__desc">{item.description}</small>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  )
}
