'use client'

import { useState, useTransition } from 'react'
import { approve, approveInTestMode, simulate, type Approval, type Proposal, type TestResult, type TraceStep, type Turn } from './sandbox-actions'

type Scenario = { key: string; label: string; channel: string; about: string }
type Entry =
  | { who: 'customer'; text: string }
  | { who: 'ai'; turn: Turn; approval?: Approval; test?: TestResult }
  | { who: 'error'; text: string }

const STEP_WORDS: Record<string, string> = {
  receive: 'Message in',
  understand: 'Understood',
  guardrail: 'Guardrail',
  module_check: 'Module check',
  read: 'Data read',
  permission: 'Permission check',
  note: 'Note',
  propose: 'Proposed action',
  approval: 'Approval',
  recheck: 'Live re-check',
  simulate: 'Simulated action',
  sandbox: 'Sandbox',
  test_record: 'Test Mode',
}

function Trace({ steps }: { steps: TraceStep[] }) {
  return (
    <ol className="bos-sandbox__trace">
      {steps.map((s, i) => (
        <li key={i} className={`is-${s.kind}${s.ok === false || s.decision === 'refused' ? ' is-no' : ''}`}>
          <span className="bos-sandbox__step">{STEP_WORDS[s.kind] ?? s.kind}</span>
          <strong>{s.label}</strong>
          {s.detail ? <span>{s.detail}</span> : null}
          {s.contract ? <small>Through: {s.contract}</small> : null}
          {s.tier ? <small>Tool tier {s.tier}</small> : null}
        </li>
      ))}
    </ol>
  )
}

/**
 * The sandbox conversation: the owner types as a customer, the AI employee
 * answers from the business's real records, and every step it took is listed.
 * Proposals are approved here only — the API re-checks them and writes nothing.
 */
export function SandboxConsole({ businessId, scenarios, suggestions, notice, canTest }: {
  businessId: string
  scenarios: Scenario[]
  suggestions: Record<string, string[]>
  notice: string
  /** May approve in Test Mode (ai_employees.manage). */
  canTest: boolean
}) {
  const [scenario, setScenario] = useState(scenarios[0]?.key ?? 'whatsapp_manager')
  const [logs, setLogs] = useState<Record<string, Entry[]>>({})
  const [draft, setDraft] = useState('')
  const [pending, start] = useTransition()
  const entries = logs[scenario] ?? []
  const current = scenarios.find((s) => s.key === scenario)
  const push = (entry: Entry) => setLogs((all) => ({ ...all, [scenario]: [...(all[scenario] ?? []), entry] }))

  const send = (text: string) => {
    const said = text.split(/\s+/).join(' ').trim()
    if (!said || pending) return
    setDraft('')
    push({ who: 'customer', text: said })
    start(async () => {
      const r = await simulate(businessId, scenario, said)
      push(r.ok && r.data ? { who: 'ai', turn: r.data } : { who: 'error', text: r.ok ? 'No answer.' : r.message })
    })
  }

  const approveAt = (index: number, proposal: Proposal) => {
    start(async () => {
      const r = await approve(businessId, proposal)
      setLogs((all) => {
        const list = [...(all[scenario] ?? [])]
        const entry = list[index]
        if (entry?.who === 'ai') {
          list[index] = r.ok && r.data
            ? { ...entry, approval: r.data }
            : { ...entry, approval: { ok: false, reference: null, result: r.ok ? 'No answer.' : r.message,
                                      trace: [], simulated: true, notice } }
        }
        return { ...all, [scenario]: list }
      })
    })
  }

  const testAt = (index: number, proposal: Proposal) => {
    start(async () => {
      const r = await approveInTestMode(businessId, scenario, proposal)
      setLogs((all) => {
        const list = [...(all[scenario] ?? [])]
        const entry = list[index]
        if (entry?.who === 'ai') {
          list[index] = { ...entry, test: r.ok && r.data ? r.data : {
            ok: false, reference: null, result: r.ok ? 'No answer.' : r.message, trace: [], notice, record: null } }
        }
        return { ...all, [scenario]: list }
      })
    })
  }

  return (
    <div className="bos-sandbox">
      <div className="bos-sandbox__tabs" role="tablist" aria-label="AI employee">
        {scenarios.map((s) => (
          <button key={s.key} type="button" role="tab" aria-selected={s.key === scenario}
                  className={s.key === scenario ? 'btn btn-primary' : 'btn btn-ghost'}
                  onClick={() => setScenario(s.key)}>
            {s.label}
          </button>
        ))}
      </div>
      {current ? <p className="bos-hint">{current.about} <span className="bos-tag">{current.channel}</span></p> : null}

      <section className="bos-sandbox__chat" aria-label={`${current?.label ?? 'AI'} conversation`} aria-live="polite">
        {entries.length === 0 ? (
          <p className="bos-sandbox__empty">Type what a customer might say, or pick one of the examples below.</p>
        ) : null}
        {entries.map((e, i) =>
          e.who === 'customer' ? (
            <div key={i} className="bos-bubble bos-bubble--in">
              <span className="bos-bubble__tag">Customer</span>
              <p>{e.text}</p>
            </div>
          ) : e.who === 'error' ? (
            <div key={i} className="bos-bubble bos-bubble--out is-bad"><p>{e.text}</p></div>
          ) : (
            <div key={i} className="bos-sandbox__turn">
              <div className="bos-bubble bos-bubble--out">
                <span className="bos-bubble__tag">{current?.label ?? 'AI'} · simulated</span>
                <p>{e.turn.reply}</p>
                <span className="bos-bubble__meta">No external message sent</span>
              </div>
              <details className="bos-sandbox__details" open={i === entries.length - 1}>
                <summary>What the AI did ({e.turn.trace.length} steps)</summary>
                <Trace steps={e.turn.trace} />
              </details>
              {e.turn.proposal ? (
                <div className="bos-sandbox__proposal">
                  <div>
                    <span className="bos-bubble__tag">Needs your approval</span>
                    <strong>{e.turn.proposal.summary}</strong>
                  </div>
                  {e.test ? (
                    <div className={e.test.ok ? 'bos-sandbox__result is-ok' : 'bos-sandbox__result is-no'}>
                      <strong>{e.test.ok ? 'Saved in Test Mode' : 'Not completed'}</strong>
                      <span>{e.test.result}</span>
                      {e.test.ok ? <span className="bos-hint">It is in Test records below — not in your real orders, bookings or enquiries.</span> : null}
                      {e.test.trace.length ? <Trace steps={e.test.trace} /> : null}
                    </div>
                  ) : e.approval ? (
                    <div className={e.approval.ok ? 'bos-sandbox__result is-ok' : 'bos-sandbox__result is-no'}>
                      <strong>{e.approval.ok ? 'Approved in the sandbox' : 'Not completed'}</strong>
                      <span>{e.approval.result}</span>
                      {e.approval.trace.length ? <Trace steps={e.approval.trace} /> : null}
                    </div>
                  ) : (
                    <div className="bos-sandbox__choices">
                      {canTest ? (
                        <button type="button" className="btn btn-primary" disabled={pending}
                                onClick={() => testAt(i, e.turn.proposal as Proposal)}>
                          Approve in Test Mode
                        </button>
                      ) : null}
                      <button type="button" className={canTest ? 'btn btn-ghost' : 'btn btn-primary'} disabled={pending}
                              onClick={() => approveAt(i, e.turn.proposal as Proposal)}>
                        Just check it (nothing saved)
                      </button>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          ),
        )}
        {pending ? <p className="bos-sandbox__empty">Working…</p> : null}
      </section>

      {(suggestions[scenario] ?? []).length ? (
        <div className="bos-sandbox__examples" aria-label="Example messages">
          {(suggestions[scenario] ?? []).map((s) => (
            <button key={s} type="button" className="btn btn-ghost" disabled={pending} onClick={() => send(s)}>{s}</button>
          ))}
        </div>
      ) : null}

      <form className="bos-sandbox__compose" onSubmit={(ev) => { ev.preventDefault(); send(draft) }}>
        <label className="bos-label" htmlFor="sandbox-said">Customer says</label>
        <div>
          <input id="sandbox-said" value={draft} maxLength={500} autoComplete="off"
                 placeholder="e.g. Saturday evening slot iruka?" onChange={(ev) => setDraft(ev.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={pending || !draft.trim()}>Send</button>
        </div>
      </form>
      <p className="bos-hint" style={{ marginTop: '.6rem' }}>{notice}</p>
    </div>
  )
}
