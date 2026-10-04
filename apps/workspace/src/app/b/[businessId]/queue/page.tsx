import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { createQueueLane, issueToken, queueAct } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Lane = {
  id: string
  name: string
  location_id: string
  provider_id: string | null
  department: string | null
  allow_requeue: boolean
  avg_service_minutes: number | null
}
type Token = {
  id: string
  token_number: number
  status: string
  display_name: string
  source: string
  ahead: number | null
  estimated_wait_minutes: number | null
  booking_id: string | null
}
type Board = { lane: Lane; columns: { waiting: Token[]; called: Token[]; serving: Token[]; done: Token[] } }
type Location = { id: string; name: string }
type Member = { id: string; display_name: string }

const COLUMNS: { key: keyof Board['columns']; label: string }[] = [
  { key: 'waiting', label: 'Waiting' },
  { key: 'called', label: 'Called' },
  { key: 'serving', label: 'Serving' },
  { key: 'done', label: 'Done / Missed' },
]

export default async function QueuePage({ params, searchParams }: {
  params: { businessId: string }
  searchParams?: { lane?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const [lanesRes, locRes, peopleRes, context] = await Promise.all([
    apiTry<{ data: { lanes: Lane[] } }>(`/v1/platform/businesses/${b}/queue/lanes`, token),
    apiTry<{ data: Location[] }>(`/v1/platform/businesses/${b}/locations`, token),
    apiTry<{ data: Member[] }>(`/v1/platform/businesses/${b}/workforce/members`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const header = <PageHeader title="Walk-in queue" subtitle="Tokens for people waiting now. A booked appointment joins this queue; it stays a booking." />
  if (!lanesRes.ok) return <div className="bos-page">{header}<GateNotice error={lanesRes.error} businessId={b} moduleLabel="Walk-in queue" /></div>
  const lanes = lanesRes.data.data.lanes
  const locations = locRes.ok ? locRes.data.data : []
  const people = peopleRes.ok ? peopleRes.data.data : []
  const perms = context.ok ? context.data.data.permissions : []
  const canOperate = perms.includes('queue.operate')
  const canConfigure = perms.includes('queue.configure')
  const laneId = searchParams?.lane && lanes.some((lane) => lane.id === searchParams.lane) ? searchParams.lane : lanes[0]?.id
  const board = laneId
    ? await apiTry<{ data: Board }>(`/v1/platform/businesses/${b}/queue/lanes/${laneId}`, token)
    : null
  const lane = board?.ok ? board.data.data.lane : null
  return (
    <div className="bos-page bos-queue">
      {header}
      {lanes.length > 0 ? (
        <nav className="bos-queue__lanes" aria-label="Queues">
          {lanes.map((item) => (
            <Link key={item.id} href={`/b/${b}/queue?lane=${item.id}`} aria-current={item.id === laneId ? 'page' : undefined}>
              {item.name}{item.department ? ` · ${item.department}` : ''}
            </Link>
          ))}
        </nav>
      ) : <p className="bos-empty">No queue yet. Add one for a location, and a provider or department when people wait for a specific person.</p>}
      {lane && board?.ok ? (
        <>
          {canOperate ? (
            <SafeForm action={issueToken} className="bos-queue__issue">
              <input type="hidden" name="businessId" value={b} />
              <input type="hidden" name="laneId" value={lane.id} />
              <label>Walk-in name<input name="partyLabel" maxLength={80} placeholder="Who is waiting" /></label>
              <label>Or booking id<input name="bookingId" placeholder="Existing booking" /></label>
              <button className="btn" type="submit">Issue token</button>
            </SafeForm>
          ) : null}
          <div className="bos-queue__board">
            {COLUMNS.map((column) => (
              <section key={column.key} aria-label={column.label}>
                <h2>{column.label}</h2>
                {column.key === 'waiting' && canOperate ? (
                  <SafeForm action={queueAct}>
                    <input type="hidden" name="businessId" value={b} />
                    <input type="hidden" name="laneId" value={lane.id} />
                    <input type="hidden" name="action" value="call-next" />
                    <button className="btn" type="submit">Call next</button>
                  </SafeForm>
                ) : null}
                <ol>
                  {board.data.data.columns[column.key].map((entry) => (
                    <li key={entry.id}>
                      <strong>#{entry.token_number}</strong> {entry.display_name}
                      {entry.source === 'booking' ? <span className="bos-hint"> Booked</span> : null}
                      {entry.ahead != null ? <span className="bos-hint"> · {entry.ahead} ahead{entry.estimated_wait_minutes != null ? ` · about ${entry.estimated_wait_minutes} min` : ''}</span> : null}
                      {entry.status === 'missed' ? <span className="bos-hint"> Missed</span> : null}
                      {canOperate ? <TokenActions businessId={b} entry={entry} allowRequeue={lane.allow_requeue} /> : null}
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </div>
        </>
      ) : null}
      {canConfigure && locations.length > 0 ? (
        <section className="bos-queue__setup" aria-labelledby="new-queue">
          <h2 id="new-queue">New queue</h2>
          <SafeForm action={createQueueLane} className="bos-compliance__form">
            <input type="hidden" name="businessId" value={b} />
            <label>Name<input name="name" required maxLength={80} placeholder="OPD morning" /></label>
            <label>Location<select name="locationId" required>{locations.map((loc) => <option key={loc.id} value={loc.id}>{loc.name}</option>)}</select></label>
            <label>Department<input name="department" maxLength={80} placeholder="Optional" /></label>
            <label>Provider<select name="providerId"><option value="">Anyone at this desk</option>{people.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></label>
            <label>Average minutes per person<input name="avgServiceMinutes" type="number" min={1} max={480} /></label>
            <label>Your turn soon when this many are ahead<input name="turnSoonAhead" type="number" min={0} max={50} defaultValue={2} /></label>
            <label className="bos-compliance__check"><input type="checkbox" name="allowRequeue" defaultChecked /> Missed tokens can rejoin</label>
            <button className="btn" type="submit">Add queue</button>
          </SafeForm>
        </section>
      ) : null}
    </div>
  )
}

function TokenActions({ businessId, entry, allowRequeue }: { businessId: string; entry: Token; allowRequeue: boolean }) {
  const actions: { action: string; label: string }[] = []
  if (entry.status === 'waiting') actions.push({ action: 'call', label: 'Call' }, { action: 'miss', label: 'Miss' })
  if (entry.status === 'called') actions.push({ action: 'serve', label: 'Start serving' }, { action: 'miss', label: 'Miss' })
  if (entry.status === 'serving') actions.push({ action: 'complete', label: 'Done' }, { action: 'miss', label: 'Miss' })
  if (entry.status === 'missed' && allowRequeue) actions.push({ action: 'requeue', label: 'Requeue' })
  if (!actions.length) return null
  return (
    <div className="bos-queue__actions">
      {actions.map((item) => (
        <SafeForm key={item.action} action={queueAct}>
          <input type="hidden" name="businessId" value={businessId} />
          <input type="hidden" name="entryId" value={entry.id} />
          <input type="hidden" name="action" value={item.action} />
          <button className="btn-ghost" type="submit">{item.label}</button>
        </SafeForm>
      ))}
    </div>
  )
}
