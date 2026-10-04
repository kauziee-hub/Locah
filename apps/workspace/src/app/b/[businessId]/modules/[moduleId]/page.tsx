import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { setModuleState } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Step = { key: string; label: string; done: boolean; action: { label: string; href: string } | null }
type Dependency = { module: string; label: string; ready: boolean; enabled: boolean; holding_back: boolean; href: string }
type Setup = {
  module: string
  label: string
  does: string
  customer_can: string[]
  staff_can: string[]
  status: 'not_enabled' | 'deactivated' | 'restricted' | 'waiting' | 'setup_required' | 'partial' | 'ready' | 'unavailable'
  status_label: string
  enabled: boolean
  included: boolean
  steps: Step[]
  remaining: number
  dependencies: Dependency[]
  website: string[]
  home: string | null
  /** Advice that does not block "Working" (e.g. Bookings without opening hours). */
  tips?: { text: string; label: string; href: string }[]
}
type ModuleDetail = { module_id: string; display_name: string; module_class: string; description: string | null }

const TONE: Record<Setup['status'], string> = {
  ready: 'is-good', partial: 'is-warn', setup_required: 'is-warn', waiting: 'is-warn',
  restricted: 'is-bad', not_enabled: '', deactivated: '', unavailable: '',
}

/**
 * Doc 09 CORE-014 — one tool's setup and status. It answers "why isn't this
 * working yet?" in the owner's words: each setup step from the tool's real
 * readiness (true only when the records are there), where to do it, the other
 * tools it is waiting on, and what it adds for customers once it works.
 */
export default async function ModuleSetupPage({
  params,
  searchParams,
}: {
  params: { businessId: string; moduleId: string }
  searchParams: { problem?: string; enabled?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/b/${params.businessId}`
  const [setupRes, ctxRes] = await Promise.all([
    apiTry<{ data: Setup }>(`/v1/b/${params.businessId}/modules/${params.moduleId}/setup`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(params.businessId)),
  ])
  if (!setupRes.ok) {
    // Platform Core groups have no setup of their own.
    const core = await apiTry<{ data: ModuleDetail }>(`/v1/platform/modules/${params.moduleId}`, token)
    return (
      <div className="bos-page">
        <Link className="ws-backlink" href={`${base}/modules`}>← All tools</Link>
        {core.ok ? (
          <>
            <PageHeader title={core.data.data.display_name} subtitle={core.data.data.description ?? undefined} />
            <p className="bos-hint">Part of every business on LOCAH and always on.</p>
          </>
        ) : (
          <GateNotice error={setupRes.error} businessId={params.businessId} moduleLabel="This tool" />
        )}
      </div>
    )
  }
  const s = setupRes.data.data
  const perms = new Set(ctxRes.ok ? ctxRes.data.data.permissions : [])
  const canEnable = perms.has('modules.enable')
  const canTurnOff = perms.has('modules.deactivate')
  const done = s.steps.filter((x) => x.done).length
  const waitingOn = s.dependencies.filter((d) => d.holding_back)

  return (
    <div className="bos-page bos-setup">
      <Link className="ws-backlink" href={`${base}/modules`}>← All tools</Link>
      <PageHeader
        title={s.label}
        subtitle={s.does}
        actions={s.status === 'ready' && s.home ? <Link className="btn" href={`${base}${s.home}`}>Open {s.label}</Link> : undefined}
      />

      {searchParams.problem ? (
        <p className="bos-status bos-error" role="alert">{searchParams.problem}</p>
      ) : null}
      {searchParams.enabled && s.enabled && s.status !== 'ready' ? (
        <p className="bos-status" role="status">{s.label} is on. Here is what is left before customers can use it.</p>
      ) : null}

      <section className="bos-card bos-setup__status" aria-labelledby="status-h">
        <div className="bos-setup__state">
          <h2 id="status-h" className="sr-only">Status</h2>
          <span className={`bos-setup__chip ${TONE[s.status]}`}>{s.status_label}</span>
          {s.enabled && s.status !== 'ready' && s.remaining > 0 ? (
            <span className="bos-setup__remaining">
              {s.remaining} {s.remaining === 1 ? 'step' : 'steps'} remaining
            </span>
          ) : null}
        </div>
        {s.status === 'ready' ? (
          <p className="bos-hint">Working — customers can use it{s.website.length ? ` (${s.website.join(', ')})` : ''}.</p>
        ) : s.status === 'restricted' ? (
          <p className="bos-hint">Your records are kept. It works again once your plan includes it.</p>
        ) : s.status === 'deactivated' ? (
          <p className="bos-hint">Switched off: nothing new happens through it, and everything recorded is kept for when you turn it back on.</p>
        ) : null}
        {(s.tips ?? []).map((tip) => (
          <p key={tip.href} className="bos-tip">
            {tip.text} <Link href={`${base}${tip.href}`}>{tip.label} →</Link>
          </p>
        ))}

        {s.steps.length > 0 ? (
          <ol className="bos-setup__steps" aria-label={`${s.label} setup`}>
            {s.steps.map((step) => (
              <li key={step.key} className={step.done ? 'is-done' : ''}>
                <span className="bos-setup__mark" aria-hidden>{step.done ? '✓' : '○'}</span>
                <span className="bos-setup__label">
                  {step.label}
                  <span className="sr-only">{step.done ? ' — done' : ' — not done yet'}</span>
                </span>
                {!step.done && step.action && s.enabled ? (
                  <Link className="btn-quiet" href={`${base}${step.action.href}`}>{step.action.label} →</Link>
                ) : null}
              </li>
            ))}
          </ol>
        ) : s.enabled && s.status === 'ready' ? null : (
          <p className="bos-hint">Nothing to set up — it works as soon as it is on.</p>
        )}
        {s.steps.length > 0 ? (
          <p className="bos-setup__progress">{done} of {s.steps.length} done</p>
        ) : null}

        {waitingOn.length > 0 ? (
          <p className="bos-setup__waiting">
            Also waiting on{' '}
            {waitingOn.map((d, i) => (
              <span key={d.module}>
                {i > 0 ? ', ' : ''}
                <Link href={`${base}${d.href}`}>{d.label}</Link>
                {d.enabled ? ' (being set up)' : ' (off)'}
              </span>
            ))}
            .
          </p>
        ) : null}
      </section>

      <div className="bos-setup__grid">
        {s.customer_can.length > 0 ? (
          <section className="bos-card" aria-labelledby="customers-h">
            <h2 id="customers-h" className="bos-card__title">Customers can</h2>
            <ul>{s.customer_can.map((c) => <li key={c}>{c}</li>)}</ul>
            {s.website.length ? <p className="bos-hint">On your website: {s.website.join(', ')}.</p> : null}
          </section>
        ) : null}
        {s.staff_can.length > 0 ? (
          <section className="bos-card" aria-labelledby="team-h">
            <h2 id="team-h" className="bos-card__title">Your team can</h2>
            <ul>{s.staff_can.map((c) => <li key={c}>{c}</li>)}</ul>
          </section>
        ) : null}
        {s.dependencies.length > 0 ? (
          <section className="bos-card" aria-labelledby="needs-h">
            <h2 id="needs-h" className="bos-card__title">Works with</h2>
            <ul>
              {s.dependencies.map((d) => (
                <li key={d.module}>
                  <Link href={`${base}${d.href}`}>{d.label}</Link> — {d.ready ? 'ready' : d.enabled ? 'being set up' : 'off'}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>

      {s.status !== 'unavailable' ? (
        <section className="bos-setup__switch">
          {!s.enabled && canEnable && s.included ? (
            <SafeForm action={setModuleState}>
              <input type="hidden" name="businessId" value={params.businessId} />
              <input type="hidden" name="moduleId" value={params.moduleId} />
              <input type="hidden" name="action" value="enable" />
              <button type="submit" className="btn-primary">Turn on {s.label}</button>
            </SafeForm>
          ) : null}
          {s.enabled && canTurnOff ? (
            <SafeForm action={setModuleState}>
              <input type="hidden" name="businessId" value={params.businessId} />
              <input type="hidden" name="moduleId" value={params.moduleId} />
              <input type="hidden" name="action" value="deactivate" />
              <button type="submit" className="btn-quiet">Turn off</button>
              <p className="bos-hint">Turning it off hides it and stops new activity. Your records stay and come back if you turn it on again.</p>
            </SafeForm>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
