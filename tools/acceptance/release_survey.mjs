// Read-only release acceptance on the existing LOCAL Nila Cafe / salon fixtures.
// Uses the installed Chrome and local mock-auth key, never a hosted session.
import { execFileSync } from 'node:child_process'
import { createHmac } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { launch } from './cdp.mjs'

const WS = process.env.LOCAH_WORKSPACE || 'http://localhost:3101'
const WEB = process.env.LOCAH_WEB || 'http://localhost:3100'
const DB = process.env.LOCAH_ACCEPT_DB || 'locah_accept'
const OUT = process.env.LOCAH_ACCEPT_OUT || 'acceptance-out/release'
for (const origin of [WS, WEB]) {
  if (!['localhost', '127.0.0.1'].includes(new URL(origin).hostname)) throw new Error('Local acceptance only')
}
if (!/^[a-zA-Z0-9_]+$/.test(DB)) throw new Error('Invalid local fixture database')
mkdirSync(OUT, { recursive: true })
const sql = (query) => String(execFileSync('psql', ['-h', '127.0.0.1', '-p', '54329', '-U', 'postgres',
  '-d', DB, '-At', '-v', 'ON_ERROR_STOP=1', '-c', query])).trim()
const fixtures = sql(`SELECT b.id,b.slug,i.supabase_user_id,i.email FROM businesses b
  JOIN platform_identities i ON i.id=b.primary_owner_identity_id
  WHERE b.display_name IN ('Nila Cafe & Bakehouse','Kavya Beauty Studio') AND b.deleted_at IS NULL
  ORDER BY b.display_name`).split('\n').filter(Boolean).map((line) => line.trim().split('|'))
if (fixtures.length !== 2) throw new Error('The local cafe and salon fixtures must exist')
const b64 = (value) => Buffer.from(JSON.stringify(value)).toString('base64url')
function cookie(id, email) {
  if (!email.endsWith('.test')) throw new Error('Refusing a non-test fixture identity')
  const exp = Math.floor(Date.now() / 1000) + 3600
  const head = b64({ alg: 'HS256', typ: 'JWT' })
  const body = b64({ sub: id, email, aud: 'authenticated', role: 'authenticated', exp })
  const sig = createHmac('sha256', 'local-acceptance-secret-with-at-least-32-characters')
    .update(`${head}.${body}`).digest('base64url')
  return 'base64-' + b64({ access_token: `${head}.${body}.${sig}`, token_type: 'bearer',
    expires_in: 3600, expires_at: exp, refresh_token: 'local-refresh',
    user: { id, email, aud: 'authenticated', role: 'authenticated',
      app_metadata: { provider: 'email' }, user_metadata: {} } })
}
const routes = ['', '/offerings', '/offerings/import', '/orders', '/bookings', '/payments',
  '/customers', '/leads', '/inventory', '/fulfilment', '/workforce', '/memberships', '/locations',
  '/modules', '/website', '/website/preview', '/ai-employees/sandbox']
const results = []
const bad = /Application error|Unhandled Runtime Error|Internal Server Error|Something went wrong|API .* failed: 5\d\d/i
for (const mobile of [false, true]) {
  const page = await launch({ width: mobile ? 390 : 1440, height: mobile ? 844 : 900, mobile })
  try {
    for (const [id, slug, owner, email] of fixtures) {
      await page.cookie('sb-127-auth-token', cookie(owner, email), WS)
      await page.cookie('sb-127-auth-token', cookie(owner, email), WEB)
      for (const route of routes) {
        await page.goto(`${WS}/b/${id}${route}`)
        const body = String(await page.eval('document.body.innerText') || '')
        const url = String(await page.url())
        const overflow = await page.eval('document.documentElement.scrollWidth > innerWidth + 1')
        const tableScroll = mobile && await page.eval(`[...document.querySelectorAll('.ws-datatable')]
          .some(el => el.scrollWidth > el.clientWidth + 1)`)
        const h1 = String(await page.eval("document.querySelector('h1')?.innerText || ''"))
        const preview = route === '/website/preview' && await page.eval(`(() => {
          const frame = document.querySelector('iframe');
          return !!frame && !!frame.src && frame.clientWidth > 0 && frame.clientHeight > 0;
        })()`)
        const ok = !bad.test(body) && !url.includes('/login') && !overflow && !tableScroll && (!!h1 || preview)
        const key = `${slug}-${route.replaceAll('/', '-') || 'home'}-${mobile ? 'phone' : 'desktop'}`
        await page.shot(`${OUT}/${key}.png`)
        results.push({ fixture: slug, route, mobile, ok, overflow, tableScroll, h1,
          error: bad.exec(body)?.[0] || '', login: url.includes('/login') })
        console.log(`${ok ? 'PASS' : 'FAIL'} ${slug} ${mobile ? '390px' : '1440px'} ${route || '/'} ${h1}`)
      }
      await page.goto(`${WEB}/${slug}`)
      const body = String(await page.eval('document.body.innerText') || '')
      const overflow = await page.eval('document.documentElement.scrollWidth > innerWidth + 1')
      const ok = body.length > 100 && !bad.test(body) && !overflow
      await page.shot(`${OUT}/${slug}-website-${mobile ? 'phone' : 'desktop'}.png`)
      results.push({ fixture: slug, route: 'published-website', mobile, ok, overflow })
      console.log(`${ok ? 'PASS' : 'FAIL'} ${slug} published website ${mobile ? '390px' : '1440px'}`)
      await page.goto(`${WEB}/start/${id}/interview`)
      const talkBody = String(await page.eval('document.body.innerText') || '')
      const talkUrl = String(await page.url())
      const talkOverflow = await page.eval('document.documentElement.scrollWidth > innerWidth + 1')
      const talkOk = talkBody.length > 100 && !bad.test(talkBody) && !talkOverflow && !talkUrl.includes('/login')
      await page.shot(`${OUT}/${slug}-talk-${mobile ? 'phone' : 'desktop'}.png`)
      results.push({ fixture: slug, route: 'talk', mobile, ok: talkOk, overflow: talkOverflow })
      console.log(`${talkOk ? 'PASS' : 'FAIL'} ${slug} Talk with LOCAH ${mobile ? '390px' : '1440px'}`)
    }
    const errors = page.consoleErrors.filter((error) => !/webpack-hmr|ERR_ABORTED|Failed to fetch RSC payload/.test(error))
    results.push({ route: 'browser-errors', mobile, ok: errors.length === 0, errors })
  } finally {
    await page.close()
  }
}
writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2))
console.log(`${results.filter(r => r.ok).length}/${results.length} browser checks passed`)
if (results.some(r => !r.ok)) process.exitCode = 1
