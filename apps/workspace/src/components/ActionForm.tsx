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
  const [state, formAction] = useFormState(action, null)
  const ref = useRef<HTMLFormElement>(null)
  useEffect(() => {
    if (state?.ok && resetOnSuccess) ref.current?.reset()
  }, [state, resetOnSuccess])
  return (
    <form ref={ref} action={formAction} className={className} style={style} aria-label={label}>
      {children}
      {state && !state.ok ? <p className="bos-error ws-form__msg" role="alert">{state.message}</p> : null}
      {state?.ok && success ? <p className="bos-status ws-form__msg" role="status">{success}</p> : null}
    </form>
  )
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
