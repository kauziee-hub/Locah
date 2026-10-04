import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { EmptyState, GateNotice, PageHeader, ROW, StatusPill, TABLE, TD, TH } from '@/components/ModuleState'
import { createOffer } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Offer = {
  id: string
  code: string
  name: string
  kind: string
  discount_value: number
  times_used: number
  status: string
}

const INPUT: React.CSSProperties = { width: '100%' }

/** Offers and coupons, including the form that creates one. Checkout validates later. */
export default async function OffersPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/v1/platform/businesses/${params.businessId}`
  const offersRes = await apiTry<{ offers: Offer[] }>(`${base}/marketing/offers`, token)
  if (!offersRes.ok) {
    return (
      <div>
        <PageHeader title="Offers & coupons" />
        <GateNotice error={offersRes.error} businessId={params.businessId} moduleLabel="Marketing" />
      </div>
    )
  }
  const offers = offersRes.data.offers ?? []

  return (
    <div>
      <PageHeader
        title="Offers & coupons"
        subtitle="Usage limits and expiry live on the offer. Checkout will validate the code later."
        actions={<Link href={`/b/${params.businessId}/marketing`}>Campaigns</Link>}
      />

      {offers.length === 0 ? <EmptyState>No offers yet.</EmptyState> : (
        <div className="ws-tablewrap">
          <table style={TABLE}>
            <thead>
              <tr>
                <th style={TH}>Code</th>
                <th style={TH}>Name</th>
                <th style={TH}>Kind</th>
                <th style={TH}>Value</th>
                <th style={TH}>Used</th>
                <th style={TH}>Status</th>
              </tr>
            </thead>
            <tbody>
              {offers.map((offer) => (
                <tr key={offer.id} style={ROW}>
                  <td style={TD}>{offer.code}</td>
                  <td style={TD}>{offer.name}</td>
                  <td style={TD}>{offer.kind}</td>
                  <td style={TD}>{offer.discount_value}</td>
                  <td style={TD}>{offer.times_used}</td>
                  <td style={TD}>
                    <StatusPill value={offer.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <section id="new-offer" style={{ marginTop: '2rem', maxWidth: '32rem' }}>
        <h2>New offer</h2>
        <SafeForm action={createOffer} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input name="code" required maxLength={30} placeholder="Code, for example DIWALI10" style={INPUT} />
          <input name="name" required maxLength={80} placeholder="Name" style={INPUT} />
          <label>
            Kind
            <select name="kind" defaultValue="percentage_discount" style={INPUT}>
              <option value="percentage_discount">Percentage off</option>
              <option value="fixed_amount">Fixed amount</option>
              <option value="free_delivery">Free delivery</option>
              <option value="first_order">First order</option>
              <option value="win_back">Win back</option>
            </select>
          </label>
          <input name="discount_value" type="number" min="0.01" step="0.01" required placeholder="Discount value" style={INPUT} />
          <label>
            Uses per customer
            <input name="usage_limit_per_customer" type="number" min="1" defaultValue={1} style={INPUT} />
          </label>
          <button type="submit">Create offer</button>
        </SafeForm>
      </section>
    </div>
  )
}
