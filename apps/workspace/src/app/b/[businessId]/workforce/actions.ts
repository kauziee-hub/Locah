'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiPost } from '@/lib/api'

export async function createWorkforceMember(
  businessId: string,
  payload: Record<string, unknown>
) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  await apiPost(
    `/v1/platform/businesses/${businessId}/workforce/members`,
    payload,
    token
  )
  revalidatePath(`/b/${businessId}/workforce`)
  refreshBusinessShell(businessId)
}

export async function deactivateWorkforceMember(businessId: string, memberId: string) {
  const token = await getAccessToken()
  if (!token) throw new Error('Unauthorized')
  await apiPost(
    `/v1/platform/businesses/${businessId}/workforce/members/${memberId}/deactivate`,
    {},
    token
  )
  revalidatePath(`/b/${businessId}/workforce`)
  revalidatePath(`/b/${businessId}/workforce/${memberId}`)
  refreshBusinessShell(businessId)
}
