import { platformUrl } from '@platform/config'
const apiUrl = platformUrl('api')

export type BookingOptions = {
  business: { display_name: string; slug: string }
  locations: Array<{ id: string; name: string; status: string; timezone?: string; hours_known?: boolean }>
  offerings: Array<{
    id: string; title: string; description: string | null; offering_type: string; mode: string; minutes: number
    price_amount: number | null; currency: string; capacity: number | null; max_guests: number | null
  }>
  table: { tables: number; max_party: number } | null
  providers: Array<{ id: string; display_name: string; location_ids: string[]; offering_ids: string[] }>
  policy: { require_deposit: boolean; deposit_amount: number | null; cancel_window_hours: number; waitlist_enabled?: boolean }
  payment_methods: string[]
}

export type BookingSlot = { starts_at: string; ends_at: string; label: string; full?: boolean; places_left?: number | null }

export async function fetchBookingOptions(slug: string): Promise<BookingOptions> {
  const res = await fetch(`${apiUrl}/v1/public/websites/${slug}/booking/options`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('Booking options unavailable')
  return (await res.json()).data as BookingOptions
}

async function postJson<T>(path: string, body: unknown, authToken?: string | null): Promise<T> {
  const res = await fetch(`${apiUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) },
    body: JSON.stringify(body),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const message = json?.error?.message || json?.detail?.message || 'That did not work'
    const code = json?.error?.details?.code || json?.detail?.details?.code
    throw Object.assign(new Error(message), { code })
  }
  return json.data as T
}

/** The times open on one day, from the same checks the booking makes (appointment, table, class, site visit). */
export async function fetchBookingSlots(slug: string, body: Record<string, unknown>) {
  return postJson<{ hours_known: boolean; closed: boolean; slots: BookingSlot[] }>(
    `/v1/public/websites/${slug}/booking/slots`, body)
}

/** Stays (check-in/out), rentals (from/until) and event dates: is the range free, and which rooms could take it. */
export async function checkBookingRange(slug: string, body: Record<string, unknown>) {
  return postJson<{ available: boolean; reason: string | null; starts_at: string; ends_at: string;
    resources: { resource_id: string; name: string; resource_type: string }[] }>(
    `/v1/public/websites/${slug}/booking/range`, body)
}

/** Ask to be offered a place in a full class; nothing is booked until the guest takes an offer. */
export async function joinWaitlist(slug: string, body: Record<string, unknown>, authToken?: string | null) {
  return postJson<{ id: string; status: string }>(`/v1/public/websites/${slug}/waitlist`, body, authToken)
}

export async function checkBookingAvailability(slug: string, body: Record<string, unknown>) {
  const res = await fetch(`${apiUrl}/v1/public/websites/${slug}/booking/availability`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Availability check failed')
  return (await res.json()).data as {
    available: boolean
    reason?: string | null
    code?: string
  }
}

/** A signed-in customer's token joins the booking to their own LOCAH record (Founder §12). */
export async function createPublicBooking(slug: string, body: Record<string, unknown>, authToken?: string | null) {
  const res = await fetch(`${apiUrl}/v1/public/websites/${slug}/bookings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) },
    body: JSON.stringify(body),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const message = json?.detail?.message || json?.error?.message || 'Booking failed'
    const code = json?.error?.details?.code || json?.detail?.details?.code || json?.detail?.code
    // The status too: a 409 is "someone else has this time now", which the
    // Book page answers by taking the time away and showing what is still free.
    throw Object.assign(new Error(message), { code, status: res.status })
  }
  return json.data
}

export async function fetchManagedBooking(bookingId: string, token: string) {
  const res = await fetch(
    `${apiUrl}/v1/public/bookings/${bookingId}?token=${encodeURIComponent(token)}`,
    { cache: 'no-store' }
  )
  if (res.status === 404) return null
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const code = json?.detail?.details?.code
    if (code === 'expired_link') return { expired: true as const }
    throw new Error('Booking unavailable')
  }
  return { expired: false as const, booking: json.data }
}

export async function cancelManagedBooking(
  bookingId: string,
  token: string,
  reason: string
) {
  const res = await fetch(`${apiUrl}/v1/public/bookings/${bookingId}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, reason }),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const message = json?.detail?.message || 'Cancel failed'
    const code = json?.detail?.details?.code
    throw Object.assign(new Error(message), { code })
  }
  return json.data
}

export async function rescheduleManagedBooking(
  bookingId: string,
  token: string,
  starts_at: string,
  ends_at: string
) {
  const res = await fetch(`${apiUrl}/v1/public/bookings/${bookingId}/reschedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, starts_at, ends_at }),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const message = json?.detail?.message || 'Reschedule failed'
    const code = json?.detail?.details?.code
    throw Object.assign(new Error(message), { code })
  }
  return json.data
}

export type WaitlistOffer = {
  business: { display_name: string; slug: string }
  title: string
  starts_at: string
  ends_at: string
  party_size: number
  status: string
  offer_expires_at: string | null
  can_take: boolean
}

/** A waitlist offer as its link shows it; null when the link is not (or no longer) valid. */
export async function fetchWaitlistOffer(slug: string, entryId: string, token: string): Promise<WaitlistOffer | null> {
  const res = await fetch(
    `${apiUrl}/v1/public/websites/${slug}/waitlist/${entryId}?t=${encodeURIComponent(token)}`,
    { cache: 'no-store' }
  )
  if (!res.ok) return null
  return (await res.json()).data as WaitlistOffer
}

export async function claimWaitlistOffer(slug: string, entryId: string, token: string) {
  const res = await fetch(`${apiUrl}/v1/public/websites/${slug}/waitlist/${entryId}/claim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const code = json?.error?.details?.code || json?.detail?.details?.code
    throw Object.assign(new Error(json?.error?.message || 'Could not take the place'), { code })
  }
  return json.data as { id: string; booking_number: string; management_token: string }
}
