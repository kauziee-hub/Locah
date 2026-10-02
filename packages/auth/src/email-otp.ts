/**
 * Email one-time-code sign-up and sign-in (Doc 09 AUTH-001–AUTH-003; Doc 05
 * §4.4: OTP is a supported ceremony and changes no routing semantics).
 *
 * Why a code and not a link: a confirmation *link* carries a host. When the
 * Supabase project's Site URL or Redirect URLs allowlist does not match the
 * deployment, Supabase silently substitutes Site URL — which is how a real
 * inbox received `http://localhost:3000/...` (infra/supabase/email-templates
 * README). A six-digit code is typed back into the page the person is already
 * on, so nothing in the email depends on any URL configuration, and the
 * Destination Intent never leaves this browser tab.
 *
 * Supabase Auth stays the identity provider: `signInWithOtp` sends the code
 * (creating the Platform Identity's auth user on first use when allowed) and
 * `verifyOtp` establishes the cookie session through `@supabase/ssr`. No code is
 * stored or checked here, and no service-role key is involved.
 *
 * UI lives in each app (their visual contexts must not converge); this module
 * is the shared, framework-free part.
 */

import type { SupabaseClient } from '@supabase/supabase-js'

/** The part of a Supabase client the code ceremony uses (any browser client). */
export type OtpAuthClient = { auth: Pick<SupabaseClient['auth'], 'signInWithOtp' | 'verifyOtp'> }

/** Supabase's default (and this project's configured) code length. */
export const OTP_LENGTH = 6

/** Seconds before a new code may be requested from the same page. */
export const RESEND_COOLDOWN_SECONDS = 60

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

export function normalizeEmail(raw: string): string {
  return raw.trim().toLowerCase()
}

export function isEmail(raw: string): boolean {
  return EMAIL.test(normalizeEmail(raw))
}

/** Keep the digits a person typed or pasted ("123 456", "123-456"), at most six. */
export function normalizeOtp(raw: string): string {
  return raw.replace(/\D/g, '').slice(0, OTP_LENGTH)
}

export function isCompleteOtp(raw: string): boolean {
  return normalizeOtp(raw).length === OTP_LENGTH
}

export type OtpProblem =
  | 'incomplete_code'
  | 'wrong_or_expired_code'
  | 'rate_limited'
  | 'no_account'
  | 'invalid_email'
  | 'unknown'

/**
 * What went wrong, from the provider's error, in terms a screen can act on.
 * The provider's own wording describes its internals and is never shown.
 */
export function classifyOtpError(error: { message?: string; code?: string; status?: number } | null): OtpProblem {
  if (!error) return 'unknown'
  const code = (error.code || '').toLowerCase()
  const m = (error.message || '').toLowerCase()
  // Supabase answers a mistyped code and an expired one identically
  // ("Token has expired or is invalid", otp_expired), so they are one problem.
  if (code === 'otp_expired' || m.includes('expired') || (m.includes('invalid') &&
      (m.includes('token') || m.includes('otp') || m.includes('code')))) return 'wrong_or_expired_code'
  if (code === 'over_email_send_rate_limit' || code === 'over_request_rate_limit' || error.status === 429 ||
      m.includes('rate limit') || m.includes('too many') || m.includes('security purposes')) return 'rate_limited'
  if (code === 'otp_disabled' || code === 'signup_disabled' || m.includes('signups not allowed') ||
      m.includes('user not found')) return 'no_account'
  if (code === 'validation_failed' && m.includes('email')) return 'invalid_email'
  return 'unknown'
}

export const OTP_PROBLEM_WORDS: Record<OtpProblem, string> = {
  incomplete_code: 'Enter all 6 digits from the email.',
  wrong_or_expired_code: 'That code is not right or has expired. Check the latest email, or send a new code.',
  rate_limited: 'Too many attempts. Wait a minute, then try again.',
  no_account: 'There is no account with this email yet. Create one instead.',
  invalid_email: 'That does not look like an email address.',
  unknown: 'We could not do that just now. Try again in a moment.',
}

/**
 * Email a code. `createAccount` decides whether an unknown email becomes a new
 * Platform Identity (sign-up) or is refused (sign-in).
 */
export async function requestEmailOtp(
  supabase: OtpAuthClient,
  email: string,
  { createAccount }: { createAccount: boolean },
): Promise<{ ok: true } | { ok: false; problem: OtpProblem }> {
  if (!isEmail(email)) return { ok: false, problem: 'invalid_email' }
  const { error } = await supabase.auth.signInWithOtp({
    email: normalizeEmail(email),
    options: { shouldCreateUser: createAccount },
  })
  return error ? { ok: false, problem: classifyOtpError(error) } : { ok: true }
}

/** Check the code with Supabase; on success the session cookie is set. */
export async function verifyEmailOtp(
  supabase: OtpAuthClient,
  email: string,
  code: string,
): Promise<{ ok: true } | { ok: false; problem: OtpProblem }> {
  if (!isCompleteOtp(code)) return { ok: false, problem: 'incomplete_code' }
  const { data, error } = await supabase.auth.verifyOtp({
    email: normalizeEmail(email),
    token: normalizeOtp(code),
    type: 'email',
  })
  if (error || !data?.session) return { ok: false, problem: classifyOtpError(error) }
  return { ok: true }
}
