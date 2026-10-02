import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { SandboxConsole } from './SandboxConsole'

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
 * AI Employee Sandbox (a demonstration, not a live employee). It reads this
 * business's real catalogue, prices, stock, hours and free times and shows the
 * same permission decision a live AI employee would get — but it sends no
 * message and saves nothing. AI employees as a product are a later layer
 * (Doc 11 §6.4), so nothing here claims they are switched on.
 */
export default async function AISandboxPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const res = await apiTry<{ data: Overview }>(`/v1/b/${b}/ai-employees/sandbox`, token)
  const header = (
    <PageHeader
      title="AI sandbox"
      subtitle="See how an AI employee would handle your customers, using your real menu, prices, stock, hours and free times. It is a simulation: no message is sent and nothing is saved."
      actions={
        <>
          <StatusPill value="sandbox" tone="warn" label="Sandbox" />
          <StatusPill value="simulation" tone="info" label="Simulation" />
        </>
      }
    />
  )
  if (!res.ok) {
    return <div className="bos-page">{header}<GateNotice error={res.error} businessId={b} moduleLabel="the AI sandbox" /></div>
  }
  const data = res.data.data

  return (
    <div className="bos-page">
      {header}
      <Card tone="urgent" style={{ marginBottom: '1rem' }}>
        <p style={{ margin: 0 }}>
          <strong>No external message is sent.</strong> Customers never see this, no order, booking or enquiry is
          created, and no AI model is called — answers come from {data.business.name}&rsquo;s own records by rule.
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
      <SandboxConsole businessId={b} scenarios={data.scenarios} suggestions={data.suggestions} notice={data.notice} />
    </div>
  )
}
