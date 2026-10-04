'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'
import { asForm, type FormResult } from '@/lib/form-result'

const optional = (v: FormDataEntryValue | null) => (v && String(v).trim() ? String(v).trim() : undefined)

export async function createLead(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/leads`, 'POST', {
    display_name: String(formData.get('display_name') || '').trim(),
    email: optional(formData.get('email')),
    phone: optional(formData.get('phone')),
    message: optional(formData.get('message')),
    source: 'manual',
  })
  if (r.ok) revalidatePath(`/b/${businessId}/leads`)
  return asForm(r)
}

/** Move an enquiry to a stage; losing one needs a reason (from the form). */
export async function moveLeadStage(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const leadId = String(formData.get('leadId'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/leads/${leadId}/move-stage`, 'POST', {
    status: String(formData.get('status')),
    reason: optional(formData.get('reason')),
  })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/leads`)
    revalidatePath(`/b/${businessId}/leads/${leadId}`)
  }
  return asForm(r)
}

/** One-click stage move (contacted, interested, won, reopen). */
export async function setLeadStage(businessId: string, leadId: string, status: string): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/leads/${leadId}/move-stage`, 'POST', { status })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/leads`)
    revalidatePath(`/b/${businessId}/leads/${leadId}`)
  }
  return r
}

export async function addLeadNote(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const leadId = String(formData.get('leadId'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/leads/${leadId}/notes`, 'POST', {
    body: String(formData.get('body') || '').trim(),
  })
  if (r.ok) revalidatePath(`/b/${businessId}/leads/${leadId}`)
  return asForm(r)
}

export async function assignLead(_prev: FormResult, formData: FormData): Promise<FormResult> {
  const businessId = String(formData.get('businessId'))
  const leadId = String(formData.get('leadId'))
  const assignee = String(formData.get('assignee_identity_id') || '')
  const r = await sendJson(`/v1/platform/businesses/${businessId}/leads/${leadId}/assign`, 'POST', {
    assignee_identity_id: assignee || null,
  })
  if (r.ok) revalidatePath(`/b/${businessId}/leads/${leadId}`)
  return asForm(r)
}
