"""The Business OS module catalogue (Capability Universe §5, §6; Business OS Guide §4).

One entry per entitlement key. It says, in the owner's words, what a module
does, what it lets customers do, what it lets staff do, and which setup steps
must be true before any surface may present it as working (Guide §4: "A
module should never be presented to a business as working until its data,
API, permissions and real UI are complete").

Keys follow the Capability Universe except where the First Launch registry
already had the key (MD §1: "the registry key wins"): the MD's `queue` is the
registry's `queue-operations`, and the MD's `insights` is the registry's
`analytics`. `trade-network` (ChitBridge link) is distinct from the registry's
`b2b-network` (supplier discovery, P6).

`built` is the honesty switch: only modules whose data, API, permissions and
UI exist in this codebase are built. A module that is not built is never
enabled, never offered as working, and never shown on a website.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# MD key -> registry key (MD §1 reconciliation; ledger OD-01).
KEY_ALIASES: dict[str, str] = {
    "queue": "queue-operations",
    "insights": "analytics",
    "offerings": "offerings-catalog",
    "crm": "customer-relationships",
    "website": "core-website",
    "marketplace": "core-marketplace-presence",
}

# Storefront (§5): always on for every business, never a choice.
STOREFRONT = ("core-website", "core-marketplace-presence", "customer-relationships", "reviews",
              "messaging", "analytics", "compliance")


@dataclass(frozen=True)
class SetupStep:
    key: str
    label: str  # what the owner does, in plain words


@dataclass(frozen=True)
class ModuleInfo:
    key: str
    label: str
    phase: str  # P0 (First Launch) .. P5, FUTURE
    does: str
    customer_can: tuple[str, ...] = ()
    staff_can: tuple[str, ...] = ()
    setup: tuple[SetupStep, ...] = ()
    packs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    # Semantic website capabilities this module contributes when ready (see
    # platform_core.website.capabilities). Never shown when the module is not ready.
    site: tuple[str, ...] = ()
    marketplace_actions: tuple[str, ...] = ()
    surfaces: tuple[str, ...] = ("workspace",)
    built: bool = False
    future: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def _s(key: str, label: str) -> SetupStep:
    return SetupStep(key, label)


MODULES: dict[str, ModuleInfo] = {m.key: m for m in (
    # ---------------------------------------------------------- First Launch, extended
    ModuleInfo(
        "offerings-catalog", "Products & services", "P0",
        "One catalogue for everything you sell: products, weighed items, menu, services, classes, rooms, plans, packages, projects and more.",
        customer_can=("Browse what you offer with prices",),
        staff_can=("Add and price offerings", "Hide or archive items"),
        setup=(_s("offering_live", "Add at least one offering customers can see"),),
        packs=("commerce",), site=("catalogue",), built=True,
    ),
    ModuleInfo(
        "orders", "Orders", "P0",
        "Take orders from your website, Marketplace, WhatsApp and counter into one list.",
        customer_can=("Add to cart and check out", "See order status in My Activity"),
        staff_can=("Accept, prepare and complete orders", "Cancel with a reason"),
        setup=(_s("priced_product", "Add a product with a price"), _s("payment_method", "Choose how customers pay")),
        packs=("commerce",), depends_on=("offerings-catalog",),
        site=("cart", "checkout", "my_orders"), marketplace_actions=("order",), built=True,
    ),
    ModuleInfo(
        "payments", "Payments", "P0",
        "Collect money for orders, bookings and plans, and refund it when you need to.",
        customer_can=("Pay online, at the business or on delivery",),
        staff_can=("See every payment and its state", "Refund"),
        setup=(_s("payment_method", "Choose how customers pay"),),
        packs=("commerce",), built=True,
    ),
    ModuleInfo(
        "inventory", "Stock", "P0",
        "Know what you have at each location; online and counter sales take from the same stock.",
        staff_can=("Record opening stock", "Adjust and receive stock", "See low stock"),
        setup=(_s("stock_recorded", "Record stock for at least one item"),),
        packs=("commerce",), depends_on=("offerings-catalog",), built=True,
    ),
    ModuleInfo(
        "fulfilment", "Pickup & delivery", "P0",
        "Pickup and local delivery for orders, with a tracking page customers can open.",
        customer_can=("Choose pickup or delivery", "Track the order"),
        staff_can=("Move orders through preparing, ready, out for delivery",),
        setup=(_s("fulfilment_mode", "Turn on pickup or delivery"),),
        packs=("commerce", "delivery"), depends_on=("orders",), site=("track_order",), built=True,
    ),
    ModuleInfo(
        "bookings", "Bookings", "P0",
        "Appointments, tables, rooms, classes, rentals, site visits and event dates — each with its own rules.",
        customer_can=("Pick a date and time and book", "Manage or cancel their booking"),
        staff_can=("See the calendar", "Confirm, check in, complete, cancel"),
        setup=(_s("bookable_offering", "Add a service, room, table, class or staff member people can book"),),
        packs=("appointments", "stays"), depends_on=("offerings-catalog",),
        site=("book", "my_bookings"), marketplace_actions=("book",), built=True,
    ),
    ModuleInfo(
        "memberships", "Memberships & plans", "P0",
        "Plans people join and renew: gym access, session packs, subscriptions, AMCs, fee plans and dues.",
        customer_can=("See plans and join", "See their membership and renew"),
        staff_can=("Enrol members", "Pause or cancel", "See who is expiring"),
        setup=(_s("plan_live", "Publish at least one plan"),),
        packs=("memberships",), depends_on=("payments",),
        site=("plans", "join", "my_membership"), marketplace_actions=("join",), built=True,
    ),
    ModuleInfo(
        "workforce", "Staff & providers", "P0",
        "Your people and when they work, so bookings go to someone who is available.",
        staff_can=("Add staff and providers", "Set availability"),
        setup=(_s("provider_added", "Add at least one staff member"),),
        packs=("appointments",), built=True,
    ),
    ModuleInfo(
        "customer-relationships", "Customers", "P0",
        "Every customer's history in one place: orders, bookings, notes and consent.",
        staff_can=("See a customer's timeline", "Add notes and tags"),
        packs=("storefront",), built=True,
    ),
    ModuleInfo(
        "leads", "Enquiries", "P0",
        "Every enquiry — website, Marketplace, WhatsApp — becomes a lead someone follows up.",
        customer_can=("Send an enquiry",),
        staff_can=("Assign and follow up", "Mark won or lost"),
        packs=("sales",), site=("enquire",), marketplace_actions=("enquire",), built=True,
    ),
    ModuleInfo(
        "quotes", "Quotes", "P0",
        "Versioned quotes customers open, accept or decline online, then convert.",
        customer_can=("Request a quote", "View and accept a quote"),
        staff_can=("Draft, issue and revise quotes",),
        packs=("sales", "trade"), site=("request_quote",), marketplace_actions=("request_quote",), built=True,
    ),
    ModuleInfo(
        "projects", "Projects", "P0",
        "Committed work tracked through phases and tasks to completion.",
        staff_can=("Plan phases and tasks", "Assign people"),
        packs=("sales",), built=True,
    ),
    # ---------------------------------------------------------- New in the Capability Universe
    ModuleInfo(
        "invoicing", "Invoices & GST", "P1",
        "Correctly numbered tax invoices, bills of supply and credit notes, with CA-ready exports.",
        customer_can=("Receive a bill as PDF and on WhatsApp", "See invoices in My Activity"),
        staff_can=("Issue and cancel invoices", "Raise credit notes", "Export for the CA"),
        setup=(_s("tax_profile", "Tell LOCAH how you bill and your GST registration (or that you are not registered)"),),
        packs=("commerce", "trade", "back_office"), site=("my_invoices",), built=True,
    ),
    ModuleInfo(
        "pos", "Counter billing", "P1",
        "Bill at the counter: scan or search, hold bills, take cash/UPI/card/khata, and close the drawer.",
        staff_can=("Open and close a shift", "Bill, hold, return", "Print or WhatsApp the receipt"),
        setup=(_s("register_created", "Create a counter register"),),
        packs=("commerce",), depends_on=("offerings-catalog", "invoicing"), surfaces=("pos",), built=True,
    ),
    ModuleInfo(
        "ledger", "Khata / credit book", "P1",
        "Who owes you and whom you owe, with limits, ageing and WhatsApp statements.",
        customer_can=("See what they owe and pay it",),
        staff_can=("Give credit within a limit", "Record settlements", "Send statements"),
        packs=("commerce", "trade", "back_office"), built=True,
    ),
    ModuleInfo(
        "messaging", "WhatsApp & messages", "P1",
        "One inbox for customer conversations, templates and consent; orders and bookings from chat land in LOCAH.",
        customer_can=("Order, book, pay and track on WhatsApp",),
        staff_can=("Reply from one inbox", "Hand chats to the right person"),
        setup=(_s("channel_connected", "Connect your WhatsApp number"),),
        packs=("storefront",), marketplace_actions=("whatsapp",), built=True,
    ),
    ModuleInfo(
        "reviews", "Reviews", "P1",
        "Verified reviews from real customers; reply, report, and feature the best on your website.",
        customer_can=("Review after a completed order, booking or visit",),
        staff_can=("Reply", "Report a violation", "Feature reviews on the website"),
        packs=("storefront",), site=("reviews",), built=True,
    ),
    ModuleInfo(
        "compliance", "Licences & deadlines", "P1",
        "Your licences and filing dates in one calendar, with reminders before anything expires.",
        staff_can=("Record licences and due dates", "Get reminded before expiry"),
        packs=("storefront", "back_office"), built=True,
    ),
    ModuleInfo(
        "analytics", "Insights", "P1",
        "Numbers computed from your real orders, bookings and payments — never estimates.",
        staff_can=("See sales, bookings and collections",),
        packs=("storefront",),
    ),
    ModuleInfo(
        "dispatch", "Dispatch", "P2",
        "After the order exists, a person picks it up, carries it, and marks it delivered. Status and times. A live location only when a device is actually sharing one.",
        customer_can=("See how far the delivery has got",),
        staff_can=("Assign a delivery", "Mark picked up, out for delivery, delivered or failed"),
        packs=("delivery", "field_service"), depends_on=("fulfilment",), surfaces=("workspace", "crew"),
        site=("track_order",), built=True,
    ),
    ModuleInfo(
        "queue-operations", "Walk-in queue", "P2",
        "Tokens for walk-ins, a live queue board, and a WhatsApp nudge when it's nearly their turn.",
        customer_can=("Take a token and see the queue",),
        staff_can=("Call next, mark served or missed",),
        packs=("appointments", "health"), site=("queue_status",), built=True,
    ),
    ModuleInfo(
        "tasks", "Tasks & checklists", "P2",
        "Housekeeping, maintenance, prep and opening/closing checklists assigned to people.",
        staff_can=("Assign and complete tasks with photo proof",),
        packs=("stays",), surfaces=("workspace", "crew"), built=True,
    ),
    ModuleInfo(
        "attendance", "Check-ins", "P2",
        "Member, student and staff check-ins by code or by hand. Memberships decides who may come in.",
        staff_can=("Check people in", "Take class attendance", "See who is here"),
        packs=("memberships", "learning"), built=True,
    ),
    ModuleInfo(
        "kitchen", "Kitchen display", "P2",
        "Order tickets by kitchen station with bump and prep timers.",
        staff_can=("See what to cook next", "Bump tickets when done"),
        packs=("food_service",), depends_on=("orders",), surfaces=("kitchen",), built=True,
    ),
    ModuleInfo(
        "marketing", "Campaigns & offers", "P3",
        "Audiences from your own customers, coupons and campaigns you approve, with results traced to sales.",
        staff_can=("See campaigns and audience counts", "Draft campaigns and offers"),
        packs=("growth",), built=True,
    ),
    ModuleInfo(
        "loyalty", "Loyalty & referrals", "P3",
        "Points, stamp cards and referral codes customers earn and redeem.",
        customer_can=("Earn and redeem points", "Share a referral code"),
        packs=("growth",), site=("loyalty",), built=True,
    ),
    ModuleInfo(
        "ai-employees", "AI staff", "P3",
        "AI employees that work inside your limits with a full audit trail — they never act beyond what you allow.",
        staff_can=("Install, limit, pause and review AI staff",), built=True,
    ),
    ModuleInfo(
        "connectors", "Integrations", "P4",
        "Connect Tally, billing software and other tools, with a clear owner for each kind of data.",
        staff_can=("Connect a tool", "Choose who owns what data", "See sync status"),
        packs=("back_office",),
    ),
    ModuleInfo(
        "expenses", "Expenses & cash book", "P4",
        "Expenses, petty cash and the daily cash closing.",
        staff_can=("Record expenses", "Close the day's cash"),
        packs=("back_office",), built=True,
    ),
    ModuleInfo(
        "procurement", "Buying", "P4",
        "Suppliers, requisitions, purchase orders, goods received and supplier bills.",
        staff_can=("Raise and approve POs", "Receive goods", "Record supplier bills"),
        packs=("food_service", "trade"), built=True,
    ),
    ModuleInfo(
        "recipes", "Recipes & BOM", "P4",
        "What each item is made of, so cooked orders use up stock and demand turns into what to buy.",
        staff_can=("Define recipes and yields", "See ingredients used when the kitchen finishes"),
        packs=("food_service", "trade"), depends_on=("inventory",), built=True,
    ),
    ModuleInfo(
        "trade-network", "Supplier network (ChitBridge)", "P4",
        "Send purchase orders to connected suppliers and receive orders from buyers without re-typing.",
        staff_can=("Link suppliers and buyers", "Send and receive POs"),
        packs=("trade",), depends_on=("procurement",),
    ),
    ModuleInfo(
        "jobs", "Job cards", "P5",
        "Repair and service jobs from request to inspection, estimate, approval, parts, QC and invoice.",
        customer_can=("Request service", "Approve an estimate", "Track the job"),
        staff_can=("Inspect, estimate, record parts and photos",),
        packs=("field_service",), surfaces=("workspace", "crew"), site=("request_service",), built=True,
    ),
    ModuleInfo(
        "academics", "Courses & batches", "P5",
        "Courses, batches, class times, enrolment, results and the guardian or student view. Fees and attendance stay elsewhere.",
        customer_can=("See their classes and results",),
        staff_can=("Run batches", "Schedule classes", "Enter marks", "Post notices"),
        packs=("learning",), site=("courses",), built=True,
    ),
    ModuleInfo(
        "documents", "Forms & files", "P5",
        "Templates, intake and consent forms, secure upload requests and typed or drawn signatures.",
        customer_can=("Fill and sign a form from a private link", "Upload a requested document"),
        staff_can=("Build forms and templates", "Send secure request links", "See signed submissions"),
        packs=("back_office",), built=True,
    ),
    ModuleInfo(
        "donations", "Donations", "P5",
        "Causes, one-off and recurring gifts, and receipts that are right first time.",
        customer_can=("Give to a cause", "Get a receipt"),
        staff_can=("Run causes", "Issue receipts", "See donor history"),
        packs=("community",), site=("donate",), marketplace_actions=("donate",), built=True,
    ),
    # ---------------------------------------------------------- FUTURE (MD §6.2)
    ModuleInfo("payroll", "Payroll", "FUTURE", "Salary runs from attendance and commissions.", future=True),
    ModuleInfo("channel-manager", "OTA sync", "FUTURE", "Room availability sync with travel sites.", future=True),
    ModuleInfo("ticketing", "Event tickets", "FUTURE", "Tickets for events.", future=True),
)}


def canonical(key: str) -> str:
    """The registry key for a module name used in the sources."""
    return KEY_ALIASES.get(key, key)


def module(key: str) -> ModuleInfo | None:
    return MODULES.get(canonical(key))


def is_built(key: str) -> bool:
    """Platform Core (core-*) is built by definition; catalogue modules say so."""
    if key.startswith("core-"):
        return True
    info = MODULES.get(canonical(key))
    return bool(info and info.built and not info.future)


def storefront_modules() -> tuple[str, ...]:
    """Built Storefront modules outside Platform Core — on for every business
    (§6.1 "Storefront is always on"); an owner cannot switch them off."""
    return tuple(k for k in STOREFRONT if not k.startswith("core-") and is_built(k))


def built_modules() -> frozenset[str]:
    return frozenset(k for k, m in MODULES.items() if m.built and not m.future)
