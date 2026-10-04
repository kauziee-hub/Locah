'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function call(businessId: string, path: string, method: string, body?: unknown): Promise<ActionResult> {
  const r = await sendJson(`/v1/b/${businessId}/ai-employees${path}`, method, body)
  if (r.ok) revalidatePath(`/b/${businessId}/ai-employees`)
  return r
}

/** Switch one AI employee on or off (its own kill switch). */
export async function setEnabled(form: FormData): Promise<ActionResult> {
  const r = await call(String(form.get('businessId')), `/${String(form.get('kind'))}`, 'PATCH', {
    enabled: form.get('enabled') === 'true',
  })

  if (!r.ok) return r
  return { ok: true }
}

/** Autonomy, tools and limits — the owner's settings; the service enforces them. */
export async function saveSettings(form: FormData): Promise<ActionResult> {
  const limits: Record<string, number> = {}
  for (const [key, value] of form.entries()) {
    if (key.startsWith('limit:') && String(value).trim() !== '') limits[key.slice(6)] = Number(value)
  }
  const r = await call(String(form.get('businessId')), `/${String(form.get('kind'))}`, 'PATCH', {
    autonomy: String(form.get('autonomy')),
    tools: form.getAll('tools').map(String),
    limits,
  })
  if (!r.ok) return r
  return { ok: true }
}

/** Pause or resume every AI employee at once. */
export async function setPaused(form: FormData): Promise<ActionResult> {
  const r = await call(String(form.get('businessId')), '/pause', 'POST', { paused: form.get('paused') === 'true' })

  if (!r.ok) return r
  return { ok: true }
}

/** Approve or decline a request waiting for the owner. */
export async function decide(form: FormData): Promise<ActionResult> {
  const r = await call(String(form.get('businessId')), `/actions/${String(form.get('actionId'))}/decision`, 'POST', {
    approve: form.get('approve') === 'true',
  })

  if (!r.ok) return r
  return { ok: true }
}

/** Run the collections or procurement assistant now. */
export async function runNow(form: FormData): Promise<ActionResult> {
  const r = await call(String(form.get('businessId')), `/${String(form.get('kind'))}/run`, 'POST')

  if (!r.ok) return r
  return { ok: true }
}
