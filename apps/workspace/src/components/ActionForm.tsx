'use client'

import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { useFormState, useFormStatus } from 'react-dom'
import type { FormResult } from '@/lib/form-result'

/**
 * A form whose server action answers instead of throwing: the API's own
 * reason appears under the form when it is refused (never the error screen),
 * an optional note confirms success, and the fields can clear for the next one.
 */
export function ActionForm({
  action,
  children,
  className,
  style,
  success,
  resetOnSuccess = false,
  'aria-label': label,
}: {
  action: (prev: FormResult, formData: FormData) => Promise<FormResult>
  children: ReactNode
  className?: string
  style?: CSSProperties
  /** Shown after it worked, e.g. "Saved." */
  success?: string
  resetOnSuccess?: boolean
  'aria-label'?: string
}) {
  // What was sent, so a late answer never clears what the owner has typed since
  // (owner lab, hotel: "Cottage 2" typed while "Cottage 1" was saving was wiped
  // by Cottage 1's reset, and the stale "Added." said it had been added).
  const sent = useRef('')
  const [state, formAction] = useFormState(async (prev: FormResult, formData: FormData) => {
    sent.current = fields(formData)
    return action(prev, formData)
  }, null)
  const ref = useRef<HTMLFormElement>(null)
  useEffect(() => {
    const form = ref.current
    if (state?.ok && resetOnSuccess && form && fields(new FormData(form)) === sent.current) form.reset()
  }, [state, resetOnSuccess])
  return (
    <form ref={ref} action={formAction} className={className} style={style} aria-label={label}>
      {children}
      <FormMessage state={state} success={success} />
    </form>
  )
}

function fields(data: FormData): string {
  return JSON.stringify([...data.entries()].filter(([, v]) => typeof v === 'string'))
}

/** The last answer — hidden while the next one is on its way, so it never speaks for it. */
function FormMessage({ state, success }: { state: FormResult; success?: string }) {
  const { pending } = useFormStatus()
  if (pending || !state) return null
  if (!state.ok) return <p className="bos-error ws-form__msg" role="alert">{state.message}</p>
  return success ? <p className="bos-status ws-form__msg" role="status">{success}</p> : null
}

/** A submit button that shows it is working while its form's action runs. */
export function SubmitButton({
  children,
  busy = 'Saving…',
  className,
  disabled = false,
}: {
  children: ReactNode
  busy?: string
  className?: string
  /** Not ready to send yet (e.g. a required part is missing). */
  disabled?: boolean
}) {
  const { pending } = useFormStatus()
  return (
    <button type="submit" className={className} disabled={pending || disabled} aria-busy={pending}>
      {pending ? busy : children}
    </button>
  )
}
