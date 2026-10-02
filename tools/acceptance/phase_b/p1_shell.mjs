// P1 Workspace shell in the browser (Business OS Guide §3, §5; Build Spec §8).
//  - The owner's sidebar shows the Guide's areas in order, only with what this
//    business runs; Reach / Insights / AI employees stay hidden until built.
//  - The owner's home answers: needs you now · today · your business, with
//    rows that link to the real records.
//  - A store keeper and a location manager join through real join links and
//    each lands on a home answering their own question, with a sidebar that
//    holds only what they may open; the server refuses the rest.
// Desktop and 390 px.
//
//   CHROME_PATH=/opt/pw-browsers/chromium CHROME_NO_SANDBOX=1 node tools/acceptance/phase_b/p1_shell.mjs
import { mkdirSync, writeFileSync } from 'node:fs'
import { launch } from '../cdp.mjs'
import { OUT, WS, api, browser, check, newBusiness, realErrors, joinWithCode } from './common.mjs'

const results = []
const shots = `${OUT}/phase_b/p1_shell`
mkdirSync(shots, { recursive: true })
const biz = await newBusiness({
  name: 'Selvi Provisions', category: 'fresh_grocery', sub: 'grocery', type: 'retail',
  modules: ['offerings-catalog', 'inventory', 'orders', 'payments', 'leads', 'fulfilment'],
})
const base = `/v1/platform/businesses/${biz.id}`
const main = (await api(`${base}/locations`)).data.find((l) => l.is_primary)
const branch = (await api(`${base}/locations`, { method: 'POST', body: { name: 'T Nagar branch' } })).data
const product = (await api(`${base}/products`, {
  method: 'POST',
  body: { title: 'Toor dal 1 kg', sku: `TD-${Date.now()}`, track_inventory: true, low_stock_threshold: 5, status: 'active', price_amount: 165 },
})).data.id
await api(`${base}/inventory/opening-stock`, { method: 'POST', body: { offering_id: product, location_id: main.id, quantity: 4 } })
await api(`${base}/inventory/opening-stock`, { method: 'POST', body: { offering_id: product, location_id: branch.id, quantity: 25 } })
await api(`${base}/orders`, { method: 'POST', body: { location_id: branch.id, payment_method: 'cod', items: [{ offering_id: product, quantity: 2 }] } })

const areasOf = (page) => page.eval(`[...document.querySelectorAll('#ws-primary-navigation [role=group]')].map(g => g.getAttribute('aria-label'))`)
const linksOf = (page) => page.eval(`[...document.querySelectorAll('#ws-primary-navigation nav a')].map(a => a.innerText.trim().replace(/\\s+\\d+$/, ''))`)

// ---- owner
const owner = await browser()
try {
  await owner.goto(`${WS}/b/${biz.id}`)
  await owner.waitFor('Needs you now', { text: true })
  const areas = await areasOf(owner)
  // Messaging is switched on for every new business, so Reach shows (its tools
  // marked "Set up" until a number is connected, NAV-008); basic Insights is
  // part of the Workspace for anyone who can read orders. AI staff is off.
  check(JSON.stringify(areas) === JSON.stringify(['Business presence', 'Sell', 'Offerings', 'Customers', 'Money', 'Team', 'Reach', 'Insights', 'Modules & integrations', 'Settings']),
    `owner areas in the Guide's order (${areas.join(', ')})`, results)
  check(!areas.includes('AI employees'), 'areas with nothing built stay hidden', results)
  const bands = await owner.eval(`[...document.querySelectorAll('.bos-band h2')].map(h => h.innerText)`)
  check(JSON.stringify(bands) === JSON.stringify(['Needs you now', 'Today', 'Your business']), `owner home has the three bands (${bands.join(' / ')})`, results)
  const rows = await owner.eval(`[...document.querySelectorAll('.bos-band--now .bos-attention__row')].map(a => a.innerText.replace(/\\s+/g, ' '))`)
  check(rows.some((r) => r.startsWith('1 Orders waiting to be accepted')), `pending order listed (${rows[0] ?? 'none'})`, results)
  check(rows.some((r) => r.includes('Items low or out of stock') && r.includes('Toor dal')), 'low stock at the main shop listed', results)
  const biz_rows = await owner.eval(`document.querySelector('.bos-band--business').innerText`)
  check(biz_rows.includes('Not published yet'), 'your business says the website is not live yet', results)
  await owner.shot(`${shots}/01-owner-home.png`, { full: true })
  await owner.eval(`[...document.querySelectorAll('.bos-band--now a')].find(a => a.innerText.includes('Orders waiting')).click()`)
  let path = ''
  for (let i = 0; i < 40 && !path.endsWith('/orders'); i++) {
    await new Promise((r) => setTimeout(r, 250))
    path = await owner.eval('location.pathname')
  }
  check(path.endsWith('/orders'), `row opens the orders behind it (${path})`, results)
  await owner.goto(`${WS}/b/${biz.id}/settings/automations`)
  await owner.waitFor('Automations', { text: true })
  const active = await owner.eval(`[...document.querySelectorAll('#ws-primary-navigation a[aria-current=page]')].map(a => a.innerText.trim())`)
  check(JSON.stringify(active) === JSON.stringify(['Automations']), `exactly one active link (${active.join(', ')})`, results)
  await owner.viewport(390, 844, true)
  await owner.goto(`${WS}/b/${biz.id}`)
  await owner.waitFor('Needs you now', { text: true })
  check(!(await owner.eval('document.documentElement.scrollWidth > window.innerWidth + 1')), 'owner home fits 390 px', results)
  await owner.shot(`${shots}/02-owner-home-phone.png`, { full: true })
  await owner.eval(`document.querySelector('.ws-mobile-bar__toggle').click()`)
  await new Promise((r) => setTimeout(r, 400))
  await owner.shot(`${shots}/03-owner-drawer-phone.png`)
  check(realErrors(owner).length === 0, `no console errors for owner (${realErrors(owner).slice(0, 2).join(' | ')})`, results)
} finally {
  await owner.close()
}

async function joinAs(name, role, locations) {
  const email = `${name.toLowerCase()}-${Date.now()}@locah.test`
  const added = await api(`${base}/team/people`, { method: 'POST', body: { name, email, role, location_ids: locations } })
  const page = await launch({ width: 1440, height: 900 })
  await page.goto(`${WS}${added.data.join_path}`)
  await joinWithCode(page, email)
  for (let i = 0; i < 60; i++) {
    if ((await page.eval('location.pathname')).startsWith('/b/')) break
    await new Promise((r) => setTimeout(r, 500))
  }
  await page.waitFor('.bos-band')
  return page
}

// ---- store keeper at the main shop
const keeper = await joinAs('Murugan', 'store_keeper', [main.id])
try {
  const sub = await keeper.text('.ws-page-header p')
  check(sub.includes('Store keeper · What is low, what arrived'), `store keeper home asks their question (${sub})`, results)
  const bands = await keeper.eval(`[...document.querySelectorAll('.bos-band h2')].map(h => h.innerText)`)
  check(JSON.stringify(bands) === JSON.stringify(['What is low', 'What arrived']), `store keeper bands (${bands.join(' / ')})`, results)
  const low = await keeper.eval(`document.querySelector('.bos-band--low').innerText.replace(/\\s+/g, ' ')`)
  check(low.includes('Toor dal 1 kg') && low.includes('4 left'), `low stock at their shop (${low})`, results)
  const arrived = await keeper.eval(`document.querySelector('.bos-band--arrived').innerText.replace(/\\s+/g, ' ')`)
  check(arrived.includes('+4') && !arrived.includes('+25'), 'what arrived is only their location', results)
  const links = await linksOf(keeper)
  // A grocery that lists only products calls the catalogue "Products" (Doc 07 §3.3).
  check(JSON.stringify(links) === JSON.stringify(['Home', 'Notifications', 'Products', 'Stock', 'Transfers', 'Van stock']), `store keeper sidebar holds only their work (${links.join(', ')})`, results)
  await keeper.shot(`${shots}/04-store-keeper-home.png`, { full: true })
  await keeper.goto(`${WS}/b/${biz.id}/payments`)
  await keeper.waitFor('main')
  const refused = await keeper.eval('document.body.innerText')
  check(!refused.includes('Toor dal') && /not|permission|access/i.test(refused), 'typing the payments address is refused by the server', results)
  await keeper.shot(`${shots}/05-store-keeper-refused.png`, { full: true })
  check(realErrors(keeper).length === 0, `no console errors for store keeper (${realErrors(keeper).slice(0, 2).join(' | ')})`, results)
} finally {
  await keeper.close()
}

// ---- manager at the branch
const manager = await joinAs('Kavya', 'manager', [branch.id])
try {
  const sub = await manager.text('.ws-page-header p')
  check(sub.includes('Manager · What is late or stuck at my location?'), `manager home asks their question (${sub})`, results)
  const late = await manager.eval(`document.querySelector('.bos-band--late').innerText.replace(/\\s+/g, ' ')`)
  check(late.includes('Nothing is late or stuck.'), 'a fresh order at the branch is not yet late', results)
  const areas = await areasOf(manager)
  check(areas.includes('Sell') && areas.includes('Team') && !areas.includes('Business presence'), `manager areas (${areas.join(', ')})`, results)
  await manager.shot(`${shots}/06-manager-home.png`, { full: true })
  await manager.viewport(390, 844, true)
  await manager.goto(`${WS}/b/${biz.id}`)
  await manager.waitFor('.bos-band')
  check(!(await manager.eval('document.documentElement.scrollWidth > window.innerWidth + 1')), 'manager home fits 390 px', results)
  await manager.shot(`${shots}/07-manager-home-phone.png`, { full: true })
} finally {
  await manager.close()
  writeFileSync(`${shots}/results.json`, JSON.stringify({ business: biz, results }, null, 1))
}
