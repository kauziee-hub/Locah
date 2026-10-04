import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { FilterTabs, GateNotice, PageHeader } from '@/components/ui'
import { featureReview, replyReview, reportReview } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Review = {
  id: string; reviewer_name: string; rating: number; body: string | null; verified: string
  published_at: string | null; status: string; featured: boolean
  reply: { body: string } | null; customer: { name: string; phone: string | null } | null
  photos: string[]
  report: { reason_words: string; status: string } | null
}
type Reviews = { average: number | null; count: number; distribution: Record<string, number>; reviews: Review[]; counts: { reply: number; low: number; featured: number }; violations: Record<string, string>; max_featured: number }
const TABS = [
  { value: '', label: 'All' }, { value: 'reply', label: 'Needs reply' },
  { value: 'low', label: '1–2 stars' }, { value: 'featured', label: 'Featured' },
  { value: 'reported', label: 'Reported' }, { value: 'removed', label: 'Removed' },
]

export default async function ReviewsPage({ params, searchParams }: { params: { businessId: string }; searchParams?: { view?: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const view = TABS.some((tab) => tab.value === searchParams?.view) ? searchParams?.view || '' : ''
  const [res, context] = await Promise.all([
    apiTry<{ data: Reviews }>(`/v1/platform/businesses/${b}/reviews?view=${view || 'all'}`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const header = <PageHeader title="Reviews" subtitle="Verified customer experiences. Respond, resolve, and feature — never rewrite or delete a customer's words." />
  if (!res.ok) return <div className="bos-page">{header}<GateNotice error={res.error} businessId={b} moduleLabel="Reviews" /></div>
  const data = res.data.data
  const permissions = new Set(context.ok ? context.data.data.permissions : [])
  const canReply = permissions.has('reviews.reply')
  const canManage = permissions.has('reviews.manage')
  return (
    <div className="bos-page bos-reviews">
      {header}
      <div className="bos-review-summary">
        <div><span>Overall rating</span><strong>{data.count ? `${data.average?.toFixed(1)} ★` : '—'}</strong><small>{data.count} verified {data.count === 1 ? 'review' : 'reviews'}</small></div>
        <div><span>Needs reply</span><strong>{data.counts.reply}</strong><small>Respond publicly</small></div>
        <div><span>Low ratings</span><strong>{data.counts.low}</strong><small>Reach out and make it right</small></div>
      </div>
      <FilterTabs current={view} options={TABS} hrefFor={(v) => `/b/${b}/reviews${v ? `?view=${v}` : ''}`} />
      {data.reviews.length ? <div className="bos-review-list">{data.reviews.map((review) => (
        <article className="bos-review-card" key={review.id}>
          <div className="bos-review-card__head"><div><strong>{review.reviewer_name}</strong><p aria-label={`${review.rating} out of 5 stars`}>{'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)} · {review.verified}</p></div><span>{review.published_at ? new Date(review.published_at).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : review.status}</span></div>
          {review.body ? <p className="bos-review-card__body">{review.body}</p> : <p className="bos-hint">Star rating only</p>}
          {review.status === 'published' && review.photos.length ? <div className="bos-review-card__photos">{review.photos.map((id) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={id} src={`/b/${b}/reviews/photos/${id}`} alt={`Photo shared by ${review.reviewer_name}`} />
          ))}</div> : null}
          {review.customer ? <p className="bos-review-card__customer">Customer: {review.customer.name}{review.customer.phone ? <> · <a href={`tel:${review.customer.phone}`}>{review.customer.phone}</a></> : null}</p> : null}
          {review.reply ? <div className="bos-review-card__reply"><strong>Your public response</strong><p>{review.reply.body}</p></div> : null}
          {review.report ? <p className="bos-review-card__report">Reported: {review.report.reason_words} · {review.report.status}</p> : null}
          {review.status === 'published' ? <div className="bos-review-card__actions">
            {canReply ? <SafeForm action={replyReview}><input type="hidden" name="businessId" value={b} /><input type="hidden" name="reviewId" value={review.id} /><label htmlFor={`reply-${review.id}`}>Public response</label><textarea id={`reply-${review.id}`} name="body" defaultValue={review.reply?.body || ''} maxLength={1000} rows={2} placeholder="Thank the customer, or explain how you will put this right." /><button className="btn" type="submit">{review.reply ? 'Update response' : 'Post response'}</button></SafeForm> : null}
            {canManage ? <div className="bos-review-card__manage">
              <SafeForm action={featureReview}><input type="hidden" name="businessId" value={b} /><input type="hidden" name="reviewId" value={review.id} /><input type="hidden" name="featured" value={review.featured ? 'false' : 'true'} /><button className="btn-ghost" type="submit">{review.featured ? 'Unfeature' : 'Feature on website'}</button></SafeForm>
              {!review.report ? <SafeForm action={reportReview}><input type="hidden" name="businessId" value={b} /><input type="hidden" name="reviewId" value={review.id} /><label htmlFor={`reason-${review.id}`}>Report a policy violation</label><select id={`reason-${review.id}`} name="reason" required><option value="">Select a reason</option>{Object.entries(data.violations).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select><input name="note" maxLength={500} placeholder="Context for moderator (optional)" /><button className="btn-ghost" type="submit">Send report</button></SafeForm> : null}
            </div> : null}
          </div> : null}
        </article>
      ))}</div> : <div className="bos-empty">No reviews in this view yet. Invitations are sent after a completed order or booking when Reviews and Messaging are active.</div>}
      <p className="bos-hint">Featured reviews appear on a published website only when you add its Reviews section. <Link href={`/b/${b}/website`}>Edit website</Link>. Showing a review does not imply LOCAH endorses its contents.</p>
    </div>
  )
}
