"""Inventory's public read contract (Doc 09 §10.7: "Availability/out-of-stock
projection"; §5.5: reflect Location stock "without exposing internal
quantities").

What a visitor may learn about stock is one word per offering — available, low
stock or out of stock — worked out by the inventory module's own rule
(InventoryResolver.stock_status). Quantities, thresholds and locations' counts
never leave this module. An offering the business does not track stock for has
no availability here at all: absence of a record is "not tracked", never "sold
out".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.models import InventoryRecord, Offering
from platform_core.resolvers.inventory_resolver import InventoryResolver

_RANK = {"out_of_stock": 0, "low_stock": 1, "available": 2}


async def public_availability(
    session: AsyncSession,
    business_id: uuid.UUID,
    offerings: Iterable[Offering],
    *,
    location_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """offering id -> "available" | "low_stock" | "out_of_stock", for tracked offerings.

    Business-wide, an offering is as available as its best-stocked record. With
    a Location, only that Location's stock counts: tracked elsewhere but not
    stocked here is out of stock *here* (Doc 09 §5.5).
    """
    by_id = {o.id: o for o in offerings}
    if not by_id:
        return {}
    query = select(InventoryRecord).where(
        InventoryRecord.business_id == business_id, InventoryRecord.offering_id.in_(list(by_id))
    )
    records = (await session.execute(query)).scalars().all()
    tracked = {r.offering_id for r in records}
    best: dict[uuid.UUID, str] = {}
    for record in records:
        if location_id is not None and record.location_id != location_id:
            continue
        status = InventoryResolver.stock_status(record, offering=by_id.get(record.offering_id))
        current = best.get(record.offering_id)
        if current is None or _RANK.get(status, 0) > _RANK.get(current, 0):
            best[record.offering_id] = status
    return {str(oid): best.get(oid, "out_of_stock") for oid in tracked}
