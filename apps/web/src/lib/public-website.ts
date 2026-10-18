import type { Metadata } from 'next'
import { platformUrl } from '@platform/config'
import { LANG_LOCALE, isSiteLang, offered } from './site-words'
import { locality, pagePath, pageTitle, siteHref } from './structured-data'
const apiUrl = platformUrl('api')

/** How a stock photograph is credited: the photographer and the source, with
 *  the links the source asks for (Unsplash: referral links; Pixabay: the source). */
export type PhotoCredit = {
  line: string
  name?: string
  name_url?: string
  source?: string
  source_url?: string
  page_url?: string
}

export type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'

/** The main location, in words (address, hours_summary, phone) and as facts a
 *  machine reads — each only when the owner saved it. */
export type PublicPlace = {
  address?: string
  hours_summary?: string
  phone?: string
  /** The saved week as HH:MM spans; a day left out is closed. */
  hours?: Partial<Record<Weekday, [string, string][]>>
  /** The location's own timezone ("Asia/Kolkata"), with the hours. */
  timezone?: string
  /** The saved address in parts (none for a digital-only business). */
  address_parts?: {
    street?: string
    area?: string
    city?: string
    state?: string
    postal_code?: string
    country?: string
  }
  /** The map pin the owner set (none for a digital-only business). */
  geo?: { lat: number; lng: number }
  /** The town people search by: "Anna Nagar, Chennai". */
  locality?: string
}

export type PublicWebsitePayload = {
  business: {
    id: string
    slug: string
    display_name: string
    business_type?: string | null
    /** Only what the owner published: a number to call or WhatsApp, an email. */
    contact?: { phone?: string; whatsapp?: string; email?: string }
    /** Where and when to find them: the main location as the owner keeps it today. */
    place?: PublicPlace
    /** What the business is, from the platform taxonomy ("Biryani shop",
     *  playbook "restaurant"). Null when the business never said. */
    trade?: { category: string; subcategory?: string; label: string; playbook: string } | null
  }
  /** What a visitor can actually do here, from the business's live modules.
   *  Sections read this instead of assuming from their own type. */
  capabilities?: Record<string, boolean | string | null>
  /** The business's connected WhatsApp number, when a WhatsApp journey
   *  (order, book, ask) can run right now: "menu" is already typed. */
  whatsapp?: { href: string; label: string; journeys: string[] } | null
  /** languages: the site's own words, first shown first (P1-10E6). */
  website: { status: string; languages?: string[]; published_version_id?: string | null }
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
      assets?: Record<string, { url: string; alt_text?: string | null; credit?: PhotoCredit | null }>
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

/** Tab title, description, canonical address and share card for a public
 *  Business Website page. The visitor is on the business's own site, so the
 *  business name owns the tab — not LOCAH. A preview is never indexed.
 *
 *  `lang` is an explicit ?lang= the page was opened with: a language the site
 *  offers (other than its first) is its own canonical, and every language the
 *  site speaks is listed as an alternate (hreflang). */
export function websiteMetadata(
  data: PublicWebsitePayload | null,
  opts: { lang?: string | null } = {}
): Metadata {
  if (!data) return {}
  const { title, description } = pageTitle(data)
  const path = pagePath(data)
  const home = siteHref(data, path)
  const languages = offered(data.website.languages)
  const asked = isSiteLang(opts.lang) && languages.includes(opts.lang) && opts.lang !== languages[0] ? opts.lang : null
  const url = asked ? `${home}?lang=${asked}` : home
  // Each publish gets its own card address, so a chat app that cached the old
  // card shows the new cover after the owner republishes.
  const version = data.website.published_version_id
  const image = `${siteHref(data, `${path}/opengraph-image`)}${version ? `?v=${version.slice(0, 8)}` : ''}`
  const where = locality(data)
  const alternates: NonNullable<Metadata['alternates']> = { canonical: url }
  if (languages.length > 1) {
    alternates.languages = Object.fromEntries([
      ...languages.map((l, i) => [LANG_LOCALE[l], i === 0 ? home : `${home}?lang=${l}`]),
      ['x-default', home],
    ])
  }
  return {
    title,
    description,
    alternates,
    openGraph: {
      type: 'website',
      title,
      description,
      url,
      siteName: data.business.display_name,
      locale: LANG_LOCALE[asked ?? languages[0]].replace('-', '_'),
      images: [{ url: image, width: 1200, height: 630,
        alt: where ? `${data.business.display_name}, ${where}` : data.business.display_name }],
    },
    twitter: { card: 'summary_large_image', title, description, images: [image] },
    ...(data.is_preview ? { robots: { index: false, follow: false } } : {}),
  }
}
