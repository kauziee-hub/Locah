'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send(form: FormData, path: string, method: string, body: unknown): Promise<ActionResult> {
  const b = String(form.get('businessId'))
  const r = await sendJson(`/v1/platform/businesses/${b}/compliance/items${path}`, method, body)
  if (r.ok) revalidatePath(`/b/${b}/compliance`)
  return r
}

export async function createComplianceItem(form: FormData): Promise<ActionResult> {
  const r = await send(form, '', 'POST', {
    item_type: String(form.get('item_type')),
    kind: String(form.get('kind')),
    title: String(form.get('title')),
    due_on: String(form.get('due_on')),
    recurrence: String(form.get('recurrence') || 'none'),
    licence_number: String(form.get('licence_number') || '') || null,
    authority: String(form.get('authority') || '') || null,
    document_url: String(form.get('document_url') || '') || null,
    notes: String(form.get('notes') || '') || null,
    show_on_site: form.get('item_type') === 'licence' && form.get('show_on_site') === 'on',
  })

  if (!r.ok) return r
  return { ok: true }
}

export async function updateComplianceItem(form: FormData): Promise<ActionResult> {
  const item = String(form.get('itemId'))
  const r = await send(form, `/${item}`, 'PATCH', {
    title: String(form.get('title')),
    due_on: String(form.get('due_on')),
    licence_number: String(form.get('licence_number') || '') || null,
    authority: String(form.get('authority') || '') || null,
    document_url: String(form.get('document_url') || '') || null,
    notes: String(form.get('notes') || '') || null,
    show_on_site: form.get('show_on_site') === 'on',
  })
  if (!r.ok) return r
  return { ok: true }
}

export async function renewComplianceItem(form: FormData): Promise<ActionResult> {
  const r = await send(form, `/${String(form.get('itemId'))}/renew`, 'POST', {
    new_due_on: String(form.get('new_due_on')),
    note: String(form.get('note') || '') || null,
  })

  if (!r.ok) return r
  return { ok: true }
}

export async function markComplianceFiled(form: FormData): Promise<ActionResult> {
  const r = await send(form, `/${String(form.get('itemId'))}/filed`, 'POST', { note: String(form.get('note') || '') || null })

  if (!r.ok) return r
  return { ok: true }
}

export async function setComplianceArchived(form: FormData): Promise<ActionResult> {
  const r = await send(form, `/${String(form.get('itemId'))}/archive`, 'POST', { archived: form.get('archived') === 'true' })

  if (!r.ok) return r
  return { ok: true }
}
