#!/usr/bin/env node
/**
 * Render the Supabase auth email templates for a specific platform origin.
 *
 * The links in these emails cannot be relative and cannot be resolved at send
 * time — Supabase mails whatever HTML it was given. So the origin has to be
 * baked in, and baking it into the checked-in source is how a `localhost` link
 * reaches a real inbox. The source under `src/` therefore carries a placeholder,
 * and this script writes the deployable copies into `dist/`.
 *
 * Usage:
 *   node tools/render-email-templates.mjs --origin https://locah.in
 *   PLATFORM_DOMAIN=locah.in node tools/render-email-templates.mjs
 *
 * `dist/` is generated and gitignored: the origin belongs to a deployment, not
 * to the repository.
 */

import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const SRC = join(here, '..', 'infra', 'supabase', 'email-templates', 'src')
const OUT = join(here, '..', 'infra', 'supabase', 'email-templates', 'dist')
const PLACEHOLDER = '__LOCAH_WEB_ORIGIN__'
const CODE_ONLY = new Set(['confirm-signup.html', 'magic-link.html', 'reauthentication.html'])
// Security notifications tell the person something happened. They carry no link
// on purpose (a "click here" in a security email is what phishing looks like),
// so there is no origin to bake in.
const NOTIFICATIONS = new Set([
  'password-changed.html',
  'email-changed.html',
  'phone-changed.html',
  'identity-linked.html',
  'identity-unlinked.html',
  'mfa-enrolled.html',
  'mfa-unenrolled.html',
])

function resolveOrigin() {
  const flagIndex = process.argv.indexOf('--origin')
  if (flagIndex !== -1 && process.argv[flagIndex + 1]) {
    return process.argv[flagIndex + 1]
  }
  if (process.env.NEXT_PUBLIC_WEB_URL) {
    return process.env.NEXT_PUBLIC_WEB_URL
  }
  const domain = (process.env.PLATFORM_DOMAIN || '').trim()
  if (domain && domain !== 'localhost') {
    return `https://${domain.replace(/^\.+/, '')}`
  }
  return null
}

const raw = resolveOrigin()
if (!raw) {
  console.error(
    'No origin. Pass --origin https://your-domain, or set PLATFORM_DOMAIN / NEXT_PUBLIC_WEB_URL.'
  )
  process.exit(1)
}

const origin = raw.trim().replace(/\/+$/, '')

if (!/^https?:\/\/[^/\s]+$/.test(origin)) {
  console.error(`Not a bare origin: ${origin}`)
  process.exit(1)
}

// A confirmation link that points at a developer's machine is the exact bug
// this script exists to prevent, so it is refused rather than warned about.
if (/^http:\/\//.test(origin) && !/localhost|127\.0\.0\.1/.test(origin)) {
  console.error(`Refusing to render a plaintext origin for email: ${origin}`)
  process.exit(1)
}
if (/localhost|127\.0\.0\.1/.test(origin) && !process.argv.includes('--allow-localhost')) {
  console.error(
    `Refusing to bake ${origin} into an email template. Pass --allow-localhost if this is a throwaway local test.`
  )
  process.exit(1)
}

await mkdir(OUT, { recursive: true })
const files = (await readdir(SRC)).filter((f) => f.endsWith('.html'))

for (const file of files) {
  const source = await readFile(join(SRC, file), 'utf8')
  // Code-only and notification emails deliberately have no link, so there is no
  // origin to render. All link-based emails still require a deployment origin.
  const hasLink = /\bhref\s*=|\.ConfirmationURL\b|\.TokenHash\b/i.test(source)
  const codeOnly =
    !hasLink &&
    ((CODE_ONLY.has(file) && source.includes('{{ .Token }}')) || NOTIFICATIONS.has(file))
  if (!source.includes(PLACEHOLDER) && !codeOnly) {
    console.error(`${file} has no ${PLACEHOLDER} — it would ship with a stale origin.`)
    process.exit(1)
  }
  const rendered = source.split(PLACEHOLDER).join(origin)
  await writeFile(join(OUT, file), rendered, 'utf8')
  console.log(`  ${file}`)
}

console.log(`\n${files.length} template(s) rendered for ${origin} into infra/supabase/email-templates/dist/`)
console.log('Paste each into Supabase Dashboard -> Authentication -> Emails.')
