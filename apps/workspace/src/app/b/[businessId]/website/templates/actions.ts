'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { sendJson, type ActionResult } from '@/lib/server-send'

/**
 * Apply a template to the draft.
 *
 * The API owns what this means — including refusing a template whose modules
 * are off, and replacing the draft rather than merging into it. Nothing is
 * decided here; the failure the owner sees is the API's own sentence.
 */
export async function applyTemplate(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const templateId = String(formData.get('templateId'))
  const r = await sendJson(`/v1/b/${businessId}/website/templates/apply`, 'POST', { template_id: templateId })
  if (!r.ok) return r

  revalidatePath(`/b/${businessId}/website`)
  revalidatePath(`/b/${businessId}/website/templates`)
  revalidatePath(`/b/${businessId}/website/preview`)
  // Straight to the editor: the point of choosing a template is to start
  // working on it, not to admire the confirmation.
  redirect(`/b/${businessId}/website/preview`)
}
