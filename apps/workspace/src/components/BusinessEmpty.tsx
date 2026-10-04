import Link from 'next/link'
import { cache } from 'react'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { wsLang } from '@/lib/ws-lang'
import { EmptyState } from '@/components/ui'

type Empty = { title: string; body: string; actions: { label: string; href: string }[] }
export type EmptyModule = 'orders' | 'bookings' | 'customers' | 'leads' | 'fulfilment' | 'inventory'

// One request per page render, however many lists on it are empty.
const load = cache(async (businessId: string, lang: string) => {
  const token = await getAccessToken()
  if (!token) return null
  const res = await apiTry<{ data: Record<string, Empty> }>(
    `/v1/platform/businesses/${businessId}/empty-states?lang=${lang}`, token)
  return res.ok ? res.data.data : null
})

/**
 * An empty list that speaks about THIS business: what will fill it (the
 * owner's own items), whether their website can bring the first one in yet,
 * and the one or two things to do now. Falls back to the page's own words.
 */
export async function BusinessEmpty({
  businessId,
  module,
  fallbackTitle,
  fallback,
}: {
  businessId: string
  module: EmptyModule
  fallbackTitle: string
  fallback: string
}) {
  const all = await load(businessId, wsLang())
  const e = all?.[module]
  if (!e) return <EmptyState title={fallbackTitle}>{fallback}</EmptyState>
  return (
    <EmptyState
      title={e.title}
      action={e.actions.length ? (
        <div className="bos-empty__actions">
          {e.actions.map((a, i) => (
            <Link key={a.href} className={i === 0 ? 'btn' : 'btn btn-ghost'} href={`/b/${businessId}${a.href}`}>
              {a.label}
            </Link>
          ))}
        </div>
      ) : undefined}
    >
      {e.body}
    </EmptyState>
  )
}
