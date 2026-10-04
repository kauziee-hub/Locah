import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import { fetchPublicWebsite } from '@/lib/public-website'
import { siteLang } from '@/lib/site-lang'
import { SiteFrame } from '@/components/website/SiteFrame'
import WaitlistOfferClient from './WaitlistOfferClient'

export const dynamic = 'force-dynamic'

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Your waitlist place')
}

/** A place a customer was waiting for has opened up: take it, or let it pass on. In the business's own colours. */
export default async function WaitlistOfferPage({
  params,
  searchParams,
}: {
  params: { slug: string; entryId: string }
  searchParams?: { t?: string; lang?: string }
}) {
  const site = await fetchPublicWebsite(params.slug)
  return (
    <SiteFrame site={site} lang={siteLang(site?.website.languages, searchParams?.lang, true)}>
      <WaitlistOfferClient slug={params.slug} entryId={params.entryId} token={searchParams?.t || ''} />
    </SiteFrame>
  )
}
