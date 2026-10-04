'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

/** Save one section's words. Posted by a SafeForm, which shows the reason when it is refused. */
export async function saveSectionContent(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId') || '')
  const sectionId = String(formData.get('sectionId') || '')
  const sectionTypeId = String(formData.get('sectionTypeId') || '')
  const layoutVariant = String(formData.get('layoutVariant') || '')
  const headline = String(formData.get('headline') || '')
  const body = String(formData.get('body') || '')
  const rawInitial = String(formData.get('initialContent') || '{}')
  let content: Record<string, unknown> = {}
  try {
    content = JSON.parse(rawInitial) as Record<string, unknown>
  } catch {
    content = {}
  }
  if (sectionTypeId === 'hero' || sectionTypeId === 'cta_band' || 'headline' in content) {
    content.headline = headline
  }
  if ('subheadline' in content) content.subheadline = body
  if ('body' in content || sectionTypeId === 'about' || sectionTypeId === 'text_block') {
    content.body = body
  }

  const r = await sendJson(`/v1/b/${businessId}/website/sections/${sectionId}`, 'PATCH', {
    content, layout_variant: layoutVariant || null,
  })
  if (r.ok) revalidatePath(`/b/${businessId}/website/pages`)
  return r
}
