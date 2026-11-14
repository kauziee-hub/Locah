// WhatsApp, without Meta: a customer messages the business's sandbox number and
// the whole path runs — the same webhook code a real message takes.
//   node tools/certify/owner-lab/whatsapp-check.mjs <scenario-run-dir-name>
// The sandbox records what WOULD have been sent; nothing leaves this machine.
// What this cannot show: Meta's own delivery, template approval, Embedded Signup.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mintToken } from './session.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const API = process.env.CERTIFY_API || 'http://localhost:8020'
const journal = JSON.parse(readFileSync(path.join(ROOT, 'certify-out/product-e2e/SCENARIOS', process.argv[2], 'journal.json'), 'utf8'))
const token = mintToken(journal.owner)
const B = journal.business_id
let passed = 0
let failed = 0
const check = (label, ok, detail = '') => {
  ok ? passed++ : failed++
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ` — ${String(detail).replace(/\s+/g, ' ').slice(0, 260)}` : ''}`)
}
async function api(method, p, body) {
  const res = await fetch(`${API}/v1/platform/businesses/${B}${p}`, {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = await res.json() } catch {}
  return { status: res.status, data: data?.data ?? data }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const CUSTOMER = '+919840055667'

const setup0 = await api('GET', '/messaging/setup')
console.log('setup:', setup0.status, JSON.stringify(setup0.data).slice(0, 300))
if (!setup0.data?.channel) {
  const connected = await api('POST', '/messaging/channel/sandbox', { display_phone: '+919847021456', display_name: journal.business_name || 'Sandbox business' })
  check('the sandbox number connects', connected.status === 200, `${connected.status} ${JSON.stringify(connected.data).slice(0, 200)}`)
}
const setup = await api('GET', '/messaging/setup')
check('WhatsApp shows as connected to the sandbox number', setup.data?.channel?.provider === 'sandbox', JSON.stringify(setup.data?.channel).slice(0, 200))

async function says(text, extra = {}) {
  const res = await api('POST', '/messaging/sandbox/inbound', { from_phone: CUSTOMER, name: 'Anitha (lab customer)', text, ...extra })
  await sleep(2500)
  return res
}
async function thread() {
  const list = await api('GET', '/messaging/conversations')
  const rows = Array.isArray(list.data) ? list.data : list.data?.items || list.data?.conversations || []
  const mine = rows.find((c) => JSON.stringify(c).includes(CUSTOMER.replace('+', ''))) || rows[0]
  if (!mine) return { rows, conversation: null, messages: [] }
  const one = await api('GET', `/messaging/conversations/${mine.id}`)
  const messages = one.data?.messages || one.data?.items || []
  return { rows, conversation: one.data?.conversation || one.data, messages }
}
const line = (m) => `${m.direction === 'inbound' ? 'customer' : m.sent_via || 'business'}: ${String(m.body || m.text || JSON.stringify(m.payload || m.content || '')).replace(/\s+/g, ' ').slice(0, 220)}`

const first = await says('hi')
check('a customer’s "hi" is taken in through the webhook path', first.status === 200, `${first.status} ${JSON.stringify(first.data).slice(0, 200)}`)
let t = await thread()
check('the conversation is in the owner’s WhatsApp inbox', Boolean(t.conversation), `${t.rows.length} conversation(s)`)
console.log(t.messages.map(line).join('\n'))
const outbound = t.messages.filter((m) => m.direction !== 'inbound')
check('the business answers on its own (greeting / menu of what the customer can do)', outbound.length > 0, outbound.map(line).join(' | '))

const second = await says('menu enna iruku? biriyani rate?')
t = await thread()
console.log(t.messages.slice(-3).map(line).join('\n'))
check('a question in Tanglish is received and kept with the customer’s name', second.status === 200 && t.messages.some((m) => /biriyani rate/i.test(String(m.body || m.text || ''))))

// The owner replies from the Workspace inbox.
if (t.conversation?.id) {
  const reply = await api('POST', `/messaging/conversations/${t.conversation.id}/messages`, { text: 'Chicken biriyani ₹280, mutton ₹360. Order here: http://localhost:3200/' + (journal.slug || '') })
  check('the owner’s reply from the inbox is recorded as sent', reply.status === 200, `${reply.status} ${JSON.stringify(reply.data).slice(0, 220)}`)
  t = await thread()
  console.log(t.messages.slice(-2).map(line).join('\n'))
}
const customers = await api('GET', '/customers')
const rows = Array.isArray(customers.data) ? customers.data : customers.data?.items || []
check('the person who messaged is a customer the owner can find', rows.some((c) => JSON.stringify(c).includes('9840055667')), `${rows.length} customers`)
const notes = await api('GET', '/notifications')
const noteRows = Array.isArray(notes.data) ? notes.data : notes.data?.items || []
check('the owner was told about the new WhatsApp message', noteRows.some((n) => /whatsapp|message/i.test(JSON.stringify(n))), noteRows.slice(0, 3).map((n) => n.title).join(' | '))
console.log(`\n${passed} passed, ${failed} failed.`)
process.exit(failed ? 1 : 0)
