import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import Link from 'next/link'
import { Fragment } from 'react'
import { notFound } from 'next/navigation'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { fetchTracking } from '@/lib/checkout-api'
import { fetchPublicWebsite } from '@/lib/public-website'
import { siteLang } from '@/lib/site-lang'
import { siteWords, type Words } from '@/lib/site-words'
import { SiteFrame } from '@/components/website/SiteFrame'

export const dynamic = 'force-dynamic'

const rupees = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: Number.isInteger(v) ? 0 : 2 }).format(v)

/** The customer reads plain words, never stored states (Founder refinement — Payments §13). */
const paymentWords = (t: Words): Record<string, string> => ({
  pending: t('Not paid yet'),
  pending_offline: t('To pay when you collect it'),
  partially_paid: t('Part paid'),
  paid: t('Payment received'),
  refunded: t('Refunded'),
  partially_refunded: t('Part refunded'),
  failed: t('Payment failed — try again'),
})

const orderWords = (t: Words): Record<string, string> => ({
  pending: t('Waiting for the shop to accept'),
  accepted: t('Accepted'),
  preparing: t('Being prepared'),
  ready: t('Ready'),
  completed: t('Completed'),
  cancelled: t('Cancelled'),
  rejected: t('Declined'),
})

const jobWords = (t: Words): Record<string, string> => ({
  received: t('Received'),
  preparing: t('Being prepared'),
  ready: t('Ready'),
  out_for_delivery: t('Out for delivery'),
  delivered: t('Delivered'),
  failed: t('Could not be completed'),
  cancelled: t('Cancelled'),
})

const modeWords = (t: Words): Record<string, string> => ({ pickup: t('Pickup'), delivery: t('Delivery'), shipping: t('Shipping') })

const trackSteps = (t: Words): { key: string; label: string }[] => [
  { key: 'placed', label: t('Placed') },
  { key: 'preparing', label: t('Preparing') },
  { key: 'picked_up', label: t('Picked up') },
  { key: 'on_the_way', label: t('On the way') },
  { key: 'delivered', label: t('Delivered') },
]

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Your order')
}

/**
 * WEB-008 Order Tracking — Doc 12 §11.2 / Doc 09 WEB-008. Reached from the
 * order confirmation and from WhatsApp (?lang= carries the customer's
 * language), in the business's own colours.
 */
export default async function TrackOrderPage({
  params,
  searchParams,
}: {
  params: { slug: string; orderId: string }
  searchParams?: { token?: string; lang?: string }
}) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  const site = await fetchPublicWebsite(params.slug)
  const lang = siteLang(site?.website.languages, searchParams?.lang, true)
  const t = siteWords(lang)
  const token = searchParams?.token
  const data = token ? await fetchTracking(params.orderId, token) : null
  const name = site?.business.display_name

  let body: React.ReactNode
  if (!token) {
    body = <><h1 className="ls-title">{t('Tracking unavailable')}</h1><p className="ls-meta">{t('This tracking link is missing a token.')}</p></>
  } else if (!data) {
    body = <><h1 className="ls-title">{t('Invalid tracking link')}</h1><p className="ls-meta">{t('We could not find this order. The link may be incorrect.')}</p></>
  } else if (data.state === 'expired') {
    body = (
      <>
        <h1 className="ls-title">{t('Tracking link expired')}</h1>
        <p className="ls-meta">{t('Order {number} can no longer be viewed with this link.', { number: data.order?.order_number ?? '' })}</p>
      </>
    )
  } else {
    const job = data.fulfilment
    body = (
      <>
        <h1 className="ls-title">{t('Order {number}', { number: data.order.order_number })}</h1>
        <section className="ls-bill__card">
          <dl className="ls-bill__totals">
            <dt>{t('Order')}</dt>
            <dd>{orderWords(t)[data.order.status] ?? data.order.status}</dd>
            <dt>{t('Payment')}</dt>
            <dd>{paymentWords(t)[data.order.payment_status] ?? t('Being checked')}</dd>
            {data.order.due_words ? (<><dt>{t('Ready')}</dt><dd>{data.order.due_words}</dd></>) : null}
            {job ? (
              <>
                <dt>{modeWords(t)[job.mode] ?? job.mode}</dt>
                <dd>{jobWords(t)[job.customer_status] ?? job.customer_status}</dd>
              </>
            ) : null}
          </dl>
          {data.dispatch ? (
            <>
              <ol>
                {trackSteps(t).map((step) => {
                  const here = step.key === data.dispatch.reached_step
                  return (
                    <li key={step.key} aria-current={here ? 'step' : undefined}>
                      {here ? <strong>{step.label}</strong> : step.label}
                    </li>
                  )
                })}
              </ol>
              {data.dispatch.partner_first_name ? (
                <p className="ls-meta">{t('With {name}', { name: data.dispatch.partner_first_name })}</p>
              ) : null}
              {data.dispatch.failed ? (
                <p className="ls-offer__error" role="alert">{t('Could not be completed')}</p>
              ) : null}
              <p className="ls-meta">{t('Live location is off until a device shares it.')}</p>
            </>
          ) : null}
          {data.state === 'delayed' ? <p className="ls-meta">{t('Delivery appears delayed. Contact the business if needed.')}</p> : null}
          {data.state === 'failed' ? <p className="ls-offer__error" role="alert">{t('This could not be completed. Contact the business for help.')}</p> : null}
          {data.state === 'cancelled' ? <p className="ls-meta">{t('This was cancelled.')}</p> : null}
        </section>
        {data.items?.length ? (
          <section className="ls-bill__card" aria-label={t('Items')}>
            <dl className="ls-bill__totals">
              {data.items.map((item: { title: string; quantity: number; line_total: number }, i: number) => (
                <Fragment key={`${item.title}-${i}`}>
                  <dt>{item.quantity} × {item.title}</dt>
                  <dd>{rupees(item.line_total)}</dd>
                </Fragment>
              ))}
              <dt className="is-total">{t('Total')}</dt>
              <dd className="is-total">{rupees(data.order.total_amount)}</dd>
            </dl>
          </section>
        ) : null}
        {data.pickup ? (
          <section className="ls-bill__card" aria-label={t('Pickup')}>
            <p className="ls-meta">{t('Collect it from')}</p>
            <p>{[data.pickup.name, data.pickup.address].filter(Boolean).join(' · ') || name}</p>
            {data.pickup.phone ? (
              <p><a href={`tel:${data.pickup.phone.replace(/[^+\d]/g, '')}`}>{t('Call {phone}', { phone: data.pickup.phone })}</a></p>
            ) : null}
          </section>
        ) : null}
      </>
    )
  }

  return (
    <SiteFrame site={site} lang={lang}>
      <main className="ls-section">
        <div className="ls-inner ls-checkout">
          <p><Link href={`/${params.slug}`}>← {name ?? t('Website')}</Link></p>
          {body}
        </div>
      </main>
    </SiteFrame>
  )
}
