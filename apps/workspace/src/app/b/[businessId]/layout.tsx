import { notFound, redirect } from 'next/navigation'
import { ReactNode } from 'react'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { AppSidebar, type NavBusiness } from '@/components/AppSidebar'
import { AdoptLanguage } from '@/components/WorkspaceLanguage'
import { WsWordsProvider } from '@/components/WsWords'
import { wsLang } from '@/lib/ws-lang'
import { isWsLang } from '@/lib/ws-words'

export const dynamic = 'force-dynamic'

type Context = {
  module_states: Record<string, string>
  /** Module readiness for navigation: active | setup_required | … (Doc 05 NAV-007/008). */
  navigation_modules?: Record<string, string>
  /** This business's own words for its destinations (Menu, Reservations, Guests). */
  terms?: Record<string, string>
  permissions: string[]
  solo?: boolean
  workspace_language?: string
}

/**
 * Business workspace shell. Fetches only what the sidebar needs — the business
 * list for the switcher, module states and the viewer's permissions for the
 * area navigation, and the unread count — in one parallel round.
 */
export default async function WorkspaceBusinessLayout({
  children,
  params,
}: {
  children: ReactNode
  params: { businessId: string }
}) {
  const token = await getAccessToken()
  if (!token) {
    // Carry the business through the sign-in hand-off. Without it, someone
    // whose session expired mid-task signs in and lands on the Workspace root,
    // having to re-find the business they were already in.
    redirect(`/login?destination=${encodeURIComponent(`/b/${params.businessId}`)}`)
  }

  const bh = businessHeaders(params.businessId)
  const [businessesRes, contextRes, unreadRes] = await Promise.all([
    apiTry<{ data: NavBusiness[] }>('/v1/platform/businesses', token),
    apiTry<{ data: Context }>('/v1/me/context', token, bh),
    apiTry<{ data: { unread_count: number } }>(
      `/v1/platform/businesses/${params.businessId}/notifications/unread-count`,
      token
    ),
  ])

  const businesses = businessesRes.ok ? businessesRes.data.data : []

  // Someone with a good session but no membership of THIS business used to get
  // the full Workspace shell — real headings, empty tables — for a business
  // that is not theirs. No data leaked (every endpoint refuses separately), but
  // the page confirmed the id exists and read as a broken Workspace rather than
  // a refusal. `notFound` is the honest answer and reveals nothing.
  //
  // The list is the server's own answer to "which businesses is this identity an
  // active member of", so this is a rendering consequence of server-side
  // authorization, not a second opinion about it. It is deliberately skipped
  // when the list could not be loaded: an API outage must not lock an owner out
  // of their own Workspace.
  if (businessesRes.ok && !businesses.some((b) => b.id === params.businessId)) {
    notFound()
  }
  // Readiness-based states when the API sends them; raw activation states only
  // from an older API, so navigation never silently empties during a deploy.
  const moduleStates = contextRes.ok
    ? contextRes.data.data.navigation_modules ?? contextRes.data.data.module_states ?? {}
    : {}
  const terms = contextRes.ok ? contextRes.data.data.terms ?? {} : {}
  const permissions = contextRes.ok ? contextRes.data.data.permissions ?? [] : null
  const unreadCount = unreadRes.ok ? unreadRes.data.data.unread_count : 0
  const solo = contextRes.ok ? Boolean(contextRes.data.data.solo) : false
  // The account's language wins; this browser's cookie is how server pages know it (P1-10E6).
  const saved = contextRes.ok ? contextRes.data.data.workspace_language : undefined
  const lang = isWsLang(saved) ? saved : wsLang()

  return (
    <WsWordsProvider lang={lang}>
    {lang !== wsLang() ? <AdoptLanguage lang={lang} /> : null}
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--color-background)' }}>
      <AppSidebar
        businessId={params.businessId}
        businesses={businesses}
        moduleStates={moduleStates}
        terms={terms}
        permissions={permissions}
        unreadCount={unreadCount}
        solo={solo}
        lang={lang}
      />
      <main className="ws-page" style={{ flex: 1, minWidth: 0 }}>
        {children}
      </main>
    </div>
    </WsWordsProvider>
  )
}
