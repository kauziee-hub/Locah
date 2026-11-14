'use server'

import { revalidatePath } from 'next/cache'
import { getAccessToken } from '@/lib/supabase/access-token'
import { platformUrl } from '@platform/config'

/**
 * Arranging and styling the site, and asking LOCAH to do either.
 *
 * Every action here is one call to an endpoint the API already governs —
 * reorder, show/hide, duplicate, remove, add, the theme merge, the assistant.
 * Nothing is decided in the browser: what an owner may add, which styles
 * exist and whether a change is allowed are all the server's answers.
 */

export type Result<T = unknown> = { ok: true; data: T } | { ok: false; error: string }

async function call<T>(
  businessId: string,
  path: string,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
  failure = 'That did not work'
): Promise<Result<T>> {
  const token = await getAccessToken()
  if (!token) return { ok: false, error: 'Your session expired — sign in again.' }
  let res: Response
  try {
    res = await fetch(`${platformUrl('api')}/v1/b/${businessId}/website${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    })
  } catch {
    return { ok: false, error: `${failure} — LOCAH could not be reached. Try again.` }
  }
  type Body = { data?: T; error?: { message?: string }; detail?: { message?: string } }
  const json: Body | null = await res.json().then(
    (value) => value as Body,
    () => null
  )
  if (!res.ok) {
    const said = json?.error?.message || json?.detail?.message
    return { ok: false, error: said || `${failure} (${res.status}).` }
  }
  if (method !== 'GET') revalidatePath(`/b/${businessId}/website/preview`)
  return { ok: true, data: (json?.data ?? null) as T }
}

export async function reorderSections(businessId: string, pageId: string, sectionIds: string[]) {
  return call(businessId, `/pages/${pageId}/sections/reorder`, 'POST', { section_ids: sectionIds },
    'The new order was not saved')
}

export async function setSectionVisible(businessId: string, sectionId: string, visible: boolean) {
  return call(businessId, `/sections/${sectionId}`, 'PATCH', { is_visible: visible },
    visible ? 'That section could not be shown' : 'That section could not be hidden')
}

export async function setSectionLayout(businessId: string, sectionId: string, layout: string) {
  return call(businessId, `/sections/${sectionId}`, 'PATCH', { layout_variant: layout },
    'That layout could not be used')
}

export async function duplicateSection(businessId: string, sectionId: string) {
  return call(businessId, `/sections/${sectionId}/duplicate`, 'POST', undefined,
    'That section could not be copied')
}

export async function removeSection(businessId: string, sectionId: string) {
  return call(businessId, `/sections/${sectionId}`, 'DELETE', undefined, 'That section could not be removed')
}

export type SectionType = {
  id: string
  label: string
  description: string | null
  allowed_variants: string[]
  requires_module: string | null
  available: boolean
  /** The API can add it as it stands (its starter words satisfy its schema). */
  can_start: boolean
}

export async function listSectionTypes(businessId: string) {
  return call<{ section_types: SectionType[] }>(businessId, '/section-types', 'GET', undefined,
    'The list of sections did not load')
}

/** Added with the section's own starter words; the owner then makes them theirs. */
export async function addSection(businessId: string, pageId: string, sectionTypeId: string, position?: number) {
  return call<{ id: string }>(businessId, `/pages/${pageId}/sections`, 'POST',
    { section_type_id: sectionTypeId, ...(position === undefined ? {} : { position }) },
    'That section could not be added')
}

export type StyleOptions = {
  fonts: { id: string; label: string; note: string; display: string; body: string }[]
  sizes: string[]
  corners: string[]
}

export async function loadStyleOptions(businessId: string) {
  return call<StyleOptions>(businessId, '/style-options', 'GET', undefined, 'The style choices did not load')
}

/** A theme edit is laid over the stored theme by the API; send only what changed. */
export async function saveThemeEdit(businessId: string, edit: Record<string, unknown>) {
  return call<{ theme: Record<string, unknown> }>(businessId, '/theme', 'PATCH', { theme: edit },
    'That style was not saved')
}

export async function saveNavigation(businessId: string, navigation: { label: string; path: string }[]) {
  return call(businessId, '/theme', 'PATCH', { navigation }, 'The menu was not saved')
}

export type AssistantReply = {
  reply: string
  done: string[]
  not_done: string[]
  changed: boolean
  structure_changed: boolean
  theme_changed: boolean
  jobs: unknown[]
}

export async function askLocah(businessId: string, message: string, pageId?: string) {
  return call<AssistantReply>(businessId, '/assistant', 'POST',
    { message, ...(pageId ? { page_id: pageId } : {}) }, 'LOCAH could not make that change')
}

export type ReferenceReply = {
  matched?: boolean
  undone?: boolean
  reply: string
  kept?: string[]
  dropped?: string[]
  mood?: string[]
  theme?: Record<string, unknown>
}

/** "Make it look like this": a screenshot of a design the owner likes, read
 *  into their own site's colours, lettering, corners and scale. */
export async function matchReference(businessId: string, imageBase64: string, mimeType: string) {
  return call<ReferenceReply>(businessId, '/reference-style', 'POST',
    { image_base64: imageBase64, mime_type: mimeType }, 'LOCAH could not use that picture')
}

export async function undoReference(businessId: string) {
  return call<ReferenceReply>(businessId, '/reference-style', 'POST', { undo: true },
    'That could not be undone')
}
