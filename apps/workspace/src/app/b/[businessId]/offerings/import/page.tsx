import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { ImportWizard } from './ImportWizard'
import type { RecentImport } from './types'

export const dynamic = 'force-dynamic'

/**
 * Products & services → Import: a sheet (CSV / XLSX), or a PDF, photo or pasted
 * menu read by LOCAH, becomes drafts the owner checks row by row — then chooses
 * which to make live. Nothing is published by the import itself.
 */
export default async function ImportOfferingsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const [recent, context] = await Promise.all([
    apiTry<{ data: RecentImport[] }>(`/v1/platform/businesses/${params.businessId}/catalogue-import`, token),
    apiTry<{ data: { terms?: Record<string, string> } }>('/v1/me/context', token, businessHeaders(params.businessId)),
  ])
  const base = `/b/${params.businessId}/offerings`
  const title = (context.ok ? context.data.data.terms?.offerings : undefined) ?? 'Products & services'
  const header = (
    <PageHeader
      title={`Import into ${title}`}
      subtitle="Bring in your whole list at once. Everything arrives as a draft — you check it, then choose what goes live."
      breadcrumb={<Link href={base}>{title}</Link>}
    />
  )
  if (!recent.ok) {
    return (
      <div className="bos-page">
        {header}
        <GateNotice error={recent.error} businessId={params.businessId} moduleLabel="Products & services" />
      </div>
    )
  }
  return (
    <div className="bos-page">
      {header}
      <ImportWizard businessId={params.businessId} listTitle={title} recent={recent.data.data} />
    </div>
  )
}
