'use server'

import { sendJson, type ActionResult } from '@/lib/server-send'

export type TraceStep = {
  kind: string
  label: string
  detail: string
  tool?: string
  tier?: string | null
  decision?: string
  contract?: string
  module?: string
  ok?: boolean
  action?: string
}
export type Proposal = { action: 'order' | 'booking' | 'lead'; summary: string } & Record<string, unknown>
export type Turn = {
  scenario: string
  reply: string
  trace: TraceStep[]
  proposal: Proposal | null
  simulated: true
  notice: string
}
export type Approval = {
  ok: boolean
  reference: string | null
  result: string
  trace: TraceStep[]
  simulated: true
  notice: string
}

/** One customer message, handled the way the AI employee would. The API reads
 *  real records and writes nothing, so there is nothing to revalidate. */
export async function simulate(businessId: string, scenario: string, message: string): Promise<ActionResult<Turn>> {
  return sendJson<Turn>(`/v1/b/${businessId}/ai-employees/sandbox/simulate`, 'POST', { scenario, message })
}

/** Approve a proposal inside the sandbox: re-checked live, never created. */
export async function approve(businessId: string, proposal: Proposal): Promise<ActionResult<Approval>> {
  return sendJson<Approval>(`/v1/b/${businessId}/ai-employees/sandbox/approve`, 'POST', proposal)
}
