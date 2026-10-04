import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { addSupplier, approveRequirement, prepareRequirement, receiveGoods } from '../supply-actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Home = {
  purchase_orders: Record<string, number>
  bills_due: number
  needs_buying: number
  requisitions: {
    id: string
    explanation: string
    quantity: number
    demand_quantity: number
    usable_on_hand: number
    confirmed_inbound: number
    safety_stock: number
  }[]
  orders: {
    id: string
    reference: string
    status: string
    explanation: string
    ordered_quantity: number
    received_quantity: number
  }[]
  suppliers: { id: string; name: string }[]
}
type Incoming = { lines: { buyer_label: string; item_label: string; quantity: number }[]; totals: Record<string, number> }
type Offering = { id: string; title: string }
type Location = { id: string; name: string; is_primary?: boolean }

export default async function BuyingPage({ params, searchParams }: {
  params: { businessId: string }
  searchParams?: { view?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const view = searchParams?.view === 'incoming' ? 'incoming' : 'buying'
  const home = await apiTry<{ data: Home }>(`/v1/platform/businesses/${b}/buying`, token)
  if (!home.ok) {
    return <div className="bos-page"><PageHeader title="Buying" /><GateNotice error={home.error} businessId={b} moduleLabel="Buying" /></div>
  }
  const board = home.data.data
  const [products, locations] = await Promise.all([
    apiTry<{ data: Offering[] }>(`/v1/platform/businesses/${b}/products`, token),
    apiTry<{ data: Location[] }>(`/v1/platform/businesses/${b}/locations`, token),
  ])
  const offerings = products.ok ? products.data.data : []
  const locs = locations.ok ? locations.data.data : []
  const locationId = locs.find((loc) => loc.is_primary)?.id ?? locs[0]?.id ?? ''
  const incoming = view === 'incoming'
    ? await apiTry<{ data: Incoming }>(`/v1/platform/businesses/${b}/buying/incoming`, token)
    : null
  const counts = board.purchase_orders
  const waiting = (counts.sent ?? 0) + (counts.acknowledged ?? 0) + (counts.countered ?? 0)
  const arriving = board.orders.filter((order) => order.status === 'dispatched' || (Number(order.received_quantity) > 0 && Number(order.received_quantity) < Number(order.ordered_quantity)))

  return (
    <div className="bos-page">
      <PageHeader title="Buying" subtitle="What to buy, why that quantity, and what has actually arrived." />
      <nav className="bos-stock-tabs" aria-label="Buying views">
        <Link href={`/b/${b}/buying`} aria-current={view === 'buying' ? 'page' : undefined}>Needs buying</Link>
        <Link href={`/b/${b}/buying?view=incoming`} aria-current={view === 'incoming' ? 'page' : undefined}>Incoming demand</Link>
      </nav>
      {view === 'buying' ? (
        <>
          <div className="bos-review-summary">
            <div><span>Needs buying</span><strong>{board.needs_buying}</strong><small>Requirements not yet approved</small></div>
            <div><span>Needs approval</span><strong>{counts.draft ?? 0}</strong><small>Draft purchase orders</small></div>
            <div><span>Waiting on supplier</span><strong>{waiting}</strong><small>Sent, countered, or acknowledged</small></div>
            <div><span>Arriving</span><strong>{arriving.length}</strong><small>Partly received</small></div>
            <div><span>Bills due</span><strong>{board.bills_due}</strong><small>Open supplier bills</small></div>
          </div>
          <SafeForm action={addSupplier} className="bos-form">
            <h2>Supplier</h2>
            <input type="hidden" name="businessId" value={b} />
            <label>Name<input name="name" required maxLength={160} /></label>
            <label>Contact<input name="contact_name" maxLength={160} /></label>
            <label>Phone<input name="phone" maxLength={40} /></label>
            <label>Credit days<input name="credit_days" type="number" min={0} defaultValue={0} /></label>
            <button type="submit" className="btn-primary">Save supplier</button>
          </SafeForm>
          <SafeForm action={prepareRequirement} className="bos-form">
            <h2>What to buy</h2>
            <input type="hidden" name="businessId" value={b} />
            <input type="hidden" name="location_id" value={locationId} />
            <label>Supplier
              <select name="supplier_id" required>
                {board.suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
              </select>
            </label>
            <label>Item
              <select name="offering_id" required>
                {offerings.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
              </select>
            </label>
            <label>Required demand<input name="demand" type="number" min={1} required /></label>
            <label>Pack size<input name="pack_size" type="number" min={1} defaultValue={1} /></label>
            <label>Minimum order<input name="moq" type="number" min={1} defaultValue={1} /></label>
            <button type="submit" className="btn-primary">Calculate requirement</button>
          </SafeForm>
          <section>
            <h2>Why this quantity</h2>
            {board.requisitions.length === 0 ? <p>No requirement is waiting.</p> : board.requisitions.map((row) => (
              <article key={row.id}>
                <p>{row.explanation}</p>
                <p>Demand {row.demand_quantity} + safety {row.safety_stock} − usable {row.usable_on_hand} − inbound {row.confirmed_inbound}. Buy {row.quantity}.</p>
                <SafeForm action={approveRequirement}>
                  <input type="hidden" name="businessId" value={b} />
                  <input type="hidden" name="requisitionId" value={row.id} />
                  <button type="submit" className="btn-primary">Approve and send</button>
                </SafeForm>
              </article>
            ))}
          </section>
          <section>
            <h2>Receive goods</h2>
            {board.orders.filter((order) => ['sent', 'acknowledged', 'dispatched'].includes(order.status)).length === 0
              ? <p>Nothing is waiting to be received. A purchase order on its own does not change stock.</p>
              : board.orders.filter((order) => ['sent', 'acknowledged', 'dispatched'].includes(order.status)).map((order) => (
                <SafeForm key={order.id} action={receiveGoods} className="bos-form">
                  <p>{order.reference}: ordered {order.ordered_quantity}, received so far {order.received_quantity}. {order.explanation}</p>
                  <input type="hidden" name="businessId" value={b} />
                  <input type="hidden" name="purchaseOrderId" value={order.id} />
                  <input type="hidden" name="location_id" value={locationId} />
                  <label>Good quantity<input name="received_quantity" type="number" min={0} required /></label>
                  <label>Damaged<input name="damaged_quantity" type="number" min={0} defaultValue={0} /></label>
                  <button type="submit" className="btn-primary">Record receipt</button>
                </SafeForm>
              ))}
          </section>
        </>
      ) : (
        <section>
          <h2>What buyers have asked for</h2>
          {incoming?.ok ? (
            <>
              <ul>
                {Object.entries(incoming.data.data.totals).map(([item, qty]) => (
                  <li key={item}><strong>{item}</strong> — {qty} across buyers</li>
                ))}
              </ul>
              <table>
                <caption>Each buyer</caption>
                <thead><tr><th>Buyer</th><th>Item</th><th>Quantity</th></tr></thead>
                <tbody>
                  {incoming.data.data.lines.map((line, index) => (
                    <tr key={`${line.buyer_label}-${index}`}>
                      <td>{line.buyer_label}</td>
                      <td>{line.item_label}</td>
                      <td>{line.quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {incoming.data.data.lines.length === 0 ? <p>No incoming demand yet.</p> : null}
            </>
          ) : <p>Incoming demand could not be loaded.</p>}
        </section>
      )}
    </div>
  )
}
