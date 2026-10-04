import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { EmptyState, GateNotice, PageHeader, ROW, StatusPill, TABLE, TD, TH } from '@/components/ModuleState'
import { createStampCard, earnPoints, issueVoucher, redeemPoints, saveLoyaltyProgram } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Program = {
  id: string
  name: string
  program_type: string
  points_per_rupee: number
  redemption_rupees_per_point: number
  min_redemption_points: number
  expiry_days: number | null
  status: string
}

type Customer = { id: string; display_name: string }
type StampProgram = {
  id: string
  name: string
  required_stamps: number
  reward_kind: string
  reward_details: { item_name?: string }
  status: string
}
type Balance = { customer_contact_id: string; usable_points: number; current_points: number }

const INPUT: React.CSSProperties = { width: '100%' }
const FORM: React.CSSProperties = { display: 'grid', gap: '0.6rem', maxWidth: '32rem' }

/**
 * Loyalty programme the owner actually edits: points, stamp cards, vouchers,
 * and a desk earn/redeem so a completed sale can be recorded before Orders
 * calls the earn hook itself.
 */
export default async function LoyaltyPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/v1/platform/businesses/${params.businessId}`
  const progRes = await apiTry<Program>(`${base}/loyalty/program`, token)
  if (!progRes.ok) {
    return (
      <div>
        <PageHeader title="Loyalty" />
        <GateNotice error={progRes.error} businessId={params.businessId} moduleLabel="Loyalty" />
      </div>
    )
  }
  const prog = progRes.data

  const [customersRes, stampsRes] = await Promise.all([
    apiTry<{ data: Customer[] }>(`${base}/customers`, token),
    apiTry<{ programs: StampProgram[] }>(`${base}/loyalty/stamps`, token),
  ])
  const customers = customersRes.ok ? customersRes.data.data || [] : []
  const stamps = stampsRes.ok ? stampsRes.data.programs || [] : []

  const balances: Balance[] = []
  for (const customer of customers.slice(0, 15)) {
    const bal = await apiTry<Balance>(`${base}/loyalty/customers/${customer.id}/balance`, token)
    if (bal.ok) balances.push(bal.data)
  }
  const pointsOf = new Map(balances.map((row) => [row.customer_contact_id, row.usable_points]))

  return (
    <div>
      <PageHeader
        title="Loyalty"
        subtitle="Points per rupee, stamp cards, and gift vouchers. A completed sale earns points once Orders is connected."
      />

      <section style={{ maxWidth: '32rem' }}>
        <h2>Points programme</h2>
        <SafeForm action={saveLoyaltyProgram} style={FORM}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <label>
            Name
            <input name="name" required defaultValue={prog.name} style={INPUT} />
          </label>
          <label>
            Points per ₹1
            <input name="points_per_rupee" type="number" min="0" step="0.01" required defaultValue={prog.points_per_rupee} style={INPUT} />
          </label>
          <label>
            Rupees per point when redeeming
            <input
              name="redemption_rupees_per_point"
              type="number"
              min="0.01"
              step="0.01"
              required
              defaultValue={prog.redemption_rupees_per_point}
              style={INPUT}
            />
          </label>
          <label>
            Minimum points to redeem
            <input name="min_redemption_points" type="number" min="0" required defaultValue={prog.min_redemption_points} style={INPUT} />
          </label>
          <label>
            Points expire after (days, blank for none)
            <input name="expiry_days" type="number" min="1" defaultValue={prog.expiry_days ?? ''} style={INPUT} />
          </label>
          <label>
            Status
            <select name="status" defaultValue={prog.status} style={INPUT}>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
            </select>
          </label>
          <button type="submit">Save programme</button>
        </SafeForm>
        <p style={{ marginTop: '0.6rem' }}>
          <StatusPill value={prog.status} /> <span style={{ color: 'var(--color-muted)' }}>{prog.program_type}</span>
        </p>
      </section>

      <section style={{ marginTop: '2.25rem' }}>
        <h2>Customer balance</h2>
        {customers.length === 0 ? (
          <EmptyState>
            No customers yet. Add one under <Link href={`/b/${params.businessId}/customers`}>Customers</Link>, then earn points here.
          </EmptyState>
        ) : (
          <div className="ws-tablewrap">
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>Customer</th>
                  <th style={TH}>Usable points</th>
                  <th style={TH}>Earn from a sale</th>
                  <th style={TH}>Redeem</th>
                </tr>
              </thead>
              <tbody>
                {customers.slice(0, 15).map((customer) => (
                  <tr key={customer.id} style={ROW}>
                    <td style={TD}>{customer.display_name}</td>
                    <td style={TD}>{pointsOf.get(customer.id) ?? 0}</td>
                    <td style={TD}>
                      <SafeForm action={earnPoints} style={{ display: 'flex', gap: '0.4rem' }}>
                        <input type="hidden" name="businessId" value={params.businessId} />
                        <input type="hidden" name="contact_id" value={customer.id} />
                        <input name="amount_rupees" type="number" min="1" step="1" placeholder="₹" required style={{ width: '5rem' }} />
                        <button type="submit">Earn</button>
                      </SafeForm>
                    </td>
                    <td style={TD}>
                      <SafeForm action={redeemPoints} style={{ display: 'flex', gap: '0.4rem' }}>
                        <input type="hidden" name="businessId" value={params.businessId} />
                        <input type="hidden" name="contact_id" value={customer.id} />
                        <input type="hidden" name="order_amount_paise" value="100000" />
                        <input name="points" type="number" min="1" step="1" placeholder="pts" required style={{ width: '5rem' }} />
                        <button type="submit">Redeem</button>
                      </SafeForm>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section style={{ marginTop: '2.25rem' }}>
        <h2>Stamp cards</h2>
        {stamps.length === 0 ? <EmptyState>No stamp card yet. The usual one is the 10th visit free.</EmptyState> : null}
        {stamps.length > 0 ? (
          <div className="ws-tablewrap">
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>Card</th>
                  <th style={TH}>Stamps</th>
                  <th style={TH}>Reward</th>
                  <th style={TH}>Status</th>
                </tr>
              </thead>
              <tbody>
                {stamps.map((card) => (
                  <tr key={card.id} style={ROW}>
                    <td style={TD}>{card.name}</td>
                    <td style={TD}>{card.required_stamps}</td>
                    <td style={TD}>{card.reward_details?.item_name || card.reward_kind}</td>
                    <td style={TD}>
                      <StatusPill value={card.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <SafeForm action={createStampCard} style={{ ...FORM, marginTop: '1rem' }}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input name="name" required placeholder="Card name, for example Coffee card" style={INPUT} />
          <input name="required_stamps" type="number" min="2" max="100" defaultValue={10} required style={INPUT} />
          <input name="reward_item" required placeholder="Reward, for example Free coffee" style={INPUT} />
          <button type="submit">Add stamp card</button>
        </SafeForm>
      </section>

      <section style={{ marginTop: '2.25rem', maxWidth: '32rem' }}>
        <h2>Issue a gift voucher</h2>
        <p style={{ color: 'var(--color-muted)', fontSize: '0.9rem' }}>
          This records the balance. Taking the money for the voucher waits on Payments.
        </p>
        <SafeForm action={issueVoucher} style={FORM}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input name="recipient_name" placeholder="Recipient name" style={INPUT} />
          <label>
            Holder
            <select name="holder_contact_id" style={INPUT} defaultValue="">
              <option value="">No customer yet</option>
              {customers.map((customer) => (
                <option key={customer.id} value={customer.id}>
                  {customer.display_name}
                </option>
              ))}
            </select>
          </label>
          <input name="amount_rupees" type="number" min="1" step="1" required placeholder="Amount in rupees" style={INPUT} />
          <button type="submit">Issue voucher</button>
        </SafeForm>
      </section>
    </div>
  )
}
