import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { Card, PageHeader } from '@/components/ui'
import { RecommendedTools, type ForYou } from '@/components/RecommendedTools'
import { pageWords } from '@/lib/ws-lang'

export const dynamic = 'force-dynamic'

type Business = { display_name: string; state: string; status: string; visibility: string }

type Item = { label: string; count: number; href: string; detail: string; tone: string }
type Stat = { label: string; value: string; href: string; note: string }
type Band = { key: string; title: string; items?: Item[]; stats?: Stat[]; empty: string }
type Header = {
  greeting: string
  name: string
  place: string
  location_id: string | null
  open: { state: 'open' | 'closed' | 'unknown'; text: string }
  website: boolean
}
type Home = {
  role: { key: string; label: string; question: string }
  location_scoped: boolean
  header: Header
  quick_actions: { label: string; href: string }[]
  bands: Band[]
}

/**
 * Workspace Home (Business OS Guide §3: "Home should answer a question, not
 * display random cards"; Build Spec §8). The API composes the bands for the
 * viewer's role from real records within their permissions and locations;
 * this page lays them out and links every row to the records behind it.
 */
export default async function WorkspaceHomePage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const t = pageWords()
  const base = `/b/${params.businessId}`
  const [homeRes, businessRes, ctxRes] = await Promise.all([
    apiTry<{ data: Home }>(`/v1/platform/businesses/${params.businessId}/home`, token),
    apiTry<{ data: Business }>(`/v1/b/${params.businessId}`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(params.businessId)),
  ])
  const canEnable = ctxRes.ok && ctxRes.data.data.permissions.includes('modules.enable')
  const business = businessRes.ok ? businessRes.data.data : null

  if (business && business.status && business.status !== 'in_good_standing') {
    const suspended = business.status === 'suspended'
    return (
      <div>
        <PageHeader title={business.display_name} />
        <Card tone="danger" style={{ maxWidth: '46rem' }}>
          <h2 style={{ marginBottom: '0.4rem' }}>
            {suspended ? t('This business is suspended') : t('This business is under review')}
          </h2>
          <p style={{ color: 'var(--status-bad-fg)' }}>
            {suspended
              ? t('New orders, bookings and payments are not being accepted right now. Your data is safe and nothing has been deleted.')
              : t('Your account is being reviewed. Everything keeps working normally while that happens.')}
          </p>
          <p style={{ color: 'var(--color-muted)' }}>{t('Contact support to resolve this. They can tell you exactly what is needed.')}</p>
        </Card>
      </div>
    )
  }

  if (!homeRes.ok) {
    return (
      <div>
        <PageHeader title={business?.display_name ?? t('Workspace')} />
        <Card style={{ maxWidth: '40rem' }}>
          <p>{t('Your home could not load just now. Refresh the page to try again.')}</p>
        </Card>
      </div>
    )
  }

  const home = homeRes.data.data
  const isOwner = home.role.key === 'owner'
  // The two best next tools, for whoever can switch tools on.
  const forYouRes = canEnable
    ? await apiTry<{ data: ForYou }>(
        `/v1/platform/businesses/${params.businessId}/module-recommendations/for-you?limit=2`, token)
    : null
  const forYou = forYouRes?.ok ? forYouRes.data.data : null
  const h = home.header
  const href = (path: string) => (path.startsWith('~') ? `${path.slice(1)}/${params.businessId}` : `${base}${path}`)
  const attention = home.bands.find((b) => b.key === 'now' || b.key === 'late')
  const waiting = attention?.items?.reduce((n, i) => n + (i.count || 0), 0) ?? 0
  const subtitle = isOwner
    ? waiting > 0
      ? waiting === 1 ? t('1 thing needs you.') : t('{n} things need you.', { n: waiting })
      : t('Nothing needs you right now.')
    : `${t(home.role.label)} · ${t(home.role.question)}`

  return (
    <div className="bos-home">
      <header className="bos-hello">
        <h1 className="bos-hello__title">
          {t(h.greeting)}, <span>{h.name}</span>
        </h1>
        <p className="bos-hello__meta">
          {h.place ? <span>{h.place}</span> : null}
          {h.open.state === 'unknown' ? (
            canEnable ? (
              <Link className="bos-hello__chip" href={h.location_id ? `${base}/locations/${h.location_id}#hours-h` : `${base}/locations`}>{t('Add your opening hours')}</Link>
            ) : null
          ) : (
            <span className={`bos-hello__chip is-${h.open.state}`}>{t(h.open.text)}</span>
          )}
          <Link className={`bos-hello__chip${h.website ? ' is-open' : ''}`} href={`${base}/website`}>
            {h.website ? t('Website live') : t('Website not published')}
          </Link>
        </p>
        {/* The "Needs you now" band says so itself when nothing is waiting. */}
        {!isOwner || waiting > 0 ? <p className="bos-hello__sub">{subtitle}</p> : null}
      </header>
      {home.location_scoped ? (
        <p className="bos-hint">{t('Showing your locations only.')}</p>
      ) : null}
      {home.quick_actions.length > 0 ? (
        <nav className="bos-quick" aria-label={t('Quick actions')}>
          {home.quick_actions.map((a, i) => (
            <Link key={a.href} href={href(a.href)} className={i === 0 ? 'btn' : 'btn btn-ghost'}>
              {t(a.label)}
            </Link>
          ))}
        </nav>
      ) : null}
      {home.bands.map((band) => (
        <section key={band.key} className={`bos-band bos-band--${band.key}`} aria-labelledby={`band-${band.key}`}>
          <h2 className="bos-section__title" id={`band-${band.key}`}>{t(band.title)}</h2>
          {band.stats ? (
            <div className="ws-stats">
              {band.stats.map((s) => (
                <Link key={s.label} href={href(s.href)} className="ws-stat bos-stat-link">
                  <p className="ws-stat__label">{t(s.label)}</p>
                  <p className="ws-stat__value">{t(s.value)}</p>
                  {s.note ? <p className="ws-stat__note">{t(s.note)}</p> : null}
                </Link>
              ))}
            </div>
          ) : null}
          {band.key === 'today' ? (
            <p className="bos-band__more"><Link href={`${base}/insights?period=7d`}>{t('Your numbers for the week and month')} →</Link></p>
          ) : null}
          {band.stats ? null : band.items && band.items.length > 0 ? (
            <ul className="bos-attention">
              {band.items.map((i) => (
                <li key={`${i.label}-${i.href}`}>
                  <Link href={href(i.href)} className={`bos-attention__row is-${i.tone}`}>
                    {band.key === 'business' || band.key === 'myday' || band.key === 'followups' ? (
                      <span className="bos-attention__dot" aria-hidden />
                    ) : (
                      <span className="bos-attention__count">{i.count}</span>
                    )}
                    <span className="bos-attention__text">
                      <strong>{t(i.label)}</strong>
                      {i.detail ? <span>{t(i.detail)}</span> : null}
                    </span>
                    <span className="bos-attention__go" aria-hidden>→</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="bos-empty">{t(band.empty)}</div>
          )}
        </section>
      ))}
      {forYou && forYou.recommended.length > 0 ? (
        <section className="bos-band bos-band--recs" aria-labelledby="band-recs">
          <h2 className="bos-section__title" id="band-recs">{t('Recommended for your Business')}</h2>
          <RecommendedTools businessId={params.businessId} data={forYou} canEnable={canEnable} compact />
          {forYou.total > forYou.recommended.length ? (
            <p className="bos-band__more">
              <Link href={`${base}/modules`}>{t('All suggestions')} ({forYou.total}) →</Link>
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
