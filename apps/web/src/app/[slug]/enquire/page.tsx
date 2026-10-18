import type { Metadata } from 'next'
import { actionPageMetadata } from '@/lib/page-meta'
import { notFound } from 'next/navigation'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchPublicWebsite } from '@/lib/public-website'
import { fetchPublicOfferings, fetchPublicPlans } from '@/lib/checkout-api'
import { coverPicture } from '@/lib/structured-data'
import { SiteFrame } from '@/components/website/SiteFrame'
import { siteLang } from '@/lib/site-lang'
import { siteWords } from '@/lib/site-words'
import { EnquiryForm } from '@/components/website/EnquiryForm'
import { PURPOSES, purposeTitles } from '@/components/website/enquiry-purposes'
import { Specs, priceLabel, type PublicOffering } from '@/components/website/offering-view'

export const dynamic = 'force-dynamic'

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return actionPageMetadata(params.slug, 'Send an enquiry')
}

type Route = { key: string; label: string; href: string }

/**
 * A business's enquiry page — its own colours, one heading (the thing asked
 * about, or what the enquiry is for), the form, and beside it what happens
 * after Send and every other way to reach them: a visitor who would rather
 * call is never left with only a form.
 */
export default async function EnquirePage({
  params,
  searchParams,
}: {
  params: { slug: string }
  searchParams: { offering_id?: string; plan_id?: string; purpose?: string; lang?: string }
}) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const site = await fetchPublicWebsite(params.slug)
  if (!site) notFound()
  const lang = siteLang(site.website.languages, searchParams.lang)
  const t = siteWords(lang)
  const offerings = ((await fetchPublicOfferings(params.slug)).offerings ?? []) as PublicOffering[]
  const offering = searchParams.offering_id ? offerings.find((o) => o.id === searchParams.offering_id) : undefined
  const plan = searchParams.plan_id
    ? (await fetchPublicPlans(params.slug)).find((p) => p.id === searchParams.plan_id)
    : undefined
  const name = site.business.display_name
  const open = Boolean(site.capabilities?.enquire)
  const asked = searchParams.purpose || ''
  const purpose = plan ? 'membership' : PURPOSES.includes(asked) ? asked : 'enquiry'

  // Every other way in — only what the owner published.
  const place = site.business.place || {}
  const contact = site.business.contact || {}
  const phone = place.phone || contact.phone || ''
  const wa = site.whatsapp?.href || (contact.whatsapp ? `https://wa.me/${contact.whatsapp.replace(/\D/g, '')}` : '')
  const where = place.address || place.locality || ''
  const routes: Route[] = []
  if (phone) routes.push({ key: 'Call', label: phone, href: `tel:${phone.replace(/[^\d+]/g, '')}` })
  if (wa) routes.push({ key: 'WhatsApp', label: t('Message on WhatsApp'), href: wa })
  if (contact.email) routes.push({ key: 'Email', label: contact.email, href: `mailto:${contact.email}` })
  const picture = offering?.image_url ? { url: offering.image_url, alt: offering.title } : coverPicture(site)

  return (
    <SiteFrame site={site} lang={lang} style={{ minHeight: undefined }}>
      <main className="ls-section ls-enquire-page">
        <div className="ls-inner ls-enquire">
          <header className="ls-enquire__head">
            <p className="ls-eyebrow">{offering?.kind ? t(offering.kind.label) : plan ? t('Plan') : name}</p>
            <h1 className="ls-title">{offering ? offering.title : plan ? plan.title : purposeTitles(t)[purpose]}</h1>
            {offering && priceLabel(offering, t) ? <p className="ls-price">{priceLabel(offering, t)}</p> : null}
            {plan ? (
              <p className="ls-price">
                {new Intl.NumberFormat('en-IN', {
                  style: 'currency',
                  currency: plan.currency || 'INR',
                  maximumFractionDigits: 0,
                }).format(Number(plan.price_amount))}
                {plan.duration_days ? ` · ${t('{n} days', { n: plan.duration_days })}` : ''}
              </p>
            ) : null}
          </header>

          <div className="ls-enquire__grid">
            <div className="ls-enquire__main">
              {offering?.description ? <p className="ls-item__desc">{offering.description}</p> : null}
              {offering ? <Specs o={offering} t={t} /> : null}
              {plan?.description ? <p className="ls-item__desc">{plan.description}</p> : null}
              {open ? (
                <EnquiryForm
                  slug={params.slug}
                  businessName={name}
                  offeringId={offering?.id}
                  offeringTitle={offering?.title}
                  planId={plan?.id}
                  planTitle={plan?.title}
                  purpose={purpose}
                  titled={false}
                />
              ) : (
                <p className="ls-meta">
                  {t('{business} is not taking enquiries online yet. Use the contact details on their site.', {
                    business: name,
                  })}
                </p>
              )}
            </div>

            <aside className="ls-enquire__aside" aria-label={t('What happens next')}>
              {picture ? (
                <figure className="ls-enquire__picture">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={picture.url} alt={picture.alt} />
                </figure>
              ) : null}
              {open ? (
                <div className="ls-enquire__next">
                  <h2 className="ls-enquire__h">{t('What happens next')}</h2>
                  <ol>
                    <li>{t('{business} reads your enquiry.', { business: name })}</li>
                    <li>{t('They reply to you by phone or email.')}</li>
                    <li>{t('Nothing is booked or paid until you agree.')}</li>
                  </ol>
                </div>
              ) : null}
              {routes.length || where || place.hours_summary ? (
                <dl className="ls-enquire__routes">
                  {routes.map((r) => (
                    <div key={r.key}>
                      <dt>{t(r.key)}</dt>
                      <dd>
                        <a href={r.href} {...(r.key === 'WhatsApp' ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
                          {r.label}
                        </a>
                      </dd>
                    </div>
                  ))}
                  {where ? (
                    <div>
                      <dt>{t('Find us')}</dt>
                      <dd>{where}</dd>
                    </div>
                  ) : null}
                  {place.hours_summary ? (
                    <div>
                      <dt>{t('Hours')}</dt>
                      <dd>{place.hours_summary}</dd>
                    </div>
                  ) : null}
                </dl>
              ) : null}
            </aside>
          </div>
        </div>
      </main>
    </SiteFrame>
  )
}
