import uuid
from datetime import date
from typing import Any, Literal
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import get_request_context
from platform_core.context import RequestContext
from platform_core.services.consumer_activity import ConsumerActivityService
from platform_core.services.identity import IdentityService
from platform_core.services.invoicing import share_token
from platform_core.services.reviews import review_token

router = APIRouter(prefix="/v1/me", tags=["identity"])


class ProfileResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    avatar_url: str | None


class ContextResponse(BaseModel):
    identity_id: str
    active_context: str
    business_id: str | None
    location_id: str | None
    is_super_admin: bool
    permissions: list[str]
    entitled_modules: list[str]
    module_states: dict[str, str]
    # Per catalogue module: active | setup_required | not_entitled | deactivated
    # | not_enabled | unavailable — the Workspace navigation's projection input
    # (Doc 05 NAV-007/NAV-008), from the same readiness customer surfaces use.
    navigation_modules: dict[str, str] = Field(default_factory=dict)
    # This Business's own words for its destinations (Doc 07 §3.3): offerings,
    # bookings, customers. Labels only; routes and permissions never change.
    terms: dict[str, str] = Field(default_factory=dict)
    default_business_id: str | None = None
    last_business_id: str | None = None
    primary_business_id: str | None = None
    # OM-21 (MD §22 "Solo professionals: simplified navigation (no team menus),
    # one calendar"): the business's organisation shape is solo and one person runs it.
    solo: bool = False
    # P1-10E6: this person's Workspace language ('en' | 'ta' | 'hi').
    workspace_language: str = "en"


@router.get("")
async def get_me_v1(
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    identity = await IdentityService.get_by_id(session, ctx.identity_id)
    await session.commit()
    return {
        "data": ProfileResponse(
            id=str(ctx.identity_id),
            email=ctx.email,
            display_name=identity.display_name if identity else ctx.display_name,
            avatar_url=identity.avatar_url if identity else None,
        ).model_dump(),
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.get("/context")
async def get_context(
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    prefs = await IdentityService.get_consumer_preferences(session, ctx.identity_id)
    solo = False
    navigation_modules: dict[str, str] = {}
    terms: dict[str, str] = {}
    if ctx.business_id is not None:
        from platform_core.services.business import BusinessService
        from platform_core.services.business_classification import run_solo
        from platform_core.services.workspace_projection import navigation_modules as project, terms_for

        solo = await run_solo(session, ctx.business_id)
        navigation_modules = await project(session, ctx.business_id)
        business = await BusinessService.get_by_id(session, ctx.business_id)
        if business is not None:
            terms = await terms_for(session, business)
    return {
        "data": ContextResponse(
            identity_id=str(ctx.identity_id),
            active_context=ctx.active_context.value,
            business_id=str(ctx.business_id) if ctx.business_id else None,
            location_id=str(ctx.location_id) if ctx.location_id else None,
            is_super_admin=ctx.is_super_admin,
            permissions=sorted(ctx.effective_permissions),
            entitled_modules=sorted(ctx.effective_entitlements.modules),
            module_states={k: v.activation_state for k, v in ctx.module_states.items()},
            navigation_modules=navigation_modules,
            terms=terms,
            default_business_id=prefs.get("default_business_id"),
            last_business_id=prefs.get("last_business_id"),
            primary_business_id=prefs.get("primary_business_id"),
            solo=solo,
            workspace_language=prefs.get("workspace_language") if prefs.get("workspace_language") in ("en", "ta", "hi")
            else "en",
        ).model_dump(),
        "meta": {"correlation_id": ctx.correlation_id},
    }


@router.get("/activity")
async def get_my_activity(
    resource_type: str | None = Query(default=None),
    business_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """My Activity — the caller's own consumer-side activity (Doc 09 ACC-011).

    Identity-scoped, not Business-scoped: this is the consumer surface, and it
    must stay separate from the Business Workspace (Doc 11 §17.7 exit: "My
    Activity remains separate from Workspace"). No Business permission is
    consulted and none is required — the rows belong to the caller.

    Coverage is bookings and review invitations for linked customers. Orders and Payments do not write to
    `consumer_activity_projections` yet, and guest activity is not linked to an
    account pending FL-DEC-024, so this feed is deliberately partial rather
    than padded with data it cannot truthfully claim.
    """
    # Verified-email guest history joins this identity first (Doc 12: verified
    # identifiers only); idempotent, so every visit is safe.
    from platform_core.services.customer_account import CustomerAccountService

    if await CustomerAccountService.link_verified(session, ctx.identity_id):
        await session.commit()
    activities = await ConsumerActivityService.list_for_identity(
        session,
        identity_id=ctx.identity_id,
        resource_type=resource_type,
        business_id=business_id,
        limit=limit,
    )
    # The projection is identity-scoped. Derive the one-use action link only
    # for an invitation whose newest activity is still an open request; never
    # expose review credentials on a business-scoped or public list.
    seen_reviews: set[str] = set()
    for item in activities:
        summary = item.get("summary") or {}
        slug = summary.get("business_slug")
        if isinstance(slug, str) and item["resource_type"] != "review_invitation":
            item["account_url"] = f"/{slug}/account"
            finished = summary.get("status") in ("completed", "cancelled", "rejected")
            if item["resource_type"] == "order" and summary.get("tracking_token") and not finished:
                item["action_url"] = f"/{slug}/track/{item['resource_id']}?token={summary['tracking_token']}"
            elif item["resource_type"] == "bill":
                item["action_url"] = f"/{slug}/bill/{share_token(UUID(item['business_id']), UUID(item['resource_id']))}"
            summary.pop("tracking_token", None)
        if item["resource_type"] != "review_invitation":
            continue
        key = item["resource_id"]
        if key in seen_reviews:
            continue
        seen_reviews.add(key)
        if item["activity_type"] != "review.requested":
            continue
        summary = item.get("summary") or {}
        slug = summary.get("business_slug")
        expires = summary.get("expires_at")
        if not isinstance(slug, str) or not isinstance(expires, str):
            continue
        try:
            if datetime.fromisoformat(expires) <= datetime.now(timezone.utc):
                continue
            item["action_url"] = f"/{slug}/review/{review_token(UUID(item['business_id']), UUID(key))}"
        except (ValueError, TypeError):
            continue
    return {
        "data": activities,
        "meta": {
            "correlation_id": ctx.correlation_id,
            "count": len(activities),
            # Named so the consumer UI can state its own limits truthfully
            # instead of implying an empty feed means no activity happened.
            "covered_resource_types": ["order", "booking", "bill", "quote", "membership", "review_invitation"],
        },
    }



# ---------------------------------------------------------------- one business's "My account" (Founder §12)
async def _public_business(session: AsyncSession, slug: str) -> Any:
    from platform_core.exceptions import ResourceNotFound
    from platform_core.services.business import BusinessService

    business = await BusinessService.get_by_slug(session, slug)
    if business is None or business.deleted_at is not None or business.visibility == "private":
        raise ResourceNotFound("Business")
    return business


@router.get("/businesses/{slug}/account")
async def my_account_with_business(
    slug: str,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Everything this signed-in customer has with one business — orders,
    bookings, bills, khata, quotes, memberships — for "My account" on that
    business's website. Identity-scoped: only contacts linked to the caller."""
    from platform_core.services.customer_account import CustomerAccountService

    if await CustomerAccountService.link_verified(session, ctx.identity_id):
        await session.commit()
    business = await _public_business(session, slug)
    data = await CustomerAccountService.account(session, business, ctx.identity_id)
    await session.commit()
    return {"data": data, "meta": {"correlation_id": ctx.correlation_id}}


@router.get("/businesses/{slug}/orders/{order_id}/reorder")
async def reorder_lines(
    slug: str,
    order_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Order again (§12.3 "Repeat last order" on the website): the lines of one
    of the caller's orders at today's price, and which can no longer be bought."""
    from platform_core.services.customer_account import CustomerAccountService

    business = await _public_business(session, slug)
    data = await CustomerAccountService.reorder(session, business, ctx.identity_id, order_id)
    return {"data": data, "meta": {"correlation_id": ctx.correlation_id}}


# ---------------------------------------------------------------- my memberships and subscriptions (P2-02)
class MyDeliveryDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_date: date
    kind: Literal["skip", "quantity", "restore"]
    quantity: int | None = Field(default=None, ge=1, le=100)


async def _my_membership(session: AsyncSession, slug: str, identity_id: UUID, enrolment_id: UUID) -> Any:
    """Only a relationship where the caller is the member or the payer."""
    from platform_core.exceptions import ResourceNotFound
    from platform_core.memberships.service import MembershipCore

    business, mine = await _my_contacts(session, slug, identity_id)
    enrolment = await MembershipCore.get(session, business.id, enrolment_id, lock=True)
    if enrolment.customer_contact_id not in mine and enrolment.payer_contact_id not in mine:
        raise ResourceNotFound("Membership")
    return business, enrolment


async def _pay_link(session: AsyncSession, business: Any, enrolment: Any, purpose: str, note: str) -> str:
    from decimal import Decimal

    from platform_core.exceptions import ConflictError
    from platform_core.services.payment_collect import PaymentCollectService

    due = await PaymentCollectService.money(session, business.id, "membership", enrolment.id)
    balance = Decimal(str(due["balance"] or 0))
    if balance <= 0:
        raise ConflictError("Nothing is due right now")
    _req, token = await PaymentCollectService.create_request(
        session, business.id, business.primary_owner_identity_id, source_type="membership",
        source_id=enrolment.id, amount=balance, purpose=purpose, note=note, correlation_id=str(uuid.uuid4()))
    return f"/{business.slug}/pay/{token}"


@router.post("/businesses/{slug}/memberships/{enrolment_id}/renew")
async def renew_my_membership(
    slug: str, enrolment_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Renew from My account: the next period after the current one (no day
    lost), and a payment page for it. Paying is what renews it."""
    from platform_core.memberships.service import MembershipCore

    business, enrolment = await _my_membership(session, slug, ctx.identity_id, enrolment_id)
    plan = await MembershipCore.plan_of(session, enrolment)
    await MembershipCore.renew(session, enrolment, actor_id=None)
    path = await _pay_link(session, business, enrolment, "full", f"Renewal — {plan.name}")
    await session.commit()
    return {"data": {"pay_path": path}, "meta": {"correlation_id": ctx.correlation_id}}


@router.post("/businesses/{slug}/memberships/{enrolment_id}/pay")
async def pay_my_membership(
    slug: str, enrolment_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Pay what is due now (a fee instalment, dues, an unpaid period)."""
    from platform_core.memberships.service import MembershipCore

    business, enrolment = await _my_membership(session, slug, ctx.identity_id, enrolment_id)
    plan = await MembershipCore.plan_of(session, enrolment)
    path = await _pay_link(session, business, enrolment, "balance", plan.name)
    await session.commit()
    return {"data": {"pay_path": path}, "meta": {"correlation_id": ctx.correlation_id}}


@router.post("/businesses/{slug}/memberships/{enrolment_id}/delivery-day")
async def change_my_delivery(
    slug: str, enrolment_id: UUID, body: MyDeliveryDay,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Skip tomorrow, a different quantity for one day, or back to usual —
    until the cutoff; after it, the business's policy is shown (§11)."""
    from platform_core.memberships.subscriptions import SubscriptionService

    business, enrolment = await _my_membership(session, slug, ctx.identity_id, enrolment_id)
    await SubscriptionService.change_day(session, enrolment, on_date=body.on_date, kind=body.kind,
                                         quantity=body.quantity, actor_id=None, channel="website")
    await session.commit()
    return {"data": {"ok": True}, "meta": {"correlation_id": ctx.correlation_id}}


# ---------------------------------------------------------------- my data with one business (DPDP access / erasure, MD §25.1)
class ErasureRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


async def _my_contacts(session: AsyncSession, slug: str, identity_id: UUID) -> tuple[Any, list[UUID]]:
    from platform_core.exceptions import ResourceNotFound
    from platform_core.services.customer_account import CustomerAccountService, bind_customer_context

    business = await _public_business(session, slug)
    await bind_customer_context(session, business.id, identity_id)
    mine = await CustomerAccountService.contacts(session, business.id)
    if not mine:
        raise ResourceNotFound("Your records with this business")
    return business, mine


@router.get("/businesses/{slug}/my-data")
async def my_data_with_business(
    slug: str,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Download everything this business keeps about me (DPDP right of access)."""
    from platform_core.customers.privacy import PrivacyRequests, export

    business, mine = await _my_contacts(session, slug, ctx.identity_id)
    data = await export(session, business.id, mine, business_name=business.display_name)
    for contact_id in mine:
        await PrivacyRequests.record(session, business.id, contact_id, kind="access", source="customer",
                                     identity_id=ctx.identity_id, note="Downloaded by the customer", status="done")
    await session.commit()
    return {"data": data, "meta": {"correlation_id": ctx.correlation_id}}


@router.post("/businesses/{slug}/erasure-request")
async def ask_to_erase_my_data(
    slug: str,
    body: ErasureRequestBody,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Ask this business to delete my details (DPDP right of erasure). The business
    acts on it — bills the law makes them keep stay — and the request shows here."""
    from platform_core.customers.privacy import PrivacyRequests
    from platform_core.permissions import CUSTOMERS_ERASE
    from platform_core.services.notification import NotificationService

    business, mine = await _my_contacts(session, slug, ctx.identity_id)
    already = True
    for contact_id in mine:
        row = await PrivacyRequests.record(session, business.id, contact_id, kind="erasure", source="customer",
                                           identity_id=ctx.identity_id, note=body.note)
        if not row["already"]:
            already = False
            await NotificationService.fan_out(
                session, business_id=business.id, notification_type="customer.erasure_requested",
                title="A customer asked you to delete their details",
                body="Open the customer to erase their details, or decline with a reason (for example money still owed).",
                required_permission=CUSTOMERS_ERASE, severity="warning", resource_type="customer",
                resource_id=contact_id)
    await session.commit()
    return {"data": {"requested": True, "already": already}, "meta": {"correlation_id": ctx.correlation_id}}


class WorkspaceLanguageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(pattern="^(en|ta|hi)$")


@router.put("/workspace-language")
async def set_workspace_language(
    body: WorkspaceLanguageBody,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """The language my Workspace speaks — English, Tamil or Hindi (P1-10E6)."""
    language = await IdentityService.set_workspace_language(session, identity_id=ctx.identity_id,
                                                            language=body.language)
    await session.commit()
    return {"data": {"workspace_language": language}, "meta": {"correlation_id": ctx.correlation_id}}
