import type { Metadata } from 'next'
import { privatePageMetadata } from '@/lib/page-meta'
import { notFound } from 'next/navigation'
import { platformUrl } from '@platform/config'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'
import { cartKey, fetchCheckoutOptions, type CartItem } from '@/lib/checkout-api'
import { fetchPublicWebsite } from '@/lib/public-website'
import { getAccessToken } from '@/lib/supabase/access-token'
import { SiteFrame } from '@/components/website/SiteFrame'
import { siteLang } from '@/lib/site-lang'
import CheckoutClient from './CheckoutClient'

export const dynamic = 'force-dynamic'

type ReorderLine = { offering_id: string; variant_id: string | null; title: string; quantity: number; options: Record<string, unknown> | null; available: boolean; unit_price?: number; reason?: string }

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  return privatePageMetadata(params.slug, 'Checkout')
}

/**
 * WEB-007 Cart / Checkout — Doc 12 §11.2 `/{slug}/checkout`, in the business's
 * own colours. A signed-in LOCAH customer orders under their own identity
 * (Founder §12); `?reorder=` refills the cart from one of their earlier orders
 * at today's catalogue price (§12.3 "Repeat last order").
 */
export default async function CheckoutPage({ params, searchParams }: { params: { slug: string }; searchParams?: { reorder?: string; lang?: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) notFound()
  let options
  try {
    options = await fetchCheckoutOptions(params.slug)
  } catch {
    notFound()
  }
  const site = await fetchPublicWebsite(params.slug)
  const lang = siteLang(site?.website.languages, searchParams?.lang)
  const token = await getAccessToken()
  let customer: { name: string; email: string } | null = null
  let reorder: CartItem[] | null = null
  let unavailable: string[] = []
  if (token) {
    const api = platformUrl('api')
    const me = await fetch(`${api}/v1/me`, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' })
    if (me.ok) {
      const profile = ((await me.json()) as { data: { email: string; display_name: string | null } }).data
      customer = { name: profile.display_name ?? '', email: profile.email }
    }
    if (searchParams?.reorder && customer) {
      const res = await fetch(`${api}/v1/me/businesses/${encodeURIComponent(params.slug)}/orders/${encodeURIComponent(searchParams.reorder)}/reorder`,
        { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' })
      if (res.ok) {
        const lines = ((await res.json()) as { data: ReorderLine[] }).data
        unavailable = lines.filter((l) => !l.available).map((l) => l.title)
        reorder = lines.filter((l) => l.available).map((l) => {
          const item: CartItem = { offering_id: l.offering_id, title: l.title, quantity: l.quantity, unit_price: l.unit_price ?? 0,
            currency: 'INR', options: l.options ?? undefined, variant_id: l.variant_id ?? undefined }
          return { ...item, key: cartKey(item) }
        })
      }
    }
  }
  return (
    <SiteFrame site={site} lang={lang}>
      <CheckoutClient slug={params.slug} options={options} customer={customer} authToken={customer ? token : null} reorder={reorder} unavailable={unavailable} />
    </SiteFrame>
  )
}
