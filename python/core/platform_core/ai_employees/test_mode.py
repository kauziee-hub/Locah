"""AI Employee Studio — Test Mode.

The sandbox shows how an AI employee would answer; Test Mode lets the owner
take what it proposed all the way: approve the order, booking or enquiry, take
a test payment, and see the result as a record — without any of it being real.

* **Checked live.** Approving goes through the sandbox's own re-check (the
  item is still on sale at that price; the time is still free), so a test
  record is what a real one would have been at that moment.
* **Isolated by construction.** It is written to `ai_test_records` only. No
  module reads that table, no domain event is emitted, no customer is
  messaged and nothing holds a time on the real calendar.
* **Test payments only.** `TestPaymentAdapter` decides in-process and never
  calls a payment provider; there are no keys and no money.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.ai_employees import sandbox
from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.models import AITestRecord, Offering

TEST_NOTICE = ("Test Mode — saved as a test record only. No customer was messaged, no money moved, and your real "
               "orders, bookings and enquiries are untouched.")
KIND_WORDS = {"order": "Test order", "booking": "Test booking", "lead": "Test enquiry"}
STATUS_WORDS = {"confirmed": "Confirmed (test)", "paid": "Paid (test)", "payment_failed": "Payment failed (test)",
                "cancelled": "Cancelled (test)"}


class TestPaymentAdapter:
    """The only way money "moves" in Test Mode: decided here, never by a provider."""

    provider_id = "test"
    __test__ = False  # not a pytest test class

    def charge(self, *, amount: float, outcome: str) -> dict[str, Any]:
        if outcome not in ("succeed", "fail"):
            raise ValidationError("Choose whether the test payment succeeds or fails", details={"field": "outcome"})
        return {
            "adapter": self.provider_id,
            "status": "paid" if outcome == "succeed" else "failed",
            "amount": round(amount, 2),
            "method": "Test UPI",
            "reference": f"TESTPAY-{uuid.uuid4().hex[:8].upper()}",
            "at": datetime.now(timezone.utc).isoformat(),
            **({"reason": "Declined by the test adapter"} if outcome == "fail" else {}),
        }


def _view(row: AITestRecord) -> dict[str, Any]:
    return {
        "id": str(row.id), "kind": row.kind, "kind_label": KIND_WORDS[row.kind], "reference": row.reference,
        "scenario": row.scenario, "summary": row.summary, "detail": row.detail,
        "amount": float(row.amount) if row.amount is not None else None,
        "status": row.status, "status_label": STATUS_WORDS.get(row.status, row.status), "payment": row.payment,
        "can_pay": row.kind == "order" and row.status in ("confirmed", "payment_failed") and bool(row.amount),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def record(session: AsyncSession, business_id: uuid.UUID, proposal: dict[str, Any], *, scenario: str,
                 actor_id: uuid.UUID) -> dict[str, Any]:
    """Approve a proposal in Test Mode: re-check it live, then keep it as a test record."""
    from platform_core.services.audit import AuditService

    if scenario not in sandbox.SCENARIOS:
        raise ValidationError("Unknown scenario", details={"field": "scenario"})
    checked = await sandbox.approve(session, business_id, proposal)
    if not checked.get("ok"):
        return {**checked, "record": None, "notice": TEST_NOTICE}
    kind = str(proposal["action"])
    detail: dict[str, Any] = {}
    amount: float | None = None
    if kind in ("order", "booking"):
        offering = await session.get(Offering, uuid.UUID(str(proposal.get("offering_id"))))
        if offering is None or offering.business_id != business_id:
            raise ResourceNotFound("Offering")
        price = float(offering.price_amount) if offering.price_amount is not None else None
        qty = max(1, min(int(proposal.get("quantity") or 1), 50)) if kind == "order" else 1
        detail = {"offering_id": str(offering.id), "item": offering.title, "quantity": qty, "unit_price": price,
                  "location_id": proposal.get("location_id")}
        if kind == "booking":
            detail.update({"starts_at": proposal.get("starts_at"), "ends_at": proposal.get("ends_at"),
                           "mode": proposal.get("mode"),
                           "note": "A test booking does not hold this time on your real calendar."})
        amount = price * qty if price is not None else None
    else:
        detail = {"message": str(proposal.get("message") or proposal.get("summary") or "")[:500]}
    ref = f"TEST-{kind[0].upper()}{uuid.uuid4().hex[:6].upper()}"
    row = AITestRecord(business_id=business_id, kind=kind, reference=ref, scenario=scenario,
                       summary=str(proposal.get("summary") or KIND_WORDS[kind])[:300], detail=detail,
                       amount=amount, status="confirmed", created_by=actor_id)
    session.add(row)
    await session.flush()
    await AuditService.record(session, event_type="ai_employee.test_record.created", actor_identity_id=actor_id,
                              actor_context="business", business_id=business_id, resource_type="ai_test_record",
                              resource_id=row.id, action="create",
                              after_state={"kind": kind, "reference": ref, "scenario": scenario})
    trace = [*checked["trace"], {"kind": "test_record", "label": f"Saved as {KIND_WORDS[kind].lower()} {ref}",
                                 "detail": "Test Mode only — not a real record"}]
    return {"ok": True, "reference": ref, "trace": trace, "record": _view(row), "notice": TEST_NOTICE,
            "result": f"{KIND_WORDS[kind]} {ref}: {row.summary}"}


async def records(session: AsyncSession, business_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (await session.execute(select(AITestRecord).where(
        AITestRecord.business_id == business_id, AITestRecord.cleared_at.is_(None),
    ).order_by(AITestRecord.created_at.desc()).limit(100))).scalars().all()
    return [_view(r) for r in rows]


async def pay(session: AsyncSession, business_id: uuid.UUID, record_id: uuid.UUID, *, outcome: str,
              actor_id: uuid.UUID) -> dict[str, Any]:
    """Take a test payment for a test order through the test adapter."""
    from platform_core.services.audit import AuditService

    row = await session.get(AITestRecord, record_id)
    if row is None or row.business_id != business_id or row.cleared_at is not None:
        raise ResourceNotFound("Test record")
    if row.kind != "order" or not row.amount:
        raise ValidationError("Only a test order with a price can take a test payment", details={"field": "kind"})
    if row.status == "paid":
        raise ValidationError("This test order is already paid", details={"field": "status"})
    result = TestPaymentAdapter().charge(amount=float(row.amount), outcome=outcome)
    row.payment = result
    row.status = "paid" if result["status"] == "paid" else "payment_failed"
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await AuditService.record(session, event_type="ai_employee.test_record.paid", actor_identity_id=actor_id,
                              actor_context="business", business_id=business_id, resource_type="ai_test_record",
                              resource_id=row.id, action="pay",
                              after_state={"status": row.status, "adapter": "test"})
    return _view(row)


async def clear(session: AsyncSession, business_id: uuid.UUID, *, actor_id: uuid.UUID) -> int:
    """Clear the test records from view; they stay in the audit trail."""
    from platform_core.services.audit import AuditService

    done = (await session.execute(update(AITestRecord).where(
        AITestRecord.business_id == business_id, AITestRecord.cleared_at.is_(None),
    ).values(cleared_at=datetime.now(timezone.utc)).returning(AITestRecord.id))).scalars().all()
    if done:
        await AuditService.record(session, event_type="ai_employee.test_records.cleared",
                                  actor_identity_id=actor_id, actor_context="business", business_id=business_id,
                                  resource_type="ai_test_record", resource_id=None, action="clear",
                                  after_state={"count": len(done)})
    return len(done)
