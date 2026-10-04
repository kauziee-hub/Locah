import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { platformUrl } from '@platform/config'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchPublicWebsite } from '@/lib/public-website'
import { SiteFrame } from '@/components/website/SiteFrame'
import { siteLang } from '@/lib/site-lang'
import { PayActions, type PayView } from './PayActions'

export const dynamic = 'force-dynamic'

async function fetchPay(slug: string, token: string): Promise<PayView | null> {
  const res = await fetch(
    `${platformUrl('api')}/v1/public/websites/${encodeURIComponent(slug)}/pay/${encodeURIComponent(token)}`,
    { cache: 'no-store' }
  )
  if (!res.ok) return null
  return ((await res.json()) as { data: PayView }).data
}

export async function generateMetadata({ params }: { params: { slug: string; token: string } }): Promise<Metadata> {
  const view = await fetchPay(params.slug, params.token)
  const amount = view && view.state !== 'paid' && view.paying_now
    ? `Pay ${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: Number.isInteger(view.paying_now) ? 0 : 2 }).format(view.paying_now)}`
    : 'Payment'
  return privatePageMetadata(params.slug, amount, view?.business.name)
}

/**
 * A payment link from a business (Founder refinement — Payments §6–§7, §13):
 * what it is for, the amount due, what is being paid now, what was already
 * paid and what will remain — in the business's own colours. Paying by UPI
 * goes straight to the business; the business confirms it arrived, so the page
 * says "still being confirmed" until it does. The link is the credential.
 */
export default async function PayPage({ params, searchParams }: { params: { slug: string; token: string }; searchParams?: { lang?: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const view = await fetchPay(params.slug, params.token)
  if (!view) notFound()
  const site = await fetchPublicWebsite(params.slug)
  const qr = `${platformUrl('api')}/v1/public/websites/${encodeURIComponent(params.slug)}/pay/${encodeURIComponent(params.token)}/upi-qr.svg`
  return (
    <SiteFrame site={site} lang={siteLang(site?.website.languages, searchParams?.lang, true)} style={{ minHeight: undefined }}>
      <main className="ls-section">
        <div className="ls-inner ls-bill ls-pay">
          {site ? (
            <p>
              <Link href={`/${params.slug}`}>← {view.business.name}</Link>
            </p>
          ) : null}
          <PayActions slug={params.slug} token={params.token} initial={view} qrUrl={qr} />
        </div>
      </main>
    </SiteFrame>
  )
}
