import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { createComplianceItem, markComplianceFiled, renewComplianceItem, setComplianceArchived, updateComplianceItem } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Item = {
  id: string; item_type: 'licence' | 'filing'; kind: string; title: string; due_on: string
  licence_number: string | null; authority: string | null; recurrence: string; document_url: string | null
  notes: string | null; show_on_site: boolean; status: string; attention: string; last_done_on: string | null
}
type History = { action: string; from_due: string | null; to_due: string | null; note: string | null; at: string }
const KINDS = [
  ['fssai', 'FSSAI'], ['trade_licence', 'Trade licence'], ['shop_establishment', 'Shop & establishment'],
  ['drug_licence', 'Drug licence'], ['fire_noc', 'Fire NOC'], ['bar_licence', 'Bar licence'],
  ['pollution', 'Pollution'], ['gst_registration', 'GST registration'], ['gst_filing', 'GST filing'],
  ['income_tax', 'Income tax'], ['tds', 'TDS'], ['professional_tax', 'Professional tax'],
  ['rera', 'RERA'], ['accreditation', 'Accreditation'], ['other', 'Other'],
]
const date = (value: string) => new Date(`${value}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

export default async function CompliancePage({ params, searchParams }: { params: { businessId: string }; searchParams?: { archived?: string; item?: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const archived = searchParams?.archived === '1'
  const [res, context] = await Promise.all([
    apiTry<{ data: { items: Item[]; counts: { overdue: number; due_soon: number } } }>(`/v1/platform/businesses/${b}/compliance/items?archived=${archived}`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const header = <PageHeader title="Licences & due dates" subtitle="Track the dates your team enters. LOCAH reminds you; it does not decide which licences you need or provide legal or tax advice." />
  if (!res.ok) return <div className="bos-page">{header}<GateNotice error={res.error} businessId={b} moduleLabel="Compliance calendar" /></div>
  const data = res.data.data
  const canManage = context.ok && context.data.data.permissions.includes('compliance.manage')
  const selected = data.items.find((item) => item.id === searchParams?.item)
  const history = selected ? await apiTry<{ data: History[] }>(`/v1/platform/businesses/${b}/compliance/items/${selected.id}/history`, token) : null
  return (
    <div className="bos-page bos-compliance">
      {header}
      <div className="bos-review-summary"><div><span>Overdue</span><strong>{data.counts.overdue}</strong><small>Check with your team</small></div><div><span>Due in 7 days</span><strong>{data.counts.due_soon}</strong><small>Dates you entered</small></div><div><span>Tracked</span><strong>{data.items.length}</strong><small>Licences and filings</small></div></div>
      <nav className="bos-compliance__tabs" aria-label="Compliance items"><Link href={`/b/${b}/compliance`} aria-current={!archived ? 'page' : undefined}>Active</Link><Link href={`/b/${b}/compliance?archived=1`} aria-current={archived ? 'page' : undefined}>All including archived</Link></nav>
      {data.items.length ? <div className="bos-compliance__list">{data.items.map((item) => (
        <article className="bos-compliance__card" key={item.id}>
          <div><span className={`bos-compliance__state is-${item.attention}`}>{item.attention.replace('_', ' ')}</span><span className="bos-hint"> {item.item_type === 'licence' ? 'Licence' : 'Filing'}</span></div>
          <h2><Link href={`/b/${b}/compliance?${archived ? 'archived=1&' : ''}item=${item.id}`}>{item.title}</Link></h2>
          <p>Due {date(item.due_on)}{item.recurrence !== 'none' ? ` · ${item.recurrence}` : ''}</p>
          {item.authority ? <p className="bos-hint">{item.authority}</p> : null}
          {item.licence_number ? <p className="bos-hint">Number {item.licence_number}{item.show_on_site ? ' · shown publicly' : ''}</p> : null}
          {canManage && item.status === 'active' ? <div className="bos-compliance__actions">
            {item.item_type === 'licence' ? <SafeForm action={renewComplianceItem}><input type="hidden" name="businessId" value={b} /><input type="hidden" name="itemId" value={item.id} /><label htmlFor={`renew-${item.id}`}>New expiry date supplied by authority</label><input id={`renew-${item.id}`} type="date" name="new_due_on" min={item.due_on} required /><button type="submit" className="btn-ghost">Record renewal</button></SafeForm> : <SafeForm action={markComplianceFiled}><input type="hidden" name="businessId" value={b} /><input type="hidden" name="itemId" value={item.id} /><button type="submit" className="btn-ghost">Mark filed</button></SafeForm>}
          </div> : null}
        </article>
      ))}</div> : <div className="bos-empty">No {archived ? '' : 'active '}licences or filing dates tracked yet. Add only dates confirmed by your team or adviser.</div>}
      {selected ? <section className="bos-compliance__detail" aria-labelledby="compliance-detail"><h2 id="compliance-detail">{selected.title}</h2>
        {canManage ? <><SafeForm action={updateComplianceItem} className="bos-compliance__form"><input type="hidden" name="businessId" value={b} /><input type="hidden" name="itemId" value={selected.id} /><label>Title<input name="title" defaultValue={selected.title} maxLength={120} required /></label><label>Due / expiry date<input type="date" name="due_on" defaultValue={selected.due_on} required /></label><label>Licence number<input name="licence_number" defaultValue={selected.licence_number || ''} maxLength={60} /></label><label>Issuing authority<input name="authority" defaultValue={selected.authority || ''} maxLength={120} /></label><label>Document URL (HTTPS)<input name="document_url" type="url" defaultValue={selected.document_url || ''} /></label><label>Notes<textarea name="notes" defaultValue={selected.notes || ''} maxLength={1000} /></label>{selected.item_type === 'licence' ? <label className="bos-compliance__check"><input type="checkbox" name="show_on_site" defaultChecked={selected.show_on_site} /> Show this licence number on my public website</label> : null}<button type="submit" className="btn">Save details</button></SafeForm>
          <SafeForm action={setComplianceArchived}><input type="hidden" name="businessId" value={b} /><input type="hidden" name="itemId" value={selected.id} /><input type="hidden" name="archived" value={selected.status === 'active' ? 'true' : 'false'} /><button type="submit" className="btn-ghost">{selected.status === 'active' ? 'Archive item' : 'Restore item'}</button></SafeForm></> : null}
        <h3>History</h3>{history?.ok && history.data.data.length ? <ol>{history.data.data.map((event, i) => <li key={`${event.at}-${i}`}>{event.action} · {new Date(event.at).toLocaleDateString('en-IN', { dateStyle: 'medium' })}{event.from_due && event.to_due && event.from_due !== event.to_due ? ` · ${date(event.from_due)} → ${date(event.to_due)}` : ''}{event.note ? ` · ${event.note}` : ''}</li>)}</ol> : <p className="bos-hint">No history available.</p>}
      </section> : null}
      {canManage ? <section className="bos-compliance__detail" aria-labelledby="add-compliance"><h2 id="add-compliance">Add a licence or filing</h2><p className="bos-hint">Enter only dates you know. Reminders are based on these dates, not on a legal calendar.</p><SafeForm action={createComplianceItem} className="bos-compliance__form"><input type="hidden" name="businessId" value={b} /><label>Type<select name="item_type" required><option value="licence">Licence</option><option value="filing">Filing</option></select></label><label>Kind<select name="kind" required>{KINDS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>Title<input name="title" maxLength={120} required placeholder="e.g. Food safety licence" /></label><label>Due / expiry date<input type="date" name="due_on" required /></label><label>Recurs<select name="recurrence"><option value="none">No</option><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="yearly">Yearly</option></select></label><label>Licence number (optional)<input name="licence_number" maxLength={60} /></label><label>Issuing authority (optional)<input name="authority" maxLength={120} /></label><label>Document URL (HTTPS, optional)<input name="document_url" type="url" /></label><label>Notes (optional)<textarea name="notes" maxLength={1000} /></label><label className="bos-compliance__check"><input type="checkbox" name="show_on_site" /> Show licence number on public website</label><button className="btn" type="submit">Add item</button></SafeForm></section> : null}
    </div>
  )
}
