// P1 roles and staff logins, in the browser (Capability Universe §7.2–§7.3;
// Business OS Guide §5; founder: "owner gives role, creates their credentials").
//  1. The owner sees ready-made roles, makes a custom role from Store keeper.
//  2. The owner adds Murugan as Store keeper at the main shop only and gets a
//     join link.
//  3. In a separate browser with no session, Murugan opens the link, creates
//     his login, joins, and sees only the main shop's stock.
//  4. The owner's Team page shows him with his role and location.
// Desktop and 390 px.
//
//   CHROME_PATH=/opt/pw-browsers/chromium CHROME_NO_SANDBOX=1 node tools/acceptance/phase_b/p1_team.mjs
import { mkdirSync, writeFileSync } from 'node:fs'
import { launch } from '../cdp.mjs'
import { OUT, WS, api, browser, check, clickUntil, newBusiness, realErrors, joinWithCode } from './common.mjs'

const results = []
const shots = `${OUT}/phase_b/p1_team`
mkdirSync(shots, { recursive: true })
const biz = await newBusiness({
  name: 'Selvi Provisions', category: 'fresh_grocery', sub: 'grocery', type: 'retail',
  modules: ['offerings-catalog', 'inventory', 'orders', 'payments'],
})
const base = `/v1/platform/businesses/${biz.id}`
const main = (await api(`${base}/locations`)).data.find((l) => l.is_primary)
const branch = (await api(`${base}/locations`, { method: 'POST', body: { name: 'T Nagar branch' } })).data
const product = (await api(`${base}/products`, {
  method: 'POST',
  body: { title: 'Toor dal 1 kg', sku: `TD-${Date.now()}`, track_inventory: true, status: 'active', price_amount: 165 },
})).data.id
for (const [loc, qty] of [[main.id, 12], [branch.id, 30]]) {
  await api(`${base}/inventory/opening-stock`, { method: 'POST', body: { offering_id: product, location_id: loc, quantity: qty } })
}
const email = `murugan-${Date.now()}@locah.test`

const page = await browser()
let joinUrl = ''
try {
  // ---- roles
  await page.goto(`${WS}/b/${biz.id}/team/roles`)
  await page.waitFor('Ready-made roles', { text: true })
  let body = await page.eval('document.body.innerText')
  check(['Owner', 'Manager', 'Store keeper', 'Accountant'].every((r) => body.includes(r)), 'ready-made roles listed', results)
  check(!body.includes('Delivery partner') && !body.includes('Cashier'), 'roles whose screens are not built yet are not offered', results)
  check(body.includes('What is low, what arrived'), 'each role says what its home screen answers', results)
  await page.shot(`${shots}/01-roles.png`, { full: true })
  await clickUntil(page, 'Make a role', '.bos-roleform')
  await page.type('.bos-roleform input:not([type])', 'Stock checker')
  await page.eval(`(() => { const s = document.querySelector('.bos-roleform select'); s.value = 'store_keeper'; s.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)
  await page.eval(`[...document.querySelectorAll('.bos-permpick label')].find(l => l.innerText.trim() === 'Adjust stock').querySelector('input').click()`)
  await page.shot(`${shots}/02-custom-role-form.png`, { full: true })
  await page.click('Make role', { byText: true })
  await page.waitFor('Role made. Give it to someone from the Team page.', { text: true })
  const custom = (await api(`${base}/roles`)).data.custom
  check(custom.length === 1 && custom[0].label === 'Stock checker' && !custom[0].permissions.includes('inventory.adjust'),
    'custom role saved without "Adjust stock"', results)

  // ---- add a person
  await page.goto(`${WS}/b/${biz.id}/team/add`)
  await page.waitFor('What they do', { text: true })
  await page.type('.bos-form-grid label:nth-child(1) input', 'Murugan')
  await page.type('.bos-form-grid input[type=email]', email)
  await page.eval(`[...document.querySelectorAll('.bos-role-option')].find(l => l.innerText.startsWith('Store keeper')).querySelector('input').click()`)
  await page.waitFor('Where they work', { text: true })
  const branchBox = `[...document.querySelectorAll('.bos-role-locations label')].find(l => l.innerText.includes('T Nagar'))`
  const branchOn = await page.eval(`${branchBox}.querySelector('input').checked`)
  check(branchOn === false, 'only the main shop is ticked by default', results)
  await page.shot(`${shots}/03-add-person.png`, { full: true })
  await page.click('Add and make a join link', { byText: true })
  await page.waitFor('Send Murugan this link', { text: true })
  joinUrl = await page.eval(`document.querySelector('.bos-joinlink input').value`)
  check(/\/join\/[A-Za-z0-9_-]{20,}$/.test(joinUrl), `join link made (${joinUrl.slice(0, 40)}…)`, results)
  const wa = await page.eval(`document.querySelector('.bos-joinlink a').href`)
  check(wa.startsWith('https://wa.me/?text=') && decodeURIComponent(wa).includes('Store keeper'), 'WhatsApp share carries the role and link', results)
  await page.shot(`${shots}/04-join-link.png`, { full: true })
  await page.goto(`${WS}/b/${biz.id}/team`)
  await page.waitFor('Waiting to join', { text: true })
  body = await page.eval('document.body.innerText')
  check(body.includes('Murugan') && body.includes(email), 'Murugan is waiting to join', results)
} finally {
  await page.close()
}

// ---- Murugan, in his own browser with no session
const staff = await launch({ width: 1440, height: 900 })
try {
  await staff.goto(joinUrl)
  await staff.waitFor('Create your login', { text: true })
  const intro = await staff.eval(`document.querySelector('.bos-join__intro').innerText`)
  check(intro.includes('Murugan, join Selvi Provisions') && intro.includes('Store keeper') && intro.includes('What is low, what arrived')
    && intro.includes('Selvi Provisions') && !intro.includes('T Nagar'), 'join page says who, what role, where and the home screen', results)
  await staff.shot(`${shots}/05-join-page.png`, { full: true })
  await joinWithCode(staff, email)
  let landed = ''
  for (let i = 0; i < 60 && !landed.startsWith('/b/'); i++) {
    await new Promise((r) => setTimeout(r, 500))
    landed = await staff.eval('location.pathname')
  }
  check(landed === `/b/${biz.id}`, `joined and landed in the business (${landed})`, results)
  await staff.goto(`${WS}/b/${biz.id}/inventory`)
  await staff.waitFor('Toor dal 1 kg', { text: true })
  const onHand = await staff.eval(`[...document.querySelectorAll('table tbody tr')].map(r => r.innerText)`)
  check(onHand.length === 1 && /\b12\b/.test(onHand[0]) && !/\b30\b/.test(onHand[0]),
    `he sees only the main shop’s stock (${onHand.join(' / ').replace(/\s+/g, ' ')})`, results)
  await staff.shot(`${shots}/06-staff-inventory.png`, { full: true })
  await staff.goto(joinUrl)
  await staff.waitFor('This link does not work', { text: true })
  check(true, 'the join link works once', results)
  check(realErrors(staff).length === 0, `no console errors for staff (${realErrors(staff).slice(0, 2).join(' | ')})`, results)
} finally {
  await staff.close()
}

// ---- back to the owner
const owner = await browser()
try {
  await owner.goto(`${WS}/b/${biz.id}/team`)
  await owner.waitFor('Waiting to join', { text: true })
  const row = await owner.eval(`[...document.querySelectorAll('#members-h ~ .bos-people .bos-person')].find(li => li.innerText.includes('Murugan'))?.innerText || ''`)
  check(row.includes('Store keeper') && row.includes(main.name), `team shows Murugan as Store keeper at ${main.name}`, results)
  await owner.shot(`${shots}/07-team.png`, { full: true })
  await owner.viewport(390, 844, true)
  for (const [path, name] of [['team', '08-team-phone'], ['team/add', '09-add-phone'], ['team/roles', '10-roles-phone']]) {
    await owner.goto(`${WS}/b/${biz.id}/${path}`)
    await owner.waitFor('main')
    const overflow = await owner.eval('document.documentElement.scrollWidth > window.innerWidth + 1')
    check(!overflow, `no sideways scroll at 390 px (${path})`, results)
    await owner.shot(`${shots}/${name}.png`, { full: true })
  }
  check(realErrors(owner).length === 0, `no console errors for owner (${realErrors(owner).slice(0, 2).join(' | ')})`, results)
} finally {
  await owner.close()
}
const phone = await launch({ width: 390, height: 844, mobile: true })
try {
  // A fresh link, opened on a phone.
  const again = await api(`${base}/team/people`, { method: 'POST', body: { name: 'Kavya', email: `kavya-${Date.now()}@locah.test`, role: 'accountant' } })
  await phone.goto(`${WS}${again.data.join_path}`)
  await phone.waitFor('Create your login', { text: true })
  const overflow = await phone.eval('document.documentElement.scrollWidth > window.innerWidth + 1')
  check(!overflow, 'join page fits a 390 px phone', results)
  await phone.shot(`${shots}/11-join-phone.png`, { full: true })
} finally {
  await phone.close()
  writeFileSync(`${shots}/results.json`, JSON.stringify({ business: biz, results }, null, 1))
}
