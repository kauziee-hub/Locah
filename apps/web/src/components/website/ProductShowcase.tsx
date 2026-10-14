'use client'

import Link from 'next/link'
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { addToBasket, fetchPublicOfferings } from '@/lib/checkout-api'
import type { SiteContact } from './SectionRenderer'
import { useWords } from './SiteWords'
import type { Words } from '@/lib/site-words'
import { OfferingCard } from './OfferingCard'
import { money as formatMoney, soldOut, type PublicOffering } from './offering-view'

/**
 * The things a visitor chooses between — dishes, cuts, plans, projects,
 * services — presented the way this kind of site browses.
 *
 * Content comes from the owner's own catalogue (names, and prices only where
 * they gave them). Once the business's live catalogue is ready, its real
 * items replace the words written at build time, in the same layout: a menu
 * stays a menu, a rail stays a rail. Every action is real — Add puts the item
 * in the basket (a sheet with its choices opens first when it has packs, cuts
 * or add-ons); otherwise a WhatsApp message that names the item, or a call.
 *
 * Layouts (product_showcase layout_variant):
 *   menu_book        a real menu: chapters by category, a rail that follows,
 *                    diet marks, spice, the owner's tags, prices
 *   rail             a horizontal run of large cards, pinned while it travels
 *   bento            an asymmetric grid, the first thing largest
 *   spotlight        one signature thing per row, large, alternating
 *   stack            cards that stick and stack (plans, services, projects)
 *   category_boards  each category a board with its items
 *   compact_list     a price list in columns
 *   *_grid / *_cards cards with pictures and the rest as a price list
 */

type Asset = { url: string; alt_text?: string | null }
type Item = {
  name: string
  category?: string
  description?: string
  price?: string
  unit?: string
  diet?: string
  spice?: string
  tag?: string
  image?: Asset
  /** A live catalogue item: Add really adds. */
  live?: PublicOffering
}
type Category = {
  name: string
  description?: string
  meta?: string
  tags?: string[]
  image?: Asset
}
type LiveRow = PublicOffering & { category?: string | null }

function orderHref(contact: SiteContact | undefined, businessName: string, item: string, t: Words) {
  if (contact?.whatsapp) {
    const text = encodeURIComponent(t('Hi {business}, I’d like to order {item}.', { business: businessName, item }))
    return `https://wa.me/${contact.whatsapp.replace(/\D/g, '')}?text=${text}`
  }
  if (contact?.phone) return `tel:${contact.phone}`
  return ''
}

function slugify(text: string) {
  return (
    text
      .toLowerCase()
      // Letters in any script (a Tamil chapter name is a fine anchor).
      .replace(/[^\p{L}\p{N}]+/gu, '-')
      .replace(/^-+|-+$/g, '') || 'more'
  )
}

/** "Non-veg", "non veg", "NV" → non_veg; unknown words → nothing. */
function dietKey(value?: string): '' | 'veg' | 'non_veg' | 'egg' | 'vegan' {
  const v = (value || '').toLowerCase().replace(/[^a-z]/g, '')
  if (!v) return ''
  if (v.startsWith('vegan')) return 'vegan'
  if (v.startsWith('non') || v === 'nv' || v === 'nonvegetarian') return 'non_veg'
  if (v.startsWith('egg')) return 'egg'
  if (v.startsWith('veg') || v === 'pureveg') return 'veg'
  return ''
}

function spiceLevel(value?: string): number {
  const v = (value || '').toLowerCase()
  if (!v) return 0
  if (/hot|spicy|high|3/.test(v)) return 3
  if (/medium|2/.test(v)) return 2
  if (/mild|low|1/.test(v)) return 1
  return 0
}

function Diet({ value, t }: { value?: string; t: Words }) {
  const key = dietKey(value)
  if (!key) return null
  const label =
    key === 'veg' ? t('Vegetarian') : key === 'vegan' ? t('Vegan') : key === 'egg' ? t('Contains egg') : t('Non-vegetarian')
  return <span className={`fx-diet fx-diet--${key}`} role="img" aria-label={label} title={label} />
}

function Spice({ value, t }: { value?: string; t: Words }) {
  const level = spiceLevel(value)
  if (!level) return null
  const label = level === 3 ? t('Hot') : level === 2 ? t('Medium spicy') : t('Mild')
  return (
    <span className="fx-spice" role="img" aria-label={label} title={label}>
      {'🌶'.repeat(level)}
    </span>
  )
}

function Price({ item, className = 'ls-price' }: { item: Item; className?: string }) {
  if (!item.price) return null
  return (
    <span className={className}>
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

/** Categories in the owner's order: the ones they named, then any others. */
function chapters(items: Item[], categories: Category[], filters: string[]): string[] {
  const order: string[] = []
  const push = (name?: string) => {
    const key = (name || '').trim()
    if (!order.includes(key)) order.push(key)
  }
  categories.forEach((c) => push(c.name))
  filters.forEach(push)
  items.forEach((i) => push(i.category))
  return order.filter((name) => items.some((i) => (i.category || '').trim() === name))
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
  const [live, setLive] = useState<LiveRow[]>([])
  const [added, setAdded] = useState('')
  const [choosing, setChoosing] = useState<PublicOffering | null>(null)
  const sheet = useRef<HTMLDialogElement>(null)
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
      .then((data: { offerings?: LiveRow[] }) => {
        if (gone) return
        const rows = (data?.offerings || []).filter(
          (row) => row.id && row.title && (typeof row.price_amount === 'number' || !canOrder)
        )
        setLive(rows)
      })
      .catch(() => undefined)
    return () => {
      gone = true
    }
  }, [businessSlug, canOrder, canBrowse])

  useEffect(() => {
    const dialog = sheet.current
    if (!dialog) return
    if (choosing && !dialog.open) dialog.showModal()
    if (!choosing && dialog.open) dialog.close()
  }, [choosing])

  // Live items, in the same shape as the words written at build time — so
  // the layout the site was designed with holds the real catalogue.
  const shownItems: Item[] = useMemo(() => {
    if (!(canBrowse && live.length > 0)) return items
    const pictureByName = new Map(items.map((i) => [i.name.toLowerCase(), i.image]))
    return live.map((row) => {
      const attrs = row.attributes || {}
      const amount = formatMoney(row.packs?.[0]?.price_amount ?? row.price_amount, row.currency)
      return {
        name: row.title,
        category: row.category || undefined,
        description: row.description || undefined,
        price: amount ? (row.packs?.length || row.option_groups?.length ? t('from {price}', { price: amount }) : amount) : undefined,
        diet: typeof attrs.diet === 'string' ? attrs.diet : undefined,
        spice: typeof attrs.spice === 'string' ? attrs.spice : undefined,
        image: row.image_url ? { url: row.image_url, alt_text: row.title } : pictureByName.get(row.title.toLowerCase()),
        live: row,
      }
    })
  }, [canBrowse, live, items, t])
  const liveMode = canBrowse && live.length > 0
  const liveFilters = useMemo(
    () => (liveMode ? chapters(shownItems, categories, []).filter(Boolean) : filters),
    [liveMode, shownItems, categories, filters]
  )

  const shown = useMemo(
    () => (active === 'All' ? shownItems : shownItems.filter((item) => item.category === active)),
    [active, shownItems]
  )

  function quickAdd(row: PublicOffering) {
    addToBasket(businessSlug, {
      offering_id: row.id,
      title: row.title,
      quantity: 1,
      unit_price: Number(row.price_amount || 0),
      currency: row.currency || 'INR',
    })
    window.dispatchEvent(new Event('locah-cart'))
    setAdded(row.title)
  }

  /** The one thing a visitor can do with this item, right now. */
  function action(item: Item, small = true): ReactNode {
    const size = small ? 'ls-btn ls-btn--sm' : 'ls-btn'
    const row = item.live
    if (row && canOrder && (row.kind?.flow ?? 'cart') === 'cart') {
      if (soldOut(row)) return <span className="ls-stock ls-stock--out">{t('Out of stock')}</span>
      const chooses = Boolean(row.packs?.length || row.option_groups?.length || (row.variants?.length ?? 0) > 0)
      return (
        <button
          type="button"
          className={`${size} ls-order`}
          onClick={() => (chooses ? setChoosing(row) : quickAdd(row))}
        >
          {chooses ? t('Choose') : `+ ${t('Add')}`}
        </button>
      )
    }
    const href = orderHref(contact, businessName, item.name, t)
    if (!href || !orderLabel) return null
    return (
      <a
        className={`${size} ls-order`}
        href={href}
        target={href.startsWith('https') ? '_blank' : undefined}
        rel={href.startsWith('https') ? 'noopener noreferrer' : undefined}
      >
        {t(orderLabel)}
      </a>
    )
  }

  const head = (
    <div className="ls-head ls-head--showcase">
      <h2 className="ls-title">{title}</h2>
      {subtitle ? <p className="ls-sub">{subtitle}</p> : null}
    </div>
  )

  const basket = added ? (
    <div className="ls-basket-bar" role="status">
      <span>{t('Added {item}', { item: added })}</span>
      <Link className="ls-btn ls-btn--sm" href={`/${businessSlug}/checkout`}>
        {t('View basket')} →
      </Link>
    </div>
  ) : null

  const chooser = (
    <dialog
      ref={sheet}
      className="ls-sheet"
      onClose={() => setChoosing(null)}
      onClick={(event) => {
        if (event.target === sheet.current) setChoosing(null)
      }}
    >
      {choosing ? (
        <div className="ls-sheet__body">
          <button type="button" className="ls-sheet__close" onClick={() => setChoosing(null)} aria-label={t('Close')}>
            ×
          </button>
          <OfferingCard
            o={choosing}
            slug={businessSlug}
            canOrder={canOrder}
            canBook={Boolean(capabilities?.book)}
            canEnquire={Boolean(capabilities?.enquire)}
            onAdded={() => {
              setAdded(choosing.title)
              setChoosing(null)
            }}
          />
        </div>
      ) : null}
    </dialog>
  )

  const chips =
    liveFilters.length > 1 && !['category_boards', 'menu_book', 'stack', 'spotlight'].includes(variant) ? (
      <div className="ls-chips" role="tablist" aria-label={t('Categories')}>
        {['All', ...liveFilters].map((name) => (
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

  const ground = alt ? 'ls-section--alt' : ''

  /* ------------------------------------------------------------ menu_book */
  if (variant === 'menu_book') {
    return (
      <MenuBook
        anchor={anchor}
        ground={ground}
        title={title}
        subtitle={subtitle}
        items={shownItems}
        categories={categories}
        filters={liveFilters}
        action={action}
        t={t}
      >
        {basket}
        {chooser}
      </MenuBook>
    )
  }

  /* ----------------------------------------------------------------- rail */
  if (variant === 'rail') {
    // The pictured things ride the rail; the rest wait underneath as a list,
    // never a picture card beside an empty one.
    const pictured = shown.filter((item) => item.image)
    const riding = pictured.length >= 3 ? pictured : shown
    const waiting = pictured.length >= 3 ? shown.filter((item) => !item.image) : []
    return (
      <section id={anchor} className={`ls-section fx-rail ${ground}`} data-rail="">
        <div className="fx-rail__stage">
          <div className="fx-rail__head">
            {head}
            <span className="fx-rail__count" aria-hidden="true">
              {String(riding.length).padStart(2, '0')}
            </span>
          </div>
          {chips ? <div className="fx-rail__head">{chips}</div> : null}
          <div className="fx-rail__track" data-rail-track="">
            <ul className="fx-rail__list" data-reveal-group="">
              {riding.map((item, i) => (
                <li key={`${item.category}-${item.name}`} className="fx-rail__card" data-tilt="">
                  <span className="fx-rail__index">{String(i + 1).padStart(2, '0')}</span>
                  <Picture image={item.image} name={item.name} className="fx-rail__media" />
                  <div className="fx-rail__body">
                    {item.category ? <span className="fx-rail__kicker">{item.category}</span> : null}
                    <div className="fx-rail__row">
                      <h3>
                        {item.name} <Diet value={item.diet} t={t} />
                      </h3>
                      <Price item={item} />
                    </div>
                    {item.description ? <p>{item.description}</p> : null}
                    <div>{action(item)}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="fx-rail__bar" aria-hidden="true">
            <span />
          </div>
          {basket}
        </div>
        {waiting.length ? (
          <div className="ls-inner fx-rail__rest">
            <RestList items={waiting} t={t} showCategory={active === 'All'} action={action} />
          </div>
        ) : null}
        {chooser}
      </section>
    )
  }

  /* ---------------------------------------------------------------- bento */
  if (variant === 'bento') {
    // The largest cell is always a picture when there is one to give it.
    const ordered = [...shown.filter((item) => item.image), ...shown.filter((item) => !item.image)]
    return (
      <section id={anchor} className={`ls-section ${ground}`}>
        <div className="ls-inner">
          {head}
          {chips}
          <ul className="fx-bento" data-reveal-group="">
            {ordered.slice(0, 10).map((item) => (
              <li
                key={`${item.category}-${item.name}`}
                className={`fx-bento__cell ${item.image ? 'fx-bento__cell--pic' : ''}`}
                data-tilt=""
              >
                {item.image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.image.url} alt={item.image.alt_text || item.name} loading="lazy" />
                ) : null}
                <div className="fx-bento__copy">
                  {item.tag ? <span className="fx-tag">{item.tag}</span> : null}
                  <h3>
                    {item.name} <Diet value={item.diet} t={t} />
                  </h3>
                  {item.description ? <p>{item.description}</p> : null}
                  <div className="fx-bento__foot">
                    <Price item={item} />
                    {action(item)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {ordered.length > 10 ? (
            <RestList items={ordered.slice(10)} t={t} showCategory={active === 'All'} action={action} />
          ) : null}
          {basket}
        </div>
        {chooser}
      </section>
    )
  }

  /* ------------------------------------------------------------ spotlight */
  if (variant === 'spotlight') {
    const lead = shown.filter((item) => item.image).slice(0, 4)
    const featured = lead.length ? lead : shown.slice(0, 4)
    const rest = shown.filter((item) => !featured.includes(item))
    return (
      <section id={anchor} className={`ls-section ${ground}`}>
        <div className="ls-inner">
          {head}
          <div className="fx-spot">
            {featured.map((item, i) => (
              <article key={`${item.category}-${item.name}`} className="fx-spot__row" data-progress="">
                <figure className="fx-spot__media" data-reveal="mask">
                  {item.image ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.image.url} alt={item.image.alt_text || item.name} loading="lazy" />
                  ) : (
                    <span className="ls-picture__plate" aria-hidden="true">
                      <span>{item.name}</span>
                    </span>
                  )}
                </figure>
                <div className="fx-spot__copy" data-reveal="">
                  <span className="fx-spot__num" aria-hidden="true">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  {item.category ? <span className="fx-rail__kicker">{item.category}</span> : null}
                  <h3>
                    {item.name} <Diet value={item.diet} t={t} />
                  </h3>
                  {item.description ? <p>{item.description}</p> : null}
                  <div className="fx-spot__foot">
                    <Price item={item} />
                    {action(item, false)}
                  </div>
                </div>
              </article>
            ))}
          </div>
          {rest.length ? <RestList items={rest} t={t} showCategory /> : null}
          {basket}
        </div>
        {chooser}
      </section>
    )
  }

  /* ---------------------------------------------------------------- stack */
  if (variant === 'stack') {
    const cards = shown.slice(0, 8)
    const rest = shown.slice(8)
    return (
      <section id={anchor} className={`ls-section ${ground}`}>
        <div className="ls-inner">
          {head}
          <ol className="fx-stack" data-scene="" style={{ '--n': cards.length } as CSSProperties}>
            {cards.map((item, i) => (
              <li key={`${item.category}-${item.name}`} className="fx-stack__card" style={{ '--i': i } as CSSProperties}>
                <div className="fx-stack__body">
                  <div>
                    <span className="fx-stack__kicker">
                      {String(i + 1).padStart(2, '0')}
                      {item.category ? ` · ${item.category}` : ''}
                    </span>
                    <h3>{item.name}</h3>
                  </div>
                  {item.description ? <p>{item.description}</p> : null}
                  <div className="fx-spot__foot">
                    <Price item={item} className="ls-price fx-stack__price" />
                    {action(item, false)}
                  </div>
                </div>
                {item.image ? (
                  <div className="fx-stack__media">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={item.image.url} alt={item.image.alt_text || item.name} loading="lazy" />
                  </div>
                ) : (
                  <div className="fx-stack__big" aria-hidden="true">
                    {String(i + 1).padStart(2, '0')}
                  </div>
                )}
              </li>
            ))}
          </ol>
          {rest.length ? <RestList items={rest} t={t} showCategory /> : null}
          {basket}
        </div>
        {chooser}
      </section>
    )
  }

  /* ------------------------------------------------------ category_boards */
  if (variant === 'category_boards') {
    const boards = categories.length
      ? categories
      : chapters(shownItems, [], liveFilters).map((name) => ({ name }) as Category)
    return (
      <section id={anchor} className={`ls-section ls-showcase ls-boards ${ground}`}>
        <div className="ls-inner">
          {head}
          <div className="ls-boards__list">
            {boards.map((category, i) => {
              const rows = shownItems.filter((item) => item.category === category.name)
              return (
                <article
                  key={category.name}
                  className={`ls-board ${i % 2 ? 'ls-board--flip' : ''}`}
                  data-reveal=""
                >
                  <Picture image={category.image} name={category.name} className="ls-board__media" />
                  <div className="ls-board__body">
                    <div className="ls-board__head">
                      <h3 className="ls-board__title">{category.name}</h3>
                      {category.meta ? <span className="ls-board__meta">{category.meta}</span> : null}
                    </div>
                    {category.description ? <p className="ls-board__text">{category.description}</p> : null}
                    {rows.length > 0 ? (
                      <ul className="ls-board__items">
                        {rows.map((item) => (
                          <li key={item.name} className="ls-board__item">
                            <div>
                              <span className="ls-board__name">
                                {item.name} <Diet value={item.diet} t={t} />
                              </span>
                              {item.description ? <small>{item.description}</small> : null}
                            </div>
                            <Price item={item} />
                            {item.live ? action(item) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {rows.some((r) => r.live) ? null : action({ name: category.name })}
                  </div>
                </article>
              )
            })}
          </div>
          {basket}
        </div>
        {chooser}
      </section>
    )
  }

  /* --------------------------------------------------------- compact_list */
  if (variant === 'compact_list') {
    const groups = liveFilters.length ? liveFilters : Array.from(new Set(shownItems.map((i) => i.category || '')))
    return (
      <section id={anchor} className={`ls-section ls-showcase ls-pricelist ${ground}`}>
        <div className="ls-inner">
          {head}
          <div className="ls-pricelist__cols" data-reveal-group="">
            {groups.map((group) => (
              <div key={group} className="ls-pricelist__group">
                {group ? <h3 className="ls-pricelist__title">{group}</h3> : null}
                <ul>
                  {shownItems
                    .filter((item) => (item.category || '') === group)
                    .map((item) => (
                      <li key={item.name} className="ls-pricelist__row">
                        <span className="ls-pricelist__name">
                          {item.name} <Diet value={item.diet} t={t} />
                        </span>
                        <span className="ls-pricelist__dots" aria-hidden="true" />
                        <Price item={item} />
                        {item.description ? <small className="ls-pricelist__desc">{item.description}</small> : null}
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </div>
          {basket}
        </div>
        {chooser}
      </section>
    )
  }

  /* ---------------------------------- grids: menu, commerce, projects, plans */
  const kind = variant.replace(/_(grid|cards)$/, '')
  // A draft pictures a few items per category, not all of them. The pictured
  // ones are cards; the rest are a clean price list under them — never a
  // photo card next to a letter placeholder.
  const pictured = kind === 'plan' ? [] : shown.filter((item) => item.image)
  const cards = pictured.length > 0 ? pictured : shown
  const rest = pictured.length > 0 ? shown.filter((item) => !item.image) : []
  return (
    <section id={anchor} className={`ls-section ls-showcase ls-grid-${kind} ${ground}`}>
      <div className="ls-inner">
        {head}
        {chips}
        <ul className={`ls-product-grid ls-product-grid--${kind}`} data-count={cards.length} data-reveal-group="">
          {cards.map((item) => (
            <li key={`${item.category}-${item.name}`} className="ls-card ls-card--product" data-tilt="">
              {kind !== 'plan' ? (
                // A project's card already says its name: its plate stays a quiet drawing.
                <Picture
                  image={item.image}
                  name={item.name}
                  className="ls-card__media"
                  plate={kind === 'project' ? '' : item.name}
                />
              ) : null}
              <div className="ls-card__body">
                {item.category && kind !== 'menu' ? <span className="ls-card__kicker">{item.category}</span> : null}
                <div className="ls-card__row">
                  <h3 className="ls-card__title">
                    {item.name} <Diet value={item.diet} t={t} />
                  </h3>
                  {kind !== 'plan' ? <Price item={item} /> : null}
                </div>
                {kind === 'plan' ? <Price item={item} /> : null}
                {item.description ? <p className="ls-card__text">{item.description}</p> : null}
                {action(item)}
              </div>
            </li>
          ))}
        </ul>
        {rest.length > 0 ? <RestList items={rest} t={t} showCategory={active === 'All'} action={action} /> : null}
        {basket}
      </div>
      {chooser}
    </section>
  )
}

/** The rest of a range, as a clean price list under the pictured cards. */
function RestList({
  items,
  t,
  showCategory,
  action,
}: {
  items: Item[]
  t: Words
  showCategory: boolean
  action?: (item: Item) => ReactNode
}) {
  return (
    <div className="ls-more">
      <h3 className="ls-more__title">{t('Also available')}</h3>
      <ul className="ls-more__list" data-reveal-group="">
        {items.map((item) => (
          <li key={`${item.category}-${item.name}`} className="ls-pricelist__row">
            <span className="ls-pricelist__name">
              {item.name} <Diet value={item.diet} t={t} />
              {item.category && showCategory ? <small className="ls-more__cat">{item.category}</small> : null}
            </span>
            <span className="ls-pricelist__dots" aria-hidden="true" />
            <Price item={item} />
            {item.description ? <small className="ls-pricelist__desc">{item.description}</small> : null}
            {item.live && action ? action(item) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

function MenuAction({ children }: { children: ReactNode }) {
  return children ? <div className="fx-menu__act">{children}</div> : null
}

/**
 * A real menu. Each category a chapter (with its picture where there is one),
 * a rail of chapters that follows the reader and shows where they are, and
 * every dish with what a diner looks for: veg or not, how hot, the owner's own
 * tag ("Bestseller"), the price, and how to order it.
 */
function MenuBook({
  anchor,
  ground,
  title,
  subtitle,
  items,
  categories,
  filters,
  action,
  t,
  children,
}: {
  anchor?: string
  ground: string
  title: string
  subtitle?: string
  items: Item[]
  categories: Category[]
  filters: string[]
  action: (item: Item) => ReactNode
  t: Words
  children: ReactNode
}) {
  const names = chapters(items, categories, filters)
  const prefix = slugify(anchor || 'menu')
  const ids = names.map((name) => `${prefix}-${slugify(name || title)}`)
  const [current, setCurrent] = useState(ids[0] || '')
  const diets = new Set(items.map((i) => dietKey(i.diet)).filter(Boolean))

  useEffect(() => {
    const seen = new Map<string, boolean>()
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) seen.set(entry.target.id, entry.isIntersecting)
        const first = ids.find((id) => seen.get(id))
        if (first) setCurrent(first)
      },
      { rootMargin: '-30% 0px -55% 0px' }
    )
    ids.forEach((id) => {
      const el = document.getElementById(id)
      if (el) io.observe(el)
    })
    return () => io.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join('|')])

  const categoryInfo = new Map(categories.map((c) => [c.name.trim(), c]))
  return (
    <section id={anchor} className={`ls-section fx-menu ${ground}`}>
      <div className="fx-menu__layout">
        <header className="fx-menu__head">
          <div>
            <p className="ls-eyebrow" data-reveal="fade">
              {t('Menu')}
            </p>
            <h2 className="ls-title">{title}</h2>
            {subtitle ? <p className="ls-sub">{subtitle}</p> : null}
          </div>
          {diets.size ? (
            <p className="fx-menu__legend">
              {diets.has('veg') || diets.has('vegan') ? (
                <span>
                  <Diet value="veg" t={t} /> {t('Vegetarian')}
                </span>
              ) : null}
              {diets.has('egg') ? (
                <span>
                  <Diet value="egg" t={t} /> {t('Contains egg')}
                </span>
              ) : null}
              {diets.has('non_veg') ? (
                <span>
                  <Diet value="non_veg" t={t} /> {t('Non-vegetarian')}
                </span>
              ) : null}
            </p>
          ) : null}
        </header>
        {names.length > 1 ? (
          <nav className="fx-menu__rail" aria-label={t('Categories')}>
            {names.map((name, i) => (
              <a key={ids[i]} href={`#${ids[i]}`} aria-current={current === ids[i] ? 'true' : undefined}>
                {name || t('More')}
                <small>{items.filter((it) => (it.category || '').trim() === name).length}</small>
              </a>
            ))}
          </nav>
        ) : null}
        <div className="fx-menu__chapters" style={names.length > 1 ? undefined : { gridColumn: '1 / -1' }}>
          {names.map((name, n) => {
            const info = categoryInfo.get(name)
            const rows = items.filter((it) => (it.category || '').trim() === name)
            return (
              <section key={ids[n]} id={ids[n]} className="fx-menu__chapter" aria-label={name || title}>
                {names.length > 1 || name ? (
                  <div className="fx-menu__chapter-head">
                    <span className="fx-menu__num">{String(n + 1).padStart(2, '0')}</span>
                    <h3>{name || t('More')}</h3>
                    {info?.description ? <p>{info.description}</p> : null}
                    {info?.image ? (
                      <div className="fx-menu__banner" data-reveal="mask">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={info.image.url} alt={info.image.alt_text || name} loading="lazy" />
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <ul className="fx-menu__items" data-reveal-group="">
                  {rows.map((item) => (
                    <li
                      key={item.name}
                      className={`fx-menu__item ${item.image ? '' : 'fx-menu__item--plain'}`}
                    >
                      {item.image ? (
                        <div className="fx-menu__thumb">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={item.image.url} alt={item.image.alt_text || item.name} loading="lazy" />
                        </div>
                      ) : null}
                      <h4 className="fx-menu__name">
                        <Diet value={item.diet} t={t} />
                        {item.name}
                        <Spice value={item.spice} t={t} />
                        {item.tag ? <span className="fx-tag">{item.tag}</span> : null}
                      </h4>
                      <span className="fx-menu__price">
                        {item.price || ''}
                        {item.price && item.unit ? <small>{item.unit}</small> : null}
                      </span>
                      {item.description ? <p className="fx-menu__desc">{item.description}</p> : null}
                      <MenuAction>{action(item)}</MenuAction>
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      </div>
      {children}
    </section>
  )
}
