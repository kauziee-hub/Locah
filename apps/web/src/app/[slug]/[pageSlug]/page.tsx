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
  params: { slug: string; pageSlug: string }
  searchParams?: { preview_token?: string; lang?: string }
}): Promise<Metadata> {
  if (RESERVED_SLUGS.has(params.slug)) return {}
  // See the home route: a preview of an unlisted draft needs the token here
  // as well, or the tab title falls back to LOCAH's.
  return websiteMetadata(
    await fetchPublicWebsite(params.slug, params.pageSlug, searchParams?.preview_token),
    { lang: searchParams?.lang }
  )
}

export default async function BusinessWebsitePage({
  params,
  searchParams,
}: {
  params: { slug: string; pageSlug: string }
  searchParams?: { preview_token?: string; lang?: string }
}) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const data = await fetchPublicWebsite(params.slug, params.pageSlug, searchParams?.preview_token)
  if (!data) notFound()
  return (
    <>
      {/* Local SEO: the business, this page (with its breadcrumb) and its
          content as one schema.org graph, written on the server. */}
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
