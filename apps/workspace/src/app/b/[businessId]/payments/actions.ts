'use server'

import { revalidatePath } from 'next/cache'
import { getAccessToken } from '@/lib/supabase/access-token'
import { platformUrl } from '@platform/config'
import { sendJson, type ActionResult } from '@/lib/server-send'

const apiUrl = platformUrl('api')

/** Money for a pay-later / pay-at-the-business payment was received in person. */
export async function markPaymentReceived(businessId: string, paymentId: string): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/payments/${paymentId}/record-settlement`, 'POST', {})
  if (r.ok) {
    revalidatePath(`/b/${businessId}/payments`)
    revalidatePath(`/b/${businessId}/payments/${paymentId}`)
  }
  return r
}

/**
 * Record a refund. The idempotency key is made once per form: a double-click or
 * a retried request records the refund once.
 */
export async function recordRefund(
  businessId: string,
  paymentId: string,
  body: { amount: number; reason: string; idempotency_key: string },
): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/payments/${paymentId}/refunds`, 'POST', body)
  if (r.ok) {
    revalidatePath(`/b/${businessId}/payments`)
    revalidatePath(`/b/${businessId}/payments/${paymentId}`)
  }
  return r
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

/** The UPI ID customers pay on payment links (the counter uses the same one). */
export async function saveUpi(
  businessId: string,
  body: { upi_vpa: string | null; upi_payee_name: string | null },
): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/payments/upi`, 'PUT', body)
  if (r.ok) revalidatePath(`/b/${businessId}/payments`)
  return r
}
