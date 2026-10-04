'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

function base(formData: FormData) {
  return `/v1/platform/businesses/${String(formData.get('businessId'))}/loyalty`
}

export async function saveLoyaltyProgram(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const expiry = String(formData.get('expiry_days') || '')
  const r = await send(`${base(formData)}/program`, 'PUT', {
    name: String(formData.get('name') || ''),
    points_per_rupee: Number(formData.get('points_per_rupee')),
    redemption_rupees_per_point: Number(formData.get('redemption_rupees_per_point')),
    min_redemption_points: Number(formData.get('min_redemption_points')),
    expiry_days: expiry === '' ? null : Number(expiry),
    status: String(formData.get('status') || 'active'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/loyalty`)
  return { ok: true }
}

export async function createStampCard(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const r = await send(`${base(formData)}/stamps`, 'POST', {
    name: String(formData.get('name') || ''),
    required_stamps: Number(formData.get('required_stamps') || 10),
    reward_kind: 'free_item',
    reward_item: String(formData.get('reward_item') || 'Free reward'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/loyalty`)
  return { ok: true }
}

export async function issueVoucher(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const rupees = Number(formData.get('amount_rupees'))
  const r = await send(`${base(formData)}/vouchers`, 'POST', {
    issued_amount_paise: Math.round(rupees * 100),
    recipient_name: String(formData.get('recipient_name') || '') || null,
    holder_contact_id: String(formData.get('holder_contact_id') || '') || null,
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/loyalty`)
  return { ok: true }
}

export async function earnPoints(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const contactId = String(formData.get('contact_id'))
  const rupees = Number(formData.get('amount_rupees'))
  const sourceId = `desk-${Date.now()}`
  const r = await send(`${base(formData)}/customers/${contactId}/earn`, 'POST', {
    order_amount_paise: Math.round(rupees * 100),
    source_type: 'pos',
    source_id: sourceId,
    idempotency_key: sourceId,
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/loyalty`)
  return { ok: true }
}

export async function redeemPoints(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const contactId = String(formData.get('contact_id'))
  const sourceId = `redeem-${Date.now()}`
  const r = await send(`${base(formData)}/customers/${contactId}/redeem`, 'POST', {
    points_to_redeem: Number(formData.get('points')),
    order_amount_paise: Number(formData.get('order_amount_paise') || 0),
    source_type: 'pos',
    source_id: sourceId,
    idempotency_key: sourceId,
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/loyalty`)
  return { ok: true }
}
