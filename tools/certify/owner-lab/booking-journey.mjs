// Owner Simulation Lab — the steps of a booking business (a salon, a clinic).
//
// journey.mjs owns the browser, the owner, the journal and the shared steps
// (start, interview, build, tools, workspace, publish); these are the steps an
// appointment business has instead of a catalogue and an order:
//
//   services     the conversation's services → drafts → each given its time → live; one price changed
//   hours        the opening hours LOCAH took from the chat, checked; the address added
//   providers    a stylist on Staff & rota: the services they give, their week, a day off
//   book         a guest in another browser books on the public /book page (pay at the salon)
//   conflicts    a taken time is not offered, a race for one time is refused, times
//                outside the hours / the stylist's rota are neither offered nor accepted
//   appointment  the owner hears of it, opens it, confirms it, moves it; the customer sees it
//   guest-cancel the guest cancels a second booking from their link; the owner sees it; the time frees
//   team         a manager works the bookings; an accountant (no bookings permission) is refused
//   lifecycle    Bookings off → the website stops offering Book; on again → nothing lost
//   return       a new session: find the booking and the customer's history
//
// The API is read to check what the UI claims (and, in `conflicts`, called the
// way a crafted request would be, to prove the server refuses it too).
import { mintToken, newOwner, sessionCookies } from './session.mjs'

const TZ = 'Asia/Kolkata'
const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
const clockFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const istToday = () => dayFmt.format(new Date())
const addDays = (iso, n) => new Date(Date.parse(`${iso}T12:00:00Z`) + n * 864e5).toISOString().slice(0, 10)
/** 0 = Monday, the way the API counts weekdays. */
const weekdayOf = (iso) => (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7
const istDayOf = (when) => dayFmt.format(new Date(when))
const clockOf = (when) => clockFmt.format(new Date(when))
const ist = (day, hhmm) => `${day}T${hhmm}:00+05:30`
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const flat = (s) => String(s || '').replace(/\s+/g, ' ').trim()
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

// The stylist the owner adds: people ask for him by name. Tuesday to Saturday,
// 11 to 7 — inside the salon's 10 to 8 — and Sundays off.
const STYLIST = {
  name: 'Farhan', designation: 'Senior stylist (lab)', phone: '+91 98940 11111',
  services: [/women.?s haircut/i, /colou?r/i, /keratin/i], weekdays: [1, 2, 3, 4, 5], from: '11:00', until: '19:00',
}
// How long each service takes, as this owner would put it.
function minutesFor(title) {
  const t = title.toLowerCase()
  if (t.includes('bridal')) return 120
  if (t.includes('keratin')) return 180
  if (t.includes('colour') || t.includes('color')) return 120
  if (t.includes('facial')) return 60
  if (t.includes('women')) return 45
  if (t.includes('men')) return 30
  return 45
}
const PRIYA = { name: 'Priya Raman', email: 'priya.salon-lab@locah.test', phone: '+919840011223' }
const MEENA = { name: 'Meena Sundaram', email: 'meena.salon-lab@locah.test', phone: '+919840022334' }
const KAVYA = { name: 'Kavya Iyer', email: 'kavya.salon-lab@locah.test', phone: '+919840033445' }

export function bookingJourney(ctx) {
  const { browser, page, api, step, journal, B, WS, WEB, API, sleep, pageErrors } = ctx
  const VIEW = { viewport: { width: 1440, height: 900 }, timezoneId: TZ, locale: 'en-IN' }

  // ---------------------------------------------------------------- reading
  const products = async () => (await api('GET', `/v1/platform/businesses/${B}/products`)).data || []
  const members = async () => (await api('GET', `/v1/platform/businesses/${B}/workforce/members`)).data || []
  const bookings = async (qs = '') => {
    const r = await api('GET', `/v1/platform/businesses/${B}/bookings${qs}`)
    return Array.isArray(r.data) ? r.data : r.data?.items || []
  }
  const booking = async (id) => (await api('GET', `/v1/platform/businesses/${B}/bookings/${id}`)).data || {}
  const history = async (id) => (await api('GET', `/v1/platform/businesses/${B}/bookings/${id}/history`)).data || []
  const publicJson = async (method, p, body) => {
    const res = await fetch(`${API}${p}`, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
    let json = null
    try { json = await res.json() } catch {}
    return { status: res.status, data: json?.data ?? null, error: json?.error || json?.detail || null }
  }
  const options = async () => (await publicJson('GET', `/v1/public/websites/${journal.slug}/booking/options`)).data || {}
  const capabilities = async () => (await (await fetch(`${API}/v1/public/websites/${journal.slug}`)).json())?.data?.capabilities || {}
  /** The open times on a day, from the same public call the Book page makes. */
  async function slots({ day, offeringId, providerId = null }) {
    const opts = journal.booking_ids || {}
    const r = await publicJson('POST', `/v1/public/websites/${journal.slug}/booking/slots`, {
      location_id: opts.location_id, offering_id: offeringId, mode: 'appointment', date: day, party_size: 1, provider_id: providerId,
    })
    return { status: r.status, closed: r.data?.closed, hours_known: r.data?.hours_known,
      open: (r.data?.slots || []).filter((x) => !x.full).map((x) => x.label), raw: r.data?.slots || [], error: r.error }
  }
  const view = (p) => ({ id: p.id, title: p.title, type: p.offering_type, status: p.status, price_type: p.price_type,
    price: p.price_amount, minutes: p.attributes?.duration_minutes ?? null })

  /** The days this run books on, fixed once (a resumed run keeps them). */
  function plan() {
    if (journal.plan) return journal.plan
    const today = istToday()
    const works = (d) => STYLIST.weekdays.includes(weekdayOf(d))
    let dayA = addDays(today, 2)
    while (!works(dayA)) dayA = addDays(dayA, 1)
    let away = addDays(dayA, 1)
    while (!works(away)) away = addDays(away, 1)
    let dayB = addDays(away, 1)
    while (!works(dayB)) dayB = addDays(dayB, 1)
    let sunday = addDays(today, 1)
    while (weekdayOf(sunday) !== 6) sunday = addDays(sunday, 1)
    let monday = addDays(today, 1)
    while (weekdayOf(monday) !== 0) monday = addDays(monday, 1)
    journal.plan = { today, dayA, away, dayB, sunday, monday }
    return journal.plan
  }

  // ----------------------------------------------------- the public Book page
  async function guestPage() {
    const c = await browser.newContext(VIEW)
    const g = await c.newPage()
    g.on('pageerror', (e) => pageErrors.push(`guest: ${String(e).slice(0, 300)}`))
    g.on('console', (m) => { if (m.type() === 'error') pageErrors.push(`guest: ${m.text().slice(0, 300)}`) })
    return g
  }
  /** On /book: the service, the person, the day — and the times it then offers. */
  async function choose(g, { service, provider, day }) {
    const chip = g.locator('button.ls-book__choice').filter({ has: g.locator('.ls-book__choice-name', { hasText: service }) })
    if (await chip.count()) await chip.first().click()
    await sleep(400)
    const form = g.locator('form.ls-book__form')
    if (provider !== undefined) {
      const sel = form.locator('label').filter({ hasText: /^\s*With/ }).locator('select')
      if (await sel.count()) await sel.selectOption(provider ? { label: provider } : { value: '' })
      else return { times: [], note: 'no "With" choice on the page', noProvider: true }
      await sleep(300)
    }
    const answered = g.waitForResponse((r) => r.url().includes('/booking/slots') && r.request().method() === 'POST', { timeout: 30000 }).catch(() => null)
    const btn = g.locator(`button.ls-day[data-day="${day}"]`)
    if (await btn.count()) await btn.click()
    else await form.locator('input[type=date]').fill(day)
    await answered
    await sleep(700)
    const times = (await form.locator('fieldset.ls-book__times button').allInnerTexts()).map((t) => flat(t))
    const note = flat((await form.locator('p[role=status]').allInnerTexts()).join(' '))
    return { times, note }
  }
  /** Pick a time and fill in who is coming (not yet sent). */
  async function fillIn(g, time, who) {
    const form = g.locator('form.ls-book__form')
    await form.locator('fieldset.ls-book__times button').filter({ hasText: new RegExp(`^${esc(time)}`) }).first().click()
    await sleep(400)
    await form.locator('label').filter({ hasText: /^\s*Name/ }).locator('input').fill(who.name)
    await form.locator('label').filter({ hasText: /^\s*Email/ }).locator('input').fill(who.email)
    await form.locator('label').filter({ hasText: /^\s*Phone/ }).locator('input').fill(who.phone)
  }
  /** Send it; what the page then says. */
  async function send(g) {
    await g.getByRole('button', { name: /^confirm booking$/i }).click()
    // The Book page's own heading is also .ls-confirm__title ("Book"): the
    // answer is the confirmation header, or the form's alert.
    await g.locator('header.ls-confirm__head, form.ls-book__form [role=alert]').first().waitFor({ timeout: 45000 }).catch(() => {})
    await sleep(500)
    const title = flat(await g.locator('header.ls-confirm__head .ls-confirm__title').first().innerText().catch(() => ''))
    const lede = flat(await g.locator('header.ls-confirm__head .ls-confirm__lede').first().innerText().catch(() => ''))
    const alert = flat(await g.locator('form.ls-book__form [role=alert]').first().innerText().catch(() => ''))
    const manage = g.getByRole('link', { name: /manage this booking/i })
    const manageUrl = (await manage.count()) ? new URL(await manage.first().getAttribute('href'), g.url()).href : ''
    const number = (lede.match(/BKG-[A-Z0-9]+/) || [])[0] || ''
    return { title, lede, alert, manageUrl, number, body: flat(await g.innerText('main').catch(() => '')) }
  }
  const findByNumber = async (number) => (await bookings()).find((x) => x.booking_number === number)

  // =================================================================== steps
  return {
    // ------------------------------------------------------------ services
    async services() {
      const s = step('services: bring in what I told LOCAH as services, give each its time, make them live, change one price')
      await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'services-empty', true)
      const fromTalk = page.getByRole('button', { name: /as drafts$/i })
      if (await fromTalk.count()) {
        s.note(`offered from the conversation: ${flat(await page.locator('#from-talk-h').locator('..').innerText()).slice(0, 300)}`)
        await fromTalk.click()
        const t0 = Date.now()
        while (Date.now() - t0 < 120000) {
          await sleep(2000)
          if ((await products()).length) break
        }
        await page.locator('#from-talk-h').waitFor({ state: 'detached', timeout: 60000 }).catch(() => {})
        s.note(`drafts made in ${Math.round((Date.now() - t0) / 1000)}s`)
      } else {
        s.note('no "From your conversation with LOCAH" offer on the page')
      }
      await page.reload({ waitUntil: 'networkidle' })
      await s.shot(page, 'services-drafts', true)
      let items = await products()
      journal.services_after_import = items.map(view)
      s.note(`services (API): ${journal.services_after_import.map((p) => `${p.title} [${p.type}] ${p.price_type || ''} ${p.price ?? '-'} ${p.minutes ? p.minutes + 'min' : 'no time'} (${p.status})`).join('; ')}`)
      s.check('the services the owner named arrived', items.length >= 5, `${items.length} items`)
      s.check('they arrived as bookable services, not products', items.length > 0 && items.every((p) => p.offering_type === 'service'),
        items.map((p) => `${p.title}: ${p.offering_type}`).join(', '))
      const priced = items.filter((p) => Number(p.price_amount) > 0)
      s.check('the prices the owner gave came with them', priced.length >= 5, `${priced.length}/${items.length} priced`)
      const colour = items.find((p) => /colou?r/i.test(p.title))
      if (colour) s.check('"global colour from 3500" is a starting price', colour.price_type === 'starting_from', `${colour.price_type} ${colour.price_amount}`)
      // A name said in passing ("Haircut, colour, facials…") beside the priced
      // ones ("Women's haircut 900, men's 450"): the owner archives the duplicate.
      const dupes = items.filter((p) => !(Number(p.price_amount) > 0) && p.status !== 'archived' &&
        items.some((q) => q !== p && Number(q.price_amount) > 0 && q.title.toLowerCase().includes(p.title.toLowerCase())))
      journal.services_archived = []
      for (const d of dupes) {
        await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle' })
        const row = page.locator('ul.bos-catalogue > li').filter({ has: page.locator('strong', { hasText: new RegExp(`^${esc(d.title)}$`, 'i') }) })
        if (!(await row.count())) { s.note(`${d.title}: not in the list to archive`); continue }
        await row.first().getByRole('button', { name: /^archive$/i }).click()
        await sleep(2500)
        journal.services_archived.push(d.id)
        s.note(`${d.title}: an unpriced duplicate of a priced service → Archive`)
      }
      for (const p of items.filter((x) => !dupes.includes(x) && x.status !== 'archived').slice(0, 10)) {
        await page.goto(`${WS}/b/${B}/offerings/${p.id}`, { waitUntil: 'networkidle', timeout: 120000 })
        const mins = minutesFor(p.title)
        const field = page.locator('label').filter({ has: page.locator('span.bos-label', { hasText: /^How long it takes/ }) }).locator('input')
        if (await field.count()) await field.first().fill(String(mins))
        else s.check(`${p.title}: there is a field for how long it takes`, false)
        if (/(^|[^o])men.?s haircut/i.test(p.title) && !/women/i.test(p.title)) {
          const price = page.locator('label').filter({ has: page.locator('span.bos-label', { hasText: /^Price/ }) }).locator('input')
          if (await price.count()) {
            await price.first().fill('500')
            journal.price_changed = { id: p.id, title: p.title, from: p.price_amount, to: 500 }
            s.note(`${p.title}: price ${p.price_amount} → 500`)
          } else s.check(`${p.title}: the price field is there to change`, false)
        }
        const liveLabel = page.locator('label.bos-toggle', { hasText: /draft — only you can see it|live — shown to customers/i })
        const toggle = liveLabel.locator('input[type="checkbox"]')
        if ((await toggle.count()) && !(await toggle.isChecked())) await liveLabel.click()
        await page.getByRole('button', { name: /^save$/i }).click()
        const said = await page.locator('p.bos-status').filter({ hasText: /saved|could not|error|needs|add /i }).first().innerText({ timeout: 30000 }).catch(() => '')
        s.note(`${p.title}: ${mins} min, live → "${flat(said).slice(0, 140)}"`)
        if (p === items[0] || /women/i.test(p.title)) await s.shot(page, `service-${p.title.toLowerCase().replace(/[^a-z]+/g, '-').slice(0, 24)}`, true)
      }
      items = await products()
      journal.services_live = items.map(view)
      const live = items.filter((p) => p.status === 'active')
      s.check('the owner made the services live (API)', live.length >= 5, `${live.length}/${items.length} live`)
      s.check('each live service says how long it takes (API)', live.length > 0 && live.every((p) => Number(p.attributes?.duration_minutes) > 0),
        live.map((p) => `${p.title} ${p.attributes?.duration_minutes ?? '-'}`).join(', '))
      if (journal.price_changed) {
        const changed = items.find((p) => p.id === journal.price_changed.id)
        s.check('the price change was saved (API)', Number(changed?.price_amount) === 500, `${changed?.price_amount}`)
      }
      for (const id of journal.services_archived) {
        const a = items.find((p) => p.id === id)
        s.check(`the duplicate "${a?.title}" is archived (API)`, a?.status === 'archived', a?.status)
      }
      await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle' })
      await s.shot(page, 'services-live', true)
      s.done()
    },

    // --------------------------------------------------------------- hours
    async hours() {
      const s = step('hours and place: check the hours LOCAH took from "10 to 8, Monday holiday"; add the address')
      const locs = (await api('GET', `/v1/platform/businesses/${B}/locations`)).data || []
      let loc = locs.find((l) => l.is_primary) || locs[0]
      journal.location_id = loc.id
      journal.hours_saved = loc.hours
      journal.address_from_conversation = { address: loc.address, phone: loc.phone }
      await page.goto(`${WS}/b/${B}/locations/${loc.id}`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'location-before', true)
      const readHours = () => page.locator('.bos-hours__day').evaluateAll((days) => days.map((d) => ({
        day: d.getAttribute('data-day'),
        spans: [...d.querySelectorAll('.bos-hours__span')].map((sp) => [...sp.querySelectorAll('input[type=time]')].map((i) => i.value).join('-')),
      })))
      const want = { mon: [], tue: ['10:00-20:00'], wed: ['10:00-20:00'], thu: ['10:00-20:00'], fri: ['10:00-20:00'], sat: ['10:00-20:00'], sun: ['10:00-20:00'] }
      let ui = await readHours()
      journal.hours_ui = ui
      s.note(`hours on the page: ${ui.map((d) => `${d.day} ${d.spans.join(',') || 'closed'}`).join('; ')}`)
      const same = (rows) => rows.length === 7 && rows.every((d) => JSON.stringify(d.spans) === JSON.stringify(want[d.day]))
      const fromChat = same(ui)
      s.check('the page shows what the owner said: 10 to 8, closed Monday', fromChat, ui.map((d) => `${d.day} ${d.spans.join(',') || 'closed'}`).join('; '))
      const saved = (h) => Object.fromEntries(Object.keys(want).map((k) => [k, (h?.[k] || []).map((x) => x.join('-'))]))
      s.check('and that is what is saved (API)', ui.every((d) => JSON.stringify(d.spans) === JSON.stringify(saved(loc.hours)[d.day])), JSON.stringify(saved(loc.hours)))
      if (!fromChat) {
        // Set them by hand, the way the owner would.
        for (const [day, spans] of Object.entries(want)) {
          const row = page.locator(`.bos-hours__day[data-day="${day}"]`)
          const box = row.locator('input[type=checkbox]')
          if ((await box.isChecked()) !== spans.length > 0) await row.locator('label.bos-toggle').click()
          if (spans.length) {
            await row.locator('input[type=time]').nth(0).fill('10:00')
            await row.locator('input[type=time]').nth(1).fill('20:00')
          }
        }
        await page.getByRole('button', { name: 'Save opening hours' }).click()
        await sleep(2500)
        loc = ((await api('GET', `/v1/platform/businesses/${B}/locations`)).data || []).find((l) => l.id === loc.id)
        s.check('the hours the owner set are saved (API)', JSON.stringify(saved(loc.hours)) === JSON.stringify(want), JSON.stringify(saved(loc.hours)))
      }
      // The salon's address and number, said in the chat ("DB Road, RS Puram,
      // Coimbatore", "98940 73562") — on the place, where customers are told where to come.
      const addr = loc.address || {}
      s.note(`address on the place from the conversation: ${JSON.stringify(addr)}; phone ${loc.phone || '—'}`)
      if (!addr.line1 && !addr.locality) {
        await page.locator('input[name=line1]').fill('DB Road')
        await page.locator('input[name=locality]').fill('RS Puram')
        await page.locator('input[name=city]').fill('Coimbatore')
        await page.locator('input[name=state]').fill('Tamil Nadu')
        if (!loc.phone) await page.locator('input[name=phone]').fill('98940 73562')
        await page.getByRole('button', { name: /^save$/i }).first().click()
        await sleep(2500)
        const said = flat(await page.locator('[role=status], [role=alert]').filter({ hasText: /saved|could not|check|error/i }).first().innerText().catch(() => ''))
        s.note(`address typed in by the owner → "${said.slice(0, 120)}"`)
        loc = ((await api('GET', `/v1/platform/businesses/${B}/locations`)).data || []).find((l) => l.id === loc.id)
      }
      journal.address_saved = { address: loc.address, phone: loc.phone }
      s.check('the address is saved on the place (API)', /RS Puram/i.test(JSON.stringify(loc.address || {})), JSON.stringify(loc.address))
      await page.reload({ waitUntil: 'networkidle' })
      await s.shot(page, 'location-after', true)
      s.done()
    },

    // ----------------------------------------------------------- providers
    async providers() {
      const s = step('providers: add Farhan, the stylist people ask for — the services he gives, his week, a day off')
      const { away } = plan()
      await page.goto(`${WS}/b/${B}/workforce`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'staff-empty', true)
      let farhan = (await members()).find((m) => m.display_name === STYLIST.name)
      if (!farhan) {
        const form = page.locator('form[aria-label="Add someone"]')
        await form.locator('input[name=display_name]').fill(STYLIST.name)
        await form.locator('input[name=designation]').fill(STYLIST.designation)
        await form.locator('input[name=phone]').fill(STYLIST.phone)
        await form.getByRole('button', { name: /^add$/i }).click()
        const said = flat(await form.locator('[role=status], [role=alert]').first().innerText({ timeout: 20000 }).catch(() => ''))
        s.note(`Add → "${said}"`)
        await sleep(1000)
        farhan = (await members()).find((m) => m.display_name === STYLIST.name)
      }
      s.check('Farhan is on Staff & rota (API)', Boolean(farhan), JSON.stringify(farhan || {}).slice(0, 120))
      if (!farhan) return s.done()
      journal.provider = { id: farhan.id, name: farhan.display_name }
      await page.reload({ waitUntil: 'networkidle' })
      s.check('the Staff & rota list shows him taking bookings', /Farhan[\s\S]*Taking bookings/i.test(await page.innerText('main')))
      await page.goto(`${WS}/b/${B}/workforce/${farhan.id}`, { waitUntil: 'networkidle' })
      await s.shot(page, 'stylist-new', true)
      const mine = async () => (await api('GET', `/v1/platform/businesses/${B}/workforce/members/${farhan.id}`)).data || {}
      // The services he gives.
      const live = (await products()).filter((p) => p.status === 'active')
      for (const re of STYLIST.services) {
        const svc = live.find((p) => re.test(p.title))
        if (!svc) { s.check(`a live service for ${re.source}`, false); continue }
        if ((await mine()).services?.some((x) => x.offering_id === svc.id)) { s.note(`${svc.title}: already his`); continue }
        const form = page.locator('form[aria-label="Add a service they do"]')
        await form.locator('select[name=offering_id]').selectOption(svc.id)
        await form.getByRole('button', { name: /add service/i }).click()
        const said = flat(await form.locator('[role=status], [role=alert]').first().innerText({ timeout: 20000 }).catch(() => ''))
        s.note(`service ${svc.title} → "${said}"`)
        await page.reload({ waitUntil: 'networkidle' })
      }
      // His week.
      for (const wd of STYLIST.weekdays) {
        if ((await mine()).availability?.some((a) => a.weekday === wd && a.is_available)) { s.note(`${WEEKDAYS[wd]}: already set`); continue }
        const form = page.locator('form[aria-label="Add weekly hours"]')
        await form.locator('select[name=weekday]').selectOption(String(wd))
        await form.locator('input[name=start_time]').fill(STYLIST.from)
        await form.locator('input[name=end_time]').fill(STYLIST.until)
        await form.locator('select[name=kind]').selectOption('work')
        await form.getByRole('button', { name: /add hours/i }).click()
        const said = flat(await form.locator('[role=status], [role=alert]').first().innerText({ timeout: 20000 }).catch(() => ''))
        s.note(`${WEEKDAYS[wd]} ${STYLIST.from}–${STYLIST.until} → "${said}"`)
        await page.reload({ waitUntil: 'networkidle' })
      }
      // A day off: a family function.
      if (!(await mine()).availability?.some((a) => a.exception_date === away)) {
        const form = page.locator('form[aria-label="Add time off or one-off hours"]')
        await form.locator('input[name=exception_date]').fill(away)
        await form.locator('select[name=kind]').selectOption('away')
        await form.getByRole('button', { name: /^save$/i }).click()
        const said = flat(await form.locator('[role=status], [role=alert]').first().innerText({ timeout: 20000 }).catch(() => ''))
        s.note(`away all day ${away} → "${said}"`)
        await page.reload({ waitUntil: 'networkidle' })
      }
      await s.shot(page, 'stylist-set', true)
      const m = await mine()
      const titles = Object.fromEntries(live.map((p) => [p.id, p.title]))
      journal.provider_api = {
        services: (m.services || []).map((x) => titles[x.offering_id] || x.offering_id),
        availability: (m.availability || []).map((a) => `${a.weekday !== null ? WEEKDAYS[a.weekday] : a.exception_date} ${a.start_time}-${a.end_time} ${a.is_available ? 'work' : 'away'}`),
      }
      s.note(`Farhan (API): services ${journal.provider_api.services.join(', ')} | ${journal.provider_api.availability.join('; ')}`)
      s.check('he gives the three services (API)', (m.services || []).length >= 3, journal.provider_api.services.join(', '))
      const weekly = (m.availability || []).filter((a) => a.weekday !== null && a.is_available)
      s.check('his week is Tuesday to Saturday, 11 to 7 (API)',
        weekly.length === 5 && weekly.every((a) => STYLIST.weekdays.includes(a.weekday) && a.start_time.startsWith('11:00') && a.end_time.startsWith('19:00')),
        weekly.map((a) => `${a.weekday} ${a.start_time}-${a.end_time}`).join(', '))
      s.check(`his day off on ${away} is saved (API)`, (m.availability || []).some((a) => a.exception_date === away && !a.is_available))
      const text = flat(await page.innerText('main'))
      s.check('his page shows the same (services, Tuesday 11 am–7 pm, away day)',
        journal.provider_api.services.every((t) => text.includes(t)) && /Tuesday\s*11 am–7 pm/i.test(text) && /Away all day/i.test(text), text.slice(0, 300))
      s.done()
    },

    // ---------------------------------------------------------------- book
    async book() {
      const s = step('book: a guest in another browser books a women\'s haircut with Farhan, to pay at the salon')
      const { dayA } = plan()
      const opts = await options()
      journal.booking_ids = { location_id: opts.locations?.[0]?.id }
      journal.booking_options = {
        offerings: (opts.offerings || []).map((o) => `${o.title} ${o.minutes}min ₹${o.price_amount}`),
        providers: (opts.providers || []).map((p) => `${p.display_name} (${p.offering_ids.length} services)`),
        payment_methods: opts.payment_methods, policy: opts.policy,
      }
      s.note(`booking options (public API): ${JSON.stringify(journal.booking_options).slice(0, 400)}`)
      const haircut = (opts.offerings || []).find((o) => /women.?s haircut/i.test(o.title))
      journal.booking_ids.haircut = haircut?.id
      s.check('the public booking options carry the live services with their time and price',
        haircut && haircut.minutes === 45 && Number(haircut.price_amount) === 900, haircut ? `${haircut.title} ${haircut.minutes} min ₹${haircut.price_amount}` : 'no women\'s haircut')
      s.check('and Farhan, for the services he gives', (opts.providers || []).some((p) => p.display_name === STYLIST.name && p.offering_ids.includes(haircut?.id)))
      s.check('payment is at the business only (no online gateway is connected)',
        (opts.payment_methods || []).every((m) => ['cod', 'pay_at_business', 'pay_later'].includes(m)), (opts.payment_methods || []).join(', '))

      const g = await guestPage()
      await g.goto(journal.public_url, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(g, 'public-home', true)
      const ctas = await g.locator('a[href*="/book"]').evaluateAll((as) => as.filter((a) => a.getClientRects().length).map((a) => `${a.innerText.trim()}|${a.getAttribute('href')}`))
      journal.book_ctas = [...new Set(ctas)].slice(0, 12)
      s.check('the website offers Book', ctas.length > 0, journal.book_ctas.join(' · '))
      if (ctas.length) {
        await g.locator('a[href*="/book"]').filter({ visible: true }).first().click()
        await g.waitForURL(/\/book/, { timeout: 30000 }).catch(() => {})
      } else {
        await g.goto(`${journal.public_url}/book`)
      }
      await g.waitForLoadState('networkidle').catch(() => {})
      await s.shot(g, 'book-page', true)
      const choices = (await g.locator('button.ls-book__choice').allInnerTexts()).map(flat)
      s.note(`the Book page offers: ${choices.join(' | ').slice(0, 400)}`)
      s.check('each service says its time and price on the Book page', choices.some((c) => /women.?s haircut/i.test(c) && /45 min/.test(c) && /₹\s?900/.test(c)), choices.join(' | ').slice(0, 300))
      const summary = flat(await g.locator('.ls-book__summary').innerText().catch(() => ''))
      s.check('the page says payment is at the visit, and offers no online payment', /pay at your visit/i.test(summary) && !/pay online|card|razorpay/i.test(summary), summary.slice(0, 200))

      const r = await choose(g, { service: /women.?s haircut/i, provider: STYLIST.name, day: dayA })
      journal.slots_dayA_farhan_ui = r.times
      s.note(`with Farhan on ${dayA}: ${r.times.join(' ') || r.note}`)
      s.check('open times are offered for Farhan on a day he works', r.times.length > 0, r.note)
      const api_ = await slots({ day: dayA, offeringId: haircut?.id, providerId: journal.provider?.id })
      s.check('the times on the page are the engine\'s times (public API)', JSON.stringify(api_.open) === JSON.stringify(r.times.map((t) => t.split(' ')[0])),
        `page ${r.times.join(',')} | api ${api_.open.join(',')}`)
      const pick = r.times.find((t) => t.startsWith('12:00')) || r.times[Math.floor(r.times.length / 2)]
      // Failure first: no name — the browser asks for it and nothing is booked.
      const before = (await bookings()).length
      await g.locator('form.ls-book__form fieldset.ls-book__times button').filter({ hasText: new RegExp(`^${esc(pick)}`) }).first().click()
      await sleep(400)
      await g.getByRole('button', { name: /^confirm booking$/i }).click()
      await sleep(1500)
      const why = await g.locator('form.ls-book__form input:invalid').first().evaluate((e) => `${e.closest('label')?.innerText.split('\n')[0] || e.name}: ${e.validationMessage}`).catch(() => '')
      s.check('with no name or email, Confirm booking books nothing', (await bookings()).length === before, `${before} → ${(await bookings()).length}`)
      s.check('and the page says what is missing', Boolean(why), why)
      await fillIn(g, pick, PRIYA)
      await s.shot(g, 'book-details', true)
      const done = await send(g)
      await s.shot(g, 'book-done', true)
      s.note(`the page says: "${done.title}" — ${done.lede} ${done.alert}`)
      journal.first = { number: done.number, manage_url: done.manageUrl, day: dayA, time: pick.split(' ')[0], page_title: done.title, page_lede: done.lede }
      s.check('the guest gets a booking number', Boolean(done.number), done.lede)
      s.check('and a link to manage it', Boolean(done.manageUrl), done.manageUrl.replace(/token=.*/, 'token=…'))
      const mineB = done.number ? await findByNumber(done.number) : null
      journal.first.id = mineB?.id || ''
      s.check('the booking is in the business\'s bookings (API)', Boolean(mineB), mineB ? `${mineB.status} ${mineB.starts_at}` : '')
      if (mineB) {
        const full = await booking(mineB.id)
        journal.first.api = { status: full.status, starts_at: full.starts_at, ends_at: full.ends_at, provider_id: full.provider_id,
          payment_method: full.payment_method, payment_status: full.payment_status, channel: full.channel }
        s.note(`booking (API): ${JSON.stringify(journal.first.api)}`)
        s.check('for the time the guest picked, with Farhan, 45 minutes',
          clockOf(full.starts_at) === journal.first.time && istDayOf(full.starts_at) === dayA && full.provider_id === journal.provider?.id &&
          (Date.parse(full.ends_at) - Date.parse(full.starts_at)) === 45 * 60000, `${full.starts_at} – ${full.ends_at}`)
        s.check('to be paid at the salon (API)', full.payment_status === 'pending_offline', `${full.payment_method} / ${full.payment_status}`)
        // What the customer is told must be what is true.
        const says = /^confirmed$/i.test(done.title) ? 'confirmed' : /waiting|request/i.test(done.title) ? 'pending' : done.title
        s.check('what the page tells the guest matches the booking\'s state (no "Confirmed" before the salon confirms)',
          says === full.status, `page "${done.title}" / booking ${full.status}`)
      }
      // The customer's own link.
      if (done.manageUrl) {
        await g.goto(done.manageUrl, { waitUntil: 'networkidle' })
        await sleep(1500)
        const m = flat(await g.innerText('main'))
        await s.shot(g, 'manage-link', true)
        journal.first.manage_text = m.slice(0, 300)
        s.check('the manage link shows the booking, the service and the time', m.includes(done.number) && /women.?s haircut/i.test(m), m.slice(0, 200))
        s.check('the manage link says where to come (the salon\'s address)', /RS Puram|DB Road/i.test(m), m.slice(0, 200))
      }
      await g.context().close()
      s.done()
    },

    // ----------------------------------------------------------- conflicts
    async conflicts() {
      const s = step('conflicts: a taken time is not offered; two guests racing for one time — one wins; times outside the hours or Farhan\'s week are neither offered nor accepted')
      const { dayA, away, sunday, monday } = plan()
      const svc = journal.booking_ids?.haircut
      const farhan = journal.provider?.id
      // 1. The time Priya took is gone for everyone else.
      const g1 = await guestPage()
      await g1.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      const a = await choose(g1, { service: /women.?s haircut/i, provider: STYLIST.name, day: dayA })
      s.check(`the time Priya booked (${journal.first?.time}) is no longer offered with Farhan`, !a.times.some((t) => t.startsWith(journal.first?.time)), a.times.join(' '))
      // 2. Two guests on the page at once, both choosing the same free time.
      const race = a.times.map((t) => t.split(' ')[0]).filter((t) => t > (journal.first?.time || '')).find((t) => t >= '14:00') || a.times[a.times.length - 1]?.split(' ')[0]
      const g2 = await guestPage()
      await g2.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      const b2 = await choose(g2, { service: /women.?s haircut/i, provider: STYLIST.name, day: dayA })
      s.check(`both guests see ${race} free`, a.times.some((t) => t.startsWith(race)) && b2.times.some((t) => t.startsWith(race)), `${a.times.join(' ')} | ${b2.times.join(' ')}`)
      await fillIn(g1, race, MEENA)
      await fillIn(g2, race, KAVYA)
      await s.shot(g2, 'race-both-ready', true)
      const first = await send(g1)
      const second = await send(g2)
      await s.shot(g1, 'race-winner', true)
      await s.shot(g2, 'race-refused', true)
      s.note(`first guest: "${first.title}" ${first.lede} | second guest: "${second.title}" ${second.alert}`)
      journal.second = { number: first.number, manage_url: first.manageUrl, day: dayA, time: race }
      s.check('the first guest gets the time', Boolean(first.number), first.lede || first.alert)
      s.check('the second guest is refused and nothing is booked for her', !second.number && Boolean(second.alert), second.alert || second.title)
      s.check('she is told in her own terms that the time was just taken (not a system message)',
        /just taken|no longer free|choose another/i.test(second.alert) && !/provider/i.test(second.alert), second.alert)
      const atRace = (await bookings()).filter((x) => x.provider_name === STYLIST.name && istDayOf(x.starts_at) === dayA && clockOf(x.starts_at) === race && ['pending', 'confirmed'].includes(x.status))
      s.check(`exactly one booking holds Farhan at ${race} (API)`, atRace.length === 1, atRace.map((x) => `${x.booking_number} ${x.customer?.name}`).join(', '))
      const second_ = first.number ? await findByNumber(first.number) : null
      journal.second.id = second_?.id || ''
      // The refused guest's page offers the remaining times, without the taken one.
      await sleep(1500)
      const again = (await g2.locator('form.ls-book__form fieldset.ls-book__times button').allInnerTexts().catch(() => [])).map(flat)
      s.note(`the refused guest's page now offers: ${again.join(' ').slice(0, 200)}`)
      s.check(`after the refusal her page no longer offers ${race}`, !again.some((t) => t.startsWith(race)), again.join(' '))
      await g1.context().close()
      await g2.context().close()
      // 3. A crafted request for a taken time, straight to the API.
      const firstApi = journal.first?.api || {}
      const twice = await publicJson('POST', `/v1/public/websites/${journal.slug}/bookings`, {
        location_id: journal.booking_ids.location_id, offering_id: svc, provider_id: farhan, reservation_mode: 'appointment',
        starts_at: firstApi.starts_at, ends_at: firstApi.ends_at, party_size: 1, payment_method: 'pay_at_business',
        guest: { name: 'Lab Double', email: 'double.salon-lab@locah.test', phone: '+919840044556' },
      })
      journal.conflict_api = { double: { status: twice.status, error: twice.error } }
      s.check('booking Priya\'s time again through the API is refused', twice.status === 409 || (twice.status >= 400 && twice.status < 500), `${twice.status} ${JSON.stringify(twice.error).slice(0, 160)}`)
      // 4. Times that are not offered — and refused if asked for anyway.
      const ui = await guestPage()
      await ui.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      const early = await choose(ui, { service: /women.?s haircut/i, provider: STYLIST.name, day: dayA })
      const firstTime = early.times[0]?.split(' ')[0] || ''
      const lastTime = early.times[early.times.length - 1]?.split(' ')[0] || ''
      s.check('with Farhan, nothing before 11 or ending after 7 is offered (his week, inside the 10–8 salon day)',
        firstTime >= '11:00' && lastTime <= '18:15', `${firstTime} … ${lastTime}`)
      const anyone = await choose(ui, { service: /women.?s haircut/i, provider: '', day: dayA })
      journal.slots_dayA_anyone_ui = anyone.times
      s.note(`"Anyone available" on ${dayA}: ${anyone.times.join(' ').slice(0, 300)}`)
      await s.shot(ui, 'anyone-available', true)
      // Farhan is the only person who gives this service. "Anyone available"
      // at the time he is already booked would be a second haircut with nobody to do it.
      const check = await publicJson('POST', `/v1/public/websites/${journal.slug}/booking/availability`, {
        location_id: journal.booking_ids.location_id, offering_id: svc, provider_id: null, reservation_mode: 'appointment',
        starts_at: firstApi.starts_at, ends_at: firstApi.ends_at, party_size: 1,
      })
      journal.conflict_api.anyone_at_taken_time = { status: check.status, data: check.data, error: check.error }
      s.check(`"Anyone available" does not offer ${journal.first?.time}, when the only stylist for it is booked`,
        !anyone.times.some((t) => t.startsWith(journal.first?.time)) && check.data?.available === false,
        `offered: ${anyone.times.some((t) => t.startsWith(journal.first?.time))}; availability API: ${JSON.stringify(check.data || check.error).slice(0, 160)}`)
      const off = await choose(ui, { service: /women.?s haircut/i, provider: STYLIST.name, day: away })
      await s.shot(ui, 'farhan-day-off', true)
      s.check(`on Farhan's day off (${away}) no time with him is offered`, off.times.length === 0, `${off.times.join(' ')} ${off.note}`)
      const sun = await choose(ui, { service: /women.?s haircut/i, provider: STYLIST.name, day: sunday })
      s.check(`on Sunday (${sunday}; the salon is open, Farhan is not) no time with him is offered`, sun.times.length === 0, `${sun.times.join(' ')} ${sun.note}`)
      const mon = await choose(ui, { service: /women.?s haircut/i, provider: '', day: monday })
      await s.shot(ui, 'monday-closed', true)
      s.check(`on Monday (${monday}) the page says the salon is closed`, mon.times.length === 0 && /closed/i.test(mon.note), `${mon.times.join(' ')} ${mon.note}`)
      await ui.context().close()
      const attempt = async (label, day, hhmm, providerId) => {
        const r = await publicJson('POST', `/v1/public/websites/${journal.slug}/bookings`, {
          location_id: journal.booking_ids.location_id, offering_id: svc, provider_id: providerId, reservation_mode: 'appointment',
          starts_at: ist(day, hhmm), ends_at: new Date(Date.parse(ist(day, hhmm)) + 45 * 60000).toISOString(), party_size: 1,
          payment_method: 'pay_at_business', guest: { name: `Lab ${label}`, email: `${label.replace(/\W+/g, '-')}.salon-lab@locah.test`, phone: '+919840055667' },
        })
        journal.conflict_api[label] = { status: r.status, error: r.error, booked: r.data?.booking_number || null }
        s.check(`asked for anyway through the API, it is refused: ${label}`, r.status >= 400 && r.status < 500 && !r.data?.booking_number,
          `${r.status} ${JSON.stringify(r.error || r.data?.booking_number).slice(0, 160)}`)
      }
      await attempt('Farhan at 10:00, before his hours', dayA, '10:00', farhan)
      await attempt('Farhan on his day off', away, '12:00', farhan)
      await attempt('Farhan on Sunday', sunday, '12:00', farhan)
      await attempt('Monday, the salon is closed', monday, '12:00', null)
      await attempt('20:30, after closing', dayA, '20:30', null)
      s.done()
    },

    // --------------------------------------------------------- appointment
    async appointment() {
      const s = step('owner: hear about the booking, open it, confirm it, move it to another day; the customer sees each change')
      const { dayA, dayB } = plan()
      const id = journal.first?.id
      await page.goto(`${WS}/b/${B}/notifications`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'notifications', true)
      const noteText = flat(await page.innerText('main'))
      s.check('a notification tells the owner about the new booking', /new booking/i.test(noteText), noteText.slice(0, 300))
      s.check('the notification names which booking (number, customer, service or time)',
        new RegExp(`${journal.first?.number}|Priya|haircut`, 'i').test(noteText), noteText.slice(0, 300))
      const item = page.locator('article').filter({ hasText: /new booking/i })
      const open = item.getByRole('link', { name: /^open$/i })
      // The oldest "new booking" is Priya's (Meena's came after it).
      if (await open.count()) {
        await open.last().click()
        await page.waitForURL(/\/bookings\//, { timeout: 20000 }).catch(() => {})
        await page.waitForLoadState('networkidle').catch(() => {})
      }
      s.check('Open on the notification goes to the booking', page.url().includes(`/bookings/${id}`), page.url())
      if (!page.url().includes(id)) await page.goto(`${WS}/b/${B}/bookings/${id}`, { waitUntil: 'networkidle' })
      await s.shot(page, 'booking-new', true)
      const detail = flat(await page.innerText('main'))
      s.check('the booking shows the customer, the service, Farhan and "pays at the visit"',
        /Priya Raman/.test(detail) && /haircut/i.test(detail) && /Farhan/.test(detail) && /pays at the visit/i.test(detail), detail.slice(0, 300))
      const guest = await guestPage()
      const customerSees = async (label) => {
        await guest.goto(journal.first.manage_url, { waitUntil: 'networkidle' })
        await sleep(1500)
        const text = flat(await guest.innerText('main'))
        await s.shot(guest, `customer-${label}`, true)
        return text
      }
      // Confirm.
      const confirm = page.getByRole('button', { name: /^confirm$/i })
      s.check('the booking offers Confirm', (await confirm.count()) > 0)
      if (await confirm.count()) {
        await confirm.first().click()
        const yes = page.getByRole('dialog').getByRole('button', { name: /^(yes|confirm)/i })
        if (await yes.count()) await yes.first().click()
        await sleep(2500)
        await page.reload({ waitUntil: 'networkidle' })
      }
      let bk = await booking(id)
      s.check('the booking is confirmed (API)', bk.status === 'confirmed', bk.status)
      await s.shot(page, 'booking-confirmed', true)
      const seen1 = await customerSees('confirmed')
      s.check('the customer\'s link now says Confirmed', /confirmed/i.test(seen1), seen1.slice(0, 200))
      // Move it: Priya asked on the phone for Friday afternoon instead.
      const target = await slots({ day: dayB, offeringId: journal.booking_ids.haircut, providerId: journal.provider.id })
      const newTime = target.open.find((t) => t === '15:00') || target.open.find((t) => t >= '14:00') || target.open[0]
      journal.moved = { from: { day: dayA, time: journal.first.time }, to: { day: dayB, time: newTime } }
      const move = page.locator('form[aria-label="Move to another time"]')
      s.check('the booking offers a way to move it to another time', (await move.count()) > 0,
        (await move.count()) ? '' : `buttons: ${(await page.getByRole('button').allInnerTexts()).join(' | ').slice(0, 200)}`)
      if (await move.count()) {
        await move.locator('input[name=day]').fill(dayB)
        await move.locator('input[name=time]').fill(newTime)
        await move.getByRole('button', { name: /^move$/i }).click()
        const said = flat(await move.locator('[role=status], [role=alert]').first().innerText({ timeout: 30000 }).catch(() => ''))
        s.note(`moved to ${dayB} ${newTime} → "${said}"`)
        await sleep(1000)
        await page.reload({ waitUntil: 'networkidle' })
        await s.shot(page, 'booking-moved', true)
      }
      bk = await booking(id)
      journal.moved.api = { status: bk.status, starts_at: bk.starts_at, ends_at: bk.ends_at }
      s.check(`the booking is now ${dayB} at ${newTime}, still 45 minutes, still confirmed (API)`,
        istDayOf(bk.starts_at) === dayB && clockOf(bk.starts_at) === newTime && Date.parse(bk.ends_at) - Date.parse(bk.starts_at) === 45 * 60000 && bk.status === 'confirmed',
        `${bk.starts_at} – ${bk.ends_at} ${bk.status}`)
      const hist = await history(id)
      journal.first.history = hist.map((h) => `${h.from_status || '—'}→${h.to_status} ${h.reason || ''}`)
      s.note(`what happened (API): ${journal.first.history.join(' | ')}`)
      s.check('its history records the confirmation and the move', hist.some((h) => h.to_status === 'confirmed') && hist.some((h) => /resched|moved/i.test(h.reason || '')))
      const seen2 = await customerSees('moved')
      const [y, mo, d] = dayB.split('-').map(Number)
      const dayWords = new Date(Date.UTC(y, mo - 1, d, 12)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' })
      s.check('the customer\'s link shows the new day and time', seen2.includes(dayWords) && /3:00\s*pm|15:00/i.test(seen2) && /confirmed/i.test(seen2), seen2.slice(0, 200))
      const freed = await slots({ day: dayA, offeringId: journal.booking_ids.haircut, providerId: journal.provider.id })
      s.check(`the old time (${dayA} ${journal.first.time}) is free again for others`, freed.open.includes(journal.first.time), freed.open.join(' '))
      const taken = await slots({ day: dayB, offeringId: journal.booking_ids.haircut, providerId: journal.provider.id })
      s.check(`and the new one (${dayB} ${newTime}) is taken`, !taken.open.includes(newTime), taken.open.join(' '))
      await guest.context().close()
      s.done()
    },

    // -------------------------------------------------------- guest-cancel
    async guestCancel() {
      const s = step('guest cancels the second booking from her link; the owner sees it cancelled; the time frees up')
      const sec = journal.second || {}
      const g = await guestPage()
      await g.goto(sec.manage_url, { waitUntil: 'networkidle', timeout: 120000 })
      await sleep(1500)
      await s.shot(g, 'second-manage', true)
      const cancel = g.getByRole('button', { name: /cancel booking/i })
      s.check('the guest\'s link offers Cancel booking', (await cancel.count()) > 0)
      if (await cancel.count()) {
        let asked = ''
        g.once('dialog', async (d) => { asked = d.message(); await d.accept() })
        await cancel.first().click()
        await sleep(2500)
        s.note(asked ? `the page asked first: "${asked}"` : 'the page cancelled at once, without asking "are you sure?"')
        journal.second.cancel_asked = Boolean(asked)
      }
      const said = flat(await g.innerText('main'))
      await s.shot(g, 'second-cancelled', true)
      s.check('the guest\'s page says it is cancelled', /cancelled/i.test(said), said.slice(0, 200))
      const bk = await booking(sec.id)
      s.check('the booking is cancelled (API)', bk.status === 'cancelled', `${bk.status} ${bk.cancellation_reason || ''}`)
      const hist = await history(sec.id)
      journal.second.history = hist.map((h) => `${h.from_status || '—'}→${h.to_status} ${h.reason || ''} by ${h.actor_identity_id === journal.owner.id ? 'OWNER' : h.actor_identity_id || '—'}`)
      s.note(`what happened (API): ${journal.second.history.join(' | ')}`)
      const byGuest = hist.find((h) => h.to_status === 'cancelled')
      s.check('the cancellation is not recorded as the owner\'s own action', byGuest && byGuest.actor_identity_id !== journal.owner.id,
        byGuest ? `actor ${byGuest.actor_identity_id === journal.owner.id ? 'the owner' : byGuest.actor_identity_id}` : 'no history row')
      await page.goto(`${WS}/b/${B}/notifications`, { waitUntil: 'networkidle' })
      const notes = flat(await page.innerText('main'))
      await s.shot(page, 'notifications-cancelled', true)
      s.check('the owner is told a booking was cancelled', /booking was cancelled/i.test(notes), notes.slice(0, 200))
      s.check('the notification says which one', new RegExp(`${sec.number}|Meena`, 'i').test(notes), notes.slice(0, 200))
      await page.goto(`${WS}/b/${B}/bookings?status=cancelled`, { waitUntil: 'networkidle' })
      const list = flat(await page.innerText('main'))
      await s.shot(page, 'bookings-cancelled', true)
      s.check('the owner\'s Cancelled list shows Meena\'s booking', /Meena Sundaram/.test(list), list.slice(0, 200))
      const freed = await slots({ day: sec.day, offeringId: journal.booking_ids.haircut, providerId: journal.provider.id })
      s.check(`the time (${sec.day} ${sec.time}) is free again`, freed.open.includes(sec.time), freed.open.join(' '))
      await g.context().close()
      s.done()
    },

    // ---------------------------------------------------------------- team
    async team() {
      const s = step('team: a manager works the bookings; an accountant (no bookings permission) is refused them')
      const PEOPLE = [{ role: 'manager', name: 'Lakshmi (lab manager)' }, { role: 'accountant', name: 'Ravi (lab accountant)' }]
      journal.team = journal.team || {}
      for (const person of PEOPLE) {
        const who = newOwner(person.role, `lab-${person.role}-${Date.now().toString(36)}@locah.test`)
        journal.team[person.role] = { id: who.id, email: who.email }
        await page.goto(`${WS}/b/${B}/team/add`, { waitUntil: 'networkidle', timeout: 120000 })
        await page.locator('label', { hasText: /^\s*Name/ }).locator('input').first().fill(person.name)
        await page.locator('input[type=email]').first().fill(who.email)
        await page.locator(`input[name=role-new][value=${person.role}]`).check()
        const loc = page.locator('label', { hasText: /Primary Location/ }).locator('input[type=checkbox]')
        if ((await loc.count()) && !(await loc.isChecked())) await page.locator('label', { hasText: /Primary Location/ }).click()
        await page.getByRole('button', { name: 'Add and make a join link' }).click()
        const link = page.getByLabel('Join link')
        await link.waitFor({ timeout: 30000 })
        const url = await link.inputValue()
        s.note(`${person.role}: join link made`)
        await s.shot(page, `team-${person.role}-link`)
        const c = await browser.newContext(VIEW)
        await c.addCookies(sessionCookies(who))
        const p2 = await c.newPage()
        await p2.goto(url, { waitUntil: 'networkidle', timeout: 120000 })
        const join = p2.getByRole('button', { name: /^join /i })
        s.check(`${person.role}: the join page offers to join this business`, (await join.count()) > 0, flat(await p2.innerText('body')).slice(0, 160))
        if (await join.count()) {
          await join.first().click()
          await p2.waitForURL(new RegExp(`/b/${B}`), { timeout: 60000 }).catch(() => {})
        }
        s.check(`${person.role}: joined and landed in the Workspace`, p2.url().includes(`/b/${B}`), p2.url())
        await p2.waitForLoadState('networkidle').catch(() => {})
        await s.shot(p2, `team-${person.role}-home`, true)
        journal.team[person.role].home = flat(await p2.innerText('main').catch(() => '')).slice(0, 600)
        const as = (m, pth, body) => api(m, pth, body, who.token)
        await p2.goto(`${WS}/b/${B}/bookings`, { waitUntil: 'networkidle' })
        const list = flat(await p2.innerText('main').catch(() => ''))
        await s.shot(p2, `team-${person.role}-bookings`, true)
        if (person.role === 'manager') {
          s.check('manager: sees the bookings (Priya\'s among them)', /Priya Raman/.test(list), list.slice(0, 200))
          await p2.goto(`${WS}/b/${B}/bookings/${journal.first.id}`, { waitUntil: 'networkidle' })
          const acts = await p2.getByRole('button').allInnerTexts()
          s.check('manager: can act on a booking (Mark as arrived / Cancel)', acts.some((t) => /mark as arrived/i.test(t)), acts.join(' | ').slice(0, 200))
          const en = await as('POST', `/v1/b/${B}/modules/payments/enable`)
          s.check('manager: switching a tool on through the API is refused', en.status === 403, `status ${en.status}`)
          const pub = await as('POST', `/v1/b/${B}/website/publish`)
          s.check('manager: publishing the website through the API is refused', pub.status === 403, `status ${pub.status}`)
          const inv = await as('POST', `/v1/platform/businesses/${B}/team/people`, { name: 'X', email: 'x-salon-lab@locah.test', role: 'manager', location_ids: [] })
          s.check('manager: adding people through the API is refused', inv.status === 403, `status ${inv.status}`)
        } else {
          s.check('accountant: the Bookings page shows no bookings', !/Priya Raman|Meena/.test(list), list.slice(0, 200))
          s.check('accountant: and says why (no access), not an error screen', /access|permission|not allowed|ask the owner/i.test(list) && !/something went wrong|application error/i.test(list), list.slice(0, 200))
          const all = await as('GET', `/v1/platform/businesses/${B}/bookings`)
          s.check('accountant: reading bookings through the API is refused', all.status === 403, `status ${all.status}`)
          const one = await as('GET', `/v1/platform/businesses/${B}/bookings/${journal.first.id}`)
          s.check('accountant: one booking by its id is refused too', one.status === 403 || one.status === 404, `status ${one.status}`)
          const act = await as('POST', `/v1/platform/businesses/${B}/bookings/${journal.first.id}/status`, { status: 'cancelled', reason: 'lab bypass attempt' })
          s.check('accountant: cancelling a booking through the API is refused', act.status === 403 || act.status === 404, `status ${act.status}`)
          await p2.goto(`${WS}/b/${B}/bookings/${journal.first.id}`, { waitUntil: 'networkidle' })
          const direct = flat(await p2.innerText('main').catch(() => ''))
          s.check('accountant: the booking\'s own address shows no customer details', !/Priya Raman|\+?91\s?98400/.test(direct), direct.slice(0, 200))
          await s.shot(p2, 'team-accountant-booking-direct', true)
        }
        await c.close()
      }
      const stranger = newOwner('stranger')
      const theirs = await api('GET', `/v1/platform/businesses/${B}/bookings`, null, stranger.token)
      s.check('another owner cannot read this business\'s bookings (tenant isolation, API)', theirs.status === 403 || theirs.status === 404, `status ${theirs.status}`)
      const still = await booking(journal.first.id)
      s.check('after every refused attempt Priya\'s booking is unchanged (API)', still.status === 'confirmed', still.status)
      s.done()
    },

    // ----------------------------------------------------------- lifecycle
    async lifecycle() {
      const s = step('lifecycle: turn Bookings off and on again — the website stops offering Book, the bookings stay')
      const active = async () => ((await api('GET', `/v1/b/${B}/modules`)).data || []).some((m) => m.module_id === 'bookings' && m.activation_state === 'active')
      if (!(await active())) {
        await page.goto(`${WS}/b/${B}/modules/bookings`, { waitUntil: 'networkidle', timeout: 120000 })
        await page.getByRole('button', { name: /^turn on/i }).first().click()
        await sleep(2500)
        s.note('Bookings was off at the start; turned it on first')
      }
      const before = (await bookings()).map((x) => `${x.booking_number}:${x.status}`).sort()
      await page.goto(`${WS}/b/${B}/modules/bookings`, { waitUntil: 'networkidle', timeout: 120000 })
      const off = page.getByRole('button', { name: /^turn off/i })
      s.check('the Bookings tool page offers Turn off', (await off.count()) > 0)
      await off.first().click()
      const confirm = page.getByRole('dialog').getByRole('button', { name: /^(yes|turn off|confirm)/i })
      if (await confirm.count()) await confirm.last().click()
      await page.waitForLoadState('networkidle').catch(() => {})
      await sleep(2500)
      await page.reload({ waitUntil: 'networkidle' })
      await s.shot(page, 'bookings-turned-off', true)
      s.check('Bookings is off (API)', !(await active()))
      let caps = await capabilities()
      s.check('the live website no longer takes bookings', caps.book === false, JSON.stringify(caps).slice(0, 160))
      const g = await guestPage()
      await g.goto(journal.public_url, { waitUntil: 'networkidle' })
      const ctas = await g.locator('a[href*="/book"]').evaluateAll((as) => as.filter((a) => a.getClientRects().length).map((a) => `${a.innerText.trim()}|${a.getAttribute('href')}`))
      await s.shot(g, 'home-with-bookings-off', true)
      s.check('no Book button is left on the home page (no stale CTA)', ctas.length === 0, ctas.join(' · '))
      const bookRes = await g.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      const bookText = flat(await g.innerText('body').catch(() => ''))
      await s.shot(g, 'book-page-with-bookings-off', true)
      s.note(`/book with Bookings off: HTTP ${bookRes?.status()} — ${bookText.slice(0, 200)}`)
      s.check('the Book page offers nothing to book', !(await g.locator('button.ls-book__choice').count()) && !(await g.getByRole('button', { name: /confirm booking/i }).count()), bookText.slice(0, 160))
      await page.goto(`${WS}/b/${B}/bookings`, { waitUntil: 'networkidle' })
      const ownerSays = flat(await page.innerText('main'))
      await s.shot(page, 'bookings-page-while-off', true)
      s.note(`owner's Bookings page while off: ${ownerSays.slice(0, 220)}`)
      s.check('the owner is told Bookings is off and nothing is lost', /off|switched off|turn(ed)? off/i.test(ownerSays) && !/something went wrong/i.test(ownerSays), ownerSays.slice(0, 200))
      await page.goto(`${WS}/b/${B}/modules/bookings`, { waitUntil: 'networkidle' })
      await page.getByRole('button', { name: /^turn on/i }).first().click()
      await page.waitForLoadState('networkidle').catch(() => {})
      await sleep(2500)
      s.check('Bookings is on again (API)', await active())
      const after = (await bookings()).map((x) => `${x.booking_number}:${x.status}`).sort()
      s.check('every past booking is still there, in the same state', JSON.stringify(after) === JSON.stringify(before), `${before.join(', ')} → ${after.join(', ')}`)
      caps = await capabilities()
      s.check('the website takes bookings again', caps.book === true, JSON.stringify(caps).slice(0, 160))
      await g.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      s.check('and the Book page offers the services again', (await g.locator('button.ls-book__choice').count()) > 0)
      await g.context().close()
      s.done()
    },

    // -------------------------------------------------------------- return
    async ret(owner) {
      const s = step('return: a new session another day — find the booking, the cancelled one, and the customer\'s history')
      const c = await browser.newContext(VIEW)
      await c.addCookies(sessionCookies({ ...owner, token: mintToken(owner) }))
      const p3 = await c.newPage()
      await p3.goto(`${WS}/b/${B}`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(p3, 'return-home', true)
      const home = flat(await p3.innerText('main'))
      journal.return_home = home.slice(0, 800)
      s.note(`home: ${home.slice(0, 300)}`)
      s.check('the home is no longer the empty "add a service" start', !/No products or services yet/i.test(home), home.slice(0, 200))
      await p3.goto(`${WS}/b/${B}/bookings?status=confirmed`, { waitUntil: 'networkidle' })
      const conf = flat(await p3.innerText('main'))
      await s.shot(p3, 'return-bookings-confirmed', true)
      s.check('Priya\'s booking is under Confirmed, at the new time', /Priya Raman/.test(conf) && /3:00\s*pm/i.test(conf), conf.slice(0, 240))
      await p3.goto(`${WS}/b/${B}/bookings?status=cancelled`, { waitUntil: 'networkidle' })
      s.check('Meena\'s is under Cancelled', /Meena Sundaram/.test(flat(await p3.innerText('main'))))
      const customers = await api('GET', `/v1/platform/businesses/${B}/customers`)
      const priya = (customers.data || []).find?.((x) => /priya raman/i.test(x.display_name || x.name || ''))
      if (priya) {
        await p3.goto(`${WS}/b/${B}/customers/${priya.id}`, { waitUntil: 'networkidle' })
        const hist = flat(await p3.innerText('main'))
        await s.shot(p3, 'return-customer', true)
        s.check('Priya\'s customer page shows her booking', hist.includes(journal.first.number) || /booking/i.test(hist), hist.slice(0, 240))
      } else {
        s.check('the customer who booked is in Clients (API)', false, JSON.stringify(customers.data).slice(0, 200))
      }
      await c.close()
      s.done()
    },
  }
}
