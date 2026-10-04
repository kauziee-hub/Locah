import Link from 'next/link'
import type { CSSProperties, ReactNode } from 'react'
import type { ApiError } from '@/lib/api'

/* ========================================================================
   Workspace shared UI (Frontend Design Work Order, Prompt B).
   Server-component safe — no hooks, no "use client". Motion lives in CSS.
   ======================================================================== */

/* ---------------------------------------------------------------- StatusPill
   One component, one colour map, used everywhere. Label always as text — the
   colour never carries meaning alone. */

type Tone = 'good' | 'warn' | 'bad' | 'neutral' | 'info'

const STATUS_TONE: Record<string, Tone> = {
  // good
  active: 'good', ready: 'good', succeeded: 'good', paid: 'good', completed: 'good',
  confirmed: 'good', delivered: 'good', published: 'good', won: 'good', enabled: 'good',
  in_stock: 'good', in_good_standing: 'good', fulfilled: 'good', open: 'good',
  // warn
  pending: 'warn', preparing: 'warn', processing: 'warn', partial: 'warn', low_stock: 'warn',
  awaiting: 'warn', unconfirmed: 'warn', draft: 'warn', changes_pending: 'warn',
  under_review: 'warn', past_due: 'warn', reserved: 'warn',
  pending_offline: 'warn', partially_refunded: 'warn', partially_paid: 'warn',
  // bad
  failed: 'bad', cancelled: 'bad', canceled: 'bad', rejected: 'bad', lost: 'bad',
  suspended: 'bad', expired: 'bad', out_of_stock: 'bad', blocked: 'bad', overdue: 'bad',
  refunded: 'bad', invalid_credentials: 'bad', declined: 'bad', error: 'bad',
  // neutral
  archived: 'neutral', inactive: 'neutral', not_active: 'neutral', unpublished: 'neutral',
  closed: 'neutral', paused: 'neutral', not_connected: 'neutral', new: 'info',
  contacted: 'info', qualified: 'info', accepted: 'info', scheduled: 'info',
}

const TONE_VARS: Record<Tone, CSSProperties> = {
  good: { color: 'var(--status-good-fg)', background: 'var(--status-good-bg)', borderColor: 'var(--status-good-bd)' },
  warn: { color: 'var(--status-warn-fg)', background: 'var(--status-warn-bg)', borderColor: 'var(--status-warn-bd)' },
  bad: { color: 'var(--status-bad-fg)', background: 'var(--status-bad-bg)', borderColor: 'var(--status-bad-bd)' },
  neutral: { color: 'var(--status-neutral-fg)', background: 'var(--status-neutral-bg)', borderColor: 'var(--status-neutral-bd)' },
  info: { color: 'var(--status-info-fg)', background: 'var(--status-info-bg)', borderColor: 'var(--status-info-bd)' },
}

export function StatusPill({ value, tone, label: shown }: { value: string; tone?: Tone; label?: string }) {
  const key = String(value || '').toLowerCase().replace(/[\s-]+/g, '_')
  const resolved = tone ?? STATUS_TONE[key] ?? 'neutral'
  // `label`: the words to show (e.g. in the person's language); the tone still follows the stored value.
  const label = shown ?? String(value || '—').replace(/_/g, ' ')
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.3rem',
        border: '1px solid',
        borderRadius: '999px',
        padding: '0.1rem 0.55rem',
        fontSize: '0.78rem',
        fontWeight: 500,
        lineHeight: 1.6,
        whiteSpace: 'nowrap',
        // Given words are shown as written; a raw stored value is tidied.
        textTransform: shown ? 'none' : 'capitalize',
        ...TONE_VARS[resolved],
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: 'currentColor',
          flex: 'none',
        }}
      />
      {label}
    </span>
  )
}

/* ---------------------------------------------------------------- Card */

export function Card({
  children,
  interactive,
  tone,
  style,
}: {
  children: ReactNode
  interactive?: boolean
  tone?: 'default' | 'urgent' | 'danger'
  style?: CSSProperties
}) {
  const border =
    tone === 'urgent'
      ? 'var(--status-warn-bd)'
      : tone === 'danger'
        ? 'var(--status-bad-bd)'
        : 'var(--color-border)'
  return (
    <div
      className={interactive ? 'ws-card ws-card--interactive' : 'ws-card'}
      style={{
        background: tone === 'danger' ? 'var(--status-bad-bg)' : 'var(--color-surface)',
        border: `1px solid ${border}`,
        borderRadius: 'var(--radius)',
        boxShadow: 'var(--shadow-card)',
        padding: '1rem 1.1rem',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/* ---------------------------------------------------------------- PageHeader */

export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumb,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  breadcrumb?: ReactNode
}) {
  return (
    <header className="ws-page-header" style={{ marginBottom: '1.5rem' }}>
      {breadcrumb ? (
        <div style={{ fontSize: '0.82rem', color: 'var(--color-muted)', marginBottom: '0.5rem' }}>
          {breadcrumb}
        </div>
      ) : null}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1>{title}</h1>
          {subtitle ? (
            <p style={{ color: 'var(--color-muted)', margin: '0.3rem 0 0', maxWidth: '46rem' }}>
              {subtitle}
            </p>
          ) : null}
        </div>
        {actions ? <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>{actions}</div> : null}
      </div>
    </header>
  )
}

/* ---------------------------------------------------------------- FilterTabs */

export function FilterTabs({
  options,
  current,
  hrefFor,
}: {
  options: { value: string; label: string; count?: number }[]
  current: string | undefined
  hrefFor: (value: string) => string
}) {
  return (
    <nav
      style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', margin: '0 0 1.1rem' }}
      aria-label="Filter"
    >
      {options.map((o) => {
        const active = (current ?? '') === o.value
        return (
          <Link
            key={o.value || 'all'}
            href={hrefFor(o.value)}
            aria-current={active ? 'page' : undefined}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              padding: '0.35rem 0.7rem',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.85rem',
              textDecoration: 'none',
              border: `1px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
              background: active ? 'var(--color-primary)' : 'var(--color-surface)',
              color: active ? 'var(--color-primary-fg)' : 'var(--color-foreground)',
            }}
          >
            {o.label}
            {typeof o.count === 'number' ? (
              <span style={{ fontVariantNumeric: 'tabular-nums', opacity: 0.8 }}>{o.count}</span>
            ) : null}
          </Link>
        )
      })}
    </nav>
  )
}

/* ---------------------------------------------------------------- EmptyState */

export function EmptyState({
  title,
  children,
  action,
}: {
  title?: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div
      className="ws-empty"
      style={{
        border: '1px dashed var(--color-border-strong)',
        borderRadius: 'var(--radius)',
        padding: '2rem 1.5rem',
        textAlign: 'center',
        background: 'var(--color-surface)',
      }}
    >
      {title ? <h3 style={{ marginBottom: '0.35rem' }}>{title}</h3> : null}
      {children ? (
        <p style={{ color: 'var(--color-muted)', maxWidth: '32rem', margin: '0 auto' }}>{children}</p>
      ) : null}
      {action ? <div style={{ marginTop: '1rem' }}>{action}</div> : null}
    </div>
  )
}

/* ---------------------------------------------------------------- DataTable
   One table for every list page. Column alignment by declared type; sticky
   header; empty / loading / error states built in. */

export type Column<T> = {
  key: string
  header: string
  align?: 'text' | 'num'
  width?: string
  render: (row: T) => ReactNode
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty,
  loading,
  error,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  empty?: ReactNode
  loading?: boolean
  error?: ReactNode
}) {
  if (error) return <>{error}</>
  return (
    <div
      className="ws-datatable"
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius)',
        overflow: 'hidden',
        background: 'var(--color-surface)',
      }}
    >
      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} data-num={c.align === 'num' || undefined} style={{ width: c.width }}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    {columns.map((c) => (
                      <td key={c.key} data-num={c.align === 'num' || undefined}>
                        <span
                          className="ws-skeleton"
                          style={{ display: 'block', height: 12, width: c.align === 'num' ? 48 : '70%' }}
                        />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((row) => (
                  <tr key={rowKey(row)}>
                    {columns.map((c) => (
                      // data-label: on a phone each row becomes a card that names its fields.
                      <td key={c.key} data-num={c.align === 'num' || undefined}
                          data-label={typeof c.header === 'string' && c.header ? c.header : undefined}>
                        {c.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
      {!loading && rows.length === 0 ? (
        <div style={{ padding: '1.5rem', borderTop: '1px solid var(--color-border)' }}>
          {empty ?? <p style={{ color: 'var(--color-muted)', margin: 0 }}>Nothing here yet.</p>}
        </div>
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------------- DetailShell
   One shell for every detail page so Orders / Bookings / Leads read as one
   product. */

export function DetailShell({
  breadcrumb,
  title,
  status,
  meta,
  actions,
  children,
}: {
  breadcrumb?: ReactNode
  title: string
  status?: ReactNode
  meta?: [string, ReactNode][]
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <div>
      <PageHeader
        title={title}
        breadcrumb={breadcrumb}
        actions={actions}
      />
      {status || (meta && meta.length) ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '1.25rem',
            flexWrap: 'wrap',
            padding: '0.75rem 1rem',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius)',
            background: 'var(--color-surface)',
            marginBottom: '1.5rem',
          }}
        >
          {status}
          {(meta ?? []).map(([label, val]) => (
            <div key={label} style={{ display: 'grid', gap: '0.1rem' }}>
              <span style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--color-muted)' }}>
                {label}
              </span>
              <span style={{ fontSize: '0.9rem', fontVariantNumeric: 'tabular-nums' }}>{val}</span>
            </div>
          ))}
        </div>
      ) : null}
      {children}
    </div>
  )
}

/* ---------------------------------------------------------------- Section */

export function Section({ title, children, style, id }: { title?: string; children: ReactNode; style?: CSSProperties; id?: string }) {
  return (
    <section className="ws-section" id={id} style={{ marginTop: '1.5rem', ...style }}>
      {title ? <h2 style={{ marginBottom: '0.75rem' }}>{title}</h2> : null}
      {children}
    </section>
  )
}

/* ---------------------------------------------------------------- Skeleton */

export function Skeleton({ w = '100%', h = 14, style }: { w?: string | number; h?: number; style?: CSSProperties }) {
  return <span className="ws-skeleton" style={{ display: 'block', width: w, height: h, ...style }} />
}

/* ---------------------------------------------------------------- GateNotice
   Truthful rendering of a gate failure (Doc 12 §8.9 gates [6]/[7]/[8]).
   Logic unchanged — each gate keeps its distinct code and distinct recovery.
   Launch-readiness requirement, restyled only. */


export function GateNotice({
  error,
  businessId,
  moduleLabel,
}: {
  error: ApiError
  businessId: string
  moduleLabel: string
}) {
  const base = `/b/${businessId}`
  const shell = (heading: string, body: string, href: string, cta: string) => (
    <Card style={{ maxWidth: '44rem' }}>
      <h2 style={{ marginBottom: '0.4rem' }}>{heading}</h2>
      <p style={{ color: 'var(--color-muted)' }}>{body}</p>
      <Link href={href} className="btn btn-ghost" style={{ marginTop: '0.9rem' }}>
        {cta}
      </Link>
    </Card>
  )
  // Straight to that tool's setup page when the gate says which tool it is.
  const setup = error.moduleId ? `${base}/modules/${error.moduleId}` : `${base}/modules`
  if (error.code === 'MODULE_NOT_ACTIVE') {
    return shell(
      `${moduleLabel} is switched off`,
      `Turn ${moduleLabel} on to use these pages. The setup page shows what it adds for your customers and the few steps before it's ready — nothing you've saved is lost while it's off.`,
      setup,
      `Set up ${moduleLabel}`
    )
  }
  if (error.code === 'ENTITLEMENT_REQUIRED') {
    return shell(
      `${moduleLabel} isn't in your plan`,
      `Your current plan doesn't include ${moduleLabel}. See what it does and what it needs.`,
      setup,
      `About ${moduleLabel}`
    )
  }
  if (error.code === 'PERMISSION_DENIED') {
    return shell(
      `You do not have access to ${moduleLabel}`,
      `${moduleLabel} is active for this business, but your role does not include permission to view it. An owner or manager can grant access from Team.`,
      `${base}/team`,
      'Open Team'
    )
  }
  return (
    <Card tone="danger" style={{ maxWidth: '44rem' }}>
      <h2 style={{ marginBottom: '0.4rem' }}>{moduleLabel} could not be loaded</h2>
      <p style={{ color: 'var(--status-bad-fg)' }}>{error.message}</p>
      <p style={{ fontSize: '0.8rem', color: 'var(--color-muted)', margin: 0 }}>Reference: {error.code}</p>
    </Card>
  )
}
