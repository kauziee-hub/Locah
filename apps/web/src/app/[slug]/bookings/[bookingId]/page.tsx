import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import { fetchPublicWebsite } from '@/lib/public-website'
import { siteLang } from '@/lib/site-lang'
import { SiteFrame } from '@/components/website/SiteFrame'
import ManageBookingClient from './ManageBookingClient'

export const dynamic = 'force-dynamic'

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Your booking')
}

/** WEB-010 Booking Management — Doc 09 expired link / cancel-window states, in the business's own colours. */
export default async function ManageBookingPage({
  params,
  searchParams,
}: {
  params: { slug: string; bookingId: string }
  searchParams?: { token?: string; lang?: string }
}) {
  const token = searchParams?.token || ''
  const site = await fetchPublicWebsite(params.slug)
  return (
    <SiteFrame site={site} lang={siteLang(site?.website.languages, searchParams?.lang, true)}>
      <ManageBookingClient slug={params.slug} name={site?.business.display_name ?? null} bookingId={params.bookingId} token={token} />
    </SiteFrame>
  )
}
