import type { Metadata } from 'next'
import { fetchPublicWebsite } from '@/lib/public-website'

/** "Checkout · Nila Cafe & Bakehouse" — the tab names the business, not LOCAH. */
async function titled(slug: string, what: string, business?: string | null): Promise<string> {
  const name = business ?? (await fetchPublicWebsite(slug).catch(() => null))?.business.display_name
  return name ? `${what} · ${name}` : what
}

/**
 * A customer's own page — a payment link, a bill, an order being tracked, an
 * account. Never indexed, and its address (which may carry the link's token)
 * is never passed on to another site as a referrer.
 */
export async function privatePageMetadata(slug: string, what: string, business?: string | null): Promise<Metadata> {
  return {
    title: await titled(slug, what, business),
    robots: { index: false, follow: false },
    referrer: 'no-referrer',
  }
}

/** A public action page of the business's site (book, enquire): titled for the business. */
export async function actionPageMetadata(slug: string, what: string): Promise<Metadata> {
  return { title: await titled(slug, what) }
}
