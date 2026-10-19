// Owner Simulation Lab — the steps of a membership business (a gym, a club, a studio).
//
// journey.mjs owns the browser, the owner, the journal and the shared steps
// (start, interview, build, tools, workspace, publish); these are the steps a
// business that sells plans people join and renew has instead:
//
//   plans    the plans the owner told LOCAH: in the catalogue (from the conversation) and in
//            Memberships, where a plan has its length, grace and freeze rules
//   join     a visitor in another browser presses Join on "Open gym, monthly" on the website
//   enrol    the owner adds that person as a member of the plan and records the cash at the desk
//   checkin  the front desk code lets the member in; a wrong code does not
//   changes  a week's freeze stops entry; taking it back lets them in again
//   return   a new session: the member, their plan, what they paid, their visits
//
// The API is read to check what the UI claims.
import { mintToken, sessionCookies } from './session.mjs'

const TZ = 'Asia/Kolkata'
const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
const istToday = () => dayFmt.format(new Date())
const addDays = (iso, n) => new Date(Date.parse(`${iso}T12:00:00Z`) + n * 864e5).toISOString().slice(0, 10)
const flat = (s) => String(s || '').replace(/\s+/g, ' ').trim()
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// The plans the owner named (owners.py "gym"), as they would set them up.
const PLANS = [
  { key: 'monthly', re: /open gym|monthly/i, name: 'Open gym, monthly', price: 3500, days: 30 },
  { key: 'quarterly', re: /quarterly/i, name: 'Quarterly', price: 9500, days: 90 },
  { key: 'annual', re: /annual/i, name: 'Annual', price: 32000, days: 365 },
]
const RAHUL = { name: 'Rahul Nair', email: 'rahul.gym-lab@locah.test', phone: '+919880011223' }

export function membershipJourney(ctx) {
  const { browser, page, api, step, journal, B, WS, API, sleep, pageErrors } = ctx
  const VIEW = { viewport: { width: 1440, height: 900 }, timezoneId: TZ, locale: 'en-IN' }
  const base = `/v1/platform/businesses/${B}`

  // ---------------------------------------------------------------- reading
  const products = async () => (await api('GET', `${base}/products`)).data || []
  const plans = async () => (await api('GET', `${base}/membership-plans`)).data || []
  const enrolments = async () => {
    const r = await api('GET', `${base}/membership-enrolments`)
    return Array.isArray(r.data) ? r.data : r.data?.items || []
  }
  const enrolment = async (id) => (await api('GET', `${base}/membership-enrolments/${id}`)).data || {}
  const customers = async () => (await api('GET', `${base}/customers?limit=200`)).data || []
  async function guestPage() {
    const c = await browser.newContext(VIEW)
    const g = await c.newPage()
    g.on('pageerror', (e) => pageErrors.push(`guest: ${String(e).slice(0, 300)}`))
    g.on('console', (m) => { if (m.type() === 'error') pageErrors.push(`guest: ${m.text().slice(0, 300)}`) })
    return g
  }
  /** The front desk: type the code, press Check; what the desk says. */
  async function desk(code) {
    await page.goto(`${WS}/b/${B}/memberships/checkin`, { waitUntil: 'networkidle', timeout: 120000 })
    await page.locator('input[name=code]').fill(code)
    await page.getByRole('button', { name: /^check$/i }).click()
    await page.locator('section.bos-checkin, [role=alert]').first().waitFor({ timeout: 20000 }).catch(() => {})
    await sleep(500)
    return flat(await page.locator('section.bos-checkin, p[role=alert]').first().innerText().catch(() => ''))
  }

  // =================================================================== steps
  return {
    // --------------------------------------------------------------- plans
    async plans() {
      const s = step('plans: bring in the plans I told LOCAH, then set up "Open gym, monthly" in Memberships')
      await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle', timeout: 120000 })
      const fromTalk = page.getByRole('button', { name: /as drafts$/i })
      if (await fromTalk.count()) {
        s.note(`offered from the conversation: ${flat(await page.locator('#from-talk-h').locator('..').innerText().catch(() => '')).slice(0, 300)}`)
        await fromTalk.click()
        const t0 = Date.now()
        while (Date.now() - t0 < 120000) {
          await sleep(2000)
          if ((await products()).length) break
        }
      } else s.note('no "From your conversation with LOCAH" offer on the page')
      await page.reload({ waitUntil: 'networkidle' })
      await s.shot(page, 'catalogue-drafts', true)
      const items = await products()
      journal.catalogue = items.map((p) => ({ id: p.id, title: p.title, type: p.offering_type, price: p.price_amount, unit: p.unit_of_measure, attrs: p.attributes, status: p.status }))
      s.note(`catalogue drafts (API): ${items.map((p) => `${p.title} [${p.offering_type}] ₹${p.price_amount ?? '-'} ${p.unit_of_measure || ''} ${JSON.stringify(p.attributes || {})}`).join('; ').slice(0, 900)}`)
      for (const pl of PLANS) {
        const p = items.find((x) => pl.re.test(x.title))
        s.check(`"${pl.name}" arrived as a plan at ₹${pl.price}`, p && p.offering_type === 'membership_plan' && Number(p.price_amount) === pl.price,
          p ? `${p.title}: ${p.offering_type} ₹${p.price_amount}` : 'missing')
      }
      // Memberships: where a plan has its length and rules.
      await page.goto(`${WS}/b/${B}/memberships`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'memberships-first', true)
      const first = flat(await page.innerText('main'))
      journal.memberships_first = first.slice(0, 600)
      const before = await plans()
      journal.membership_plans_from_conversation = before.map((p) => `${p.name} ₹${p.price_amount} ${p.duration_days}d`)
      s.check('the plans the owner told LOCAH are already in Memberships, with their length',
        PLANS.every((pl) => before.some((p) => pl.re.test(p.name) && Number(p.price_amount) === pl.price && Number(p.duration_days) === pl.days)),
        before.length ? journal.membership_plans_from_conversation.join(', ') : `none — the page says: ${first.slice(0, 160)}`)
      let monthly = before.find((p) => PLANS[0].re.test(p.name))
      if (monthly && monthly.status === 'draft') {
        // From the conversation, waiting for the owner: Make it live.
        const row = page.locator('li').filter({ has: page.locator('strong', { hasText: new RegExp(`^${esc(monthly.name)}$`) }) })
        const live = row.getByRole('button', { name: /make it live/i })
        s.check('a plan from the conversation waits as a draft with "Make it live"', (await live.count()) > 0)
        if (await live.count()) {
          await live.first().click()
          await sleep(2500)
          await page.reload({ waitUntil: 'networkidle' })
        }
        monthly = (await plans()).find((p) => p.id === monthly.id)
        s.note(`the owner made "${monthly?.name}" live: ${monthly?.status}`)
      }
      if (!monthly) {
        // As the owner would: New plan → Open gym, monthly · ₹3,500 · 30 days · 3 days' grace.
        const details = page.locator('details').filter({ has: page.locator('summary', { hasText: /^new plan$/i }) })
        if (!(await details.evaluate((d) => d.open))) await details.locator('summary').click()
        const form = details.locator('form')
        await form.locator('input[name=name]').fill(PLANS[0].name)
        await form.locator('input[name=price_amount]').fill(String(PLANS[0].price))
        await form.locator('input[name=duration_days]').fill(String(PLANS[0].days))
        if (await form.locator('input[name=grace_days]').count()) await form.locator('input[name=grace_days]').fill('3')
        await form.getByRole('button', { name: /save|create|add/i }).first().click()
        await page.waitForLoadState('networkidle').catch(() => {})
        await sleep(2500)
        monthly = (await plans()).find((p) => PLANS[0].re.test(p.name))
        s.note(`the owner made the plan in Memberships: ${monthly ? `${monthly.name} ₹${monthly.price_amount} ${monthly.duration_days} days` : 'not saved'}`)
      }
      s.check('the monthly plan is a live Memberships plan: ₹3,500 for 30 days (API)',
        monthly && Number(monthly.price_amount) === 3500 && Number(monthly.duration_days) === 30 && monthly.status === 'active',
        JSON.stringify(monthly || {}).slice(0, 200))
      journal.plan_id = monthly?.id || ''
      await page.goto(`${WS}/b/${B}/memberships`, { waitUntil: 'networkidle' })
      await s.shot(page, 'memberships-plans', true)
      s.done()
    },

    // ---------------------------------------------------------------- join
    async join() {
      const s = step('join: a visitor wants to join; the owner lets them ask online; the visitor asks')
      const g = await guestPage()
      const planLinks = async () => g.locator('a').evaluateAll((as) => as.filter((a) => a.getClientRects().length &&
        /join/i.test(a.innerText)).map((a) => `${a.innerText.trim()}|${a.getAttribute('href')}`))
      await g.goto(journal.public_url, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(g, 'public-home', true)
      const body = flat(await g.innerText('body'))
      s.check('the website shows the monthly plan and its price', /monthly/i.test(body) && /3,500/.test(body), body.slice(0, 200))
      let links = await planLinks()
      journal.join_links_before = links
      s.note(`join links with Enquiries off: ${links.join(' · ').slice(0, 300)}`)
      const online = (ls) => ls.find((l) => /plan_id=|purpose=membership/.test(l))
      if (!online(links)) {
        s.check('without Enquiries, "Ask to join" calls the gym (never a form that refuses)', links.some((l) => /\|tel:/.test(l)), links.join(' · '))
        // The owner wants people to join online: what does Memberships say?
        await page.goto(`${WS}/b/${B}/modules/memberships`, { waitUntil: 'networkidle', timeout: 120000 })
        const said = flat(await page.innerText('main'))
        await s.shot(page, 'memberships-tool', true)
        s.check('the Memberships tool says joining is by phone and how to take requests online', /joining by phone only/i.test(said) && /turn on enquiries/i.test(said), said.slice(0, 300))
        const tip = page.getByRole('link', { name: /turn on enquiries/i })
        if (await tip.count()) {
          await Promise.all([page.waitForURL(/\/modules\/leads/, { timeout: 30000 }).catch(() => {}), tip.first().click()])
          await page.waitForLoadState('networkidle').catch(() => {})
          const on = page.getByRole('button', { name: /^turn on/i })
          if (await on.count()) { await on.first().click(); await sleep(2500) }
          s.note(`the owner turned on Enquiries from the tip: ${page.url()}`)
        }
        await g.reload({ waitUntil: 'networkidle' })
        links = await planLinks()
        journal.join_links_after = links
        s.note(`join links with Enquiries on: ${links.join(' · ').slice(0, 300)}`)
      }
      const href = online(links)?.split('|')[1]
      s.check('the website offers Join on the monthly plan', Boolean(href), links.join(' · ').slice(0, 200))
      await g.goto(href ? new URL(href, journal.public_url).href : `${journal.public_url}/enquire?plan_id=${journal.plan_id}&purpose=membership`,
        { waitUntil: 'networkidle' })
      await s.shot(g, 'join-page', true)
      const joinPage = flat(await g.innerText('main').catch(() => ''))
      s.check('the Join page names the plan and its price', /monthly/i.test(joinPage) && /3,?500/.test(joinPage), joinPage.slice(0, 200))
      const field = (re) => g.locator('label').filter({ hasText: re }).locator('input, textarea')
      if (await field(/name/i).count()) {
        await field(/name/i).first().fill(RAHUL.name)
        if (await field(/phone/i).count()) await field(/phone/i).first().fill(RAHUL.phone)
        if (await field(/email/i).count()) await field(/email/i).first().fill(RAHUL.email)
        await g.getByRole('button', { name: /send|join|submit|request|ask/i }).first().click()
        await g.locator('[role=status], [role=alert]').first().waitFor({ timeout: 30000 }).catch(() => {})
        await sleep(1000)
      } else s.note('no name field on the Join page')
      const said = flat(await g.innerText('main').catch(() => ''))
      await s.shot(g, 'join-sent', true)
      journal.join_result = said.slice(0, 400)
      s.check('the visitor is told the gym has the request', !/not taking enquiries|could not|went wrong/i.test(said) && /(thank|received|has your|will (call|get back))/i.test(said), said.slice(0, 220))
      await page.goto(`${WS}/b/${B}/notifications`, { waitUntil: 'networkidle', timeout: 120000 })
      const notes = flat(await page.innerText('main'))
      await s.shot(page, 'notifications', true)
      s.check('the owner hears that Rahul wants to join', /rahul|enquiry|join|membership/i.test(notes), notes.slice(0, 240))
      await g.context().close()
      s.done()
    },

    // --------------------------------------------------------------- enrol
    async enrol() {
      const s = step('enrol: the owner makes Rahul a member of "Open gym, monthly" and records ₹3,500 cash')
      let rahul = (await customers()).find?.((c) => /rahul nair/i.test(c.display_name || ''))
      if (!rahul) {
        await page.goto(`${WS}/b/${B}/customers`, { waitUntil: 'networkidle', timeout: 120000 })
        await page.locator('#c-name').fill(RAHUL.name)
        await page.locator('#c-phone').fill(RAHUL.phone)
        await page.locator('#c-email').fill(RAHUL.email)
        await page.getByRole('button', { name: /add customer/i }).click()
        await sleep(2500)
        rahul = (await customers()).find?.((c) => /rahul nair/i.test(c.display_name || ''))
        s.note(`the owner added Rahul by hand on Customers: ${rahul ? 'saved' : 'not saved'}`)
      }
      s.check('Rahul is a customer (API)', Boolean(rahul))
      await page.goto(`${WS}/b/${B}/memberships`, { waitUntil: 'networkidle', timeout: 120000 })
      const form = page.locator('section[aria-labelledby="mem-enrol"] form')
      s.check('Memberships offers "Add a member"', (await form.count()) > 0)
      if ((await form.count()) && rahul) {
        await form.locator('select[name=plan_id]').selectOption(journal.plan_id).catch(() => {})
        await form.locator('select[name=customer_contact_id]').selectOption(rahul.id).catch(() => {})
        if (await form.locator('input[name=starts_on]').count()) await form.locator('input[name=starts_on]').fill(istToday())
        await form.locator('button[type=submit]').click()
        await page.waitForURL(/\/memberships\/[0-9a-f-]{36}/, { timeout: 30000 }).catch(() => {})
        await page.waitForLoadState('networkidle').catch(() => {})
      }
      const id = (page.url().match(/memberships\/([0-9a-f-]{36})/) || [])[1]
      journal.enrolment_id = id || ''
      s.check('enrolling opens Rahul\'s membership', Boolean(id), page.url())
      if (!id) return s.done()
      await s.shot(page, 'member-new', true)
      let e = await enrolment(id)
      s.note(`enrolment (API) before payment: ${JSON.stringify({ status: e.status, valid_until: e.valid_until, outstanding: e.outstanding ?? e.balance }).slice(0, 200)}`)
      const money = page.getByRole('button', { name: /record money received/i })
      s.check('the membership offers "Record money received"', (await money.count()) > 0)
      const ask = page.getByRole('button', { name: /ask for payment/i })
      if (await ask.count()) s.note('the money panel also offers "Ask for payment" (no payment provider is connected on this stack)')
      if (await money.count()) {
        await money.first().click()
        const f = page.locator('form').filter({ has: page.locator('input[name=amount]') }).last()
        await f.locator('input[name=amount]').fill('3500')
        if (await f.locator('select[name=method]').count()) await f.locator('select[name=method]').selectOption('cash').catch(() => {})
        await f.getByRole('button', { name: /^record$/i }).click()
        await sleep(3000)
        await page.reload({ waitUntil: 'networkidle' })
      }
      await s.shot(page, 'member-paid', true)
      e = await enrolment(id)
      journal.enrolment = { status: e.status, starts_on: e.starts_on, valid_until: e.valid_until, plan: e.plan?.name }
      s.note(`enrolment (API) after payment: ${JSON.stringify(journal.enrolment)}`)
      s.check('Rahul is an active member after paying (API)', e.status === 'active', e.status)
      const until = String(e.valid_until || '').slice(0, 10)
      s.check('valid for the plan\'s 30 days from today (API)', until === addDays(istToday(), 30) || until === addDays(istToday(), 29), `${e.starts_on} → ${e.valid_until}`)
      const text = flat(await page.innerText('main'))
      const code = (text.match(/Front desk code\s*([A-Z0-9-]{6,})/) || [])[1] || ''
      journal.checkin_code = code
      s.check('his membership shows a front desk code', Boolean(code), text.slice(0, 240))
      s.done()
    },

    // ------------------------------------------------------------- checkin
    async checkin() {
      const s = step('checkin: the front desk code lets Rahul in; a wrong code does not')
      const ok = await desk(journal.checkin_code || 'NOCODE')
      await s.shot(page, 'desk-in', true)
      s.check('the desk says "Come in" for Rahul', /come in/i.test(ok) && /rahul/i.test(ok), ok.slice(0, 200))
      const bad = await desk('ZZZZZZ99')
      await s.shot(page, 'desk-wrong', true)
      s.check('a wrong code is refused in plain words', /no membership with that code|not found/i.test(bad), bad.slice(0, 200))
      if (journal.enrolment_id) {
        await page.goto(`${WS}/b/${B}/memberships/${journal.enrolment_id}`, { waitUntil: 'networkidle' })
        const m = flat(await page.innerText('main'))
        s.check('the visit is on Rahul\'s membership', /check-in|visit|came in/i.test(m), m.slice(0, 240))
      }
      s.done()
    },

    // ------------------------------------------------------------- changes
    async changes() {
      const s = step('changes: a week\'s freeze stops entry; taking it back lets Rahul in again')
      const id = journal.enrolment_id
      if (!id) { s.check('there is a membership to change', false); return s.done() }
      await page.goto(`${WS}/b/${B}/memberships/${id}`, { waitUntil: 'networkidle', timeout: 120000 })
      const freeze = page.getByRole('button', { name: /^freeze/i })
      s.check('the membership offers Freeze', (await freeze.count()) > 0)
      if (await freeze.count()) {
        await freeze.first().click()
        const f = page.locator('form').filter({ has: page.locator('input[name=days]') }).first()
        await f.locator('input[name=starts_on]').fill(istToday())
        await f.locator('input[name=days]').fill('7')
        await f.locator('input[name=reason]').fill('Travelling for work')
        await f.locator('button[type=submit]').click()
        await sleep(2500)
        await page.reload({ waitUntil: 'networkidle' })
      }
      await s.shot(page, 'member-frozen', true)
      const e = await enrolment(id)
      s.note(`after the freeze (API): ${JSON.stringify({ status: e.status, valid_until: e.valid_until }).slice(0, 200)}`)
      s.check('a week\'s freeze moves the end date a week later (API)', String(e.valid_until || '').slice(0, 10) === addDays(String(journal.enrolment?.valid_until || '').slice(0, 10), 7),
        `${journal.enrolment?.valid_until} → ${e.valid_until}`)
      const frozen = await desk(journal.checkin_code || 'NOCODE')
      s.check('while frozen, the desk does not let him in', /not allowed|frozen|paused/i.test(frozen) && !/^come in/i.test(frozen), frozen.slice(0, 200))
      await page.goto(`${WS}/b/${B}/memberships/${id}`, { waitUntil: 'networkidle' })
      const takeBack = page.getByRole('button', { name: /take (it )?back|cancel freeze|resume/i })
      if (await takeBack.count()) {
        await takeBack.first().click()
        await sleep(2500)
      } else s.check('the freeze can be taken back', false)
      const back = await desk(journal.checkin_code || 'NOCODE')
      s.check('after taking the freeze back, he is let in', /come in/i.test(back), back.slice(0, 200))
      s.done()
    },

    // -------------------------------------------------------------- return
    async ret(owner) {
      const s = step('return: a new session — the member, his plan, what he paid, his visits')
      const c = await browser.newContext(VIEW)
      await c.addCookies(sessionCookies({ ...owner, token: mintToken(owner) }))
      const p3 = await c.newPage()
      await p3.goto(`${WS}/b/${B}/memberships`, { waitUntil: 'networkidle', timeout: 120000 })
      const list = flat(await p3.innerText('main'))
      await s.shot(p3, 'return-members', true)
      s.check('Rahul is in the members list, active, with his plan', /Rahul Nair/.test(list) && /monthly/i.test(list), list.slice(0, 300))
      if (journal.enrolment_id) {
        await p3.goto(`${WS}/b/${B}/memberships/${journal.enrolment_id}`, { waitUntil: 'networkidle' })
        const m = flat(await p3.innerText('main'))
        await s.shot(p3, 'return-member', true)
        s.check('his membership shows the ₹3,500 he paid', /3,500/.test(m) && /(paid|received|cash)/i.test(m), m.slice(0, 300))
      }
      await c.close()
      s.done()
    },
  }
}
