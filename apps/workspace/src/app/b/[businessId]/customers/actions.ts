'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'
import { asForm, type FormResult } from '@/lib/form-result'

const optional = (v: FormDataEntryValue | null) => (v && String(v).trim() ? String(v).trim() : undefined)

export async function createCustomer(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/customers`, 'POST', {
    display_name: String(formData.get('display_name') || '').trim(),
    email: optional(formData.get('email')),
    phone: optional(formData.get('phone')),
  })
  if (r.ok) revalidatePath(`/b/${businessId}/customers`)
  return asForm(r)
}

export async function setCustomerState(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const customerId = String(formData.get('customerId'))
  const action = String(formData.get('action'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/customers/${customerId}/${action}`, 'POST')
  if (r.ok) {
    revalidatePath(`/b/${businessId}/customers`)
    revalidatePath(`/b/${businessId}/customers/${customerId}`)
  }
  return asForm(r)
}

export async function addCustomerNote(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const customerId = String(formData.get('customerId'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/customers/${customerId}/notes`, 'POST', {
    body: String(formData.get('body') || '').trim(),
  })
  if (r.ok) revalidatePath(`/b/${businessId}/customers/${customerId}`)
  return asForm(r)
}

/** Block, archive or restore a customer record (from a confirm button). */
export async function changeCustomerState(businessId: string, customerId: string, action: string): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/customers/${customerId}/${action}`, 'POST')
  if (r.ok) {
    revalidatePath(`/b/${businessId}/customers`)
    revalidatePath(`/b/${businessId}/customers/${customerId}`)
  }
  return r
}
