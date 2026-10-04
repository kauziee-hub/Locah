'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'
import { asForm, type FormResult } from '@/lib/form-result'

/** Move a pickup or delivery job to its next step; failing or cancelling carries a reason. */
export async function setJobStatus(
  businessId: string,
  jobId: string,
  status: string,
  reason?: string,
): Promise<ActionResult> {
  const r = await sendJson(`/v1/b/${businessId}/fulfilment/jobs/${jobId}/status`, 'PATCH', { status, reason })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/fulfilment/${jobId}`)
    revalidatePath(`/b/${businessId}/fulfilment`)
  }
  return r
}

/** "Couldn't complete" with the reason the owner typed. */
export async function failJob(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const jobId = String(formData.get('jobId'))
  return asForm(await setJobStatus(businessId, jobId, 'failed', String(formData.get('reason') || '').trim() || undefined))
}

export async function createZone(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const kind = String(formData.get('match_type') || 'city')
  const where = String(formData.get('where') || '').trim()
  const r = await sendJson(`/v1/b/${businessId}/fulfilment/zones`, 'POST', {
    name: String(formData.get('name') || '').trim() || where,
    match_type: kind,
    city: kind === 'city' ? where : undefined,
    postal_prefix: kind === 'postal_prefix' ? where.replace(/\s+/g, '') : undefined,
    charge_amount: Number(formData.get('charge_amount') || 0),
  })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/fulfilment/zones`)
    revalidatePath(`/b/${businessId}/fulfilment`)
    refreshBusinessShell(businessId)
  }
  return asForm(r)
}

/** Switch a delivery zone off or back on. */
export async function setZoneActive(businessId: string, zoneId: string, active: boolean): Promise<ActionResult> {
  const r = await sendJson(`/v1/b/${businessId}/fulfilment/zones/${zoneId}`, 'PATCH', { is_active: active })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/fulfilment/zones`)
    refreshBusinessShell(businessId)
  }
  return r
}

export async function updateFulfilmentSettings(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const r = await sendJson(`/v1/b/${businessId}/fulfilment/settings`, 'PATCH', {
    pickup_enabled: formData.get('pickup_enabled') === 'on',
    delivery_enabled: formData.get('delivery_enabled') === 'on',
  })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/fulfilment`)
    revalidatePath(`/b/${businessId}/fulfilment/zones`)
    refreshBusinessShell(businessId)
  }
  return asForm(r)
}

/** Paying on delivery / at pickup — one rule for the website and WhatsApp (Founder: Orders; Payments §5). */
export async function updatePaymentRules(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const cap = String(formData.get('first_order_cod_cap') || '').trim()
  const r = await sendJson(`/v1/b/${businessId}/fulfilment/settings`, 'PATCH', {
    cod_allowed: formData.get('cod_allowed') === 'on',
    first_order_cod_cap: cap ? Number(cap) : null,
  })
  if (r.ok) revalidatePath(`/b/${businessId}/fulfilment/zones`)
  return asForm(r)
}
