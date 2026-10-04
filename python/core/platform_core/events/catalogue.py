"""The domain event catalogue — every event type the platform may publish.

This list used to live in the worker as `KNOWN_HANDLERS`, where it did two
unrelated jobs badly: it was named for handlers but contained no handlers, and
it was consulted hours after publication, so a typo'd event type surfaced as a
dead letter attributed to the worker rather than to the code that emitted it.

It is now checked at publish time, in the emitting transaction, where the
mistake is attributable. Membership here says only "this is a real event type"
— not that anything consumes it. Who consumes what lives in
`platform_core.events.registry`, and most of these have no subscriber at all.

Adding an event type is deliberately a one-line edit here. That is the only
central edit a new capability needs; it does not touch the worker.
"""

from __future__ import annotations

# Grouped by the capability that owns the event. An owner may publish only the
# events in its own group.
_CATALOGUE: dict[str, frozenset[str]] = {
    "business": frozenset(
        {
            "business.created",
            "business.initialized",
            "business.settings.updated",
            "business.profile.updated",
            "business.branding.updated",
            "business.preferences.updated",
            "business.visibility.changed",
            "business.suspended",
            "business.context_switched",
            "business.override.updated",
            "business_type.changed",
            "business.classification.changed",
            "business.traits.changed",
        }
    ),
    "membership": frozenset(
        {
            "membership.created",
            "membership.updated",
            "membership.suspended",
            "membership.reactivated",
            "membership.removed",
            "ownership.transferred",
            "role.changed",
        }
    ),
    "invitation": frozenset(
        {
            "invitation.created",
            "invitation.resent",
            "invitation.accepted",
            "invitation.declined",
            "invitation.revoked",
            "invitation.expired",
        }
    ),
    "configuration": frozenset(
        {
            "configuration.resolved",
            "configuration.profile.updated",
            "entitlement.updated",
            "module.enabled",
            "module.disabled",
            "module.deactivated",
            "feature.enabled",
            "feature.disabled",
        }
    ),
    "authorization": frozenset(
        {
            "permission.granted",
            "permission.override.created",
            "permission.override.removed",
            "authorization.snapshot.updated",
        }
    ),
    "location": frozenset(
        {
            "location.created",
            "location.updated",
            "location.archived",
        }
    ),
    "employee": frozenset(
        {
            "employee.created",
            "employee.updated",
            "employee.deactivated",
            "employee.assigned",
            "employee.unassigned",
            "employee.transferred",
        }
    ),
    "customer": frozenset(
        {
            "customer.created",
            "customer.updated",
            "customer.blocked",
            "customer.archived",
            "customer.restored",
            "customer.tagged",
            "customer.note.created",
            "customer_asset.recorded",
        }
    ),
    "catalogue": frozenset(
        {
            "product_category.created",
            "product_category.updated",
            "product_category.archived",
            "offering.created",
            "offering.updated",
            "offering.archived",
            "offering.restored",
            "offering.variant.created",
            "pricing.rate.updated",
        }
    ),
    "inventory": frozenset(
        {
            "inventory.stock.updated",
            "inventory.stock.low",
            "inventory.stock.zero",
            "inventory.stock.replenished",
            "inventory.adjusted",
            "inventory.opening_stock.set",
            # P1-10A stock depth (§15.1)
            "inventory.received",
            "inventory.wastage.recorded",
            "inventory.converted",
            "inventory.count.submitted",
            "inventory.count.variance",
            "inventory.count.approved",
            "inventory.count.rejected",
            "inventory.transfer.requested",
            "inventory.transfer.approved",
            "inventory.transfer.in_transit",
            "inventory.transfer.received",
            "inventory.job.consumed",
            "inventory.job.returned",
            "inventory.client_stock.moved",
        }
    ),
    "order": frozenset(
        {
            "order.created",
            "order.updated",
            "order.accepted",
            "order.preparing",
            "order.ready",
            "order.completed",
            "order.cancelled",
            "order.rejected",
            "order.note.created",
        }
    ),
    "booking": frozenset(
        {
            "booking.created",
            "booking.updated",
            "booking.confirmed",
            "booking.rejected",
            "booking.checked_in",
            "booking.completed",
            "booking.cancelled",
            "booking.rescheduled",
            "booking.no_show",
            "booking.note.created",
            "booking.deposit_collected",
            "booking.policy_updated",
            "booking.hold_released",
            "booking.waitlist_joined",
            "booking.waitlist_offered",
            "booking.waitlist_claimed",
            "booking.waitlist_expired",
            "booking.series_created",
            "booking.series_changed",
            "booking.series_ended",
            "bookings.resource.created",
            "bookings.resource.updated",
            "bookings.resource.archived",
        }
    ),
    "workforce": frozenset(
        {
            "workforce.member_created",
            "workforce.member_updated",
            "workforce.location_assigned",
            "workforce.location_unassigned",
            "workforce.service_associated",
            "workforce.availability_updated",
        }
    ),
    "payment": frozenset(
        {
            "payment.initiated",
            "payment.completed",
            "payment.failed",
            "payment.refunded",
            "payment.refund_requested",
            "payment.refund_failed",
            "payment.updated",
            "payment.webhook_processed",
            "payment.merchant.updated",
            "payment.request.created",
            "payment.confirmation_requested",
            "payment.paid_twice",
        }
    ),
    "website": frozenset(
        {
            "website.draft_generated",
            "website.published",
            "website.generation_failed",
            "website.auto_sections.changed",
            "website.languages.changed",
            "stage.changed",
            "stage_set.changed",
        }
    ),
    "marketplace": frozenset(
        {
            "marketplace.indexed",
            "marketplace.index_failed",
            "marketplace.deindexed",
            "marketplace.reindex_triggered",
        }
    ),
    "fulfilment": frozenset(
        {
            "fulfilment.job_created",
            "fulfilment.status_changed",
            "fulfilment.failed",
            "fulfilment.delivered",
            "fulfilment.zone_configured",
            "fulfilment.settings_updated",
        }
    ),
    "dispatch": frozenset(
        {
            "dispatch.job_created",
            "dispatch.assigned",
            "dispatch.picked_up",
            "dispatch.out_for_delivery",
            "dispatch.delivered",
            "dispatch.failed",
        }
    ),
    "lead": frozenset(
        {
            "lead.created",
            "lead.updated",
            "lead.assigned",
            "lead.deleted",
            "lead.stage_changed",
            "lead.contacted",
            "lead.qualified",
            "lead.won",
            "lead.lost",
            "lead.note.created",
        }
    ),
    "quote": frozenset(
        {
            "quote.created",
            "quote.updated",
            "quote.issued",
            "quote.accepted",
            "quote.rejected",
            "quote.expired",
            "quote.cancelled",
            "quote.revised",
            "quote.converted",
            "quote.viewed",
            "quote.rfq_received",
            "quote.acceptance_code_issued",
            "quote.discount_decided",
            "quote.payment_handoff",
            "quote.conversion_requested",
        }
    ),
    # Projects and work orders. `project.completed` is the one anything
    # downstream is likely to care about — invoicing, a review request, a
    # follow-up — so it is distinct from the generic status change rather than
    # something a subscriber has to infer from a payload.
    "project": frozenset(
        {
            "project.created",
            "project.updated",
            "project.status.changed",
            "project.completed",
            "project.cancelled",
            "project.task.assigned",
            "project.task.completed",
            "project.phase.completed",
        }
    ),
    "job": frozenset({
        "job.created", "job.assigned", "job.status.changed", "job.part.consumed", "job.part.returned", "job.completed",
    }),
    "academics": frozenset({
        "academics.course.created", "academics.batch.created", "academics.session.scheduled",
        "academics.student.enrolled", "academics.assessment.created", "academics.result.recorded",
        "academics.announcement.created",
    }),
    "attendance": frozenset({
        "attendance.checked_in", "attendance.checked_out", "attendance.session_recorded",
    }),
    "membership_plan": frozenset(
        {
            "membership.plan.created",
            "membership.plan.updated",
            "membership.plan.archived",
            "membership.enrolled",
            "membership.enrolment.updated",
            "membership.enrolment.activated",
            "membership.enrolment.paused",
            "membership.enrolment.expired",
            "membership.enrolment.cancelled",
            "membership.enrolment.completed",
            "membership.enrolment.grace",
            "membership.period_paid",
            "membership.instalment_paid",
            "membership.freeze_added",
            "membership.session_used",
            "membership.session_reversed",
            "membership.delivery_changed",
            "membership.deliveries_generated",
            "membership.service_visit_due",
        }
    ),
    # Capability Universe §14 — the one billing engine.
    "invoicing": frozenset(
        {
            "invoicing.settings.updated",
            "invoicing.tax_rates.changed",
            "invoice.issued",
            "invoice.cancelled",
            "invoice.payment_recorded",
            "invoice.paid",
        }
    ),
    # Capability Universe §6.2 `ledger`, §14.5 — the khata.
    "ledger": frozenset(
        {
            "ledger.entry.posted",
            "ledger.limit.overridden",
        }
    ),
    # Capability Universe §6.2 kitchen. Preparation truth, not a second order.
    # `kitchen.preparation.completed` is the event Recipe/BOM subscribes to.
    "kitchen": frozenset(
        {
            "kitchen.ticket.created",
            "kitchen.ticket.started",
            "kitchen.ticket.ready",
            "kitchen.preparation.completed",
            "kitchen.ticket.cancelled",
        }
    ),
    # Capability Universe §17 — verified reviews and their moderation.
    "reviews": frozenset(
        {
            "review.invited",
            "review.published",
            "review.updated",
            "review.replied",
            "review.featured",
            "review.reported",
            "review.removed",
            "review.restored",
            "review.redacted",
        }
    ),
    # Capability Universe §6.2 `compliance` — licences and filings.
    "compliance": frozenset(
        {
            "compliance.item.created",
            "compliance.item.updated",
            "compliance.item.renewed",
            "compliance.item.filed",
            "compliance.item.archived",
        }
    ),
    # Supply lane. Buying, recipes, expenses, connectors, documents, donations.
    "procurement": frozenset(
        {
            "procurement.requisition.created",
            "procurement.po.approved",
            "procurement.po.sent",
            "procurement.po.countered",
            "procurement.goods_received",
            "supplier.bill.created",
            "recipe.consumed",
            "trade.message.received",
        }
    ),
    "expenses": frozenset({"expense.created"}),
    "donations": frozenset({"donation.received"}),
    "connectors": frozenset({"connector.sync.completed"}),
    # One documents owner: the supply lane's business-document register and the
    # forms / secure requests / signatures workflow.
    "documents": frozenset({
        "document.recorded", "document.created", "document.requested", "document.uploaded",
        "form.submitted", "document.signed",
    }),
    # Business OS Guide §6.2 walk-in queue. queue.turn_soon is the Messaging contract.
    "queue": frozenset(
        {
            "queue.turn_soon",
        }
    ),
    # Business OS Guide §6.2 shared tasks.
    "tasks": frozenset(
        {
            "task.created",
            "task.assigned",
            "task.due",
            "task.completed",
        }
    ),
}

KNOWN_EVENT_TYPES: frozenset[str] = frozenset().union(*_CATALOGUE.values())

EVENT_OWNERS: dict[str, str] = {
    event_type: owner for owner, events in _CATALOGUE.items() for event_type in events
}


class UnknownEventType(ValueError):
    """An event type that is not in the catalogue — almost always a typo."""


def is_known_event_type(event_type: str) -> bool:
    return event_type in KNOWN_EVENT_TYPES


def assert_known_event_type(event_type: str) -> None:
    if event_type not in KNOWN_EVENT_TYPES:
        raise UnknownEventType(
            f"Unknown domain event type {event_type!r}. Add it to "
            "platform_core.events.catalogue before publishing it."
        )


def owner_of(event_type: str) -> str | None:
    return EVENT_OWNERS.get(event_type)
