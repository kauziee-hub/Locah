/**
 * Workspace navigation (Business OS Guide §3 "Recommended Workspace navigation
 * model"; Doc 05 §9.1 NAV-007–NAV-011). Twelve areas in a fixed order; what
 * sits inside each is a projection of the tools this business runs and what
 * this person may do. An area with nothing inside for this person is not shown
 * — "the Workspace expands only as relevant capabilities become active".
 *
 * Module state comes from the API's `navigation_modules` (module readiness:
 * entitled, switched on, set up). `active` is an operational destination;
 * `setup_required` is shown only to people who can complete setup
 * (`modules.configure`), marked as such, never as operational (NAV-008).
 * Labels follow the business's own words (`terms`: Menu, Reservations, Guests)
 * while routes stay the same (Doc 07 §3.3). This only decides what is shown;
 * the API decides what anyone may actually do.
 */

/** `href` is relative to the business (`/orders` → /b/{id}/orders); a leading `~`
 *  names another full-screen surface (`~/pos` → /pos/{id}). */
export type NavChild = {
  href: string
  label: string
  perm?: string
  anyPerm?: string[]
  module?: string
  /** 'solo': only when one person runs the business; 'team': never then (OM-21). */
  shape?: 'solo' | 'team'
  /** Which of the business's own words names this destination (`terms` from the API). */
  term?: 'offerings' | 'bookings' | 'customers'
  /** A deployment switch from the API's `features` that must be on (e.g. the AI sandbox). */
  feature?: string
}
/** A destination as shown: `setup` marks a tool waiting for its setup. */
export type NavItem = { href: string; label: string; setup?: boolean }
export type NavArea = { key: string; label: string; children: NavChild[] }

export const AREAS: NavArea[] = [
  {
    key: 'home',
    label: 'Home',
    children: [
      { href: '', label: 'Home' },
      // One person, one calendar (MD §22 "Solo professionals … one calendar").
      { href: '/calendar', label: 'Calendar', shape: 'solo' },
    ],
  },
  {
    key: 'presence',
    label: 'Business presence',
    children: [
      { href: '/profile', label: 'Profile', perm: 'business.update' },
      { href: '/website', label: 'Website', perm: 'website.edit' },
      { href: '/brand', label: 'Brand & media', perm: 'business.update' },
      { href: '/marketplace', label: 'Marketplace', perm: 'marketplace.configure' },
      { href: '/locations', label: 'Locations', perm: 'locations.update' },
    ],
  },
  {
    key: 'operate',
    label: 'Sell & serve',
    children: [
      { href: '~/pos', label: 'Counter (POS)', perm: 'pos.use', module: 'pos' },
      { href: '/orders', label: 'Orders', perm: 'orders.read', module: 'orders' },
      { href: '~/kds', label: 'Kitchen display', perm: 'kitchen.read', module: 'kitchen' },
      { href: '/kitchen', label: 'Kitchen stations', perm: 'kitchen.configure', module: 'kitchen' },
      { href: '/bookings', label: 'Bookings', perm: 'bookings.read', module: 'bookings', term: 'bookings' },
      { href: '/queue', label: 'Queue', perm: 'queue.read', module: 'queue-operations' },
      { href: '/tasks', label: 'Tasks', perm: 'tasks.read', module: 'tasks' },
      { href: '/attendance', label: 'Check-ins', perm: 'attendance.read', module: 'attendance' },
      { href: '/fulfilment', label: 'Deliveries & pickup', perm: 'fulfilment.read', module: 'fulfilment' },
      { href: '/dispatch', label: 'Dispatch', perm: 'dispatch.assign', module: 'dispatch' },
      { href: '/crew', label: 'My jobs', perm: 'dispatch.update_status', module: 'dispatch' },
      { href: '/memberships', label: 'Memberships', perm: 'memberships.read', module: 'memberships' },
      { href: '/quotes', label: 'Quotes', perm: 'quotes.read', module: 'quotes' },
      { href: '/projects', label: 'Projects', perm: 'projects.read', module: 'projects' },
      { href: '/jobs', label: 'Job cards', perm: 'jobs.read', module: 'jobs' },
      { href: '/academics', label: 'Courses & batches', perm: 'academics.read', module: 'academics' },
    ],
  },
  {
    key: 'offerings',
    label: 'Offerings',
    children: [
      { href: '/offerings', label: 'Products & services', perm: 'offerings.read', module: 'offerings-catalog', term: 'offerings' },
      { href: '/inventory', label: 'Stock', perm: 'inventory.read', module: 'inventory' },
      { href: '/buying', label: 'Buying', perm: 'procurement.read', module: 'procurement' },
      { href: '/recipes', label: 'Recipes', perm: 'procurement.read', module: 'recipes' },
      { href: '/inventory/transfers', label: 'Transfers', perm: 'inventory.read', module: 'inventory' },
      { href: '/inventory/vans', label: 'Van stock', perm: 'inventory.read', module: 'inventory' },
    ],
  },
  {
    key: 'customers',
    label: 'Customers',
    children: [
      { href: '/customers', label: 'Customers', perm: 'customers.read', module: 'customer-relationships', term: 'customers' },
      { href: '/leads', label: 'Enquiries', perm: 'leads.read', module: 'leads' },
      { href: '/reviews', label: 'Reviews', perm: 'reviews.read', module: 'reviews' },
      { href: '/loyalty', label: 'Loyalty', perm: 'loyalty.read', module: 'loyalty' },
      { href: '/documents', label: 'Documents & requests', perm: 'documents.read', module: 'documents' },
      { href: '/forms', label: 'Forms', perm: 'documents.read', module: 'documents' },
    ],
  },
  {
    key: 'money',
    label: 'Money',
    children: [
      { href: '/invoices', label: 'Bills & invoices', perm: 'invoices.read', module: 'invoicing' },
      { href: '/payments', label: 'Payments', perm: 'payments.read', module: 'payments' },
      { href: '/khata', label: 'Khata (credit book)', perm: 'ledger.read', module: 'ledger' },
      { href: '/expenses', label: 'Expenses', perm: 'expenses.read', module: 'expenses' },
      { href: '/donations', label: 'Donations', perm: 'donations.read', module: 'donations' },
      { href: '/invoices/tax-rates', label: 'Tax rates', perm: 'invoices.read', module: 'invoicing' },
      { href: '/pos/shifts', label: 'Counter shifts', perm: 'pos.approve', module: 'pos' },
      { href: '/invoices/reports', label: 'Reports for your CA', perm: 'invoices.export', module: 'invoicing' },
    ],
  },
  {
    key: 'team',
    label: 'Team',
    children: [
      { href: '/team', label: 'People', perm: 'team.read', shape: 'team' },
      { href: '/team/roles', label: 'Roles', perm: 'team.read', shape: 'team' },
      { href: '/workforce', label: 'Staff & rota', perm: 'workforce.read', module: 'workforce', shape: 'team' },
    ],
  },
  {
    key: 'reach',
    label: 'Reach',
    children: [
      { href: '/inbox', label: 'WhatsApp inbox', perm: 'messaging.read', module: 'messaging' },
      { href: '/whatsapp', label: 'WhatsApp', perm: 'messaging.read', module: 'messaging' },
      { href: '/marketing', label: 'Campaigns', perm: 'marketing.read', module: 'marketing' },
      { href: '/marketing/offers', label: 'Offers & coupons', perm: 'marketing.read', module: 'marketing' },
    ],
  },
  {
    key: 'insights',
    label: 'Insights',
    // Basic insights from real data (IS-01) are part of the Workspace; the deeper Analytics tool comes later.
    children: [{ href: '/insights', label: 'Your numbers', anyPerm: ['orders.read', 'bookings.read', 'invoices.read', 'payments.read'] }],
  },
  {
    key: 'ai',
    label: 'AI employees',
    children: [
      { href: '/ai-employees', label: 'AI staff', perm: 'ai_employees.read', module: 'ai-employees' },
      // A labelled demonstration on the business's real records; it needs no module (nothing runs).
      { href: '/ai-employees/sandbox', label: 'AI sandbox', perm: 'ai_employees.read', feature: 'ai_sandbox' },
    ],
  },
  {
    key: 'modules',
    label: 'Modules & integrations',
    children: [{ href: '/modules', label: 'Tools', perm: 'modules.read' }],
  },
  {
    key: 'settings',
    label: 'Settings',
    children: [
      { href: '/settings', label: 'Business settings', perm: 'settings.read' },
      { href: '/settings/business', label: 'How your business works', perm: 'settings.read' },
      { href: '/settings/invoicing', label: 'Tax & invoicing', perm: 'invoices.read', module: 'invoicing' },
      { href: '/settings/counter', label: 'Counter billing', perm: 'pos.use', module: 'pos' },
      { href: '/settings/automations', label: 'Automations', perm: 'settings.read' },
      { href: '/compliance', label: 'Licences & due dates', perm: 'compliance.read', module: 'compliance' },
      { href: '/settings/usage', label: 'Usage & limits', perm: 'settings.read' },
      // A solo business has no team menus; this is how a second person joins.
      { href: '/team', label: 'Invite someone', perm: 'team.read', shape: 'solo' },
    ],
  },
]

// `active` from navigation_modules; `ready`/`enabled` only from an older API
// that sent raw activation states.
const OPERATIONAL = new Set(['active', 'ready', 'enabled'])
const SETUP = 'setup_required'

/** "Sell & serve" reads as what this business actually does. */
function operateLabel(on: (m: string) => boolean): string {
  const sells = on('orders') || on('quotes') || on('pos')
  const serves = on('bookings') || on('memberships')
  if (sells && serves) return 'Sell & serve'
  if (serves) return 'Serve'
  if (sells) return 'Sell'
  return 'Operate'
}

export function visibleAreas(
  moduleStates: Record<string, string>,
  permissions: string[] | null,
  solo = false,
  terms: Record<string, string> = {},
  features: Record<string, boolean> = {},
): { key: string; label: string; children: NavItem[] }[] {
  const on = (m: string) => OPERATIONAL.has(moduleStates[m] ?? '')
  // Before the context loads (or if it fails) show only Home, never a guess.
  const perms = permissions ? new Set(permissions) : null
  const canSetUp = perms !== null && perms.has('modules.configure')
  const settingUp = (c: NavChild) => Boolean(c.module) && moduleStates[c.module!] === SETUP && canSetUp
  const may = (c: NavChild) =>
    (!c.shape || (c.shape === 'solo') === solo) &&
    (!c.feature || features[c.feature] === true) &&
    (!c.module || on(c.module) || settingUp(c)) &&
    (!c.perm || (perms !== null && perms.has(c.perm))) &&
    (!c.anyPerm || (perms !== null && c.anyPerm.some((p) => perms.has(p))))
  return AREAS.map((a) => ({
    key: a.key,
    label: a.key === 'operate' ? operateLabel(on) : a.label,
    children: a.children.filter(may).map((c) => ({
      href: c.href,
      label: (c.term && terms[c.term]) || c.label,
      ...(c.module && !on(c.module) ? { setup: true } : {}),
    })),
  })).filter((a) => a.children.length > 0)
}
