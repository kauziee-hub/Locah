import { fetchPublicWebsite } from '@/lib/public-website'
import { OG_SIZE, shareCard } from '@/lib/og-card'
import { RESERVED_SLUGS } from '@/lib/reserved-slugs'

// The card a business's home page shows when it is shared (lib/og-card.tsx).
export const size = OG_SIZE
export const contentType = 'image/png'
// Edge: the Node build of next/og cannot find its bundled font on Windows,
// and the card needs nothing Node-only.
export const runtime = 'edge'
export const revalidate = 3600
export const alt = 'Website preview'

export default async function Image({ params }: { params: { slug: string } }) {
  if (RESERVED_SLUGS.has(params.slug)) return shareCard(null)
  return shareCard(await fetchPublicWebsite(params.slug).catch(() => null))
}
