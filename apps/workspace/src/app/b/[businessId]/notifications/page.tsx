import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { EmptyState, GateNotice, PageHeader } from '@/components/ModuleState'
import { markAllRead, markRead, setPreference } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Notification = {
  id: string
  notification_type: string
  category: string
  severity: string
  title: string
  body: string | null
  resource_type: string | null
  resource_id: string | null
  read_at: string | null
  created_at: string
}

type Preference = { category: string; in_app_enabled: boolean }

const CATEGORIES = ['operational', 'commercial', 'access', 'platform']

// Where a notification's "open destination" actually lives in this app.
const DESTINATION: Record<string, string> = {
  order: 'orders',
  booking: 'bookings',
  lead: 'leads',
  invitation: 'team/invitations',
  membership_enrolment: 'memberships',
  payment: 'payments',
  module: 'modules',
}

const SEVERITY_TONE: Record<string, string> = {
  info: 'var(--color-border)',
  warning: 'rgba(138,109,31,0.35)',
  critical: 'rgba(163,51,51,0.4)',
}

/** Doc 09 CORE-015 Notifications. */
export default async function NotificationsPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { category?: string; unread?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const query = new URLSearchParams()
  if (searchParams?.category) query.set('category', searchParams.category)
  if (searchParams?.unread === '1') query.set('unread_only', 'true')
  const qs = query.toString() ? `?${query.toString()}` : ''

  const res = await apiTry<{
    data: Notification[]
    meta: { unread_count: number }
  }>(`/v1/platform/businesses/${params.businessId}/notifications${qs}`, token)
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Notifications" />
        <GateNotice
          error={res.error}
          businessId={params.businessId}
          moduleLabel="Notifications"
        />
      </div>
    )
  }
  const notifications = res.data.data || []
  const unread = res.data.meta?.unread_count ?? 0

  const prefsRes = await apiTry<{ data: Preference[] }>(
    `/v1/platform/businesses/${params.businessId}/notification-preferences`,
    token
  )
  const preferences = prefsRes.ok ? prefsRes.data.data || [] : []
  const base = `/b/${params.businessId}/notifications`

  return (
    <div>
      <PageHeader
        title="Notifications"
        subtitle={unread > 0 ? `${unread} unread` : 'You are all caught up.'}
        action={
          unread > 0 ? (
            <SafeForm action={markAllRead}>
              <input type="hidden" name="businessId" value={params.businessId} />
              <button type="submit" style={BUTTON}>
                Mark all as read
              </button>
            </SafeForm>
          ) : undefined
        }
      />

      <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
        <Link href={base}>All</Link>
        <Link href={`${base}?unread=1`}>Unread</Link>
        {CATEGORIES.map((category) => (
          <Link key={category} href={`${base}?category=${category}`}>
            {category}
          </Link>
        ))}
      </div>

      <div style={{ display: 'grid', gap: '0.6rem' }}>
        {notifications.map((notification) => {
          const destination = notification.resource_type
            ? DESTINATION[notification.resource_type]
            : undefined
          const href =
            destination && notification.resource_id
              ? `/b/${params.businessId}/${destination}/${notification.resource_id}`
              : destination
                ? `/b/${params.businessId}/${destination}`
                : undefined
          return (
            <article
              key={notification.id}
              style={{
                padding: '0.9rem 1.1rem',
                borderRadius: '10px',
                border: `1px solid ${SEVERITY_TONE[notification.severity] ?? SEVERITY_TONE.info}`,
                background: notification.read_at
                  ? 'var(--color-surface)'
                  : 'var(--color-surface)',
                display: 'flex',
                justifyContent: 'space-between',
                gap: '1rem',
                flexWrap: 'wrap',
              }}
            >
              <div>
                <div style={{ fontWeight: notification.read_at ? 400 : 700 }}>
                  {notification.title}
                </div>
                {notification.body ? (
                  <div style={{ opacity: 0.85 }}>{notification.body}</div>
                ) : null}
                <div style={{ opacity: 0.6, fontSize: '0.85rem', marginTop: '0.25rem' }}>
                  {notification.category} · {new Date(notification.created_at).toLocaleString()}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                {href ? <Link href={href}>Open</Link> : null}
                {notification.read_at ? null : (
                  <SafeForm action={markRead}>
                    <input type="hidden" name="businessId" value={params.businessId} />
                    <input type="hidden" name="notificationId" value={notification.id} />
                    <button type="submit" style={LINK_BUTTON}>
                      Mark read
                    </button>
                  </SafeForm>
                )}
              </div>
            </article>
          )
        })}
      </div>
      {notifications.length === 0 ? (
        <EmptyState>
          Nothing here. Notifications arrive when something happens that you can act on — a new
          order, a booking, an invitation.
        </EmptyState>
      ) : null}

      <section style={{ marginTop: '2.25rem', maxWidth: '32rem' }}>
        <h2 >What you get notified about</h2>
        {preferences.map((preference) => (
          <SafeForm
            key={preference.category}
            action={setPreference}
            style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.5rem' }}
          >
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="category" value={preference.category} />
            <label style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', minWidth: '12rem' }}>
              <input
                type="checkbox"
                name="in_app_enabled"
                defaultChecked={preference.in_app_enabled}
              />
              {preference.category}
            </label>
            <button type="submit" style={LINK_BUTTON}>
              Save
            </button>
          </SafeForm>
        ))}
      </section>
    </div>
  )
}

const BUTTON: React.CSSProperties = {
  justifySelf: 'start',
}
const LINK_BUTTON: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: 'var(--color-primary)',
  cursor: 'pointer',
  font: 'inherit',
  fontWeight: 500,
  padding: 0,
  minHeight: 'auto',
  textDecoration: 'underline',
}
