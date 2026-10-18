import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchPublicWebsite, websiteMetadata } from '@/lib/public-website'
import { WebsitePageView } from '@/components/website/WebsitePageView'
import { siteLang } from '@/lib/site-lang'
import { buildJsonLd, jsonLdText, pageTitle } from '@/lib/structured-data'

export const revalidate = 60

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: { slug: string }
  searchParams?: { preview_token?: string; lang?: string }
}): Promise<Metadata> {
  if (RESERVED_SLUGS.has(params.slug)) return {}
  // The token has to be passed here too. Without it a draft belonging to a
  // Business that is not public yet resolves to nothing, and the tab falls back
  // to LOCAH's own title while the page below shows the business.
  return websiteMetadata(
    await fetchPublicWebsite(params.slug, undefined, searchParams?.preview_token),
    { lang: searchParams?.lang }
  )
}

export default async function BusinessWebsiteHome({
  params,
  searchParams,
}: {
  params: { slug: string }
  searchParams?: { preview_token?: string; lang?: string }
}) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const data = await fetchPublicWebsite(params.slug, undefined, searchParams?.preview_token)
  if (!data) notFound()
  return (
    <>
      {/* Local SEO: the business, this page and its content as one schema.org
          graph, written on the server from the page's own facts. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdText(buildJsonLd(data, pageTitle(data))) }}
      />
      <WebsitePageView
        data={data}
        previewToken={data.is_preview ? searchParams?.preview_token : undefined}
        lang={siteLang(data.website.languages, searchParams?.lang)}
      />
    </>
  )
}
