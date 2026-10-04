import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { platformUrl } from '@platform/config'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchPublicWebsite } from '@/lib/public-website'
import { getAccessToken } from '@/lib/supabase/access-token'
import { SiteFrame } from '@/components/website/SiteFrame'
import { siteLang } from '@/lib/site-lang'
import { LANG_LOCALE, siteWords, type Words } from '@/lib/site-words'
import { askToErase, changeTomorrow, payMembership, renewMembership } from './actions'

export const dynamic = 'force-dynamic'

type Account = {
  business: { id: string; slug: string; name: string }
  linked: boolean
  orders: { id: string; number: string; status: string; payment_status: string; total: number; placed_at: string; due_at?: string | null; due_words?: string | null; items: { title: string; quantity: number }[]; fulfilment: { mode: string; status: string } | null; track_url: string | null; bill_url: string | null; can_reorder: boolean }[]
  bookings: { id: string; number: string; title: string; status: string; starts_at: string; upcoming: boolean; manage_url: string | null }[]
  bills: { id: string; number: string; kind: string; status: string; issue_date: string | null; total: number; amount_due: number; url: string }[]
  quotes: { id: string; number: string; title: string | null; status: string; total: number; valid_until: string | null; url: string | null }[]
  memberships: {
    id: string; plan: string; kind: string; title: string; valid_label: string; status: string; starts_at: string
    ends_at: string | null; days_left: number | null; sessions_left: number | null; outstanding: number; paid: number
    next_due_on: string | null; overdue: boolean; good_standing: boolean | null; checkin_code: string | null
    can_renew: boolean; can_pay: boolean
    next_instalment?: { label: string; amount: number; due_on: string } | null
    tomorrow?: { date: string; status: string; quantity: number; cutoff: string; open: boolean }
  }[]
  khata: { balance: number; url: string } | null
  erasure_request?: { status: 'open' | 'done' | 'declined'; asked_at: string; reason: string | null } | null
}

const rupees = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(v)
const orderWords = (t: Words): Record<string, string> => ({
  pending: t('Placed — waiting for the shop'), accepted: t('Accepted'), preparing: t('Being prepared'), ready: t('Ready'),
  completed: t('Completed'), cancelled: t('Cancelled'), rejected: t('Could not be taken'),
})
/** Booking, membership and quote states in plain words; anything else shows as stored. */
const stateWords = (t: Words): Record<string, string> => ({
  confirmed: t('Confirmed'), pending: t('Waiting to be confirmed'), cancelled: t('Cancelled'), completed: t('Completed'),
  no_show: t('Missed'), active: t('Active'), expired: t('Ended'), paused: t('Paused'), sent: t('Sent to you'),
  accepted: t('Accepted'), declined: t('Declined'), draft: t('Being prepared'),
})

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Your account')
}

export default async function AccountPage({ params, searchParams }: { params: { slug: string }; searchParams?: { privacy?: string; lang?: string; membership?: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const site = await fetchPublicWebsite(params.slug)
  if (!site) notFound()
  const lang = siteLang(site.website.languages, searchParams?.lang)
  const t = siteWords(lang)
  const locale = LANG_LOCALE[lang]
  const when = (v: string) => new Date(v).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' })
  const at = (v: string) => new Date(v).toLocaleString(locale, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
  const state = (v: string) => stateWords(t)[v] ?? v
  const name = site.business.display_name
  const token = await getAccessToken()
  const shell = (body: React.ReactNode) => (
    <SiteFrame site={site} lang={lang} style={{ minHeight: undefined }}>
      <main className="ls-section">
        <div className="ls-inner ls-account">
          <p><Link href={`/${params.slug}`}>← {name}</Link></p>
          {body}
        </div>
      </main>
    </SiteFrame>
  )
  if (!token) {
    return shell(
      <section className="ls-account__signin">
        <h1 className="ls-title">{t('Your orders and bookings with {business}', { business: name })}</h1>
        <p className="ls-meta">{t('Sign in to see what you have ordered and booked here, open your bills and track a delivery. The same sign-in works on every business that uses LOCAH.')}</p>
        <p><a className="ls-btn" href={`/login?destination=${encodeURIComponent(`/${params.slug}/account`)}`}>{t('Sign in')}</a></p>
      </section>,
    )
  }
  const res = await fetch(`${platformUrl('api')}/v1/me/businesses/${encodeURIComponent(params.slug)}/account`, {
    headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
  })
  if (!res.ok) {
    return shell(<><h1 className="ls-title">{t('Your account with {business}', { business: name })}</h1><p className="ls-meta">{t('We could not load your records just now. Nothing is lost — try again in a moment.')}</p></>)
  }
  const a = ((await res.json()) as { data: Account }).data
  const upcoming = a.bookings.filter((b) => b.upcoming)
  const past = a.bookings.filter((b) => !b.upcoming)
  const empty = !a.orders.length && !a.bookings.length && !a.bills.length && !a.quotes.length && !a.memberships.length && !a.khata
  return shell(
    <>
      <header className="ls-account__head">
        <h1 className="ls-title">{t('Your account with {business}', { business: name })}</h1>
        <p className="ls-meta">{t('Only your own orders, bookings and bills here.')}</p>
        <form action="/auth/logout" method="post"><button type="submit" className="ls-btn ls-btn--outline">{t('Sign out')}</button></form>
      </header>
      {empty ? <div className="ls-account__card"><p><strong>{t('Nothing with {business} yet.', { business: name })}</strong></p>
        <p className="ls-meta">{t('Orders and bookings you make while signed in appear here — and earlier ones made with the email you signed in with.')}</p>
        <p><Link className="ls-btn" href={`/${params.slug}`}>{t('See what {business} offers', { business: name })}</Link></p></div> : null}

      {a.memberships.length ? <section className="ls-account__block" aria-labelledby="acc-m" id="acc-m"><h2 id="acc-m-h">{t(a.memberships[0].title)}</h2>
        {searchParams?.membership === 'late' ? <p className="ls-meta" role="status">{t('Tomorrow is already decided — call or message the business to change it.')}</p> : null}
        {searchParams?.membership === 'failed' ? <p className="ls-meta" role="status">{t('That could not be done right now.')}</p> : null}
        {a.memberships.map((m) => <div key={m.id} className="ls-account__card"><p><strong>{m.plan}</strong> · {state(m.status)}</p>
          <p className="ls-meta">{m.ends_at ? `${t(m.valid_label)} ${when(m.ends_at)}` : t('From {start}', { start: when(m.starts_at) })}{m.days_left !== null ? ` · ${m.days_left === 1 ? t('1 day left') : t('{n} days left', { n: m.days_left })}` : ''}{m.sessions_left !== null ? ` · ${t('{n} sessions left', { n: m.sessions_left })}` : ''}</p>
          {m.good_standing !== null ? <p className="ls-meta">{m.good_standing ? t('In good standing') : t('Dues not paid')}</p> : null}
          {m.next_instalment ? <p className="ls-meta">{t('Next instalment: {label} · {amount} due {date}', { label: m.next_instalment.label, amount: rupees(m.next_instalment.amount), date: when(m.next_instalment.due_on) })}</p> : null}
          {m.kind === 'fee_plan' ? <p className="ls-meta">{t('Paid {paid} · outstanding {amount}', { paid: rupees(m.paid), amount: rupees(m.outstanding) })}</p> : null}
          {m.checkin_code ? <p className="ls-meta">{t('Show this code at the front desk: {code}', { code: m.checkin_code })}</p> : null}
          {m.tomorrow ? <p className="ls-meta">{m.tomorrow.status === 'deliver' ? t('Tomorrow: {qty}', { qty: m.tomorrow.quantity }) : m.tomorrow.status === 'skipped' ? t('Tomorrow: skipped') : m.tomorrow.status === 'paused' ? t('Tomorrow: paused') : t('Tomorrow: no delivery')}{m.tomorrow.open ? ` · ${t('Changes close at {time} tonight.', { time: m.tomorrow.cutoff })}` : ''}</p> : null}
          <div className="ls-account__actions">
            {m.tomorrow && m.tomorrow.open && (m.tomorrow.status === 'deliver' || m.tomorrow.status === 'skipped') ? <form action={changeTomorrow}><input type="hidden" name="slug" value={params.slug} /><input type="hidden" name="id" value={m.id} /><input type="hidden" name="on_date" value={m.tomorrow.date} /><input type="hidden" name="kind" value={m.tomorrow.status === 'deliver' ? 'skip' : 'restore'} /><button type="submit" className="ls-btn ls-btn--outline">{m.tomorrow.status === 'deliver' ? t('Skip tomorrow') : t('Back to the usual tomorrow')}</button></form> : null}
            {m.can_pay ? <form action={payMembership}><input type="hidden" name="slug" value={params.slug} /><input type="hidden" name="id" value={m.id} /><button type="submit" className="ls-btn">{t('Pay {amount}', { amount: rupees(m.outstanding) })}</button></form> : m.can_renew ? <form action={renewMembership}><input type="hidden" name="slug" value={params.slug} /><input type="hidden" name="id" value={m.id} /><button type="submit" className="ls-btn">{t('Renew')}</button></form> : null}
          </div></div>)}</section> : null}

      {upcoming.length ? <section className="ls-account__block" aria-labelledby="acc-b"><h2 id="acc-b">{t('Coming up')}</h2>
        {upcoming.map((b) => <div key={b.id} className="ls-account__card"><p><strong>{b.title}</strong> · {at(b.starts_at)}</p>
          <p className="ls-meta">{t('Booking {number}', { number: b.number })} · {state(b.status)}</p>{b.manage_url ? <p><a className="ls-btn ls-btn--outline" href={b.manage_url}>{t('Change or cancel')}</a></p> : null}</div>)}</section> : null}

      {a.orders.length ? <section className="ls-account__block" aria-labelledby="acc-o"><h2 id="acc-o">{t('Orders')}</h2>
        {a.orders.map((o) => <div key={o.id} className="ls-account__card">
          <p className="ls-account__row"><strong>{t('Order {number}', { number: o.number })}</strong><span>{rupees(o.total)}</span></p>
          <p className="ls-meta">{when(o.placed_at)} · {orderWords(t)[o.status] ?? o.status}{o.fulfilment ? ` · ${o.fulfilment.mode === 'delivery' ? t('Delivery') : t('Pickup')}` : ''}</p>
          {o.due_words ? <p className="ls-meta">{t('Wanted for {when}', { when: o.due_words })}</p> : null}
          <ul className="ls-account__items">{o.items.map((i, n) => <li key={n}>{i.quantity} × {i.title}</li>)}</ul>
          <p className="ls-account__actions">
            {o.track_url && !['completed', 'cancelled', 'rejected'].includes(o.status) ? <a className="ls-btn ls-btn--outline" href={o.track_url}>{t('Track')}</a> : null}
            {o.bill_url ? <a className="ls-btn ls-btn--outline" href={o.bill_url}>{t('Bill')}</a> : null}
            {o.can_reorder ? <Link className="ls-btn" href={`/${params.slug}/checkout?reorder=${o.id}`}>{t('Order again')}</Link> : null}
          </p></div>)}</section> : null}

      {a.khata ? <section className="ls-account__block" aria-labelledby="acc-k"><h2 id="acc-k">{t('Your khata')}</h2>
        <div className="ls-account__card"><p className="ls-account__row"><strong>{a.khata.balance > 0 ? t('You owe') : a.khata.balance < 0 ? t('In your favour') : t('Settled')}</strong><span>{rupees(Math.abs(a.khata.balance))}</span></p>
          <p><a className="ls-btn ls-btn--outline" href={a.khata.url}>{a.khata.balance > 0 ? t('Statement and pay') : t('Statement')}</a></p></div></section> : null}

      {a.bills.length ? <section className="ls-account__block" aria-labelledby="acc-i"><h2 id="acc-i">{t('Bills')}</h2>
        <ul className="ls-account__list">{a.bills.map((d) => <li key={d.id}><a href={d.url}>{d.number}</a><span className="ls-meta">{d.issue_date ? when(d.issue_date) : ''}{d.status === 'cancelled' ? ` · ${t('Cancelled')}` : d.amount_due > 0 ? ` · ${t('{amount} due', { amount: rupees(d.amount_due) })}` : ''}</span><strong>{rupees(d.total)}</strong></li>)}</ul></section> : null}

      {a.quotes.length ? <section className="ls-account__block" aria-labelledby="acc-q"><h2 id="acc-q">{t('Quotes')}</h2>
        <ul className="ls-account__list">{a.quotes.map((q) => <li key={q.id}>{q.url ? <a href={q.url}>{q.title || q.number}</a> : <span>{q.title || q.number}</span>}<span className="ls-meta">{state(q.status)}{q.valid_until ? ` · ${t('valid until {date}', { date: when(q.valid_until) })}` : ''}</span><strong>{rupees(q.total)}</strong></li>)}</ul></section> : null}

      {past.length ? <section className="ls-account__block" aria-labelledby="acc-p"><h2 id="acc-p">{t('Past bookings')}</h2>
        <ul className="ls-account__list">{past.map((b) => <li key={b.id}><span>{b.title}</span><span className="ls-meta">{at(b.starts_at)} · {state(b.status)}</span></li>)}</ul></section> : null}

      {a.linked ? <section className="ls-account__block" id="acc-data" aria-labelledby="acc-d"><h2 id="acc-d">{t('Your details')}</h2>
        <div className="ls-account__card">
          <p className="ls-meta">{t('Download everything {business} keeps about you, or ask them to delete your details. Bills they must keep by law stay with them.', { business: name })}</p>
          <p className="ls-account__actions"><a className="ls-btn ls-btn--outline" href={`/${params.slug}/account/my-data`} download>{t('Download my data')}</a></p>
          {searchParams?.privacy === 'asked' ? <p className="ls-meta" role="status">{t('Your request was sent to {business}.', { business: name })}</p> : null}
          {searchParams?.privacy === 'failed' ? <p className="ls-meta" role="status">{t('Your request could not be sent just now — try again in a moment.')}</p> : null}
          {a.erasure_request?.status === 'open' ? (
            <p className="ls-meta">{t('You asked {business} to delete your details on {date}. They will act on it once nothing is still open with you.', { business: name, date: when(a.erasure_request.asked_at) })}</p>
          ) : a.erasure_request?.status === 'declined' ? (
            <p className="ls-meta">{t('{business} could not delete your details yet: {reason}', { business: name, reason: a.erasure_request.reason ?? '' })}</p>
          ) : (
            <form action={askToErase} className="ls-account__erase">
              <input type="hidden" name="slug" value={params.slug} />
              <label className="ls-meta" htmlFor="erase-note">{t('Anything they should know — optional')}</label>
              <input id="erase-note" name="note" maxLength={500} />
              <button type="submit" className="ls-btn ls-btn--outline">{t('Ask {business} to delete my details', { business: name })}</button>
            </form>
          )}
        </div></section> : null}
    </>,
  )
}
