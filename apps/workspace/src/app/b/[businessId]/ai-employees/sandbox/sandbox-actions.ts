'use server'

import { revalidatePath } from 'next/cache'
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

export type TestRecord = {
  id: string
  kind: 'order' | 'booking' | 'lead'
  kind_label: string
  reference: string
  scenario: string
  summary: string
  detail: Record<string, unknown>
  amount: number | null
  status: string
  status_label: string
  payment: { adapter: string; status: string; method: string; reference: string; reason?: string } | null
  can_pay: boolean
  created_at: string | null
}
export type TestResult = Omit<Approval, 'simulated'> & { record: TestRecord | null }

/** Approve a proposal in Test Mode: re-checked live, then kept as a TEST
 *  record only — never a real order, booking or enquiry. */
export async function approveInTestMode(
  businessId: string, scenario: string, proposal: Proposal,
): Promise<ActionResult<TestResult>> {
  const r = await sendJson<TestResult>(`/v1/b/${businessId}/ai-employees/test-records`, 'POST', { ...proposal, scenario })
  if (r.ok) revalidatePath(`/b/${businessId}/ai-employees/sandbox`)
  return r
}

/** A test payment through the test adapter: no provider, no money. */
export async function payTestRecord(formData: FormData): Promise<void> {
  const businessId = String(formData.get('businessId'))
  await sendJson(`/v1/b/${businessId}/ai-employees/test-records/${String(formData.get('recordId'))}/pay`, 'POST', {
    outcome: String(formData.get('outcome')) === 'fail' ? 'fail' : 'succeed',
  })
  revalidatePath(`/b/${businessId}/ai-employees/sandbox`)
}

export async function clearTestRecords(formData: FormData): Promise<void> {
  const businessId = String(formData.get('businessId'))
  await sendJson(`/v1/b/${businessId}/ai-employees/test-records/clear`, 'POST')
  revalidatePath(`/b/${businessId}/ai-employees/sandbox`)
}
