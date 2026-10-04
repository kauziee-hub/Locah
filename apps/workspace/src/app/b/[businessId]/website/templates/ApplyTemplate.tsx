'use client'

import { useState } from 'react'
import { applyTemplate } from './actions'
import { SafeForm } from '@/components/SafeForm'
import { SubmitButton } from '@/components/ActionForm'

/**
 * Choosing a template, with the consequence stated before it happens.
 *
 * Applying replaces the current draft — that is the honest meaning of "use this
 * one instead", and it is not something to discover afterwards. So the first
 * click asks, and only the second one does it. A business that has never
 * published has nothing to lose and is told so; one that has published is told
 * its live site is untouched until it publishes again, because that is the
 * thing they would actually worry about.
 *
 * A generated site names the template it was personalised from, and that is a
 * different situation again: the shape came from here, but every word in it was
 * written for this business. Re-applying the template would swap that back for
 * the plain starting copy, which is a loss worth spelling out — it is the one
 * case where choosing "the one you are already on" is destructive.
 */
export function ApplyTemplate({
  businessId,
  templateId,
  templateName,
  relationship,
  hasDraftWork,
  disabled,
  disabledReason,
}: {
  businessId: string
  templateId: string
  templateName: string
  relationship: 'applied' | 'generated-from' | 'none'
  hasDraftWork: boolean
  disabled?: boolean
  disabledReason?: string
}) {
  const [confirming, setConfirming] = useState(false)

  if (disabled) {
    return (
      <p className="tpl-locked" role="note">
        {disabledReason}
      </p>
    )
  }

  if (relationship === 'applied') {
    return (
      <p className="tpl-current" role="status">
        You are using this one
      </p>
    )
  }

  if (!confirming) {
    return (
      <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
        {relationship === 'generated-from' ? 'Reset to the plain layout' : 'Use this template'}
      </button>
    )
  }

  return (
    <SafeForm action={applyTemplate} className="tpl-confirm">
      <input type="hidden" name="businessId" value={businessId} />
      <input type="hidden" name="templateId" value={templateId} />
      <p className="tpl-confirm__text">
        {relationship === 'generated-from'
          ? `Your draft was written for your business using this layout. Resetting keeps the layout but replaces that writing with ${templateName}'s starting text. Your live site does not change until you publish.`
          : hasDraftWork
            ? `This replaces your current draft with ${templateName}. Anything you have edited but not published will be lost. Your live site does not change until you publish.`
            : `Start from ${templateName}? You can change everything on it afterwards.`}
      </p>
      <div className="tpl-confirm__row">
        <SubmitButton className="btn" busy="Applying…">
          {relationship === 'generated-from' ? 'Reset to the plain layout' : `Use ${templateName}`}
        </SubmitButton>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setConfirming(false)}
        >
          Keep what I have
        </button>
      </div>
    </SafeForm>
  )
}
