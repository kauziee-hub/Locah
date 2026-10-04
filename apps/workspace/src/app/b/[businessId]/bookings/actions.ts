'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'
import { asForm, type FormResult } from '@/lib/form-result'
import { RESOURCE_KINDS } from './words'

const api = (businessId: string) => `/v1/platform/businesses/${businessId}`
const num = (v: FormDataEntryValue | null, fallback: number) => (v && String(v).trim() ? Number(v) : fallback)

function refresh(businessId: string, bookingId?: string) {
  revalidatePath(`/b/${businessId}/bookings`)
  if (bookingId) revalidatePath(`/b/${businessId}/bookings/${bookingId}`)
}

/** Move a booking to its next step. Answers with the API's reason when refused. */
export async function transitionBooking(
  businessId: string,
  bookingId: string,
  status: string,
  reason?: string,
): Promise<ActionResult> {
  const r = await sendJson(`${api(businessId)}/bookings/${bookingId}/status`, 'POST', { status, reason })
  if (r.ok) refresh(businessId, bookingId)
  return r
}

export async function saveBookingsPolicy(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const deposit = formData.get('require_deposit') === 'on'
  const r = await sendJson(`${api(businessId)}/bookings-policy`, 'PATCH', {
    require_deposit: deposit,
    deposit_amount: deposit && formData.get('deposit_amount') ? Number(formData.get('deposit_amount')) : null,
    cancel_window_hours: num(formData.get('cancel_window_hours'), 24),
    hold_minutes: num(formData.get('hold_minutes'), 15),
    waitlist_enabled: formData.get('waitlist_enabled') === 'on',
    waitlist_offer_minutes: num(formData.get('waitlist_offer_minutes'), 60),
  })
  if (r.ok) refresh(businessId)
  return asForm(r)
}

export async function withdrawWaitlist(businessId: string, entryId: string): Promise<ActionResult> {
  const r = await sendJson(`${api(businessId)}/bookings-waitlist/${entryId}/withdraw`, 'POST', {})
  if (r.ok) refresh(businessId)
  return r
}

/** Repeat a booking every N weeks. */
export async function repeatBooking(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const bookingId = String(formData.get('bookingId'))
  const r = await sendJson(`${api(businessId)}/bookings/${bookingId}/repeat`, 'POST', {
    interval_weeks: num(formData.get('interval_weeks'), 1),
    occurrences: num(formData.get('occurrences'), 4),
  })
  if (r.ok) refresh(businessId, bookingId)
  return asForm(r)
}

/** Move this and the later bookings of a series by days and minutes — a shift from
 *  this booking's own time, so no clock or time zone is involved. */
export async function shiftSeries(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const bookingId = String(formData.get('bookingId'))
  const shift = (num(formData.get('days'), 0) * 24 * 60 + num(formData.get('minutes'), 0)) * 60_000
  if (!shift) return { ok: false, message: 'Choose how many days or minutes to move them by.' }
  const startsAt = new Date(String(formData.get('starts_at')))
  const endsAt = new Date(String(formData.get('ends_at')))
  const start = new Date(startsAt.getTime() + shift)
  const r = await sendJson(`${api(businessId)}/bookings-series/${String(formData.get('seriesId'))}/change-future`,
    'POST', {
      from_booking_id: bookingId, starts_at: start.toISOString(),
      ends_at: new Date(start.getTime() + (endsAt.getTime() - startsAt.getTime())).toISOString(),
    })
  if (r.ok) refresh(businessId, bookingId)
  return asForm(r)
}

export async function endSeries(businessId: string, bookingId: string, seriesId: string): Promise<ActionResult> {
  const r = await sendJson(`${api(businessId)}/bookings-series/${seriesId}/end`, 'POST', { from_booking_id: bookingId })
  if (r.ok) refresh(businessId, bookingId)
  return r
}

/** Tables, rooms, chairs… what customers book time on. */
export async function addResource(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const kindKey = String(formData.get('kind'))
  const kind = RESOURCE_KINDS[kindKey] ?? RESOURCE_KINDS.table
  const pooled = kind.mode === 'pooled'
  const size = num(formData.get('size'), 1)
  const r = await sendJson(`${api(businessId)}/bookings/resources`, 'POST', {
    location_id: String(formData.get('location_id')),
    resource_type: kindKey in RESOURCE_KINDS ? kindKey : 'table',
    name: String(formData.get('name') || '').trim(),
    allocation_mode: kind.mode,
    granularity: kind.granularity,
    capacity: pooled ? size : 1,
    max_party_size: pooled ? null : size,
    buffer_after_minutes: num(formData.get('buffer'), 0),
  })
  if (r.ok) revalidatePath(`/b/${businessId}/bookings/resources`)
  return asForm(r)
}

export async function setResourceActive(businessId: string, resourceId: string, active: boolean): Promise<ActionResult> {
  const r = await sendJson(`${api(businessId)}/bookings/resources/${resourceId}`, 'PATCH', { is_active: active })
  if (r.ok) revalidatePath(`/b/${businessId}/bookings/resources`)
  return r
}
