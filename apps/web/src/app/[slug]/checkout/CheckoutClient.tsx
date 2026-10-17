'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import {
  CartItem,
  cartStorageKey,
  fetchGstStates,
  placeCheckoutOrder,
  priceCart,
  type PricedCart,
} from '@/lib/checkout-api'
import { LANG_LOCALE, type Words } from '@/lib/site-words'
import { useSiteLang, useWords } from '@/components/website/SiteWords'

type Options = {
  fulfilment_modes: string[]
  payment_methods: string[]
  /** Cash on delivery as the business set it (the same rule as its WhatsApp orders). */
  cod?: { on_delivery: boolean; first_order_cap: number | null }
  locations: Array<{ id: string; name: string; is_primary: boolean }>
  business: { display_name: string; slug: string }
}

type RazorpayCheckout = {
  provider: string
  order_id: string
  key_id: string
  amount: number
  currency: string
}

// The legacy online checkout (frozen, not extended — founder 2026-09-27): only
// for a business whose old Razorpay connection is still active.
function loadRazorpayScript(): Promise<void> {
  if (typeof window === 'undefined') return Promise.resolve()
  if (document.querySelector('script[src="https://checkout.razorpay.com/v1/checkout.js"]')) {
    return Promise.resolve()
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Could not load the payment page.'))
    document.body.appendChild(script)
  })
}

function openRazorpayCheckout(checkout: RazorpayCheckout, name: string) {
  void loadRazorpayScript().then(() => {
    const RazorpayCtor = (window as unknown as { Razorpay?: new (opts: Record<string, unknown>) => { open: () => void } }).Razorpay
    if (!RazorpayCtor) return
    const rzp = new RazorpayCtor({
      key: checkout.key_id,
      amount: Math.round(checkout.amount * 100),
      currency: checkout.currency,
      order_id: checkout.order_id,
      name,
      handler: () => window.location.reload(),
    })
    rzp.open()
  })
}

const rupees = (v: number | null | undefined) =>
  v === null || v === undefined
    ? ''
    : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: Number.isInteger(v) ? 0 : 2 }).format(v)

const hour = (hhmm: string, locale = 'en-IN') => {
  const [h, m] = hhmm.split(':').map(Number)
  if (locale !== 'en-IN') return new Date(2000, 0, 1, h, m).toLocaleTimeString(locale, { hour: 'numeric', minute: m ? '2-digit' : undefined })
  const suffix = h >= 12 ? 'pm' : 'am'
  const h12 = h % 12 === 0 ? 12 : h % 12
  return m ? `${h12}:${String(m).padStart(2, '0')} ${suffix}` : `${h12} ${suffix}`
}

const modeWords = (t: Words): Record<string, string> => ({ pickup: t('Pickup'), delivery: t('Delivery'), shipping: t('Shipping') })

type Confirmation = {
  order_number: string
  tracking: { href: string }
  state: string
  due_words: string | null
  advance: { amount: number; path: string } | null
  checkout?: RazorpayCheckout | null
  paymentError?: string | null
}

/**
 * The website checkout (Founder refinement — Orders & Customer Transactions):
 * basket → pickup or delivery → address → the day it is wanted (made-to-order
 * items) → how to pay → the server's prices, tax, delivery charge and advance →
 * place → confirmation, tracking and My Activity. Every amount on this page
 * comes from the server; the basket's own numbers are never sent.
 */
export default function CheckoutClient({
  slug,
  options,
  customer,
  authToken,
  reorder,
  unavailable,
  rangePath = '',
}: {
  slug: string
  options: Options
  /** The site's range page ("/menu"): where an empty basket sends the visitor. */
  rangePath?: string
  /** The signed-in LOCAH customer, if any: the order joins their own record. */
  customer?: { name: string; email: string } | null
  authToken?: string | null
  /** "Order again": the lines of an earlier order at today's price. */
  reorder?: CartItem[] | null
  unavailable?: string[]
}) {
  const t = useWords()
  const locale = LANG_LOCALE[useSiteLang()]
  /** A day as the visitor reads it: the server's English label, or the date in their language. */
  const dayLabel = (d: { date: string; label: string }) =>
    locale === 'en-IN' ? d.label : new Date(`${d.date}T00:00:00`).toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'short' })
  const [items, setItems] = useState<CartItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const [mode, setMode] = useState(options.fulfilment_modes[0] || '')
  const [paymentMethod, setPaymentMethod] = useState(options.payment_methods[0] || 'cod')
  const [name, setName] = useState(customer?.name ?? '')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [city, setCity] = useState('')
  const [line1, setLine1] = useState('')
  const [postal, setPostal] = useState('')
  const [stateCode, setStateCode] = useState('')
  const [states, setStates] = useState<{ code: string; name: string }[]>([])
  const [dueDate, setDueDate] = useState('')
  const [dueTime, setDueTime] = useState('')
  const [priced, setPriced] = useState<PricedCart | null>(null)
  const [pricing, setPricing] = useState(false)
  const [priceError, setPriceError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)

  useEffect(() => {
    if (reorder && reorder.length) {
      setItems(reorder)
      try {
        localStorage.setItem(cartStorageKey(slug), JSON.stringify(reorder))
      } catch {
        /* storage unavailable — the cart still holds the lines */
      }
    } else {
      try {
        const raw = localStorage.getItem(cartStorageKey(slug))
        setItems(raw ? (JSON.parse(raw) as CartItem[]) : [])
      } catch {
        setItems([])
      }
    }
    setLoaded(true)
  }, [slug, reorder])

  useEffect(() => {
    if (mode === 'delivery' && !states.length) fetchGstStates().then(setStates).catch(() => setStates([]))
  }, [mode, states.length])

  const cartBody = useMemo(
    () =>
      items.map((i) => ({ offering_id: i.offering_id, variant_id: i.variant_id, quantity: i.quantity, options: i.options })),
    [items]
  )
  const due = dueDate ? { date: dueDate, time: dueTime } : null
  const address = mode === 'delivery' ? { city, line1, postal_code: postal, state_code: stateCode || undefined } : undefined

  // The server prices the basket whenever something that changes the total changes.
  useEffect(() => {
    if (!items.length) {
      setPriced(null)
      return
    }
    let live = true
    setPricing(true)
    const timer = setTimeout(() => {
      priceCart(slug, { items: cartBody, fulfilment_mode: mode || undefined, delivery_address: address, due })
        .then((p) => {
          if (!live) return
          setPriced(p)
          setPriceError(null)
          if (p.preorder.offered && !dueDate && p.preorder.needed) {
            const first = p.preorder.dates.find((d) => !d.full)
            if (first) {
              setDueDate(first.date)
              setDueTime(first.times[0])
            }
          }
        })
        .catch((e: unknown) => live && setPriceError(e instanceof Error ? e.message : t('We could not price your basket.')))
        .finally(() => live && setPricing(false))
    }, 250)
    return () => {
      live = false
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, cartBody, mode, city, line1, postal, stateCode, dueDate, dueTime])

  const pre = priced?.preorder
  const day = pre?.dates.find((d) => d.date === dueDate)
  const delivery = mode === 'delivery' ? priced?.delivery : null
  const payingNow = pre && pre.advance > 0 && dueDate ? pre.advance : 0
  const cod = priced?.cod ?? options.cod

  function persist(next: CartItem[]) {
    setItems(next)
    try {
      localStorage.setItem(cartStorageKey(slug), JSON.stringify(next))
    } catch {
      /* storage unavailable */
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!items.length) return setError(t('Your basket is empty.'))
    if (!mode) return setError(t('This business is not taking pickup or delivery orders right now.'))
    if (mode === 'delivery' && delivery && !delivery.serviceable) return setError(t('We do not deliver to this address yet.'))
    if (pre?.needed && !dueDate) return setError(t('Choose the day you need it.'))
    setSubmitting(true)
    try {
      const data = await placeCheckoutOrder(
        slug,
        {
          // Prices are never sent: the server prices each line from the catalogue.
          items: cartBody,
          fulfilment_mode: mode,
          payment_method: paymentMethod,
          location_id: options.locations.find((l) => l.is_primary)?.id || options.locations[0]?.id,
          delivery_address: address,
          guest: customer ? { name: name || customer.name, phone: phone || undefined } : { name, email, phone: phone || undefined },
          due: pre?.offered && dueDate ? due : undefined,
          idempotency_key: crypto.randomUUID(),
        },
        authToken
      )
      localStorage.removeItem(cartStorageKey(slug))
      const payment = data.payment as { checkout?: RazorpayCheckout; failure_reason?: string } | null | undefined
      setConfirmation({
        order_number: data.confirmation.order_number,
        tracking: data.tracking,
        state: data.state,
        due_words: pre?.offered && dueDate && day ? `${dayLabel(day)}, ${hour(dueTime, locale)}` : null,
        advance: data.advance ? { amount: data.advance.amount, path: data.advance.path } : null,
        checkout: payment?.checkout ?? null,
        paymentError: payment?.failure_reason ?? null,
      })
      if (payment?.checkout) openRazorpayCheckout(payment.checkout, options.business.display_name)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('That did not go through. Try again.'))
    } finally {
      setSubmitting(false)
    }
  }

  if (confirmation) {
    const pickupAt = options.locations.find((l) => l.is_primary) || options.locations[0]
    const howToPay = confirmation.checkout && !['succeeded', 'paid'].includes(confirmation.state)
      ? t('Your order is held. Finish the payment to confirm it.')
      : confirmation.state === 'paid' || confirmation.state === 'succeeded'
        ? t('Payment received.')
        : confirmation.paymentError || (mode === 'delivery' ? t('Pay when it is delivered.') : t('Pay when you collect your order.'))
    return (
      <main className="ls-section ls-confirm">
        <div className="ls-inner ls-checkout">
          <header className="ls-confirm__head">
            <p className="ls-eyebrow">{t('Order {number}', { number: confirmation.order_number })}</p>
            <h1 className="ls-confirm__title">{t('Order confirmed')}</h1>
            <p className="ls-confirm__lede">
              {confirmation.advance ? null : howToPay}
              {confirmation.due_words ? ` ${t('ready {when}', { when: confirmation.due_words })}` : ''}
            </p>
          </header>
          {confirmation.advance ? (
            <div className="ls-bill__card">
              <p style={{ margin: 0 }}>
                {t('Please pay the {amount} advance to confirm your order. The rest is paid when you collect it.', { amount: rupees(confirmation.advance.amount) })}
              </p>
              <div className="ls-bill__actions">
                <Link className="ls-btn" href={confirmation.advance.path}>{t('Pay {amount} advance', { amount: rupees(confirmation.advance.amount) })}</Link>
              </div>
            </div>
          ) : null}
          {items.length ? (
            <section className="ls-bill__card" aria-labelledby="ordered-h">
              <h2 id="ordered-h" className="ls-checkout__h">{t('Basket')}</h2>
              <ul className="ls-bill__lines">
                {items.map((item, idx) => {
                  const line = priced?.lines[idx]
                  return (
                    <li key={item.key ?? item.offering_id}>
                      <span>{item.quantity} × {line?.title ?? item.title}</span>
                      <strong>{line ? rupees(line.line_total) : ''}</strong>
                    </li>
                  )
                })}
              </ul>
              {priced ? (
                <dl className="ls-bill__totals">
                  <dt className="is-total">{t('Total')}</dt>
                  <dd className="is-total">{rupees(priced.total)}</dd>
                </dl>
              ) : null}
              {mode !== 'delivery' && pickupAt?.name && !/^(primary|main|default) location$/i.test(pickupAt.name.trim()) ? (
                <p className="ls-meta">{pickupAt.name}</p>
              ) : null}
            </section>
          ) : null}
          {confirmation.checkout ? (
            <button type="button" className="ls-btn" onClick={() => openRazorpayCheckout(confirmation.checkout!, options.business.display_name)}>
              {t('Pay now')}
            </button>
          ) : null}
          <div className="ls-bill__actions">
            <Link className="ls-btn" href={confirmation.tracking.href}>{t('Track your order')}</Link>
            <Link className="ls-btn ls-btn--outline" href={`/${slug}`}>{t('Back to {business}', { business: options.business.display_name })}</Link>
          </div>
        </div>
      </main>
    )
  }

  return (
    <main className="ls-section">
      <div className="ls-inner ls-checkout">
        <h1 className="ls-title">{t('Your order')}</h1>
        {reorder && reorder.length ? <p className="ls-meta" role="status">{t('Your earlier order, at today’s prices. Change anything before you place it.')}</p> : null}
        {unavailable && unavailable.length ? <p className="ls-meta" role="status">{t('No longer sold: {items}.', { items: unavailable.join(', ') })}</p> : null}

        {loaded && items.length === 0 ? (
          <section className="ls-bill__card ls-checkout__empty">
            <h2 className="ls-checkout__h">{t('Your basket is empty')}</h2>
            {/* Straight to where the things to add are, not back to the home page. */}
            <Link className="ls-btn ls-btn--primary" href={`/${slug}${rangePath}`}>
              {t('See what {business} sells', { business: options.business.display_name })}
            </Link>
          </section>
        ) : (
          <form onSubmit={onSubmit} className="ls-checkout__form">
            <section className="ls-bill__card" aria-labelledby="basket-h">
              <h2 id="basket-h" className="ls-checkout__h">{t('Basket')}</h2>
              <ul className="ls-bill__lines">
                {items.map((item, idx) => {
                  const line = priced?.lines[idx]
                  return (
                    <li key={item.key ?? item.offering_id}>
                      <span>
                        {item.quantity} × {line?.title ?? item.title}
                        {!line && item.detail ? <small>{item.detail}</small> : null}
                      </span>
                      <span className="ls-checkout__line-end">
                        <strong>{line ? rupees(line.line_total) : '…'}</strong>
                        <button type="button" className="ls-checkout__remove"
                          onClick={() => persist(items.filter((i) => (i.key ?? i.offering_id) !== (item.key ?? item.offering_id)))}>
                          {t('Remove')}
                        </button>
                      </span>
                    </li>
                  )
                })}
              </ul>
              {priced?.problems.length ? (
                <p className="ls-offer__error" role="alert">
                  {priced.problems.map((p) => `${p.title}: ${p.available ? t('only {n} left', { n: p.available }) : t('out of stock')}`).join(' · ')} — {t('change the quantity or remove it.')}
                </p>
              ) : null}
            </section>

            <section className="ls-bill__card" aria-labelledby="how-h">
              <h2 id="how-h" className="ls-checkout__h">{t('How you get it')}</h2>
              {options.fulfilment_modes.length === 0 ? (
                <p className="ls-meta">{t('This business is not taking pickup or delivery orders right now.')}</p>
              ) : (
                <div className="ls-choice" role="radiogroup" aria-label={t('Pickup or delivery')}>
                  {options.fulfilment_modes.map((m) => (
                    <button key={m} type="button" role="radio" aria-checked={mode === m} className={`ls-chip${mode === m ? ' is-on' : ''}`}
                      onClick={() => setMode(m)}>
                      {modeWords(t)[m] || m}
                    </button>
                  ))}
                </div>
              )}
              {mode === 'delivery' ? (
                <div className="ls-checkout__fields">
                  <label><span>{t('Address')}</span><input name="line1" value={line1} onChange={(e) => setLine1(e.target.value)} required autoComplete="street-address" /></label>
                  <label><span>{t('City')}</span><input name="city" value={city} onChange={(e) => setCity(e.target.value)} required autoComplete="address-level2" /></label>
                  <label><span>{t('PIN code')}</span><input name="postal_code" value={postal} onChange={(e) => setPostal(e.target.value.replace(/[^\d]/g, ''))} inputMode="numeric" maxLength={6} autoComplete="postal-code" /></label>
                  {states.length ? (
                    <label><span>{t('State')}</span>
                      <select value={stateCode} onChange={(e) => setStateCode(e.target.value)}>
                        <option value="">{t('Choose')}</option>
                        {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                      </select>
                    </label>
                  ) : null}
                  {delivery ? (
                    <p className="ls-meta">{delivery.serviceable ? t('Delivery charge {amount}', { amount: rupees(delivery.charge ?? 0) }) : t('We do not deliver to this address yet.')}</p>
                  ) : null}
                </div>
              ) : null}
            </section>

            {pre?.offered ? (
              <section className="ls-bill__card" aria-labelledby="when-h">
                <h2 id="when-h" className="ls-checkout__h">{pre.needed ? t('When do you need it?') : t('Want it on a particular day?')}</h2>
                {pre.earliest_words ? <p className="ls-meta">{t('Made to order — the earliest is {when}.', { when: pre.earliest_words })}</p> : null}
                {pre.dates.filter((d) => !d.full).length === 0 ? (
                  <p className="ls-offer__error" role="alert">{t('No day is open for these items right now. Call the business to ask.')}</p>
                ) : (
                  <div className="ls-checkout__fields">
                    <label>
                      <span>{t('Day')}</span>
                      <select value={dueDate} onChange={(e) => {
                        const d = pre.dates.find((x) => x.date === e.target.value)
                        setDueDate(e.target.value)
                        setDueTime(d?.times[0] ?? '')
                      }}>
                        {!pre.needed ? <option value="">{t('As soon as possible')}</option> : null}
                        {pre.dates.map((d) => (
                          <option key={d.date} value={d.date} disabled={d.full}>{dayLabel(d)}{d.full ? ` — ${t('full')}` : ''}</option>
                        ))}
                      </select>
                    </label>
                    {day ? (
                      <label>
                        <span>{t('Ready at')}</span>
                        <select value={dueTime} onChange={(e) => setDueTime(e.target.value)}>
                          {day.times.map((x) => <option key={x} value={x}>{hour(x, locale)}</option>)}
                        </select>
                      </label>
                    ) : null}
                  </div>
                )}
                {priced?.due_error ? <p className="ls-offer__error" role="alert">{priced.due_error}</p> : null}
                {pre.cancel_hours !== null && pre.cancel_hours !== undefined ? (
                  <p className="ls-meta">{t('You can cancel up to {hours} hours before it is due.', { hours: pre.cancel_hours })}</p>
                ) : null}
              </section>
            ) : null}

            <section className="ls-bill__card" aria-labelledby="pay-h">
              <h2 id="pay-h" className="ls-checkout__h">{t('Paying')}</h2>
              <div className="ls-choice" role="radiogroup" aria-label={t('How you pay')}>
                {options.payment_methods.map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={paymentMethod === m}
                    className={`ls-chip${paymentMethod === m ? ' is-on' : ''}`} onClick={() => setPaymentMethod(m)}>
                    {m === 'cod' ? (mode === 'delivery' ? t('Cash on delivery') : t('Pay at pickup')) : t('Pay online')}
                  </button>
                ))}
              </div>
              {payingNow > 0 ? (
                <p className="ls-meta">{t('This order asks for a {amount} advance — you pay it by UPI right after placing the order.', { amount: rupees(payingNow) })}</p>
              ) : null}
              {mode === 'delivery' && paymentMethod === 'cod' && cod && !cod.on_delivery ? (
                <p className="ls-meta">{t('Cash on delivery is not available. Choose pickup to pay when you collect.')}</p>
              ) : null}
              {mode === 'delivery' && paymentMethod === 'cod' && cod?.on_delivery && cod.first_order_cap !== null ? (
                <p className="ls-meta">{t('For a first order, cash on delivery is up to {amount}.', { amount: rupees(cod.first_order_cap) })}</p>
              ) : null}
            </section>

            <section className="ls-bill__card" aria-labelledby="you-h">
              <h2 id="you-h" className="ls-checkout__h">{t('Your details')}</h2>
              {customer ? (
                <p className="ls-meta">
                  {t('Ordering as {who}.', { who: `${customer.name || customer.email} · ${customer.email}` })}{' '}
                  <Link href={`/${slug}/account`}>{t('It will be in your account.')}</Link>
                </p>
              ) : (
                <p className="ls-meta">
                  <a href={`/login?destination=${encodeURIComponent(`/${slug}/checkout`)}`}>{t('Sign in')}</a> ·{' '}
                  {t('Signing in keeps this order with your others. Or order as a guest.')}
                </p>
              )}
              <div className="ls-checkout__fields">
                <label><span>{t('Name')}</span><input name="name" aria-label={t('Name')} value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" /></label>
                {customer ? null : (
                  <label><span>{t('Email')}</span><input name="email" type="email" aria-label={t('Email')} value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label>
                )}
                <label><span>{t('Phone (for updates on WhatsApp)')}</span><input name="phone" aria-label={t('Phone')} value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="tel" /></label>
              </div>
            </section>

            <section className="ls-bill__card" aria-label={t('Total')}>
              <dl className="ls-bill__totals">
                <dt>{t('Items')}</dt>
                <dd>{priced ? rupees(priced.items_total) : '…'}</dd>
                {priced && priced.tax_amount > 0 ? (
                  <>
                    <dt>{priced.tax_included ? t('GST (included)') : t('GST')}</dt>
                    <dd>{rupees(priced.tax_amount)}</dd>
                  </>
                ) : null}
                {delivery?.serviceable ? (
                  <>
                    <dt>{t('Delivery')}</dt>
                    <dd>{rupees(delivery.charge ?? 0)}</dd>
                  </>
                ) : null}
                <dt className="is-total">{t('Total')}</dt>
                <dd className="is-total">{priced ? rupees(priced.total) : '…'}</dd>
                {payingNow > 0 && priced ? (
                  <>
                    <dt>{t('Advance now')}</dt>
                    <dd>{rupees(payingNow)}</dd>
                    <dt>{mode === 'delivery' ? t('Balance at delivery') : t('Balance at pickup')}</dt>
                    <dd>{rupees(Math.max(0, priced.total - payingNow))}</dd>
                  </>
                ) : null}
              </dl>
              {priceError ? <p className="ls-offer__error" role="alert">{priceError}</p> : null}
              {error ? <p className="ls-offer__error" role="alert">{error}</p> : null}
              <button type="submit" className="ls-btn ls-checkout__place" disabled={submitting || pricing || !mode || !priced}>
                {submitting
                  ? t('Placing your order…')
                  : paymentMethod === 'online'
                    ? t('Place order and pay')
                    : payingNow > 0
                      ? t('Place order · pay {amount} advance', { amount: rupees(payingNow) })
                      : t('Place order')}
              </button>
            </section>
          </form>
        )}
      </div>
    </main>
  )
}
