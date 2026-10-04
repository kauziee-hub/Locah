import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { ArchiveButton } from './ArchiveButton'
import { FromConversation } from './FromConversation'
import { inr, type Offering } from './types'

export const dynamic = 'force-dynamic'

function priceText(o: Offering): string {
  if (o.offering_type === 'cause') return 'People choose what to give'
  if (o.price_formula) return o.price_amount !== null ? `${inr(o.price_amount)} at today's rate` : 'No price until the rate is entered'
  if (o.sell_units?.length && o.price_amount !== null) {
    const per = String(o.attributes?.price_per ?? 'kg')
    return `${inr(o.price_amount)} per ${per}`
  }
  if (o.price_type === 'enquiry') return 'Price on request'
  if (o.price_type === 'free') return 'Free'
  const p = inr(o.price_amount)
  if (!p) return 'No price yet'
  return o.price_type === 'starting_from' ? `From ${p}` : p
}

/**
 * Catalogue (Capability Universe §6.3: one catalogue, many kinds). Grouped by
 * kind so a restaurant sees its menu and a developer its projects, with what
 * each item still needs before it can show properly.
 */
export default async function OfferingsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const [res, rates, context, talk] = await Promise.all([
    apiTry<{ data: Offering[] }>(`/v1/platform/businesses/${params.businessId}/products`, token),
    apiTry<{ data: unknown[] }>(`/v1/platform/businesses/${params.businessId}/pricing/rates`, token),
    apiTry<{ data: { terms?: Record<string, string> } }>('/v1/me/context', token, businessHeaders(params.businessId)),
    apiTry<{ data: { setup_pending?: string[]; blueprint: { revision: number } } }>(
      `/v1/b/${params.businessId}/interview`, token),
  ])
  const base = `/b/${params.businessId}/offerings`
  // The business's own word for this page (Menu, Services, Products) — the route stays the same.
  const title = (context.ok ? context.data.data.terms?.offerings : undefined) ?? 'Products & services'
  const fromTalk = talk.ok ? talk.data.data.setup_pending ?? [] : []
  const header = (
    <PageHeader
      title={title}
      subtitle="Everything people can buy, book, join, give to or ask about — kept in one place."
      actions={
        <>
          {rates.ok && rates.data.data.length ? <Link className="btn-ghost" href={`${base}/rates`}>Today&apos;s rates</Link> : null}
          <Link className="btn-ghost" href={`${base}/import`}>Import</Link>
          <Link className="btn" href={`${base}/new`}>Add</Link>
        </>
      }
    />
  )
  if (!res.ok) {
    return (
      <div className="bos-page">
        {header}
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Products & services" />
      </div>
    )
  }
  const offerings = res.data.data.filter((o) => o.title !== 'Delivery fee')
  const groups = new Map<string, Offering[]>()
  for (const o of offerings) groups.set(o.kind_label, [...(groups.get(o.kind_label) ?? []), o])

  return (
    <div className="bos-page">
      {header}
      {fromTalk.length && talk.ok ? (
        <FromConversation businessId={params.businessId} names={fromTalk} revision={talk.data.data.blueprint.revision} />
      ) : null}
      {offerings.length === 0 ? (
        <div className="bos-empty">
          Nothing here yet. Add what you sell, the services people book, or what they can enquire about — each
          stays a draft until you make it live.{' '}
          <Link href={`${base}/new`}>Add the first one</Link>, or{' '}
          <Link href={`${base}/import`}>import your list</Link> from a sheet, a PDF or a photo of your menu.
        </div>
      ) : (
        [...groups.entries()].map(([label, items]) => (
          <section key={label} className="bos-section" aria-labelledby={`k-${label}`} style={{ marginTop: '1.4rem' }}>
            <h2 className="bos-section__title" id={`k-${label}`}>
              {label} <span>{items.length}</span>
            </h2>
            <ul className="bos-catalogue">
              {items.map((o) => (
                <li key={o.id} className={o.status === 'archived' ? 'is-muted' : ''}>
                  <Link href={`${base}/${o.id}`} className="bos-catalogue__main">
                    <strong>{o.title}</strong>
                    <span>{priceText(o)}</span>
                    {o.missing_fields?.length ? (
                      <span className="bos-catalogue__needs">Needs: {o.missing_fields.join(', ')}</span>
                    ) : null}
                  </Link>
                  <span className={`bos-state${o.status === 'active' ? ' is-ready' : ' is-off'}`}>
                    {o.status === 'active' ? 'Live' : o.status === 'draft' ? 'Draft' : 'Archived'}
                  </span>
                  <ArchiveButton businessId={params.businessId} offeringId={o.id} archived={o.status === 'archived'} />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
