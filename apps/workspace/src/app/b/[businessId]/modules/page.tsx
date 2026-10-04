import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { RecommendedTools, type ForYou } from '@/components/RecommendedTools'
import { setModuleState } from './actions'

export const dynamic = 'force-dynamic'

type Step = { key: string; label: string; done: boolean }
type Readiness = {
  state: string
  enabled: boolean
  built: boolean
  steps: Step[]
  configured: boolean
  ready: boolean
}
type Pick = {
  module: string
  tier: 'always' | 'core' | 'recommended' | 'optional'
  reason: string
  hints: string[]
  label: string
  built: boolean
  does: string
  customer_can: string[]
  staff_can: string[]
  readiness: Readiness | null
}
type Recommendations = {
  family_label: string | null
  modules: Pick[]
}
type CatalogueModule = { key: string; label: string; does: string; built: boolean; future: boolean }

const ALWAYS_LABEL: Record<string, string> = {
  'core-website': 'Website',
  'core-marketplace-presence': 'Marketplace listing',
}

/**
 * Modules & integrations (Business OS Guide §3; Founder §50).
 *
 * For each tool: what it does, why LOCAH recommends it, what customers get,
 * what the team gets, and the setup that remains. Switching a tool on is the
 * owner's choice; "on" is not "ready" until its setup is true in real data.
 * Tools LOCAH has not built are not shown at all.
 */
export default async function ModulesPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const [recRes, forYouRes, catRes, ctxRes] = await Promise.all([
    apiTry<{ data: Recommendations }>(`/v1/platform/businesses/${params.businessId}/module-recommendations`, token),
    apiTry<{ data: ForYou }>(`/v1/platform/businesses/${params.businessId}/module-recommendations/for-you`, token),
    apiTry<{ data: { modules: CatalogueModule[] } }>(`/v1/public/taxonomy`, token),
    apiTry<{ data: { features?: Record<string, boolean>; permissions: string[] } }>(
      '/v1/me/context', token, businessHeaders(params.businessId)),
  ])
  if (!recRes.ok) {
    return (
      <div>
        <PageHeader title="Tools" />
        <GateNotice error={recRes.error} businessId={params.businessId} moduleLabel="Modules" />
      </div>
    )
  }
  const rec = recRes.data.data
  // The AI Employee Sandbox is a demonstration, not a tool: it is offered here,
  // where an owner looks at what LOCAH can do, and on the AI staff card — never
  // as a navigation area of its own.
  const sandbox = ctxRes.ok && ctxRes.data.data.features?.ai_sandbox === true
    && ctxRes.data.data.permissions.includes('ai_employees.read')
  const forYou = forYouRes.ok ? forYouRes.data.data : null
  const canEnable = ctxRes.ok && ctxRes.data.data.permissions.includes('modules.enable')
  const built = rec.modules.filter((m) => m.built)
  // Only what is really there: a Storefront tool LOCAH has not built yet is not claimed.
  const always = rec.modules.filter((m) => m.tier === 'always' && m.built)
  const running = built.filter((m) => m.tier !== 'always' && m.readiness?.enabled)
  // Everything else for businesses like this one, minus what is already
  // recommended above with its own reason (or put off by the owner).
  const shown = new Set([...(forYou?.recommended ?? []).map((r) => r.module), ...(forYou?.put_off ?? []).map((r) => r.module)])
  const others = built.filter((m) => m.tier !== 'always' && !m.readiness?.enabled && !shown.has(m.module))
  const known = new Set(rec.modules.map((m) => m.module))
  const more = (catRes.ok ? catRes.data.data.modules : []).filter((m) => m.built && !m.future && !known.has(m.key))

  const base = `/b/${params.businessId}`
  return (
    <div className="bos-page bos-modules">
      <PageHeader
        title="Tools for your business"
        subtitle="Switch on what helps your business run. Each suggestion says why — and nothing turns on until you choose it."
        actions={<Link className="btn-quiet" href={`${base}/settings/business`}>How your business works</Link>}
      />
      {sandbox ? (
        <p className="bos-hint" style={{ maxWidth: 'none' }}>
          Curious how an AI employee would answer your customers?{' '}
          <Link href={`${base}/ai-employees/sandbox`}>Open the AI Employee Studio</Link> — it answers from your own
          menu, prices and free times, sends nothing, and keeps anything you approve in Test Mode as a test record.
        </p>
      ) : null}

      <section aria-labelledby="for-you-h" className="bos-section">
        <h2 id="for-you-h" className="bos-section__title">
          Recommended for your Business <span>{forYou?.recommended.length ?? 0}</span>
        </h2>
        <p className="bos-hint">From what you told LOCAH, what you have added and how you work.</p>
        {forYou ? (
          <RecommendedTools businessId={params.businessId} data={forYou} canEnable={canEnable} />
        ) : (
          <p className="bos-empty">Recommendations could not load just now.</p>
        )}
        {forYou && forYou.recommended.length === 0 && running.length === 0 ? (
          <p className="bos-empty">
            Tell LOCAH what you sell and how customers buy, and recommendations will follow.{' '}
            <Link href={`${base}/settings/business`}>How your business works</Link>
          </p>
        ) : null}
      </section>

      {running.length > 0 ? (
        <section aria-labelledby="running-h" className="bos-section">
          <h2 id="running-h" className="bos-section__title">Running <span>{running.length}</span></h2>
          <div className="bos-grid">
            {running.map((m) => <ToolCard key={m.module} m={m} businessId={params.businessId} sandbox={sandbox} />)}
          </div>
        </section>
      ) : null}

      {others.length > 0 ? (
        <details className="bos-section bos-more">
          <summary className="bos-section__title">Other tools for businesses like yours <span>{others.length}</span></summary>
          <div className="bos-grid">
            {others.map((m) => <ToolCard key={m.module} m={m} businessId={params.businessId} sandbox={sandbox} />)}
          </div>
        </details>
      ) : null}

      {more.length > 0 ? (
        <details className="bos-section bos-more">
          <summary className="bos-section__title">More tools <span>{more.length}</span></summary>
          <p className="bos-hint">Any business can use any tool. These are not usually needed for businesses like yours.</p>
          <ul className="bos-mini-list">
            {more.map((m) => (
              <li key={m.key}>
                <div>
                  <strong>{m.label}</strong>
                  <p>{m.does}</p>
                </div>
                <form action={setModuleState}>
                  <input type="hidden" name="businessId" value={params.businessId} />
                  <input type="hidden" name="moduleId" value={m.key} />
                  <input type="hidden" name="action" value="enable" />
                  <button type="submit" className="btn-quiet">Turn on</button>
                </form>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <section aria-labelledby="always-h" className="bos-section">
        <h2 id="always-h" className="bos-section__title">Always included</h2>
        <p className="bos-hint">Every business on LOCAH has these.</p>
        <div className="bos-pills">
          {always.map((m) => (
            <span key={m.module} className="bos-pill">{ALWAYS_LABEL[m.module] ?? m.label}</span>
          ))}
        </div>
      </section>
    </div>
  )
}

function ToolCard({ m, businessId, sandbox = false }: { m: Pick; businessId: string; sandbox?: boolean }) {
  const r = m.readiness
  const on = !!r?.enabled
  const todo = (r?.steps ?? []).filter((s) => !s.done)
  const status = !on ? null : r?.ready ? 'Ready — customers can use it' : `Setup: ${(r?.steps.length ?? 0) - todo.length} of ${r?.steps.length ?? 0} done`
  return (
    <article className={`bos-tool${on ? ' is-on' : ''}`} aria-labelledby={`t-${m.module}`}>
      <header className="bos-tool__head">
        <h3 id={`t-${m.module}`}>{m.label}</h3>
        {status ? <span className={`bos-state${r?.ready ? ' is-ready' : ''}`}>{status}</span> : null}
      </header>
      <p className="bos-tool__does">{m.does}</p>
      <p className="bos-tool__why"><span>Why</span>{m.reason}{m.hints?.length ? ` — set up for ${m.hints.join(', ')}` : ''}</p>
      {m.customer_can.length > 0 ? (
        <div className="bos-tool__cap"><span>Customers can</span><ul>{m.customer_can.map((c) => <li key={c}>{c}</li>)}</ul></div>
      ) : null}
      {m.staff_can.length > 0 ? (
        <div className="bos-tool__cap"><span>Your team can</span><ul>{m.staff_can.map((c) => <li key={c}>{c}</li>)}</ul></div>
      ) : null}
      {r && r.steps.length > 0 ? (
        <div className="bos-tool__setup">
          <span>{on ? 'Setup' : 'Setup after you turn it on'}</span>
          <ul>
            {r.steps.map((s) => (
              <li key={s.key} className={s.done ? 'is-done' : ''}>
                <span aria-hidden>{s.done ? '✓' : '○'}</span> {s.label}
                <span className="sr-only">{s.done ? ' (done)' : ' (not done yet)'}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {on && !r?.ready && todo.length > 0 ? (
        <p className="bos-tool__next"><span>Next</span>{todo[0].label}</p>
      ) : null}
      <footer className="bos-tool__foot">
        {sandbox && m.module === 'ai-employees' ? (
          <Link className="btn-quiet" href={`/b/${businessId}/ai-employees/sandbox`}>See it work (sandbox)</Link>
        ) : null}
        {on && !r?.ready ? (
          <Link className="btn-primary" href={`/b/${businessId}/modules/${m.module}`}>Continue setup</Link>
        ) : null}
        <form action={setModuleState}>
          <input type="hidden" name="businessId" value={businessId} />
          <input type="hidden" name="moduleId" value={m.module} />
          <input type="hidden" name="action" value={on ? 'deactivate' : 'enable'} />
          <button type="submit" className={on ? 'btn-quiet' : 'btn-primary'}>{on ? 'Turn off' : 'Turn on'}</button>
        </form>
      </footer>
    </article>
  )
}
