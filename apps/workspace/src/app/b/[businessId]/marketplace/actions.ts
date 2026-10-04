'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

/**
 * These two calls once ignored the response, so a refusal — not eligible to be
 * listed, say — came back as the same page with no reason. They now answer
 * with the API's reason, which the form shows under it.
 */
export async function optInDiscoverable(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId') || '')
  const r = await sendJson(`/v1/b/${businessId}/marketplace/opt-in`, 'POST', {
    confirmed: formData.get('confirmed') === 'true',
  })
  if (r.ok) revalidatePath(`/b/${businessId}/marketplace`)
  return r
}

export async function setVisibility(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId') || '')
  const r = await sendJson(`/v1/b/${businessId}/marketplace/visibility`, 'POST', {
    visibility: String(formData.get('visibility') || 'private'),
  })
  if (r.ok) revalidatePath(`/b/${businessId}/marketplace`)
  return r
}
