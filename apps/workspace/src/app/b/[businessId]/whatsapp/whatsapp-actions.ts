'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'
import type { Setup, Thread } from './types'

const api = (b: string) => `/v1/platform/businesses/${b}`

function refresh(b: string) {
  revalidatePath(`/b/${b}/whatsapp`)
  revalidatePath(`/b/${b}/inbox`)
  // A connected number is what makes WhatsApp ready (and its "Set up" mark go).
  refreshBusinessShell(b)
}

export async function connectSandbox(b: string, body: Record<string, unknown>): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/channel/sandbox`, 'POST', body)
  if (r.ok) refresh(b)
  return r
}

export async function completeSignup(b: string, body: Record<string, unknown>): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/channel/embedded-signup`, 'POST', body)
  if (r.ok) refresh(b)
  return r
}

export async function disconnect(b: string): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/channel`, 'DELETE')
  if (r.ok) refresh(b)
  return r
}

export async function submitTemplates(b: string): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/templates/submit`, 'POST')
  if (r.ok) refresh(b)
  return r
}

export async function saveSettings(b: string, body: Record<string, unknown>): Promise<ActionResult<Setup>> {
  const r = await sendJson<Setup>(`${api(b)}/messaging/settings`, 'PUT', body)
  if (r.ok) refresh(b)
  return r
}

export async function saveMyAlerts(b: string, body: Record<string, unknown>): Promise<ActionResult<Setup>> {
  const r = await sendJson<Setup>(`${api(b)}/messaging/alerts/me`, 'PUT', body)
  if (r.ok) refresh(b)
  return r
}

export async function sandboxInbound(b: string, body: Record<string, unknown>): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/sandbox/inbound`, 'POST', body)
  if (r.ok) refresh(b)
  return r
}

export async function reply(b: string, id: string, body: string): Promise<ActionResult<Thread>> {
  const r = await sendJson<Thread>(`${api(b)}/messaging/conversations/${id}/messages`, 'POST', { body })
  if (r.ok) refresh(b)
  return r
}

export async function assign(b: string, id: string, assignedTo: string | null): Promise<ActionResult<Thread>> {
  const r = await sendJson<Thread>(`${api(b)}/messaging/conversations/${id}/assign`, 'POST', { assigned_to: assignedTo })
  if (r.ok) refresh(b)
  return r
}

export async function setState(b: string, id: string, body: Record<string, unknown>): Promise<ActionResult<Thread>> {
  const r = await sendJson<Thread>(`${api(b)}/messaging/conversations/${id}/state`, 'POST', body)
  if (r.ok) refresh(b)
  return r
}

export async function markRead(b: string, id: string): Promise<ActionResult> {
  return sendJson(`${api(b)}/messaging/conversations/${id}/read`, 'POST')
}

export async function addQuickReply(b: string, title: string, body: string): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/quick-replies`, 'POST', { title, body })
  if (r.ok) refresh(b)
  return r
}

export async function removeQuickReply(b: string, id: string): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/quick-replies/${id}`, 'DELETE')
  if (r.ok) refresh(b)
  return r
}

/** A bill or a khata statement, from the business's own WhatsApp number. */
export async function sendDocument(b: string, what: 'bill' | 'statement', id: string): Promise<ActionResult<{ body: string }>> {
  const path = what === 'bill' ? `${api(b)}/invoices/${id}/whatsapp` : `${api(b)}/ledger/accounts/${id}/whatsapp`
  const r = await sendJson<{ body: string }>(path, 'POST')
  if (r.ok) revalidatePath(`/b/${b}/inbox`)
  return r
}

export async function registerNumber(b: string, pin: string): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/channel/register`, 'POST', { pin })
  if (r.ok) refresh(b)
  return r
}

export async function sendTestMessage(b: string, to: string): Promise<ActionResult> {
  return sendJson(`${api(b)}/messaging/test`, 'POST', { to })
}

export async function setCalling(b: string, enabled: boolean): Promise<ActionResult> {
  const r = await sendJson(`${api(b)}/messaging/calling`, 'POST', { enabled })
  if (r.ok) refresh(b)
  return r
}
