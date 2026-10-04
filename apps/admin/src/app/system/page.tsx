import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { retryPaymentWebhook } from './actions'
import { AdminNotice, EmptyState, MONO, PageHeader, Pill, ROW, TABLE, TD, TH } from '@/components/AdminNotice'

export const dynamic = 'force-dynamic'

type SystemHealth = {
  dead_letters: Array<{
    id: string
    source_table: string
    source_id: string
    event_type: string
    final_error: string | null
    attempt_count: number | null
    created_at: string | null
    resolved_at: string | null
    resolution_note: string | null
  }>
  outbox_by_status: Array<{ status: string; count: number; oldest: string | null }>
  failed_jobs: Array<{
    id: string
    job_type: string
    status: string
    last_error: string | null
    attempt_count: number | null
    created_at: string | null
  }>
  failing_event_types: Array<{ event_type: string; count: number }>
}

/**
 * ADM-019 — System Health & Events.
 *
 * Doc 11 §17.7 exit: dead-letter, provider, search, payment, Website and
 * entitlement failures must be visible. Each of those classes flows through
 * the outbox or the async-job table, so they surface here as a dead-letter
 * row or a failing event type.
 */
export default async function AdminSystemHealthPage() {
  const token = await getAccessToken()
  if (!token) {
    return (
      <div>
        <PageHeader title="System Health" />
        <AdminNotice error={{ status: 0, code: 'NO_SESSION', message: 'no session' }} />
      </div>
    )
  }

  const res = await apiTry<{ data: SystemHealth }>('/v1/admin/system/health?limit=100', token)
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="System Health" />
        <AdminNotice error={res.error} />
      </div>
    )
  }
  const health = res.data.data

  const backlog = health.outbox_by_status.reduce(
    (sum, row) => (row.status === 'pending' || row.status === 'failed' ? sum + row.count : sum),
    0
  )

  return (
    <div>
      <PageHeader
        title="System Health"
        subtitle={
          health.dead_letters.length === 0 && backlog === 0
            ? 'Nothing stuck.'
            : `${health.dead_letters.length} dead letters · ${backlog} outbox events pending or failed`
        }
      />

      <section>
        <h2 style={{ fontSize: '1.15rem' }}>Outbox backlog</h2>
        <div style={{ overflowX: 'auto' }}>
          <table style={TABLE}>
            <thead>
              <tr>
                <th style={TH}>Status</th>
                <th style={TH}>Count</th>
                <th style={TH}>Oldest</th>
              </tr>
            </thead>
            <tbody>
              {health.outbox_by_status.map((row) => (
                <tr key={row.status} style={ROW}>
                  <td style={TD}>
                    <Pill value={row.status} />
                  </td>
                  <td style={{ ...TD, fontVariantNumeric: 'tabular-nums' }}>{row.count}</td>
                  <td style={TD}>{row.oldest ? new Date(row.oldest).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section style={{ marginTop: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem' }}>Failing event types</h2>
        {health.failing_event_types.length === 0 ? (
          <p style={{ opacity: 0.7 }}>No failed or dead-lettered outbox events.</p>
        ) : (
          <ul style={{ lineHeight: 1.8 }}>
            {health.failing_event_types.map((f) => (
              <li key={f.event_type}>
                <code style={MONO}>{f.event_type}</code> — {f.count}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={{ marginTop: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem' }}>Dead letters</h2>
        <div style={{ overflowX: 'auto' }}>
          <table style={TABLE}>
            <thead>
              <tr>
                <th style={TH}>When</th>
                <th style={TH}>Source</th>
                <th style={TH}>Event</th>
                <th style={TH}>Attempts</th>
                <th style={TH}>Final error</th>
                <th style={TH}>Action</th>
              </tr>
            </thead>
            <tbody>
              {health.dead_letters.map((d) => (
                <tr key={d.id} style={ROW}>
                  <td style={{ ...TD, whiteSpace: 'nowrap' }}>
                    {d.created_at ? new Date(d.created_at).toLocaleString() : '—'}
                  </td>
                  <td style={{ ...TD, ...MONO, opacity: 0.7 }}>{d.source_table}</td>
                  <td style={{ ...TD, ...MONO }}>{d.event_type}</td>
                  <td style={{ ...TD, fontVariantNumeric: 'tabular-nums' }}>{d.attempt_count ?? '?'}</td>
                  <td style={{ ...TD, opacity: 0.85 }}>{d.final_error ?? '—'}</td>
                  <td style={TD}>
                    {d.resolved_at ? (
                      <span style={{ opacity: 0.7 }}>{d.resolution_note || 'Resolved'}</span>
                    ) : d.source_table === 'payments_webhook_receipts' ? (
                      <form action={retryPaymentWebhook}>
                        <input type="hidden" name="receiptId" value={d.source_id} />
                        <button type="submit">Retry</button>
                      </form>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {health.dead_letters.length === 0 ? (
          <EmptyState>No dead-letter events. Nothing has exhausted its retries.</EmptyState>
        ) : null}
      </section>

      <section style={{ marginTop: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem' }}>Failed async jobs</h2>
        {health.failed_jobs.length === 0 ? (
          <p style={{ opacity: 0.7 }}>No failed jobs.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>When</th>
                  <th style={TH}>Job type</th>
                  <th style={TH}>Status</th>
                  <th style={TH}>Attempts</th>
                  <th style={TH}>Last error</th>
                </tr>
              </thead>
              <tbody>
                {health.failed_jobs.map((j) => (
                  <tr key={j.id} style={ROW}>
                    <td style={{ ...TD, whiteSpace: 'nowrap' }}>
                      {j.created_at ? new Date(j.created_at).toLocaleString() : '—'}
                    </td>
                    <td style={{ ...TD, ...MONO }}>{j.job_type}</td>
                    <td style={TD}>
                      <Pill value={j.status} />
                    </td>
                    <td style={{ ...TD, fontVariantNumeric: 'tabular-nums' }}>
                      {j.attempt_count ?? '?'}
                    </td>
                    <td style={{ ...TD, opacity: 0.85 }}>{j.last_error ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
