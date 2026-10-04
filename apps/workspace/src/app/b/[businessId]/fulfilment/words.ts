/** Pickup and delivery jobs in the owner's words. */
export function statusWords(mode: string): Record<string, string> {
  const pickup = mode !== 'delivery' && mode !== 'shipping'
  return {
    pending: 'Received', preparing: 'Being prepared', ready: pickup ? 'Ready for pickup' : 'Ready to send',
    out_for_delivery: mode === 'shipping' ? 'Shipped' : 'Out for delivery', delivered: pickup ? 'Collected' : 'Delivered',
    failed: "Couldn't be completed", cancelled: 'Cancelled',
  }
}

/** What moving a job to a step is called on its button. */
export function moveWords(mode: string): Record<string, string> {
  const pickup = mode !== 'delivery' && mode !== 'shipping'
  return {
    preparing: 'Start preparing', ready: pickup ? 'Ready for pickup' : 'Ready to send',
    out_for_delivery: mode === 'shipping' ? 'Mark as shipped' : 'Send out for delivery',
    delivered: pickup ? 'Collected by the customer' : 'Delivered', failed: "Couldn't complete", cancelled: 'Cancel',
  }
}

export const MODE_WORDS: Record<string, string> = { pickup: 'Pickup', delivery: 'Delivery', shipping: 'Shipping' }
