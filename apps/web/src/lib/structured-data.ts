import { businessSiteUrl } from '@platform/config'
import type { PublicWebsitePayload } from './public-website'

/**
 * Local SEO for a tenant website: one schema.org JSON-LD `@graph` per page,
 * built only from what the public payload carries — the owner's words on the
 * page, the main location's saved facts (`business.place`), the trade from the
 * platform taxonomy (`business.trade`) and what the business's live tools can
 * do (`capabilities`). Nothing is inferred that the owner did not give: no
 * rating without reviews, no price that is not on the page, no cuisine the
 * page does not name.
 *
 * Rendered by the server page components (app/[slug]/page.tsx and
 * app/[slug]/[pageSlug]/page.tsx), never by a client component.
 */

type Json = Record<string, unknown>
type Section = PublicWebsitePayload['page']['sections'][number]

const SCHEMA = 'https://schema.org'

// ---------------------------------------------------------------------------
// What the business is
// ---------------------------------------------------------------------------

/** Taxonomy subcategories with a more exact schema.org type than their playbook. */
const BY_SUBCATEGORY: Record<string, string> = {
  dental: 'Dentist',
  physiotherapy: 'Physiotherapy',
  veterinary: 'VeterinaryCare',
  hospital: 'Hospital',
  pharmacy: 'Pharmacy',
  diagnostic_centre: 'DiagnosticLab',
  bakery: 'Bakery',
  home_bakery: 'Bakery',
  ice_cream: 'IceCreamShop',
  pub_bar: 'BarOrPub',
  fast_food: 'FastFoodRestaurant',
  cloud_kitchen: 'FoodEstablishment',
  barber: 'HairSalon',
  nail_studio: 'NailSalon',
  tattoo_studio: 'TattooParlor',
  spa: 'DaySpa',
  massage_centre: 'DaySpa',
  resort: 'Resort',
  hostel: 'Hostel',
  clothing: 'ClothingStore',
  footwear: 'ShoeStore',
  electronics: 'ElectronicsStore',
  mobile_store: 'MobilePhoneStore',
  furniture: 'FurnitureStore',
  home_decor: 'HomeGoodsStore',
  kitchenware: 'HomeGoodsStore',
  hardware: 'HardwareStore',
  books: 'BookStore',
  toys: 'ToyStore',
  sports_goods: 'SportingGoodsStore',
  jewellery: 'JewelryStore',
  florist: 'Florist',
  pet_shop: 'PetStore',
  pet_supplies: 'PetStore',
  grocery: 'GroceryStore',
  supermarket: 'GroceryStore',
  provision_store: 'GroceryStore',
  lawyer: 'LegalService',
  ca: 'AccountingService',
  accountant: 'AccountingService',
  tax_consultant: 'AccountingService',
  plumber: 'Plumber',
  electrician: 'Electrician',
  painting_contractor: 'HousePainter',
  roofing_contractor: 'RoofingContractor',
  hvac: 'HVACBusiness',
  car_wash: 'AutoWash',
  travel_agency: 'TravelAgency',
}

/** Taxonomy playbooks → the most specific schema.org LocalBusiness type. */
const BY_PLAYBOOK: Record<string, string> = {
  restaurant: 'Restaurant',
  cafe: 'CafeOrCoffeeShop',
  bakery_sweets: 'Bakery',
  home_food: 'FoodEstablishment',
  tiffin: 'FoodEstablishment',
  catering: 'FoodEstablishment',
  meat_seafood: 'Store',
  grocery: 'GroceryStore',
  produce: 'GroceryStore',
  dairy_subscription: 'Store',
  general_retail: 'Store',
  fashion_retail: 'ClothingStore',
  boutique: 'ClothingStore',
  electronics: 'ElectronicsStore',
  furniture_decor: 'FurnitureStore',
  jewellery: 'JewelryStore',
  optical: 'Store',
  pet_shop: 'PetStore',
  florist: 'Florist',
  pharmacy: 'Pharmacy',
  handmade: 'Store',
  gym: 'ExerciseGym',
  studio: 'ExerciseGym',
  salon: 'BeautySalon',
  makeup_artist: 'BeautySalon',
  spa: 'DaySpa',
  clinic: 'MedicalClinic',
  hospital: 'Hospital',
  diagnostics: 'DiagnosticLab',
  therapy: 'MedicalClinic',
  hotel: 'Hotel',
  homestay: 'LodgingBusiness',
  stay: 'LodgingBusiness',
  ngo: 'NGO',
  community: 'NGO',
  contractor: 'HomeAndConstructionBusiness',
  home_service: 'HomeAndConstructionBusiness',
  laundry: 'DryCleaningOrLaundry',
  design_studio: 'ProfessionalService',
  consulting: 'ProfessionalService',
  professional_firm: 'ProfessionalService',
  creative_agency: 'ProfessionalService',
  software: 'ProfessionalService',
  photographer: 'ProfessionalService',
  event_planner: 'ProfessionalService',
  maker: 'ProfessionalService',
  print_shop: 'ProfessionalService',
  security_facility: 'ProfessionalService',
  finance: 'FinancialService',
  real_estate_broker: 'RealEstateAgent',
  real_estate_developer: 'RealEstateAgent',
  auto_service: 'AutoRepair',
  detailing: 'AutoWash',
  vehicle_dealer: 'AutoDealer',
  auto_parts: 'AutoPartsStore',
  travel: 'TravelAgency',
  daycare: 'ChildCare',
}

/** The legacy business type, when the taxonomy has nothing for this business. */
const BY_BUSINESS_TYPE: Record<string, string> = {
  restaurant: 'Restaurant',
  cafe: 'CafeOrCoffeeShop',
  bakery: 'Bakery',
  home_food: 'FoodEstablishment',
  salon: 'BeautySalon',
  spa: 'DaySpa',
  clinic: 'MedicalClinic',
  gym: 'ExerciseGym',
  fitness: 'ExerciseGym',
  hotel: 'Hotel',
  homestay: 'LodgingBusiness',
  retail: 'Store',
  professional_service: 'ProfessionalService',
  real_estate: 'RealEstateAgent',
}

const FOOD = new Set([
  'Restaurant', 'Bakery', 'CafeOrCoffeeShop', 'FoodEstablishment', 'IceCreamShop', 'BarOrPub', 'FastFoodRestaurant',
])

/** A type a catalogue of things to buy (Product + Offer) suits, rather than services. */
function sellsGoods(type: string): boolean {
  return type === 'Store' || type.endsWith('Store') || type === 'Florist'
}

/** Words for "what it is" when the taxonomy gave none ("Konkan Table — Restaurant in …"). */
const TYPE_WORDS: Record<string, string> = {
  Restaurant: 'Restaurant',
  Bakery: 'Bakery',
  CafeOrCoffeeShop: 'Café',
  FoodEstablishment: 'Home kitchen',
  Store: 'Shop',
  ExerciseGym: 'Gym',
  BeautySalon: 'Salon',
  HairSalon: 'Hair salon',
  DaySpa: 'Spa',
  MedicalClinic: 'Clinic',
  Dentist: 'Dental clinic',
  Hotel: 'Hotel',
  LodgingBusiness: 'Stay',
  RealEstateAgent: 'Real estate',
}

export function trade(data: PublicWebsitePayload) {
  return data.business.trade ?? null
}

/** The most specific schema.org type for this business's trade. */
export function businessSchemaType(data: PublicWebsitePayload): string {
  const t = trade(data)
  return (
    (t?.subcategory && BY_SUBCATEGORY[t.subcategory]) ||
    (t?.playbook && BY_PLAYBOOK[t.playbook]) ||
    BY_BUSINESS_TYPE[(data.business.business_type || '').toLowerCase()] ||
    'LocalBusiness'
  )
}

/** "Biryani shop", "Salon" — what the business is, in a page title. */
export function tradeWords(data: PublicWebsitePayload): string {
  return trade(data)?.label || TYPE_WORDS[businessSchemaType(data)] || ''
}

// ---------------------------------------------------------------------------
// Where it is
// ---------------------------------------------------------------------------

function heroOf(data: PublicWebsitePayload): Section | undefined {
  return data.page.sections.find((s) => s.section_type_id === 'hero' && s.is_visible !== false)
}

function str(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function isHome(data: PublicWebsitePayload): boolean {
  const page = data.page as PublicWebsitePayload['page'] & { page_type?: string }
  return page.slug === 'home' || page.page_type === 'home'
}

/**
 * The town people search by ("Indiranagar, Bengaluru"). The API states it from
 * the saved address or the cover line when it names a known town; a payload
 * from before it did falls back to the home cover's place line ("Area, City").
 */
export function locality(data: PublicWebsitePayload): string {
  const said = str(data.business.place?.locality)
  if (said) return said
  if (!isHome(data)) return ''
  const line = str(heroOf(data)?.content?.eyebrow)
  return line.length <= 40 && line.includes(',') && !/\d/.test(line) ? line : ''
}

// ---------------------------------------------------------------------------
// Addresses on the site
// ---------------------------------------------------------------------------

/** A path on this business's site → its absolute URL (canonical form). */
export function siteHref(data: PublicWebsitePayload, path = ''): string {
  if (/^https?:\/\//.test(path)) return path
  const [bare, hash] = path.split('#')
  const base = businessSiteUrl(data.business.slug, bare && bare !== '/' ? bare : '')
  return hash ? `${base}#${hash}` : base
}

/** This page's path on the site: '' for home, '/menu' for an inner page. */
export function pagePath(data: PublicWebsitePayload): string {
  return isHome(data) ? '' : `/${data.page.slug}`
}

// ---------------------------------------------------------------------------
// Titles
// ---------------------------------------------------------------------------

export type PageTitle = { title: string; description?: string }

const TITLE_MAX = 65

/** Cut at a word, under `max` characters. */
function clip(text: string, max: number): string {
  const said = text.replace(/\s+/g, ' ').trim()
  if (said.length <= max) return said
  const cut = said.slice(0, max - 1)
  const at = cut.lastIndexOf(' ')
  return `${(at > max * 0.6 ? cut.slice(0, at) : cut).replace(/[\s,;:.—–-]+$/, '')}…`
}

/** The town, shortened to its first part ("Indiranagar") when the whole
 *  title would run past what a results page shows. */
function within(build: (where: string) => string, where: string): string {
  const full = build(where)
  if (full.length <= TITLE_MAX || !where.includes(',')) return full
  return build(where.split(',')[0].trim())
}

/**
 * The page's title and description.
 *
 * Home: "Konkan Table — Restaurant in Indiranagar, Bengaluru". An inner page:
 * "Menu — Konkan Table, Indiranagar, Bengaluru". A title the owner wrote
 * themselves (anything but the builder's "<page> — <business>" or the bare
 * name) is kept exactly. The description is the page's own SEO description
 * (else the cover's line), at most 155 characters.
 */
export function pageTitle(data: PublicWebsitePayload): PageTitle {
  const name = data.business.display_name
  const where = locality(data)
  const seo = str(data.page.seo_title)
  let title: string
  if (isHome(data)) {
    const what = tradeWords(data)
    title = seo && seo !== name
      ? seo
      : what && where
        ? within((w) => `${name} — ${what} in ${w}`, where)
        : what
          ? `${name} — ${what}`
          : where
            ? within((w) => `${name} — ${w}`, where)
            : name
  } else {
    const tail = [` — ${name}`, ` | ${name}`, ` - ${name}`, ` · ${name}`].find((t) => seo.endsWith(t))
    const label = !seo ? data.page.title : tail ? seo.slice(0, -tail.length).trim() : ''
    title = !label ? seo : where ? within((w) => `${label} — ${name}, ${w}`, where) : `${label} — ${name}`
  }
  const said = str(data.page.seo_description) || str(heroOf(data)?.content?.subheadline)
  return { title, description: said ? clip(said, 155) : undefined }
}

// ---------------------------------------------------------------------------
// Prices, only as the page states them
// ---------------------------------------------------------------------------

const RUPEE = '₹'
const AMOUNT = /(?:₹|\brs\.?|\binr)\s*(\d[\d,]*(?:\.\d+)?)/gi
const FOREIGN = /[$€£¥]|\b(?:usd|eur|gbp|aed)\b/i

/** "₹1,250" → 1250; "₹200–₹400" → 200 with max 400; a price in another
 *  currency, or words with no amount, → null. */
export function priceOf(text: unknown): { value: number; max?: number } | null {
  const said = str(text)
  if (!said || FOREIGN.test(said)) return null
  let amounts = Array.from(said.matchAll(AMOUNT), (m) => Number(m[1].replace(/,/g, '')))
  if (!amounts.length && /^\d[\d,]*(?:\.\d+)?$/.test(said)) amounts = [Number(said.replace(/,/g, ''))]
  amounts = amounts.filter((n) => Number.isFinite(n) && n > 0 && n < 1e8)
  if (!amounts.length) return null
  const max = Math.max(...amounts)
  return max > amounts[0] ? { value: amounts[0], max } : { value: amounts[0] }
}

function rupees(n: number): string {
  return `${RUPEE}${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function offer(price: { value: number; max?: number }, unit?: string): Json {
  const out: Json = { '@type': 'Offer', price: price.value, priceCurrency: 'INR' }
  if (price.max) {
    out.priceSpecification = {
      '@type': 'PriceSpecification', minPrice: price.value, maxPrice: price.max, priceCurrency: 'INR',
    }
  } else if (unit) {
    out.priceSpecification = {
      '@type': 'UnitPriceSpecification', price: price.value, priceCurrency: 'INR',
      unitText: unit.replace(/^(?:per|\/)\s*/i, ''),
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// The page's own content
// ---------------------------------------------------------------------------

type Item = {
  name: string
  description?: string
  category?: string
  price?: { value: number; max?: number }
  unit?: string
  diet?: string
  image?: string
}

function absolute(url: unknown): string {
  const u = str(url)
  return /^https?:\/\//.test(u) ? u : ''
}

/** Every priced or named thing in the page's range sections, once each. */
function rangeItems(data: PublicWebsitePayload): { title: string; items: Item[] } {
  const items: Item[] = []
  let title = ''
  for (const section of data.page.sections) {
    if (section.section_type_id !== 'product_showcase' || section.is_visible === false) continue
    const content = section.content || {}
    title = title || str(content.title)
    const rows = Array.isArray(content.items) ? content.items : []
    rows.forEach((row, i) => {
      if (!row || typeof row !== 'object') return
      const r = row as Record<string, unknown>
      const name = str(r.name)
      if (!name || items.some((it) => it.name === name)) return
      items.push({
        name,
        description: str(r.description) || undefined,
        category: str(r.category) || undefined,
        price: priceOf(r.price) ?? undefined,
        unit: str(r.unit) || undefined,
        diet: str(r.diet).toLowerCase() || undefined,
        image: absolute(section.assets?.[`items.${i}`]?.url) || undefined,
      })
    })
  }
  return { title, items }
}

function faqs(data: PublicWebsitePayload): { q: string; a: string }[] {
  const out: { q: string; a: string }[] = []
  for (const section of data.page.sections) {
    if (section.section_type_id !== 'faq' || section.is_visible === false) continue
    const rows = Array.isArray(section.content?.items) ? (section.content.items as unknown[]) : []
    for (const row of rows) {
      if (!row || typeof row !== 'object') continue
      const q = str((row as Record<string, unknown>).q)
      const a = str((row as Record<string, unknown>).a)
      if (q && a && !out.some((f) => f.q === q)) out.push({ q, a })
    }
  }
  return out
}

/** The cover photograph, then up to four more of the page's pictures. */
export function pageImages(data: PublicWebsitePayload, limit = 5): string[] {
  const urls: string[] = []
  const hero = heroOf(data)
  const cover = absolute(hero?.assets?.image_asset_id?.url)
  if (cover) urls.push(cover)
  for (const section of data.page.sections) {
    if (section.is_visible === false) continue
    for (const [key, asset] of Object.entries(section.assets || {})) {
      const url = absolute(asset?.url)
      if (url && key !== 'logo_asset_id' && !urls.includes(url)) urls.push(url)
      if (urls.length >= limit) return urls
    }
  }
  return urls
}

export function coverImage(data: PublicWebsitePayload | null): string {
  return data ? absolute(heroOf(data)?.assets?.image_asset_id?.url) : ''
}

/** Cuisines a page can name. Only an adjective the owner's words use is
 *  stated; state names that are also places ("Kerala", "Tamil") are left out. */
const CUISINES = [
  'South Indian', 'North Indian', 'Chettinad', 'Konkani', 'Konkan', 'Malvani', 'Goan', 'Mangalorean', 'Udupi',
  'Malabar', 'Andhra', 'Hyderabadi', 'Punjabi', 'Mughlai', 'Awadhi', 'Lucknowi', 'Bengali', 'Gujarati',
  'Rajasthani', 'Maharashtrian', 'Kashmiri', 'Parsi', 'Sindhi', 'Indo-Chinese', 'Chinese', 'Italian', 'Thai',
  'Japanese', 'Korean', 'Mexican', 'Lebanese', 'Mediterranean', 'Continental', 'Arabian', 'Tibetan', 'Burmese',
  'Sri Lankan', 'Vietnamese', 'French', 'Middle Eastern', 'Pan-Asian', 'Turkish', 'Persian', 'Greek', 'Spanish',
]

function pageWords(data: PublicWebsitePayload): string {
  const parts: string[] = [str(data.page.seo_description)]
  for (const section of data.page.sections) {
    if (section.is_visible === false) continue
    const c = section.content || {}
    for (const key of ['headline', 'subheadline', 'text', 'body', 'subtitle', 'title', 'quote']) parts.push(str(c[key]))
    if (section.section_type_id === 'media_text' && Array.isArray(c.items)) {
      for (const row of c.items as Record<string, unknown>[]) parts.push(str(row?.title), str(row?.body))
    }
  }
  return parts.filter(Boolean).join(' \n ')
}

function cuisines(data: PublicWebsitePayload): string[] {
  const words = pageWords(data)
  const found: string[] = []
  for (const name of CUISINES) {
    const pattern = new RegExp(`(^|[^A-Za-z])${name.replace(/[-\s]/g, '[-\\s]')}(?![A-Za-z])`, 'i')
    if (pattern.test(words) && !found.some((f) => f.includes(name) || name.includes(f))) found.push(name)
  }
  return found.slice(0, 4)
}

/** The range's own page: this page when it carries the range, else the page
 *  the home teaser links to, else the navigation entry the catalogue is under. */
function rangePath(data: PublicWebsitePayload): string {
  const showcase = data.page.sections.find((s) => s.section_type_id === 'product_showcase')
  if (showcase && !isHome(data)) return pagePath(data)
  const more = str(showcase?.content?.more_path)
  if (more.startsWith('/')) return more
  const label = str(data.capabilities?.catalogue_label).toLowerCase()
  const nav = (data.navigation || []).find(
    (n) => label && n.label.trim().toLowerCase() === label && n.path.startsWith('/') && n.path !== '/'
  )
  return nav ? nav.path : ''
}

// ---------------------------------------------------------------------------
// The week
// ---------------------------------------------------------------------------

const DAY_NAMES: Record<string, string> = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
}
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/

/** place.hours → OpeningHoursSpecification, one per span shared by its days. */
export function openingHours(hours: unknown): Json[] {
  if (!hours || typeof hours !== 'object') return []
  const byspan = new Map<string, string[]>()
  for (const [day, name] of Object.entries(DAY_NAMES)) {
    const spans = (hours as Record<string, unknown>)[day]
    if (!Array.isArray(spans)) continue
    for (const span of spans) {
      if (!Array.isArray(span) || span.length !== 2) continue
      const [opens, closes] = span.map(String)
      if (!HHMM.test(opens) || !HHMM.test(closes) || opens >= closes) continue
      const key = `${opens}-${closes}`
      byspan.set(key, [...(byspan.get(key) || []), name])
    }
  }
  return Array.from(byspan, ([key, days]) => {
    const [opens, closes] = key.split('-')
    return { '@type': 'OpeningHoursSpecification', dayOfWeek: days, opens, closes }
  })
}

// ---------------------------------------------------------------------------
// The graph
// ---------------------------------------------------------------------------

function postalAddress(data: PublicWebsitePayload): Json | null {
  const place = data.business.place
  const parts = place?.address_parts
  if (parts && (parts.street || parts.area || parts.city || parts.postal_code)) {
    const street = [parts.street, parts.area].filter(Boolean).join(', ')
    const out: Json = { '@type': 'PostalAddress' }
    if (street) out.streetAddress = street
    if (parts.city || parts.area) out.addressLocality = parts.city || parts.area
    if (parts.state) out.addressRegion = parts.state
    if (parts.postal_code) out.postalCode = parts.postal_code
    out.addressCountry = parts.country || 'IN'
    return out
  }
  const said = str(place?.address)
  return said ? { '@type': 'PostalAddress', streetAddress: said, addressCountry: 'IN' } : null
}

function menuNode(id: string, url: string, title: string, items: Item[]): Json {
  const menuItem = (it: Item): Json => {
    const out: Json = { '@type': 'MenuItem', name: it.name }
    if (it.description) out.description = it.description
    if (it.image) out.image = it.image
    if (it.price) out.offers = offer(it.price, it.unit)
    if (it.diet === 'veg' || it.diet === 'vegetarian') out.suitableForDiet = `${SCHEMA}/VegetarianDiet`
    if (it.diet === 'vegan') out.suitableForDiet = `${SCHEMA}/VeganDiet`
    return out
  }
  const sections = new Map<string, Item[]>()
  for (const it of items) sections.set(it.category || '', [...(sections.get(it.category || '') || []), it])
  const node: Json = { '@type': 'Menu', '@id': id, name: title || 'Menu', url }
  if (sections.size === 1 && sections.has('')) {
    node.hasMenuItem = items.map(menuItem)
  } else {
    node.hasMenuSection = Array.from(sections, ([name, rows]) => ({
      '@type': 'MenuSection', name: name || title || 'Menu', hasMenuItem: rows.map(menuItem),
    }))
  }
  return node
}

function catalogueNode(type: string, title: string, items: Item[], pageUrl: string): Json | null {
  if (sellsGoods(type)) {
    // A product is listed only with the price the page gives it.
    const products = items.filter((it) => it.price).map((it) => {
      const p: Json = { '@type': 'Product', name: it.name, offers: { ...offer(it.price!, it.unit), url: pageUrl } }
      if (it.description) p.description = it.description
      if (it.image) p.image = it.image
      if (it.category) p.category = it.category
      return p
    })
    return products.length ? { '@type': 'OfferCatalog', name: title || 'Shop', itemListElement: products } : null
  }
  const services = items.map((it) => {
    const service: Json = { '@type': 'Service', name: it.name }
    if (it.description) service.description = it.description
    if (it.category) service.category = it.category
    return it.price ? { ...offer(it.price, it.unit), itemOffered: service } : { '@type': 'Offer', itemOffered: service }
  })
  return services.length ? { '@type': 'OfferCatalog', name: title || 'Services', itemListElement: services } : null
}

/** The page's JSON-LD graph (see the module comment). */
export function buildJsonLd(data: PublicWebsitePayload, meta: PageTitle): Json {
  const { business, capabilities = {} } = data
  const siteUrl = siteHref(data)
  const pageUrl = siteHref(data, pagePath(data))
  const type = businessSchemaType(data)
  const food = FOOD.has(type)
  const ids = {
    business: `${siteUrl}#business`,
    website: `${siteUrl}#website`,
    page: `${pageUrl}#webpage`,
    breadcrumb: `${pageUrl}#breadcrumb`,
    menu: `${pageUrl}#menu`,
  }
  const languages = (data.website.languages?.length ? data.website.languages : ['en']).map((l) => `${l}-IN`)
  const images = pageImages(data)
  const place = business.place || {}
  const extra: Json[] = []

  // ---- the business
  const org: Json = { '@type': type, '@id': ids.business, name: business.display_name, url: siteUrl }
  if (images.length) org.image = images
  const logo = absolute(data.theme?.logo_url)
  if (logo) org.logo = logo
  if (isHome(data) && meta.description) org.description = meta.description
  const phone = str(place.phone) || str(business.contact?.phone)
  if (phone) org.telephone = phone
  const email = str(business.contact?.email)
  if (email) org.email = email
  const address = postalAddress(data)
  if (address) org.address = address
  if (place.geo && Number.isFinite(place.geo.lat) && Number.isFinite(place.geo.lng)) {
    org.geo = { '@type': 'GeoCoordinates', latitude: place.geo.lat, longitude: place.geo.lng }
    org.hasMap = `https://www.google.com/maps/search/?api=1&query=${place.geo.lat},${place.geo.lng}`
  }
  const hours = openingHours(place.hours)
  if (hours.length) org.openingHoursSpecification = hours

  const range = rangeItems(data)
  const prices = range.items.flatMap((it) => (it.price ? [it.price.value, it.price.max ?? it.price.value] : []))
  if (prices.length) {
    const lo = Math.min(...prices)
    const hi = Math.max(...prices)
    org.priceRange = lo === hi ? rupees(lo) : `${rupees(lo)}–${rupees(hi)}`
  }
  const rangeAt = rangePath(data)
  const rangeUrl = rangeAt ? siteHref(data, rangeAt) : ''
  if (food) {
    const named = cuisines(data)
    if (named.length) org.servesCuisine = named
    if (capabilities.book) org.acceptsReservations = true
    if (range.items.length) {
      extra.push(menuNode(ids.menu, rangeUrl || pageUrl, range.title, range.items))
      org.hasMenu = { '@id': ids.menu }
    } else if (rangeUrl) {
      org.hasMenu = rangeUrl
    }
  } else if (range.items.length) {
    const catalogue = catalogueNode(type, range.title, range.items, rangeUrl || pageUrl)
    if (catalogue) org.hasOfferCatalog = catalogue
  }
  const actions: Json[] = []
  if (capabilities.order) {
    const primary = capabilities.primary === 'order' ? str(capabilities.primary_path) : ''
    const target = siteHref(data, primary || rangeAt || '/checkout')
    actions.push({
      '@type': 'OrderAction',
      target: { '@type': 'EntryPoint', urlTemplate: target, inLanguage: languages[0],
        actionPlatform: [`${SCHEMA}/DesktopWebPlatform`, `${SCHEMA}/MobileWebPlatform`] },
    })
  }
  if (capabilities.book) {
    actions.push({
      '@type': 'ReserveAction',
      target: { '@type': 'EntryPoint', urlTemplate: siteHref(data, '/book'), inLanguage: languages[0],
        actionPlatform: [`${SCHEMA}/DesktopWebPlatform`, `${SCHEMA}/MobileWebPlatform`] },
    })
  }
  if (actions.length) org.potentialAction = actions.length === 1 ? actions[0] : actions

  // ---- the site and this page
  const website: Json = {
    '@type': 'WebSite', '@id': ids.website, url: siteUrl, name: business.display_name,
    inLanguage: languages.length === 1 ? languages[0] : languages, publisher: { '@id': ids.business },
  }
  const questions = faqs(data)
  const webpage: Json = {
    '@type': questions.length ? ['WebPage', 'FAQPage'] : 'WebPage',
    '@id': ids.page,
    url: pageUrl,
    name: meta.title,
    isPartOf: { '@id': ids.website },
    about: { '@id': ids.business },
    inLanguage: languages[0],
  }
  if (meta.description) webpage.description = meta.description
  if (images[0]) webpage.primaryImageOfPage = { '@type': 'ImageObject', url: images[0] }
  if (questions.length) {
    webpage.mainEntity = questions.map(({ q, a }) => ({
      '@type': 'Question', name: q, acceptedAnswer: { '@type': 'Answer', text: a },
    }))
  }
  if (!isHome(data)) {
    webpage.breadcrumb = { '@id': ids.breadcrumb }
    extra.unshift({
      '@type': 'BreadcrumbList',
      '@id': ids.breadcrumb,
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: business.display_name, item: siteUrl },
        { '@type': 'ListItem', position: 2, name: data.page.title, item: pageUrl },
      ],
    })
  }
  return { '@context': SCHEMA, '@graph': [org, website, webpage, ...extra] }
}

/**
 * JSON for a <script type="application/ld+json">: `<`, `>` and `&` written as
 * JSON unicode escapes, so an owner's words can never close the script tag
 * ("</script>") or open a comment; U+2028/2029 likewise.
 */
export function jsonLdText(value: unknown): string {
  const BS = String.fromCharCode(92)
  return JSON.stringify(value)
    .replace(/</g, `${BS}u003c`)
    .replace(/>/g, `${BS}u003e`)
    .replace(/&/g, `${BS}u0026`)
    .replace(new RegExp(String.fromCharCode(0x2028), 'g'), `${BS}u2028`)
    .replace(new RegExp(String.fromCharCode(0x2029), 'g'), `${BS}u2029`)
}
