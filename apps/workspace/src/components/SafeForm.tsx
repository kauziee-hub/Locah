'use client'

import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { useFormState, useFormStatus } from 'react-dom'

type Answer = { ok: true; data?: unknown } | { ok: false; message: string } | null | undefined | void

/**
 * A form for a server action that takes only the form data — `(formData) =>
 * …` — and answers with `{ ok, message }` (or nothing when it redirects or has
 * nothing to say). The API's reason shows under the form instead of the error
 * screen; the fields are disabled while it runs; an optional note confirms it
 * worked. For actions written as `(previous, formData)`, use ActionForm.
 */
export function SafeForm({
  action,
  children,
  success,
  resetOnSuccess = false,
  className,
  style,
  id,
  encType,
  'aria-label': label,
}: {
  action: (formData: FormData) => Promise<Answer>
  children: ReactNode
  /** Shown after it worked, e.g. "Saved." */
  success?: string
  resetOnSuccess?: boolean
  className?: string
  style?: CSSProperties
  id?: string
  encType?: string
  'aria-label'?: string
}) {
  const [state, formAction] = useFormState(async (_prev: Answer, formData: FormData): Promise<Answer> => {
    const answer = await action(formData)
    return answer ?? { ok: true }
  }, null)
  const ref = useRef<HTMLFormElement>(null)
  useEffect(() => {
    if (state && state.ok && resetOnSuccess) ref.current?.reset()
  }, [state, resetOnSuccess])
  return (
    <form ref={ref} action={formAction} className={className} style={style} id={id} encType={encType} aria-label={label}>
      <Busy>{children}</Busy>
      {state && !state.ok ? <p className="bos-error ws-form__msg" role="alert">{state.message}</p> : null}
      {state && state.ok && success ? <p className="bos-status ws-form__msg" role="status">{success}</p> : null}
    </form>
  )
}

/** Disables the form's fields and buttons while its action runs, without changing its layout. */
function Busy({ children }: { children: ReactNode }) {
  const { pending } = useFormStatus()
  return (
    <fieldset disabled={pending} aria-busy={pending} className="ws-safeform">
      {children}
    </fieldset>
  )
}
