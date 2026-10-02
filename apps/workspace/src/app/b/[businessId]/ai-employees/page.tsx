import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { Card, EmptyState, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { decide, runNow, saveSettings, setEnabled, setPaused } from './actions'

export const dynamic = 'force-dynamic'

type Tool = { name: string; tier: string; label: string; on: boolean }
type Employee = {
  kind: string
  name: string
  role: string
  enabled: boolean
  autonomy: string
  limits: Record<string, number>
  limit_bounds: Record<string, [number, number]>
  tools: Tool[]
}
type Action = {
  id: string
  employee: string
  tool_label: string
  tier: string
  status: string
  approval_status: string | null
  input: string
  result: string
  reason: string
  at: string | null
}
type Overview = { module_on: boolean; paused: boolean; employees: Employee[]; needs_approval: Action[]; recent: Action[] }

const TIER_WORDS: Record<string, string> = {
  T0: 'Read only',
  T1: 'Draft — a person sends',
  T2: 'Act within your limits',
  T3: 'Always asks you',
}
const LIMIT_WORDS: Record<string, string> = {
  max_replies_per_chat_per_day: 'Replies per chat per day',
  min_days_overdue: 'Days overdue before a reminder',
  min_days_between_reminders: 'Days between reminders for one bill',
  max_reminders_per_run: 'Reminders per run',
  max_drafts_per_run: 'Draft requisitions per run',
}
const TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral' | 'info'> = {
  done: 'good', drafted: 'info', approved: 'good', awaiting_approval: 'warn', escalated: 'info',
  refused: 'neutral', rejected: 'neutral', failed: 'bad',
}

function when(at: string | null) {
  return at ? new Date(at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : ''
}

export default async function AIEmployeesPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const [res, context] = await Promise.all([
    apiTry<{ data: Overview }>(`/v1/b/${b}/ai-employees`, token),
    apiTry<{ data: { permissions: string[]; features?: Record<string, boolean> } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const sandbox = context.ok && context.data.data.features?.ai_sandbox === true
  const header = (
    <PageHeader
      title="AI employees"
      subtitle="Staff that work inside the limits you set. They use the same tools your team does, answer only from your own records, and every action is written down below."
      actions={sandbox ? <Link className="btn btn-ghost" href={`/b/${b}/ai-employees/sandbox`}>Try it in the sandbox</Link> : undefined}
    />
  )
  if (!res.ok) return <div className="bos-page">{header}<GateNotice error={res.error} businessId={b} moduleLabel="AI staff" /></div>
  const data = res.data.data
  const canManage = (context.ok ? context.data.data.permissions : []).includes('ai_employees.manage')

  return (
    <div className="bos-page bos-ai">
      {header}
      {!data.module_on ? (
        <Card tone="urgent" style={{ marginBottom: '1rem' }}>
          <p style={{ margin: 0 }}>Switch on <strong>AI staff</strong> in Modules to let these employees work.</p>
        </Card>
      ) : null}

      <Card style={{ marginBottom: '1rem' }}>
        <div className="bos-card__head">
          <div>
            <h2 style={{ margin: 0 }}>All AI employees</h2>
            <p className="bos-hint" style={{ margin: '.2rem 0 0' }}>
              Pausing stops every AI employee at once — chats go back to buttons and your team.
            </p>
          </div>
          <StatusPill value={data.paused ? 'paused' : 'active'} tone={data.paused ? 'warn' : 'good'}
                      label={data.paused ? 'Paused' : 'Working'} />
        </div>
        {canManage ? (
          <form action={setPaused} style={{ marginTop: '.8rem' }}>
            <input type="hidden" name="businessId" value={b} />
            <input type="hidden" name="paused" value={data.paused ? 'false' : 'true'} />
            <button type="submit" className={data.paused ? 'btn btn-primary' : 'btn btn-ghost'}>
              {data.paused ? 'Resume all' : 'Pause all'}
            </button>
          </form>
        ) : null}
      </Card>

      <section aria-labelledby="needs-you" style={{ marginBottom: '1.5rem' }}>
        <h2 id="needs-you">Needs your approval</h2>
        {data.needs_approval.length ? (
          <ul className="bos-mini-list">
            {data.needs_approval.map((a) => (
              <li key={a.id}>
                <div>
                  <strong>{a.employee}: {a.input}</strong>
                  <p>{a.reason} · {when(a.at)}</p>
                </div>
                {canManage ? (
                  <div style={{ display: 'flex', gap: '.4rem' }}>
                    <form action={decide}>
                      <input type="hidden" name="businessId" value={b} />
                      <input type="hidden" name="actionId" value={a.id} />
                      <input type="hidden" name="approve" value="true" />
                      <button type="submit" className="btn btn-primary">Approve</button>
                    </form>
                    <form action={decide}>
                      <input type="hidden" name="businessId" value={b} />
                      <input type="hidden" name="actionId" value={a.id} />
                      <input type="hidden" name="approve" value="false" />
                      <button type="submit" className="btn btn-ghost">Decline</button>
                    </form>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="bos-empty">Nothing is waiting for you.</p>
        )}
      </section>

      <div className="bos-grid" style={{ marginBottom: '1.5rem' }}>
        {data.employees.map((e) => (
          <Card key={e.kind}>
            <div className="bos-card__head">
              <h2 style={{ margin: 0 }}>{e.name}</h2>
              <StatusPill value={e.enabled ? 'active' : 'off'} tone={e.enabled ? 'good' : 'neutral'}
                          label={e.enabled ? 'On' : 'Off'} />
            </div>
            <p className="bos-hint">{e.role}</p>
            {canManage ? (
              <form action={setEnabled} style={{ margin: '.4rem 0 .8rem' }}>
                <input type="hidden" name="businessId" value={b} />
                <input type="hidden" name="kind" value={e.kind} />
                <input type="hidden" name="enabled" value={e.enabled ? 'false' : 'true'} />
                <button type="submit" className={e.enabled ? 'btn btn-ghost' : 'btn btn-primary'}
                        disabled={!data.module_on && !e.enabled}>
                  {e.enabled ? 'Switch off' : 'Switch on'}
                </button>
              </form>
            ) : null}
            <form action={saveSettings}>
              <input type="hidden" name="businessId" value={b} />
              <input type="hidden" name="kind" value={e.kind} />
              <label className="bos-label" htmlFor={`${e.kind}-autonomy`}>Autonomy</label>
              <select id={`${e.kind}-autonomy`} name="autonomy" defaultValue={e.autonomy} disabled={!canManage}>
                {['T0', 'T1', 'T2'].map((t) => (
                  <option key={t} value={t}>{t} · {TIER_WORDS[t]}</option>
                ))}
              </select>
              <fieldset style={{ border: 0, padding: 0, margin: '.8rem 0' }}>
                <legend className="bos-label">Allowed tools</legend>
                {e.tools.map((t) => (
                  <label key={t.name} style={{ display: 'flex', gap: '.45rem', alignItems: 'flex-start', margin: '.25rem 0' }}>
                    <input type="checkbox" style={{ minHeight: 0, margin: '.2rem 0 0', flex: 'none' }} name="tools" value={t.name} defaultChecked={t.on} disabled={!canManage} />
                    <span>{t.label} <span className="bos-hint">· {t.tier} {TIER_WORDS[t.tier]}</span></span>
                  </label>
                ))}
              </fieldset>
              {Object.entries(e.limit_bounds).map(([key, [lo, hi]]) => (
                <label key={key} style={{ display: 'block', margin: '.35rem 0' }}>
                  <span className="bos-label">{LIMIT_WORDS[key] ?? key}</span>
                  <input type="number" name={`limit:${key}`} min={lo} max={hi} defaultValue={e.limits[key]}
                         disabled={!canManage} style={{ maxWidth: '8rem' }} />
                </label>
              ))}
              {canManage ? <button type="submit" className="btn btn-ghost" style={{ marginTop: '.5rem' }}>Save limits</button> : null}
            </form>
            {canManage && e.kind !== 'receptionist' ? (
              <form action={runNow} style={{ marginTop: '.6rem' }}>
                <input type="hidden" name="businessId" value={b} />
                <input type="hidden" name="kind" value={e.kind} />
                <button type="submit" className="btn btn-ghost" disabled={!e.enabled}>Run now</button>
              </form>
            ) : null}
          </Card>
        ))}
      </div>

      <section aria-labelledby="recent">
        <h2 id="recent">Recent actions</h2>
        {data.recent.length ? (
          <ul className="bos-mini-list">
            {data.recent.map((a) => (
              <li key={a.id}>
                <div>
                  <strong>{a.employee} · {a.tool_label}</strong>
                  <p>{a.result}{a.input ? ` — “${a.input}”` : ''} · {when(a.at)}</p>
                </div>
                <StatusPill value={a.status} tone={TONE[a.status] ?? 'neutral'} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No actions yet">Switch an AI employee on and its work shows up here.</EmptyState>
        )}
      </section>
    </div>
  )
}
