/* Pure helpers shared by the offering card (client) and server-rendered
   tenant pages such as the enquiry page. No hooks here. */

import { siteWords, type Words } from '@/lib/site-words'

const english = siteWords('en')

export type Choice = { label: string; price_delta: string }
export type OptionGroup = { name: string; required: boolean; max: number; choices: Choice[]; text?: boolean; max_length?: number }
/** Ordering ahead (P1-10D2): whether a day is needed, the earliest, the advance. */
export type PreorderInfo = {
  needed: boolean
  lead_hours: number
  earliest_words: string | null
  advance: { type: 'percent' | 'fixed'; value: number } | null
  cancel_hours: number | null
}
export type PublicOffering = {
  id: string
  title: string
  description?: string | null
  offering_type?: string | null
  price_type?: string
  price_amount?: number | null
  currency?: string
  image_url?: string | null
  kind?: { label: string; flow: string; cta: string; extra_ctas: string[] }
  attributes?: Record<string, unknown>
  labels?: Record<string, string>
  units?: Record<string, string>
  option_groups?: OptionGroup[]
  packs?: { label: string; price_amount: number | null }[]
  variants?: { id: string; name: string; price_amount: number | null }[]
  raised_amount?: number
  preorder?: PreorderInfo
  /** Priced from today's rate (OK-15): how the price is made up. */
  price_basis?: { words: string | null; rate_at: string | null }
  /** Inventory's public word for this item (never a quantity); absent when
   *  the business does not track its stock or Inventory is not on. */
  availability?: 'available' | 'low_stock' | 'out_of_stock' | null
}

/** Sold out can be shown but never added to a basket. */
export function soldOut(o: PublicOffering): boolean {
  return o.availability === 'out_of_stock'
}

/** One honest line about stock, from Inventory's public answer — or nothing. */
export function StockNote({ o, t = english }: { o: PublicOffering; t?: Words }) {
  if (o.availability === 'out_of_stock') return <p className="ls-stock ls-stock--out">{t('Out of stock')}</p>
  if (o.availability === 'low_stock') return <p className="ls-stock ls-stock--low">{t('Only a few left')}</p>
  return null
}

export function money(amount?: number | null, currency?: string) {
  if (amount === null || amount === undefined) return null
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currency || 'INR',
      maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    }).format(amount)
  } catch {
    return `₹${amount}`
  }
}

export function priceLabel(o: PublicOffering, t: Words = english): string | null {
  if (o.offering_type === 'cause') return null
  if (o.packs?.length) {
    const first = o.packs.find((p) => p.price_amount !== null)
    return first ? `${money(first.price_amount, o.currency)} / ${first.label}` : null
  }
  if (o.price_type === 'enquiry') return t('Price on request')
  if (o.price_type === 'free') return t('Free')
  const p = money(o.price_amount, o.currency)
  if (!p) return null
  return o.price_type === 'starting_from' ? t('From {price}', { price: p }) : p
}

/** A kind's own details, labelled in words, e.g. "Fuel: Petrol". */
export function Specs({ o, skip = [], t = english }: { o: PublicOffering; skip?: string[]; t?: Words }) {
  // The kind's own field order (labels arrive in it); the stored attributes
  // come back in the database's key order.
  const attrs = o.attributes ?? {}
  const order = Object.keys(o.labels ?? {}).filter((k) => k in attrs)
  const rows = (order.length ? order.map((k) => [k, attrs[k]] as [string, unknown]) : Object.entries(attrs))
    .filter(([k, v]) => !skip.includes(k) && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0))
    .filter(([k]) => !['min_amount', 'suggested_amounts', 'goal_amount', 'price_per', 'map_link'].includes(k))
  if (rows.length === 0) return null
  return (
    <dl className="ls-specs">
      {rows.map(([k, v]) => (
        <div key={k} className="ls-specs__row">
          <dt>{t(o.labels?.[k] ?? k)}</dt>
          <dd>
            {Array.isArray(v) ? (
              <ul>{v.map((x) => <li key={String(x)}>{String(x)}</li>)}</ul>
            ) : typeof v === 'boolean' ? (v ? t('Yes') : t('No')) : `${String(v)}${o.units?.[k] ? ` ${t(o.units[k])}` : ''}`}
          </dd>
        </div>
      ))}
    </dl>
  )
}

