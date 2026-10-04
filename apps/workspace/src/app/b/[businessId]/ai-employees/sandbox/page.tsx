import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { Card, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { SandboxConsole } from './SandboxConsole'
import { clearTestRecords, payTestRecord, type TestRecord } from './sandbox-actions'

export const dynamic = 'force-dynamic'

type Overview = {
  scenarios: { key: string; label: string; channel: string; employee: string; about: string }[]
  notice: string
  business: { name: string }
  location: string | null
  ready: Record<string, boolean>
  suggestions: Record<string, string[]>
}

const READY_WORDS: Record<string, string> = {
  'offerings-catalog': 'Catalogue',
  orders: 'Orders',
  fulfilment: 'Pickup & delivery',
  bookings: 'Bookings',
  inventory: 'Stock',
  leads: 'Enquiries',
}

/**
 * AI Employee Studio. The AI employee answers from this business's real
 * catalogue, prices, stock, hours and free times and gets the same permission
 * decision a live one would — but it sends no message. What it proposes can be
 * checked (nothing saved) or approved in Test Mode, which keeps a TEST order,
 * booking or enquiry and takes test payments through a test adapter: isolated
 * from real records, customers and money. AI employees as a product are a later
 * layer (Doc 11 §6.4), so nothing here claims they are switched on.
 */
export default async function AISandboxPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const [res, testsRes, ctxRes] = await Promise.all([
    apiTry<{ data: Overview }>(`/v1/b/${b}/ai-employees/sandbox`, token),
    apiTry<{ data: { records: TestRecord[]; notice: string } }>(`/v1/b/${b}/ai-employees/test-records`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const canTest = ctxRes.ok && ctxRes.data.data.permissions.includes('ai_employees.manage')
  const tests = testsRes.ok ? testsRes.data.data.records : []
  const header = (
    <PageHeader
      title="AI Employee Studio"
      subtitle="See how an AI employee would handle your customers, using your real menu, prices, stock, hours and free times. No message is sent to anyone. Approve what it proposes in Test Mode to see the order, booking or enquiry it would make — as a test record only."
      actions={
        <>
          <StatusPill value="sandbox" tone="warn" label="No messages sent" />
          <StatusPill value="test" tone="info" label="Test Mode" />
        </>
      }
    />
  )
  if (!res.ok) {
    return <div className="bos-page">{header}<GateNotice error={res.error} businessId={b} moduleLabel="the AI Employee Studio" /></div>
  }
  const data = res.data.data

  return (
    <div className="bos-page">
      {header}
      <Card tone="urgent" style={{ marginBottom: '1rem' }}>
        <p style={{ margin: 0 }}>
          <strong>No external message is sent.</strong> Customers never see this, no real order, booking or enquiry
          is created, no money moves, and no AI model is called — answers come from {data.business.name}&rsquo;s own
          records by rule. Test Mode keeps its results apart, as test records.
        </p>
      </Card>
      <Card style={{ marginBottom: '1rem' }}>
        <h2 style={{ margin: '0 0 .5rem' }}>What the AI can see right now</h2>
        <ul className="bos-sandbox__ready">
          {Object.entries(READY_WORDS).map(([key, label]) => (
            <li key={key}>
              <StatusPill value={data.ready[key] ? 'ready' : 'off'} tone={data.ready[key] ? 'good' : 'neutral'}
                          label={`${label}: ${data.ready[key] ? 'ready' : 'not set up'}`} />
            </li>
          ))}
          {data.location ? <li className="bos-hint" style={{ margin: 0 }}>Location: {data.location}</li> : null}
        </ul>
      </Card>
      <SandboxConsole businessId={b} scenarios={data.scenarios} suggestions={data.suggestions} notice={data.notice}
                      canTest={canTest} />
      <TestRecords businessId={b} records={tests} canTest={canTest} />
    </div>
  )
}

/** What Test Mode made: test orders, bookings and enquiries, with test payments. */
function TestRecords({ businessId, records, canTest }: { businessId: string; records: TestRecord[]; canTest: boolean }) {
  return (
    <section className="bos-card bos-tests" aria-labelledby="tests-h" style={{ marginTop: '1.25rem' }}>
      <div className="bos-card__head">
        <h2 id="tests-h" className="bos-card__title">Test records ({records.length})</h2>
        {canTest && records.length > 0 ? (
          <form action={clearTestRecords}>
            <input type="hidden" name="businessId" value={businessId} />
            <button type="submit" className="btn-quiet">Clear test records</button>
          </form>
        ) : null}
      </div>
      <p className="bos-hint">
        Made in Test Mode only. They are not in your orders, bookings, enquiries or numbers, no customer was told, and
        test bookings do not hold a time on your real calendar. Test payments use a test adapter — no money moves.
      </p>
      {records.length === 0 ? (
        <p className="bos-empty">Nothing yet. Approve something the AI proposes in Test Mode and it appears here.</p>
      ) : (
        <ul className="bos-tests__list">
          {records.map((r) => (
            <li key={r.id} className="bos-tests__row">
              <div className="bos-tests__main">
                <span className="bos-tag">{r.kind_label}</span>
                <strong>{r.summary}</strong>
                <span className="bos-hint">
                  {r.reference}
                  {r.amount != null ? ` · ₹${r.amount.toLocaleString('en-IN')}` : ''}
                  {r.payment ? ` · ${r.payment.method} ${r.payment.reference}` : ''}
                  {r.payment?.reason ? ` · ${r.payment.reason}` : ''}
                </span>
              </div>
              <span className={`bos-tests__status is-${r.status}`}>{r.status_label}</span>
              {canTest && r.can_pay ? (
                <div className="bos-tests__pay">
                  <form action={payTestRecord}>
                    <input type="hidden" name="businessId" value={businessId} />
                    <input type="hidden" name="recordId" value={r.id} />
                    <input type="hidden" name="outcome" value="succeed" />
                    <button type="submit" className="btn">Take test payment</button>
                  </form>
                  <form action={payTestRecord}>
                    <input type="hidden" name="businessId" value={businessId} />
                    <input type="hidden" name="recordId" value={r.id} />
                    <input type="hidden" name="outcome" value="fail" />
                    <button type="submit" className="btn-quiet">Try a failed payment</button>
                  </form>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
