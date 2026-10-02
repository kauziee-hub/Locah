// Email one-time codes and Destination Intent (Doc 05 §4, §14; Doc 12 §6.6).
// Run: pnpm --filter @platform/auth test  (builds, then node --test).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  classifyOtpError,
  isCompleteOtp,
  normalizeOtp,
  OTP_PROBLEM_WORDS,
  requestEmailOtp,
  verifyEmailOtp,
} from '../dist/email-otp.js'
import { isValidDestinationIntent, resolveDestinationIntent } from '../dist/redirects.js'

/** A stand-in for supabase-js's `auth` surface, recording what was asked. */
function fakeSupabase({ otpError = null, verify = { data: { session: { access_token: 't' } }, error: null } } = {}) {
  const calls = []
  return {
    calls,
    auth: {
      async signInWithOtp(args) {
        calls.push(['signInWithOtp', args])
        return { data: {}, error: otpError }
      },
      async verifyOtp(args) {
        calls.push(['verifyOtp', args])
        return verify
      },
    },
  }
}

test('a pasted or spaced code is read as its six digits', () => {
  assert.equal(normalizeOtp(' 123 456 '), '123456')
  assert.equal(normalizeOtp('123-456-789'), '123456')
  assert.equal(isCompleteOtp('12345'), false)
  assert.equal(isCompleteOtp('12 34 56'), true)
})

test('sign-up asks Supabase to create the identity; sign-in never does', async () => {
  const up = fakeSupabase()
  assert.deepEqual(await requestEmailOtp(up, ' New@Example.com ', { createAccount: true }), { ok: true })
  assert.deepEqual(up.calls[0], ['signInWithOtp', { email: 'new@example.com', options: { shouldCreateUser: true } }])
  const inn = fakeSupabase()
  await requestEmailOtp(inn, 'owner@example.com', { createAccount: false })
  assert.equal(inn.calls[0][1].options.shouldCreateUser, false)
})

test('no email link is involved: the request carries no redirect at all', async () => {
  const sb = fakeSupabase()
  await requestEmailOtp(sb, 'a@b.co', { createAccount: true })
  assert.equal('emailRedirectTo' in sb.calls[0][1].options, false)
})

test('an unknown email at sign-in is "no account", not a crash', async () => {
  const sb = fakeSupabase({ otpError: { message: 'Signups not allowed for otp', code: 'otp_disabled', status: 422 } })
  assert.deepEqual(await requestEmailOtp(sb, 'nobody@example.com', { createAccount: false }),
    { ok: false, problem: 'no_account' })
})

test('a wrong and an expired code are the same answer from Supabase, and one message here', async () => {
  const wrong = fakeSupabase({ verify: { data: { session: null }, error: { message: 'Token has expired or is invalid', code: 'otp_expired', status: 403 } } })
  assert.deepEqual(await verifyEmailOtp(wrong, 'a@b.co', '000000'), { ok: false, problem: 'wrong_or_expired_code' })
  assert.match(OTP_PROBLEM_WORDS.wrong_or_expired_code, /not right or has expired/)
})

test('a short code never reaches Supabase', async () => {
  const sb = fakeSupabase()
  assert.deepEqual(await verifyEmailOtp(sb, 'a@b.co', '123'), { ok: false, problem: 'incomplete_code' })
  assert.equal(sb.calls.length, 0)
})

test('a right code verifies as an email OTP and yields a session', async () => {
  const sb = fakeSupabase()
  assert.deepEqual(await verifyEmailOtp(sb, ' A@B.co ', '12 34 56'), { ok: true })
  assert.deepEqual(sb.calls[0], ['verifyOtp', { email: 'a@b.co', token: '123456', type: 'email' }])
})

test('rate limits are recognised however Supabase words them', () => {
  assert.equal(classifyOtpError({ code: 'over_email_send_rate_limit', message: 'x' }), 'rate_limited')
  assert.equal(classifyOtpError({ message: 'For security purposes, you can only request this after 42 seconds.' }), 'rate_limited')
  assert.equal(classifyOtpError({ status: 429, message: '' }), 'rate_limited')
})

test('destinations return people to platform places, including a business checkout', () => {
  for (const ok of ['/', '/start', '/workspace/b/1', '/b/x/orders', '/chennai-dosa/checkout', '/chennai-dosa/book?offering_id=9',
    '/chennai-dosa/account', '/activity', '/marketplace?q=salon']) {
    assert.equal(isValidDestinationIntent(ok), true, ok)
  }
})

test('nothing can send someone off-platform', () => {
  for (const bad of ['https://evil.example', '//evil.example', '/\\evil.example', '/%5cevil.example',
    'javascript:alert(1)', '/a/../../etc', '/x%2f%2fevil', 'evil', '', '/a\u0000b', '/Café']) {
    assert.equal(isValidDestinationIntent(bad), false, JSON.stringify(bad))
  }
  assert.equal(resolveDestinationIntent('//evil.example', '/start'), '/start')
})
