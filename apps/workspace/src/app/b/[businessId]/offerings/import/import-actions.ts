'use server'

import { revalidatePath } from 'next/cache'
import { refreshBusinessShell } from '@/lib/refresh'
import { sendJson, type ActionResult } from '@/lib/server-send'
import type { CheckResult, CommitResult, ImportBatch, MappedRow, SheetRead } from './types'

const path = (businessId: string, rest = '') => `/v1/platform/businesses/${businessId}/catalogue-import${rest}`

/** A sheet, PDF or photo (base64), or a menu pasted as text. */
export async function readImport(
  businessId: string,
  input: { filename: string; content_base64: string } | { text: string },
): Promise<ActionResult<SheetRead>> {
  return sendJson<SheetRead>(path(businessId, '/read'), 'POST', input)
}

export async function checkImport(
  businessId: string,
  rows: MappedRow[],
  defaultKind: string | null,
): Promise<ActionResult<CheckResult>> {
  return sendJson<CheckResult>(path(businessId, '/check'), 'POST', { rows, default_kind: defaultKind })
}

export async function commitImport(
  businessId: string,
  body: {
    filename: string
    file_hash: string
    source: string
    rows: MappedRow[]
    decisions: Record<string, string>
    default_kind: string | null
  },
): Promise<ActionResult<CommitResult>> {
  const r = await sendJson<CommitResult>(path(businessId), 'POST', body)
  if (r.ok) {
    revalidatePath(`/b/${businessId}/offerings`)
    refreshBusinessShell(businessId)
  }
  return r
}

export async function loadImport(businessId: string, importId: string): Promise<ActionResult<ImportBatch>> {
  return sendJson<ImportBatch>(path(businessId, `/${importId}`), 'GET')
}

export async function makeImportLive(
  businessId: string,
  importId: string,
  offeringIds: string[],
): Promise<ActionResult<{ live: number; results: { id: string; result: string; problem?: string }[] }>> {
  const r = await sendJson<{ live: number; results: { id: string; result: string; problem?: string }[] }>(
    path(businessId, `/${importId}/make-live`), 'POST', { offering_ids: offeringIds })
  if (r.ok) {
    revalidatePath(`/b/${businessId}/offerings`)
    refreshBusinessShell(businessId)
  }
  return r
}
