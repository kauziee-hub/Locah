'use server'

import { revalidatePath } from 'next/cache'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiPost } from '@/lib/api'

/** Put a dead-lettered payment webhook back into the retry lane, as the signed-in Super Admin. */
export async function retryPaymentWebhook(formData: FormData) {
  const receiptId = String(formData.get('receiptId') || '')
  const token = await getAccessToken()
  if (!token) {
    throw new Error('Not signed in')
  }
  await apiPost(`/v1/admin/payment-webhooks/${receiptId}/retry`, undefined, token)
  revalidatePath('/system')
}
