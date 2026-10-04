import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, FilterTabs, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { createCustomer } from './actions'
import { BusinessEmpty } from '@/components/BusinessEmpty'

export const dynamic = 'force-dynamic'

type CustomerRow = {
  id: string
  display_name: string
  email: string | null
  phone: string | null
  status: string
  tags?: string[]
}

/**
 * Doc 11 §9 Customer Relationships. Business-owned customer records (Doc 05
 * CUS-001) — distinct from platform identities.
 */
export default async function CustomersPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { status?: string; tag?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/b/${params.businessId}`
  const q = new URLSearchParams()
  if (searchParams?.status) q.set('status', searchParams.status)
  if (searchParams?.tag) q.set('tag', searchParams.tag)
  const qs = q.toString() ? `?${q.toString()}` : ''
  const [res, tagsRes] = await Promise.all([
    apiTry<{ data: CustomerRow[] }>(`/v1/platform/businesses/${params.businessId}/customers${qs}`, token),
    apiTry<{ data: { tag: string; count: number }[] }>(`/v1/platform/businesses/${params.businessId}/customers/tags`, token),
  ])
  const tags = tagsRes.ok ? tagsRes.data.data : []
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Customers" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Customers" />
      </div>
    )
  }
  const customers = res.data.data || []

  return (
    <div>
      <PageHeader
        title="Customers"
        subtitle="This business's own customer records — separate from platform accounts."
        actions={<Link className="btn-ghost" href={`${base}/customers/segments`}>Segments</Link>}
      />
      {tags.length ? (
        <nav className="bos-tagbar" aria-label="Tags">
          <Link href={`${base}/customers`} aria-current={!searchParams?.tag ? 'page' : undefined}>
            <span className="bos-tag">All</span>
          </Link>
          {tags.map((t) => (
            <Link key={t.tag} href={`${base}/customers?tag=${encodeURIComponent(t.tag)}`}
              aria-current={searchParams?.tag === t.tag ? 'page' : undefined}>
              <span className="bos-tag">{t.tag} · {t.count}</span>
            </Link>
          ))}
        </nav>
      ) : null}
      <FilterTabs
        current={searchParams?.status}
        hrefFor={(v) => `${base}/customers${v ? `?status=${v}` : ''}${searchParams?.tag ? `${v ? '&' : '?'}tag=${encodeURIComponent(searchParams.tag)}` : ''}`}
        options={[
          { value: '', label: 'All' },
          { value: 'active', label: 'Active' },
          { value: 'blocked', label: 'Blocked' },
          { value: 'archived', label: 'Archived' },
        ]}
      />
      <DataTable
        rows={customers}
        rowKey={(c) => c.id}
        columns={[
          {
            key: 'name',
            header: 'Name',
            render: (c) => <Link href={`${base}/customers/${c.id}`}>{c.display_name}</Link>,
          },
          { key: 'email', header: 'Email', render: (c) => c.email || '—' },
          { key: 'phone', header: 'Phone', render: (c) => c.phone || '—' },
          { key: 'tags', header: 'Tags', render: (c) => (c.tags?.length ? c.tags.join(', ') : '—') },
          { key: 'status', header: 'Status', render: (c) => <StatusPill value={c.status} /> },
        ]}
        empty={
          <BusinessEmpty businessId={params.businessId} module="customers" fallbackTitle="No customer records yet"
                         fallback="A record is created the first time someone orders or books. You can also add one below." />
        }
      />

      <Section title="Add a customer" id="add">
        <form action={createCustomer} style={{ display: 'grid', gap: '0.6rem', maxWidth: '32rem' }}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input name="display_name" placeholder="Name" required />
          <input name="email" type="email" placeholder="Email" />
          <input name="phone" placeholder="Phone" />
          <button type="submit" style={{ justifySelf: 'start' }}>
            Add customer
          </button>
        </form>
      </Section>
    </div>
  )
}
