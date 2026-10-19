'use client'

import { useState, useTransition } from 'react'
import {
  cancelFreeze,
  cancelMembership,
  changeDeliveryDay,
  changeDeliveryFuture,
  freeze,
  renew,
  resume,
  recordSession,
} from '../member-actions'

export type Detail = {
  /** The business's calendar day (its own time zone), from the server. */
  today: string
  id: string
  plan: { id: string; name: string; kind: string; price_amount: number; duration_days: number | null; grace_days: number; freeze_allowed: boolean; max_freeze_days: number | null; billing_timing: string }
  words: Record<string, string>
  member: { id: string; name: string | null; phone: string | null }
  status: string
  status_words: string
  reason: string
  valid_until: string | null
  /** The last day covered (YYYY-MM-DD, the business's own days). */
  last_day?: string | null
  grace_until: string | null
  days_remaining: number | null
  expiring_soon: boolean
  next_due_on: string | null
  sessions_remaining: number | null
  charged: number
  paid: number
  outstanding: number
  overdue: boolean
  good_standing: boolean | null
  checkin_code: string | null
  delivery: { quantity?: string; days?: number[]; slot?: string; cutoff?: string } | null
  periods: { id: string; seq: number; starts_at: string; ends_at: string; base_ends_at: string; extended_days: number; amount: number; paid_amount: number; payment_state: string; sessions_included: number | null; source: string }[]
  freezes: { id: string; kind: string; starts_on: string; ends_on: string; days: number; status: string; reason: string | null; extends_cover: boolean }[]
  instalments: { id: string; seq: number; label: string; amount: number; paid_amount: number; due_on: string; status: string }[]
  visits: { id: string; seq: number; due_on: string; status: string; job_ref: string | null }[]
  session_uses: { id: string; used_at: string; source_type: string; status: string }[]
  history: { from: string | null; to: string; reason: string | null; at: string | null }[]
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
/** A calendar day plus whole days: date arithmetic only, no clock and no time zone. */
const addDays = (day: string, n: number) => {
  const t = new Date(`${day}T00:00:00Z`)
  t.setUTCDate(t.getUTCDate() + n)
  return t.toISOString().slice(0, 10)
}

/** The few things the desk does with one relationship; the server decides every rule. */
export function MemberActions({ businessId, detail: d }: { businessId: string; detail: Detail }) {
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [open, setOpen] = useState<'none' | 'freeze' | 'cancel' | 'future'>('none')
  const kind = d.plan.kind
  const today = d.today
  const tomorrow = addDays(d.today, 1)
  const running = !['cancelled', 'completed'].includes(d.status)
  const renews = ['access', 'session_pack', 'service_contract', 'member_dues'].includes(kind) || (kind === 'recurring_delivery' && d.plan.billing_timing === 'prepaid')
  const scheduled = d.freezes.filter((f) => f.status === 'confirmed' && f.starts_on > today)

  function run(fn: () => Promise<{ ok: boolean; message?: string }>, after: string) {
    setError(null)
    setDone(null)
    start(async () => {
      const r = await fn()
      if (!r.ok) setError(r.message || 'That did not save.')
      else {
        setDone(after)
        setOpen('none')
      }
    })
  }

  return (
    <div className="bos-member-actions">
      {running ? (
        <div className="bos-money__row">
          {renews ? (
            <button type="button" disabled={pending} onClick={() => run(() => renew(businessId, d.id), 'Renewal added — collect it in Payments below.')}>
              {d.words.renew}
            </button>
          ) : null}
          {(d.plan.freeze_allowed || kind === 'recurring_delivery') && d.status !== 'paused' ? (
            <button type="button" className="btn-ghost" onClick={() => setOpen(open === 'freeze' ? 'none' : 'freeze')}>
              {kind === 'recurring_delivery' ? 'Pause deliveries' : 'Freeze'}
            </button>
          ) : null}
          {d.status === 'paused' ? (
            <button type="button" className="btn-ghost" disabled={pending} onClick={() => run(() => resume(businessId, d.id), 'Resumed.')}>
              Resume now
            </button>
          ) : null}
          {kind === 'session_pack' && d.sessions_remaining ? (
            <button type="button" className="btn-ghost" disabled={pending}
              onClick={() => run(() => recordSession(businessId, d.id, crypto.randomUUID()), 'One session recorded.')}>
              Record a session
            </button>
          ) : null}
          <button type="button" className="btn-ghost" onClick={() => setOpen(open === 'cancel' ? 'none' : 'cancel')}>
            Cancel
          </button>
        </div>
      ) : (
        <p className="bos-hint">This {d.words.noun} has ended.</p>
      )}

      {open === 'freeze' ? (
        <form
          className="bos-money__form"
          onSubmit={(e) => {
            e.preventDefault()
            const f = new FormData(e.currentTarget)
            run(() => freeze(businessId, d.id, { starts_on: String(f.get('starts_on')), days: Number(f.get('days')), reason: String(f.get('reason') || '') || undefined }),
              kind === 'recurring_delivery' ? 'Paused — no deliveries on those days.' : 'Frozen — the end date moved by those days.')
          }}
        >
          <label>
            <span>From</span>
            <input name="starts_on" type="date" required defaultValue={kind === 'recurring_delivery' ? tomorrow : today} />
          </label>
          <label>
            <span>Days</span>
            <input name="days" type="number" min="1" max={d.plan.max_freeze_days || 366} required defaultValue={kind === 'recurring_delivery' ? 3 : 7} />
          </label>
          <label className="bos-money__wide">
            <span>Reason (optional)</span>
            <input name="reason" maxLength={200} />
          </label>
          <button type="submit" disabled={pending}>
            {kind === 'recurring_delivery' ? 'Pause' : 'Freeze'}
          </button>
        </form>
      ) : null}

      {open === 'cancel' ? (
        <form
          className="bos-money__form"
          onSubmit={(e) => {
            e.preventDefault()
            const reason = String(new FormData(e.currentTarget).get('reason') || '')
            run(() => cancelMembership(businessId, d.id, reason), 'Cancelled. Unpaid charges are no longer owed.')
          }}
        >
          <label className="bos-money__wide">
            <span>Why is it being cancelled?</span>
            <input name="reason" required maxLength={200} />
          </label>
          <button type="submit" className="btn-danger" disabled={pending}>
            Cancel {d.words.noun}
          </button>
        </form>
      ) : null}

      {scheduled.length ? (
        <ul className="bos-mini-list">
          {scheduled.map((f) => (
            <li key={f.id}>
              <div>
                <strong>
                  {f.kind === 'pause' ? 'Pause' : 'Freeze'} from {f.starts_on} · {f.days} days
                </strong>
                <p>Not started yet</p>
              </div>
              <button type="button" className="btn-ghost" disabled={pending} onClick={() => run(() => cancelFreeze(businessId, d.id, f.id), 'Taken back.')}>
                Take back
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {kind === 'recurring_delivery' && running && d.delivery ? (
        <div className="bos-mem__delivery">
          <p className="bos-hint">
            Usually {d.delivery.quantity} {d.delivery.slot ? `· ${d.delivery.slot}` : ''} on {(d.delivery.days || []).map((i) => DAYS[i]).join(', ')} · changes close at {d.delivery.cutoff} the day before.
          </p>
          <form
            className="bos-money__form"
            onSubmit={(e) => {
              e.preventDefault()
              const f = new FormData(e.currentTarget)
              const choice = String(f.get('kind'))
              run(() => changeDeliveryDay(businessId, d.id, { on_date: String(f.get('on_date')), kind: choice, quantity: choice === 'quantity' ? Number(f.get('quantity')) : undefined }),
                choice === 'skip' ? 'Skipped for that day.' : choice === 'restore' ? 'Back to the usual.' : 'Changed for that day only.')
            }}
          >
            <label>
              <span>Day</span>
              <input name="on_date" type="date" required defaultValue={tomorrow} />
            </label>
            <label>
              <span>Change</span>
              <select name="kind" defaultValue="skip">
                <option value="skip">Skip that day</option>
                <option value="quantity">Different quantity that day</option>
                <option value="restore">Back to the usual</option>
              </select>
            </label>
            <label>
              <span>Quantity that day</span>
              <input name="quantity" type="number" min="1" max="1000" defaultValue={Number(d.delivery.quantity || 1) + 1} />
            </label>
            <button type="submit" disabled={pending}>
              Save for that day
            </button>
          </form>
          <button type="button" className="btn-ghost" onClick={() => setOpen(open === 'future' ? 'none' : 'future')}>
            Change future deliveries
          </button>
          {open === 'future' ? (
            <form
              className="bos-money__form"
              onSubmit={(e) => {
                e.preventDefault()
                const f = new FormData(e.currentTarget)
                run(() => changeDeliveryFuture(businessId, d.id, { quantity: Number(f.get('quantity')) }), 'Future deliveries changed.')
              }}
            >
              <label>
                <span>Usual quantity from now on</span>
                <input name="quantity" type="number" min="1" max="1000" defaultValue={Number(d.delivery.quantity || 1)} />
              </label>
              <button type="submit" disabled={pending}>
                Change from now on
              </button>
            </form>
          ) : null}
        </div>
      ) : null}

      <p className={`bos-status ${error ? 'bos-error' : ''}`} role="status">
        {error || done || ''}
      </p>
    </div>
  )
}
