import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader, StatusPill } from '@/components/ModuleState'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { rupees } from '@/lib/when'
import { createZone, setZoneActive, updateFulfilmentSettings, updatePaymentRules } from '../actions'

export const dynamic = 'force-dynamic'

type Zone = {
  id: string
  name: string
  match_type: string
  city: string | null
  postal_prefix: string | null
  radius_km: number | null
  charge_amount: number
  is_active: boolean
}
type Settings = { pickup_enabled: boolean; delivery_enabled: boolean; cod_allowed: boolean; first_order_cod_cap: number | null }

function where(z: Zone): string {
  if (z.match_type === 'postal_prefix') return `PIN codes starting ${z.postal_prefix}`
  if (z.match_type === 'radius') return `Within ${z.radius_km} km`
  return `All of ${z.city}`
}

/** How orders reach customers: pickup, delivery areas with their charges, and paying on delivery. */
export default async function FulfilmentZonesPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const back = <Link href={`/b/${params.businessId}/fulfilment`}>Deliveries &amp; pickup</Link>
  const [zonesRes, settingsRes] = await Promise.all([
    apiTry<{ data: Zone[] }>(`/v1/b/${params.businessId}/fulfilment/zones`, token),
    apiTry<{ data: Settings }>(`/v1/b/${params.businessId}/fulfilment/settings`, token),
  ])
  if (!zonesRes.ok) {
    return (
      <div className="bos-page">
        <PageHeader title="Delivery areas & charges" breadcrumb={back} />
        <GateNotice error={zonesRes.error} businessId={params.businessId} moduleLabel="Deliveries & pickup" />
      </div>
    )
  }
  const zones = zonesRes.data.data || []
  const settings = settingsRes.ok
    ? settingsRes.data.data
    : { pickup_enabled: false, delivery_enabled: false, cod_allowed: true, first_order_cod_cap: null }

  return (
    <div className="bos-page bos-zones">
      <PageHeader title="Delivery areas & charges" breadcrumb={back}
        subtitle="How customers get their orders, where you deliver, and what delivery costs them." />

      <section className="bos-card" aria-labelledby="modes-h">
        <h2 id="modes-h">How customers get their order</h2>
        <ActionForm action={updateFulfilmentSettings} className="ws-form" success="Saved.">
          <input type="hidden" name="businessId" value={params.businessId} />
          <label className="bos-field__check">
            <input type="checkbox" name="pickup_enabled" defaultChecked={settings.pickup_enabled} /> They can pick it up from you
          </label>
          <label className="bos-field__check">
            <input type="checkbox" name="delivery_enabled" defaultChecked={settings.delivery_enabled} /> You deliver it
            {zones.some((z) => z.is_active) ? null : <span className="bos-fieldhelp"> — add a delivery area below first</span>}
          </label>
          <div><SubmitButton>Save</SubmitButton></div>
        </ActionForm>
      </section>

      <section className="bos-card" aria-labelledby="zones-h">
        <h2 id="zones-h">Where you deliver</h2>
        {zones.length ? (
          <ul className="bos-mini-list">
            {zones.map((z) => (
              <li key={z.id}>
                <div>
                  <strong>{z.name}</strong>
                  <p>{where(z)} · {z.charge_amount ? `${rupees(z.charge_amount)} delivery` : 'Free delivery'}</p>
                </div>
                <span className="bos-pay__confirm">
                  <StatusPill value={z.is_active ? 'active' : 'off'} label={z.is_active ? 'On' : 'Off'} />
                  <ActionButton className="btn-ghost" label={z.is_active ? 'Switch off' : 'Switch on'} busyLabel="Saving…"
                    run={setZoneActive.bind(null, params.businessId, z.id, !z.is_active)} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="bos-hint">No delivery areas yet. Add one so customers can choose delivery at checkout.</p>
        )}
        <h3 className="bos-zones__add">Add a delivery area</h3>
        <ActionForm action={createZone} className="ws-form" success="Delivery area added." resetOnSuccess>
          <input type="hidden" name="businessId" value={params.businessId} />
          <label className="bos-label" htmlFor="z-kind">Deliver to</label>
          <select id="z-kind" name="match_type" defaultValue="postal_prefix">
            <option value="postal_prefix">PIN codes (e.g. 600040, or 6000 for many)</option>
            <option value="city">A whole city</option>
          </select>
          <label className="bos-label" htmlFor="z-where">PIN code or city</label>
          <input id="z-where" name="where" required maxLength={80} placeholder="600040" />
          <label className="bos-label" htmlFor="z-name">Name customers see (optional)</label>
          <input id="z-name" name="name" maxLength={80} placeholder="Anna Nagar" />
          <label className="bos-label" htmlFor="z-charge">Delivery charge (₹)</label>
          <input id="z-charge" name="charge_amount" type="number" step="1" min="0" max="100000" defaultValue="0" />
          <div><SubmitButton busy="Adding…">Add delivery area</SubmitButton></div>
        </ActionForm>
      </section>

      <section className="bos-card" aria-labelledby="cod-h">
        <h2 id="cod-h">Paying on delivery or at pickup</h2>
        <p className="bos-hint">The same rule for orders from your website and WhatsApp.</p>
        <ActionForm action={updatePaymentRules} className="ws-form" success="Saved.">
          <input type="hidden" name="businessId" value={params.businessId} />
          <label className="bos-field__check">
            <input type="checkbox" name="cod_allowed" defaultChecked={settings.cod_allowed} /> Customers can pay on delivery or at pickup
          </label>
          <label className="bos-label" htmlFor="cod-cap">A new customer&apos;s first order can be paid this way up to (₹)</label>
          <input id="cod-cap" name="first_order_cod_cap" inputMode="decimal" placeholder="No limit"
            defaultValue={settings.first_order_cod_cap === null ? '' : String(settings.first_order_cod_cap)} />
          <div><SubmitButton>Save payment rules</SubmitButton></div>
        </ActionForm>
      </section>
    </div>
  )
}
