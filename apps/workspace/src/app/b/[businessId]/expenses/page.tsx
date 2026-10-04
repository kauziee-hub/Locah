import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { addExpense } from '../supply-actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Totals = { total_paise: number; cash_paise: number; bank_paise: number }

const rupees = (paise: number) => `₹${(paise / 100).toLocaleString('en-IN')}`

export default async function ExpensesPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const summary = await apiTry<{ data: Totals }>(`/v1/platform/businesses/${b}/expenses/summary`, token)
  if (!summary.ok) {
    return <div className="bos-page"><PageHeader title="Expenses" /><GateNotice error={summary.error} businessId={b} moduleLabel="Expenses" /></div>
  }
  const data = summary.data.data
  return (
    <div className="bos-page">
      <PageHeader title="Expenses" subtitle="What went out today, in cash and through the bank." />
      <div className="bos-review-summary">
        <div><span>Total</span><strong>{rupees(data.total_paise)}</strong><small>All recorded expenses</small></div>
        <div><span>Cash</span><strong>{rupees(data.cash_paise)}</strong><small>Including petty cash</small></div>
        <div><span>Bank, UPI, card</span><strong>{rupees(data.bank_paise)}</strong><small>Everything that is not cash</small></div>
      </div>
      <SafeForm action={addExpense} className="bos-form">
        <h2>Record an expense</h2>
        <input type="hidden" name="businessId" value={b} />
        <label>Category<input name="category" required maxLength={80} /></label>
        <label>Payee<input name="payee" maxLength={160} /></label>
        <label>Amount (₹)<input name="rupees" type="number" min={0} step="0.01" required /></label>
        <label>Paid from
          <select name="method" defaultValue="cash">
            <option value="cash">Cash</option>
            <option value="bank">Bank</option>
            <option value="upi">UPI</option>
            <option value="card">Card</option>
          </select>
        </label>
        <label><input type="checkbox" name="petty_cash" /> Petty cash</label>
        <button type="submit" className="btn-primary">Save expense</button>
      </SafeForm>
    </div>
  )
}
