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

type Line = { id: string; title: string; hsn_sac: string | null; unit_label: string | null; quantity: number; line_total: number; tax_rate: number | null; basis_words?: string | null }
type PublicBill = {
  doc_kind: string
  kind_label: string
  status: string
  number: string
  issue_date: string
  due_date: string | null
  seller: { trade_name?: string; legal_name?: string; gstin?: string; scheme?: string; address?: string; declaration?: string; phone?: string }
  buyer: { name?: string; gstin?: string }
  place_of_supply_label: string
  intra_state: boolean | null
  reverse_charge: boolean
  prices_include_tax: boolean
  taxable_total: number
  cgst_total: number
  sgst_total: number
  igst_total: number
  round_off: number
  amount_due: number
  lines: Line[]
  related: { kind_label: string; number: string | null; issue_date: string | null }[]
  pdf_path: string
}

async function fetchBill(slug: string, token: string): Promise<PublicBill | null> {
  const res = await fetch(`${platformUrl('api')}/v1/public/websites/${encodeURIComponent(slug)}/bills/${encodeURIComponent(token)}`, { cache: 'no-store' })
  if (!res.ok) return null
  return ((await res.json()) as { data: PublicBill }).data
}

const rupees = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 }).format(v)
const day = (v: string | null, locale = 'en-IN') => (v ? new Date(`${v.slice(0, 10)}T00:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' }) : '')

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Your bill')
}

/**
 * "Your bill from <business>" (Capability Universe §14.4 outputs): the copy a
 * customer opens from WhatsApp, in the business's own colours, with its PDF.
 * The link itself is the credential; nothing else about the business or the
 * customer is shown.
 */
export default async function BillPage({ params, searchParams }: { params: { slug: string; token: string }; searchParams?: { lang?: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const bill = await fetchBill(params.slug, params.token)
  if (!bill) notFound()
  const site = await fetchPublicWebsite(params.slug)
  // A bill sent on WhatsApp carries the customer's language (?lang=); the PDF stays the legal English copy.
  const lang = siteLang(site?.website.languages, searchParams?.lang, true)
  const t = siteWords(lang)
  const locale = LANG_LOCALE[lang]
  const name = bill.seller.trade_name || bill.seller.legal_name || site?.business.display_name || ''
  const gst = bill.seller.scheme === 'regular' && !['bill', 'bill_of_supply'].includes(bill.doc_kind)
  const intra = bill.intra_state !== false
  const pdf = `${platformUrl('api')}${bill.pdf_path}`
  return (
    <SiteFrame site={site} lang={lang} style={{ minHeight: undefined }}>
      <main className="ls-section">
        <div className="ls-inner ls-bill">
          {site ? <p><Link href={`/${params.slug}`}>← {name}</Link></p> : null}
          <header className="ls-bill__head">
            <p className="ls-meta">{t('Your bill from {business}', { business: name })}</p>
            <h1 className="ls-title">{t(bill.kind_label)} {bill.number}</h1>
            <p className="ls-meta">{day(bill.issue_date, locale)}{bill.buyer.name ? ` · ${t('for {name}', { name: bill.buyer.name })}` : ''}</p>
          </header>
          {bill.status === 'cancelled' ? <p className="ls-bill__cancelled" role="status">{t('This bill was cancelled by {business}.', { business: name })}</p> : null}
          {bill.related.length && bill.doc_kind.endsWith('note') ? (
            <p className="ls-meta">{t('Against {kind} {number} of {date}', { kind: t(bill.related[0].kind_label), number: bill.related[0].number ?? '', date: day(bill.related[0].issue_date, locale) })}</p>
          ) : null}
          <div className="ls-bill__card">
            <ul className="ls-bill__lines">
              {bill.lines.map((l) => (
                <li key={l.id}>
                  <span>
                    {l.title}
                    <small>{l.quantity}{l.unit_label ? ` ${l.unit_label}` : ''}{gst && l.tax_rate !== null ? ` · GST ${l.tax_rate}%` : ''}</small>
                    {l.basis_words ? <small>{l.basis_words}</small> : null}
                  </span>
                  <strong>{rupees(l.line_total)}</strong>
                </li>
              ))}
            </ul>
            <dl className="ls-bill__totals">
              {gst ? (<><dt>{t('Taxable value')}</dt><dd>{rupees(bill.taxable_total)}</dd></>) : null}
              {gst && intra ? (<><dt>CGST</dt><dd>{rupees(bill.cgst_total)}</dd><dt>SGST</dt><dd>{rupees(bill.sgst_total)}</dd></>) : null}
              {gst && !intra ? (<><dt>IGST</dt><dd>{rupees(bill.igst_total)}</dd></>) : null}
              {bill.round_off ? (<><dt>{t('Round-off')}</dt><dd>{rupees(bill.round_off)}</dd></>) : null}
              <dt className="is-total">{bill.doc_kind === 'credit_note' ? t('Credit') : t('Total')}</dt>
              <dd className="is-total">{rupees(bill.amount_due)}</dd>
            </dl>
            {bill.doc_kind === 'bill_of_supply' && bill.seller.declaration ? <p className="ls-meta">{bill.seller.declaration}</p> : null}
          </div>
          <div className="ls-bill__actions">
            <a className="ls-btn" href={pdf} target="_blank" rel="noreferrer">{t('Download PDF')}</a>
            <a className="ls-btn ls-btn--outline" href={`${pdf}?layout=thermal_80`} target="_blank" rel="noreferrer">{t('Receipt size')}</a>
          </div>
          <footer className="ls-bill__seller ls-meta">
            <span>{bill.seller.legal_name}</span>
            {bill.seller.address ? <span>{bill.seller.address}</span> : null}
            {bill.seller.gstin && bill.seller.scheme !== 'unregistered' ? <span>GSTIN {bill.seller.gstin}</span> : null}
            {gst && bill.place_of_supply_label ? <span>{t('Place of supply {place}', { place: bill.place_of_supply_label })}</span> : null}
          </footer>
        </div>
      </main>
    </SiteFrame>
  )
}
