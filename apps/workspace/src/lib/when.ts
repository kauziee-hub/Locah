/**
 * Dates and times as an Indian business reads them — always in India time.
 *
 * Pages render on the server, and a server's clock is usually UTC: a booking at
 * 10:30 am would read "5:00 am" if formatted without a time zone. Every date the
 * Workspace shows goes through here (or passes `timeZone: IST` itself).
 */
export const IST = 'Asia/Kolkata'

type When = string | number | Date | null | undefined

function at(value: When): Date | null {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/** "4 Oct 2026" */
export function dayLabel(value: When, locale = 'en-IN'): string {
  const d = at(value)
  return d ? d.toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric', timeZone: IST }) : '—'
}

/** "4 Oct 2026, 7:30 pm" */
export function dayTimeLabel(value: When, locale = 'en-IN'): string {
  const d = at(value)
  return d
    ? d.toLocaleString(locale, {
        day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: IST,
      })
    : '—'
}

/** "7:30 pm" */
export function timeLabel(value: When, locale = 'en-IN'): string {
  const d = at(value)
  return d ? d.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit', timeZone: IST }) : '—'
}

/** "₹1,200" or "₹99.50" */
export function rupees(value: number | string | null | undefined): string {
  const n = Number(value ?? 0)
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: Number.isInteger(n) ? 0 : 2,
  }).format(n)
}

/** "09:00" or "17:30:00" (a time of day, no date) -> "9 am", "5:30 pm", "noon", "midnight". */
export function clockLabel(hhmm: string | null | undefined): string {
  if (!hhmm) return '—'
  const [h, m] = hhmm.split(':').map((x) => Number(x))
  if (Number.isNaN(h)) return hhmm
  if ((h === 0 && !m) || (h === 23 && m === 59)) return 'midnight'
  if (h === 12 && !m) return 'noon'
  return `${h % 12 || 12}${m ? `:${String(m).padStart(2, '0')}` : ''} ${h < 12 ? 'am' : 'pm'}`
}

/** Today's date in India as YYYY-MM-DD (for date inputs), whatever the server's clock zone. */
export function todayInIndia(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: IST, year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date())
}
