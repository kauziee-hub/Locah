import { notFound } from 'next/navigation'
import { WebsitePageView } from '@/components/website/WebsitePageView'
import { readLabPage } from '@/lib/site-lab'

export const dynamic = 'force-dynamic'
export const metadata = { robots: { index: false, follow: false } }

/**
 * The site lab: a website fixture rendered by the real tenant renderer.
 *
 * Local only. It exists when LOCAH_SITE_LAB_DIR points at fixtures written by
 * `platform_testing.website_fixtures` and is a 404 everywhere else — no
 * database, no API, no business data, nothing to reach in production.
 */
export default async function SiteLabPage({
  params,
  searchParams,
}: {
  params: { fixture: string }
  searchParams?: { from?: string; to?: string }
}) {
  const data = await readLabPage(params.fixture, undefined, searchParams)
  if (!data) notFound()
  return <WebsitePageView data={data} />
}
