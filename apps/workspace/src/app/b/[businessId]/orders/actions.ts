'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

function refresh(businessId: string, orderId: string) {
  revalidatePath(`/b/${businessId}/orders/${orderId}`)
  revalidatePath(`/b/${businessId}/orders`)
}

/** Move an order to its next step (accept, preparing, ready, completed) or reject it. */
export async function setOrderStatus(
  businessId: string,
  orderId: string,
  status: string,
  reason?: string,
): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/orders/${orderId}/status`, 'POST', { status, reason })
  if (r.ok) refresh(businessId, orderId)
  return r
}

export async function cancelOrder(businessId: string, orderId: string, reason: string): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/orders/${orderId}/cancel`, 'POST', { reason })
  if (r.ok) refresh(businessId, orderId)
  return r
}
