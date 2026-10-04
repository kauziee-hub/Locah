'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'
import { asForm, type FormResult } from '@/lib/form-result'

const members = (businessId: string) => `/v1/platform/businesses/${businessId}/workforce/members`
const text = (v: FormDataEntryValue | null) => String(v ?? '').trim()

function refresh(businessId: string, memberId?: string) {
  revalidatePath(`/b/${businessId}/workforce`)
  if (memberId) revalidatePath(`/b/${businessId}/workforce/${memberId}`)
}

export async function createWorkforceMember(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const locationId = text(formData.get('location_id'))
  const r = await sendJson(members(businessId), 'POST', {
    display_name: text(formData.get('display_name')),
    designation: text(formData.get('designation')) || null,
    phone: text(formData.get('phone')) || null,
    location_ids: locationId ? [locationId] : [],
    primary_location_id: locationId || null,
  })
  if (r.ok) {
    refresh(businessId)
    refreshBusinessShell(businessId)
  }
  return asForm(r)
}

/** Stop or start offering this person for bookings. Their past bookings stay. */
export async function setMemberActive(businessId: string, memberId: string, active: boolean): Promise<ActionResult> {
  const r = active
    ? await sendJson(`${members(businessId)}/${memberId}`, 'PATCH', { status: 'active' })
    : await sendJson(`${members(businessId)}/${memberId}/deactivate`, 'POST', {})
  if (r.ok) {
    refresh(businessId, memberId)
    refreshBusinessShell(businessId)
  }
  return r
}

export async function addPlace(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const memberId = text(formData.get('memberId'))
  const r = await sendJson(`${members(businessId)}/${memberId}/locations`, 'POST', {
    location_id: text(formData.get('location_id')), is_primary: formData.get('is_primary') === 'on',
  })
  if (r.ok) refresh(businessId, memberId)
  return asForm(r)
}

export async function removePlace(businessId: string, memberId: string, locationId: string): Promise<ActionResult> {
  const r = await sendJson(`${members(businessId)}/${memberId}/locations/${locationId}`, 'DELETE')
  if (r.ok) refresh(businessId, memberId)
  return r
}

export async function addService(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const memberId = text(formData.get('memberId'))
  const r = await sendJson(`${members(businessId)}/${memberId}/services`, 'POST', {
    offering_id: text(formData.get('offering_id')),
  })
  if (r.ok) refresh(businessId, memberId)
  return asForm(r)
}

export async function removeService(businessId: string, memberId: string, offeringId: string): Promise<ActionResult> {
  const r = await sendJson(`${members(businessId)}/${memberId}/services/${offeringId}`, 'DELETE')
  if (r.ok) refresh(businessId, memberId)
  return r
}

/** Usual weekly hours, or a weekly break that can't be booked. */
export async function addWeeklyHours(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const memberId = text(formData.get('memberId'))
  const r = await sendJson(`${members(businessId)}/${memberId}/availability`, 'POST', {
    weekday: Number(formData.get('weekday')),
    start_time: text(formData.get('start_time')),
    end_time: text(formData.get('end_time')),
    is_available: formData.get('kind') !== 'break',
  })
  if (r.ok) refresh(businessId, memberId)
  return asForm(r)
}

/** A day away (all day or part), or one-off working hours instead of the usual. */
export async function addDatedHours(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = text(formData.get('businessId'))
  const memberId = text(formData.get('memberId'))
  const away = formData.get('kind') !== 'extra'
  const allDay = away && formData.get('all_day') === 'on'
  const r = await sendJson(`${members(businessId)}/${memberId}/availability`, 'POST', {
    exception_date: text(formData.get('exception_date')),
    start_time: allDay ? '00:00' : text(formData.get('start_time')),
    end_time: allDay ? '23:59' : text(formData.get('end_time')),
    is_available: !away,
  })
  if (r.ok) refresh(businessId, memberId)
  return asForm(r)
}

export async function removeHours(businessId: string, memberId: string, availabilityId: string): Promise<ActionResult> {
  const r = await sendJson(`${members(businessId)}/${memberId}/availability/${availabilityId}`, 'DELETE')
  if (r.ok) refresh(businessId, memberId)
  return r
}
