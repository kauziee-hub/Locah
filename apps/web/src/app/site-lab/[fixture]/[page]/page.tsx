import { notFound } from 'next/navigation'
import { WebsitePageView } from '@/components/website/WebsitePageView'
import { readLabPage } from '@/lib/site-lab'

export const dynamic = 'force-dynamic'
export const metadata = { robots: { index: false, follow: false } }

/** An inner page of a site-lab fixture (menu, about, visit…). Local only. */
export default async function SiteLabInnerPage({
  params,
  searchParams,
}: {
  params: { fixture: string; page: string }
  searchParams?: { from?: string; to?: string }
}) {
  const data = await readLabPage(params.fixture, params.page, searchParams)
  if (!data) notFound()
  return <WebsitePageView data={data} />
}
