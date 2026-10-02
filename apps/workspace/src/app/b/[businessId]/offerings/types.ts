export type KindField = {
  key: string
  label: string
  type: 'text' | 'long_text' | 'int' | 'money' | 'choice' | 'list' | 'bool' | 'date' | 'year'
  required: boolean
  choices: string[]
  unit: string | null
  help: string | null
}

export type Kind = {
  key: string
  source: string
  label: string
  plural: string
  flow: 'cart' | 'booking' | 'membership' | 'enquiry' | 'give'
  cta: string
  extra_ctas: string[]
  help: string
  options: boolean
  packs: boolean
  variants: boolean
  stockable: boolean
  tax_code: 'HSN' | 'SAC'
  fields: KindField[]
}

export type Choice = { label: string; price_delta: string | number }
export type OptionGroup = {
  name: string
  required: boolean
  max: number
  choices: Choice[]
  /** A box the customer writes in (the message on a cake, a name to engrave). */
  text?: boolean
  max_length?: number
}

/** Ordering ahead (P1-10D2): the day it is wanted, notice, cutoff, window, limit, advance. */
export type Preorder = {
  mode: 'required' | 'optional'
  lead_hours: number
  cutoff: string | null
  ready_times: string[]
  max_days: number
  window: { order_until: string | null; ready_from: string | null; ready_until: string | null }
  daily_limit: number | null
  advance: { type: 'percent' | 'fixed'; value: string } | null
  cancel_hours: number | null
}
/** Priced from a rate the owner enters each day (OK-15): rate × quantity + making + extras. */
export type PriceFormula = {
  rate_key: string
  quantity: string
  making: { type: 'percent' | 'per_unit' | 'flat'; value: string } | null
  extra: string
  extra_label: string | null
  round: 'rupee' | 'paise'
  last?: Record<string, unknown>
  last_words?: string | null
}
export type RateLite = { key: string; label: string; unit: string; unit_label: string; value: number | null }
export type Pack = { label: string; qty: number }
export type Axis = { name: string; values: string[] }

export type Offering = {
  id: string
  title: string
  description: string | null
  offering_type: string
  kind_label: string
  status: string
  visibility: string
  price_type: string
  price_amount: number | null
  currency: string
  tax_rate: number | null
  hsn_sac: string | null
  sku: string | null
  barcode: string | null
  track_inventory: boolean
  low_stock_threshold: number | null
  stock_unit: string
  attributes: Record<string, unknown>
  option_groups: OptionGroup[]
  preorder?: Preorder | null
  price_formula?: PriceFormula | null
  sell_units: Pack[]
  variant_options: Axis[]
  missing_fields: string[]
  version: number
  image_asset_ids?: string[]
  /** This offering's ready pictures, in order (`draft`: drawn by LOCAH, not yet kept). */
  images?: OfferingPicture[]
}

export type OfferingPicture = { id: string; url: string | null; alt_text: string | null; draft: boolean }

export type Variant = { id: string; name: string; price_amount: number | null; attributes: Record<string, string> }

export function inr(amount: number | null | undefined) {
  if (amount === null || amount === undefined) return null
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
  }).format(amount)
}
