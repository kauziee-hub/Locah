import type { MetadataRoute } from 'next'
import { platformUrl } from '@platform/config'

/**
 * What a search engine may crawl on the public platform.
 *
 * Sign-in, the Workspace hand-off, the auth plumbing and the API are not
 * content; per-customer pages (pay links, quotes, tracking) live under their own
 * private paths and already carry `noindex`.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/workspace', '/login', '/signup', '/auth/', '/api/', '/q/', '/document-request/'],
      },
    ],
    sitemap: platformUrl('web', '/sitemap.xml'),
  }
}
