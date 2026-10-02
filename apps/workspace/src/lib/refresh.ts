import { revalidatePath } from 'next/cache'

/**
 * A change that can move a module's readiness — switching a tool on or off,
 * the first live offering, a published plan, a staff member, pickup turned on,
 * a WhatsApp number connected — changes what the business shell projects: the
 * navigation (active / set up), the business's words (Menu, Reservations),
 * Home's setup list and the Website panel's "what customers can do".
 *
 * Revalidating the business's layout re-renders all of it on the response to
 * the same server action, so the sidebar is right without a reload. The public
 * website is a different app; the API tells it through the outbox
 * (`website.revalidate`). Call only from server actions.
 */
export function refreshBusinessShell(businessId: string) {
  revalidatePath(`/b/${businessId}`, 'layout')
}
