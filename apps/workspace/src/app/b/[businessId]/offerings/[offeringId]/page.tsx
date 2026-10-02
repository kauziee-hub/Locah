import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { OfferingEditor } from '../OfferingEditor'
import type { Kind, Offering, RateLite, Variant } from '../types'
import { LabelTools } from './LabelTools'
import { PicturePanel } from './PicturePanel'

export const dynamic = 'force-dynamic'

export default async function EditOfferingPage({ params }: { params: { businessId: string; offeringId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/v1/platform/businesses/${params.businessId}/products/${params.offeringId}`
  const [res, kindsRes, varRes, counter, ratesRes, contextRes] = await Promise.all([
    apiTry<{ data: Offering }>(base, token),
    apiTry<{ data: Kind[] }>('/v1/public/offering-kinds', token),
    apiTry<{ data: Variant[] }>(`${base}/variants`, token),
    apiTry<{ data: unknown }>(`/v1/platform/businesses/${params.businessId}/pos/setup`, token),
    apiTry<{ data: RateLite[] }>(`/v1/platform/businesses/${params.businessId}/pricing/rates`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(params.businessId)),
  ])
  const back = <Link href={`/b/${params.businessId}/offerings`}>Products & services</Link>
  if (!res.ok) {
    return (
      <div className="bos-page">
        <PageHeader title="Offering" breadcrumb={back} />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Products & services" />
      </div>
    )
  }
  const offering = res.data.data
  const kind = (kindsRes.ok ? kindsRes.data.data : []).find((k) => k.key === offering.offering_type)
  return (
    <div className="bos-page">
      <PageHeader title={offering.title} subtitle={kind?.label ?? offering.kind_label} breadcrumb={back} />
      {kind ? (
        <OfferingEditor
          businessId={params.businessId}
          kind={kind}
          offering={offering}
          variants={varRes.ok ? varRes.data.data : []}
          rates={ratesRes.ok ? ratesRes.data.data : []}
        />
      ) : (
        <div className="bos-empty">This is an older kind of listing and can only be archived.</div>
      )}
      <PicturePanel
        businessId={params.businessId}
        offeringId={offering.id}
        title={offering.title}
        pictures={offering.images ?? []}
        canChange={(contextRes.ok ? contextRes.data.data.permissions : []).includes('offerings.update')}
      />
      {counter.ok && kind?.stockable ? (
        <LabelTools businessId={params.businessId} offeringId={offering.id} barcode={(offering as { barcode?: string | null }).barcode ?? null} />
      ) : null}
    </div>
  )
}
