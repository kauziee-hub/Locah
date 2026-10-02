'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { registerNumber, sendTestMessage, setCalling } from './whatsapp-actions'
import type { CallRow, Connection } from './types'

// Owner words for each state; the state names themselves are the contract.
const STATE_WORDS: Record<string, string> = {
  ACTIVATION_REQUIRED: 'Not available yet',
  META_REVIEW_REQUIRED: 'Waiting for Meta to approve LOCAH',
  NOT_CONNECTED: 'Not connected',
  SETUP_REQUIRED: 'Connection not finished',
  PHONE_VERIFICATION_REQUIRED: 'Number needs registering',
  TEMPLATE_SETUP_REQUIRED: 'Waiting for message templates',
  ACTIVE: 'Working',
  DEGRADED: 'Working with problems',
  DISCONNECTED: 'Disconnected',
  CALLING_NOT_AVAILABLE: 'Not available',
  CALLING_ACTIVATION_REQUIRED: 'Not switched on for LOCAH yet',
  CALLING_ELIGIBLE: 'Can be switched on',
  CALLING_SETUP_REQUIRED: 'Being set up',
  CALLING_ACTIVE: 'On',
  CALLING_DEGRADED: 'On, with problems',
}
const CALL_STATE: Record<string, string> = {
  ringing: 'Ringing', missed: 'Missed', ended: 'Answered', failed: 'Failed', rejected: 'Declined',
  connected: 'In progress', accepted: 'Answering',
}

function ago(iso: string | null): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

export function ConnectionPanel({ businessId, connection, calls, canConfigure }: {
  businessId: string; connection: Connection; calls: CallRow[]; canConfigure: boolean
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [pin, setPin] = useState('')
  const [to, setTo] = useState('')
  const [msg, setMsg] = useState<{ where: string; text: string; bad?: boolean } | null>(null)
  const m = connection.messaging
  const c = connection.calling
  const run = (where: string, fn: () => Promise<{ ok: boolean; message?: string }>, ok: string) =>
    start(async () => {
      setMsg(null)
      const r = await fn()
      setMsg({ where, text: r.ok ? ok : r.message ?? 'That did not work', bad: !r.ok })
      if (r.ok) router.refresh()
    })
  const status = (where: string) => (msg?.where === where ? <p className={`bos-status${msg.bad ? ' bos-error' : ''}`} role="status">{msg.text}</p> : null)
  const canSend = ['ACTIVE', 'DEGRADED', 'TEMPLATE_SETUP_REQUIRED'].includes(m.state)

  return (
    <div className="bos-works">
      <section className="bos-card" aria-labelledby="conn-h">
        <h2 id="conn-h">Connection</h2>
        <div className="bos-wa-number">
          <strong>{STATE_WORDS[m.state] || m.state}</strong>
          <span className="bos-tag">{m.state}</span>
          {m.label ? <span className="bos-tag bos-tag--warn">{m.label}</span> : null}
        </div>
        {m.reason ? <p className="bos-hint">{m.reason}</p> : null}
        <ul className="bos-checklist">
          {m.steps.map((s) => (
            <li key={s.key}>{s.done ? '✓' : '○'} {s.label}</li>
          ))}
        </ul>
        <p className="bos-hint">
          Templates: {connection.templates.approved} approved · {connection.templates.awaiting_review} waiting for WhatsApp
          {connection.templates.rejected ? ` · ${connection.templates.rejected} rejected` : ''} · last message from WhatsApp: {ago(connection.last_webhook_at)}
        </p>

        {m.state === 'PHONE_VERIFICATION_REQUIRED' && canConfigure ? (
          <form className="bos-inv-form" onSubmit={(e) => { e.preventDefault(); run('register', () => registerNumber(businessId, pin), 'Number registered') }}>
            <label>
              Two-step verification PIN (6 digits)
              <input inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={pin} autoComplete="off"
                onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} required />
            </label>
            <p className="bos-hint">Sent to WhatsApp to register your number. LOCAH does not keep it.</p>
            <button type="submit" disabled={pending || pin.length !== 6}>Register number</button>
            {status('register')}
          </form>
        ) : null}

        {canSend && canConfigure ? (
          <form className="bos-inv-form" onSubmit={(e) => { e.preventDefault(); run('test', () => sendTestMessage(businessId, to), 'Test message sent') }}>
            <label>
              Send a test message to
              <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="+91 98765 43210" required />
            </label>
            <button type="submit" disabled={pending}>Send test</button>
            {status('test')}
          </form>
        ) : null}
      </section>

      <section className="bos-card" aria-labelledby="call-h">
        <h2 id="call-h">Calls</h2>
        <p><strong>WhatsApp calls:</strong> {STATE_WORDS[c.state] || c.state} <span className="bos-tag">{c.state}</span></p>
        {c.reason ? <p className="bos-hint">{c.reason}</p> : null}
        {canConfigure && (c.state === 'CALLING_ELIGIBLE' || c.state === 'CALLING_ACTIVE' || c.state === 'CALLING_DEGRADED') ? (
          <div className="bos-inv-buttons">
            <button type="button" disabled={pending}
              onClick={() => run('calling', () => setCalling(businessId, c.state === 'CALLING_ELIGIBLE'),
                c.state === 'CALLING_ELIGIBLE' ? 'Calling switched on' : 'Calling switched off')}>
              {c.state === 'CALLING_ELIGIBLE' ? 'Switch on WhatsApp calls' : 'Switch off WhatsApp calls'}
            </button>
            {status('calling')}
          </div>
        ) : null}
        <p><strong>Phone line:</strong> {connection.telephony.state === 'ACTIVATION_REQUIRED' ? 'Not connected' : connection.telephony.state} <span className="bos-tag">{connection.telephony.state}</span></p>
        {connection.telephony.reason ? <p className="bos-hint">{connection.telephony.reason}</p> : null}
        <p className="bos-hint">LOCAH never calls a customer who has not allowed it on WhatsApp.</p>
        {calls.length ? (
          <ul>
            {calls.map((call) => (
              <li key={call.id}>
                {ago(call.started_at)} · {call.direction === 'inbound' ? `from +${(call.from_number || '').replace(/^\+/, '')}` : 'outgoing'} · {CALL_STATE[call.state] || call.state}
                {call.within_business_hours === false ? ' · after hours' : ''}
                {call.duration_seconds ? ` · ${call.duration_seconds}s` : ''}
                {call.note ? <span className="bos-hint" style={{ display: 'block' }}>{call.note}</span> : null}
              </li>
            ))}
          </ul>
        ) : <p className="bos-hint">No calls yet.</p>}
      </section>
    </div>
  )
}
