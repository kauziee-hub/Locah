"""Website enquiries become leads (Capability Universe §6.3 enquiry flows,
§19.2 "every enquiry becomes a lead"; Business OS Guide §4).

A visitor asks about a project, a vehicle, a piece of work or anything else —
or asks for a site visit or a test drive with a preferred date. It lands in
Enquiries exactly like one typed in by the team, with where it came from.
The details are used to reply to this enquiry only; no marketing opt-in is
taken here.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.catalog.offering_kinds import KINDS
from platform_core.exceptions import ValidationError
from platform_core.models import BusinessModuleState, MembershipPlan, Offering

PURPOSES = {
    "enquiry": "Enquiry",
    "site_visit": "Site visit request",
    "test_drive": "Test drive request",
    "callback": "Call-back request",
    # "Get a quote" on the website / Marketplace (RFQ intake): the team quotes from the lead.
    "quote_request": "Quote request",
    # "Ask to join" on a plan: the team enrols the member (online join with
    # payment is the Memberships packet).
    "membership": "Membership enquiry",
}


def _bad(field: str, message: str) -> ValidationError:
    return ValidationError(message, details={"errors": [{"field": field, "message": message}]})


class PublicEnquiryService:
    @staticmethod
    async def accepting(session: AsyncSession, business_id: uuid.UUID) -> bool:
        """Leads' public intake: open while Leads is ready — switched on and
        entitled (a stale activation without an Entitlement takes nothing,
        Doc 08 §20.2) — the same answer that puts the enquiry form on the site."""
        from platform_core.services.module_readiness import module_ready

        return bool(await module_ready(session, business_id, "leads"))

    @staticmethod
    async def submit(session: AsyncSession, *, slug: str, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        from platform_core.services.checkout import CheckoutService
        from platform_core.services.lead import LeadService

        business = await CheckoutService._resolve_business(session, slug)
        if payload.get("website"):  # honeypot: people never fill a hidden field
            return {"received": True}
        if not await PublicEnquiryService.accepting(session, business.id):
            raise ValidationError("This business is not taking enquiries online yet",
                                  details={"code": "enquiries_off"})
        name = str(payload.get("name") or "").strip()
        if not 1 <= len(name) <= 80:
            raise _bad("name", "Tell us your name")
        phone = str(payload.get("phone") or "").strip() or None
        email = str(payload.get("email") or "").strip() or None
        if not phone and not email:
            raise _bad("phone", "Leave a phone number or email so they can reply")
        message = str(payload.get("message") or "").strip()[:1000] or None
        purpose = str(payload.get("purpose") or "enquiry")
        if purpose not in PURPOSES:
            raise _bad("purpose", "Unknown kind of request")
        preferred = payload.get("preferred_date")
        preferred_iso = None
        if preferred:
            try:
                day = date.fromisoformat(str(preferred))
            except ValueError:
                raise _bad("preferred_date", "Pick a date") from None
            if not date.today() <= day <= date.today() + timedelta(days=180):
                raise _bad("preferred_date", "Pick a date in the next six months")
            preferred_iso = day.isoformat()

        origin: dict[str, Any] = {"purpose": purpose, "purpose_label": PURPOSES[purpose], "channel": "website"}
        offering_id = None
        if payload.get("offering_id"):
            offering = (await session.execute(
                select(Offering).where(Offering.id == uuid.UUID(str(payload["offering_id"])),
                                       Offering.business_id == business.id, Offering.deleted_at.is_(None),
                                       Offering.status == "active", Offering.visibility == "public")
            )).scalars().first()
            if offering is None:
                raise _bad("offering_id", "That item is no longer listed")
            offering_id = offering.id
            k = KINDS.get(offering.offering_type)
            origin.update({"offering_id": str(offering.id), "offering_title": offering.title,
                           "offering_kind": k.label if k else offering.offering_type})
        if payload.get("plan_id"):
            plan = (await session.execute(
                select(MembershipPlan).where(MembershipPlan.id == uuid.UUID(str(payload["plan_id"])),
                                             MembershipPlan.business_id == business.id,
                                             MembershipPlan.deleted_at.is_(None), MembershipPlan.status == "active",
                                             MembershipPlan.visibility == "public")
            )).scalars().first()
            if plan is None:
                raise _bad("plan_id", "That plan is no longer offered")
            origin.update({"plan_id": str(plan.id), "plan_title": plan.name})
        if preferred_iso:
            origin["preferred_date"] = preferred_iso

        lead = await LeadService.create_lead(
            session, business_id=business.id, actor_id=business.primary_owner_identity_id,
            correlation_id=correlation_id, actor_context="website_enquiry",
            payload={"display_name": name, "phone": phone, "email": email, "message": message,
                     "source": "website_enquiry", "origin_context": origin,
                     "offering_id": str(offering_id) if offering_id else None},
        )
        # A "Get a quote" request is also a draft quote when Quotes is on.
        # The lead stays the follow-up. The draft is what the team prices.
        if purpose == "quote_request":
            quotes_on = (await session.execute(
                select(BusinessModuleState.activation_state).where(
                    BusinessModuleState.business_id == business.id,
                    BusinessModuleState.module_id == "quotes",
                )
            )).scalar()
            if quotes_on in ("enabled", "ready", "active"):
                from platform_core.services.quote import QuoteService

                offering_title = origin.get("offering_title")
                await QuoteService.intake_rfq(
                    session,
                    business_id=business.id,
                    actor_id=business.primary_owner_identity_id,
                    correlation_id=correlation_id,
                    channel="website",
                    idempotency_key=str(lead.id),
                    customer_name=name,
                    phone=phone,
                    email=email,
                    brief=message,
                    lines=None,
                    offering_title=str(offering_title) if offering_title else None,
                    source_ref=str(lead.id),
                )
        return {"received": True, "reference": str(lead.id)[:8].upper()}
