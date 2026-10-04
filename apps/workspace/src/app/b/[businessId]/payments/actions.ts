'use server'

import { revalidatePath } from 'next/cache'
import { getAccessToken } from '@/lib/supabase/access-token'
import { platformUrl } from '@platform/config'

const apiUrl = platformUrl('api')

async function send(path: string, method: string, body?: unknown) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  const res = await fetch(`${apiUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status} ${await res.text()}`)
  return res.json()
}

export async function recordSettlement(formData: FormData) {
  const businessId = String(formData.get('businessId'))
  const paymentId = String(formData.get('paymentId'))
  await send(
    `/v1/platform/businesses/${businessId}/payments/${paymentId}/record-settlement`,
    'POST',
    {}
  )
  revalidatePath(`/b/${businessId}/payments`)
  revalidatePath(`/b/${businessId}/payments/${paymentId}`)
}

export async function refundPayment(formData: FormData) {
  const businessId = String(formData.get('businessId'))
  const paymentId = String(formData.get('paymentId'))
  await send(`/v1/platform/businesses/${businessId}/payments/${paymentId}/refunds`, 'POST', {
    amount: Number(formData.get('amount')),
    reason: String(formData.get('reason')),
    idempotency_key: String(formData.get('idempotency_key') || '') || undefined,
  })
  revalidatePath(`/b/${businessId}/payments`)
  revalidatePath(`/b/${businessId}/payments/${paymentId}`)
}

export type RazorpayState = { ok: boolean; error: string | null; status?: string }

/** Try a request that may legitimately fail (bad credentials) — return the
 * reason instead of throwing, so the form can show it. */
async function trySend(
  path: string,
  method: string,
  body?: unknown
): Promise<{ ok: boolean; data?: Record<string, unknown>; error?: string; code?: string }> {
  const token = await getAccessToken()
  if (!token) return { ok: false, error: 'Your session expired. Sign in again.' }
  const res = await fetch(`${apiUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  })
  const json = await res.json().catch(() => null)
  if (!res.ok) {
    return {
      ok: false,
      error: json?.error?.message || `Request failed (${res.status})`,
      code: json?.error?.code,
    }
  }
  return { ok: true, data: json?.data }
}

export async function enablePlatformPayments(
  _prev: RazorpayState,
  formData: FormData
): Promise<RazorpayState> {
  const businessId = String(formData.get('businessId'))
  const r = await trySend(
    `/v1/platform/businesses/${businessId}/payments/razorpay/enable`,
    'POST'
  )
  revalidatePath(`/b/${businessId}/payments`)
  if (!r.ok) return { ok: false, error: r.error ?? 'Could not enable online payments.' }
  const status = String(r.data?.status ?? '')
  if (status === 'active') {
    return { ok: true, error: null, status }
  }
  return {
    ok: false,
    status,
    error:
      String(r.data?.verification_error ?? '') ||
      'Razorpay could not finish linking this business yet. Cash still works.',
  }
}

export async function connectRazorpay(
  _prev: RazorpayState,
  formData: FormData
): Promise<RazorpayState> {
  const businessId = String(formData.get('businessId'))
  const keyId = String(formData.get('key_id') || '').trim()
  const keySecret = String(formData.get('key_secret') || '').trim()
  if (!keyId || !keySecret) {
    return { ok: false, error: 'Enter both the Key ID and the Key Secret.' }
  }

  const r = await trySend(
    `/v1/platform/businesses/${businessId}/payments/razorpay/connect`,
    'POST',
    { key_id: keyId, key_secret: keySecret }
  )
  revalidatePath(`/b/${businessId}/payments`)
  if (!r.ok) return { ok: false, error: r.error ?? 'Could not save the credentials.' }

  const status = String(r.data?.status ?? '')
  if (status === 'active') {
    return { ok: true, error: null, status }
  }
  return {
    ok: false,
    status,
    error:
      String(r.data?.verification_error ?? '') ||
      'Saved, but Razorpay did not verify the credentials.',
  }
}

export async function verifyRazorpay(
  _prev: RazorpayState,
  formData: FormData
): Promise<RazorpayState> {
  const businessId = String(formData.get('businessId'))
  const r = await trySend(
    `/v1/platform/businesses/${businessId}/payments/razorpay/verify`,
    'POST'
  )
  revalidatePath(`/b/${businessId}/payments`)
  if (!r.ok) return { ok: false, error: r.error ?? 'Verification failed.' }
  const status = String(r.data?.status ?? '')
  return status === 'active'
    ? { ok: true, error: null, status }
    : {
        ok: false,
        status,
        error: String(r.data?.verification_error ?? '') || 'Razorpay did not verify.',
      }
}
