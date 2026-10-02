'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'

const api = (b: string) => `/v1/platform/businesses/${b}`

function refresh(businessId: string, enrolmentId?: string) {
  revalidatePath(`/b/${businessId}/memberships`)
  if (enrolmentId) revalidatePath(`/b/${businessId}/memberships/${enrolmentId}`)
  // A published or archived plan is what makes Memberships ready or not.
  if (!enrolmentId) refreshBusinessShell(businessId)
}

async function send<T = unknown>(
  businessId: string,
  path: string,
  method: string,
  body?: unknown,
  enrolmentId?: string
): Promise<ActionResult<T>> {
  const r = await sendJson<T>(`${api(businessId)}${path}`, method, body)
  if (r.ok) refresh(businessId, enrolmentId)
  return r
}

export async function createPlan(businessId: string, body: Record<string, unknown>) {
  return send<{ id: string }>(businessId, '/membership-plans', 'POST', body)
}

export async function archivePlan(businessId: string, planId: string) {
  return send(businessId, `/membership-plans/${planId}/archive`, 'POST', {})
}

export async function enrol(businessId: string, body: Record<string, unknown>) {
  return send<{ id: string }>(businessId, '/membership-enrolments', 'POST', body)
}

export async function renew(businessId: string, enrolmentId: string) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/renew`, 'POST', undefined, enrolmentId)
}

export async function freeze(businessId: string, enrolmentId: string, body: Record<string, unknown>) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/freezes`, 'POST', body, enrolmentId)
}

export async function cancelFreeze(businessId: string, enrolmentId: string, freezeId: string) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/freezes/${freezeId}/cancel`, 'POST', undefined,
    enrolmentId)
}

export async function resume(businessId: string, enrolmentId: string) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/resume`, 'POST', {}, enrolmentId)
}

export async function cancelMembership(businessId: string, enrolmentId: string, reason: string) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/cancel`, 'POST', { reason }, enrolmentId)
}

export async function recordSession(businessId: string, enrolmentId: string, key: string) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/sessions`, 'POST', { idempotency_key: key },
    enrolmentId)
}

export async function changeDeliveryDay(businessId: string, enrolmentId: string, body: Record<string, unknown>) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/delivery-day`, 'POST', body, enrolmentId)
}

export async function changeDeliveryFuture(businessId: string, enrolmentId: string, body: Record<string, unknown>) {
  return send(businessId, `/membership-enrolments/${enrolmentId}/delivery`, 'PATCH', body, enrolmentId)
}

export async function finaliseDay(businessId: string, onDate: string) {
  return send<{ orders: number; not_delivered: number }>(businessId, `/subscriptions/day/${onDate}/generate`,
    'POST')
}

export type CheckinResult = {
  enrolment_id: string
  member: string | null
  plan: string
  decision: 'allowed' | 'warning' | 'denied'
  colour: 'green' | 'amber' | 'red'
  reason: string
  status: string
  valid_until: string | null
  days_remaining: number | null
  sessions_remaining: number | null
  renew: string | null
}

export async function checkin(businessId: string, code: string) {
  return sendJson<CheckinResult>(`${api(businessId)}/membership-checkin`, 'POST', { code })
}
