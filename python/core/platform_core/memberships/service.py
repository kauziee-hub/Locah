"""The recurring-relationship engine (Founder refinement — Memberships; Capability Universe §10).

One engine for memberships, session packs, subscriptions, fee plans, service
contracts and dues. It owns:

* **what a payment means** — Payments owns the money; a verified payment is
  applied here to the oldest open period or instalment, exactly once
  (`memberships_payment_applications` is unique per payment);
* **periods** — every stretch of cover is a row that is never rewritten; a
  renewal adds the next one after the last (early renewal never loses days);
* **freezes** — a 10-day freeze moves the cover end by exactly 10 days, with
  the freeze kept as history;
* **sessions** — each use is one row with its own idempotency key;
* **state** — recalculated (platform_core.memberships.lifecycle) whenever
  something happens and by the daily sweep; the renewal ladder follows the
  cover end and stops by itself once renewed.

It never creates orders, jobs or attendance itself: subscriptions hand the
Orders module their demand, AMC visits are published for Jobs, check-ins are
answered for Attendance.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceNotFound, ValidationError
from platform_core.memberships import lifecycle as lc
from platform_core.memberships.models import (
    MembershipFreeze,
    MembershipInstalment,
    MembershipPaymentApplication,
    MembershipPeriod,
    MembershipServiceVisit,
    MembershipSessionUse,
)
from platform_core.memberships.words import CHECKIN_COLOURS, STATUS_WORDS, words
from platform_core.models import (
    BusinessLocation,
    CustomerContact,
    MembershipEnrolment,
    MembershipEnrolmentStatusHistory,
    MembershipPlan,
    PaymentAttempt,
)
from platform_core.services.outbox import OutboxService

ZERO = Decimal("0")
RENEWAL_LADDER = "membership.renewal"
INSTALMENT_LADDER = "membership.instalment"
RENEWING_KINDS = ("access", "session_pack", "recurring_delivery", "service_contract", "member_dues")
STATUS_EVENTS = {
    "active": "membership.enrolment.activated",
    "paused": "membership.enrolment.paused",
    "grace": "membership.enrolment.grace",
    "expired": "membership.enrolment.expired",
    "cancelled": "membership.enrolment.cancelled",
    "completed": "membership.enrolment.completed",
    "pending": "membership.enrolment.updated",
}


def _d(v: Any) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _err(field: str, message: str) -> ValidationError:
    return ValidationError(message, details={"errors": [{"field": field, "message": message}], "field": field})


def _inr(v: Any) -> str:
    return f"₹{float(v or 0):,.2f}".replace(".00", "")


class MembershipCore:
    # ------------------------------------------------------------------ loading
    @staticmethod
    async def tz(session: AsyncSession, business_id: uuid.UUID, location_id: uuid.UUID | None = None) -> str:
        """The business's own timezone (the relationship's location, else the primary one)."""
        q = select(BusinessLocation.timezone).where(BusinessLocation.business_id == business_id)
        q = q.where(BusinessLocation.id == location_id) if location_id else q.order_by(
            BusinessLocation.is_primary.desc())
        zone = (await session.execute(q.limit(1))).scalar()
        return str(zone or "Asia/Kolkata")

    @staticmethod
    async def get(session: AsyncSession, business_id: uuid.UUID, enrolment_id: uuid.UUID, *,
                  lock: bool = False) -> MembershipEnrolment:
        q = select(MembershipEnrolment).where(MembershipEnrolment.business_id == business_id,
                                              MembershipEnrolment.id == enrolment_id,
                                              MembershipEnrolment.deleted_at.is_(None))
        if lock:
            q = q.with_for_update().execution_options(populate_existing=True)
        row = (await session.execute(q)).scalars().first()
        if row is None:
            raise ResourceNotFound("Membership")
        return row

    @staticmethod
    async def plan_of(session: AsyncSession, enrolment: MembershipEnrolment) -> MembershipPlan:
        plan = await session.get(MembershipPlan, enrolment.plan_id)
        assert plan is not None
        return plan

    @staticmethod
    async def periods(session: AsyncSession, enrolment_id: uuid.UUID) -> list[MembershipPeriod]:
        return list((await session.execute(select(MembershipPeriod).where(
            MembershipPeriod.enrolment_id == enrolment_id).order_by(MembershipPeriod.seq))).scalars())

    @staticmethod
    async def freezes(session: AsyncSession, enrolment_id: uuid.UUID) -> list[MembershipFreeze]:
        return list((await session.execute(select(MembershipFreeze).where(
            MembershipFreeze.enrolment_id == enrolment_id).order_by(MembershipFreeze.starts_on))).scalars())

    @staticmethod
    async def instalments(session: AsyncSession, enrolment_id: uuid.UUID) -> list[MembershipInstalment]:
        return list((await session.execute(select(MembershipInstalment).where(
            MembershipInstalment.enrolment_id == enrolment_id).order_by(MembershipInstalment.seq))).scalars())

    @staticmethod
    async def sessions_used(session: AsyncSession, enrolment_id: uuid.UUID) -> dict[str, int]:
        rows = (await session.execute(select(MembershipSessionUse.period_id, func.count()).where(
            MembershipSessionUse.enrolment_id == enrolment_id, MembershipSessionUse.status == "consumed")
            .group_by(MembershipSessionUse.period_id))).all()
        return {str(r[0]): int(r[1]) for r in rows}

    @staticmethod
    async def state(session: AsyncSession, enrolment: MembershipEnrolment, plan: MembershipPlan | None = None, *,
                    now: datetime | None = None) -> lc.State:
        plan = plan or await MembershipCore.plan_of(session, enrolment)
        zone = await MembershipCore.tz(session, enrolment.business_id, enrolment.location_id)
        return lc.compute(
            plan.plan_kind, now=now or _now(), tz=zone, stored_status=enrolment.status,
            starts_at=enrolment.starts_at, ends_at=enrolment.ends_at, grace_days=plan.grace_days,
            billing_timing=plan.billing_timing,
            periods=[lc.PeriodRow(str(p.id), p.seq, p.starts_at, p.ends_at, _d(p.amount), _d(p.paid_amount),
                                  p.payment_state, p.sessions_included)
                     for p in await MembershipCore.periods(session, enrolment.id)],
            freezes=[lc.FreezeRow(f.starts_on, f.ends_on, f.kind, f.status)
                     for f in await MembershipCore.freezes(session, enrolment.id)],
            instalments=[lc.InstalmentRow(i.seq, _d(i.amount), _d(i.paid_amount), i.due_on, i.status)
                         for i in await MembershipCore.instalments(session, enrolment.id)],
            sessions_used=await MembershipCore.sessions_used(session, enrolment.id),
        )

    # ------------------------------------------------------------------ opening a relationship
    @staticmethod
    async def open(session: AsyncSession, enrolment: MembershipEnrolment, plan: MembershipPlan, *,
                   actor_id: uuid.UUID | None, instalments: list[dict[str, Any]] | None = None,
                   delivery: dict[str, Any] | None = None) -> None:
        """First charges for a new relationship: the first period (or the fee
        plan's instalments), a check-in code, a subscriber's schedule."""
        enrolment.checkin_code = await MembershipCore._new_code(session, enrolment.business_id)
        kind = plan.plan_kind
        if kind == "recurring_delivery":
            enrolment.delivery = MembershipCore._clean_delivery({**(plan.delivery or {}), **(delivery or {})})
        if kind == "fee_plan":
            rows = instalments or MembershipCore._from_template(plan, enrolment.starts_at)
            if not rows:
                raise _err("instalments", "Add at least one instalment to the fee plan")
            for n, row in enumerate(rows, start=1):
                session.add(MembershipInstalment(
                    business_id=enrolment.business_id, enrolment_id=enrolment.id, seq=n,
                    label=str(row.get("label") or f"Instalment {n}")[:80], amount=_d(row["amount"]),
                    due_on=row["due_on"] if isinstance(row["due_on"], date) else date.fromisoformat(str(row["due_on"])),
                ))
            await session.flush()
            return
        if kind == "recurring_delivery" and plan.billing_timing == "postpaid":
            return
        await MembershipCore._add_period(session, enrolment, plan, starts_at=enrolment.starts_at, source="join",
                                         actor_id=actor_id)

    @staticmethod
    def _from_template(plan: MembershipPlan, starts_at: datetime) -> list[dict[str, Any]]:
        out = []
        for row in plan.instalment_template or []:
            out.append({"label": row.get("label"), "amount": row.get("amount"),
                        "due_on": (starts_at + timedelta(days=int(row.get("due_after_days") or 0))).date()})
        return out

    @staticmethod
    def _clean_delivery(raw: dict[str, Any]) -> dict[str, Any]:
        days = sorted({int(d) for d in (raw.get("days") or list(range(7))) if 0 <= int(d) <= 6})
        qty = Decimal(str(raw.get("quantity") or 1))
        # Orders count whole selling units: 1 litre of a 500 ml pack is 2.
        if qty <= 0 or qty != qty.to_integral_value():
            raise _err("quantity", "Quantity is a whole number of the item (2 packs, 3 meals)")
        if not raw.get("offering_id"):
            raise _err("offering_id", "Choose what is delivered")
        cutoff = str(raw.get("cutoff") or "21:00")
        try:
            hh, mm = (int(x) for x in cutoff.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            raise _err("cutoff", "Cutoff is a time like 21:00") from None
        return {"offering_id": str(raw["offering_id"]), "quantity": str(int(qty)), "days": days or list(range(7)),
                "slot": str(raw.get("slot") or "")[:30], "window": str(raw.get("window") or "")[:30],
                "cutoff": f"{hh:02d}:{mm:02d}", "address": raw.get("address") or None,
                "mode": raw.get("mode") if raw.get("mode") in ("delivery", "pickup") else "delivery"}

    @staticmethod
    async def _new_code(session: AsyncSession, business_id: uuid.UUID) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(8):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            taken = (await session.execute(select(MembershipEnrolment.id).where(
                MembershipEnrolment.business_id == business_id, MembershipEnrolment.checkin_code == code))).first()
            if taken is None:
                return code
        raise ConflictError("Could not make a check-in code; try again")

    @staticmethod
    async def _add_period(session: AsyncSession, enrolment: MembershipEnrolment, plan: MembershipPlan, *,
                          starts_at: datetime, source: str, actor_id: uuid.UUID | None) -> MembershipPeriod:
        if not plan.duration_days:
            raise _err("duration_days", "This plan has no length; set how many days it covers")
        seq = int((await session.execute(select(func.coalesce(func.max(MembershipPeriod.seq), 0)).where(
            MembershipPeriod.enrolment_id == enrolment.id))).scalar() or 0) + 1
        ends = starts_at + timedelta(days=int(plan.duration_days))
        price = _d(plan.price_amount)
        period = MembershipPeriod(
            business_id=enrolment.business_id, enrolment_id=enrolment.id, seq=seq, starts_at=starts_at,
            base_ends_at=ends, ends_at=ends, amount=price, paid_amount=ZERO,
            payment_state="waived" if price <= 0 else "unpaid",
            sessions_included=plan.sessions_included if plan.plan_kind == "session_pack" else None,
            source=source, created_by=actor_id, paid_at=_now() if price <= 0 else None)
        session.add(period)
        await session.flush()
        if price <= 0:
            await MembershipCore._on_period_covered(session, enrolment, plan, period)
        return period

    # ------------------------------------------------------------------ money
    @staticmethod
    async def charged(session: AsyncSession, enrolment: MembershipEnrolment) -> Decimal:
        """Everything this relationship has charged (periods + instalments) — the
        total Payments measures payments against."""
        periods = sum((_d(p.amount) for p in await MembershipCore.periods(session, enrolment.id)
                       if p.payment_state != "cancelled"), ZERO)
        inst = sum((_d(i.amount) for i in await MembershipCore.instalments(session, enrolment.id)
                    if i.status not in ("cancelled", "waived")), ZERO)
        return periods + inst

    @staticmethod
    async def due_now(session: AsyncSession, enrolment: MembershipEnrolment) -> Decimal:
        """What the member pays to start: the first period, or the fee plan's
        instalments due on or before the start (at least the first)."""
        plan = await MembershipCore.plan_of(session, enrolment)
        if plan.plan_kind == "fee_plan":
            rows = await MembershipCore.instalments(session, enrolment.id)
            start = enrolment.starts_at.date()
            due = [i for i in rows if i.due_on <= start] or rows[:1]
            return sum((_d(i.amount) - _d(i.paid_amount) for i in due), ZERO)
        periods = [p for p in await MembershipCore.periods(session, enrolment.id)
                   if p.payment_state in ("unpaid", "part_paid")]
        return sum((_d(p.amount) - _d(p.paid_amount) for p in periods[:1]), ZERO)

    @staticmethod
    async def apply_payment(session: AsyncSession, payment: PaymentAttempt) -> bool:
        """A verified payment lands on the oldest open period or instalment —
        once. A replayed webhook, a second click or a retried job finds the
        payment already applied and changes nothing."""
        enrolment = await MembershipCore.get(session, payment.business_id, payment.source_id, lock=True)
        done = (await session.execute(select(MembershipPaymentApplication.id).where(
            MembershipPaymentApplication.payment_attempt_id == payment.id))).first()
        if done is not None:
            return False
        plan = await MembershipCore.plan_of(session, enrolment)
        left = _d(payment.amount) - _d(payment.refunded_amount)
        if plan.plan_kind == "fee_plan":
            charges: list[Any] = [i for i in await MembershipCore.instalments(session, enrolment.id)
                                  if i.status in ("due", "part_paid")]
            kind = "instalment"
        else:
            charges = [p for p in await MembershipCore.periods(session, enrolment.id)
                       if p.payment_state in ("unpaid", "part_paid")]
            kind = "period"
        if not charges and left > 0 and kind == "period" and plan.plan_kind in RENEWING_KINDS:
            # A late payment on an old link, after the unpaid renewal lapsed:
            # the money buys a fresh period starting now, never nothing.
            charges = [await MembershipCore._add_period(session, enrolment, plan, starts_at=max(
                _now(), *(p.ends_at for p in await MembershipCore.periods(session, enrolment.id)
                          if p.payment_state in lc.COVERED)), source="renewal", actor_id=None)]
        newly_covered: list[MembershipPeriod] = []
        for charge in charges:
            if left <= 0:
                break
            open_amount = _d(charge.amount) - _d(charge.paid_amount)
            take = min(open_amount, left)
            if take <= 0:
                continue
            charge.paid_amount = _d(charge.paid_amount) + take
            left -= take
            full = _d(charge.paid_amount) >= _d(charge.amount)
            if kind == "period":
                charge.payment_state = "paid" if full else "part_paid"
                if full:
                    charge.paid_at = _now()
                    newly_covered.append(charge)
            else:
                charge.status = "paid" if full else "part_paid"
                if full:
                    charge.paid_at = _now()
            session.add(MembershipPaymentApplication(
                business_id=enrolment.business_id, enrolment_id=enrolment.id, payment_attempt_id=payment.id,
                charge_type=kind, charge_id=charge.id, amount=take))
        await session.flush()
        for period in newly_covered:
            await MembershipCore._on_period_covered(session, enrolment, plan, period)
            await OutboxService.publish(session, event_type="membership.period_paid", business_id=enrolment.business_id,
                                        payload={"enrolment_id": str(enrolment.id), "period_id": str(period.id),
                                                 "seq": period.seq, "ends_at": period.ends_at.isoformat(),
                                                 "customer_contact_id": str(enrolment.customer_contact_id),
                                                 "renewal": period.seq > 1, "payment_id": str(payment.id)})
        if kind == "instalment":
            await OutboxService.publish(session, event_type="membership.instalment_paid",
                                        business_id=enrolment.business_id,
                                        payload={"enrolment_id": str(enrolment.id), "payment_id": str(payment.id),
                                                 "customer_contact_id": str(enrolment.customer_contact_id)})
        # The "pay at the business" choice made at enrolment was for the first
        # charge; once that is paid, nobody should collect it again.
        if await MembershipCore._first_charge_paid(session, enrolment, plan):
            from platform_core.services.payment_collect import PaymentCollectService

            await PaymentCollectService.close_intents(session, payment)
        await MembershipCore.recalculate(session, enrolment, reason="Payment received")
        return True

    @staticmethod
    async def _first_charge_paid(session: AsyncSession, enrolment: MembershipEnrolment,
                                 plan: MembershipPlan) -> bool:
        if plan.plan_kind == "fee_plan":
            rows = await MembershipCore.instalments(session, enrolment.id)
            first = [i for i in rows if i.due_on <= enrolment.starts_at.date()] or rows[:1]
            return all(i.status in ("paid", "waived", "cancelled") for i in first)
        first_period = next(iter(await MembershipCore.periods(session, enrolment.id)), None)
        return first_period is None or first_period.payment_state in ("paid", "waived", "cancelled")

    @staticmethod
    async def _on_period_covered(session: AsyncSession, enrolment: MembershipEnrolment, plan: MembershipPlan,
                                 period: MembershipPeriod) -> None:
        """A service contract's covered visits are booked once the period is paid."""
        if plan.plan_kind != "service_contract":
            return
        have = (await session.execute(select(func.count()).select_from(MembershipServiceVisit).where(
            MembershipServiceVisit.period_id == period.id))).scalar_one()
        if have:
            return
        for n, day in enumerate(lc.visit_dates(period.starts_at.date(), period.ends_at.date(),
                                               count=plan.visits_included, every_days=plan.visit_every_days),
                                start=1):
            session.add(MembershipServiceVisit(business_id=enrolment.business_id, enrolment_id=enrolment.id,
                                               period_id=period.id, seq=n, due_on=day))
        await session.flush()

    # ------------------------------------------------------------------ state
    @staticmethod
    async def recalculate(session: AsyncSession, enrolment: MembershipEnrolment, *, now: datetime | None = None,
                          actor_id: uuid.UUID | None = None, reason: str | None = None,
                          correlation_id: str | None = None) -> lc.State:
        """Work out the relationship's state again and act on any change: history,
        the customer's timeline and My Activity (via events), cached dates, and
        the renewal ladder anchored on the cover end."""
        plan = await MembershipCore.plan_of(session, enrolment)
        st = await MembershipCore.state(session, enrolment, plan, now=now)
        before = enrolment.status
        enrolment.valid_until = st.valid_until
        enrolment.grace_until = st.grace_until
        enrolment.next_due_on = st.next_due_on
        if st.status == "paused" and enrolment.paused_at is None:
            enrolment.paused_at = now or _now()
        elif st.status != "paused":
            enrolment.paused_at = None
        if plan.plan_kind != "fee_plan" and st.valid_until is not None:
            enrolment.ends_at = st.valid_until
        if before != st.status:
            enrolment.status = st.status
            enrolment.version += 1
            session.add(MembershipEnrolmentStatusHistory(
                business_id=enrolment.business_id, enrolment_id=enrolment.id, from_status=before,
                to_status=st.status, actor_identity_id=actor_id, reason=(reason or st.reason)[:200]))
            await session.flush()
            from platform_core.services.customer_timeline import CustomerTimelineService

            await CustomerTimelineService.record_entry(
                session, business_id=enrolment.business_id, contact_id=enrolment.customer_contact_id,
                activity_type=f"membership.{st.status}", resource_type="membership_enrolment",
                resource_id=enrolment.id,
                summary={"plan_id": str(enrolment.plan_id), "status": st.status, "reason": st.reason})
            await OutboxService.publish(
                session, event_type=STATUS_EVENTS.get(st.status, "membership.enrolment.updated"),
                business_id=enrolment.business_id, correlation_id=correlation_id,
                payload={"business_id": str(enrolment.business_id), "enrolment_id": str(enrolment.id),
                         "plan_id": str(enrolment.plan_id), "status": st.status, "from": before,
                         "customer_contact_id": str(enrolment.customer_contact_id), "reason": st.reason})
        # payment_status mirrors what Payments measures: charged vs paid.
        enrolment.payment_status = ("paid" if st.charged > 0 and st.outstanding <= 0 else
                                    "partially_paid" if st.paid > 0 else enrolment.payment_status
                                    if enrolment.payment_status in ("pending", "pending_offline") else "pending")
        await session.flush()
        await MembershipCore._ladders(session, enrolment, plan, st, now=now)
        return st

    @staticmethod
    async def _ladders(session: AsyncSession, enrolment: MembershipEnrolment, plan: MembershipPlan, st: lc.State, *,
                       now: datetime | None) -> None:
        from platform_core.automation import AutomationEngine

        if plan.plan_kind in RENEWING_KINDS and not (plan.plan_kind == "recurring_delivery"
                                                     and plan.billing_timing == "postpaid"):
            key = f"{st.valid_until:%Y%m%d%H%M}" if st.valid_until else ""
            live = st.status in ("active", "paused", "grace", "expired") and st.valid_until is not None
            # Steps for any earlier cover end are obsolete: renewed, frozen or cancelled.
            await session.execute(text(
                "UPDATE automation_steps SET status = 'cancelled', executed_at = now(), "
                "outcome = CASE WHEN :live THEN 'The plan was renewed or its end date moved' "
                "ELSE 'The membership is no longer running' END "
                "WHERE business_id = :b AND ladder_key = :l AND entity_id = :e AND status = 'pending' "
                "AND (period_key <> :k OR NOT :live)"),
                {"b": str(enrolment.business_id), "l": RENEWAL_LADDER, "e": str(enrolment.id), "k": key,
                 "live": live})
            if live and st.valid_until is not None and st.status != "expired":
                grace_end = st.grace_until or st.valid_until
                await AutomationEngine.schedule(
                    session, enrolment.business_id, ladder_key=RENEWAL_LADDER, entity_id=enrolment.id,
                    anchor=st.valid_until, period_key=key,
                    due_overrides={"grace_end": grace_end + timedelta(minutes=1)},
                    context={"valid_until": st.valid_until.isoformat()}, now=now)
        if plan.plan_kind == "fee_plan":
            zone = await MembershipCore.tz(session, enrolment.business_id, enrolment.location_id)
            from zoneinfo import ZoneInfo

            for inst in await MembershipCore.instalments(session, enrolment.id):
                if inst.status in ("paid", "waived", "cancelled") or enrolment.status in ("cancelled", "completed"):
                    await AutomationEngine.cancel(session, enrolment.business_id, ladder_key=INSTALMENT_LADDER,
                                                  entity_id=inst.id, reason="Paid" if inst.status == "paid"
                                                  else "No longer due")
                    continue
                anchor = datetime.combine(inst.due_on, datetime.min.time().replace(hour=10), ZoneInfo(zone))
                await AutomationEngine.schedule(session, enrolment.business_id, ladder_key=INSTALMENT_LADDER,
                                                entity_id=inst.id, anchor=anchor, period_key=str(inst.due_on),
                                                context={"enrolment_id": str(enrolment.id)}, now=now)

    # ------------------------------------------------------------------ renew
    @staticmethod
    async def renew(session: AsyncSession, enrolment: MembershipEnrolment, *, actor_id: uuid.UUID | None,
                    source: str = "renewal", now: datetime | None = None) -> MembershipPeriod:
        """The next period, straight after the last one (§21): renewing on
        20 Dec a plan ending 31 Dec gives 1 Jan → 31 Jan. Asking twice returns
        the same unpaid period rather than stacking charges."""
        plan = await MembershipCore.plan_of(session, enrolment)
        if plan.plan_kind not in RENEWING_KINDS or (plan.plan_kind == "recurring_delivery"
                                                    and plan.billing_timing == "postpaid"):
            raise ConflictError("This plan is not renewed period by period")
        if enrolment.status == "cancelled":
            raise ConflictError("A cancelled membership cannot be renewed; enrol again")
        moment = now or _now()
        periods = await MembershipCore.periods(session, enrolment.id)
        waiting = next((p for p in periods if p.payment_state in ("unpaid", "part_paid") and p.ends_at > moment),
                       None)
        if waiting is not None:
            return waiting
        start, _ = lc.next_period_window(
            now=moment, duration_days=int(plan.duration_days or 1),
            periods=[lc.PeriodRow(str(p.id), p.seq, p.starts_at, p.ends_at, _d(p.amount), _d(p.paid_amount),
                                  p.payment_state) for p in periods])
        early = any(p.payment_state in lc.COVERED and p.ends_at > moment for p in periods)
        period = await MembershipCore._add_period(session, enrolment, plan, starts_at=start,
                                                  source="early_renewal" if early and source == "renewal"
                                                  else source, actor_id=actor_id)
        await MembershipCore.recalculate(session, enrolment, now=now, actor_id=actor_id, reason="Renewal started")
        return period

    @staticmethod
    async def lapse_unpaid(session: AsyncSession, enrolment: MembershipEnrolment, *,
                           now: datetime | None = None) -> int:
        """When a membership expires, an unpaid renewal it was offered lapses:
        it is no longer money owed (a later payment starts a new period)."""
        moment = now or _now()
        n = 0
        for p in await MembershipCore.periods(session, enrolment.id):
            if p.payment_state == "unpaid" and p.starts_at <= moment:
                p.payment_state = "cancelled"
                n += 1
        if n:
            await session.flush()
            await MembershipCore.recalculate(session, enrolment, now=now, reason="Unpaid renewal lapsed")
        return n

    # ------------------------------------------------------------------ freeze / pause
    @staticmethod
    async def freeze(session: AsyncSession, enrolment: MembershipEnrolment, *, starts_on: date, days: int,
                     reason: str | None, actor_id: uuid.UUID | None, channel: str = "workspace",
                     now: datetime | None = None) -> MembershipFreeze:
        """A gym freeze moves the cover end by exactly `days` (§7); a
        subscription pause stops deliveries without moving it (§11)."""
        plan = await MembershipCore.plan_of(session, enrolment)
        kind = "pause" if plan.plan_kind == "recurring_delivery" else "freeze"
        if kind == "freeze" and not plan.freeze_allowed:
            raise ConflictError("This plan does not allow freezes")
        if not 1 <= days <= 366:
            raise _err("days", "Between 1 and 366 days")
        if plan.max_freeze_days and kind == "freeze":
            already = sum(f.days for f in await MembershipCore.freezes(session, enrolment.id)
                          if f.status == "confirmed" and f.kind == "freeze")
            if already + days > plan.max_freeze_days:
                raise _err("days", f"This plan allows {plan.max_freeze_days} days of freezes in all; "
                                   f"{plan.max_freeze_days - already} are left")
        if enrolment.status in ("cancelled", "expired", "completed"):
            raise ConflictError("Only a running membership can be frozen or paused")
        ends_on = starts_on + timedelta(days=days - 1)
        for f in await MembershipCore.freezes(session, enrolment.id):
            if f.status == "confirmed" and f.starts_on <= ends_on and starts_on <= f.ends_on:
                raise ConflictError("These dates overlap another freeze or pause")
        extends = kind == "freeze"
        row = MembershipFreeze(business_id=enrolment.business_id, enrolment_id=enrolment.id, kind=kind,
                               starts_on=starts_on, ends_on=ends_on, days=days, extends_cover=extends,
                               reason=(reason or "").strip()[:200] or None, approved_by=actor_id, channel=channel)
        session.add(row)
        await session.flush()
        if extends:
            await MembershipCore._shift(session, enrolment, from_day=starts_on, days=days)
        await OutboxService.publish(session, event_type="membership.freeze_added", business_id=enrolment.business_id,
                                    payload={"enrolment_id": str(enrolment.id), "freeze_id": str(row.id),
                                             "kind": kind, "starts_on": str(starts_on), "ends_on": str(ends_on),
                                             "days": days, "customer_contact_id": str(enrolment.customer_contact_id)})
        await MembershipCore.recalculate(session, enrolment, now=now, actor_id=actor_id,
                                         reason=f"{'Frozen' if extends else 'Paused'} {days} days")
        return row

    @staticmethod
    async def cancel_freeze(session: AsyncSession, enrolment: MembershipEnrolment, freeze_id: uuid.UUID, *,
                            actor_id: uuid.UUID | None, now: datetime | None = None) -> MembershipFreeze:
        """Take back a freeze or pause that has not started; the days it added come off again."""
        row = (await session.execute(select(MembershipFreeze).where(
            MembershipFreeze.business_id == enrolment.business_id, MembershipFreeze.id == freeze_id,
            MembershipFreeze.enrolment_id == enrolment.id).with_for_update())).scalars().first()
        if row is None:
            raise ResourceNotFound("Freeze")
        zone = await MembershipCore.tz(session, enrolment.business_id, enrolment.location_id)
        from zoneinfo import ZoneInfo

        today = (now or _now()).astimezone(ZoneInfo(zone)).date()
        if row.status != "confirmed":
            return row
        if row.starts_on <= today:
            raise ConflictError("It has already started; end it early by resuming instead")
        row.status, row.cancelled_at = "cancelled", _now()
        if row.extends_cover:
            await MembershipCore._shift(session, enrolment, from_day=row.starts_on, days=-row.days)
        await session.flush()
        await MembershipCore.recalculate(session, enrolment, now=now, actor_id=actor_id, reason="Freeze taken back")
        return row

    @staticmethod
    async def _shift(session: AsyncSession, enrolment: MembershipEnrolment, *, from_day: date, days: int) -> None:
        """Move the end of every period still running on `from_day` (and every
        later one) by `days`. `base_ends_at` keeps what was bought."""
        for p in await MembershipCore.periods(session, enrolment.id):
            if p.payment_state == "cancelled" or p.ends_at.date() < from_day:
                continue
            p.ends_at = p.ends_at + timedelta(days=days)
            if p.ends_at < p.base_ends_at:
                p.ends_at = p.base_ends_at
        await session.flush()

    # ------------------------------------------------------------------ sessions
    @staticmethod
    async def consume_session(session: AsyncSession, enrolment: MembershipEnrolment, *, source_type: str,
                              source_id: uuid.UUID | None, idempotency_key: str, actor_id: uuid.UUID | None,
                              now: datetime | None = None) -> MembershipSessionUse:
        """One session used — once per key, however often it is asked (§8)."""
        prior = (await session.execute(select(MembershipSessionUse).where(
            MembershipSessionUse.business_id == enrolment.business_id,
            MembershipSessionUse.idempotency_key == idempotency_key))).scalars().first()
        if prior is not None:
            return prior
        await MembershipCore.get(session, enrolment.business_id, enrolment.id, lock=True)
        plan = await MembershipCore.plan_of(session, enrolment)
        if plan.plan_kind != "session_pack":
            raise ConflictError("Only a session pack counts sessions")
        moment = now or _now()
        used = await MembershipCore.sessions_used(session, enrolment.id)
        target = None
        for p in await MembershipCore.periods(session, enrolment.id):
            if p.payment_state in lc.COVERED and p.starts_at <= moment < p.ends_at \
                    and (p.sessions_included or 0) - used.get(str(p.id), 0) > 0:
                target = p
                break
        if target is None:
            raise ConflictError("No sessions left on this pack", details={"code": "no_sessions"})
        use = MembershipSessionUse(business_id=enrolment.business_id, enrolment_id=enrolment.id,
                                   period_id=target.id, source_type=source_type, source_id=source_id,
                                   idempotency_key=idempotency_key, recorded_by=actor_id, used_at=moment)
        session.add(use)
        await session.flush()
        await OutboxService.publish(session, event_type="membership.session_used", business_id=enrolment.business_id,
                                    payload={"enrolment_id": str(enrolment.id), "use_id": str(use.id),
                                             "source_type": source_type,
                                             "source_id": str(source_id) if source_id else None})
        await MembershipCore.recalculate(session, enrolment, now=now, actor_id=actor_id, reason="Session used")
        return use

    @staticmethod
    async def reverse_session(session: AsyncSession, business_id: uuid.UUID, idempotency_key: str, *,
                              reason: str, actor_id: uuid.UUID | None) -> MembershipSessionUse | None:
        use = (await session.execute(select(MembershipSessionUse).where(
            MembershipSessionUse.business_id == business_id, MembershipSessionUse.idempotency_key == idempotency_key)
            .with_for_update())).scalars().first()
        if use is None or use.status == "reversed":
            return use
        use.status, use.reversed_at, use.reason = "reversed", _now(), reason[:200]
        await session.flush()
        enrolment = await MembershipCore.get(session, business_id, use.enrolment_id)
        await OutboxService.publish(session, event_type="membership.session_reversed", business_id=business_id,
                                    payload={"enrolment_id": str(enrolment.id), "use_id": str(use.id)})
        await MembershipCore.recalculate(session, enrolment, actor_id=actor_id, reason="Session given back")
        return use

    # ------------------------------------------------------------------ front desk
    @staticmethod
    async def resolve_code(session: AsyncSession, business_id: uuid.UUID, code_or_id: str) -> MembershipEnrolment:
        raw = (code_or_id or "").strip()
        try:
            return await MembershipCore.get(session, business_id, uuid.UUID(raw))
        except (ValueError, ResourceNotFound):
            pass
        row = (await session.execute(select(MembershipEnrolment).where(
            MembershipEnrolment.business_id == business_id, MembershipEnrolment.checkin_code == raw.upper(),
            MembershipEnrolment.deleted_at.is_(None)))).scalars().first()
        if row is None:
            raise ResourceNotFound("Membership")
        return row

    @staticmethod
    async def checkin_decision(session: AsyncSession, business_id: uuid.UUID, enrolment_id: uuid.UUID, *,
                               now: datetime | None = None) -> dict[str, Any]:
        """Can this member come in? (§6) Green when active, amber in grace if the
        owner allows entry, red otherwise — with the words the desk says."""
        enrolment = await MembershipCore.get(session, business_id, enrolment_id)
        plan = await MembershipCore.plan_of(session, enrolment)
        st = await MembershipCore.recalculate(session, enrolment, now=now, reason="Checked at the front desk")
        contact = await session.get(CustomerContact, enrolment.customer_contact_id)
        decision, why = "denied", STATUS_WORDS.get(st.status, st.status)
        if st.status == "active" and st.starts_later:
            why = "The membership has not started yet"
        elif st.status == "active":
            decision, why = "allowed", "Active"
            if plan.plan_kind == "session_pack" and plan.consume_on == "checkin" and not st.sessions_remaining:
                decision, why = "denied", "No sessions left"
        elif st.status == "grace" and plan.grace_allows_entry:
            decision, why = "warning", "In grace — ask them to renew"
        elif st.status == "paused":
            why = "Frozen — resume the membership first"
        elif st.status == "expired":
            why = "Expired — renew to come in"
        elif st.status == "pending":
            why = "Not paid yet"
        return {"enrolment_id": str(enrolment.id), "customer_contact_id": str(enrolment.customer_contact_id),
                "member": contact.display_name if contact else None, "plan": plan.name, "kind": plan.plan_kind,
                "decision": decision, "colour": CHECKIN_COLOURS[decision], "reason": why, "status": st.status,
                "valid_until": st.valid_until.isoformat() if st.valid_until else None,
                "last_day": st.last_day.isoformat() if st.last_day else None,
                "days_remaining": st.days_remaining, "sessions_remaining": st.sessions_remaining,
                "renew": words(plan.plan_kind)["renew"] if decision != "allowed" else None}

    # ------------------------------------------------------------------ bookings ask (§8)
    @staticmethod
    async def booking_entitlement(session: AsyncSession, business_id: uuid.UUID, contact_id: uuid.UUID,
                                  plan_ids: list[uuid.UUID], *, at: datetime | None = None) -> dict[str, Any] | None:
        """Can this customer book a class their plan covers, and how many
        sessions remain? Bookings asks; Memberships answers (never a separate count)."""
        moment = at or _now()
        rows = (await session.execute(select(MembershipEnrolment).where(
            MembershipEnrolment.business_id == business_id, MembershipEnrolment.customer_contact_id == contact_id,
            MembershipEnrolment.plan_id.in_(plan_ids), MembershipEnrolment.deleted_at.is_(None),
            MembershipEnrolment.status.in_(("active", "grace"))))).scalars().all()
        for enrolment in rows:
            plan = await MembershipCore.plan_of(session, enrolment)
            st = await MembershipCore.state(session, enrolment, plan, now=moment)
            if st.status != "active" and not (st.status == "grace" and plan.grace_allows_entry):
                continue
            if plan.plan_kind == "session_pack" and not st.sessions_remaining:
                continue
            return {"enrolment_id": enrolment.id, "plan_kind": plan.plan_kind, "consume_on": plan.consume_on,
                    "no_show_consumes": plan.no_show_consumes, "sessions_remaining": st.sessions_remaining}
        return None

    # ------------------------------------------------------------------ views
    @staticmethod
    def serialize_period(p: MembershipPeriod) -> dict[str, Any]:
        return {"id": str(p.id), "seq": p.seq, "starts_at": p.starts_at.isoformat(), "ends_at": p.ends_at.isoformat(),
                "base_ends_at": p.base_ends_at.isoformat(), "extended_days": (p.ends_at - p.base_ends_at).days,
                "amount": float(p.amount), "paid_amount": float(p.paid_amount), "payment_state": p.payment_state,
                "sessions_included": p.sessions_included, "source": p.source,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None}

    @staticmethod
    async def detail(session: AsyncSession, enrolment: MembershipEnrolment) -> dict[str, Any]:
        plan = await MembershipCore.plan_of(session, enrolment)
        st = await MembershipCore.state(session, enrolment, plan)
        contact = await session.get(CustomerContact, enrolment.customer_contact_id)
        payer = await session.get(CustomerContact, enrolment.payer_contact_id) if enrolment.payer_contact_id else None
        visits = (await session.execute(select(MembershipServiceVisit).where(
            MembershipServiceVisit.enrolment_id == enrolment.id).order_by(MembershipServiceVisit.due_on))).scalars()
        uses = (await session.execute(select(MembershipSessionUse).where(
            MembershipSessionUse.enrolment_id == enrolment.id).order_by(MembershipSessionUse.used_at.desc())
            .limit(50))).scalars()
        history = (await session.execute(select(MembershipEnrolmentStatusHistory).where(
            MembershipEnrolmentStatusHistory.enrolment_id == enrolment.id)
            .order_by(MembershipEnrolmentStatusHistory.created_at.desc()).limit(30))).scalars()
        # The business's calendar day, so the desk's "today"/"tomorrow" defaults
        # never follow the viewer's (or the server's) UTC clock.
        from zoneinfo import ZoneInfo

        zone = await MembershipCore.tz(session, enrolment.business_id, enrolment.location_id)
        return {
            "today": str(_now().astimezone(ZoneInfo(zone)).date()),
            "id": str(enrolment.id), "plan": {"id": str(plan.id), "name": plan.name, "kind": plan.plan_kind,
                                              "price_amount": float(plan.price_amount),
                                              "duration_days": plan.duration_days, "grace_days": plan.grace_days,
                                              "freeze_allowed": plan.freeze_allowed,
                                              "max_freeze_days": plan.max_freeze_days,
                                              "billing_timing": plan.billing_timing},
            "words": words(plan.plan_kind),
            "member": {"id": str(enrolment.customer_contact_id), "name": contact.display_name if contact else None,
                       "phone": contact.phone if contact else None},
            "payer": {"id": str(payer.id), "name": payer.display_name} if payer else None,
            "status": st.status, "status_words": STATUS_WORDS.get(st.status, st.status), "reason": st.reason,
            "valid_until": st.valid_until.isoformat() if st.valid_until else None,
            "last_day": st.last_day.isoformat() if st.last_day else None,
            "grace_until": st.grace_until.isoformat() if st.grace_until else None,
            "days_remaining": st.days_remaining, "expiring_soon": st.expiring_soon,
            "next_due_on": st.next_due_on.isoformat() if st.next_due_on else None,
            "sessions_remaining": st.sessions_remaining, "charged": float(st.charged), "paid": float(st.paid),
            "outstanding": float(st.outstanding), "overdue": st.overdue, "good_standing": st.good_standing,
            "starts_at": enrolment.starts_at.isoformat(), "checkin_code": enrolment.checkin_code,
            "delivery": enrolment.delivery, "source_ref": {"type": enrolment.source_ref_type,
                                                           "id": str(enrolment.source_ref_id)}
            if enrolment.source_ref_id else None,
            "periods": [MembershipCore.serialize_period(p) for p in await MembershipCore.periods(session, enrolment.id)],
            "freezes": [{"id": str(f.id), "kind": f.kind, "starts_on": str(f.starts_on), "ends_on": str(f.ends_on),
                         "days": f.days, "status": f.status, "reason": f.reason, "extends_cover": f.extends_cover}
                        for f in await MembershipCore.freezes(session, enrolment.id)],
            "instalments": [{"id": str(i.id), "seq": i.seq, "label": i.label, "amount": float(i.amount),
                             "paid_amount": float(i.paid_amount), "due_on": str(i.due_on), "status": i.status}
                            for i in await MembershipCore.instalments(session, enrolment.id)],
            "visits": [{"id": str(v.id), "seq": v.seq, "due_on": str(v.due_on), "status": v.status,
                        "job_ref": str(v.job_ref) if v.job_ref else None} for v in visits],
            "session_uses": [{"id": str(u.id), "used_at": u.used_at.isoformat(), "source_type": u.source_type,
                              "status": u.status} for u in uses],
            "history": [{"from": h.from_status, "to": h.to_status, "reason": h.reason,
                         "at": h.created_at.isoformat() if h.created_at else None} for h in history],
        }
