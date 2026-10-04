import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { optInDiscoverable, setVisibility } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type MarketplaceSettings = {
  visibility: string
  state: string
  eligibility: { eligible: boolean; reasons: string[] }
  discoverability_means: string[]
  index_health?: { last_status: string; last_reason?: string | null } | null
}

/**
 * Eligibility reasons in the owner's language.
 *
 * The API answers with codes — `business_not_active`, `profile_public_facts_missing`
 * — which are the right shape for a contract and the wrong thing to print on a
 * page. Anything unmapped falls back to the code rather than disappearing, so a
 * new reason is visible rather than silently swallowed.
 */
const VISIBILITY_TEXT: Record<string, string> = {
  private: 'Private — only you and your team',
  unlisted: 'Unlisted — reachable by link, not in search',
  discoverable: 'Discoverable — can appear in Marketplace search',
}

const STATE_TEXT: Record<string, string> = {
  draft: 'Draft — not live yet',
  onboarding: 'Being set up',
  active: 'Live',
  suspended: 'Suspended',
  closed: 'Closed',
}

const REASON_TEXT: Record<string, string> = {
  business_not_active: 'This business has not gone live yet',
  business_status_blocked: 'This business is on hold and cannot be listed',
  visibility_not_discoverable: 'You have not chosen to be discoverable',
  profile_missing: 'Your business profile has not been filled in',
  profile_public_facts_missing: 'Your profile is missing details customers need, such as how to reach you',
  website_not_published: 'Your website has not been published',
}

function reasonText(code: string): string {
  return REASON_TEXT[code] ?? code
}

export default async function MarketplacePresencePage({
  params,
}: {
  params: { businessId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const res = await apiTry<{ data: MarketplaceSettings }>(
    `/v1/b/${params.businessId}/marketplace`,
    token
  )
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Marketplace Presence" />
        <GateNotice
          error={res.error}
          businessId={params.businessId}
          moduleLabel="Marketplace Presence"
        />
      </div>
    )
  }
  const data = res.data.data

  return (
    <div>
      <h1 style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>Marketplace Presence</h1>
      <p style={{ maxWidth: '40rem', lineHeight: 1.5 }}>
        Choose whether customers can find you in Marketplace search. You are never listed
        automatically — this is always your decision, and you can change it at any time.
      </p>
      <dl style={{ marginTop: '1rem', lineHeight: 1.6 }}>
        <dt style={{ fontWeight: 700 }}>Current visibility</dt>
        <dd>{VISIBILITY_TEXT[data.visibility] ?? data.visibility}</dd>
        <dt style={{ fontWeight: 700 }}>Business state</dt>
        <dd>{STATE_TEXT[data.state] ?? data.state}</dd>
        <dt style={{ fontWeight: 700 }}>Eligible to index?</dt>
        <dd>
          {data.eligibility.eligible
            ? 'Yes'
            : `No — ${data.eligibility.reasons.map(reasonText).join('; ')}`}
        </dd>
        <dt style={{ fontWeight: 700 }}>Index health</dt>
        <dd>
          {data.index_health
            ? `${data.index_health.last_status}${
                data.index_health.last_reason ? ` (${data.index_health.last_reason})` : ''
              }`
            : 'never'}
        </dd>
      </dl>

      <section style={{ marginTop: '1.5rem' }}>
        <h2>What discoverability means</h2>
        <ul>
          {data.discoverability_means.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <SafeForm action={optInDiscoverable}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="confirmed" value="true" />
          <button type="submit">Confirm & become discoverable</button>
        </SafeForm>
        <SafeForm action={setVisibility}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="visibility" value="unlisted" />
          <button type="submit">Set unlisted</button>
        </SafeForm>
        <SafeForm action={setVisibility}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="visibility" value="private" />
          <button type="submit">Set private</button>
        </SafeForm>
      </section>
    </div>
  )
}
