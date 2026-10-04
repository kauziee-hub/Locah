'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

function root(formData: FormData) {
  return `/v1/platform/businesses/${String(formData.get('businessId'))}/marketing`
}

export async function createCampaign(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const created = await send<{ id: string }>(`${root(formData)}/campaigns`, 'POST', {
    name: String(formData.get('name') || ''),
    goal: String(formData.get('goal') || ''),
    channel: String(formData.get('channel') || 'whatsapp'),
    budget_paise: Math.round(Number(formData.get('budget_rupees') || 0) * 100),
  })
  if (!created.ok) return created
  revalidatePath(`/b/${businessId}/marketing`)
  redirect(`/b/${businessId}/marketing/${created.data?.id ?? ''}`)
}

export async function saveCampaignBuild(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const campaignId = String(formData.get('campaignId'))
  const segment = String(formData.get('audience_segment_id') || '')
  const offer = String(formData.get('offer_id') || '')
  const r = await send(`${root(formData)}/campaigns/${campaignId}`, 'PATCH', {
    audience_segment_id: segment || null,
    offer_id: offer || null,
    creative: { text: String(formData.get('creative') || '') },
    budget_paise: Math.round(Number(formData.get('budget_rupees') || 0) * 100),
    channel: String(formData.get('channel') || 'whatsapp'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/marketing/${campaignId}`)
  return { ok: true }
}

export async function prepareCampaign(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const campaignId = String(formData.get('campaignId'))
  const r = await send(`${root(formData)}/campaigns/${campaignId}/prepare`, 'POST')
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/marketing/${campaignId}`)
  return { ok: true }
}

export async function approveCampaign(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const campaignId = String(formData.get('campaignId'))
  const r = await send(`${root(formData)}/campaigns/${campaignId}/approve`, 'POST')
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/marketing/${campaignId}`)
  return { ok: true }
}

export async function dispatchCampaign(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const campaignId = String(formData.get('campaignId'))
  const r = await send(`${root(formData)}/campaigns/${campaignId}/dispatch`, 'POST')
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/marketing/${campaignId}`)
  return { ok: true }
}

export async function createOffer(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const r = await send(`${root(formData)}/offers`, 'POST', {
    code: String(formData.get('code') || ''),
    name: String(formData.get('name') || ''),
    kind: String(formData.get('kind') || 'percentage_discount'),
    discount_value: Number(formData.get('discount_value')),
    usage_limit_per_customer: Number(formData.get('usage_limit_per_customer') || 1),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/marketing/offers`)
  return { ok: true }
}
