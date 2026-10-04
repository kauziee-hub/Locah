import { getAccessToken } from '@/lib/supabase/access-token'
import { platformUrl } from '@platform/config'

const apiUrl = platformUrl('api')

export type ActionResult<T = unknown> = { ok: true; data?: T } | { ok: false; message: string }

/**
 * One JSON call to the platform API as the signed-in person, for server
 * actions. The API decides what they may do; this only carries their token
 * and turns a refusal into a sentence the page can show.
 */
export async function sendJson<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  const token = await getAccessToken()
  if (!token) return { ok: false, message: 'Your session ended. Sign in again.' }
  const res = await fetch(`${apiUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  })
  let payload: { data?: T; error?: { message?: string }; detail?: unknown } | null = null
  try {
    payload = await res.json()
  } catch {
    /* empty or non-JSON body */
  }
  if (res.ok) return { ok: true, data: payload?.data }
  return { ok: false, message: payload?.error?.message ?? fieldProblem(payload?.detail) ?? 'That did not save. Try again.' }
}

type FieldIssue = { type?: string; loc?: (string | number)[]; msg?: string; ctx?: Record<string, unknown> }

/**
 * A value the API's request checks refused ({"detail": [...]}), as a sentence:
 * "Hold minutes must be at least 5." — not "That did not save".
 */
export function fieldProblem(detail: unknown): string | null {
  if (!Array.isArray(detail) || !detail.length) return null
  const issue = detail[0] as FieldIssue
  const field = [...(issue.loc ?? [])].reverse().find((p) => typeof p === 'string' && p !== 'body')
  const name = field ? String(field).replace(/_/g, ' ') : 'A value'
  const label = name.charAt(0).toUpperCase() + name.slice(1)
  const ctx = issue.ctx ?? {}
  const says: Record<string, string> = {
    greater_than_equal: `must be at least ${ctx.ge}`,
    greater_than: `must be more than ${ctx.gt}`,
    less_than_equal: `must be at most ${ctx.le}`,
    less_than: `must be less than ${ctx.lt}`,
    missing: 'is needed',
    string_too_long: `is too long (at most ${ctx.max_length} characters)`,
    string_too_short: 'is too short',
    int_parsing: 'must be a whole number',
    float_parsing: 'must be a number',
    extra_forbidden: 'is not something this form takes',
  }
  const why = says[issue.type ?? ''] ?? (issue.msg ? issue.msg.charAt(0).toLowerCase() + issue.msg.slice(1) : 'is not valid')
  return `${label} ${why}.`
}
