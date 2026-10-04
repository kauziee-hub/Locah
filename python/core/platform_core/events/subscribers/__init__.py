"""Registered event subscribers.

Importing this package registers every subscriber. `registry.load_subscribers()`
does that import once; nothing else needs to.

To add a subscriber: create a module here, decorate the handler with
`@subscribe(...)`, and import the module below. That is the whole wiring — no
change to the publisher, the outbox, or the worker.
"""

from __future__ import annotations

from platform_core.events.subscribers import (  # noqa: F401  (registration side effects)
    automation_triggers,
    bookings_depth,
    compliance_due,
    customer_activity,
    fulfilment_cancellation,
    fulfilment_follows_order,
    fulfilment_follows_dispatch,
    inventory_expiry,
    invoicing_auto,
    jobs_from_service_contract,
    kitchen_intake,
    loyalty_on_sale,
    marketplace_index,
    memberships_engine,
    messaging_notify,
    orders_from_quote,
    projects_from_quote,
    queue_turn,
    recipe_consumption,
    reviews_invite,
    task_events,
    website_revalidation,
)

__all__ = [
    "automation_triggers",
    "bookings_depth",
    "compliance_due",
    "customer_activity",
    "fulfilment_cancellation",
    "fulfilment_follows_order",
    "fulfilment_follows_dispatch",
    "inventory_expiry",
    "invoicing_auto",
    "jobs_from_service_contract",
    "kitchen_intake",
    "loyalty_on_sale",
    "marketplace_index",
    "memberships_engine",
    "messaging_notify",
    "orders_from_quote",
    "projects_from_quote",
    "queue_turn",
    "recipe_consumption",
    "reviews_invite",
    "task_events",
    "website_revalidation",
]
