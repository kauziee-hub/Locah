import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader, StatusPill } from '@/components/ModuleState'
import { addCustomerNote, changeCustomerState } from '../actions'
import { ActionButton } from '@/components/ActionButton'
import { dayTimeLabel } from '@/lib/when'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { ConsentPanel, type ConsentRow } from './ConsentPanel'
import { owes, rupees, type Account } from '../../khata/types'
import { timelineText, type TimelineSummary } from './timeline-text'
import { LocalTime } from '@/components/LocalTime'
import { TagsEditor } from './TagsEditor'
import { PrivacyPanel, type Privacy } from './PrivacyPanel'

export const dynamic = 'force-dynamic'

type CustomerDetail = {
  id: string
  display_name: string
  email: string | null
  phone: string | null
  status: string
  tags?: string[]
  version: number
}

type TimelineEntry = {
  id: string
  activity_type: string
  summary: TimelineSummary
  occurred_at: string
}

type Note = { id: string; body: string; created_at: string }

export default async function CustomerDetailPage({
  params,
}: {
  params: { businessId: string; customerId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/v1/platform/businesses/${params.businessId}/customers/${params.customerId}`
  const res = await apiTry<{ data: CustomerDetail }>(base, token)
  if (!res.ok) {
    return (
      <div>
        <Link href={`/b/${params.businessId}/customers`}>← Customers</Link>
        <PageHeader title="Customer" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Customers" />
      </div>
    )
  }
  const customer = res.data.data

  const [timelineRes, notesRes, consentRes, contextRes, khataRes, tagsRes, privacyRes] = await Promise.all([
    apiTry<{ data: TimelineEntry[] }>(`${base}/timeline`, token),
    apiTry<{ data: Note[] }>(`${base}/notes`, token),
    apiTry<{ data: { history: ConsentRow[] } }>(`${base}/consents`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(params.businessId)),
    // Their khata, when the credit book is on and the viewer may see it (§14.5).
    apiTry<{ data: { account: Account | null } }>(
      `/v1/platform/businesses/${params.businessId}/ledger/lookup?contact_id=${params.customerId}`, token),
    apiTry<{ data: { tag: string }[] }>(`/v1/platform/businesses/${params.businessId}/customers/tags`, token),
    apiTry<{ data: Privacy }>(`${base}/privacy`, token),
  ])
  const khata = khataRes.ok ? khataRes.data.data.account : undefined
  const timeline = timelineRes.ok ? timelineRes.data.data || [] : []
  const notes = notesRes.ok ? notesRes.data.data || [] : []
  const perms = contextRes.ok ? contextRes.data.data.permissions ?? [] : []
  const canUpdate = perms.includes('customers.update')

  const stateActions =
    customer.status === 'active'
      ? [
          { action: 'block', label: 'Block', confirm: `Block ${customer.display_name}? They can no longer order or book online.` },
          { action: 'archive', label: 'Archive', confirm: `Archive ${customer.display_name}? Their history is kept; they leave your list.` },
        ]
      : [{
          action: 'restore',
          label: customer.status === 'blocked' ? 'Unblock' : 'Bring back',
          confirm: customer.status === 'blocked' ? `Unblock ${customer.display_name}? They can order and book online again.` : undefined,
        }]
  const STATUS: Record<string, string> = { active: 'Active', blocked: 'Blocked', archived: 'Archived' }

  return (
    <div className="bos-page">
      <PageHeader
        breadcrumb={<Link href={`/b/${params.businessId}/customers`}>Customers</Link>}
        title={customer.display_name}
        subtitle={[customer.phone, customer.email].filter(Boolean).join(' · ') || undefined}
      />

      <div className="bos-pay__confirm" style={{ marginBottom: '1rem' }}>
        <StatusPill value={customer.status} label={STATUS[customer.status] ?? customer.status} />
        {canUpdate ? stateActions.map((item) => (
          <ActionButton key={item.action} className="btn-ghost" label={item.label} busyLabel="Saving…" confirm={item.confirm}
            run={changeCustomerState.bind(null, params.businessId, params.customerId, item.action)} />
        )) : null}
      </div>

      <TagsEditor businessId={params.businessId} customerId={params.customerId} tags={customer.tags ?? []}
        version={customer.version} known={tagsRes.ok ? tagsRes.data.data.map((t) => t.tag) : []} canChange={canUpdate} />

      {consentRes.ok ? (
        <ConsentPanel
          businessId={params.businessId}
          customerId={params.customerId}
          history={consentRes.data.data.history}
          canChange={canUpdate}
        />
      ) : null}

      {privacyRes.ok ? (
        <PrivacyPanel businessId={params.businessId} customerId={params.customerId} name={customer.display_name}
          privacy={privacyRes.data.data} canExport={perms.includes('customers.export')} canErase={perms.includes('customers.erase')} />
      ) : null}

      {khata !== undefined ? (
        <section className="bos-card" style={{ marginTop: '1.5rem', maxWidth: '40rem' }} aria-labelledby="khata-h">
          <h2 id="khata-h">Khata</h2>
          {khata ? (
            <p style={{ margin: 0, display: 'flex', gap: '.8rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <strong className="bos-khata-bal">{owes(khata)}</strong>
              {khata.credit_limit !== null ? <span className="bos-hint">Limit {rupees(khata.credit_limit)}</span> : null}
              {khata.over_limit ? <StatusPill value="over limit" tone="bad" /> : null}
              <Link href={`/b/${params.businessId}/khata/${khata.id}`}>Open khata</Link>
            </p>
          ) : (
            <p className="bos-hint" style={{ margin: 0 }}>No khata yet — it opens the first time you bill them on credit.</p>
          )}
        </section>
      ) : null}

      <section style={{ marginTop: '1.75rem' }}>
        <h2 >Activity</h2>
        {timeline.length === 0 ? (
          <p style={{ opacity: 0.8 }}>Nothing recorded for this customer yet.</p>
        ) : (
          <ul className="bos-timeline">
            {timeline.map((entry) => (
              <li key={entry.id}>
                <span>{timelineText(entry.activity_type, entry.summary)}</span>
                <LocalTime value={entry.occurred_at} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={{ marginTop: '1.75rem', maxWidth: '32rem' }}>
        <h2 >Notes</h2>
        {notes.length === 0 ? <p style={{ opacity: 0.8 }}>No notes yet.</p> : null}
        <ul style={{ paddingLeft: '1.1rem' }}>
          {notes.map((note) => (
            <li key={note.id} style={{ marginBottom: '0.4rem' }}>
              {note.body}
              <span style={{ opacity: 0.6 }}> · {dayTimeLabel(note.created_at)}</span>
            </li>
          ))}
        </ul>
        <ActionForm action={addCustomerNote} className="ws-form" resetOnSuccess aria-label="Add a note">
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="customerId" value={params.customerId} />
          <textarea name="body" placeholder="Add a note — only your team sees it" required maxLength={5000} aria-label="Note" />
          <div><SubmitButton busy="Adding…">Add note</SubmitButton></div>
        </ActionForm>
      </section>
    </div>
  )
}
