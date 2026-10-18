# Conversion and local SEO

## The action ladder (every page)

1. **The live tool** — Order now (checkout), Book (the Book page), See plans /
   Ask to join, Get a quote. Only when the module is *ready*
   (`website/capabilities.py`); an action the business cannot fulfil is never
   shown.
2. **The channel** — WhatsApp (prefilled with what the visitor was looking at:
   the dish, the plan, the service) or Call.
3. **The place** — directions, hours.

One primary per screen. The header carries the live tool; the cover carries it
again with one quiet link; the phone bar carries it plus one channel (never
three buttons). After the cover scrolls away on desktop, a compact **action
dock** (bottom-right or bottom-centre) keeps the primary + channel within
reach; it hides near the closing band and the footer.

## Honest urgency and trust

- **Open now / Opens at 7** chip from the location's real hours (never invented);
  in the header utility line and the dock.
- **Today**: "Booking today: 6 slots" only from live availability.
- **Made to order**: "Order by 2 pm for tomorrow" from the owner's lead time.
- **Proof**: the owner's own numbers (since 1987, 12 cuts), reviews only from the
  Reviews module, no invented ratings or testimonials.

## Friction

- Checkout: guest by default, sign-in optional; pickup preselected when it is
  the only mode; prices from the server; the confirmation reads like the
  business's receipt (number, how to pay, lines, total, track).
- Booking: service → day strip (next 7 days) → times → details → confirm; a
  live summary card; the confirm button always visible.
- Forms: three fields max (name, phone or email, message), purpose preset from
  the button that opened it.

## Local SEO (every published site)

**JSON-LD** in the page `<head>` (one `@graph`):
- The business: the most specific schema.org type for the trade (Restaurant,
  Bakery, CafeOrCoffeeShop, Store, ExerciseGym, BeautySalon, HairSalon, DaySpa,
  MedicalClinic, Dentist, ProfessionalService, Hotel, LodgingBusiness, NGO,
  HomeAndConstructionBusiness; LocalBusiness otherwise) with `name`, `url`,
  `image` (hero + up to 4), `telephone`, `address` (PostalAddress from the
  location), `geo` when known, `openingHoursSpecification` from the location's
  structured hours, `priceRange` from the live catalogue (₹ min–max),
  `servesCuisine` (food), `acceptsReservations` (bookings ready), `hasMenu`
  (the range page URL for food), `areaServed` (delivery areas), `sameAs`
  (social links the owner gave), `potentialAction` (OrderAction/ReserveAction
  pointing at /checkout or /book only when ready).
- `WebSite` + `WebPage` per page; `BreadcrumbList` on inner pages.
- `FAQPage` from the page's FAQ section (questions and answers verbatim).
- `Menu` → `MenuSection` → `MenuItem` (+ `Offer` price INR) for food ranges;
  `OfferCatalog` / `Product` + `Offer` for retail; `Service` (+ `Offer`) for
  service menus.
- Never: AggregateRating without real reviews; prices the owner did not give.

**Metadata**: `<title>` "Page — Business, Locality" (home: "Business — what it is
in Locality"); description from the page's own SEO description (≤ 155 chars);
canonical per page; `og:title/description/image/url/type=website`,
`twitter:card=summary_large_image`; an **OG image** generated per page (the
cover photo, the business name in its display face, the locality) via
`next/og`; `robots` noindex on previews and private pages; `hreflang` for the
site's languages.

**Structure**: one `h1` per page (the cover headline), sections as `h2`, real
`<nav>`, `<main>`, `<footer>`; descriptive alt text from the photo pipeline;
links with words, not "click here"; the address and phone as text (NAP the same
everywhere).

**Speed** is SEO: hero image `fetchpriority=high` with `srcset`, everything else
lazy; fonts `display: swap`; motion and WebGL code after hydration; no layout
shift from late fonts or images (aspect-ratio on every frame).
