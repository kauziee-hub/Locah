"""The owner's recurring-relationship home, per kind (Founder refinement §5, §22, §25).

Same engine, different first screen: a gym sees active, expiring, grace,
expired, frozen and renewals today; a milk or tiffin business sees tomorrow's
quantities, skips and pauses; a coaching centre sees instalments due and
overdue and terms ending; an AMC business sees visits due and contracts
expiring; a club sees who is in good standing. Every number is counted from
real rows — nothing is estimated.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.memberships.models import MembershipInstalment, MembershipPeriod, MembershipServiceVisit
from platform_core.memberships.service import MembershipCore
from platform_core.memberships.words import STATUS_WORDS, words
from platform_core.models import CustomerContact, MembershipEnrolment, MembershipPlan

LIMIT = 500


def _name(contacts: dict[Any, CustomerContact], contact_id: Any) -> str | None:
    contact = contacts.get(contact_id)
    return contact.display_name if contact else None


def _row(enrolment: MembershipEnrolment, plan: MembershipPlan, contact: CustomerContact | None,
         st: Any) -> dict[str, Any]:
    return {"id": str(enrolment.id), "member": contact.display_name if contact else None,
            "phone": contact.phone if contact else None, "plan": plan.name, "kind": plan.plan_kind,
            "status": st.status, "status_words": STATUS_WORDS.get(st.status, st.status), "reason": st.reason,
            "valid_until": st.valid_until.isoformat() if st.valid_until else None,
            "last_day": st.last_day.isoformat() if st.last_day else None,
            "days_remaining": st.days_remaining, "expiring_soon": st.expiring_soon,
            "sessions_remaining": st.sessions_remaining, "outstanding": float(st.outstanding),
            "next_due_on": st.next_due_on.isoformat() if st.next_due_on else None, "overdue": st.overdue,
            "good_standing": st.good_standing, "checkin_code": enrolment.checkin_code}


async def kinds_in_use(session: AsyncSession, business_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (await session.execute(select(MembershipPlan.plan_kind, func.count(MembershipEnrolment.id)).outerjoin(
        MembershipEnrolment, (MembershipEnrolment.plan_id == MembershipPlan.id)
        & (MembershipEnrolment.deleted_at.is_(None))).where(
        MembershipPlan.business_id == business_id, MembershipPlan.deleted_at.is_(None),
        MembershipPlan.status != "archived").group_by(MembershipPlan.plan_kind))).all()
    return [{"kind": r[0], "label": words(r[0])["owner_home"], "count": int(r[1])} for r in rows]


async def board(session: AsyncSession, business_id: uuid.UUID, *, kind: str | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    zone = ZoneInfo(await MembershipCore.tz(session, business_id))
    today = moment.astimezone(zone).date()
    kinds = await kinds_in_use(session, business_id)
    if kind is None:
        kind = max(kinds, key=lambda k: k["count"])["kind"] if kinds else "access"
    q = select(MembershipEnrolment, MembershipPlan).join(
        MembershipPlan, MembershipPlan.id == MembershipEnrolment.plan_id).where(
        MembershipEnrolment.business_id == business_id, MembershipEnrolment.deleted_at.is_(None),
        MembershipPlan.plan_kind == kind).order_by(MembershipEnrolment.created_at.desc()).limit(LIMIT)
    rows = (await session.execute(q)).all()
    contacts = {c.id: c for c in (await session.execute(select(CustomerContact).where(
        CustomerContact.id.in_([e.customer_contact_id for e, _ in rows] or [uuid.uuid4()])))).scalars()}
    items = []
    for enrolment, plan in rows:
        st = await MembershipCore.state(session, enrolment, plan, now=moment)
        items.append(_row(enrolment, plan, contacts.get(enrolment.customer_contact_id), st))

    def bucket(pred: Any) -> list[dict[str, Any]]:
        return [i for i in items if pred(i)]

    renewed_today = (await session.execute(select(func.count()).select_from(MembershipPeriod).join(
        MembershipEnrolment, MembershipEnrolment.id == MembershipPeriod.enrolment_id).join(
        MembershipPlan, MembershipPlan.id == MembershipEnrolment.plan_id).where(
        MembershipPeriod.business_id == business_id, MembershipPlan.plan_kind == kind, MembershipPeriod.seq > 1,
        MembershipPeriod.payment_state == "paid",
        MembershipPeriod.paid_at >= datetime.combine(today, datetime.min.time(), zone)))).scalar_one()
    out: dict[str, Any] = {
        "kind": kind, "words": words(kind), "kinds": kinds, "today": str(today),
        "counts": {
            "active": len(bucket(lambda i: i["status"] == "active")),
            "expiring_soon": len(bucket(lambda i: i["expiring_soon"])),
            "due_today": len(bucket(lambda i: i["next_due_on"] == str(today) and i["status"] != "cancelled")),
            "payment_pending": len(bucket(lambda i: i["status"] == "pending")),
            "grace": len(bucket(lambda i: i["status"] == "grace")),
            "expired": len(bucket(lambda i: i["status"] == "expired")),
            "paused": len(bucket(lambda i: i["status"] == "paused")),
            "renewed_today": int(renewed_today),
        },
        "rows": items,
    }
    if kind == "recurring_delivery":
        from platform_core.memberships.subscriptions import SubscriptionService

        out["tomorrow"] = await SubscriptionService.board(session, business_id, today + timedelta(days=1))
        out["today_deliveries"] = await SubscriptionService.board(session, business_id, today)
    if kind == "fee_plan":
        inst = (await session.execute(select(MembershipInstalment, MembershipEnrolment).join(
            MembershipEnrolment, MembershipEnrolment.id == MembershipInstalment.enrolment_id).where(
            MembershipInstalment.business_id == business_id, MembershipInstalment.status.in_(("due", "part_paid")),
            MembershipEnrolment.status.notin_(("cancelled", "completed")),
            MembershipInstalment.due_on <= today + timedelta(days=7)).order_by(MembershipInstalment.due_on))).all()
        out["instalments"] = [{
            "id": str(i.id), "enrolment_id": str(e.id), "label": i.label,
            "student": _name(contacts, e.customer_contact_id),
            "amount": float(i.amount) - float(i.paid_amount), "due_on": str(i.due_on),
            "overdue": i.due_on < today} for i, e in inst]
        out["counts"]["overdue"] = sum(1 for x in out["instalments"] if x["overdue"])
        out["counts"]["term_ending_week"] = len(bucket(lambda i: i["valid_until"] and date.fromisoformat(
            i["valid_until"][:10]) <= today + timedelta(days=7) and i["status"] == "active"))
    if kind == "service_contract":
        visits = (await session.execute(select(MembershipServiceVisit, MembershipEnrolment).join(
            MembershipEnrolment, MembershipEnrolment.id == MembershipServiceVisit.enrolment_id).where(
            MembershipServiceVisit.business_id == business_id,
            MembershipServiceVisit.status.in_(("scheduled", "requested")),
            MembershipServiceVisit.due_on <= today + timedelta(days=30)).order_by(MembershipServiceVisit.due_on))).all()
        out["visits_due"] = [{
            "id": str(v.id), "enrolment_id": str(e.id), "due_on": str(v.due_on), "status": v.status,
            "customer": _name(contacts, e.customer_contact_id),
            "job_ref": str(v.job_ref) if v.job_ref else None} for v, e in visits]
    if kind == "member_dues":
        out["counts"]["good_standing"] = len(bucket(lambda i: i["good_standing"] is True))
        out["counts"]["not_in_good_standing"] = len(bucket(lambda i: i["good_standing"] is False))
    return out


async def needs_attention(session: AsyncSession, business_id: uuid.UUID, *, now: datetime | None = None) -> list[str]:
    """Owner-words lines for Home › Needs you now (§25) — only real exceptions."""
    out: list[str] = []
    for k in await kinds_in_use(session, business_id):
        b = await board(session, business_id, kind=k["kind"], now=now)
        c, w = b["counts"], b["words"]
        if c["expiring_soon"]:
            out.append(f"{c['expiring_soon']} {w['noun']}s end within a week")
        if c["grace"]:
            out.append(f"{c['grace']} {w['noun']}s are in grace, not renewed")
        if c.get("overdue"):
            out.append(f"{c['overdue']} fee instalments are overdue")
        if b.get("tomorrow"):
            t = b["tomorrow"]["slots"]
            off = sum(v["skipped"] + v["paused"] for v in t.values())
            if off:
                out.append(f"{off} deliveries tomorrow are skipped or paused")
        if b.get("visits_due"):
            out.append(f"{len(b['visits_due'])} service visits are due within 30 days")
    return out
