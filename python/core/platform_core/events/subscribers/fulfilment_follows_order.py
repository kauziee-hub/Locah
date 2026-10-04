"""The pickup / delivery job follows its order.

Marking an order "Preparing", "Ready" or "Completed" moves its job the same way
(forward only), so the owner never updates one order in two places. A delivery
still goes out through "Out for delivery" on its own — that step sends the
customer their tracking link.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.events.registry import EventContext, subscribe


@subscribe(  # type: ignore[untyped-decorator]  # see marketplace_index.py
    "fulfilment.follows_order",
    "order.preparing",
    "order.ready",
    "order.completed",
    description="Move the order's pickup or delivery job along with the order",
)
async def follow_order(session: AsyncSession, event: EventContext) -> None:
    from platform_core.services.fulfilment import FulfilmentService

    await FulfilmentService.follow_order(
        session,
        business_id=event.require_business_id(),
        order_id=event.require_uuid("order_id"),
        event_type=event.event_type,
        correlation_id=event.correlation_id or str(event.event_id),
    )
