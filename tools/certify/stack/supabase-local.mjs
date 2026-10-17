// Local stand-in for the Supabase endpoints the certification stack needs. TEST-ONLY.
//  - Auth: /auth/v1/user answers from the locally minted (HS256) token's own
//    claims; the API verifies every token signature itself.
//  - Storage: platform uploads (service role), owner uploads through signed
//    upload URLs, public and private reads — files kept on local disk under
//    STORAGE_DIR, so a certification run never writes to the hosted project.
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'

const port = Number(process.env.PORT || 54331)
const ROOT = path.resolve(process.env.STORAGE_DIR || 'certify-out/storage')
fs.mkdirSync(ROOT, { recursive: true })

const TYPES = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
  '.gif': 'image/gif', '.pdf': 'application/pdf', '.svg': 'image/svg+xml' }

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

function userJson(id, email) {
  const now = new Date().toISOString()
  return { id, aud: 'authenticated', role: 'authenticated', email, email_confirmed_at: now,
    app_metadata: { provider: 'email' }, user_metadata: {}, created_at: now, updated_at: now }
}

const json = (res, status, body) => res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body))

/** bucket/key from a URL path, refusing anything that escapes the storage root. */
function fileFor(bucket, key) {
  const file = path.resolve(ROOT, bucket, key)
  if (!file.startsWith(ROOT + path.sep)) return null
  return file
}

function readRaw(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => resolve(Buffer.concat(chunks)))
  })
}

/** The file part of a multipart/form-data body (what supabase-js and the web app send). */
function filePart(body, contentType) {
  const m = /boundary=([^;]+)/i.exec(contentType || '')
  if (!m) return body
  const boundary = Buffer.from('--' + m[1].replace(/^"|"$/g, ''))
  let at = body.indexOf(boundary)
  while (at !== -1) {
    const next = body.indexOf(boundary, at + boundary.length)
    if (next === -1) break
    const part = body.subarray(at + boundary.length, next)
    const split = part.indexOf('\r\n\r\n')
    if (split !== -1) {
      const head = part.subarray(0, split).toString('utf8')
      if (/filename=|content-type:\s*(image|application)\//i.test(head)) {
        return part.subarray(split + 4, part.length - 2)  // drop the trailing CRLF
      }
    }
    at = next
  }
  return body
}

async function store(req, res, bucket, key) {
  const file = fileFor(bucket, key)
  if (!file) return json(res, 400, { message: 'bad key' })
  const body = filePart(await readRaw(req), req.headers['content-type'])
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, body)
  return json(res, 200, { Key: `${bucket}/${key}`, Id: crypto.randomUUID() })
}

function serve(req, res, bucket, key) {
  const file = fileFor(bucket, decodeURIComponent(key))
  if (!file || !fs.existsSync(file)) return json(res, 404, { message: 'Object not found' })
  const stat = fs.statSync(file)
  res.writeHead(200, {
    'content-type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
    'content-length': stat.size,
    'cache-control': 'public, max-age=3600',
  })
  if (req.method === 'HEAD') return res.end()
  fs.createReadStream(file).pipe(res)
}

http
  .createServer(async (req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Headers', '*')
    res.setHeader('Access-Control-Allow-Methods', 'GET,HEAD,POST,PUT,OPTIONS')
    if (req.method === 'OPTIONS') return res.writeHead(204).end()
    const url = new URL(req.url, `http://localhost:${port}`)
    const p = url.pathname
    if (p === '/auth/v1/user') {
      const c = claims(req.headers.authorization)
      if (!c) return json(res, 401, { msg: 'no token' })
      return json(res, 200, userJson(c.sub, c.email))
    }
    if (p === '/auth/v1/logout') return res.writeHead(204).end()
    if (p.endsWith('/jwks.json')) return json(res, 200, { keys: [] })
    let m
    // Owner uploads: sign, then PUT to the signed path.
    if ((m = p.match(/^\/storage\/v1\/object\/upload\/sign\/([^/]+)\/(.+)$/))) {
      const [, bucket, key] = m
      if (req.method === 'POST') {
        if (!claims(req.headers.authorization)) return json(res, 401, { message: 'no token' })
        const token = crypto.randomBytes(12).toString('hex')
        return json(res, 200, { url: `/object/upload/sign/${bucket}/${key}?token=${token}` })
      }
      if (req.method === 'PUT' || req.method === 'POST') return store(req, res, bucket, decodeURIComponent(key))
    }
    if ((m = p.match(/^\/storage\/v1\/object\/public\/([^/]+)\/(.+)$/))) {
      if (req.method === 'GET' || req.method === 'HEAD') return serve(req, res, m[1], m[2])
    }
    if ((m = p.match(/^\/storage\/v1\/object\/([^/]+)\/(.+)$/))) {
      if (req.method === 'POST' || req.method === 'PUT') return store(req, res, m[1], decodeURIComponent(m[2]))
      if (req.method === 'GET' || req.method === 'HEAD') return serve(req, res, m[1], m[2])
    }
    json(res, 404, { msg: 'not in the local stand-in' })
  })
  .listen(port, () => console.log(`local supabase (auth + storage) on ${port}, files in ${ROOT}`))
