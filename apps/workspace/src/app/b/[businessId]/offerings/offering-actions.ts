'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'

export async function saveOffering(
  businessId: string,
  offeringId: string | null,
  body: Record<string, unknown>,
): Promise<ActionResult<{ id: string }>> {
  const r = offeringId
    ? await sendJson<{ id: string }>(`/v1/platform/businesses/${businessId}/products/${offeringId}`, 'PATCH', body)
    : await sendJson<{ id: string }>(`/v1/platform/businesses/${businessId}/products`, 'POST', body)
  if (r.ok) {
    revalidatePath(`/b/${businessId}/offerings`)
    if (offeringId) revalidatePath(`/b/${businessId}/offerings/${offeringId}`)
    refreshBusinessShell(businessId)
  }
  return r
}

export async function makeVariants(businessId: string, offeringId: string): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/products/${offeringId}/variants/matrix`, 'POST')
  if (r.ok) revalidatePath(`/b/${businessId}/offerings/${offeringId}`)
  return r
}

export async function setArchived(businessId: string, offeringId: string, archived: boolean): Promise<ActionResult> {
  const r = await sendJson(
    `/v1/platform/businesses/${businessId}/products/${offeringId}/${archived ? 'archive' : 'restore'}`,
    'POST',
  )
  if (r.ok) {
    revalidatePath(`/b/${businessId}/offerings`)
    refreshBusinessShell(businessId)
  }
  return r
}

function pictureChanged(businessId: string, offeringId: string) {
  revalidatePath(`/b/${businessId}/offerings`)
  revalidatePath(`/b/${businessId}/offerings/${offeringId}`)
  refreshBusinessShell(businessId)
}

/** Step 1 of an offering photo upload: a signed URL the browser PUTs the file to (Doc 12 §15.3). */
export async function startPictureUpload(
  businessId: string,
  file: { type: string; size: number; name: string },
): Promise<ActionResult<{ assetId: string; uploadUrl: string }>> {
  const r = await sendJson<{ asset: { id: string }; upload: { upload_url: string } }>(
    `/v1/b/${businessId}/media/upload-url`,
    'POST',
    { purpose: 'offering', mime_type: file.type, size_bytes: file.size, original_filename: file.name },
  )
  if (!r.ok) return r
  return { ok: true, data: { assetId: r.data!.asset.id, uploadUrl: r.data!.upload.upload_url } }
}

/** Step 2: confirm the upload, then make it this offering's first picture (older ones are kept). */
export async function finishPictureUpload(
  businessId: string,
  offeringId: string,
  assetId: string,
  current: string[],
): Promise<ActionResult> {
  const done = await sendJson(`/v1/b/${businessId}/media/${assetId}/complete`, 'POST')
  if (!done.ok) return done
  return setPictures(businessId, offeringId, [assetId, ...current.filter((id) => id !== assetId)])
}

/** The offering's pictures, in order — removing one never deletes the file. */
export async function setPictures(businessId: string, offeringId: string, ids: string[]): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/products/${offeringId}`, 'PATCH', {
    image_asset_ids: ids,
  })
  if (r.ok) pictureChanged(businessId, offeringId)
  return r
}

/** Draw an illustrative picture of this offering — a draft the owner keeps or replaces. */
export async function drawPicture(businessId: string, offeringId: string): Promise<ActionResult> {
  const r = await sendJson<{ ok: boolean; detail?: string }>(
    `/v1/platform/businesses/${businessId}/products/${offeringId}/generate-image`,
    'POST',
  )
  if (!r.ok) return r
  if (!r.data?.ok) return { ok: false, message: r.data?.detail ?? 'No picture could be drawn. Upload one instead.' }
  pictureChanged(businessId, offeringId)
  return { ok: true }
}

/** Keep a picture LOCAH drew (it stays marked as generated). */
export async function keepPicture(businessId: string, offeringId: string, assetId: string): Promise<ActionResult> {
  const r = await sendJson(`/v1/b/${businessId}/media/${assetId}/approve`, 'POST')
  if (r.ok) pictureChanged(businessId, offeringId)
  return r
}

/**
 * Bring in what the owner named while setting up with LOCAH, as private,
 * unpriced drafts — the interview's own "set up" command, which skips anything
 * already in the catalogue. Nothing goes live until the owner makes it live.
 */
export async function addFromConversation(businessId: string, revision: number): Promise<ActionResult> {
  const r = await sendJson(`/v1/b/${businessId}/interview`, 'POST', {
    action: 'setup',
    revision,
    request_id: crypto.randomUUID(),
  })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/offerings`)
    refreshBusinessShell(businessId)
  }
  return r
}
