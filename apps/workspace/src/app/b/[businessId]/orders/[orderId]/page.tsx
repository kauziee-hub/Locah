import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DetailShell, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { cancelOrder, setOrderStatus } from '../actions'
import { ActionButton } from '@/components/ActionButton'
import { OrderBill } from './OrderBill'
import { MoneySection } from '@/components/MoneySection'
import { money, paymentLabel } from '../labels'
import { LocalTime } from '@/components/LocalTime'
import { ChangeOrder } from './ChangeOrder'
import type { CatalogueItem } from '../ItemPicker'
import { pageWords } from '@/lib/ws-lang'
import type { Words } from '@/lib/ws-words'
import { StageTrack, type StageWhere } from '@/components/StageTrack'

export const dynamic = 'force-dynamic'

/** What each button does, in words (the stored states never reach the screen). */
const actionWords = (t: Words): Record<string, string> => ({
  accepted: t('Accept'),
  rejected: t('Reject'),
  preparing: t('Start preparing'),
  ready: t('Mark ready'),
  completed: t('Complete'),
})
const statusWords = (t: Words): Record<string, string> => ({
  pending: t('New'), accepted: t('Accepted'), preparing: t('Preparing'), ready: t('Ready'),
  completed: t('Completed'), cancelled: t('Cancelled'), rejected: t('Declined'),
})

/** Doc 11 §4.2 order detail — state actions, cancel coordination. */
export default async function OrderDetailPage({
  params,
}: {
  params: { businessId: string; orderId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const t = pageWords()
  const ACTION_WORDS = actionWords(t)
  const base = `/b/${params.businessId}`
  const res = await apiTry<{
    data: {
      id: string
      order_number: string
      status: string
      payment_status: string
      payment_method: string
      total_amount: number
      subtotal: number
      tax_amount: number
      discount_amount: number
      round_off: number
      tax_basis: { engine?: string; inclusive?: boolean; intra_state?: boolean; scheme?: string; rates_missing?: string[] }
      due_at?: string | null
      advance_amount?: number | null
      preorder_terms?: { cancel_hours?: number | null }
      currency: string
      version: number
      items?: Array<{ id: string; title: string; quantity: number; line_total: number; basis_words?: string | null }>
      customer?: { id: string; name: string; phone: string | null } | null
      fulfilment?: { mode: string; status: string; address: string | null; phone: string | null } | null
    }
  }>(`/v1/platform/businesses/${params.businessId}/orders/${params.orderId}`, token)
  const stage = await apiTry<{ data: StageWhere }>(`/v1/b/${params.businessId}/stages/orders/${params.orderId}`, token)
  const bills = await apiTry<{ data: Array<{ id: string; number: string | null; kind_label: string; status: string; doc_kind: string }> }>(
    `/v1/platform/businesses/${params.businessId}/invoices?order_id=${params.orderId}&kind=invoices`, token)
  if (!res.ok) {
    return (
      <div>
        <PageHeader title={t('Order')} breadcrumb={<Link href={`${base}/orders`}>← {t('Orders')}</Link>} />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel={t('Orders')} />
      </div>
    )
  }
  const order = res.data.data
  const nextByStatus: Record<string, string[]> = {
    pending: ['accepted', 'rejected'],
    accepted: ['preparing'],
    preparing: ['ready'],
    ready: ['completed'],
  }
  const next = nextByStatus[order.status] || []
  const billed = bills.ok && bills.data.data.some((x) => x.status === 'issued')
  const changeable = ['pending', 'accepted', 'preparing'].includes(order.status) && !billed
  const catalogue = changeable
    ? await apiTry<{ data: (CatalogueItem & { status: string })[] }>(`/v1/platform/businesses/${params.businessId}/products?status=active`, token)
    : null
  const cancellable = ['pending', 'accepted', 'preparing', 'ready'].includes(order.status)

  const actions = (
    <>
      {next.map((status) => (
        <ActionButton key={status} label={ACTION_WORDS[status] || status} busyLabel={t('Saving…')}
          className={status === 'rejected' ? 'btn-danger' : undefined}
          confirm={status === 'rejected' ? t('Turn down order {number}? The customer is told.', { number: order.order_number }) : undefined}
          run={setOrderStatus.bind(null, params.businessId, params.orderId, status,
            status === 'rejected' ? 'Rejected by Business' : undefined)} />
      ))}
      {cancellable ? (
        <ActionButton className="btn-ghost" label={t('Cancel order')} busyLabel={t('Saving…')} confirmLabel={t('Yes, cancel it')}
          confirm={t('Cancel order {number}? The customer is told, and any money paid will need a refund.', { number: order.order_number })}
          run={cancelOrder.bind(null, params.businessId, params.orderId, 'Cancelled from Workspace')} />
      ) : null}
    </>
  )
  const customer = order.customer
  const reach = order.fulfilment

  return (
    <DetailShell
      breadcrumb={<Link href={`${base}/orders`}>← {t('Orders')}</Link>}
      title={order.order_number}
      status={<StatusPill value={order.status} label={statusWords(t)[order.status]} />}
      meta={[
        [t('Payment'), paymentLabel(order, t)],
        [t('Total'), money(Number(order.total_amount) || 0, order.currency)],
        ...(customer ? [[t('Customer'), (
          <span key="customer">
            <Link href={`${base}/customers/${customer.id}`}>{customer.name}</Link>
            {customer.phone ? <> · <a href={`tel:${customer.phone.replace(/[^+\d]/g, '')}`}>{customer.phone}</a></> : null}
          </span>
        )] as [string, React.ReactNode]] : []),
        ...(reach ? [[reach.mode === 'delivery' ? t('Delivery to') : t('Pickup'), (
          <span key="reach">{reach.mode === 'delivery' ? (reach.address || t('Address not given')) : t('Customer collects it')}</span>
        )] as [string, React.ReactNode]] : []),
        ...(order.due_at ? [[t('Wanted for'), <LocalTime key="due" value={order.due_at} />] as [string, React.ReactNode]] : []),
        ...(order.advance_amount ? [[t('Advance asked'), money(Number(order.advance_amount), order.currency)] as [string, React.ReactNode]] : []),
      ]}
      actions={next.length || cancellable ? actions : undefined}
    >
      {stage.ok && stage.data.data.has_steps ? (
        <Section title={t('Steps')}>
          <StageTrack businessId={params.businessId} entity="orders" recordId={params.orderId} where={stage.data.data} />
        </Section>
      ) : null}
      <Section title={t('Items')}>
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius)',
            overflow: 'hidden',
            background: 'var(--color-surface)',
          }}
        >
          <div className="ws-tablewrap">
            <table>
              <thead>
                <tr>
                  <th>{t('Item')}</th>
                  <th data-num>{t('Qty')}</th>
                  <th data-num>{t('Line total')}</th>
                </tr>
              </thead>
              <tbody>
                {(order.items || []).map((item, idx) => (
                  <tr key={idx}>
                    <td>
                      {item.title}
                      {item.basis_words ? <small className="bos-line-basis">{item.basis_words}</small> : null}
                    </td>
                    <td data-num>{item.quantity}</td>
                    <td data-num>{money(Number(item.line_total) || 0, order.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(order.items || []).length === 0 ? (
            <p style={{ padding: '1rem', color: 'var(--color-muted)', margin: 0 }}>
              {t('No line items on this order.')}
            </p>
          ) : null}
        </div>
      </Section>

      {changeable ? (
        <ChangeOrder businessId={params.businessId} orderId={params.orderId} version={order.version}
          lines={(order.items || []).filter((i) => i.title !== 'Delivery fee').map((i) => ({ id: i.id, title: i.title, quantity: i.quantity }))}
          items={catalogue && catalogue.ok ? catalogue.data.data.filter((o) => o.status === 'active' && o.title !== 'Delivery fee') : []} />
      ) : null}

      {order.tax_basis?.engine ? (
        <dl className="bos-inv-ordertax">
          <dt>{t('Before tax')}</dt><dd>{money(Number(order.subtotal) || 0, order.currency)}</dd>
          {order.discount_amount ? (<><dt>{t('Discount')}</dt><dd>− {money(Number(order.discount_amount) || 0, order.currency)}</dd></>) : null}
          <dt>{order.tax_basis.scheme !== 'regular' ? t('Tax') : order.tax_basis.intra_state ? 'CGST + SGST' : 'IGST'}</dt>
          <dd>{money(Number(order.tax_amount) || 0, order.currency)}{order.tax_basis.inclusive ? ` ${t('(included in prices)')}` : ''}</dd>
          {order.round_off ? (<><dt>{t('Round-off')}</dt><dd>{money(Number(order.round_off) || 0, order.currency)}</dd></>) : null}
          <dt>{t('Total')}</dt><dd>{money(Number(order.total_amount) || 0, order.currency)}</dd>
        </dl>
      ) : null}
      {order.tax_basis?.rates_missing?.length ? (
        <p className="bos-inv-warn">{t('No GST rate yet for: {items}. Add it in Tax rates before billing.', { items: order.tax_basis.rates_missing.join(', ') })}</p>
      ) : null}

      {bills.ok ? (
        <Section title={t('Bill')}>
          <OrderBill
            businessId={params.businessId}
            orderId={params.orderId}
            cancelled={['cancelled', 'rejected'].includes(order.status)}
            live={bills.data.data.find((x) => x.status !== 'cancelled') ?? null}
          />
        </Section>
      ) : null}

      <MoneySection businessId={params.businessId} token={token} sourceType="order" sourceId={params.orderId}
        path={`${base}/orders/${params.orderId}`} />
    </DetailShell>
  )
}
