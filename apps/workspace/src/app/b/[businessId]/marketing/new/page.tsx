import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { createCampaign } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

const INPUT: React.CSSProperties = { width: '100%' }

/** Campaign creation. The builder (audience, offer, approval) is the next page. */
export default async function NewCampaignPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  return (
    <div>
      <p style={{ marginBottom: '1rem' }}>
        <Link href={`/b/${params.businessId}/marketing`}>Campaigns</Link>
      </p>
      <h1>New campaign</h1>
      <SafeForm action={createCampaign} style={{ display: 'grid', gap: '0.6rem', maxWidth: '32rem', marginTop: '1rem' }}>
        <input type="hidden" name="businessId" value={params.businessId} />
        <label>
          Name
          <input name="name" required maxLength={100} placeholder="Diwali week" style={INPUT} />
        </label>
        <label>
          Goal
          <input name="goal" required maxLength={60} placeholder="Bring back lapsed customers" style={INPUT} />
        </label>
        <label>
          Channel
          <select name="channel" defaultValue="whatsapp" style={INPUT}>
            <option value="whatsapp">WhatsApp</option>
            <option value="meta_ads">Meta ads</option>
          </select>
        </label>
        <label>
          Budget (rupees)
          <input name="budget_rupees" type="number" min="0" step="1" defaultValue={0} style={INPUT} />
        </label>
        <button type="submit">Create draft</button>
      </SafeForm>
    </div>
  )
}
