"""Collect what is due, simply (Founder refinement — Payments; MD §6.1, §12.4).

Payments answers five questions for any transaction — an order, a booking, a
membership, a bill or a khata balance: how much is due, how much is being
collected now, how it is paid, whether it was actually confirmed, and what
remains. The transaction's own state never changes because a payment attempt
failed; retrying creates a new attempt on the same transaction, never a new
order.

A **payment request** is a secure link for an amount (full, advance, deposit,
balance or dues). The customer pays it by:

* **UPI to the business's own UPI ID** — LOCAH cannot see that money arrive, so
  the attempt stays "being confirmed" until the business confirms it arrived
  (or says it did not, and the customer can try again);
* **online through a payment provider** — only when the business has an active
  provider connection, and confirmed only by the provider's verified webhook
  (Cashfree direction; activation pending, so not offered today).

The browser is never payment truth. A webhook replay never pays twice; a
second payment for a link that was already paid is kept (the money moved) and
flagged for a refund.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceNotFound, ValidationError
from platform_core.models import (
    Booking,
    InvoicingDocument,
    LedgerAccount,
    MembershipEnrolment,
    MembershipPlan,
    PaymentAttempt,
    PaymentRequest,
    SalesOrder,
)
from platform_core.services.audit import AuditService
from platform_core.services.outbox import OutboxService

ZERO = Decimal("0")
PAID_STATUSES = ("succeeded", "partially_refunded", "refunded")
PURPOSES = {"full": "Full payment", "advance": "Advance", "deposit": "Deposit", "balance": "Balance",
            "dues": "Dues"}
# Money the business records itself (the counter, a bank transfer, a card on
# its own terminal) — true when recorded, like a cash bill.
RECORDED_METHODS = {"cash": "Cash", "upi": "UPI", "card": "Card (own terminal)", "bank_transfer": "Bank transfer"}
_INVOICE_METHOD = {"upi_direct": "upi", "online": "other", "cash": "cash", "upi": "upi", "card": "card",
                   "bank_transfer": "bank_transfer"}
LINK_DAYS = 7
# Chosen at checkout; settled by collecting the money, closed if it came another way.
OFFLINE_INTENTS = ("cod", "pay_at_business", "pay_later")
ONLINE_LINKS_ACTIVE = False

# What a customer reads (§13) — never provider words.
STATE_WORDS = {
    "paid": "Payment received",
    "failed": "Payment failed — try again",
    "pending": "Payment still being confirmed",
    "partially_paid": "Part paid",
    "unpaid": "Not paid yet",
    "refunded": "Refunded",
    "partially_refunded": "Part refunded",
}
# How a payment came or is meant to come, as the Workspace shows it.
ATTEMPT_METHOD_WORDS = {"upi_direct": "UPI to your UPI ID", "online": "Online", "cod": "Cash on delivery",
                        "pay_at_business": "Pay at the business", "pay_later": "Pay later", **RECORDED_METHODS}
# What the OWNER reads about one payment (the Workspace) — never a status code.
OWNER_STATUS_WORDS = {
    "pending": "Waiting for payment", "processing": "Being processed", "pending_offline": "To collect",
    "succeeded": "Received", "failed": "Failed", "partially_refunded": "Part refunded", "refunded": "Refunded",
    "cancelled": "Cancelled", "expired": "Expired",
}
# A payment link's state as its page says it (the tenant page translates these — P1-10E6).
LINK_STATE_WORDS: dict[str, str | None] = {
    "open": None, "being_confirmed": STATE_WORDS["pending"], "failed": STATE_WORDS["failed"],
    "paid": STATE_WORDS["paid"], "cancelled": "This payment link was cancelled",
    "expired": "This payment link has expired — ask for a new one",
}


def _d(v: Any) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _f(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def _inr(v: Decimal) -> str:
    return f"₹{v:,.2f}".replace(".00", "")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def payment_state(total: Decimal | None, paid: Decimal, refunded: Decimal, *, pending: bool,
                  last_failed: bool) -> str:
    """One transaction's payment state (§2), separate from its own state. Pure."""
    if refunded > 0:
        return "refunded" if paid - refunded <= 0 else "partially_refunded"
    if paid > 0 and (total is None or paid >= total):
        return "paid"
    if pending:
        return "pending"
    if paid > 0:
        return "partially_paid"
    if last_failed:
        return "failed"
    return "unpaid"


def upi_link(vpa: str, payee: str, amount: Decimal, note: str) -> str:
    """UPI intent for the exact amount, straight to the business (§8 'exact amount')."""
    return (f"upi://pay?pa={quote(vpa, safe='@.')}&pn={quote(payee[:40])}&am={amount:.2f}&cu=INR"
            f"&tn={quote(note[:60])}")


@dataclass
class Source:
    source_type: str
    source_id: uuid.UUID
    label: str
    total: Decimal | None
    customer_contact_id: uuid.UUID | None
    collectable: bool
    why_not: str | None = None
    # bills and khata keep their own paid figure (the shared document system)
    own_paid: Decimal | None = None
    own_balance: Decimal | None = None


class PaymentCollectService:
    # ------------------------------------------------------------------ what is due
    @staticmethod
    async def source(session: AsyncSession, business_id: uuid.UUID, source_type: str,
                     source_id: uuid.UUID) -> Source:
        if source_type == "order":
            order = (await session.execute(select(SalesOrder).where(
                SalesOrder.business_id == business_id, SalesOrder.id == source_id,
                SalesOrder.deleted_at.is_(None)))).scalars().first()
            if order is None:
                raise ResourceNotFound("Order")
            dead = order.status in ("cancelled", "rejected")
            return Source("order", order.id, f"Order {order.order_number}", _d(order.total_amount),
                          order.customer_contact_id, not dead, "This order was cancelled" if dead else None)
        if source_type == "booking":
            booking = (await session.execute(select(Booking).where(
                Booking.business_id == business_id, Booking.id == source_id))).scalars().first()
            if booking is None:
                raise ResourceNotFound("Booking")
            dead = booking.status in ("cancelled", "rejected")
            total = _d(booking.total_amount) if booking.total_amount is not None else None
            return Source("booking", booking.id, f"Booking {booking.booking_number} · {booking.title}", total,
                          booking.customer_contact_id, not dead, "This booking was cancelled" if dead else None)
        if source_type == "membership":
            row = (await session.execute(select(MembershipEnrolment, MembershipPlan).join(
                MembershipPlan, MembershipPlan.id == MembershipEnrolment.plan_id).where(
                MembershipEnrolment.business_id == business_id, MembershipEnrolment.id == source_id))).first()
            if row is None:
                raise ResourceNotFound("Membership")
            enrolment, plan = row
            from platform_core.memberships.service import MembershipCore
            from platform_core.memberships.words import words

            dead = enrolment.status == "cancelled"
            postpaid = plan.plan_kind == "recurring_delivery" and plan.billing_timing == "postpaid"
            why = ("This membership was cancelled" if dead else
                   "Billed on the customer's khata at month end — collect there" if postpaid else None)
            # What the relationship has charged (its periods and instalments),
            # not the plan's price: renewals and fee instalments add up.
            return Source("membership", enrolment.id, f"{words(plan.plan_kind)['kind_label']} · {plan.name}",
                          await MembershipCore.charged(session, enrolment),
                          enrolment.payer_contact_id or enrolment.customer_contact_id, why is None, why)
        if source_type == "invoice":
            from platform_core.services.invoicing import InvoiceService

            doc = (await session.execute(select(InvoicingDocument).where(
                InvoicingDocument.business_id == business_id, InvoicingDocument.id == source_id))).scalars().first()
            if doc is None:
                raise ResourceNotFound("Bill")
            view = await InvoiceService._money_view(session, doc)
            outstanding = _d(view["outstanding"])
            why = None
            if doc.status != "issued" or doc.doc_kind == "credit_note":
                why = "Only an issued bill can be paid"
            elif doc.on_account:
                why = "This bill is on the customer's khata — ask for the khata balance instead"
            elif doc.order_id:
                why = "This bill belongs to an order — collect on the order"
            return Source("invoice", doc.id, f"Bill {doc.number or ''}".strip(), _d(doc.amount_due),
                          doc.customer_contact_id, why is None, why,
                          own_paid=_d(doc.amount_due) - outstanding, own_balance=outstanding)
        if source_type == "khata":
            acct = (await session.execute(select(LedgerAccount).where(
                LedgerAccount.business_id == business_id, LedgerAccount.id == source_id))).scalars().first()
            if acct is None or acct.party_type != "customer":
                raise ResourceNotFound("Khata")
            balance = max(_d(acct.balance), ZERO)
            return Source("khata", acct.id, f"Khata · {acct.display_name}", None, acct.customer_contact_id,
                          balance > 0, None if balance > 0 else "Nothing is owed on this khata",
                          own_paid=None, own_balance=balance)
        raise ValidationError("Payments can be asked for an order, booking, membership, bill or khata")

    @staticmethod
    async def _attempts(session: AsyncSession, business_id: uuid.UUID, src: Source) -> list[PaymentAttempt]:
        return list((await session.execute(select(PaymentAttempt).where(
            PaymentAttempt.business_id == business_id, PaymentAttempt.source_type == src.source_type,
            PaymentAttempt.source_id == src.source_id, PaymentAttempt.deleted_at.is_(None))
            .order_by(PaymentAttempt.created_at))).scalars().all())

    @staticmethod
    def _awaiting(a: PaymentAttempt) -> bool:
        """An attempt that may still turn into money: UPI the business has not
        confirmed yet, or an online payment the provider has not settled.
        (Cash on delivery is simply unpaid until it is collected.)"""
        method, status = str(a.payment_method), str(a.status)
        return (method == "upi_direct" and status == "pending_offline") or (method == "online" and status == "processing")

    @staticmethod
    async def money(session: AsyncSession, business_id: uuid.UUID, source_type: str,
                    source_id: uuid.UUID) -> dict[str, Any]:
        """Total, paid, being confirmed and balance for one transaction (§5, §10, §13)."""
        src = await PaymentCollectService.source(session, business_id, source_type, source_id)
        attempts = await PaymentCollectService._attempts(session, business_id, src)
        mine = [a for a in attempts if a.status in PAID_STATUSES]
        refunded = sum((_d(a.refunded_amount) for a in mine), ZERO)
        if src.own_paid is not None or src.source_type == "khata":
            paid = src.own_paid or ZERO
        else:
            paid = sum((_d(a.amount) for a in mine), ZERO)
        awaiting = sum((_d(a.amount) for a in attempts if PaymentCollectService._awaiting(a)), ZERO)
        last = attempts[-1] if attempts else None
        if src.source_type == "khata":
            balance: Decimal | None = src.own_balance
        elif src.own_balance is not None:
            balance = src.own_balance
        else:
            # A refund is money the business chose to give back (a return, a
            # goodwill gesture); it never reopens a balance to chase (§9).
            balance = max(src.total - paid, ZERO) if src.total is not None else None
        state = payment_state(src.total, paid, refunded, pending=awaiting > 0,
                              last_failed=bool(last and last.status == "failed"))
        pickup = False
        if src.source_type == "order":
            from platform_core.models import FulfilmentJob

            pickup = (await session.execute(select(FulfilmentJob.mode).where(
                FulfilmentJob.business_id == business_id, FulfilmentJob.order_id == src.source_id))).scalar() == "pickup"
        if src.source_type == "khata":
            state = "pending" if awaiting > 0 else ("unpaid" if (balance or 0) > 0 else "paid")
        words = STATE_WORDS[state]
        if state in ("partially_paid", "pending") and balance:
            words = f"{words} · Balance {_inr(balance)} remaining" if state == "partially_paid" else words
        return {
            "source_type": src.source_type, "source_id": str(src.source_id), "label": src.label,
            "total": _f(src.total), "paid": _f(paid), "refunded": _f(refunded), "being_confirmed": _f(awaiting),
            "balance": _f(balance), "state": state, "state_words": words, "collectable": src.collectable,
            "why_not": src.why_not, "customer_contact_id": str(src.customer_contact_id) if src.customer_contact_id
            else None,
            # the advance its items asked (dated pre-orders)
            "advance": await PaymentCollectService._advance(session, src),
            "attempts": [PaymentCollectService._intent_row(a, balance, pickup) if a.payment_method in OFFLINE_INTENTS
                         else PaymentCollectService._attempt_row(a) for a in reversed(attempts)],
        }

    @staticmethod
    async def _advance(session: AsyncSession, src: Source) -> float | None:
        if src.source_type != "order":
            return None
        value = (await session.execute(select(SalesOrder.advance_amount).where(
            SalesOrder.id == src.source_id))).scalar()
        return float(value) if value is not None else None

    @staticmethod
    def _intent_row(a: PaymentAttempt, balance: Decimal | None, pickup: bool) -> dict[str, Any]:
        """What the customer chose at checkout — pay on delivery, at pickup or
        later. Not money: while open it stands for what is still to collect."""
        row = PaymentCollectService._attempt_row(a)
        if a.payment_method == "cod":
            row["method_label"] = "Pay at pickup" if pickup else "Cash on delivery"
        if a.status == "pending_offline" and balance is not None:
            row["amount"] = float(min(_d(a.amount), balance))
        return row

    @staticmethod
    def status_label(a: PaymentAttempt) -> str:
        if a.status == "pending_offline" and a.payment_method == "upi_direct":
            return "Customer says paid — check it arrived"
        return str(OWNER_STATUS_WORDS.get(a.status) or str(a.status).replace("_", " ").capitalize())

    @staticmethod
    async def describe(session: AsyncSession, business_id: uuid.UUID,
                       payments: list[PaymentAttempt]) -> list[dict[str, Any]]:
        """Payments as the Workspace shows them: what each was for ("Order
        NILA-0042"), how it was paid and where it stands, in plain words."""
        from platform_core.resolvers.payment_resolver import PaymentResolver

        labels: dict[tuple[str, str], str] = {}
        out = []
        for a in payments:
            key = (a.source_type, str(a.source_id))
            if key not in labels:
                try:
                    labels[key] = (await PaymentCollectService.source(session, business_id, a.source_type,
                                                                      a.source_id)).label
                except (ResourceNotFound, ValidationError):
                    labels[key] = a.source_type.replace("_", " ").capitalize()
            out.append(PaymentResolver.serialize_attempt(a) | {
                "for": labels[key],
                "method_label": ATTEMPT_METHOD_WORDS.get(a.payment_method, a.payment_method),
                "status_label": PaymentCollectService.status_label(a),
                "purpose_label": PURPOSES.get(str(a.purpose or ""), None),
                "verified_at": a.verified_at.isoformat() if a.verified_at else None,
            })
        return out

    @staticmethod
    def _attempt_row(a: PaymentAttempt) -> dict[str, Any]:
        return {"id": str(a.id), "amount": float(a.amount), "method": a.payment_method,
                "method_label": ATTEMPT_METHOD_WORDS.get(a.payment_method, a.payment_method), "status": a.status,
                "purpose": a.purpose, "reference": a.reference, "attention": a.attention,
                "request_id": str(a.request_id) if a.request_id else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                "failure_reason": a.failure_reason}

    # ------------------------------------------------------------------ asking for money
    @staticmethod
    async def create_request(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, *,
                             source_type: str, source_id: uuid.UUID, amount: Any, purpose: str,
                             note: str | None, correlation_id: str) -> tuple[PaymentRequest, str]:
        if purpose not in PURPOSES:
            raise ValidationError("Choose what this payment is for", details={"field": "purpose"})
        src = await PaymentCollectService.source(session, business_id, source_type, source_id)
        if not src.collectable:
            raise ValidationError(src.why_not or "Nothing can be collected on this", details={"field": "source"})
        view = await PaymentCollectService.money(session, business_id, source_type, source_id)
        value = _d(amount)
        if value <= 0:
            raise ValidationError("Enter the amount to ask for", details={"field": "amount"})
        balance = view["balance"]
        if balance is not None and value > _d(balance):
            raise ValidationError(f"Only {_inr(_d(balance))} is still due", details={"field": "amount"})
        token = secrets.token_urlsafe(18)
        req = PaymentRequest(business_id=business_id, source_type=src.source_type, source_id=src.source_id,
                             customer_contact_id=src.customer_contact_id, purpose=purpose, amount=value,
                             token_hash=token_hash(token), status="open",
                             note=(note or "").strip()[:200] or None,
                             expires_at=datetime.now(timezone.utc) + timedelta(days=LINK_DAYS), created_by=actor_id)
        session.add(req)
        await session.flush()
        payload = {"request_id": str(req.id), "source_type": src.source_type, "source_id": str(src.source_id),
                   "amount": float(value), "purpose": purpose}
        await OutboxService.publish(session, event_type="payment.request.created", business_id=business_id,
                                    payload=payload, correlation_id=correlation_id)
        await AuditService.record(session, event_type="payment.request.created", actor_identity_id=actor_id,
                                  actor_context="business", action="create", business_id=business_id,
                                  resource_type="payment_request", resource_id=req.id, after_state=payload)
        return req, token

    @staticmethod
    async def cancel_request(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID,
                             request_id: uuid.UUID) -> PaymentRequest:
        req = await PaymentCollectService._request(session, business_id, request_id)
        if req.status != "open":
            raise ConflictError("Only an open payment link can be cancelled")
        if any(PaymentCollectService._awaiting(a) for a in await PaymentCollectService._request_attempts(session, req)):
            raise ConflictError("A payment on this link is still being confirmed — confirm or reject it first")
        req.status = "cancelled"
        req.cancelled_at = datetime.now(timezone.utc)
        req.version += 1
        await AuditService.record(session, event_type="payment.request.cancelled", actor_identity_id=actor_id,
                                  actor_context="business", action="cancel", business_id=business_id,
                                  resource_type="payment_request", resource_id=req.id)
        return req

    @staticmethod
    async def send_on_whatsapp(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID,
                               request_id: uuid.UUID, token: str) -> Any:
        """Send an open link from the business's own WhatsApp number. The caller
        proves it holds the link (its token matches the stored hash); LOCAH
        never keeps the token itself."""
        from platform_core.models import Business, CustomerContact
        from platform_core.services.messaging import MessagingService, NotSent
        from platform_core.site_urls import business_site_url

        req = await PaymentCollectService._request(session, business_id, request_id)
        if not secrets.compare_digest(req.token_hash, token_hash(token)):
            raise ResourceNotFound("Payment link")
        if req.status != "open" or req.expires_at <= datetime.now(timezone.utc):
            raise ConflictError("Only an open payment link can be sent")
        contact = await session.get(CustomerContact, req.customer_contact_id) if req.customer_contact_id else None
        if contact is None or not contact.phone:
            raise ValidationError("This customer has no phone number", details={"field": "phone"})
        business = await session.get(Business, business_id)
        assert business is not None
        src = await PaymentCollectService.source(session, business_id, req.source_type, req.source_id)
        what = f"{_inr(_d(req.amount))} ({PURPOSES[req.purpose].lower()} for {src.label})"
        try:
            msg = await MessagingService.send_template(
                session, business_id, to=contact.phone, key="payment_due", contact_id=contact.id,
                params=[business.display_name, what, business_site_url(business.slug, f"/pay/{token}")],
                sent_via="workspace", sent_by=actor_id, idempotency_key=f"payreq:{req.id}:{uuid.uuid4()}")
        except NotSent as exc:
            raise ConflictError(str(exc)) from exc
        if msg.status != "sent":
            raise ConflictError(f"Not sent: {msg.error or msg.status}")
        return msg

    @staticmethod
    async def _request(session: AsyncSession, business_id: uuid.UUID, request_id: uuid.UUID) -> PaymentRequest:
        req = (await session.execute(select(PaymentRequest).where(
            PaymentRequest.business_id == business_id, PaymentRequest.id == request_id)
            .with_for_update())).scalars().first()
        if req is None:
            raise ResourceNotFound("Payment link")
        return req

    @staticmethod
    async def _request_attempts(session: AsyncSession, req: PaymentRequest) -> list[PaymentAttempt]:
        return list((await session.execute(select(PaymentAttempt).where(
            PaymentAttempt.business_id == req.business_id, PaymentAttempt.request_id == req.id,
            PaymentAttempt.deleted_at.is_(None)).order_by(PaymentAttempt.created_at))).scalars().all())

    @staticmethod
    async def requests_for(session: AsyncSession, business_id: uuid.UUID, source_type: str,
                           source_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = (await session.execute(select(PaymentRequest).where(
            PaymentRequest.business_id == business_id, PaymentRequest.source_type == source_type,
            PaymentRequest.source_id == source_id).order_by(PaymentRequest.created_at.desc()))).scalars().all()
        return [PaymentCollectService._request_row(r) for r in rows]

    @staticmethod
    def _request_row(r: PaymentRequest) -> dict[str, Any]:
        expired = r.status == "open" and r.expires_at <= datetime.now(timezone.utc)
        return {"id": str(r.id), "amount": float(r.amount), "purpose": r.purpose,
                "purpose_label": PURPOSES.get(r.purpose, r.purpose), "status": "expired" if expired else r.status,
                "note": r.note, "expires_at": r.expires_at.isoformat(),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "paid_at": r.paid_at.isoformat() if r.paid_at else None}

    # ------------------------------------------------------------------ the customer's side
    @staticmethod
    async def resolve_public(session: AsyncSession, slug: str, token: str, *,
                             lock: bool = False) -> tuple[Any, PaymentRequest]:
        from platform_core.context_resolver import bind_public_context
        from platform_core.models import Business

        # The link's token is the credential (like a bill's): it names its
        # business, which is then bound for this request only, and the slug in
        # the URL must match. A private business with no website can be paid.
        if not 16 <= len(token) <= 64:
            raise ResourceNotFound("Payment link")
        digest = token_hash(token)
        business_id = (await session.execute(text("SELECT payment_request_business(:h)"), {"h": digest})).scalar()
        if business_id is None:
            raise ResourceNotFound("Payment link")
        await bind_public_context(session, business_id)
        business = await session.get(Business, business_id)
        if business is None or business.deleted_at is not None or business.slug != slug:
            raise ResourceNotFound("Payment link")
        q = select(PaymentRequest).where(PaymentRequest.business_id == business.id,
                                         PaymentRequest.token_hash == digest)
        if lock:
            q = q.with_for_update()
        req = (await session.execute(q)).scalars().first()
        if req is None:
            raise ResourceNotFound("Payment link")
        return business, req

    @staticmethod
    async def public_view(session: AsyncSession, slug: str, token: str) -> dict[str, Any]:
        from platform_core.models import PosSettings
        from platform_core.services.website_publish import _public_contact

        business, req = await PaymentCollectService.resolve_public(session, slug, token)
        money = await PaymentCollectService.money(session, business.id, req.source_type, req.source_id)
        attempts = await PaymentCollectService._request_attempts(session, req)
        last = attempts[-1] if attempts else None
        now = datetime.now(timezone.utc)
        link_state = req.status
        if req.status == "open" and req.expires_at <= now:
            link_state = "expired"
        if link_state == "open" and last is not None:
            if PaymentCollectService._awaiting(last):
                link_state = "being_confirmed"
            elif last.status == "failed":
                link_state = "failed"
        pos = await session.get(PosSettings, business.id)
        amount = _d(req.amount)
        methods: list[dict[str, Any]] = []
        if link_state in ("open", "failed") and pos is not None and pos.upi_vpa:
            methods.append({"method": "upi_direct", "label": "Pay by UPI",
                            "upi_link": upi_link(pos.upi_vpa, pos.upi_payee_name or business.display_name, amount,
                                                 f"{money['label']} {PURPOSES[req.purpose]}"),
                            "upi_id": pos.upi_vpa,
                            "how": f"Pay {_inr(amount)} to {business.display_name} in any UPI app, then tap "
                                   "“I have paid”. They confirm it arrived."})
        online = await PaymentCollectService.online_available(session, business.id)
        if link_state in ("open", "failed") and online:
            methods.append({"method": "online", "label": "Pay online"})
        paying_now = amount if link_state not in ("paid", "cancelled", "expired") else ZERO
        balance = _d(money["balance"]) if money["balance"] is not None else None
        return {
            "business": {"name": business.display_name, "slug": business.slug,
                         "contact": await _public_contact(session, business.id)},
            "for": money["label"], "purpose": req.purpose, "purpose_label": PURPOSES[req.purpose],
            "note": req.note, "state": link_state,
            "state_words": LINK_STATE_WORDS[link_state],
            "amount_due": _f(_d(money["total"])) if money["total"] is not None else money["balance"],
            "already_paid": money["paid"], "paying_now": _f(paying_now),
            "balance_after": _f(max(balance - paying_now, ZERO)) if balance is not None else None,
            "balance_now": money["balance"],
            "methods": methods,
            "last_attempt": PaymentCollectService._attempt_row(last) if last is not None else None,
            "expires_at": req.expires_at.isoformat(),
        }

    @staticmethod
    async def online_available(session: AsyncSession, business_id: uuid.UUID) -> bool:
        """Online payment on a link needs the provider-neutral online adapter
        (Cashfree direction). It is not activated, so no link offers "Pay
        online" yet — ACTIVATION_REQUIRED, never a button that cannot work.
        (The legacy Razorpay route stays as it was and is not extended.)"""
        return ONLINE_LINKS_ACTIVE

    @staticmethod
    async def customer_paid(session: AsyncSession, slug: str, token: str, *, reference: str | None,
                            correlation_id: str) -> dict[str, Any]:
        """The customer says they paid by UPI. That is a claim, not payment
        truth: the attempt waits for the business to confirm it arrived. Never
        a second attempt while one is still being confirmed (§4)."""
        business, req = await PaymentCollectService.resolve_public(session, slug, token, lock=True)
        if req.status != "open" or req.expires_at <= datetime.now(timezone.utc):
            return await PaymentCollectService.public_view(session, slug, token)
        attempts = await PaymentCollectService._request_attempts(session, req)
        if any(PaymentCollectService._awaiting(a) for a in attempts):
            return await PaymentCollectService.public_view(session, slug, token)
        from platform_core.models import PosSettings

        pos = await session.get(PosSettings, business.id)
        if pos is None or not pos.upi_vpa:
            raise ValidationError("This business does not take UPI on payment links")
        attempt = PaymentAttempt(
            business_id=business.id, customer_contact_id=req.customer_contact_id, source_type=req.source_type,
            source_id=req.source_id, amount=float(req.amount), currency=req.currency, payment_method="upi_direct",
            status="pending_offline", provider="upi_direct", request_id=req.id, purpose=req.purpose,
            reference=(reference or "").strip()[:120] or None,
            idempotency_key=f"req:{req.id}:{len(attempts) + 1}")
        session.add(attempt)
        await session.flush()
        payload = {"payment_id": str(attempt.id), "request_id": str(req.id), "amount": float(req.amount),
                   "source_type": req.source_type, "source_id": str(req.source_id),
                   "reference": attempt.reference}
        await OutboxService.publish(session, event_type="payment.confirmation_requested", business_id=business.id,
                                    payload=payload, correlation_id=correlation_id)
        return await PaymentCollectService.public_view(session, slug, token)

    @staticmethod
    async def customer_not_paid(session: AsyncSession, slug: str, token: str) -> dict[str, Any]:
        """The customer withdraws a UPI claim before the business confirmed it
        ("I haven't paid yet") — then another try is safe (§4)."""
        _, req = await PaymentCollectService.resolve_public(session, slug, token, lock=True)
        for a in await PaymentCollectService._request_attempts(session, req):
            if a.payment_method == "upi_direct" and a.status == "pending_offline":
                a.status = "cancelled"
                a.failure_reason = "Withdrawn by the customer"
                a.version += 1
        await session.flush()
        return await PaymentCollectService.public_view(session, slug, token)

    # ------------------------------------------------------------------ the business's side
    @staticmethod
    async def confirm(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, attempt_id: uuid.UUID,
                      *, arrived: bool, correlation_id: str) -> PaymentAttempt:
        """The business checked its UPI app: the money arrived, or it did not."""
        from platform_core.services.payment_attempt import PaymentAttemptService

        attempt = (await session.execute(select(PaymentAttempt).where(
            PaymentAttempt.business_id == business_id, PaymentAttempt.id == attempt_id,
            PaymentAttempt.deleted_at.is_(None)).with_for_update())).scalars().first()
        if attempt is None:
            raise ResourceNotFound("Payment")
        if not (attempt.payment_method == "upi_direct" and attempt.status == "pending_offline"):
            raise ConflictError("Only a UPI payment waiting for you to confirm can be confirmed")
        attempt.verified_by = actor_id
        attempt.verified_at = datetime.now(timezone.utc)
        if arrived:
            await PaymentAttemptService.apply_status(session, payment=attempt, target_status="succeeded",
                                                     correlation_id=correlation_id, actor_id=actor_id)
        else:
            await PaymentAttemptService.apply_status(session, payment=attempt, target_status="failed",
                                                     correlation_id=correlation_id, actor_id=actor_id,
                                                     failure_code="not_received",
                                                     failure_reason="The business did not receive this payment")
        return attempt

    @staticmethod
    async def record(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, *, source_type: str,
                     source_id: uuid.UUID, amount: Any, method: str, reference: str | None,
                     purpose: str | None, correlation_id: str) -> PaymentAttempt:
        """Money the business took itself against an order, booking or
        membership — cash at pickup, UPI at the counter, a card on its own
        terminal, a bank transfer (§8, §10). Bills and khata keep their own
        'record payment' screens."""
        from platform_core.services.payment_attempt import PaymentAttemptService

        if method not in RECORDED_METHODS:
            raise ValidationError("Choose how it was paid", details={"field": "method"})
        if source_type not in ("order", "booking", "membership"):
            raise ValidationError("Record bill and khata payments on the bill or the khata")
        src = await PaymentCollectService.source(session, business_id, source_type, source_id)
        if not src.collectable:
            raise ValidationError(src.why_not or "Nothing can be collected on this")
        view = await PaymentCollectService.money(session, business_id, source_type, source_id)
        value = _d(amount)
        if value <= 0:
            raise ValidationError("Enter the amount received", details={"field": "amount"})
        if view["balance"] is not None and value > _d(view["balance"]):
            raise ValidationError(f"Only {_inr(_d(view['balance']))} is still due", details={"field": "amount"})
        attempt = PaymentAttempt(
            business_id=business_id, customer_contact_id=src.customer_contact_id, source_type=source_type,
            source_id=source_id, amount=float(value), payment_method=method, status="pending_offline",
            provider="recorded", purpose=purpose or ("full" if view["balance"] is not None
                                                     and value == _d(view["balance"]) else "balance"),
            reference=(reference or "").strip()[:120] or None, verified_by=actor_id,
            verified_at=datetime.now(timezone.utc))
        session.add(attempt)
        await session.flush()
        await PaymentAttemptService.apply_status(session, payment=attempt, target_status="succeeded",
                                                 correlation_id=correlation_id, actor_id=actor_id)
        return attempt

    # ------------------------------------------------------------------ settlement (called on success)
    @staticmethod
    async def settle(session: AsyncSession, attempt: PaymentAttempt, actor_id: uuid.UUID | None) -> None:
        """A verified success lands on the transaction exactly once: the link is
        marked paid, the bill or khata records the money in its own book, and a
        second payment for a link that was already paid is kept (the money
        moved) but flagged for a refund instead of being posted again."""
        if attempt.request_id is not None:
            req = (await session.execute(select(PaymentRequest).where(
                PaymentRequest.id == attempt.request_id).with_for_update())).scalars().first()
            if req is not None and req.status == "paid":
                await PaymentCollectService._flag_twice(session, attempt, req.id)
                return
            if req is not None:
                req.status = "paid"
                req.paid_at = datetime.now(timezone.utc)
                req.version += 1
        owner = actor_id or await PaymentCollectService._owner(session, attempt.business_id)
        method = _INVOICE_METHOD.get(attempt.payment_method, "other")
        reference = attempt.reference or f"Payment link {str(attempt.id)[:8]}"
        if attempt.source_type == "invoice":
            from platform_core.services.invoicing import InvoiceService

            doc = await InvoiceService.get(session, attempt.business_id, attempt.source_id, lock=True)
            outstanding = _d((await InvoiceService._money_view(session, doc))["outstanding"])
            take = min(_d(attempt.amount), outstanding)
            if take > 0:
                await InvoiceService.record_payment(session, attempt.business_id, attempt.source_id, owner, {
                    "amount": str(take), "method": method, "reference": reference,
                    "_via": "payment_attempt", "_payment_attempt_id": attempt.id})
            if take < _d(attempt.amount):
                await PaymentCollectService._flag_twice(session, attempt, attempt.request_id)
        elif attempt.source_type == "khata":
            from platform_core.services.ledger import LedgerService

            await LedgerService.receive(session, attempt.business_id, attempt.source_id, owner,
                                        amount=attempt.amount, method=method, reference=reference,
                                        idempotency_key=f"pay:{attempt.id}")

    @staticmethod
    async def close_intents(session: AsyncSession, attempt: PaymentAttempt) -> None:
        """Once a transaction is paid in full, the customer's "pay on delivery /
        at pickup" choice has nothing left to collect: close it, so nobody
        collects the money a second time."""
        others = (await session.execute(select(PaymentAttempt).where(
            PaymentAttempt.business_id == attempt.business_id, PaymentAttempt.source_type == attempt.source_type,
            PaymentAttempt.source_id == attempt.source_id, PaymentAttempt.id != attempt.id,
            PaymentAttempt.deleted_at.is_(None), PaymentAttempt.status == "pending_offline",
            PaymentAttempt.payment_method.in_(OFFLINE_INTENTS)).with_for_update())).scalars().all()
        for other in others:
            other.status = "cancelled"
            other.failure_reason = "Paid another way"
            other.version += 1

    @staticmethod
    async def _flag_twice(session: AsyncSession, attempt: PaymentAttempt, request_id: uuid.UUID | None) -> None:
        attempt.attention = "paid_twice"
        await OutboxService.publish(
            session, event_type="payment.paid_twice", business_id=attempt.business_id,
            payload={"payment_id": str(attempt.id), "request_id": str(request_id) if request_id else None,
                     "amount": float(attempt.amount)})

    @staticmethod
    async def _owner(session: AsyncSession, business_id: uuid.UUID) -> uuid.UUID:
        from platform_core.models import Business

        business = await session.get(Business, business_id)
        assert business is not None
        return uuid.UUID(str(business.primary_owner_identity_id))

    @staticmethod
    async def paid_status(session: AsyncSession, attempt: PaymentAttempt, total: Decimal | None) -> str | None:
        """The transaction's payment_status after this attempt, from what was
        actually paid against it — never "paid" for an advance (§5)."""
        paid = _d((await session.execute(select(func.coalesce(func.sum(PaymentAttempt.amount), 0)).where(
            PaymentAttempt.business_id == attempt.business_id, PaymentAttempt.source_type == attempt.source_type,
            PaymentAttempt.source_id == attempt.source_id, PaymentAttempt.deleted_at.is_(None),
            PaymentAttempt.status.in_(PAID_STATUSES)))).scalar())
        if paid <= 0:
            return None
        if total is None or paid >= total:
            return "paid"
        return "partially_paid"

    @staticmethod
    async def net_paid(session: AsyncSession, business_id: uuid.UUID, source_type: str,
                       source_id: uuid.UUID) -> Decimal:
        """Verified money kept on a transaction: paid minus refunded."""
        return _d((await session.execute(select(func.coalesce(func.sum(
            PaymentAttempt.amount - func.coalesce(PaymentAttempt.refunded_amount, 0)), 0)).where(
            PaymentAttempt.business_id == business_id, PaymentAttempt.source_type == source_type,
            PaymentAttempt.source_id == source_id, PaymentAttempt.deleted_at.is_(None),
            PaymentAttempt.status.in_(PAID_STATUSES)))).scalar())

    # ------------------------------------------------------------------ money received, counted once
    @staticmethod
    async def received(session: AsyncSession, business_id: uuid.UUID, first: date, until: date) -> dict[str, float]:
        """Verified money received on days ``first`` ≤ day < ``until`` (India time),
        each rupee counted once: links and recorded payments on orders, bookings
        and plans; bill and counter payments; khata payments not already a bill
        payment. The Payments page (today) and Insights (a period) read this."""
        ist = timezone(timedelta(hours=5, minutes=30))
        b = {"b": str(business_id), "start": datetime.combine(first, datetime.min.time(), tzinfo=ist),
             "end": datetime.combine(until, datetime.min.time(), tzinfo=ist), "first": first, "until": until}
        link_money = _d((await session.execute(text(
            "SELECT coalesce(sum(amount), 0) FROM payments_payment_attempts WHERE business_id = CAST(:b AS uuid) "
            "AND deleted_at IS NULL AND status IN ('succeeded', 'partially_refunded', 'refunded') "
            "AND source_type IN ('order', 'booking', 'membership') "
            "AND coalesce(verified_at, updated_at) >= :start AND coalesce(verified_at, updated_at) < :end"),
            b)).scalar())
        bill_money = _d((await session.execute(text(
            "SELECT coalesce(sum(amount), 0) FROM invoicing_payments WHERE business_id = CAST(:b AS uuid) "
            "AND received_on >= :first AND received_on < :until AND verification = 'verified' "
            "AND via IS DISTINCT FROM 'khata'"), b)).scalar())
        khata_money = _d((await session.execute(text(
            "SELECT coalesce(sum(-amount), 0) FROM ledger_entries WHERE business_id = CAST(:b AS uuid) "
            "AND kind = 'payment_received' AND entry_date >= :first AND entry_date < :until "
            "AND (idempotency_key IS NULL OR idempotency_key NOT LIKE 'billpay:%')"), b)).scalar())
        return {"total": float(link_money + bill_money + khata_money), "links_and_recorded": float(link_money),
                "bills_and_counter": float(bill_money), "khata": float(khata_money)}

    # ------------------------------------------------------------------ the owner's overview (§14)
    @staticmethod
    async def overview(session: AsyncSession, business_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """Paid today, waiting for you, failed, what is owed, refunds — verified
        money only, each rupee counted once."""
        paid = await PaymentCollectService.received(session, business_id, today, today + timedelta(days=1))
        b = {"b": str(business_id)}
        waiting = (await session.execute(select(PaymentAttempt).where(
            PaymentAttempt.business_id == business_id, PaymentAttempt.deleted_at.is_(None),
            PaymentAttempt.payment_method == "upi_direct", PaymentAttempt.status == "pending_offline")
            .order_by(PaymentAttempt.created_at))).scalars().all()
        attention = (await session.execute(select(PaymentAttempt).where(
            PaymentAttempt.business_id == business_id, PaymentAttempt.deleted_at.is_(None),
            (PaymentAttempt.attention.is_not(None)) | (
                (PaymentAttempt.status == "failed")
                & (PaymentAttempt.created_at >= datetime.now(timezone.utc) - timedelta(days=14))))
            .order_by(PaymentAttempt.created_at.desc()).limit(30))).scalars().all()
        counter_to_verify = int((await session.execute(text(
            "SELECT count(*) FROM invoicing_payments WHERE business_id = CAST(:b AS uuid) "
            "AND verification = 'to_verify'"), b)).scalar() or 0)
        owed = await PaymentCollectService._owed(session, business_id)
        refunds = (await session.execute(text(
            "SELECT r.id, r.amount, r.status, r.reason, r.created_at, a.source_type, a.source_id "
            "FROM payments_refunds r JOIN payments_payment_attempts a ON a.id = r.payment_attempt_id "
            "WHERE r.business_id = CAST(:b AS uuid) AND r.created_at >= now() - interval '30 days' "
            "ORDER BY r.created_at DESC LIMIT 20"), b)).all()
        labels: dict[tuple[str, str], str] = {}

        async def label(a: PaymentAttempt) -> str:
            key = (a.source_type, str(a.source_id))
            if key not in labels:
                try:
                    labels[key] = (await PaymentCollectService.source(session, business_id, a.source_type,
                                                                      a.source_id)).label
                except ResourceNotFound:
                    labels[key] = a.source_type
            return labels[key]

        # A failure that a later payment on the same link already fixed needs nothing.
        fixed = {r[0] for r in (await session.execute(text(
            "SELECT id FROM payments_requests WHERE business_id = CAST(:b AS uuid) AND status = 'paid'"),
            b)).all()}
        needs = [a for a in attention if a.attention or a.request_id not in fixed]
        return {
            "paid_today": paid,
            "to_confirm": [PaymentCollectService._attempt_row(a) | {"for": await label(a)} for a in waiting],
            "counter_upi_to_verify": counter_to_verify,
            "needs_attention": [PaymentCollectService._attempt_row(a) | {"for": await label(a)} for a in needs],
            "owed": owed,
            "refunds": [{"id": str(r[0]), "amount": float(r[1]), "status": r[2], "reason": r[3],
                         "created_at": r[4].isoformat(), "source_type": r[5], "source_id": str(r[6])}
                        for r in refunds],
        }

    @staticmethod
    async def _owed(session: AsyncSession, business_id: uuid.UUID) -> dict[str, Any]:
        """Who still owes what: part-paid or unpaid finished orders, bookings
        with a balance, open bills (not on khata) and khata balances."""
        b = {"b": str(business_id)}
        orders = (await session.execute(text(
            "SELECT o.id, o.order_number, o.total_amount, coalesce(p.paid, 0) AS paid, o.status "
            "FROM orders_orders o LEFT JOIN (SELECT source_id, sum(amount) AS paid FROM payments_payment_attempts "
            "  WHERE business_id = CAST(:b AS uuid) AND source_type = 'order' AND deleted_at IS NULL "
            "  AND status IN ('succeeded', 'partially_refunded', 'refunded') GROUP BY source_id) p "
            "  ON p.source_id = o.id "
            "WHERE o.business_id = CAST(:b AS uuid) AND o.deleted_at IS NULL "
            "AND o.status NOT IN ('cancelled', 'rejected') AND o.total_amount > coalesce(p.paid, 0) "
            "AND (o.status = 'completed' OR coalesce(p.paid, 0) > 0) ORDER BY o.created_at DESC LIMIT 20"),
            b)).all()
        bookings = (await session.execute(text(
            "SELECT k.id, k.booking_number, k.title, k.total_amount, coalesce(p.paid, 0) AS paid "
            "FROM bookings_bookings k LEFT JOIN (SELECT source_id, sum(amount) AS paid "
            "  FROM payments_payment_attempts WHERE business_id = CAST(:b AS uuid) AND source_type = 'booking' "
            "  AND deleted_at IS NULL AND status IN ('succeeded', 'partially_refunded', 'refunded') "
            "  GROUP BY source_id) p ON p.source_id = k.id "
            "WHERE k.business_id = CAST(:b AS uuid) AND k.status NOT IN ('cancelled', 'rejected') "
            "AND k.total_amount IS NOT NULL AND k.total_amount > coalesce(p.paid, 0) AND coalesce(p.paid, 0) > 0 "
            "ORDER BY k.starts_at LIMIT 20"), b)).all()
        bills = (await session.execute(text(
            "SELECT id, number, amount_due, amount_paid FROM invoicing_documents "
            "WHERE business_id = CAST(:b AS uuid) AND status = 'issued' AND doc_kind <> 'credit_note' "
            "AND NOT on_account AND order_id IS NULL AND amount_due > amount_paid "
            "ORDER BY issue_date LIMIT 20"), b)).all()
        khata = (await session.execute(text(
            "SELECT id, display_name, balance FROM ledger_accounts WHERE business_id = CAST(:b AS uuid) "
            "AND party_type = 'customer' AND balance > 0 ORDER BY balance DESC LIMIT 20"), b)).all()
        rows = (
            [{"source_type": "order", "source_id": str(r[0]), "label": f"Order {r[1]}",
              "balance": float(_d(r[2]) - _d(r[3])), "paid": float(r[3])} for r in orders]
            + [{"source_type": "booking", "source_id": str(r[0]), "label": f"Booking {r[1]} · {r[2]}",
                "balance": float(_d(r[3]) - _d(r[4])), "paid": float(r[4])} for r in bookings]
            + [{"source_type": "invoice", "source_id": str(r[0]), "label": f"Bill {r[1] or ''}".strip(),
                "balance": float(_d(r[2]) - _d(r[3])), "paid": float(r[3])} for r in bills]
            + [{"source_type": "khata", "source_id": str(r[0]), "label": f"Khata · {r[1]}",
                "balance": float(r[2]), "paid": None} for r in khata]
        )
        return {"total": float(sum((_d(r["balance"]) for r in rows), ZERO)), "rows": rows}


def share_text(business_name: str, what: str, amount: Decimal, url: str) -> str:
    return f"{business_name}: please pay {_inr(amount)} for {what} here — {url}"


def wa_share(phone: str | None, message: str) -> str | None:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 11:
        return None
    return f"https://wa.me/{digits}?text={quote(message)}"
