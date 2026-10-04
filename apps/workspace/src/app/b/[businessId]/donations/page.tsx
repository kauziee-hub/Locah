import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { addCause, addGift } from '../supply-actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Cause = { id: string; name: string; status: string }
type Gift = { id: string; donor_name: string; amount_paise: number; receipt_reference: string; cause: string }

const rupees = (paise: number) => `₹${(paise / 100).toLocaleString('en-IN')}`

export default async function DonationsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const loaded = await apiTry<{ data: { causes: Cause[]; gifts: Gift[] } }>(`/v1/platform/businesses/${b}/donations`, token)
  if (!loaded.ok) {
    return <div className="bos-page"><PageHeader title="Donations" /><GateNotice error={loaded.error} businessId={b} moduleLabel="Donations" /></div>
  }
  const { causes, gifts } = loaded.data.data
  return (
    <div className="bos-page">
      <PageHeader title="Donations" subtitle="Causes, donors and receipts. A gift is not an order." />
      <SafeForm action={addCause} className="bos-form">
        <h2>Cause</h2>
        <input type="hidden" name="businessId" value={b} />
        <label>Name<input name="name" required maxLength={160} /></label>
        <button type="submit" className="btn-primary">Open cause</button>
      </SafeForm>
      <SafeForm action={addGift} className="bos-form">
        <h2>Record a gift</h2>
        <input type="hidden" name="businessId" value={b} />
        <label>Cause
          <select name="cause_id" required>
            {causes.map((cause) => <option key={cause.id} value={cause.id}>{cause.name}</option>)}
          </select>
        </label>
        <label>Donor<input name="donor_name" required maxLength={160} /></label>
        <label>Amount (₹)<input name="rupees" type="number" min="1" step="0.01" required /></label>
        <button type="submit" className="btn-primary">Save gift</button>
      </SafeForm>
      <h2>Recent gifts</h2>
      {gifts.length === 0 ? <p>No gifts yet.</p> : (
        <ul>
          {gifts.map((gift) => (
            <li key={gift.id}>{gift.donor_name} gave {rupees(gift.amount_paise)} to {gift.cause}. Receipt {gift.receipt_reference}.</li>
          ))}
        </ul>
      )}
    </div>
  )
}
