// Owner Simulation Lab — the steps of a stay business (a hotel, a resort, a homestay).
//
// journey.mjs owns the browser, the owner, the journal and the shared steps
// (start, interview, build, tools, workspace, publish); these are the steps a
// business that sells nights in rooms has instead:
//
//   rooms        the conversation's room types → drafts → each says how many it sleeps → live;
//                the check-in / check-out and the weekend minimum the owner said came with them
//   roomlist     the rooms themselves on Reservations → Rooms, each of its room type
//   stay         a guest in another browser books two nights in a Valley cottage (pay at the property)
//   overlap      the second cottage goes to the next guest, a third is refused, another room type is
//                still free, back-to-back nights are fine, the weekend minimum and the room's size hold,
//                and a crafted request for another type's room is refused
//   arrival      the owner hears of it, sees the room and the total, confirms; the guest sees it
//   guest-cancel the second guest cancels from her link; the cottage is free again for those nights
//   return       a new session: the stay under Confirmed, the guest in Guests
//
// The API is read to check what the UI claims (and, in `overlap`, called the
// way a crafted request would be, to prove the server refuses it too).
import { mintToken, sessionCookies } from './session.mjs'

const TZ = 'Asia/Kolkata'
const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
const clockFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const istToday = () => dayFmt.format(new Date())
const addDays = (iso, n) => new Date(Date.parse(`${iso}T12:00:00Z`) + n * 864e5).toISOString().slice(0, 10)
/** 0 = Monday. */
const weekdayOf = (iso) => (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7
const istDayOf = (when) => dayFmt.format(new Date(when))
const clockOf = (when) => clockFmt.format(new Date(when))
const flat = (s) => String(s || '').replace(/\s+/g, ' ').trim()
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// The four room types the owner named, what each sleeps, and the rooms of each.
const TYPES = [
  { key: 'bungalow', re: /bungalow/i, price: 7500, sleeps: 2, rooms: ['Bungalow 1', 'Bungalow 2'] },
  { key: 'cottage', re: /valley/i, price: 9500, sleeps: 2, rooms: ['Cottage 1', 'Cottage 2'] },
  { key: 'family', re: /family/i, price: 12500, sleeps: 4, rooms: ['Family cottage 1'] },
  { key: 'villa', re: /pool villa/i, price: 18500, sleeps: 2, rooms: ['Pool villa 1'] },
]
const ANANYA = { name: 'Ananya Rao', email: 'ananya.hotel-lab@locah.test', phone: '+919845011223' }
const ROHIT = { name: 'Rohit Menon', email: 'rohit.hotel-lab@locah.test', phone: '+919845022334' }
const FARAH = { name: 'Farah Khan', email: 'farah.hotel-lab@locah.test', phone: '+919845033445' }

export function stayJourney(ctx) {
  const { browser, page, api, step, journal, B, WS, API, sleep, pageErrors } = ctx
  const VIEW = { viewport: { width: 1440, height: 900 }, timezoneId: TZ, locale: 'en-IN' }

  // ---------------------------------------------------------------- reading
  const products = async () => (await api('GET', `/v1/platform/businesses/${B}/products`)).data || []
  const resources = async () => (await api('GET', `/v1/platform/businesses/${B}/bookings/resources?include_inactive=true`)).data?.resources || []
  const bookings = async (qs = '') => {
    const r = await api('GET', `/v1/platform/businesses/${B}/bookings${qs}`)
    return Array.isArray(r.data) ? r.data : r.data?.items || []
  }
  const booking = async (id) => (await api('GET', `/v1/platform/businesses/${B}/bookings/${id}`)).data || {}
  const history = async (id) => (await api('GET', `/v1/platform/businesses/${B}/bookings/${id}/history`)).data || []
  const findByNumber = async (number) => (await bookings()).find((x) => x.booking_number === number)
  const publicJson = async (method, p, body) => {
    const res = await fetch(`${API}${p}`, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
    let json = null
    try { json = await res.json() } catch {}
    return { status: res.status, data: json?.data ?? null, error: json?.error || json?.detail || null }
  }
  const options = async () => (await publicJson('GET', `/v1/public/websites/${journal.slug}/booking/options`)).data || {}
  /** Is this room type free for these nights (the same public call the Book page makes)? */
  const range = async (typeId, checkIn, checkOut, party = 2) => publicJson('POST', `/v1/public/websites/${journal.slug}/booking/range`, {
    location_id: journal.location_id, offering_id: typeId, check_in: checkIn, check_out: checkOut, party_size: party,
  })
  const typeId = (key) => journal.room_types?.[key]?.id

  /** The nights this run books, fixed once (a resumed run keeps them). */
  function plan() {
    if (journal.plan) return journal.plan
    const today = istToday()
    let mon = addDays(today, 5)
    while (weekdayOf(mon) !== 0) mon = addDays(mon, 1)
    let sat = addDays(today, 5)
    while (weekdayOf(sat) !== 5) sat = addDays(sat, 1)
    journal.plan = { today, mon, wed: addDays(mon, 2), thu: addDays(mon, 3), sat, sun: addDays(sat, 1), mon2: addDays(sat, 2) }
    return journal.plan
  }

  /** The guest's booking page reads the booking in the browser: wait until it has. */
  async function settled(g) {
    for (let i = 0; i < 40; i++) {
      if (!/Loading…/.test(await g.innerText('main').catch(() => 'Loading…'))) return
      await sleep(500)
    }
  }
  async function guestPage() {
    const c = await browser.newContext(VIEW)
    const g = await c.newPage()
    g.on('pageerror', (e) => pageErrors.push(`guest: ${String(e).slice(0, 300)}`))
    g.on('console', (m) => { if (m.type() === 'error') pageErrors.push(`guest: ${m.text().slice(0, 300)}`) })
    return g
  }
  /** On /book: the room type, the nights and the guests — then Check availability. */
  async function askFor(g, { type, checkIn, checkOut, guests = 2 }) {
    const chip = g.locator('button.ls-book__choice').filter({ has: g.locator('.ls-book__choice-name', { hasText: type }) })
    if (await chip.count()) await chip.first().click()
    await sleep(400)
    const form = g.locator('form.ls-book__form')
    const field = (label) => form.locator('label').filter({ hasText: new RegExp(`^\\s*${label}`) }).locator('input')
    await field('Check-in').fill(checkIn)
    await field('Check-out').fill(checkOut)
    await field('Guests').fill(String(guests))
    const rules = flat(await form.locator('p.ls-meta').first().innerText().catch(() => ''))
    const answered = g.waitForResponse((r) => r.url().includes('/booking/range'), { timeout: 30000 }).catch(() => null)
    const check = form.getByRole('button', { name: /check availability/i })
    if (await check.count()) await check.click()
    await answered
    await sleep(800)
    const ok = flat(await form.locator('p[role=status]').allInnerTexts().then((x) => x.join(' ')).catch(() => ''))
    const alert = flat(await form.locator('[role=alert]').allInnerTexts().then((x) => x.join(' ')).catch(() => ''))
    const summary = flat(await g.locator('.ls-book__summary').innerText().catch(() => ''))
    return { available: /available/i.test(ok) && !alert, ok, alert, rules, summary }
  }
  async function fillIn(g, who) {
    const form = g.locator('form.ls-book__form')
    await form.locator('label').filter({ hasText: /^\s*Name/ }).locator('input').fill(who.name)
    await form.locator('label').filter({ hasText: /^\s*Email/ }).locator('input').fill(who.email)
    await form.locator('label').filter({ hasText: /^\s*Phone/ }).locator('input').fill(who.phone)
  }
  async function send(g) {
    await g.getByRole('button', { name: /^confirm booking$/i }).click()
    await g.locator('header.ls-confirm__head, form.ls-book__form [role=alert]').first().waitFor({ timeout: 45000 }).catch(() => {})
    await sleep(500)
    const title = flat(await g.locator('header.ls-confirm__head .ls-confirm__title').first().innerText().catch(() => ''))
    const lede = flat(await g.locator('header.ls-confirm__head .ls-confirm__lede').first().innerText().catch(() => ''))
    const alert = flat(await g.locator('form.ls-book__form [role=alert]').first().innerText().catch(() => ''))
    const facts = flat(await g.locator('.ls-book__facts').first().innerText().catch(() => ''))
    const manage = g.getByRole('link', { name: /manage this booking/i })
    const manageUrl = (await manage.count()) ? new URL(await manage.first().getAttribute('href'), g.url()).href : ''
    const number = (lede.match(/BKG-[A-Z0-9]+/) || [])[0] || ''
    return { title, lede, alert, facts, manageUrl, number }
  }
  /** Book through the page, start to end; what it said and the booking (API). */
  async function bookThrough(g, s, { label, type, checkIn, checkOut, guests, who }) {
    await g.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle', timeout: 120000 })
    const asked = await askFor(g, { type, checkIn, checkOut, guests })
    if (!asked.available) return { asked, done: null, api: null }
    await fillIn(g, who)
    await s.shot(g, `${label}-details`, true)
    const done = await send(g)
    const bk = done.number ? await findByNumber(done.number) : null
    return { asked, done, api: bk ? await booking(bk.id) : null }
  }

  // =================================================================== steps
  return {
    // --------------------------------------------------------------- rooms
    async rooms() {
      const s = step('rooms: bring in the room types I told LOCAH, say how many each sleeps, make them live')
      await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'rooms-empty', true)
      const fromTalk = page.getByRole('button', { name: /as drafts$/i })
      if (await fromTalk.count()) {
        s.note(`offered from the conversation: ${flat(await page.locator('#from-talk-h').locator('..').innerText().catch(() => '')).slice(0, 300)}`)
        await fromTalk.click()
        const t0 = Date.now()
        while (Date.now() - t0 < 120000) {
          await sleep(2000)
          if ((await products()).length) break
        }
        await page.locator('#from-talk-h').waitFor({ state: 'detached', timeout: 60000 }).catch(() => {})
      } else s.note('no "From your conversation with LOCAH" offer on the page')
      await page.reload({ waitUntil: 'networkidle' })
      await s.shot(page, 'rooms-drafts', true)
      let items = await products()
      journal.rooms_after_import = items.map((p) => ({ id: p.id, title: p.title, type: p.offering_type, price: p.price_amount, attrs: p.attributes, status: p.status }))
      s.note(`drafts (API): ${items.map((p) => `${p.title} [${p.offering_type}] ₹${p.price_amount ?? '-'} ${JSON.stringify(p.attributes || {})}`).join('; ').slice(0, 900)}`)
      journal.room_types = {}
      for (const t of TYPES) {
        const p = items.find((x) => t.re.test(x.title))
        if (p) journal.room_types[t.key] = { id: p.id, title: p.title }
        s.check(`the ${t.key} room type arrived as a room type at ₹${t.price} a night`,
          p && p.offering_type === 'accommodation' && Number(p.price_amount) === t.price, p ? `${p.title}: ${p.offering_type} ₹${p.price_amount}` : 'missing')
      }
      const anyType = items.find((x) => x.offering_type === 'accommodation')
      const said = anyType?.attributes || {}
      s.check('"Check-in 1 pm, check-out 11 am" came with them', said.check_in === '13:00' && said.check_out === '11:00', JSON.stringify(said))
      s.check('"2-night minimum on weekends" came with them', Number(said.weekend_min_nights) === 2, JSON.stringify(said))
      for (const t of TYPES) {
        const id = typeId(t.key)
        if (!id) continue
        await page.goto(`${WS}/b/${B}/offerings/${id}`, { waitUntil: 'networkidle', timeout: 120000 })
        const label = (re) => page.locator('label').filter({ has: page.locator('span.bos-label', { hasText: re }) }).locator('input')
        const sleeps = label(/^Guests per room/)
        if (await sleeps.count()) await sleeps.first().fill(String(t.sleeps))
        else s.check(`${t.key}: there is a field for how many it sleeps`, false)
        if (t.key === 'cottage') {
          const inField = label(/^Check-in from/)
          s.check('the room type shows its check-in time to the owner', (await inField.count()) > 0 && (await inField.first().inputValue()) === '13:00',
            (await inField.count()) ? await inField.first().inputValue() : 'no Check-in field')
          await s.shot(page, 'room-type-cottage', true)
        }
        const liveLabel = page.locator('label.bos-toggle', { hasText: /draft — only you can see it|live — shown to customers/i })
        const toggle = liveLabel.locator('input[type="checkbox"]')
        if ((await toggle.count()) && !(await toggle.isChecked())) await liveLabel.click()
        await page.getByRole('button', { name: /^save$/i }).click()
        const saidNow = await page.locator('p.bos-status').filter({ hasText: /saved|could not|error|needs|add /i }).first().innerText({ timeout: 30000 }).catch(() => '')
        s.note(`${t.key}: sleeps ${t.sleeps}, live → "${flat(saidNow).slice(0, 120)}"`)
      }
      items = await products()
      const live = TYPES.map((t) => items.find((p) => p.id === typeId(t.key))).filter(Boolean)
      s.check('the four room types are live, each saying how many it sleeps (API)',
        live.length === 4 && live.every((p) => p.status === 'active' && Number(p.attributes?.max_guests) > 0),
        live.map((p) => `${p.title} ${p.status} sleeps ${p.attributes?.max_guests ?? '-'}`).join(', '))
      const others = items.filter((p) => !live.includes(p))
      if (others.length) s.note(`also from the conversation: ${others.map((p) => `${p.title} [${p.offering_type}] ${p.status}`).join(', ')}`)
      await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle' })
      await s.shot(page, 'rooms-live', true)
      s.done()
    },

    // ------------------------------------------------------------ roomlist
    async roomlist() {
      const s = step('room list: add the rooms themselves on Reservations → Rooms, each of its room type')
      const locs = (await api('GET', `/v1/platform/businesses/${B}/locations`)).data || []
      journal.location_id = (locs.find((l) => l.is_primary) || locs[0])?.id
      await page.goto(`${WS}/b/${B}/bookings/resources`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'roomlist-empty', true)
      const form = page.locator('form[aria-label="Add a table, room or equipment"]')
      s.check('the Rooms page offers a way to add a room', (await form.count()) > 0)
      const typeSelect = form.locator('select[name=offering_id]')
      s.check('adding a room asks which room type it is', (await typeSelect.count()) > 0)
      const have = new Set((await resources()).map((r) => r.name))
      for (const t of TYPES) {
        for (const name of t.rooms) {
          if (have.has(name)) continue
          await form.locator('select[name=kind]').selectOption('room')
          await form.locator('input[name=name]').fill(name)
          await form.locator('input[name=size]').fill(String(t.sleeps))
          if (await typeSelect.count()) await typeSelect.selectOption({ label: journal.room_types[t.key]?.title || '' }).catch(() => {})
          await form.getByRole('button', { name: /^add$/i }).click()
          const said = flat(await form.locator('[role=status], [role=alert]').first().innerText({ timeout: 20000 }).catch(() => ''))
          s.note(`${name} (${t.key}) → "${said.slice(0, 80)}"`)
          await sleep(800)
        }
      }
      await page.reload({ waitUntil: 'networkidle' })
      await s.shot(page, 'roomlist', true)
      const rows = await resources()
      journal.rooms = Object.fromEntries(rows.map((r) => [r.name, { id: r.id, type: r.resource_type, sleeps: r.max_party_size, of: r.metadata?.offering_ids || [] }]))
      s.note(`rooms (API): ${rows.map((r) => `${r.name} [${r.resource_type}] sleeps ${r.max_party_size} of ${(r.metadata?.offering_ids || []).length} type(s)`).join('; ')}`)
      for (const t of TYPES) {
        for (const name of t.rooms) {
          const r = journal.rooms[name]
          s.check(`${name} is a room of the ${t.key} type (API)`, r && r.of.length === 1 && r.of[0] === typeId(t.key), JSON.stringify(r || {}))
        }
      }
      const text = flat(await page.innerText('main'))
      s.check('the Rooms list says each room\'s type', new RegExp(esc(journal.room_types.cottage?.title || 'Valley'), 'i').test(text), text.slice(0, 300))
      s.done()
    },

    // ---------------------------------------------------------------- stay
    async stay() {
      const s = step('stay: a guest in another browser books two nights in a Valley cottage, to pay at the property')
      const { mon, wed } = plan()
      const opts = await options()
      journal.location_id = journal.location_id || opts.locations?.[0]?.id
      const cottage = (opts.offerings || []).find((o) => o.id === typeId('cottage'))
      journal.booking_options = (opts.offerings || []).map((o) => `${o.title} [${o.mode}] ₹${o.price_amount} sleeps ${o.max_guests} ${JSON.stringify(o.stay)}`)
      s.note(`booking options (public API): ${journal.booking_options.join(' | ').slice(0, 600)}`)
      s.check('the public booking options carry the room types as stays, with the owner\'s check-in and weekend minimum',
        cottage && cottage.mode === 'accommodation' && cottage.stay?.check_in === '13:00' && cottage.stay?.weekend_min_nights === 2,
        JSON.stringify(cottage || {}).slice(0, 200))
      s.check('payment is at the property only (no online gateway is connected)',
        (opts.payment_methods || []).every((m) => ['cod', 'pay_at_business', 'pay_later'].includes(m)), (opts.payment_methods || []).join(', '))
      const g = await guestPage()
      await g.goto(journal.public_url, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(g, 'public-home', true)
      const ctas = await g.locator('a[href*="/book"]').evaluateAll((as) => as.filter((a) => a.getClientRects().length).map((a) => `${a.innerText.trim()}|${a.getAttribute('href')}`))
      s.check('the website offers a way to book a stay', ctas.length > 0, [...new Set(ctas)].slice(0, 8).join(' · '))
      await g.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      await s.shot(g, 'book-page', true)
      const choices = (await g.locator('button.ls-book__choice').allInnerTexts()).map(flat)
      s.note(`the Book page offers: ${choices.join(' | ').slice(0, 400)}`)
      s.check('each room type says its price a night', TYPES.every((t) => choices.some((c) => t.re.test(c) && /a night/i.test(c))), choices.join(' | ').slice(0, 300))
      const type = new RegExp(esc(journal.room_types.cottage?.title || 'Valley'), 'i')
      const r = await bookThrough(g, s, { label: 'stay', type, checkIn: mon, checkOut: wed, guests: 2, who: ANANYA })
      s.note(`the page said before booking: rules "${r.asked.rules}"; ${r.asked.ok || r.asked.alert}; summary "${r.asked.summary.slice(0, 200)}"`)
      s.check('before booking, the page says check-in from 1 pm and check-out by 11 am', /1:00\s*pm/i.test(r.asked.rules) && /11:00\s*am/i.test(r.asked.rules), r.asked.rules)
      s.check(`the cottage is free for ${mon} → ${wed}`, r.asked.available, r.asked.ok || r.asked.alert)
      s.check('the summary shows the stay\'s total: 2 nights · ₹19,000', /2 nights\s*·\s*₹\s?19,000/.test(r.asked.summary), r.asked.summary.slice(0, 200))
      await s.shot(g, 'stay-done', true)
      const done = r.done || {}
      journal.first = { number: done.number, manage_url: done.manageUrl, check_in: mon, check_out: wed, page_title: done.title }
      s.note(`the page says: "${done.title}" — ${done.lede} ${done.alert} | ${done.facts}`)
      s.check('the guest gets a booking number and a link to manage it', Boolean(done.number && done.manageUrl), done.lede || done.alert)
      const bk = r.api
      journal.first.id = bk?.id || ''
      if (bk) {
        journal.first.api = { status: bk.status, starts_at: bk.starts_at, ends_at: bk.ends_at, total: bk.total_amount, rooms: bk.resource_names, payment: bk.payment_status, mode: bk.reservation_mode }
        s.note(`booking (API): ${JSON.stringify(journal.first.api)}`)
        s.check('a stay from 1 pm on the first day to 11 am on the last (API)',
          bk.reservation_mode === 'accommodation' && istDayOf(bk.starts_at) === mon && clockOf(bk.starts_at) === '13:00' && istDayOf(bk.ends_at) === wed && clockOf(bk.ends_at) === '11:00',
          `${bk.starts_at} – ${bk.ends_at}`)
        s.check('it comes to ₹19,000 (two nights at ₹9,500, API)', Number(bk.total_amount) === 19000, String(bk.total_amount))
        s.check('the guest holds a Valley cottage — never another type\'s room (API)', (bk.resource_names || []).length === 1 && /^Cottage [12]$/.test(bk.resource_names[0]), JSON.stringify(bk.resource_names))
        s.check('to be paid at the property (API)', bk.payment_status === 'pending_offline', `${bk.payment_method} / ${bk.payment_status}`)
        const says = /^confirmed$/i.test(done.title) ? 'confirmed' : /waiting|request/i.test(done.title) ? 'pending' : done.title
        s.check('what the page tells the guest matches the booking\'s state', says === bk.status, `page "${done.title}" / booking ${bk.status}`)
      }
      if (done.manageUrl) {
        await g.goto(done.manageUrl, { waitUntil: 'networkidle' })
        await settled(g)
        const m = flat(await g.innerText('main'))
        await s.shot(g, 'manage-link', true)
        journal.first.manage_text = m.slice(0, 400)
        s.check('the guest\'s link shows the stay, its dates, the total and where to come',
          m.includes(done.number) && /valley/i.test(m) && /19,000/.test(m) && /Madikeri|Kaggodlu/i.test(m), m.slice(0, 260))
      }
      await g.context().close()
      s.done()
    },

    // ------------------------------------------------------------- overlap
    async overlap() {
      const s = step('overlap: the second cottage, a third refused, another type still free, back-to-back nights, the weekend minimum, the room\'s size')
      const { mon, wed, thu, sat, sun, mon2 } = plan()
      const type = new RegExp(esc(journal.room_types.cottage?.title || 'Valley'), 'i')
      // 1. Rohit, same nights: the other cottage.
      const g1 = await guestPage()
      const second = await bookThrough(g1, s, { label: 'second', type, checkIn: mon, checkOut: wed, guests: 2, who: ROHIT })
      s.check('a second guest for the same nights gets the other cottage', Boolean(second.done?.number), second.asked.alert || second.done?.lede)
      journal.second = { number: second.done?.number, manage_url: second.done?.manageUrl, id: second.api?.id, rooms: second.api?.resource_names }
      const rooms = [...(journal.first?.api?.rooms || []), ...(second.api?.resource_names || [])].sort()
      s.check('the two guests are in Cottage 1 and Cottage 2 (API)', JSON.stringify(rooms) === JSON.stringify(['Cottage 1', 'Cottage 2']), JSON.stringify(rooms))
      await g1.context().close()
      // 2. Farah, same nights: no cottage is left.
      const g2 = await guestPage()
      await g2.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      const third = await askFor(g2, { type, checkIn: mon, checkOut: wed, guests: 2 })
      await s.shot(g2, 'third-refused', true)
      s.check('a third guest for those nights is told there is no cottage free', !third.available && Boolean(third.alert), third.alert || third.ok)
      const sneak = await publicJson('POST', `/v1/public/websites/${journal.slug}/bookings`, {
        location_id: journal.location_id, offering_id: typeId('cottage'), starts_at: `${mon}T13:00:00+05:30`, ends_at: `${wed}T11:00:00+05:30`,
        party_size: 2, payment_method: 'pay_at_business', guest: FARAH,
      })
      s.check('booking a third cottage through the API is refused', sneak.status === 409, `${sneak.status} ${JSON.stringify(sneak.error).slice(0, 160)}`)
      // 3. The pool villa is untouched by the cottages being full.
      const villa = await range(typeId('villa'), mon, wed)
      s.check('the pool villa is still free for those nights', villa.data?.available === true && (villa.data?.resources || []).every((r) => /villa/i.test(r.name)),
        JSON.stringify(villa.data || villa.error).slice(0, 200))
      // 4. Back to back: in on the day the others leave.
      const next = await range(typeId('cottage'), wed, thu)
      s.check(`a cottage is free from ${wed} (check-out 11 am, check-in 1 pm)`, next.data?.available === true, JSON.stringify(next.data || next.error).slice(0, 160))
      // 5. The weekend minimum, on the page and through the API.
      await g2.goto(`${journal.public_url}/book`, { waitUntil: 'networkidle' })
      const weekend = await askFor(g2, { type, checkIn: sat, checkOut: sun, guests: 2 })
      await s.shot(g2, 'weekend-one-night', true)
      s.check('one Saturday night is refused on the page, saying the weekend minimum', !weekend.available && /at least 2 nights/i.test(weekend.alert), weekend.alert || weekend.ok)
      const twoNights = await range(typeId('cottage'), sat, mon2)
      s.check('two weekend nights are fine', twoNights.data?.available === true, JSON.stringify(twoNights.data || twoNights.error).slice(0, 160))
      const oneNight = await publicJson('POST', `/v1/public/websites/${journal.slug}/bookings`, {
        location_id: journal.location_id, offering_id: typeId('cottage'), starts_at: `${sat}T13:00:00+05:30`, ends_at: `${sun}T11:00:00+05:30`,
        party_size: 2, payment_method: 'pay_at_business', guest: FARAH,
      })
      s.check('one Saturday night through the API is refused', oneNight.status >= 400 && oneNight.status < 500 && !oneNight.data, `${oneNight.status} ${JSON.stringify(oneNight.error).slice(0, 160)}`)
      // 6. The room's size.
      const crowd = await range(typeId('cottage'), wed, thu, 4)
      s.check('four guests in a cottage that sleeps two is refused', crowd.data?.available === false, JSON.stringify(crowd.data || crowd.error).slice(0, 160))
      // 7. Another type's room, asked for by name.
      const wrong = await publicJson('POST', `/v1/public/websites/${journal.slug}/bookings`, {
        location_id: journal.location_id, offering_id: typeId('villa'), starts_at: `${thu}T13:00:00+05:30`, ends_at: `${addDays(thu, 2)}T11:00:00+05:30`,
        party_size: 2, resource_ids: [journal.rooms?.['Bungalow 1']?.id].filter(Boolean), payment_method: 'pay_at_business', guest: FARAH,
      })
      s.check('a pool villa stay in Bungalow 1, asked for through the API, is refused', wrong.status >= 400 && wrong.status < 500 && !wrong.data,
        `${wrong.status} ${JSON.stringify(wrong.error).slice(0, 160)}`)
      await g2.context().close()
      s.done()
    },

    // ------------------------------------------------------------- arrival
    async arrival() {
      const s = step('arrival: the owner hears of the stay, sees the room and the total, confirms it; the guest sees it')
      const id = journal.first?.id
      await page.goto(`${WS}/b/${B}/notifications`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(page, 'notifications', true)
      const noteText = flat(await page.innerText('main'))
      s.check('a notification tells the owner about the new booking, naming which', /new booking/i.test(noteText) && noteText.includes(journal.first?.number || '—'), noteText.slice(0, 300))
      await page.goto(`${WS}/b/${B}/bookings`, { waitUntil: 'networkidle' })
      const list = flat(await page.innerText('main'))
      await s.shot(page, 'reservations', true)
      s.check('the Reservations list shows each stay\'s room and its last day', /Cottage [12]/.test(list) && /Ananya Rao/.test(list), list.slice(0, 300))
      await page.goto(`${WS}/b/${B}/bookings/${id}`, { waitUntil: 'networkidle' })
      await s.shot(page, 'stay-new', true)
      const detail = flat(await page.innerText('main'))
      s.check('the stay shows the guest, the room, the nights and the total', /Ananya Rao/.test(detail) && /Room\s*Cottage [12]/i.test(detail) && /19,000/.test(detail), detail.slice(0, 300))
      const confirm = page.getByRole('button', { name: /^confirm$/i })
      if (await confirm.count()) {
        await confirm.first().click()
        const yes = page.getByRole('dialog').getByRole('button', { name: /^(yes|confirm)/i })
        if (await yes.count()) await yes.first().click()
        await sleep(2500)
        await page.reload({ waitUntil: 'networkidle' })
      }
      const bk = await booking(id)
      s.check('the stay is confirmed (API)', bk.status === 'confirmed', bk.status)
      await s.shot(page, 'stay-confirmed', true)
      const g = await guestPage()
      await g.goto(journal.first.manage_url, { waitUntil: 'networkidle' })
      await settled(g)
      const seen = flat(await g.innerText('main'))
      await s.shot(g, 'guest-confirmed', true)
      s.check('the guest\'s link now says Confirmed', /confirmed/i.test(seen), seen.slice(0, 200))
      await g.context().close()
      const hist = await history(id)
      journal.first.history = hist.map((h) => `${h.from_status || '—'}→${h.to_status} ${h.reason || ''} (${h.by || '?'})`)
      s.note(`what happened (API): ${journal.first.history.join(' | ')}`)
      s.done()
    },

    // -------------------------------------------------------- guest-cancel
    async guestCancel() {
      const s = step('guest cancels: Rohit cancels from his link; the cottage is free again for those nights')
      const sec = journal.second || {}
      const { mon, wed } = plan()
      const g = await guestPage()
      await g.goto(sec.manage_url, { waitUntil: 'networkidle', timeout: 120000 })
      await settled(g)
      await s.shot(g, 'second-manage', true)
      const cancel = g.getByRole('button', { name: /cancel booking/i })
      s.check('the guest\'s link offers Cancel booking', (await cancel.count()) > 0)
      if (await cancel.count()) {
        await cancel.first().click()
        await sleep(600)
        const yes = g.getByRole('button', { name: /yes, cancel/i })
        s.check('it asks first', (await yes.count()) > 0)
        if (await yes.count()) await yes.first().click()
        await sleep(2500)
      }
      const said = flat(await g.innerText('main'))
      await s.shot(g, 'second-cancelled', true)
      s.check('the guest\'s page says it is cancelled', /cancelled/i.test(said), said.slice(0, 200))
      const bk = await booking(sec.id)
      s.check('the stay is cancelled (API)', bk.status === 'cancelled', bk.status)
      const hist = await history(sec.id)
      const byGuest = hist.find((h) => h.to_status === 'cancelled')
      s.check('the cancellation is recorded as the guest\'s, not the owner\'s', byGuest && byGuest.by === 'customer', JSON.stringify(byGuest || {}).slice(0, 160))
      const again = await range(typeId('cottage'), mon, wed)
      s.check(`a cottage is free again for ${mon} → ${wed}`, again.data?.available === true, JSON.stringify(again.data || again.error).slice(0, 160))
      await g.context().close()
      s.done()
    },

    // -------------------------------------------------------------- return
    async ret(owner) {
      const s = step('return: a new session another day — the stay under Confirmed, the guest in Guests')
      const c = await browser.newContext(VIEW)
      await c.addCookies(sessionCookies({ ...owner, token: mintToken(owner) }))
      const p3 = await c.newPage()
      await p3.goto(`${WS}/b/${B}`, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(p3, 'return-home', true)
      const home = flat(await p3.innerText('main'))
      journal.return_home = home.slice(0, 800)
      s.note(`home: ${home.slice(0, 300)}`)
      s.check('the home is no longer the empty start', !/No products or services yet/i.test(home), home.slice(0, 200))
      if (/add your opening hours/i.test(home)) s.note('the home still asks for opening hours (a stay keeps check-in and check-out times instead)')
      await p3.goto(`${WS}/b/${B}/bookings?status=confirmed`, { waitUntil: 'networkidle' })
      const conf = flat(await p3.innerText('main'))
      await s.shot(p3, 'return-confirmed', true)
      s.check('Ananya\'s stay is under Confirmed', /Ananya Rao/.test(conf), conf.slice(0, 240))
      await p3.goto(`${WS}/b/${B}/bookings?status=cancelled`, { waitUntil: 'networkidle' })
      s.check('Rohit\'s is under Cancelled', /Rohit Menon/.test(flat(await p3.innerText('main'))))
      const customers = await api('GET', `/v1/platform/businesses/${B}/customers`)
      const ananya = (customers.data || []).find?.((x) => /ananya rao/i.test(x.display_name || x.name || ''))
      if (ananya) {
        await p3.goto(`${WS}/b/${B}/customers/${ananya.id}`, { waitUntil: 'networkidle' })
        const page2 = flat(await p3.innerText('main'))
        await s.shot(p3, 'return-guest', true)
        s.check('Ananya\'s guest page shows her stay', page2.includes(journal.first.number) || /booking|stay/i.test(page2), page2.slice(0, 240))
      } else s.check('the guest who booked is in Guests (API)', false, JSON.stringify(customers.data).slice(0, 200))
      await c.close()
      s.done()
    },
  }
}
