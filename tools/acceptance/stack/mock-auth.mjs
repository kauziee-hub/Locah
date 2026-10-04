// Local stand-in for the Supabase Auth endpoints the apps call. TEST-ONLY.
//  - /auth/v1/user answers from the (locally minted, HS256) token's own claims
//    so @supabase/ssr's getClaims()/getUser() succeed on localhost.
//  - /auth/v1/signup and /auth/v1/token?grant_type=password create and sign in
//    local users (the auth.users row goes into the LOCAL acceptance database
//    through psql, and its trigger creates the platform identity), so flows
//    like "a new team member creates their login" run end to end in a browser.
// The FastAPI side still verifies every token signature itself.
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import http from 'node:http'

const port = Number(process.env.PORT || 54321)
const SECRET = process.env.MOCK_AUTH_JWT_SECRET || 'local-acceptance-secret-with-at-least-32-characters'
const DB = process.env.MOCK_AUTH_DB || 'locah_accept'
const PG = ['-h', 'localhost', '-p', process.env.PGPORT || '54329', '-U', 'postgres', '-d', DB, '-v', 'ON_ERROR_STOP=1', '-At']
const users = new Map() // email -> { id, password }
const codes = new Map() // email -> { code, id, sentAt, expires } — the latest one-time code
const mail = [] // the local "inbox": { to, code, kind, at }

/** The local auth.users id for an email, from this mock or the database. */
function idFor(email) {
  if (users.has(email)) return users.get(email).id
  try {
    const out = execFileSync('psql', [...PG, '-c', `select id from auth.users where lower(email) = '${email.replace(/'/g, "''")}' limit 1`])
    const id = String(out).trim()
    return id || null
  } catch {
    return null
  }
}
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

function claims(auth) {
  const token = (auth || '').replace(/^Bearer\s+/i, '')
  const part = token.split('.')[1]
  if (!part) return null
  try {
    return JSON.parse(Buffer.from(part.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'))
  } catch {
    return null
  }
}

const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url')
function mint(id, email) {
  const exp = Math.floor(Date.now() / 1000) + 12 * 3600
  const head = b64({ alg: 'HS256', typ: 'JWT' })
  const body = b64({ sub: id, email, aud: 'authenticated', role: 'authenticated', exp })
  const sig = crypto.createHmac('sha256', SECRET).update(`${head}.${body}`).digest('base64url')
  return { token: `${head}.${body}.${sig}`, exp }
}

function userJson(id, email) {
  const now = new Date().toISOString()
  return { id, aud: 'authenticated', role: 'authenticated', email, email_confirmed_at: now,
    app_metadata: { provider: 'email' }, user_metadata: {}, created_at: now, updated_at: now }
}

function session(id, email) {
  const { token, exp } = mint(id, email)
  return { access_token: token, token_type: 'bearer', expires_in: 43200, expires_at: exp,
    refresh_token: crypto.randomUUID(), user: userJson(id, email) }
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => { try { resolve(JSON.parse(raw || '{}')) } catch { resolve({}) } })
  })
}

const json = (res, status, body) => res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body))

http
  .createServer(async (req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Headers', '*')
    if (req.method === 'OPTIONS') return res.writeHead(204).end()
    const url = new URL(req.url, `http://localhost:${port}`)
    if (url.pathname === '/auth/v1/user') {
      const c = claims(req.headers.authorization)
      if (!c) return json(res, 401, { msg: 'no token' })
      return json(res, 200, userJson(c.sub, c.email))
    }
    if (url.pathname === '/auth/v1/signup' && req.method === 'POST') {
      const { email, password } = await readBody(req)
      const e = String(email || '').trim().toLowerCase()
      if (!EMAIL.test(e) || String(password || '').length < 6) return json(res, 422, { msg: 'Enter an email and a password of at least 6 characters' })
      if (users.has(e)) return json(res, 422, { msg: 'User already registered' })
      const id = crypto.randomUUID()
      try {
        execFileSync('psql', [...PG, '-c',
          `insert into auth.users (id, instance_id, aud, role, email, encrypted_password, email_confirmed_at, created_at, updated_at)
           values ('${id}', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '${e}', '', now(), now(), now())`])
      } catch (err) {
        return json(res, 422, { msg: 'User already registered' })
      }
      users.set(e, { id, password: String(password) })
      return json(res, 200, session(id, e))
    }
    if (url.pathname === '/auth/v1/token' && url.searchParams.get('grant_type') === 'password') {
      const { email, password } = await readBody(req)
      const u = users.get(String(email || '').trim().toLowerCase())
      if (!u || u.password !== String(password)) return json(res, 400, { error: 'invalid_grant', error_description: 'Invalid login credentials' })
      return json(res, 200, session(u.id, String(email).trim().toLowerCase()))
    }
    // Email one-time codes (signInWithOtp / verifyOtp). The code is "emailed"
    // to an in-memory local mailbox, readable at GET /__mock/mail?email= — the
    // stand-in for an inbox, for browser tests on localhost only.
    if (url.pathname === '/auth/v1/otp' && req.method === 'POST') {
      const body = await readBody(req)
      const e = String(body.email || '').trim().toLowerCase()
      if (!EMAIL.test(e)) return json(res, 400, { code: 400, error_code: 'validation_failed', msg: 'Unable to validate email address: invalid format' })
      const last = codes.get(e)
      if (last && Date.now() - last.sentAt < 1000 * Number(process.env.MOCK_AUTH_RESEND_SECONDS || 0)) {
        return json(res, 429, { code: 429, error_code: 'over_email_send_rate_limit', msg: 'For security purposes, you can only request this after a few seconds.' })
      }
      let id = idFor(e)
      if (!id) {
        if (body.create_user === false) return json(res, 422, { code: 422, error_code: 'otp_disabled', msg: 'Signups not allowed for otp' })
        id = crypto.randomUUID()
        try {
          execFileSync('psql', [...PG, '-c',
            `insert into auth.users (id, instance_id, aud, role, email, encrypted_password, email_confirmed_at, created_at, updated_at)
             values ('${id}', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '${e}', '', now(), now(), now())`])
        } catch {
          return json(res, 500, { msg: 'could not create the local user' })
        }
      }
      const code = String(crypto.randomInt(0, 100000000)).padStart(8, '0')
      codes.set(e, { code, id, sentAt: Date.now(), expires: Date.now() + 1000 * Number(process.env.MOCK_AUTH_OTP_SECONDS || 600) })
      mail.push({ to: e, code, kind: body.create_user === false ? 'magic_link' : 'confirmation', at: new Date().toISOString() })
      console.log('[mock mail] local email queued')
      return json(res, 200, {})
    }
    if (url.pathname === '/auth/v1/verify' && req.method === 'POST') {
      const { email, token, type } = await readBody(req)
      const e = String(email || '').trim().toLowerCase()
      const entry = codes.get(e)
      // Real Supabase answers a wrong code and an expired one identically.
      const refused = () => json(res, 403, { code: 403, error_code: 'otp_expired', msg: 'Token has expired or is invalid' })
      if (!['email', 'signup', 'magiclink'].includes(String(type))) return refused()
      if (!entry || entry.code !== String(token || '') || Date.now() > entry.expires) return refused()
      codes.delete(e)
      return json(res, 200, session(entry.id, e))
    }
    if (url.pathname === '/__mock/mail' && req.method === 'GET') {
      const e = String(url.searchParams.get('email') || '').trim().toLowerCase()
      return json(res, 200, { messages: mail.filter((m) => !e || m.to === e) })
    }
    if (url.pathname === '/auth/v1/logout') return res.writeHead(204).end()
    if (url.pathname.endsWith('/jwks.json')) return json(res, 200, { keys: [] })
    json(res, 404, { msg: 'not in the local mock' })
  })
  .listen(port, () => console.log(`mock auth on ${port} (db ${DB})`))
