'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

export async function addStation(businessId: string, body: { key?: string; name?: string }): Promise<ActionResult> {
  const r = await send(`/v1/platform/businesses/${businessId}/kitchen/stations`, 'POST', body)

  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/kitchen`)
  return { ok: true }
}

export async function saveRoute(businessId: string, offeringId: string, stationIds: string[]): Promise<ActionResult> {
  const r = await send(`/v1/platform/businesses/${businessId}/kitchen/routes`, 'PUT', {
    offering_id: offeringId,
    station_ids: stationIds,
  })

  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/kitchen`)
  return { ok: true }
}
