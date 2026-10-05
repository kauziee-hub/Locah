import type { MetadataRoute } from 'next'
import { platformUrl } from '@platform/config'

/**
 * The public platform pages. Business websites are not listed here: they are
 * created and unpublished by their owners, so a static list would go stale. They
 * are reached through the Marketplace.
 */
const PUBLIC_PATHS: ReadonlyArray<{ path: string; priority: number }> = [
  { path: '', priority: 1 },
  { path: '/marketplace', priority: 0.9 },
  { path: '/for-businesses', priority: 0.8 },
  { path: '/product', priority: 0.8 },
  { path: '/how-it-works', priority: 0.7 },
  { path: '/pricing', priority: 0.7 },
  { path: '/contact', priority: 0.5 },
  { path: '/delivery', priority: 0.4 },
  { path: '/policies', priority: 0.3 },
  { path: '/privacy', priority: 0.3 },
  { path: '/terms', priority: 0.3 },
  { path: '/refunds', priority: 0.3 },
  { path: '/disclaimer', priority: 0.2 },
]

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date()
  return PUBLIC_PATHS.map(({ path, priority }) => ({
    url: platformUrl('web', path),
    lastModified,
    priority,
  }))
}
