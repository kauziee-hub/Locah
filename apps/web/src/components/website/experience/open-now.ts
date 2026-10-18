/**
 * "Open now · until 11 pm" / "Opens 7 am" — honest urgency from the
 * location's own saved hours (business.place.hours), worked out in the
 * visitor's browser on the business's clock (Asia/Kolkata).
 *
 * Nothing is ever invented: unknown or malformed hours give no chip at all.
 * The words around the times are the site's own (site-words.json, passed in
 * already translated by WebsitePageView); the times and day names are written
 * by the browser's locale data in the visitor's language.
 *
 * Pure: no React, no DOM — the chip component (SiteMotion.tsx) calls it.
 */

export type Slot = [string, string]
export type Week = Partial<Record<Day, Slot[]>>

const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'] as const
type Day = (typeof DAYS)[number]
const HHMM = /^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$/
const DAY_MIN = 24 * 60

/** The saved hours, only when they are the shape the location stores; else null. */
export function readHours(value: unknown): Week | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  const week: Week = {}
  let any = false
  for (const day of DAYS) {
    const slots = raw[day]
    if (slots === undefined || slots === null) continue
    if (!Array.isArray(slots)) return null
    const kept: Slot[] = []
    for (const slot of slots) {
      if (!Array.isArray(slot) || slot.length !== 2) return null
      const [open, close] = slot.map(String)
      if (!HHMM.test(open) || !HHMM.test(close) || open === close) return null
      kept.push([open, close])
    }
    week[day] = kept
    if (kept.length) any = true
  }
  return any ? week : null
}

function minutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

/** A day's slots as [open, close) minutes from that day's midnight; a slot
 *  past midnight ("18:00"–"02:00") closes after 1440. */
function spans(week: Week, dayIndex: number): Array<[number, number]> {
  const day = DAYS[((dayIndex % 7) + 7) % 7]
  return (week[day] || [])
    .map(([o, c]) => {
      const open = minutes(o)
      let close = minutes(c)
      if (close <= open) close += DAY_MIN
      return [open, close] as [number, number]
    })
    .sort((a, b) => a[0] - b[0])
}

/** The weekday (0 = Sunday) and minute of the day on the business's clock. */
export function clockAt(now: Date, timeZone = 'Asia/Kolkata'): { day: number; minute: number } {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(now)
    const get = (type: string) => parts.find((p) => p.type === type)?.value || ''
    const day = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(get('weekday'))
    const hour = Number(get('hour')) % 24
    const minute = Number(get('minute'))
    if (day >= 0 && Number.isFinite(hour) && Number.isFinite(minute)) return { day, minute: hour * 60 + minute }
  } catch {
    /* an engine without the zone: India keeps one offset all year */
  }
  const shifted = new Date(now.getTime() + 330 * 60_000)
  return { day: shifted.getUTCDay(), minute: shifted.getUTCHours() * 60 + shifted.getUTCMinutes() }
}

export type OpenState =
  /** open now; `until` minutes from today's midnight (past 1440 = after midnight) */
  | { kind: 'open'; until: number }
  /** open round the clock for the whole week */
  | { kind: 'always' }
  /** closed now; opens `inDays` days from today (0 today, 1 tomorrow) at `at` */
  | { kind: 'opens'; inDays: number; at: number; weekday: number }
  | null

/** Where the business stands right now. */
export function openState(week: Week, now: Date, timeZone = 'Asia/Kolkata'): OpenState {
  const { day, minute } = clockAt(now, timeZone)
  // Open now: a slot of today's, or last night's slot still running.
  let until: number | null = null
  for (const [, close] of spans(week, day - 1)) {
    if (close > DAY_MIN && minute < close - DAY_MIN) until = Math.max(until ?? 0, close - DAY_MIN)
  }
  for (const [open, close] of spans(week, day)) {
    if (open <= minute && minute < close) until = Math.max(until ?? 0, close)
  }
  if (until !== null) {
    // A slot that ends at midnight and one that starts at midnight are one
    // stretch: "until 2 am", not "until 12 am". Seven joined days is always open.
    for (let d = 1; d <= 7; d++) {
      if (until !== d * DAY_MIN) break
      const next = spans(week, day + d).find(([open]) => open === 0)
      if (!next) break
      if (d === 7) return { kind: 'always' }
      until = d * DAY_MIN + next[1]
    }
    return { kind: 'open', until }
  }
  for (let d = 0; d < 8; d++) {
    for (const [open] of spans(week, day + d)) {
      if (d > 0 || open > minute) return { kind: 'opens', inDays: d, at: open, weekday: (day + d) % 7 }
    }
  }
  return null
}

/** The site's own words for the chip, translated by the page (site-words.json). */
export type OpenWords = {
  open: string // "Open now"
  until: string // "until {time}"
  opens: string // "Opens {time}"
  tomorrow: string // "Opens tomorrow {time}"
  onDay: string // "Opens {day} {time}"
  always: string // "Open 24 hours"
}

/** "11 pm", "6:30 am" — or the visitor's language's own way of saying it. */
export function timeWords(minute: number, locale: string): string {
  const m = ((minute % DAY_MIN) + DAY_MIN) % DAY_MIN
  const h = Math.floor(m / 60)
  const mm = m % 60
  if (!locale.startsWith('en')) {
    try {
      // Tamil and Hindi say the part of the day ("இரவு 11", "सुबह 7").
      return new Intl.DateTimeFormat(locale, {
        hour: 'numeric',
        minute: mm ? '2-digit' : undefined,
        dayPeriod: 'short',
        timeZone: 'UTC',
      } as Intl.DateTimeFormatOptions).format(new Date(Date.UTC(2000, 0, 2, h, mm)))
    } catch {
      /* fall through to the plain clock */
    }
  }
  const h12 = h % 12 || 12
  return `${mm ? `${h12}:${String(mm).padStart(2, '0')}` : h12} ${h < 12 ? 'am' : 'pm'}`
}

function weekdayWords(weekday: number, locale: string): string {
  // 2 Jan 2000 was a Sunday.
  try {
    return new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(
      new Date(Date.UTC(2000, 0, 2 + weekday))
    )
  } catch {
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][weekday]
  }
}

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (m, key: string) => (key in values ? values[key] : m))
}

/** The chip: its words and whether the business is open; null for nothing to say. */
export function openChip(
  state: OpenState,
  words: OpenWords,
  locale: string
): { open: boolean; text: string; lead: string; rest: string } | null {
  if (!state) return null
  if (state.kind === 'always') return { open: true, text: words.always, lead: words.always, rest: '' }
  if (state.kind === 'open') {
    const rest = fill(words.until, { time: timeWords(state.until, locale) })
    return { open: true, text: `${words.open} · ${rest}`, lead: words.open, rest }
  }
  const time = timeWords(state.at, locale)
  const text =
    state.inDays === 0
      ? fill(words.opens, { time })
      : state.inDays === 1
        ? fill(words.tomorrow, { time })
        : fill(words.onDay, { day: weekdayWords(state.weekday, locale), time })
  return { open: false, text, lead: text, rest: '' }
}
