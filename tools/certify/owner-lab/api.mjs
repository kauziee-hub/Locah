// The lab's reading glass: GET (or POST) one API path as a lab owner.
//   node tools/certify/owner-lab/api.mjs <scenario-variant> GET /v1/b/{B}/offerings
// {B} is replaced by the journal's business id. Prints the JSON.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mintToken } from './session.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const [run, method = 'GET', p = '/', body] = process.argv.slice(2)
const journal = JSON.parse(readFileSync(path.join(ROOT, 'certify-out/product-e2e/SCENARIOS', run, 'journal.json'), 'utf8'))
const token = mintToken(journal.owner)
const res = await fetch(`http://localhost:8020${p.replaceAll('{B}', journal.business_id)}`, {
  method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body,
})
console.log(res.status, JSON.stringify(await res.json().catch(() => null), null, 1).slice(0, Number(process.env.MAX || 4000)))
