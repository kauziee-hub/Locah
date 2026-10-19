// Read one lab business through the owner's own API (a debugging aid).
//   node tools/certify/owner-lab/peek.mjs <run dir> <api path>
import { readFileSync } from 'node:fs'
import { mintToken } from './session.mjs'

const [dir, p] = process.argv.slice(2)
const j = JSON.parse(readFileSync(`${dir}/journal.json`, 'utf8'))
const token = mintToken(j.owner)
const res = await fetch(`${process.env.CERTIFY_API || 'http://localhost:8020'}${p.replace('{B}', j.business_id)}`, {
  headers: { Authorization: `Bearer ${token}` },
})
console.log(res.status, JSON.stringify(await res.json(), null, 1).slice(0, Number(process.env.MAX || 6000)))
