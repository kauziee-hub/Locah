import Link from 'next/link'
import {
  bringBackRecommendation,
  enableRecommended,
  putOffRecommendation,
} from '@/app/b/[businessId]/modules/actions'

export type Evidence = { key: string; kind: 'said' | 'records' | 'trait' | 'profile'; text: string }
export type Source = 'said' | 'records' | 'trait' | 'fit' | 'profile'
export type Recommended = {
  module: string
  label: string
  reason: string
  source: Source
  evidence: Evidence[]
  resurfaced: boolean
  value: string
  customer_can: string[]
  staff_can: string[]
  unlocks: string[]
  setup: { steps: string[]; effort: 'none' | 'quick' | 'a few steps' }
  dependencies: { module: string; label: string; ready: boolean; enabled: boolean }[]
  included: boolean
  state: string
}
export type ForYou = { recommended: Recommended[]; put_off: { module: string; label: string }[]; total: number }

const SOURCE: Record<Source, string> = {
  said: 'You told LOCAH',
  records: 'From your records',
  trait: 'How you work',
  fit: 'How you work',
  profile: 'Businesses like yours',
}
/** The best few are shown; the rest wait behind "More suggestions". */
const FIRST = 6
const EFFORT: Record<Recommended['setup']['effort'], string> = {
  none: 'Nothing to set up',
  quick: 'One quick step',
  'a few steps': 'A few steps',
}

/**
 * "Recommended for your Business": each suggestion says why (and where that
 * reason came from), what it is worth, what it adds for customers, the setup
 * it needs and the tools it depends on. Recommends only — nothing turns on
 * until the owner presses Enable, and "Not now" keeps it out of the way until
 * a new reason appears. Server-rendered; the buttons are server actions.
 */
export function RecommendedTools({
  businessId,
  data,
  canEnable,
  compact = false,
}: {
  businessId: string
  data: ForYou
  canEnable: boolean
  /** Home: the first two, without the put-off list. */
  compact?: boolean
}) {
  const items = compact ? data.recommended.slice(0, 2) : data.recommended.slice(0, FIRST)
  const later = compact ? [] : data.recommended.slice(FIRST)
  if (items.length === 0 && (compact || data.put_off.length === 0)) return null
  return (
    <div className="bos-recs">
      {items.length > 0 ? (
        <ul className={`bos-recs__list${compact ? ' is-compact' : ''}`}>
          {items.map((r) => (
            <li key={r.module} className="bos-rec">
              <RecommendedCard r={r} businessId={businessId} canEnable={canEnable} compact={compact} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="bos-empty">Nothing new to recommend right now.</p>
      )}
      {later.length > 0 ? (
        <details className="bos-recs__off">
          <summary>More suggestions <span>{later.length}</span></summary>
          <ul className="bos-recs__list">
            {later.map((r) => (
              <li key={r.module} className="bos-rec">
                <RecommendedCard r={r} businessId={businessId} canEnable={canEnable} compact={false} />
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {!compact && data.put_off.length > 0 ? (
        <details className="bos-recs__off">
          <summary>Put off for now <span>{data.put_off.length}</span></summary>
          <p className="bos-hint">These come back by themselves when LOCAH sees a new reason for them.</p>
          <ul className="bos-mini-list">
            {data.put_off.map((m) => (
              <li key={m.module}>
                <strong>{m.label}</strong>
                {canEnable ? (
                  <form action={bringBackRecommendation}>
                    <input type="hidden" name="businessId" value={businessId} />
                    <input type="hidden" name="moduleId" value={m.module} />
                    <button type="submit" className="btn-quiet">Bring back</button>
                  </form>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}

function RecommendedCard({
  r,
  businessId,
  canEnable,
  compact,
}: {
  r: Recommended
  businessId: string
  canEnable: boolean
  compact: boolean
}) {
  const source = r.source ?? r.evidence[0]?.kind ?? 'profile'
  const missing = r.dependencies.filter((d) => !d.enabled)
  const enableLabel = missing.length ? `Turn on ${r.label} + ${missing.map((d) => d.label).join(' + ')}` : `Turn on ${r.label}`
  return (
    <article aria-labelledby={`rec-${r.module}`}>
      <header className="bos-rec__head">
        <h3 id={`rec-${r.module}`}>{r.label}</h3>
        {r.resurfaced ? <span className="bos-rec__tag">New reason</span> : null}
        {!r.included ? <span className="bos-rec__tag is-plan">Plan upgrade</span> : null}
      </header>
      <p className="bos-rec__why">
        <span className={`bos-rec__source is-${source}`}>{SOURCE[source]}</span>
        {r.reason}
      </p>
      {!compact ? <p className="bos-rec__value">{r.value}</p> : null}
      {!compact && (r.unlocks.length > 0 || r.staff_can.length > 0) ? (
        <dl className="bos-rec__facts">
          {r.unlocks.length > 0 ? (
            <div>
              <dt>Adds</dt>
              <dd>{r.unlocks.slice(0, 3).join(' · ')}</dd>
            </div>
          ) : null}
          {r.staff_can.length > 0 ? (
            <div>
              <dt>Your team can</dt>
              <dd>{r.staff_can.slice(0, 2).join(' · ')}</dd>
            </div>
          ) : null}
          <div>
            <dt>Setup</dt>
            <dd>
              {EFFORT[r.setup.effort]}
              {r.setup.steps.length ? ` — ${r.setup.steps.join('; ')}` : ''}
            </dd>
          </div>
          {r.dependencies.length > 0 ? (
            <div>
              <dt>Needs</dt>
              <dd>
                {r.dependencies.map((d) => `${d.label}${d.ready ? ' (ready)' : d.enabled ? ' (being set up)' : ' (off)'}`).join(', ')}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      <footer className="bos-rec__foot">
        {canEnable && r.included ? (
          <form action={enableRecommended}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="moduleId" value={r.module} />
            <input type="hidden" name="also" value={missing.map((d) => d.module).join(',')} />
            <button type="submit" className="btn-primary">{enableLabel}</button>
          </form>
        ) : null}
        <Link className="btn-quiet" href={`/b/${businessId}/modules/${r.module}`}>Learn more</Link>
        {canEnable ? (
          <form action={putOffRecommendation}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="moduleId" value={r.module} />
            <button type="submit" className="btn-quiet">Not now</button>
          </form>
        ) : null}
      </footer>
    </article>
  )
}
