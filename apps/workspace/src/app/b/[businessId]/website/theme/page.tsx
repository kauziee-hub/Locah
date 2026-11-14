import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { ThemeEditor } from './ThemeEditor'

export const dynamic = 'force-dynamic'

type WebsiteResponse = {
  data: {
    draft: {
      theme: Record<string, unknown> | null
      navigation: { label: string; path: string }[] | null
      pages?: { title: string; slug: string }[]
    } | null
  }
}

export default async function WebsiteThemePage({
  params,
}: {
  params: { businessId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const res = await apiTry<WebsiteResponse>(`/v1/b/${params.businessId}/website`, token)
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Look & menu" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Website" />
      </div>
    )
  }
  const draft = res.data.data.draft
  return (
    <div>
      <PageHeader
        title="Look & menu"
        subtitle="Your site’s colours and lettering, and the links in its header. Changes save to your draft; your live site changes when you publish."
      />
      <ThemeEditor
        businessId={params.businessId}
        theme={draft?.theme || {}}
        navigation={draft?.navigation || []}
        pages={(draft?.pages || []).map((p) => ({ title: p.title, slug: p.slug }))}
      />
      <p style={{ marginTop: '1.5rem' }}>
        <a href={`/b/${params.businessId}/website/preview`}>Open the website editor →</a>
      </p>
    </div>
  )
}
