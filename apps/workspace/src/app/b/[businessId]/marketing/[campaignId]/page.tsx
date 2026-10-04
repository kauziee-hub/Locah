import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader, StatusPill } from '@/components/ModuleState'
import { approveCampaign, dispatchCampaign, prepareCampaign, saveCampaignBuild } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Campaign = {
  id: string
  name: string
  goal: string
  channel: string
  status: string
  budget_paise: number
  estimated_cost_paise: number | null
  audience_segment_id: string | null
  audience_snapshot: { total_count?: number; consented_count?: number; excluded_no_consent_count?: number } | null
  offer_id: string | null
  creative: { text?: string }
  approved_at: string | null
}

type Segment = { id: string; name: string; count: number; whatsapp_offers: number }
type Offer = { id: string; code: string; name: string }
type Results = {
  attribution_label: string
  recipients_sent: number
  excluded_no_consent: number
  excluded_frequency: number
  attributed_orders: number
  data_source: string
}

const INPUT: React.CSSProperties = { width: '100%' }

/**
 * Campaign builder: audience, offer, creative, budget, then approval.
 * Dispatch records a fixture send. Messaging delivers it later.
 */
export default async function CampaignBuilderPage({
  params,
}: {
  params: { businessId: string; campaignId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/v1/platform/businesses/${params.businessId}`
  const res = await apiTry<Campaign>(`${base}/marketing/campaigns/${params.campaignId}`, token)
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Campaign" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Marketing" />
      </div>
    )
  }
  const campaign = res.data
  const [segmentsRes, offersRes, resultsRes] = await Promise.all([
    apiTry<{ data: Segment[] }>(`${base}/customers/segments`, token),
    apiTry<{ offers: Offer[] }>(`${base}/marketing/offers`, token),
    apiTry<Results>(`${base}/marketing/campaigns/${params.campaignId}/results`, token),
  ])
  const segments = segmentsRes.ok ? segmentsRes.data.data || [] : []
  const offers = offersRes.ok ? offersRes.data.offers || [] : []
  const results = resultsRes.ok ? resultsRes.data : null
  const snap = campaign.audience_snapshot
  const locked = campaign.status === 'RUNNING' || campaign.status === 'COMPLETED' || campaign.status === 'CANCELLED'

  return (
    <div>
      <p style={{ marginBottom: '0.75rem' }}>
        <Link href={`/b/${params.businessId}/marketing`}>Campaigns</Link>
      </p>
      <PageHeader title={campaign.name} subtitle={campaign.goal} />
      <p>
        Approval state: <StatusPill value={campaign.status} />
        {campaign.approved_at ? ` · approved ${new Date(campaign.approved_at).toLocaleString('en-IN')}` : ''}
      </p>

      <section style={{ marginTop: '1.5rem', maxWidth: '36rem' }}>
        <h2>Builder</h2>
        <SafeForm action={saveCampaignBuild} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="campaignId" value={campaign.id} />
          <label>
            Audience
            <select name="audience_segment_id" defaultValue={campaign.audience_segment_id ?? ''} style={INPUT} disabled={locked}>
              <option value="">Choose a segment</option>
              {segments.map((segment) => (
                <option key={segment.id} value={segment.id}>
                  {segment.name} · {segment.count} people · {segment.whatsapp_offers} consented
                </option>
              ))}
            </select>
          </label>
          {segments.length === 0 ? (
            <p style={{ color: 'var(--color-muted)', fontSize: '0.9rem' }}>
              No segments yet. Build one under Customers, then come back.
            </p>
          ) : null}
          <label>
            Offer
            <select name="offer_id" defaultValue={campaign.offer_id ?? ''} style={INPUT} disabled={locked}>
              <option value="">No offer</option>
              {offers.map((offer) => (
                <option key={offer.id} value={offer.id}>
                  {offer.code} · {offer.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Channel
            <select name="channel" defaultValue={campaign.channel} style={INPUT} disabled={locked}>
              <option value="whatsapp">WhatsApp</option>
              <option value="meta_ads">Meta ads</option>
            </select>
          </label>
          <label>
            Message
            <textarea name="creative" rows={4} defaultValue={campaign.creative?.text ?? ''} style={INPUT} disabled={locked} />
          </label>
          <label>
            Budget (rupees)
            <input
              name="budget_rupees"
              type="number"
              min="0"
              step="1"
              defaultValue={Math.round(campaign.budget_paise / 100)}
              style={INPUT}
              disabled={locked}
            />
          </label>
          {locked ? null : <button type="submit">Save draft</button>}
        </SafeForm>
      </section>

      <section style={{ marginTop: '1.5rem' }}>
        <h2>Consent count</h2>
        {typeof snap?.total_count === 'number' ? (
          <p>
            {snap.total_count ?? 0} in the audience, {snap.consented_count ?? 0} with marketing consent,{' '}
            {snap.excluded_no_consent_count ?? 0} excluded.
            {campaign.estimated_cost_paise != null
              ? ` Estimated WhatsApp cost ₹${(campaign.estimated_cost_paise / 100).toFixed(0)}.`
              : ''}
          </p>
        ) : (
          <p style={{ color: 'var(--color-muted)' }}>Submit for approval to count consented contacts.</p>
        )}
        {locked ? null : (
          <SafeForm action={prepareCampaign}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="campaignId" value={campaign.id} />
            <button type="submit">Count audience and submit for approval</button>
          </SafeForm>
        )}
      </section>

      <section style={{ marginTop: '1.5rem' }}>
        <h2>Approval</h2>
        <p style={{ maxWidth: '36rem', color: 'var(--color-muted)' }}>
          Only someone with marketing approval can approve. A marketer can draft this page, not send it.
        </p>
        {campaign.status === 'READY_FOR_APPROVAL' || campaign.status === 'DRAFT' ? (
          <SafeForm action={approveCampaign}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="campaignId" value={campaign.id} />
            <button type="submit">Approve</button>
          </SafeForm>
        ) : null}
        {campaign.status === 'APPROVED' ? (
          <SafeForm action={dispatchCampaign}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="campaignId" value={campaign.id} />
            <button type="submit">Record fixture send</button>
          </SafeForm>
        ) : null}
      </section>

      {results ? (
        <section style={{ marginTop: '1.5rem' }}>
          <h2>Results</h2>
          <p>
            Sent {results.recipients_sent}. Excluded for consent {results.excluded_no_consent}. Excluded for frequency{' '}
            {results.excluded_frequency}. Orders attributed {results.attributed_orders}.
          </p>
          <p>
            {results.attribution_label}. {results.data_source}
          </p>
        </section>
      ) : null}
    </div>
  )
}
