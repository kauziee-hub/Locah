'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

export async function updateRegionalSettings(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const r = await send(`/v1/platform/businesses/${businessId}/settings`, 'PATCH', {
    timezone: String(formData.get('timezone')),
    currency: String(formData.get('currency')),
    country: String(formData.get('country')),
    language: String(formData.get('language')),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/settings`)
  return { ok: true }
}

export async function updatePreferences(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const r = await send(`/v1/platform/businesses/${businessId}/preferences`, 'PATCH', {
    date_format: String(formData.get('date_format')),
    time_format: String(formData.get('time_format')),
    measurement_system: String(formData.get('measurement_system')),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/settings`)
  return { ok: true }
}
