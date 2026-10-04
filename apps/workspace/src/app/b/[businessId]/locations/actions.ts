'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'
import { asForm, type FormResult } from '@/lib/form-result'

const at = (businessId: string) => `/v1/platform/businesses/${businessId}/locations`
const text = (v: FormDataEntryValue | null) => String(v ?? '').trim()
const optional = (v: FormDataEntryValue | null) => text(v) || undefined

// The address fields every reader understands (Home's area line, the AI
// receptionist's "where are you?", the website contact, the Marketplace).
const ADDRESS_FIELDS = ['line1', 'locality', 'landmark', 'city', 'state', 'postal_code'] as const

function refresh(businessId: string, locationId?: string) {
  revalidatePath(`/b/${businessId}/locations`)
  if (locationId) revalidatePath(`/b/${businessId}/locations/${locationId}`)
  revalidatePath(`/b/${businessId}`)
}

export async function createLocation(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const address = Object.fromEntries(ADDRESS_FIELDS.map((k) => [k, text(formData.get(k))]).filter(([, v]) => v))
  const r = await sendJson(at(businessId), 'POST', {
    name: text(formData.get('name')),
    timezone: text(formData.get('timezone')) || 'Asia/Kolkata',
    phone: optional(formData.get('phone')),
    email: optional(formData.get('email')),
    address: Object.keys(address).length ? { ...address, country: 'IN' } : undefined,
  })
  if (r.ok) {
    refresh(businessId)
    refreshBusinessShell(businessId)
  }
  return asForm(r)
}

/** Name, contact and address. The saved address is merged, so country and map position stay. */
export async function updateLocation(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const locationId = text(formData.get('locationId'))
  const current = await sendJson<{ address: Record<string, unknown> | null }>(`${at(businessId)}/${locationId}`, 'GET')
  if (!current.ok) return asForm(current)
  const address: Record<string, unknown> = { ...(current.data?.address ?? {}) }
  for (const k of ADDRESS_FIELDS) {
    const v = text(formData.get(k))
    if (v) address[k] = v
    else delete address[k]
  }
  if (!address.country) address.country = 'IN'
  const r = await sendJson(`${at(businessId)}/${locationId}`, 'PATCH', {
    name: text(formData.get('name')),
    phone: optional(formData.get('phone')),
    email: optional(formData.get('email')),
    notes: optional(formData.get('notes')),
    address,
  })
  if (r.ok) refresh(businessId, locationId)
  return asForm(r)
}

/** Make primary, archive or reactivate. */
export async function locationStep(
  businessId: string,
  locationId: string,
  step: 'set-primary' | 'archive' | 'reactivate',
): Promise<ActionResult> {
  // The API takes an (optionally versioned) body; an empty one is a plain request.
  const r = await sendJson(`${at(businessId)}/${locationId}/${step}`, 'POST', {})
  if (r.ok) {
    refresh(businessId, locationId)
    refreshBusinessShell(businessId)
  }
  return r
}

/** Weekly opening hours: {"mon": [["09:00", "18:00"]], ...}; bookings and WhatsApp offer times from these. */
export async function saveHours(
  businessId: string,
  locationId: string,
  hours: Record<string, unknown> | null
): Promise<ActionResult> {
  const r = await sendJson(`${at(businessId)}/${locationId}`, 'PATCH', { hours })
  if (r.ok) refresh(businessId, locationId)
  return r
}
