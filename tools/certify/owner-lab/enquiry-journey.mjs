// Owner Simulation Lab — the steps of an enquiry business (an architect, a
// consultant, an NGO): nothing is bought or booked on the website; a visitor
// asks, and the owner follows up.
//
// journey.mjs owns the browser, the owner, the journal and the shared steps
// (start, interview, build, tools, workspace, publish); these are the rest:
//
//   offer     what the owner told LOCAH (services, projects, causes) → drafts → live
//   enquire   a visitor in another browser asks through the website's own form
//   followup  the owner hears of it, opens it (who, what about, their words), notes a call,
//             moves it on — a "Get a quote" is also a draft quote when Quotes is on — and wins it
//   return    a new session: the won enquiry and the new customer
//
// The API is read to check what the UI claims.
import { mintToken, sessionCookies } from './session.mjs'

const TZ = 'Asia/Kolkata'
const flat = (s) => String(s || '').replace(/\s+/g, ' ').trim()

// Who asks, and what, per kind of business (the owners in owners.py).
const VISITORS = {
  architecture: { name: 'Meera Pillai', email: 'meera.arch-lab@locah.test', phone: '+919895011223',
    message: 'We are planning a 3-bedroom home on a 6-cent plot in Kakkanad; budget around 90 lakhs. Can we meet this month?' },
  consultant: { name: 'Arvind Rao', email: 'arvind.consult-lab@locah.test', phone: '+919845066778',
    message: 'We run four bakery outlets and need help with pricing and our GST set-up. Is a call this week possible?' },
  ngo: { name: 'Divya Shankar', email: 'divya.ngo-lab@locah.test', phone: '+919840077889',
    message: 'I would like to volunteer on Saturdays, teaching spoken English to the older children.' },
}

export function enquiryJourney(ctx) {
  const { browser, page, api, step, journal, B, WS, sleep, pageErrors, persona } = ctx
  const VIEW = { viewport: { width: 1440, height: 900 }, timezoneId: TZ, locale: 'en-IN' }
  const base = `/v1/platform/businesses/${B}`
  const visitor = VISITORS[persona.key] || { name: 'Lab Visitor', email: 'visitor.lab@locah.test', phone: '+919800012345',
    message: 'I would like to know more about what you offer.' }

  const products = async () => (await api('GET', `${base}/products`)).data || []
  const leads = async () => {
    const r = await api('GET', `${base}/leads`)
    return Array.isArray(r.data) ? r.data : r.data?.items || []
  }
  const lead = async (id) => (await api('GET', `${base}/leads/${id}`)).data || {}
  async function guestPage() {
    const c = await browser.newContext(VIEW)
    const g = await c.newPage()
    g.on('pageerror', (e) => pageErrors.push(`guest: ${String(e).slice(0, 300)}`))
    g.on('console', (m) => { if (m.type() === 'error') pageErrors.push(`guest: ${m.text().slice(0, 300)}`) })
    return g
  }

  return {
    // --------------------------------------------------------------- offer
    async offer() {
      const s = step('offer: bring in what I told LOCAH as drafts, make them live')
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
      await s.shot(page, 'offer-drafts', true)
      let items = await products()
      journal.offer_after_import = items.map((p) => `${p.title} [${p.offering_type}] ${p.price_type || ''} ${p.price_amount ?? '-'}`)
      s.note(`drafts (API): ${journal.offer_after_import.join('; ').slice(0, 900)}`)
      s.check('what the owner named arrived as drafts', items.length >= 2, `${items.length} items`)
      for (const p of items.filter((x) => x.status !== 'active').slice(0, 8)) {
        await page.goto(`${WS}/b/${B}/offerings/${p.id}`, { waitUntil: 'networkidle', timeout: 120000 })
        const liveLabel = page.locator('label.bos-toggle', { hasText: /draft — only you can see it|live — shown to customers/i })
        const toggle = liveLabel.locator('input[type="checkbox"]')
        if ((await toggle.count()) && !(await toggle.isChecked())) await liveLabel.click()
        await page.getByRole('button', { name: /^save$/i }).click()
        const said = await page.locator('p.bos-status').filter({ hasText: /saved|could not|error|needs|add /i }).first().innerText({ timeout: 30000 }).catch(() => '')
        s.note(`${p.title}: live → "${flat(said).slice(0, 140)}"`)
      }
      items = await products()
      const live = items.filter((p) => p.status === 'active')
      s.check('the owner made them live (API)', live.length >= Math.min(2, items.length), `${live.length}/${items.length} live`)
      s.done()
    },

    // ------------------------------------------------------------- enquire
    async enquire() {
      const s = step(`enquire: ${visitor.name} asks through the website`)
      const g = await guestPage()
      await g.goto(journal.public_url, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(g, 'public-home', true)
      const asks = await g.locator('a').evaluateAll((as) => as.filter((a) => a.getClientRects().length &&
        /\/enquire/.test(a.getAttribute('href') || '')).map((a) => `${a.innerText.trim()}|${a.getAttribute('href')}`))
      journal.enquire_links = [...new Set(asks)].slice(0, 12)
      s.note(`ways to ask on the home page: ${journal.enquire_links.join(' · ').slice(0, 400)}`)
      s.check('the website offers a way to ask', asks.length > 0, journal.enquire_links.join(' · '))
      const href = asks[0]?.split('|')[1]
      await g.goto(href ? new URL(href, journal.public_url).href : `${journal.public_url}/enquire`, { waitUntil: 'networkidle' })
      await s.shot(g, 'enquire-page', true)
      const form = g.locator('form').filter({ has: g.locator('input[name=name]') }).first()
      s.check('the enquiry form asks for a name and a way to reply', (await form.count()) > 0)
      const before = (await leads()).length
      if (await form.count()) {
        await form.locator('input[name=name]').fill(visitor.name)
        await form.locator('input[name=phone]').fill(visitor.phone)
        if (await form.locator('input[name=email]').count()) await form.locator('input[name=email]').fill(visitor.email)
        if (await form.locator('textarea[name=message]').count()) await form.locator('textarea[name=message]').fill(visitor.message)
        await form.locator('button[type=submit]').click()
        await g.locator('.ls-title, [role=alert]').filter({ hasText: /sent|could not|not taking|try again/i }).first().waitFor({ timeout: 30000 }).catch(() => {})
        await sleep(800)
      }
      const said = flat(await g.innerText('main').catch(() => ''))
      await s.shot(g, 'enquire-sent', true)
      journal.enquiry_reply = said.slice(0, 300)
      s.check('the visitor is told the business has it', /has your (enquiry|request)/i.test(said), said.slice(0, 200))
      const mine = (await leads()).find((l) => l.display_name === visitor.name)
      journal.lead_id = mine?.id || ''
      s.check('the enquiry is in Enquiries with their words (API)', Boolean(mine) && (await leads()).length === before + 1 &&
        (mine.message || '').includes(visitor.message.slice(0, 30)), JSON.stringify(mine || {}).slice(0, 240))
      await g.context().close()
      s.done()
    },

    // ------------------------------------------------------------ followup
    async followup() {
      const s = step('followup: hear of it, open it, note the call, move it on, win it')
      const id = journal.lead_id
      await page.goto(`${WS}/b/${B}/notifications`, { waitUntil: 'networkidle', timeout: 120000 })
      const notes = flat(await page.innerText('main'))
      await s.shot(page, 'notifications', true)
      s.check('a notification tells the owner, naming who asked', new RegExp(visitor.name.split(' ')[0], 'i').test(notes), notes.slice(0, 260))
      await page.goto(`${WS}/b/${B}/leads`, { waitUntil: 'networkidle' })
      const list = flat(await page.innerText('main'))
      await s.shot(page, 'enquiries', true)
      s.check('Enquiries lists the visitor', list.includes(visitor.name), list.slice(0, 260))
      if (!id) { s.check('there is an enquiry to open', false); return s.done() }
      await page.goto(`${WS}/b/${B}/leads/${id}`, { waitUntil: 'networkidle' })
      const detail = flat(await page.innerText('main'))
      await s.shot(page, 'enquiry', true)
      s.check('the enquiry shows how to reach them and their words', detail.includes(visitor.phone.slice(-5)) && detail.includes(visitor.message.slice(0, 30)), detail.slice(0, 300))
      const origin = (await lead(id)).origin_context || {}
      if (origin.offering_title || origin.plan_title) {
        s.check('and what they asked about', /Asked about/i.test(detail) && detail.includes(origin.offering_title || origin.plan_title), detail.slice(0, 300))
      } else s.note(`asked about nothing in particular (${origin.purpose_label || 'enquiry'})`)
      const noteForm = page.locator('form[aria-label="Add a note"]')
      if (await noteForm.count()) {
        await noteForm.locator('textarea[name=body]').fill('Called back; meeting on Saturday at 11.')
        await noteForm.getByRole('button').first().click()
        await sleep(2000)
      }
      const move = async (label) => {
        const b = page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') })
        if (!(await b.count())) return false
        await b.first().click()
        await sleep(2500)
        await page.reload({ waitUntil: 'networkidle' })
        return true
      }
      s.check('the owner can mark it contacted', await move('Mark as contacted'))
      if (persona.modules.includes('quotes') && origin.purpose === 'quote_request') {
        const quotes = (await api('GET', `${base}/quotes`)).data || {}
        const rows = Array.isArray(quotes) ? quotes : quotes.quotes || quotes.items || []
        const draft = rows.find((q) => q.source_ref === id || (q.notes || '').includes(visitor.message.slice(0, 30)))
        journal.draft_quote = draft ? { number: draft.quote_number, status: draft.status, notes: draft.notes } : null
        s.check('a "Get a quote" request is a draft quote to price, with their words (API)', draft?.status === 'draft',
          JSON.stringify(journal.draft_quote || rows.map((q) => q.quote_number)).slice(0, 200))
      }
      s.check('the owner can mark it won', await move('Mark as won'))
      const won = await lead(id)
      await s.shot(page, 'enquiry-won', true)
      s.check('a won enquiry becomes a customer (API)', won.status === 'won' && Boolean(won.customer_contact_id), `${won.status} ${won.customer_contact_id || ''}`)
      journal.customer_id = won.customer_contact_id || ''
      s.check('its history and the note are kept', (won.status_history || []).length >= 3 && (won.notes || []).some((n) => /saturday/i.test(n.body)),
        JSON.stringify({ history: (won.status_history || []).map((h) => h.to_status), notes: (won.notes || []).length }))
      s.done()
    },

    // -------------------------------------------------------------- return
    async ret(owner) {
      const s = step('return: a new session — the won enquiry and the new customer')
      const c = await browser.newContext(VIEW)
      await c.addCookies(sessionCookies({ ...owner, token: mintToken(owner) }))
      const p3 = await c.newPage()
      await p3.goto(`${WS}/b/${B}`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(p3, 'return-home', true)
      s.note(`home: ${flat(await p3.innerText('main')).slice(0, 300)}`)
      await p3.goto(`${WS}/b/${B}/leads`, { waitUntil: 'networkidle' })
      const list = flat(await p3.innerText('main'))
      s.check('the enquiry is in Enquiries, won', list.includes(visitor.name) && /won/i.test(list), list.slice(0, 260))
      if (journal.customer_id) {
        await p3.goto(`${WS}/b/${B}/customers/${journal.customer_id}`, { waitUntil: 'networkidle' })
        const page2 = flat(await p3.innerText('main'))
        await s.shot(p3, 'return-customer', true)
        s.check('the customer page has them, with the way to reach them', page2.includes(visitor.name) && page2.includes(visitor.phone.slice(-5)), page2.slice(0, 240))
      }
      await c.close()
      s.done()
    },
  }
}
