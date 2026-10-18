import { fetchPublicWebsite } from '@/lib/public-website'
import { OG_SIZE, shareCard } from '@/lib/og-card'
import { coverImage } from '@/lib/structured-data'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'

// An inner page's share card: its own picture, else the home cover, with the
// page's name above the business's (lib/og-card.tsx).
export const size = OG_SIZE
export const contentType = 'image/png'
// Edge: the Node build of next/og cannot find its bundled font on Windows,
// and the card needs nothing Node-only.
export const runtime = 'edge'
export const revalidate = 3600
export const alt = 'Website preview'

export default async function Image({ params }: { params: { slug: string; pageSlug: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) return shareCard(null)
  const [page, home] = await Promise.all([
    fetchPublicWebsite(params.slug, params.pageSlug).catch(() => null),
    fetchPublicWebsite(params.slug).catch(() => null),
  ])
  const title = String(page?.page?.title || '').trim()
  return shareCard(page, { page: title || undefined, cover: coverImage(home) || undefined })
}
