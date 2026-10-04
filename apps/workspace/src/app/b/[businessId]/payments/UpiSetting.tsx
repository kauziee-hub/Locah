'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { saveUpi } from './actions'

/** Where payment-link money goes: the business's own UPI ID. */
export function UpiSetting({
  businessId,
  vpa,
  payee,
  canEdit,
}: {
  businessId: string
  vpa: string | null
  payee: string | null
  canEdit: boolean
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [editing, setEditing] = useState(!vpa && canEdit)
  const [id, setId] = useState(vpa ?? '')
  const [name, setName] = useState(payee ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  return (
    <section className={`bos-card${vpa ? '' : ' bos-pay__needs'}`} aria-labelledby="pay-upi">
      <h2 id="pay-upi">Your UPI ID</h2>
      <p className="bos-hint">
        Customers pay your payment links to this UPI ID, straight into your account. Your counter uses the same one.
      </p>
      {!editing ? (
        <div className="bos-pay__confirm">
          {vpa ? <p><strong>{vpa}</strong>{payee ? ` · shown as ${payee}` : ''}</p> : <p>Not set yet — payment links can&apos;t take UPI until it is.</p>}
          {canEdit ? <button type="button" className="btn-ghost" onClick={() => { setSaved(false); setEditing(true) }}>{vpa ? 'Change' : 'Add your UPI ID'}</button> : null}
          {saved ? <span className="bos-status" role="status">Saved.</span> : null}
        </div>
      ) : (
        <form className="bos-pay__form" onSubmit={(e) => {
          e.preventDefault()
          setError(null)
          start(async () => {
            const r = await saveUpi(businessId, { upi_vpa: id.trim() || null, upi_payee_name: name.trim() || null })
            if (!r.ok) {
              setError(r.message)
              return
            }
            setEditing(false)
            setSaved(true)
            router.refresh()
          })
        }}>
          <label className="bos-label" htmlFor="upi-id">UPI ID</label>
          <input id="upi-id" placeholder="yourname@okaxis" value={id} autoComplete="off" spellCheck={false}
                 onChange={(e) => setId(e.target.value)} />
          <label className="bos-label" htmlFor="upi-name">Name customers see (optional)</label>
          <input id="upi-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          <div className="bos-pay__confirm">
            <button type="submit" disabled={pending || !id.trim()}>{pending ? 'Saving…' : 'Save UPI ID'}</button>
            {vpa ? <button type="button" className="btn-ghost" disabled={pending} onClick={() => setEditing(false)}>Cancel</button> : null}
          </div>
          {error ? <p className="bos-error" role="alert">{error}</p> : null}
        </form>
      )}
    </section>
  )
}
