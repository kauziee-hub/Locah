'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { useWsWords } from '@/components/WsWords'
import { saveHours } from '../actions'

const DAYS: [string, string][] = [
  ['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'],
  ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday'],
]
type Span = [string, string]
type Week = Record<string, Span[]>

function fromSaved(hours: Record<string, unknown> | null): Week {
  const week: Week = {}
  for (const [key] of DAYS) {
    const spans = hours?.[key]
    week[key] = Array.isArray(spans)
      ? spans.filter((s): s is Span => Array.isArray(s) && s.length === 2 && s.every((t) => typeof t === 'string'))
      : []
  }
  return week
}

/** Weekly opening hours (Doc 09 CORE-009). Bookings and WhatsApp offer times
 *  from these; a closed day offers none. */
export function OpeningHours({
  businessId, locationId, hours, canEdit,
}: { businessId: string; locationId: string; hours: Record<string, unknown> | null; canEdit: boolean }) {
  const router = useRouter()
  const t = useWsWords()
  const [pending, start] = useTransition()
  const [week, setWeek] = useState<Week>(() => fromSaved(hours))
  const [note, setNote] = useState(typeof hours?.note === 'string' ? hours.note : '')
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  const legacy = hours && !DAYS.some(([k]) => k in hours) && Object.keys(hours).some((k) => k !== 'note')

  const set = (day: string, spans: Span[]) => setWeek((w) => ({ ...w, [day]: spans }))
  const edit = (day: string, i: number, j: 0 | 1, value: string) =>
    set(day, week[day].map((s, k) => (k === i ? ((j === 0 ? [value, s[1]] : [s[0], value]) as Span) : s)))
  const copyMonday = () => setWeek((w) => Object.fromEntries(DAYS.map(([k]) => [k, k === 'sun' ? w.sun : w.mon.map((s) => [...s] as Span)])))

  const save = () =>
    start(async () => {
      setMsg(null)
      const body: Record<string, unknown> = {}
      for (const [k] of DAYS) if (week[k].length) body[k] = week[k]
      if (note.trim()) body.note = note.trim()
      const r = await saveHours(businessId, locationId, body)
      setMsg(r.ok ? { text: t('Opening hours saved') } : { text: r.message ?? t('Check the times'), bad: true })
      if (r.ok) router.refresh()
    })

  return (
    <section className="bos-card bos-hours" style={{ marginTop: '2rem', maxWidth: '40rem' }} aria-labelledby="hours-h">
      <h2 id="hours-h">{t('Opening hours')}</h2>
      <p className="bos-hint">{t('Customers can book, and WhatsApp offers times, only while you are open.')}</p>
      {legacy ? <p className="bos-hint">{t('Hours saved earlier in another format are replaced when you save these.')}</p> : null}
      <div className="bos-hours__days">
        {DAYS.map(([key, day]) => {
          const label = t(day)
          const spans = week[key]
          const open = spans.length > 0
          return (
            <div key={key} className="bos-hours__day" data-day={key}>
              <label className="bos-toggle">
                <input type="checkbox" checked={open} disabled={!canEdit}
                  onChange={(e) => set(key, e.target.checked ? [['09:00', '18:00']] : [])} />
                <span className="bos-toggle__track" aria-hidden />
                <span className="bos-hours__name">{label}</span>
              </label>
              {open ? (
                <div className="bos-hours__spans">
                  {spans.map((s, i) => (
                    <span key={i} className="bos-hours__span">
                      <input type="time" aria-label={t('{day} opens', { day: label })} value={s[0]} disabled={!canEdit}
                        onChange={(e) => edit(key, i, 0, e.target.value)} />
                      <span aria-hidden>–</span>
                      <input type="time" aria-label={t('{day} closes', { day: label })} value={s[1]} disabled={!canEdit}
                        onChange={(e) => edit(key, i, 1, e.target.value)} />
                      {canEdit && spans.length > 1 ? (
                        <button type="button" className="btn-quiet" aria-label={t('Remove {day} {from} to {until}', { day: label, from: s[0], until: s[1] })}
                          onClick={() => set(key, spans.filter((_, k) => k !== i))}>{t('Remove')}</button>
                      ) : null}
                    </span>
                  ))}
                  {canEdit && spans.length < 3 ? (
                    <button type="button" className="btn-quiet"
                      onClick={() => set(key, [...spans, [spans[spans.length - 1][1] < '20:00' ? spans[spans.length - 1][1] : '16:00', '21:00']])}>
                      {t('Add a break')}
                    </button>
                  ) : null}
                </div>
              ) : (
                <span className="bos-hours__closed">{t('Closed')}</span>
              )}
            </div>
          )
        })}
      </div>
      <label className="bos-label" style={{ marginTop: '.8rem' }}>
        {t('Note for customers (optional)')}
        <input value={note} maxLength={200} disabled={!canEdit} onChange={(e) => setNote(e.target.value)}
          placeholder={t('Closed on festival days')} style={{ width: '100%' }} />
      </label>
      {canEdit ? (
        <div className="bos-inv-buttons">
          <button type="button" disabled={pending} onClick={save}>{t('Save opening hours')}</button>
          <button type="button" className="btn-ghost" disabled={pending || !week.mon.length} onClick={copyMonday}>
            {t('Copy Monday to Tuesday–Saturday')}
          </button>
        </div>
      ) : null}
      {msg ? <p className={`bos-status${msg.bad ? ' bos-error' : ''}`} role="status">{msg.text}</p> : null}
    </section>
  )
}
