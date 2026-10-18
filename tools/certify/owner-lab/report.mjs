#!/usr/bin/env node
// A scenario's evidence, readable: every step, what was checked, what the UI
// and the API said, the screenshots — from its journal.json.
//
//   node tools/certify/owner-lab/report.mjs <scenario-run-dir>
//
// Writes <dir>/REPORT.md. A step's state is the last time it ran (a resumed
// run re-runs steps; earlier attempts stay in the journal).
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const dir = path.resolve(process.argv[2] || '.')
const j = JSON.parse(readFileSync(path.join(dir, 'journal.json'), 'utf8'))
const latest = new Map()
for (const s of j.steps) if (s.name !== 'error') latest.set(s.name, s)
const errors = j.steps.filter((s) => s.name === 'error')
const steps = [...latest.values()]
const checks = steps.flatMap((s) => s.checks)
const passed = checks.filter((c) => c.ok).length

const lines = [
  `# Owner lab — ${j.scenario} / ${j.variant}`,
  '',
  `Business \`${j.business_id}\` · owner \`${j.owner?.email}\` · public site ${j.public_url || '—'}`,
  `Started ${j.started_at} · last step ${j.ended_at || '—'}`,
  '',
  `**Checks: ${passed}/${checks.length} pass** across ${steps.length} steps` +
    (errors.length ? ` (${errors.length} interrupted attempts kept in the journal)` : ''),
  '',
  '| Step | State | Checks |',
  '|---|---|---|',
  ...steps.map((s) => `| ${s.name.split(':')[0]} | ${s.status.toUpperCase()} | ${s.checks.filter((c) => c.ok).length}/${s.checks.length} |`),
  '',
]
for (const s of steps) {
  lines.push(`## ${s.name}`, '', `State: **${s.status.toUpperCase()}** (${s.at})`, '')
  for (const c of s.checks) lines.push(`- ${c.ok ? 'PASS' : '**FAIL**'} ${c.label}${c.detail ? ` — ${c.detail.replace(/\s+/g, ' ').slice(0, 200)}` : ''}`)
  if (s.notes.length) {
    lines.push('', 'Notes:', '')
    for (const n of s.notes) lines.push(`- ${n.replace(/\s+/g, ' ').slice(0, 300)}`)
  }
  if (s.shots.length) lines.push('', `Screens: ${s.shots.map((f) => `[${path.basename(f)}](${f})`).join(' · ')}`)
  lines.push('')
}
if (j.page_errors?.length) {
  lines.push('## Browser console errors', '', ...j.page_errors.slice(0, 20).map((e) => `- ${e.replace(/\s+/g, ' ').slice(0, 200)}`), '')
}
writeFileSync(path.join(dir, 'REPORT.md'), lines.join('\n'))
console.log(`${dir}/REPORT.md — ${passed}/${checks.length} checks pass, ${steps.length} steps`)
