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
