'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { addToBasket, fetchPublicOfferings, fetchPublicPlans } from '@/lib/checkout-api'
import { OfferingCard } from './OfferingCard'
import { StockNote, soldOut, type PublicOffering } from './offering-view'
import { useWords } from './SiteWords'
import type { Words } from '@/lib/site-words'

/**
 * The live-record renderer behind every "list" section type.
 *
 * Doc 12 §11.1 list sections (offerings_list, menu_section, plans_section,
 * rooms_section, classes_section) all read the SAME underlying record — the
 * business's Offerings — and differ only in how they present them and which
 * `offering_type` they filter to. Keeping one fetch + one component means a
 * restaurant's Menu, a gym's Plans and a hotel's Rooms can never drift apart
 * or disagree about price formatting.
 *
 * `kind` chooses the presentation. `offeringTypes` filters the records.
 */

export type ItemKind = 'offerings' | 'menu' | 'plans' | 'rooms' | 'classes'

type Offering = PublicOffering & { category?: string | null; plan?: boolean; period_days?: number | null }

/** An item that needs choosing (pack, cut, add-ons, size) or is not a cart item. */
function needsCard(o: Offering) {
  const flow = o.kind?.flow ?? 'cart'
  return flow !== 'cart' || Boolean(o.packs?.length || o.option_groups?.length || o.variants?.length)
}

function money(amount?: number | null, currency?: string) {
  if (amount === null || amount === undefined) return null
  const code = currency || 'INR'
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: code,
      maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    }).format(amount)
  } catch {
    return `${code} ${amount}`
  }
}

/**
 * Action a visitor can take on an item.
 *
 * The section kind proposes; the business's live capabilities dispose. A salon
 * whose Orders module is off was still being given "Add" and "View basket" on
 * its own site, and the basket link led to a 404 — the section type had decided
 * on its own what the business could do. Where the proposed action is not backed
 * by a live module the item is simply shown, which is the honest outcome: the
 * price and description are real even when there is nothing to click.
 *
 * `capabilities` absent means unknown, and unknown is treated as unavailable
 * rather than assumed — an action that silently fails is worse than one that is
 * not offered.
 */
function actionFor(
  kind: ItemKind,
  capabilities?: Record<string, boolean | string | null>
): 'cart' | 'book' | 'enquire' | 'none' {
  const can = (flag: string) => Boolean(capabilities?.[flag])
  if (kind === 'menu' || kind === 'offerings') return can('order') ? 'cart' : 'none'
  if (kind === 'rooms' || kind === 'classes') return can('book') ? 'book' : 'none'
  if (kind === 'plans') return can('enquire') ? 'enquire' : 'none'
  return 'none'
}

export function LiveItemsSection({
  businessSlug,
  kind,
  title,
  subtitle,
  variant,
  maxItems,
  offeringTypes,
  showPrices = true,
  sectionClass,
  altGround,
  capabilities,
  anchor,
}: {
  businessSlug: string
  kind: ItemKind
  title?: string
  subtitle?: string
  variant?: string
  maxItems?: number
  offeringTypes?: string[]
  showPrices?: boolean
  sectionClass?: string
  altGround?: boolean
  capabilities?: Record<string, boolean | string | null>
  anchor?: string
}) {
  const t = useWords()
  const [items, setItems] = useState<Offering[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let live = true
    // Plans come from the Memberships module (active, public plans); a
    // business that only lists plans in its catalogue falls back to those —
    // never to its whole catalogue.
    const load =
      kind === 'plans'
        ? fetchPublicPlans(businessSlug).then(async (plans) =>
            plans.length > 0
              ? plans.map(
                  (p) =>
                    ({
                      id: p.id,
                      title: p.title,
                      description: p.description,
                      price_amount: Number(p.price_amount),
                      currency: p.currency,
                      plan: true,
                      period_days: p.duration_days,
                    }) as Offering
                )
              : (((await fetchPublicOfferings(businessSlug)).offerings || []) as Offering[]).filter(
                  (o) => o.offering_type === 'membership_plan'
                )
          )
        : fetchPublicOfferings(businessSlug).then((data) => ((data.offerings || []) as Offering[]) ?? [])
    load
      .then((rows) => {
        if (!live) return
        setItems(rows)
        setState('ready')
      })
      .catch(() => {
        if (live) setState('error')
      })
    return () => {
      live = false
    }
  }, [businessSlug, kind])

  function addToCart(o: Offering) {
    addToBasket(businessSlug, {
      offering_id: o.id,
      title: o.title,
      quantity: 1,
      unit_price: Number(o.price_amount || 0),
      currency: o.currency || 'INR',
    })
  }

  const filtered = (
    offeringTypes && offeringTypes.length > 0
      ? items.filter((i) => !i.offering_type || offeringTypes.includes(i.offering_type))
      : items
  ).slice(0, maxItems && maxItems > 0 ? maxItems : undefined)

  const action = actionFor(kind, capabilities)

  // A visitor must never see an empty shelf. If the business has no records
  // for this section yet, the section renders nothing at all rather than an
  // apologetic placeholder. The owner is told what to add in the Workspace.
  // A list that cannot load (the catalogue is not switched on yet) is the
  // same empty shelf — it once left a lone heading between two sections.
  if ((state === 'ready' && filtered.length === 0) || state === 'error') return null

  return (
    <section id={anchor} className={`ls-section ${altGround ? 'ls-section--alt' : ''} ${sectionClass || ''}`}>
      <div className="ls-inner">
        {(title || subtitle) && (
          <div
            className={`ls-head ${kind === 'menu' || kind === 'plans' ? 'ls-head--center' : ''}`}
          >
            {title ? <h2 className="ls-title">{title}</h2> : null}
            {subtitle ? <p className="ls-sub">{subtitle}</p> : null}
          </div>
        )}

        {state === 'loading' ? (
          <ItemsSkeleton variant={variant} />
        ) : kind === 'menu' && variant !== 'simple' ? (
          <MenuCategorized
            items={filtered}
            showPrices={showPrices}
            onAdd={addToCart}
            action={action}
            slug={businessSlug}
            capabilities={capabilities}
          />
        ) : kind === 'plans' ? (
          <Plans items={filtered} variant={variant} slug={businessSlug} action={action} />
        ) : kind === 'rooms' && variant !== 'cards' ? (
          <RoomRows items={filtered} slug={businessSlug} action={action} />
        ) : kind === 'classes' && variant !== 'cards' ? (
          <ClassSchedule items={filtered} slug={businessSlug} action={action} />
        ) : (
          <ItemGrid
            items={filtered}
            variant={variant || (kind === 'menu' ? 'list' : 'cards')}
            showPrices={showPrices}
            onAdd={addToCart}
            action={action}
            slug={businessSlug}
            capabilities={capabilities}
          />
        )}

        {action === 'cart' && filtered.length > 0 ? (
          <div style={{ marginTop: '2rem', textAlign: 'center' }}>
            <Link className="ls-btn ls-btn--outline" href={`/${businessSlug}/checkout`}>
              {t('View basket')}
            </Link>
          </div>
        ) : null}
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- pieces */

function ItemAction({
  action,
  item,
  slug,
  onAdd,
}: {
  action: 'cart' | 'book' | 'enquire' | 'none'
  item: Offering
  slug: string
  onAdd: (o: Offering) => void
}) {
  const t = useWords()
  if (action === 'cart' && soldOut(item)) return <span className="ls-stock ls-stock--out">{t('Out of stock')}</span>
  if (action === 'cart')
    return (
      <button type="button" className="ls-btn ls-btn--outline" onClick={() => onAdd(item)}>
        {t('Add')}
      </button>
    )
  if (action === 'book')
    return (
      <Link className="ls-btn" href={`/${slug}/book?offering_id=${item.id}`}>
        {t('Book')}
      </Link>
    )
  if (action === 'enquire')
    return (
      <Link className="ls-btn" href={`/${slug}/enquire?offering_id=${item.id}`}>
        {t('Enquire')}
      </Link>
    )
  return null
}

function ItemGrid({
  items,
  variant,
  showPrices,
  onAdd,
  action,
  slug,
  capabilities,
}: {
  items: Offering[]
  variant: string
  showPrices: boolean
  onAdd: (o: Offering) => void
  action: 'cart' | 'book' | 'enquire' | 'none'
  slug: string
  capabilities?: Record<string, boolean | string | null>
}) {
  const t = useWords()
  const v = variant === 'list' || variant === 'grid' ? variant : 'cards'
  const card = (o: Offering) => (
    <OfferingCard
      key={o.id}
      o={o}
      slug={slug}
      canOrder={Boolean(capabilities?.order)}
      canBook={Boolean(capabilities?.book)}
      canEnquire={Boolean(capabilities?.enquire)}
    />
  )
  // Property projects read as the Capability Universe §19.2 Projects section:
  // tabs by status, e.g. Upcoming · Live · Completed.
  const projects = items.filter((o) => o.offering_type === 'property_project')
  if (projects.length > 0 && projects.length === items.length) return <ProjectTabs items={projects} render={card} />
  if (v !== 'list') return <div className={`ls-items ls-items--${v}`}>{items.map(card)}</div>
  return (
    <div className={`ls-items ls-items--${v}`}>
      {items.map((o) => {
        if (needsCard(o)) return card(o)
        const price = showPrices ? money(o.price_amount, o.currency) : null
        return (
          <article key={o.id} className="ls-item">
            <div className="ls-item__body">
              <div className="ls-item__text">
                <h3 className="ls-item__title">{o.title}</h3>
                {o.description ? <p className="ls-item__desc">{o.description}</p> : null}
                {o.availability === 'low_stock' ? <StockNote o={o} t={t} /> : null}
              </div>
              <span className="ls-item__leader" aria-hidden="true" />
              <div className="ls-item__foot">
                {price ? <span className="ls-price">{price}</span> : null}
                <ItemAction action={action} item={o} slug={slug} onAdd={onAdd} />
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )
}

const PROJECT_ORDER = ['Upcoming', 'Launching', 'Live', 'Sold out', 'Completed', 'On hold']

function ProjectTabs({ items, render }: { items: Offering[]; render: (o: Offering) => JSX.Element }) {
  const t = useWords()
  const statusOf = (o: Offering) => String(o.attributes?.project_status ?? 'Live')
  const tabs = PROJECT_ORDER.filter((s) => items.some((o) => statusOf(o) === s))
  const [tab, setTab] = useState(tabs.includes('Live') ? 'Live' : tabs[0])
  return (
    <div>
      {tabs.length > 1 ? (
        <div className="ls-tabs" role="tablist" aria-label={t('Projects by status')}>
          {tabs.map((s) => (
            <button key={s} type="button" role="tab" aria-selected={tab === s} className={`ls-tab${tab === s ? ' is-on' : ''}`} onClick={() => setTab(s)}>
              {t(s)}
            </button>
          ))}
        </div>
      ) : null}
      <div className="ls-items ls-items--cards" role={tabs.length > 1 ? 'tabpanel' : undefined}>
        {items.filter((o) => tabs.length < 2 || statusOf(o) === tab).map(render)}
      </div>
    </div>
  )
}

function MenuCategorized({
  items,
  showPrices,
  onAdd,
  action,
  slug,
  capabilities,
}: {
  items: Offering[]
  showPrices: boolean
  onAdd: (o: Offering) => void
  action: 'cart' | 'book' | 'enquire' | 'none'
  slug: string
  capabilities?: Record<string, boolean | string | null>
}) {
  const t = useWords()
  // Group by category; anything uncategorised collects under a neutral heading
  // rather than being dropped.
  const groups = new Map<string, Offering[]>()
  for (const item of items) {
    const key = (item.category || '').trim() || t('More')
    const bucket = groups.get(key)
    if (bucket) bucket.push(item)
    else groups.set(key, [item])
  }

  return (
    <div className="ls-menu--categorized">
      {Array.from(groups.entries()).map(([cat, list]) => (
        <div key={cat} className="ls-menu__cat">
          <p className="ls-menu__catname">{cat}</p>
          <div className="ls-menu__catrule" />
          <div className="ls-menu__items">
            <div className="ls-items ls-items--list">
              {list.map((o) => {
                if (needsCard(o))
                  return (
                    <OfferingCard key={o.id} o={o} slug={slug} canOrder={Boolean(capabilities?.order)}
                      canBook={Boolean(capabilities?.book)} canEnquire={Boolean(capabilities?.enquire)} />
                  )
                const price = showPrices ? money(o.price_amount, o.currency) : null
                return (
                  <article key={o.id} className="ls-item">
                    <div className="ls-item__body">
                      <div className="ls-item__text">
                        <h3 className="ls-item__title">{o.title}</h3>
                        {o.description ? <p className="ls-item__desc">{o.description}</p> : null}
                      </div>
                      <span className="ls-item__leader" aria-hidden="true" />
                      <div className="ls-item__foot">
                        {price ? <span className="ls-price">{price}</span> : null}
                        <ItemAction action={action} item={o} slug={slug} onAdd={onAdd} />
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** "for 30 days", "a month", "a year" — how long one payment lasts. */
function planPeriod(days: number | null | undefined, t: Words) {
  if (!days) return null
  if (days === 30 || days === 31) return t('/ month')
  if (days === 90) return t('/ 3 months')
  if (days === 180) return t('/ 6 months')
  if (days === 365 || days === 366) return t('/ year')
  return t('for {days} days', { days })
}

function planHref(slug: string, p: Offering) {
  return p.plan
    ? `/${slug}/enquire?plan_id=${p.id}&purpose=membership`
    : `/${slug}/enquire?offering_id=${p.id}`
}

function Plans({
  items,
  variant,
  slug,
  action,
}: {
  items: Offering[]
  variant?: string
  slug: string
  action: 'cart' | 'book' | 'enquire' | 'none'
}) {
  const t = useWords()
  if (variant === 'comparison') {
    return (
      <div className="ls-plans--comparison">
        <table>
          <thead>
            <tr>
              <th>{t('Plan')}</th>
              <th>{t('What’s included')}</th>
              <th data-num="">{t('Price')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td>
                  <strong>{p.title}</strong>
                </td>
                <td className="ls-meta">{p.description || '—'}</td>
                <td data-num="">
                  {money(p.price_amount, p.currency) || '—'}
                  {p.period_days ? <span className="ls-meta"> {planPeriod(p.period_days, t)}</span> : null}
                </td>
                <td>
                  {action === 'enquire' ? (
                    <Link className="ls-btn ls-btn--outline" href={planHref(slug, p)}>
                      {p.plan ? t('Ask to join') : t('Choose')}
                    </Link>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Cards. The middle plan carries the emphasis — the conventional read.
  const featured = items.length >= 3 ? Math.floor(items.length / 2) : -1
  return (
    <div className="ls-plans">
      {items.map((p, i) => (
        <div key={p.id} className={`ls-plan ${i === featured ? 'ls-plan--featured' : ''}`}>
          {i === featured ? <span className="ls-plan__flag">{t('Most popular')}</span> : null}
          <h3 className="ls-plan__name">{p.title}</h3>
          <div className="ls-plan__price">
            <span className="ls-plan__amount">{money(p.price_amount, p.currency) || '—'}</span>
            {p.period_days ? <span className="ls-plan__period">{planPeriod(p.period_days, t)}</span> : null}
          </div>
          {p.description ? <p className="ls-plan__desc">{p.description}</p> : null}
          <div className="ls-plan__cta">
            {action === 'enquire' ? (
              <Link className="ls-btn" href={planHref(slug, p)}>
                {p.plan ? t('Ask to join') : t('Get started')}
              </Link>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}

function RoomRows({
  items,
  slug,
  action,
}: {
  items: Offering[]
  slug: string
  action: 'cart' | 'book' | 'enquire' | 'none'
}) {
  const t = useWords()
  return (
    <div>
      {items.map((r) => (
        <article key={r.id} className="ls-room">
          <div className="ls-room__media">
            {r.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={r.image_url} alt="" loading="lazy" />
            ) : null}
          </div>
          <div>
            <h3 className="ls-item__title" style={{ fontSize: '1.3rem' }}>
              {r.title}
            </h3>
            {r.description ? <p className="ls-item__desc">{r.description}</p> : null}
            <div className="ls-room__foot">
              <span className="ls-price" style={{ fontSize: '1.15rem' }}>
                {money(r.price_amount, r.currency) || t('On request')}
              </span>
              {action === 'book' ? (
                <Link className="ls-btn" href={`/${slug}/book?offering_id=${r.id}`}>
                  {t('Check availability')}
                </Link>
              ) : null}
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}

function ClassSchedule({
  items,
  slug,
  action,
}: {
  items: Offering[]
  slug: string
  action: 'cart' | 'book' | 'enquire' | 'none'
}) {
  const t = useWords()
  // Without per-session scheduling exposed publicly, a class list is grouped
  // by its category (e.g. "Strength", "Yoga") rather than inventing days.
  const groups = new Map<string, Offering[]>()
  for (const c of items) {
    const key = (c.category || '').trim() || t('All classes')
    const bucket = groups.get(key)
    if (bucket) bucket.push(c)
    else groups.set(key, [c])
  }

  return (
    <div className="ls-sched">
      {Array.from(groups.entries()).map(([group, list]) => (
        <div key={group} className="ls-sched__day">
          <div className="ls-sched__dayname">{group}</div>
          {list.map((c) => (
            <div key={c.id} className="ls-sched__row">
              <span className="ls-sched__time">{money(c.price_amount, c.currency) || '—'}</span>
              <span>
                <span className="ls-sched__name">{c.title}</span>
                {c.description ? <div className="ls-sched__who">{c.description}</div> : null}
              </span>
              {action === 'book' ? (
                <Link className="ls-btn ls-btn--outline" href={`/${slug}/book?offering_id=${c.id}`}>
                  {t('Book')}
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function ItemsSkeleton({ variant }: { variant?: string }) {
  const n = variant === 'list' ? 5 : 6
  return (
    <div
      className={`ls-items ls-items--${variant === 'list' ? 'list' : 'cards'}`}
      aria-hidden="true"
    >
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="ls-item" style={{ border: 0 }}>
          <div className="lc-skeleton" style={{ height: variant === 'list' ? 26 : 150 }} />
          <div className="ls-item__body">
            <div className="lc-skeleton" style={{ height: 14, width: '62%' }} />
            <div className="lc-skeleton" style={{ height: 12, width: '85%' }} />
          </div>
        </div>
      ))}
    </div>
  )
}
