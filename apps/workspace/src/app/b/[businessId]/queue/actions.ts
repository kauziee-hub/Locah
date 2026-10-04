'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send(businessId: string, path: string, body?: unknown): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/queue${path}`, 'POST', body)
  if (r.ok) revalidatePath(`/b/${businessId}/queue`)
  return r
}

export async function createQueueLane(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const department = String(form.get('department') || '').trim()
  const provider = String(form.get('providerId') || '').trim()
  const minutes = String(form.get('avgServiceMinutes') || '').trim()
  const r = await send(businessId, '/lanes', {
    location_id: String(form.get('locationId')),
    name: String(form.get('name')),
    department: department || null,
    provider_id: provider || null,
    allow_requeue: form.get('allowRequeue') === 'on',
    turn_soon_ahead: Number(form.get('turnSoonAhead') || 2),
    avg_service_minutes: minutes ? Number(minutes) : null,
  })
  if (!r.ok) return r
  return { ok: true }
}

export async function issueToken(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const booking = String(form.get('bookingId') || '').trim()
  const name = String(form.get('partyLabel') || '').trim()
  const r = await send(businessId, '/entries', {
    lane_id: String(form.get('laneId')),
    party_label: booking ? null : name,
    booking_id: booking || null,
    priority: Number(form.get('priority') || 0),
  })
  if (!r.ok) return r
  return { ok: true }
}

export async function queueAct(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const action = String(form.get('action'))
  const laneId = String(form.get('laneId') || '')
  const entryId = String(form.get('entryId') || '')
  const path = action === 'call-next' ? `/lanes/${laneId}/call-next` : `/entries/${entryId}/${action}`
  const r = await send(businessId, path, {})
  if (!r.ok) return r
  return { ok: true }
}
