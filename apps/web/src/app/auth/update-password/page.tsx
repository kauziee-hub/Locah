import type { Metadata } from 'next'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { UpdatePasswordForm } from './UpdatePasswordForm'

export const metadata: Metadata = {
  title: 'Choose a new password — LOCAH',
  robots: { index: false, follow: false },
}

export const dynamic = 'force-dynamic'

/**
 * Where a password-reset link lands (`/auth/confirm` sends `type=recovery`
 * here). The link has just signed the person in; this is the only place the
 * new password is set. Without a session there is nothing to change, so the
 * person is sent to sign in — an email code works without a password at all.
 */
export default async function UpdatePasswordPage() {
  if (!(await getAccessToken())) redirect('/login')
  return <UpdatePasswordForm />
}
