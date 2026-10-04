import { platformUrl } from '@platform/config'
const apiUrl = platformUrl('api')

export type PublicWebsitePayload = {
  business: {
    id: string
    slug: string
    display_name: string
    business_type?: string | null
    /** Only what the owner published: a number to call or WhatsApp, an email. */
    contact?: { phone?: string; whatsapp?: string; email?: string }
    /** Where and when to find them: the main location as the owner keeps it today. */
    place?: { address?: string; hours_summary?: string; phone?: string }
  }
  /** What a visitor can actually do here, from the business's live modules.
   *  Sections read this instead of assuming from their own type. */
  capabilities?: Record<string, boolean | string | null>
  /** The business's connected WhatsApp number, when a WhatsApp journey
   *  (order, book, ask) can run right now: "menu" is already typed. */
  whatsapp?: { href: string; label: string; journeys: string[] } | null
  /** languages: the site's own words, first shown first (P1-10E6). */
  website: { status: string; languages?: string[] }
  page: {
    title: string
    slug: string
    seo_title?: string | null
    seo_description?: string | null
    sections: {
      id: string
      section_type_id: string
      layout_variant?: string | null
      content: Record<string, unknown>
      /** Asset ids in `content` resolved to public URLs. Never inside `content`
       *  itself — section content is schema-validated on write. */
      assets?: Record<string, { url: string; alt_text?: string | null }>
      is_visible: boolean
    }[]
  }
  navigation: { label: string; path: string }[]
  theme: Record<string, unknown>
  is_preview: boolean
}

export async function fetchPublicWebsite(
  slug: string,
  pageSlug?: string,
  previewToken?: string
): Promise<PublicWebsitePayload | null> {
  const path = pageSlug
    ? `/v1/public/websites/${slug}/pages/${pageSlug}`
    : `/v1/public/websites/${slug}`
  const qs = previewToken ? `?preview_token=${encodeURIComponent(previewToken)}` : ''
  const res = await fetch(
    `${apiUrl}${path}${qs}`,
    previewToken ? { cache: 'no-store' } : { next: { revalidate: 60, tags: [`website:${slug}`] } }
  )
  if (!res.ok) return null
  const json = (await res.json()) as { data: PublicWebsitePayload }
  return json.data
}

/** Tab title and description for a public Business Website page. The visitor is
 *  on the business's own site, so the business name owns the tab — not LOCAH. */
export function websiteMetadata(data: PublicWebsitePayload | null) {
  if (!data) return {}
  return {
    title: data.page.seo_title || `${data.page.title} | ${data.business.display_name}`,
    description: data.page.seo_description || undefined,
  }
}
