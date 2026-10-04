'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { refreshBusinessShell } from '@/lib/refresh'
import { getAccessToken } from '@/lib/supabase/access-token'
import { platformUrl } from '@platform/config'
import { sendJson, type ActionResult } from '@/lib/server-send'

const apiUrl = platformUrl('api')

async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

export async function setModuleState(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const moduleId = String(formData.get('moduleId'))
  const action = String(formData.get('action'))
  const r = await send(`/v1/b/${businessId}/modules/${moduleId}/${action}`, 'POST')
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/modules`)
  revalidatePath(`/b/${businessId}/modules/${moduleId}`)
  refreshBusinessShell(businessId)
  return { ok: true }
}

/** The API's own message for a refused change, or a plain one. */
async function attempt(path: string, method: string): Promise<string | null> {
  const token = await getAccessToken()
  if (!token) return 'Your session ended. Sign in again.'
  const res = await fetch(`${apiUrl}${path}`, { method, headers: { Authorization: `Bearer ${token}` } })
  if (res.ok) return null
  try {
    const body = (await res.json()) as { error?: { message?: string } }
    return body.error?.message || `That did not work (${res.status}).`
  } catch {
    return `That did not work (${res.status}).`
  }
}

/**
 * "Enable" on a recommendation: the owner's explicit choice. When the card
 * named another tool it needs ("Turn on Orders + Products & services"), that
 * one is switched on first — because the button said so, never silently.
 * Then straight to the tool's setup checklist.
 */
export async function enableRecommended(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const moduleId = String(formData.get('moduleId'))
  const also = String(formData.get('also') || '').split(',').map((m) => m.trim()).filter(Boolean)
  let problem: string | null = null
  for (const m of [...also, moduleId]) {
    problem = await attempt(`/v1/b/${businessId}/modules/${m}/enable`, 'POST')
    if (problem) break
  }
  revalidatePath(`/b/${businessId}/modules`)
  refreshBusinessShell(businessId)
  redirect(`/b/${businessId}/modules/${moduleId}${problem ? `?problem=${encodeURIComponent(problem)}` : '?enabled=1'}`)
}

/** "Not now": out of the list until a new reason for it appears. */
export async function putOffRecommendation(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const moduleId = String(formData.get('moduleId'))
  await attempt(`/v1/platform/businesses/${businessId}/module-recommendations/${moduleId}/not-now`, 'POST')
  revalidatePath(`/b/${businessId}/modules`)
  revalidatePath(`/b/${businessId}`)
  return { ok: true }
}

export async function bringBackRecommendation(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const moduleId = String(formData.get('moduleId'))
  await attempt(`/v1/platform/businesses/${businessId}/module-recommendations/${moduleId}/not-now`, 'DELETE')
  revalidatePath(`/b/${businessId}/modules`)
  revalidatePath(`/b/${businessId}`)
  return { ok: true }
}
