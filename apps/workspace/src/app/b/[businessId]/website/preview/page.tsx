import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { SiteEditor, type EditorPage } from './SiteEditor'
import { platformUrl } from '@platform/config'

export const dynamic = 'force-dynamic'

type WebsiteResponse = {
  data: {
    website: { status: string }
    draft: {
      generated_by?: string | null
      theme?: Record<string, unknown> | null
      pages: EditorPage[]
    } | null
  }
}

type PreviewTokenResponse = { data: { preview_path: string } }

/**
 * CORE-005/006/007 — the Website editor (Doc 09 §9.1.1).
 *
 * Controls on the left, the real draft site on the right through a preview
 * token. Every field maps to its SectionType schema, so editing cannot produce
 * a section the structured model would reject; layout, section order,
 * navigation and theme stay in their own editors.
 */
export default async function WebsiteEditorPage({
  params,
}: {
  params: { businessId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const [siteRes, previewRes] = await Promise.all([
    apiTry<WebsiteResponse>(`/v1/b/${params.businessId}/website`, token),
    apiTry<PreviewTokenResponse>(`/v1/b/${params.businessId}/website/preview-token`, token),
  ])

  if (!siteRes.ok) {
    return (
      <div>
        <PageHeader title="Edit your website" />
        <GateNotice error={siteRes.error} businessId={params.businessId} moduleLabel="Website" />
      </div>
    )
  }

  const draft = siteRes.data.data.draft
  const base = `/b/${params.businessId}/website`
  const webUrl = platformUrl('web')

  if (!draft || draft.pages.length === 0) {
    return (
      <div>
        <PageHeader
          title="Edit your website"
          subtitle="Once LOCAH has built your site, you can change any of it here."
        />
        <p style={{ color: 'var(--color-muted)' }}>
          There is no draft yet. Generate your website first and it will appear here ready to
          edit.
        </p>
      </div>
    )
  }

  return (
    <SiteEditor
      businessId={params.businessId}
      pages={draft.pages}
      theme={draft.theme || {}}
      previewPath={previewRes.ok ? previewRes.data.data.preview_path : null}
      webUrl={webUrl}
      publishHref={`${base}/publish`}
    />
  )
}
