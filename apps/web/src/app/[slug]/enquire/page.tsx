import type { Metadata } from 'next'
import { actionPageMetadata } from '@/lib/page-meta'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchPublicWebsite } from '@/lib/public-website'
import { fetchPublicOfferings, fetchPublicPlans } from '@/lib/checkout-api'
import { SiteFrame } from '@/components/website/SiteFrame'
import { siteLang } from '@/lib/site-lang'
import { siteWords } from '@/lib/site-words'
import { EnquiryForm } from '@/components/website/EnquiryForm'
import { Specs, priceLabel, type PublicOffering } from '@/components/website/offering-view'

export const dynamic = 'force-dynamic'

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return actionPageMetadata(params.slug, 'Send an enquiry')
}

/** A business's enquiry page — its own colours, the item asked about, the form. */
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
  return (
    <SiteFrame site={site} lang={lang} style={{ minHeight: undefined }}>
      <main className="ls-section">
        <div className="ls-inner ls-enquire">
          <p><Link href={`/${params.slug}`}>← {name}</Link></p>
          {offering ? (
            <article className="ls-enquire__item">
              {offering.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={offering.image_url} alt="" />
              ) : null}
              <div>
                {offering.kind ? <p className="ls-offer__kind">{t(offering.kind.label)}</p> : null}
                <h1 className="ls-title">{offering.title}</h1>
                {priceLabel(offering, t) ? <p className="ls-price">{priceLabel(offering, t)}</p> : null}
                {offering.description ? <p className="ls-item__desc">{offering.description}</p> : null}
                <Specs o={offering} t={t} />
              </div>
            </article>
          ) : plan ? (
            <article className="ls-enquire__item">
              <div>
                <p className="ls-offer__kind">{t('Plan')}</p>
                <h1 className="ls-title">{plan.title}</h1>
                <p className="ls-price">
                  {new Intl.NumberFormat('en-IN', { style: 'currency', currency: plan.currency || 'INR', maximumFractionDigits: 0 }).format(Number(plan.price_amount))}
                  {plan.duration_days ? ` · ${t('{n} days', { n: plan.duration_days })}` : ''}
                </p>
                {plan.description ? <p className="ls-item__desc">{plan.description}</p> : null}
              </div>
            </article>
          ) : (
            <h1 className="ls-title">{t('Contact {business}', { business: name })}</h1>
          )}
          {open ? (
            <EnquiryForm slug={params.slug} businessName={name} offeringId={offering?.id}
              offeringTitle={offering?.title} planId={plan?.id} planTitle={plan?.title}
              purpose={plan ? 'membership' : searchParams.purpose} />
          ) : (
            <p className="ls-meta">{t('{business} is not taking enquiries online yet. Use the contact details on their site.', { business: name })}</p>
          )}
        </div>
      </main>
    </SiteFrame>
  )
}
