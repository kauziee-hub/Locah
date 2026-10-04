'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

export async function markRead(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const notificationId = String(formData.get('notificationId'))
  const r = await send(
    `/v1/platform/businesses/${businessId}/notifications/${notificationId}/read`,
    'POST'
  )
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/notifications`)
  return { ok: true }
}

export async function markAllRead(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const r = await send(`/v1/platform/businesses/${businessId}/notifications/read-all`, 'POST')
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/notifications`)
  return { ok: true }
}

export async function setPreference(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const r = await send(`/v1/platform/businesses/${businessId}/notification-preferences`, 'PUT', {
    category: String(formData.get('category')),
    in_app_enabled: formData.get('in_app_enabled') === 'on',
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/notifications`)
  return { ok: true }
}
