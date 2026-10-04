import type { ActionResult } from '@/lib/server-send'

/** What a form's server action answers (components/ActionForm). `null` before the first submit. */
export type FormResult = { ok: true } | { ok: false; message: string } | null

/** An API call's result as a form answer. */
export function asForm(r: ActionResult): FormResult {
  return r.ok ? { ok: true } : { ok: false, message: r.message }
}
