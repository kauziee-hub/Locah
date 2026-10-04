import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { platformUrl } from '@platform/config'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchPublicWebsite } from '@/lib/public-website'
import { SiteFrame } from '@/components/website/SiteFrame'
import { siteLang } from '@/lib/site-lang'
import { LANG_LOCALE, siteWords } from '@/lib/site-words'

export const dynamic = 'force-dynamic'

type Statement = {
  business_name: string
  name: string
  balance: number
  party_type: 'customer' | 'supplier'
  overdue: number
  entries: { kind_label: string; amount: number; balance_after: number; entry_date: string; reference: string | null }[]
  upi_uri: string | null
}

async function fetchStatement(slug: string, token: string): Promise<Statement | null> {
  const res = await fetch(`${platformUrl('api')}/v1/public/websites/${encodeURIComponent(slug)}/khata/${encodeURIComponent(token)}`, { cache: 'no-store' })
  if (!res.ok) return null
  return ((await res.json()) as { data: Statement }).data
}

const rupees = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 }).format(v)
const day = (v: string, locale = 'en-IN') => new Date(`${v.slice(0, 10)}T00:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' })

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Your account statement')
}

/**
 * "Your khata with <business>" (Capability Universe §14.5): what the customer
 * owes, the latest entries, and a UPI link to pay — opened from the statement
 * the business sends on WhatsApp, in the business's own colours. The link is
 * the credential; nothing else about the business's customers is shown.
 */
export default async function KhataStatementPage({ params, searchParams }: { params: { slug: string; token: string }; searchParams?: { lang?: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const st = await fetchStatement(params.slug, params.token)
  if (!st) notFound()
  const site = await fetchPublicWebsite(params.slug)
  const lang = siteLang(site?.website.languages, searchParams?.lang, true)
  const t = siteWords(lang)
  const name = site?.business.display_name || st.business_name
  const qr = `${platformUrl('api')}/v1/public/websites/${encodeURIComponent(params.slug)}/khata/${encodeURIComponent(params.token)}/upi-qr.svg`
  return (
    <SiteFrame site={site} lang={lang} style={{ minHeight: undefined }}>
      <main className="ls-section">
        <div className="ls-inner ls-bill">
          {site ? <p><Link href={`/${params.slug}`}>← {name}</Link></p> : null}
          <header className="ls-bill__head">
            <p className="ls-meta">{t('Your account with {business}', { business: name })}</p>
            <h1 className="ls-title">
              {st.balance > 0 ? t('{amount} due', { amount: rupees(st.balance) }) : st.balance < 0 ? t('{amount} in your favour', { amount: rupees(-st.balance) }) : t('Nothing due')}
            </h1>
            <p className="ls-meta">{st.name}{st.overdue > 0 ? ` · ${t('{amount} of it is past its due date', { amount: rupees(st.overdue) })}` : ''}</p>
          </header>
          {st.upi_uri && st.balance > 0 ? (
            <div className="ls-bill__card ls-khata__pay">
              <a className="ls-btn" href={st.upi_uri}>{t('Pay {amount} by UPI', { amount: rupees(st.balance) })}</a>
              {/* eslint-disable-next-line @next/next/no-img-element -- a QR image served by the platform */}
              <img className="ls-khata__qr" src={qr} alt={t('UPI QR code to pay {business}', { business: name })} width={180} height={180} />
              <p className="ls-meta">{t('Opens your UPI app on this phone; on a computer, scan the code. {business} confirms the payment on their side.', { business: name })}</p>
            </div>
          ) : null}
          <div className="ls-bill__card">
            <h2 className="ls-khata__h">{t('Latest entries')}</h2>
            {st.entries.length ? (
              <ul className="ls-bill__lines">
                {st.entries.map((e, i) => (
                  <li key={i}>
                    <span>
                      {t(e.kind_label)}{e.reference ? ` · ${e.reference}` : ''}
                      <small>{day(e.entry_date, LANG_LOCALE[lang])} · {t('balance {amount}', { amount: rupees(e.balance_after) })}</small>
                    </span>
                    <strong>{e.amount > 0 ? '+' : '−'}{rupees(Math.abs(e.amount))}</strong>
                  </li>
                ))}
              </ul>
            ) : <p className="ls-meta">{t('No entries yet.')}</p>}
          </div>
          <footer className="ls-bill__seller ls-meta">
            <span>{t('Questions about an entry? Ask {business}.', { business: name })}</span>
          </footer>
        </div>
      </main>
    </SiteFrame>
  )
}
