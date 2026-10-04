/** Where the thing a payment was for lives in the Workspace. */
export function sourceHref(businessId: string, type: string, id: string): string {
  const b = `/b/${businessId}`
  return ({ order: `${b}/orders/${id}`, booking: `${b}/bookings/${id}`, invoice: `${b}/invoices/${id}`,
    khata: `${b}/khata/${id}`, membership: `${b}/memberships/${id}` } as Record<string, string>)[type]
    ?? `${b}/payments`
}
