'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { sendJson, type ActionResult } from '@/lib/server-send'

/**
 * Every write goes to the quotes API as it stands.
 *
 * Nothing here computes a price, applies a discount, decides whether a quote may
 * be edited, or stamps a status. A quote is a commitment the business is held
 * to, so the numbers on it and the transitions between its states have exactly
 * one author — `QuoteService`. This file carries intent there and brings the
 * recalculated truth back.
 */
async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

type QuoteItemInput = {
  offering_id?: string | null
  title?: string | null
  description?: string | null
  unit_label?: string | null
  quantity: number
  unit_price?: number | null
  tax_rate: number
  discount_type?: string | null
  discount_value?: number | null
  line_kind?: string | null
  moq?: number | null
  lead_time_days?: number | null
  quantity_breaks?: unknown[]
  boq_section?: string | null
  size_matrix?: unknown[]
}

type QuoteChargeInput = {
  label: string
  amount: number
  taxable: boolean
  tax_rate: number
}

/**
 * Read the editor's lines back off the form.
 *
 * The editor is a client component holding a variable number of rows, so it
 * hands them over as JSON in a hidden field rather than as `item_0_title`,
 * `item_1_title` and so on. Anything malformed is dropped rather than guessed
 * at: a line the server cannot read is a line that should not end up priced.
 */
function parseItems(raw: FormDataEntryValue | null): QuoteItemInput[] {
  if (!raw) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(String(raw))
  } catch {
    return []
  }
  if (!Array.isArray(parsed)) return []
  return parsed.flatMap((row): QuoteItemInput[] => {
    if (!row || typeof row !== 'object') return []
    const r = row as Record<string, unknown>
    const quantity = Number(r.quantity)
    const kind = r.line_kind === 'boq' || r.line_kind === 'size_matrix' ? r.line_kind : 'item'
    const sizes = Array.isArray(r.size_matrix) ? r.size_matrix : []
    // A size matrix's quantity is the sum of its sizes. The typed quantity
    // can be empty; the API refuses the line if no size is filled in.
    if (kind !== 'size_matrix' && (!Number.isFinite(quantity) || quantity <= 0)) return []
    if (kind === 'size_matrix' && sizes.length === 0 && (!Number.isFinite(quantity) || quantity <= 0)) {
      return []
    }
    const offeringId = typeof r.offering_id === 'string' && r.offering_id ? r.offering_id : null
    const title = typeof r.title === 'string' && r.title.trim() ? r.title.trim() : null
    // A line is either catalogue-backed or free-text; one of the two must say
    // what is being quoted for.
    if (!offeringId && !title) return []
    const unitPrice = Number(r.unit_price)
    const discountValue = Number(r.discount_value)
    return [
      {
        offering_id: offeringId,
        title,
        description:
          typeof r.description === 'string' && r.description.trim() ? r.description.trim() : null,
        unit_label:
          typeof r.unit_label === 'string' && r.unit_label.trim() ? r.unit_label.trim() : null,
        quantity,
        unit_price: Number.isFinite(unitPrice) && unitPrice >= 0 ? unitPrice : null,
        tax_rate: Number.isFinite(Number(r.tax_rate)) ? Number(r.tax_rate) : 0,
        discount_type:
          r.discount_type === 'percent' || r.discount_type === 'amount' ? r.discount_type : null,
        discount_value:
          Number.isFinite(discountValue) && discountValue > 0 ? discountValue : null,
        line_kind:
          r.line_kind === 'boq' || r.line_kind === 'size_matrix' || r.line_kind === 'item'
            ? r.line_kind
            : 'item',
        moq: Number.isFinite(Number(r.moq)) && Number(r.moq) > 0 ? Number(r.moq) : null,
        lead_time_days:
          r.lead_time_days === null || r.lead_time_days === ''
            ? null
            : Number.isFinite(Number(r.lead_time_days))
              ? Number(r.lead_time_days)
              : null,
        quantity_breaks: Array.isArray(r.quantity_breaks) ? r.quantity_breaks : [],
        boq_section: typeof r.boq_section === 'string' && r.boq_section.trim() ? r.boq_section.trim() : null,
        size_matrix: Array.isArray(r.size_matrix) ? r.size_matrix : [],
      },
    ]
  })
}

function parsePlan(raw: FormDataEntryValue | null): Record<string, unknown>[] {
  const text = raw === null ? '' : String(raw).trim()
  if (!text) return []
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .flatMap((line) => {
      const [label, amountType, amountValue, dueRule, dueDays] = line.split('|').map((part) => part.trim())
      if (!label || !amountValue) return []
      return [
        {
          label,
          amount_type: amountType === 'percent' ? 'percent' : 'amount',
          amount_value: Number(amountValue),
          due_rule: dueRule === 'net_days' || dueRule === 'milestone' ? dueRule : 'on_acceptance',
          due_days: dueDays ? Number(dueDays) : null,
        },
      ]
    })
}

function parseCharges(raw: FormDataEntryValue | null): QuoteChargeInput[] {
  if (!raw) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(String(raw))
  } catch {
    return []
  }
  if (!Array.isArray(parsed)) return []
  return parsed.flatMap((row): QuoteChargeInput[] => {
    if (!row || typeof row !== 'object') return []
    const r = row as Record<string, unknown>
    const label = typeof r.label === 'string' ? r.label.trim() : ''
    const amount = Number(r.amount)
    if (!label || !Number.isFinite(amount) || amount < 0) return []
    return [
      {
        label,
        amount,
        taxable: Boolean(r.taxable),
        tax_rate: Number.isFinite(Number(r.tax_rate)) ? Number(r.tax_rate) : 0,
      },
    ]
  })
}

function optionalText(form: FormData, field: string): string | null {
  const value = form.get(field)
  const text = value === null ? '' : String(value).trim()
  return text ? text : null
}

function optionalNumber(form: FormData, field: string): number | null {
  const value = form.get(field)
  if (value === null || String(value).trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

/**
 * `valid_until` arrives from a date input as `YYYY-MM-DD`, which the API reads
 * as midnight UTC — the start of that day, not the end of it. A quote marked
 * valid until the 30th should still be valid during the 30th, so it is carried
 * to the end of that day.
 */
function endOfDayIso(form: FormData, field: string): string | null {
  const raw = optionalText(form, field)
  if (!raw) return null
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw
  return `${raw}T23:59:59+00:00`
}

function collectBody(formData: FormData): Record<string, unknown> {
  return {
    customer_contact_id: optionalText(formData, 'customer_contact_id'),
    title: optionalText(formData, 'title'),
    terms: optionalText(formData, 'terms'),
    notes: optionalText(formData, 'notes'),
    internal_notes: optionalText(formData, 'internal_notes'),
    discount_type: optionalText(formData, 'discount_type'),
    discount_value: optionalNumber(formData, 'discount_value'),
    deposit_type: optionalText(formData, 'deposit_type'),
    deposit_value: optionalNumber(formData, 'deposit_value'),
    valid_until: endOfDayIso(formData, 'valid_until'),
    items: parseItems(formData.get('items_json')),
    charges: parseCharges(formData.get('charges_json')),
    payment_plan: parsePlan(formData.get('payment_plan')),
  }
}

export async function createQuote(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const body = collectBody(formData)
  const created = await send<{ id?: string }>(
    `/v1/platform/businesses/${businessId}/quotes`,
    'POST',
    { ...body, currency: String(formData.get('currency') || 'INR') }
  )
  if (!created.ok) return created
  const quoteId = created.data?.id
  revalidatePath(`/b/${businessId}/quotes`)
  if (quoteId) {
    redirect(`/b/${businessId}/quotes/${quoteId}`)
  }
  redirect(`/b/${businessId}/quotes`)
}

export async function saveQuoteDraft(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const rawVersion = Number(formData.get('version'))
  const body: Record<string, unknown> = collectBody(formData)
  // Optimistic concurrency: two people editing one draft should not silently
  // overwrite each other. The API compares and refuses a stale write.
  if (Number.isFinite(rawVersion) && rawVersion >= 1) {
    body.version = rawVersion
  }
  const r = await send(`/v1/platform/businesses/${businessId}/quotes/${quoteId}`, 'PATCH', body)
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/quotes`)
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  return { ok: true }
}

export async function issueQuote(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const validDays = optionalNumber(formData, 'valid_days')
  const r = await send(`/v1/platform/businesses/${businessId}/quotes/${quoteId}/issue`, 'POST', {
    valid_days: validDays && validDays >= 1 ? Math.floor(validDays) : undefined,
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/quotes`)
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  return { ok: true }
}

export async function recordQuoteDecision(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const r = await send(`/v1/platform/businesses/${businessId}/quotes/${quoteId}/decision`, 'POST', {
    decision: String(formData.get('decision')),
    reason: optionalText(formData, 'reason'),
    decided_by_name: optionalText(formData, 'decided_by_name'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/quotes`)
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  return { ok: true }
}

export async function cancelQuote(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const r = await send(`/v1/platform/businesses/${businessId}/quotes/${quoteId}/cancel`, 'POST', {
    reason: optionalText(formData, 'reason'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/quotes`)
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  return { ok: true }
}

export async function approveQuoteDiscount(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const r = await send(`/v1/platform/businesses/${businessId}/quotes/${quoteId}/discount-approval`, 'POST', {
    decision: String(formData.get('decision') || 'approved'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  return { ok: true }
}

export async function handOffQuote(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const r = await send(`/v1/platform/businesses/${businessId}/quotes/${quoteId}/conversion`, 'POST', {
    target: String(formData.get('target') || 'order'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  return { ok: true }
}

export async function reviseQuote(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const revised = await send<{ id?: string }>(
    `/v1/platform/businesses/${businessId}/quotes/${quoteId}/revise`,
    'POST'
  )
  if (!revised.ok) return revised
  const nextId = revised.data?.id
  revalidatePath(`/b/${businessId}/quotes`)
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  // A revision is a new quote; the person who asked for it wants to edit that
  // one, not keep looking at the superseded original.
  redirect(`/b/${businessId}/quotes/${nextId ?? quoteId}`)
}
