'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { getAccessToken } from '@/lib/supabase/access-token'
import { platformUrl } from '@platform/config'

const apiUrl = platformUrl('api')

export async function updateJobStatus(formData: FormData) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  const businessId = String(formData.get('businessId'))
  const jobId = String(formData.get('jobId'))
  const status = String(formData.get('status'))
  const reason = formData.get('reason') ? String(formData.get('reason')) : undefined
  await fetch(`${apiUrl}/v1/b/${businessId}/fulfilment/jobs/${jobId}/status`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ status, reason }),
  })
  revalidatePath(`/b/${businessId}/fulfilment/${jobId}`)
  revalidatePath(`/b/${businessId}/fulfilment`)
}

export async function createZone(formData: FormData) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  const businessId = String(formData.get('businessId'))
  await fetch(`${apiUrl}/v1/b/${businessId}/fulfilment/zones`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      name: String(formData.get('name')),
      match_type: 'city',
      city: String(formData.get('city')),
      charge_amount: Number(formData.get('charge_amount') || 0),
    }),
  })
  revalidatePath(`/b/${businessId}/fulfilment/zones`)
}

export async function updateFulfilmentSettings(formData: FormData) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  const businessId = String(formData.get('businessId'))
  await fetch(`${apiUrl}/v1/b/${businessId}/fulfilment/settings`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      pickup_enabled: formData.get('pickup_enabled') === 'on',
      delivery_enabled: formData.get('delivery_enabled') === 'on',
    }),
  })
  revalidatePath(`/b/${businessId}/fulfilment`)
  revalidatePath(`/b/${businessId}/fulfilment/zones`)
  refreshBusinessShell(businessId)
}

/** Paying on delivery / at pickup — one rule for the website and WhatsApp (Founder: Orders; Payments §5). */
export async function updatePaymentRules(formData: FormData) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  const businessId = String(formData.get('businessId'))
  const cap = String(formData.get('first_order_cod_cap') || '').trim()
  await fetch(`${apiUrl}/v1/b/${businessId}/fulfilment/settings`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      cod_allowed: formData.get('cod_allowed') === 'on',
      first_order_cod_cap: cap ? Number(cap) : null,
    }),
  })
  revalidatePath(`/b/${businessId}/fulfilment/zones`)
}
