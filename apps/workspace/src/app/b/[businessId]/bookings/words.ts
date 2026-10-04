/** Bookings in the owner's words — never a stored code on the page. */
export const STATUS_WORDS: Record<string, string> = {
  pending: 'Waiting for you to confirm', confirmed: 'Confirmed', checked_in: 'Arrived', completed: 'Done',
  cancelled: 'Cancelled', rejected: 'Declined', no_show: 'Did not come',
}

export const STATUS_TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral' | 'info'> = {
  pending: 'warn', confirmed: 'info', checked_in: 'info', completed: 'good', cancelled: 'neutral',
  rejected: 'neutral', no_show: 'bad',
}

export const MODE_WORDS: Record<string, string> = {
  appointment: 'Appointment', accommodation: 'Stay', table: 'Table', class_session: 'Class', rental: 'Rental',
  site_visit: 'Site visit', event_date: 'Event',
}

export const PAYMENT_WORDS: Record<string, string> = {
  pending: 'Not paid yet', pending_offline: 'Pays at the visit', deposit_paid: 'Deposit paid', paid: 'Paid',
  refunded: 'Refunded',
}

/** The next steps a booking's state allows (validation/booking.py ALLOWED_TRANSITIONS), as buttons. */
export const NEXT_STEPS: Record<string, { to: string; label: string; reason?: string; confirm?: string; quiet?: boolean }[]> = {
  pending: [
    { to: 'confirmed', label: 'Confirm' },
    { to: 'rejected', label: 'Decline', reason: 'Declined by the business', quiet: true,
      confirm: 'Decline this booking? The time is freed for others.' },
  ],
  confirmed: [
    { to: 'checked_in', label: 'Mark as arrived' },
    { to: 'no_show', label: 'Did not come', reason: 'Did not arrive', quiet: true,
      confirm: 'Mark this booking as a no-show?' },
    { to: 'cancelled', label: 'Cancel', reason: 'Cancelled by the business', quiet: true,
      confirm: 'Cancel this booking? The time is freed for others.' },
  ],
  checked_in: [
    { to: 'completed', label: 'Mark as done' },
    { to: 'cancelled', label: 'Cancel', reason: 'Cancelled by the business', quiet: true,
      confirm: 'Cancel this booking?' },
  ],
}

export const FILTERS = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'To confirm' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'completed', label: 'Done' },
  { value: 'cancelled', label: 'Cancelled' },
]

/**
 * What customers book time on: tables, rooms, chairs, studios, courts, halls,
 * vehicles. The booking engine hands a free one to a guest who does not pick
 * (tables to table bookings, rooms to stays) and never gives one away twice.
 */
export const RESOURCE_KINDS: Record<string, {
  label: string; plural: string; mode: 'exclusive' | 'pooled'; granularity: string; seats: string; help: string
}> = {
  table: { label: 'Table', plural: 'Tables', mode: 'exclusive', granularity: 'slot', seats: 'Seats', help: 'Given to table bookings that fit.' },
  room: { label: 'Room', plural: 'Rooms', mode: 'exclusive', granularity: 'date_range', seats: 'Guests', help: 'Given to stays by the night.' },
  chair: { label: 'Chair or treatment room', plural: 'Chairs & treatment rooms', mode: 'exclusive', granularity: 'slot', seats: 'People', help: 'Held with each appointment.' },
  studio: { label: 'Studio (shared places)', plural: 'Studios', mode: 'pooled', granularity: 'slot', seats: 'Places', help: 'Several people at once, up to its places.' },
  court: { label: 'Court or bay', plural: 'Courts & bays', mode: 'exclusive', granularity: 'slot', seats: 'Players', help: 'Booked by the slot.' },
  hall: { label: 'Hall or lawn', plural: 'Halls & lawns', mode: 'exclusive', granularity: 'date_range', seats: 'Guests', help: 'Booked for event dates.' },
  vehicle: { label: 'Vehicle or equipment', plural: 'Vehicles & equipment', mode: 'exclusive', granularity: 'slot', seats: 'People', help: 'Hired for a time range.' },
}
