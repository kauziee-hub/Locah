// Navigation projection (Doc 05 §9.1 NAV-007–NAV-011; Doc 07 §3.3).
// Run: pnpm --filter @platform/workspace test  (node --test, no extra deps).
/* eslint-disable @typescript-eslint/no-var-requires -- a CommonJS test file for node --test */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const { test } = require('node:test')
const ts = require('typescript')

const source = path.join(__dirname, 'workspace-nav.ts')
const compiled = ts.transpileModule(fs.readFileSync(source, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const loaded = new Module(source, module)
loaded._compile(compiled, source)
const { visibleAreas } = loaded.exports

const OWNER = ['offerings.read', 'bookings.read', 'customers.read', 'modules.configure', 'modules.read']
const MEMBER = ['offerings.read', 'bookings.read']

function items(states, permissions, terms) {
  return visibleAreas(states, permissions, false, terms).flatMap((area) => area.children)
}
const hrefs = (list) => list.map((c) => c.href)

test('an active module projects its destination exactly once', () => {
  const list = items({ 'offerings-catalog': 'active' }, OWNER)
  assert.equal(hrefs(list).filter((h) => h === '/offerings').length, 1)
  assert.equal(list.find((c) => c.href === '/offerings').setup, undefined)
})

test('setup-required is shown, marked, only to people who can complete setup (NAV-008)', () => {
  const owner = items({ 'offerings-catalog': 'setup_required' }, OWNER)
  assert.equal(owner.find((c) => c.href === '/offerings').setup, true)
  assert.equal(hrefs(items({ 'offerings-catalog': 'setup_required' }, MEMBER)).includes('/offerings'), false)
})

test('not entitled, deactivated or never enabled projects no operational entry (NAV-007, NAV-011)', () => {
  for (const state of ['not_entitled', 'deactivated', 'not_enabled', 'unavailable', undefined]) {
    assert.equal(hrefs(items({ 'offerings-catalog': state }, OWNER)).includes('/offerings'), false, String(state))
  }
})

test('a member without route permission never sees the private destination (NAV-009)', () => {
  assert.equal(hrefs(items({ 'offerings-catalog': 'active' }, [])).includes('/offerings'), false)
  assert.equal(hrefs(items({ 'offerings-catalog': 'active' }, null)).includes('/offerings'), false)
})

test("the business's own words name the destination; the route never changes", () => {
  const list = items(
    { 'offerings-catalog': 'active', bookings: 'active', 'customer-relationships': 'active' },
    OWNER,
    { offerings: 'Menu', bookings: 'Reservations', customers: 'Guests' },
  )
  assert.equal(list.find((c) => c.href === '/offerings').label, 'Menu')
  assert.equal(list.find((c) => c.href === '/bookings').label, 'Reservations')
  assert.equal(list.find((c) => c.href === '/customers').label, 'Guests')
  // Without terms the platform word stands.
  const plain = items({ 'offerings-catalog': 'active' }, OWNER)
  assert.equal(plain.find((c) => c.href === '/offerings').label, 'Products & services')
})

test('an older API that sends raw activation states still projects operational modules', () => {
  assert.equal(hrefs(items({ 'offerings-catalog': 'enabled' }, OWNER)).includes('/offerings'), true)
})

test('the AI sandbox follows its permission and deployment switch, never the AI staff module', () => {
  const sandbox = (perms, features) =>
    visibleAreas({}, perms, false, {}, features).flatMap((a) => a.children).map((c) => c.href)
  assert.equal(sandbox(['ai_employees.read'], { ai_sandbox: true }).includes('/ai-employees/sandbox'), true)
  assert.equal(sandbox(['ai_employees.read'], { ai_sandbox: true }).includes('/ai-employees'), false)
  assert.equal(sandbox(['ai_employees.read'], { ai_sandbox: false }).includes('/ai-employees/sandbox'), false)
  assert.equal(sandbox(['ai_employees.read'], {}).includes('/ai-employees/sandbox'), false)
  assert.equal(sandbox(MEMBER, { ai_sandbox: true }).includes('/ai-employees/sandbox'), false)
})
