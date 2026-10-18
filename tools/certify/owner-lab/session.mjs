// A local test identity for the Owner Simulation Lab.
//
// The certification stack has no password or email sign-in: its auth stand-in
// (tools/certify/stack/supabase-local.mjs) answers /auth/v1/user from a token
// signed with the stack's own local secret. This mints such a token for a
// synthetic owner and turns it into the session cookie @supabase/ssr reads, so
// a real browser is signed in to the public app (:3200) and the Workspace
// (:3201) at once — cookies ignore ports. Never used against staging: the
// secret only exists in tools/certify/stack/env.sh.
import { execFileSync } from 'node:child_process'
import { createHmac } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

const SECRET = 'local-acceptance-secret-with-at-least-32-characters'
const COOKIE = 'sb-127-auth-token' // @supabase/supabase-js: sb-<first label of the auth host>-auth-token

const b64url = (buf) => Buffer.from(buf).toString('base64').replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')

export function mintToken({ id, email, hours = 8 }) {
  const now = Math.floor(Date.now() / 1000)
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const claims = b64url(JSON.stringify({
    sub: id, email, aud: 'authenticated', role: 'authenticated', iat: now, exp: now + hours * 3600,
  }))
  const sig = b64url(createHmac('sha256', SECRET).update(`${header}.${claims}`).digest())
  return `${header}.${claims}.${sig}`
}

/** A fresh synthetic owner, signed up the way the stack allows (the auth user
 *  row a real sign-up creates — platform_testing.certify.lab_owner), with its
 *  token. */
export function newOwner(label) {
  const out = execFileSync('uv', ['run', '--no-env-file', 'python', '-m', 'platform_testing.certify.lab_owner', label], {
    cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'],
  })
  const { id, email } = JSON.parse(out.trim().split(/\r?\n/).pop())
  return { id, email, token: mintToken({ id, email }) }
}

/** The session cookie(s) for a browser context on localhost. */
export function sessionCookies({ id, email, token }) {
  const now = Math.floor(Date.now() / 1000)
  const session = {
    access_token: token, token_type: 'bearer', expires_in: 8 * 3600, expires_at: now + 8 * 3600,
    refresh_token: `local-${id}`,
    user: { id, email, aud: 'authenticated', role: 'authenticated', app_metadata: {}, user_metadata: {} },
  }
  const value = `base64-${b64url(JSON.stringify(session))}`
  const base = { domain: 'localhost', path: '/', sameSite: 'Lax', httpOnly: false, secure: false }
  if (value.length <= 3180) return [{ name: COOKIE, value, ...base }]
  const parts = []
  for (let i = 0; i * 3180 < value.length; i++) parts.push({ name: `${COOKIE}.${i}`, value: value.slice(i * 3180, (i + 1) * 3180), ...base })
  return parts
}
