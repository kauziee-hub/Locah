'use client'

import { useState } from 'react'
import { submitEnquiry, type EnquiryBody } from '@/lib/checkout-api'
import type { Words } from '@/lib/site-words'
import { useWords } from './SiteWords'
import { PURPOSES, purposeTitles } from './enquiry-purposes'

const messageHint = (t: Words): Record<string, string> => ({
  quote_request: t('What do you need? Quantities, sizes, dates — whatever helps them price it'),
  membership: t('Anything they should know before you start'),
})

/**
 * An enquiry to the business (Capability Universe §6.3, §19.2): it lands in
 * their Enquiries as a lead. The details are used to reply to this enquiry
 * only. A hidden field catches bots.
 */
export function EnquiryForm({
  slug,
  businessName,
  offeringId,
  offeringTitle,
  planId,
  planTitle,
  purpose = 'enquiry',
  titled = true,
}: {
  slug: string
  businessName: string
  offeringId?: string
  offeringTitle?: string
  planId?: string
  planTitle?: string
  purpose?: string
  /** False where the page already names the enquiry in its own heading. */
  titled?: boolean
}) {
  const t = useWords()
  const p = (PURPOSES.includes(purpose) ? purpose : 'enquiry') as NonNullable<EnquiryBody['purpose']>
  const wantsDate = p === 'site_visit' || p === 'test_drive'
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [ref, setRef] = useState<string | null>(null)
  const today = new Date().toISOString().slice(0, 10)

  if (state === 'sent') {
    return (
      <div className="ls-enquiry ls-enquiry--sent" role="status">
        <h2 className="ls-title">{t('Sent')}</h2>
        <p>
          {p === 'enquiry'
            ? t('{business} has your enquiry and will get back to you.', { business: businessName })
            : t('{business} has your request and will get back to you.', { business: businessName })}
          {ref ? ` ${t('Reference {ref}.', { ref })}` : ''}
        </p>
      </div>
    )
  }
  return (
    <form
      className="ls-enquiry"
      onSubmit={async (e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        setError(null)
        setState('sending')
        try {
          const r = await submitEnquiry(slug, {
            name: String(f.get('name') || ''),
            phone: String(f.get('phone') || '') || undefined,
            email: String(f.get('email') || '') || undefined,
            message: String(f.get('message') || '') || undefined,
            preferred_date: String(f.get('preferred_date') || '') || undefined,
            website: String(f.get('website') || '') || undefined,
            offering_id: offeringId,
            plan_id: planId,
            purpose: p,
          })
          setRef(r.reference ?? null)
          setState('sent')
        } catch (err) {
          setError(err instanceof Error ? err.message : t('That did not send. Try again.'))
          setState('idle')
        }
      }}
    >
      {titled ? <h2 className="ls-title">{purposeTitles(t)[p]}</h2> : null}
      {titled && offeringTitle ? <p className="ls-sub">{t('About: {item}', { item: offeringTitle })}</p> : null}
      {titled && planTitle ? <p className="ls-sub">{t('Plan: {plan}', { plan: planTitle })}</p> : null}
      <label>
        <span>{t('Your name')}</span>
        <input name="name" required maxLength={80} autoComplete="name" />
      </label>
      <label>
        <span>{t('Phone')}</span>
        <input name="phone" type="tel" inputMode="tel" maxLength={20} autoComplete="tel" />
      </label>
      <label>
        <span>{t('Email (optional if you gave a phone)')}</span>
        <input name="email" type="email" maxLength={254} autoComplete="email" />
      </label>
      {wantsDate ? (
        <label>
          <span>{t('Preferred date')}</span>
          <input name="preferred_date" type="date" min={today} />
        </label>
      ) : null}
      <label>
        <span>{messageHint(t)[p] ?? t('Message')}</span>
        <textarea name="message" rows={4} maxLength={1000} required={p === 'quote_request'} />
      </label>
      <label className="ls-hp" aria-hidden="true">
        <span>Leave this empty</span>
        <input name="website" tabIndex={-1} autoComplete="off" />
      </label>
      <p className="ls-meta">{t('We share your details with {business} only, so they can reply.', { business: businessName })}</p>
      {error ? <p className="ls-offer__error" role="alert">{error}</p> : null}
      <button type="submit" className="ls-btn" disabled={state === 'sending'}>
        {state === 'sending' ? t('Sending…') : t('Send')}
      </button>
    </form>
  )
}
