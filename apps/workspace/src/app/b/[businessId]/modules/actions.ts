'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
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

export async function setModuleState(formData: FormData) {
  const businessId = String(formData.get('businessId'))
  const moduleId = String(formData.get('moduleId'))
  const action = String(formData.get('action'))
  await send(`/v1/b/${businessId}/modules/${moduleId}/${action}`, 'POST')
  revalidatePath(`/b/${businessId}/modules`)
  revalidatePath(`/b/${businessId}/modules/${moduleId}`)
  refreshBusinessShell(businessId)
}
