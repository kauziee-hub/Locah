import { timingSafeEqual } from 'node:crypto'
import { revalidatePath, revalidateTag } from 'next/cache'
import { NextResponse } from 'next/server'

/**
 * Drop the cached copy of one business's public website (Doc 12 §11.7:
 * published pages are ISR, revalidated on the publish event).
 *
 * Called by the worker's `website.revalidate` subscriber whenever something the
 * site renders from changes — a publish, a module switched on or off, an
 * offering, a plan, a location. The web app is its own deployment, so this is
 * the only way the platform can reach its cache. It only ever *clears* a cache
 * entry: the next visitor re-reads the API, which decides everything. A
 * shared secret keeps strangers from making the site re-render on demand.
 *
 * Without REVALIDATE_SECRET configured the route does not exist (404), and the
 * fetch-level fallback window in lib/public-website.ts applies.
 */
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$/

function sameSecret(given: string, expected: string): boolean {
  const a = Buffer.from(given)
  const b = Buffer.from(expected)
  return a.length === b.length && timingSafeEqual(a, b)
}

export async function POST(request: Request) {
  const secret = process.env.REVALIDATE_SECRET
  if (!secret) return NextResponse.json({ error: 'not_found' }, { status: 404 })
  if (!sameSecret(request.headers.get('x-locah-revalidate-secret') || '', secret)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }
  let slug = ''
  try {
    const body = (await request.json()) as { slug?: unknown }
    slug = typeof body.slug === 'string' ? body.slug.trim().toLowerCase() : ''
  } catch {
    slug = ''
  }
  if (!SLUG.test(slug)) return NextResponse.json({ error: 'invalid_slug' }, { status: 400 })

  revalidateTag(`website:${slug}`)
  revalidateTag(`marketplace:${slug}`)
  revalidatePath(`/${slug}`, 'layout')
  return NextResponse.json({ revalidated: true, slug })
}
