import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, FilterTabs, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { advanceOrderStatus } from './actions'
import { CHANNEL, money, paymentLabel } from './labels'
import { pageWords } from '@/lib/ws-lang'
import type { Words } from '@/lib/ws-words'
import { BusinessEmpty } from '@/components/BusinessEmpty'

export const dynamic = 'force-dynamic'

type OrderRow = {
  id: string
  order_number: string
  status: string
  payment_status: string
  payment_method: string
  total_amount: number
  currency: string
  channel?: string | null
  due_at?: string | null
  created_at?: string
}

type Card = {
  id: string
  order_number: string
  status: string
  stage: string | null
  channel: string | null
  due_words: string
  customer: string | null
  mode: string | null
  total: number
  paid: number
  advance: number | null
  advance_state: 'paid' | 'awaited' | null
  items: { title: string; quantity: number; notes: Record<string, string> }[]
}
type Board = {
  buckets: { key: string; label: string; orders: Card[] }[]
  count: number
  preorder_items: number
  today: string
  tomorrow: string
}

/** The next step for an order on the board, in the words the counter uses. */
const next = (t: Words): Record<string, [string, string]> => ({
  pending: ['accepted', t('Accept')],
  accepted: ['preparing', t('Start preparing')],
  preparing: ['ready', t('Mark ready')],
  ready: ['completed', t('Hand over')],
})
const statusWords = (t: Words): Record<string, string> => ({
  pending: t('New'),
  accepted: t('Accepted'),
  preparing: t('Preparing'),
  ready: t('Ready'),
  completed: t('Completed'),
  cancelled: t('Cancelled'),
  rejected: t('Declined'),
})
const emptyWords = (t: Words): Record<string, string> => ({
  overdue: t('Nothing late.'),
  now: t('Nothing due in the next few hours.'),
  today: t('Nothing else wanted today.'),
  tomorrow: t('Nothing wanted tomorrow yet.'),
  later: t('No orders for later days yet.'),
})

/**
 * Orders (Founder refinement — Orders & Customer Transactions): one list for
 * every channel — the channel is a filter, never a separate book. A business
 * that takes orders for a day (cakes, festival boxes, home-kitchen batches)
 * works them by when they are wanted: overdue, prepare now, today, tomorrow,
 * later, with the day's production list one tap away.
 */
export default async function OrdersPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { status?: string; channel?: string; view?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const t = pageWords()
  const NEXT = next(t)
  const STATUS_WORDS = statusWords(t)
  const channel = (c: string) => t(CHANNEL[c] || c)
  const base = `/b/${params.businessId}`
  const boardRes = await apiTry<{ data: Board }>(`/v1/platform/businesses/${params.businessId}/orders/board`, token)
  const board = boardRes.ok ? boardRes.data.data : null
  const takesDated = !!board && (board.count > 0 || board.preorder_items > 0)
  const view = searchParams?.view === 'list' || !takesDated ? 'list' : searchParams?.view === 'board' ? 'board' : 'board'

  const viewTabs = takesDated ? (
    <FilterTabs
      current={view}
      hrefFor={(v) => `${base}/orders?view=${v}`}
      options={[
        { value: 'board', label: t('By day wanted'), count: board?.count },
        { value: 'list', label: t('All orders') },
      ]}
    />
  ) : null

  if (view === 'board' && board) {
    return (
      <div>
        <PageHeader
          title={t('Orders')}
          subtitle={t('Orders for a day, by when they are wanted. Tap the next step as you go.')}
          actions={
            <span className="bos-inv-buttons">
              <Link className="btn" href={`${base}/orders/new`}>{t('Take a phone order')}</Link>
              <Link className="btn btn-ghost" href={`${base}/orders/production?date=${board.today}`}>{t('Today’s production')}</Link>
              <Link className="btn btn-ghost" href={`${base}/orders/production?date=${board.tomorrow}`}>{t('Tomorrow’s production')}</Link>
            </span>
          }
        />
        {viewTabs}
        <div className="bos-board">
          {board.buckets.map((b) => (
            <section key={b.key} className={`bos-board__col bos-board__col--${b.key}`} aria-labelledby={`col-${b.key}`}>
              <h2 id={`col-${b.key}`} className="bos-board__h">
                {t(b.label)} <span className="bos-board__n">{b.orders.length}</span>
              </h2>
              {b.orders.length === 0 ? <p className="bos-hint">{emptyWords(t)[b.key]}</p> : null}
              {b.orders.map((o) => (
                <article key={o.id} className="bos-ordercard">
                  <header className="bos-ordercard__head">
                    <Link href={`${base}/orders/${o.id}`}><strong>{o.order_number}</strong></Link>
                    <span className="bos-ordercard__when">{o.due_words}</span>
                  </header>
                  <p className="bos-ordercard__who">
                    {o.customer || t('Customer')}
                    {o.mode ? ` · ${o.mode === 'delivery' ? t('Delivery') : t('Pickup')}` : ''}
                    {o.channel ? ` · ${channel(o.channel)}` : ''}
                  </p>
                  <ul className="bos-ordercard__items">
                    {o.items.map((it, i) => (
                      <li key={i}>
                        <span>{it.quantity} × {it.title.replace(/\s(?:·|—)\s“[^”]*”/g, '')}</span>
                        {Object.entries(it.notes).map(([label, text]) => (
                          <span key={label} className="bos-ordercard__note">{label}: “{text}”</span>
                        ))}
                      </li>
                    ))}
                  </ul>
                  <footer className="bos-ordercard__foot">
                    <StatusPill value={o.status} label={STATUS_WORDS[o.status] || o.status} />
                    {o.stage ? <span className="bos-state">{o.stage}</span> : null}
                    {o.advance !== null ? (
                      <span className={`bos-state ${o.advance_state === 'paid' ? 'is-ready' : ''}`}>
                        {o.advance_state === 'paid' ? t('Advance paid') : t('Advance {amount} awaited', { amount: money(o.advance, 'INR') })}
                      </span>
                    ) : null}
                    {NEXT[o.status] ? (
                      <form action={advanceOrderStatus}>
                        <input type="hidden" name="businessId" value={params.businessId} />
                        <input type="hidden" name="orderId" value={o.id} />
                        <input type="hidden" name="status" value={NEXT[o.status][0]} />
                        <button type="submit" className="btn-ghost">{NEXT[o.status][1]}</button>
                      </form>
                    ) : null}
                  </footer>
                </article>
              ))}
            </section>
          ))}
        </div>
      </div>
    )
  }

  const qs = new URLSearchParams()
  if (searchParams?.status) qs.set('status', searchParams.status)
  if (searchParams?.channel) qs.set('channel', searchParams.channel)
  const res = await apiTry<{ data: OrderRow[] }>(
    `/v1/platform/businesses/${params.businessId}/orders${qs.toString() ? `?${qs}` : ''}`,
    token
  )
  if (!res.ok) {
    return (
      <div>
        <PageHeader title={t('Orders')} />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel={t('Orders')} />
      </div>
    )
  }
  const orders = res.data.data || []
  const keep = (extra: Record<string, string | undefined>) => {
    const q = new URLSearchParams({ view: 'list' })
    for (const [k, v] of Object.entries({ status: searchParams?.status, channel: searchParams?.channel, ...extra })) {
      if (v) q.set(k, v)
    }
    return `${base}/orders?${q}`
  }

  return (
    <div>
      <PageHeader title={t('Orders')} subtitle={t('Every order, from every channel, in one list. Open one to accept, prepare and complete it.')}
        actions={<Link className="btn" href={`${base}/orders/new`}>{t('Take a phone order')}</Link>} />
      {viewTabs}
      <FilterTabs
        current={searchParams?.status}
        hrefFor={(v) => keep({ status: v || undefined })}
        options={[
          { value: '', label: t('All') },
          { value: 'pending', label: t('New') },
          { value: 'accepted', label: t('Accepted') },
          { value: 'preparing', label: t('Preparing') },
          { value: 'ready', label: t('Ready') },
          { value: 'completed', label: t('Completed') },
          { value: 'cancelled', label: t('Cancelled') },
        ]}
      />
      <FilterTabs
        current={searchParams?.channel}
        hrefFor={(v) => keep({ channel: v || undefined })}
        options={[{ value: '', label: t('Any channel') }, ...Object.keys(CHANNEL).map((value) => ({ value, label: channel(value) }))]}
      />
      <DataTable
        rows={orders}
        rowKey={(o) => o.id}
        columns={[
          {
            key: 'order_number',
            header: t('Order'),
            render: (o) => <Link href={`${base}/orders/${o.id}`}>{o.order_number}</Link>,
          },
          { key: 'status', header: t('Status'), render: (o) => <StatusPill value={o.status} label={STATUS_WORDS[o.status]} /> },
          {
            key: 'channel',
            header: t('From'),
            render: (o) => (o.channel ? <span className="bos-tag">{channel(o.channel)}</span> : '—'),
          },
          {
            key: 'payment',
            header: t('Payment'),
            render: (o) => <span style={{ color: 'var(--color-muted)' }}>{paymentLabel(o, t)}</span>,
          },
          {
            key: 'total',
            header: t('Total'),
            align: 'num',
            render: (o) => money(Number(o.total_amount) || 0, o.currency),
          },
        ]}
        empty={
          searchParams?.status || searchParams?.channel ? (
            <EmptyState title={t('No orders here')}>{t('Nothing matches these filters right now.')}</EmptyState>
          ) : (
            <BusinessEmpty businessId={params.businessId} module="orders" fallbackTitle={t('No orders here')}
                           fallback={t('Orders placed on your website, WhatsApp, the counter or by phone land here.')} />
          )
        }
      />
    </div>
  )
}
