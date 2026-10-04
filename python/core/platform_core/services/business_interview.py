"""Durable, owner-scoped interview application service.

The versioned Blueprint is an onboarding configuration document in the existing
tenant's metadata, not a second store of operational records. Confirmed profile
facts use the owning services when the owner builds. No schema migration needed.
"""

from __future__ import annotations

import re

from dataclasses import replace
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.entitlements.module_registry import ModuleRegistry
from platform_core.entitlements.models import ResolvedEntitlement
from platform_core.entitlements.resolver import BusinessEntitlementResolver
from platform_core.exceptions import ConflictError, ResourceNotFound, ValidationError
from platform_core.gates import assert_business_mutable
from platform_core.interview.capabilities import (
    available_modules,
    classification_seed,
    operational_modules,
    resolve_recommendations,
    surface_new_unsupported_requests,
)
from platform_core.interview.design_strategy import (
    DESIGN_STRATEGY_VERSION,
    GENERATION_PLAN_VERSION,
    derive_strategy,
    generate_website_plan,
    select_contextual_template,
)
from platform_core.interview.models import (
    BusinessBlueprint,
    CategorySeed,
    DraftCommand,
    DraftText,
    Fact,
    InterviewCommand,
    MediaGenerationRequest,
    OfferingDraft,
    TargetState,
    now,
)
from platform_core.interview import voice
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator, QUESTIONS
from platform_core.interview.understanding import understanding
from platform_core.interview.website import build_preview, with_draft
from platform_core.logging import get_logger
from platform_core.models import Business, WebsiteGenerationJob, WebsiteVersion
from platform_core.resolvers.website_resolver import WebsiteResolver
from platform_core.services.async_jobs import AsyncJobService
from platform_core.services.audit import AuditService
from platform_core.services.entitlement import ModuleService
from platform_core.services.media import MediaService
from platform_core.services.outbox import OutboxService
from platform_core.services.website import WebsiteService
from platform_core.services.website_composition import WebsiteCompositionService
from platform_core.website.generation_plan import GenerationPlan, build_plan
from platform_core.website.image_generation import image_generation_available
from platform_core.website.template_registry import TEMPLATES_BY_ID


async def _sync_catalogue_into_draft(session: AsyncSession, business_id: UUID, bp: BusinessBlueprint) -> None:
    """Prices the owner typed appear on the draft site at once — nowhere else changes."""
    from platform_core.interview.site_composer import money
    from platform_core.models import WebsitePage, WebsiteSection

    draft = (
        await session.execute(
            select(WebsiteVersion).where(
                WebsiteVersion.business_id == business_id,
                WebsiteVersion.version_type == "draft",
                WebsiteVersion.superseded_at.is_(None),
            ).with_for_update()
        )
    ).scalars().first()
    if draft is None:
        return
    rows = (
        await session.execute(
            select(WebsiteSection).join(WebsitePage).where(
                WebsitePage.website_version_id == draft.id,
                WebsiteSection.section_type_id.in_(("product_showcase", "category_showcase")),
            )
        )
    ).scalars().all()
    groups = {g.name.casefold(): g for g in bp.taxonomy.groups}
    for section in rows:
        content = dict(section.content or {})
        for key in ("categories", "items") if section.section_type_id == "product_showcase" else ("items",):
            updated = []
            for row in content.get(key) or []:
                row = dict(row)
                if key == "categories" or section.section_type_id == "category_showcase":
                    group = groups.get(str(row.get("name", "")).casefold())
                    if group and group.price:
                        row["meta"] = f"From {money(group.price)} {group.unit}".strip()[:60]
                else:
                    group = groups.get(str(row.get("category", "")).casefold())
                    item = next((i for i in (group.items if group else [])
                                 if i.name.casefold() == str(row.get("name", "")).casefold()), None)
                    if item and item.price:
                        row["price"], row["unit"] = money(item.price), item.unit
                updated.append(row)
            content[key] = updated
        section.content = content
    draft.updated_at = now()


def _setup_rows(bp: BusinessBlueprint) -> list[tuple[str, str, str]]:
    """(title, price, unit) per draft catalogue item, from the owner's structure.

    An item named in more than one group ("Curry cut" of chicken and of
    mutton) carries its group, so the two do not collapse into one.
    """
    groups = bp.taxonomy.groups
    if not groups:
        return [(d.name.strip(), "", "") for d in bp.website_draft.offerings]
    counts: dict[str, int] = {}
    for group in groups:
        for item in group.items:
            counts[item.name.casefold()] = counts.get(item.name.casefold(), 0) + 1
    rows: list[tuple[str, str, str]] = []
    for group in groups:
        if not group.items:
            rows.append((group.name, group.price, group.unit))
            continue
        for item in group.items:
            title = item.name
            if counts[item.name.casefold()] > 1 and group.name.casefold() not in item.name.casefold():
                title = f"{group.name} {item.name[0].lower() + item.name[1:]}"
            rows.append((title[:120], item.price or group.price, item.unit or group.unit))
    return rows[:12]


def _trade(bp: BusinessBlueprint, archetype: str) -> str:
    """What the business trades in, for an image prompt — group names, not the transcript."""
    names = [g.name.lower() for g in bp.taxonomy.groups][:4]
    listed = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)
    return {
        "product_commerce": f"a local shop selling {listed}" if listed else "a local shop",
        "menu_commerce": f"a home kitchen making {listed}" if listed else "a home kitchen",
        "membership_fitness": "a strength and fitness gym",
        "real_estate_projects": "a residential real-estate developer",
    }.get(archetype, f"a local business offering {listed}" if listed else "a local business")


def public_contact(bp: BusinessBlueprint) -> dict[str, Any]:
    """The contact details the owner gave, shaped for their public site.

    Only what they actually said: a phone number they stated, and WhatsApp only
    if they mentioned WhatsApp. A number is normalised to digits so a button can
    dial it; anything that does not look like a phone number is left out rather
    than guessed at.
    """
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    contact: dict[str, Any] = {}
    phone = facts.get("phone")
    if phone:
        digits = re.sub(r"\D", "", phone.value)
        if 10 <= len(digits) <= 13:
            if len(digits) == 10:
                digits = "91" + digits  # an Indian mobile written without its country code
            contact["phone"] = "+" + digits
            said = " ".join(
                [fact.value for fact in facts.values()]
                + [m.text for m in bp.messages if m.role == "user"]
            )
            # Said in any script the owner used: "WhatsApp", "வாட்ஸ்அப்", "व्हाट्सएप".
            if re.search(r"whats\s?app|வாட்ஸ்\s?(?:அப்|ஆப்)|व्हाट्स\s?(?:एप|ऐप)", said, re.I):
                contact["whatsapp"] = "+" + digits
    email = facts.get("email")
    if email and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.value.strip()):
        contact["email"] = email.value.strip()
    return contact


async def _hours_to_location(
    session: AsyncSession, business_id: UUID, bp: BusinessBlueprint, *, actor_id: UUID, correlation_id: str,
) -> None:
    """The week the owner described ("open 9 to 10, weekends till 11") becomes
    the primary location's opening hours — the ones Home, bookings and the AI
    receptionist read. Only when none are saved: hours set in the Workspace
    are the owner's and are never overwritten by the conversation."""
    from platform_core.interview import hours
    from platform_core.services.location import LocationService

    said = ({**bp.known_facts, **bp.unconfirmed_facts}).get("opening_hours")
    week = hours.parse(said.value, asked=True) if said else None
    if not week:
        return
    locations = await LocationService.list_for_business(session, business_id, status="active")
    primary = locations[0] if locations else None
    if primary is None or primary.hours:
        return
    try:
        await LocationService.update_location(
            session, business_id=business_id, location_id=primary.id, actor_id=actor_id,
            correlation_id=correlation_id, payload={"hours": hours.for_location(week)},
        )
    except ValidationError:
        return  # never hold the website back over hours; the owner can set them in Locations


def _carry_media(fresh: BusinessBlueprint, proposed: BusinessBlueprint) -> None:
    """Keep media the worker finished while a turn was being understood."""
    known = {m.asset_id for m in proposed.media_assets}
    for media in fresh.media_assets:
        if media.asset_id not in known:
            proposed.media_assets.append(media)
    for request in fresh.media_generation_requests:
        # A request is its role AND its slot: every draft visual has role
        # "visual", so matching on role alone kept only the last one — and a
        # rebuild after the owner's next message redrew all the others.
        def same(r: MediaGenerationRequest, request: MediaGenerationRequest = request) -> bool:
            return bool(r.role == request.role and r.key == request.key)

        mine = next((r for r in proposed.media_generation_requests if same(r)), None)
        newer = (
            mine is None
            or request.status == "ready"
            # the worker moved on from what this turn started with...
            or (mine.status == "queued" and request.status in {"failed", "ready"})
        )
        # ...but a fresh ask this turn ("try again") beats an old failure.
        if newer and not (mine is not None and mine.status == "requested"):
            proposed.media_generation_requests = [
                r for r in proposed.media_generation_requests if not same(r)
            ] + [request]
    if fresh.logo_state == "generated":
        proposed.logo_state = "generated"


def _apply_draft(bp: BusinessBlueprint, command: DraftCommand) -> None:
    """The owner editing, keeping or removing website wording. The owner wins."""
    wd = bp.website_draft
    text = " ".join(command.text.split())
    if command.field == "offering":
        name = " ".join(command.offering_name.split())
        offering = next((o for o in wd.offerings if o.name.casefold() == name.casefold()), None)
        if offering is None:
            if command.op != "edit" or not name:
                raise ValidationError("That item is not in the draft")
            offering = OfferingDraft(name=name[:80])
            wd.offerings.append(offering)
        if command.op == "edit":
            offering.description = DraftText(text=text[:800], provenance="owner_edited") if text else None
        elif command.op == "approve" and offering.description:
            offering.description = offering.description.model_copy(update={"provenance": "owner_approved"})
        elif command.op == "dismiss":
            wd.offerings = [o for o in wd.offerings if o is not offering]
        return
    current = getattr(wd, command.field)
    if command.op == "edit":
        if not text:
            raise ValidationError("Write something, or remove it instead")
        limits = {"hero_headline": 90, "hero_subheadline": 220, "about": 800, "cta_label": 32}
        setattr(wd, command.field, DraftText(text=text[: limits[command.field]], provenance="owner_edited"))
        wd.dismissed = [f for f in wd.dismissed if f != command.field]
    elif command.op == "approve":
        if current is None:
            raise ValidationError("There is nothing there to keep yet")
        setattr(wd, command.field, current.model_copy(update={"provenance": "owner_approved"}))
    elif command.op == "dismiss":
        setattr(wd, command.field, None)
        if command.field not in wd.dismissed:
            wd.dismissed.append(command.field)


def _category_seed(business: Business) -> CategorySeed | None:
    """The category the owner picked when creating the business, if any."""
    from platform_core.catalog.taxonomy import resolve

    picked = (business.metadata_ or {}).get("classification") or {}
    found = resolve(picked.get("category_key"), picked.get("subcategory_key"))
    if not found:
        return None
    category, sub = found
    return CategorySeed(category_key=category.key, subcategory_key=sub.key if sub.key != category.key else "",
                        label=sub.label, source="owner_picked", group=category.label)


async def _sync_business(session: AsyncSession, business: Business, bp: BusinessBlueprint) -> None:
    """What the conversation settled about the Business itself: its name and kind.

    The name the owner said becomes the Business's name (and, while it was
    pending, its address). The kind — picked, inferred or corrected — is kept
    as the Business's classification seed; it is never a module grant.
    """
    from platform_core.services.business import BusinessService

    said = bp.identity.get("display_name")
    if said and not bp.name_pending and said.value != business.display_name:
        await BusinessService.adopt_name(session, business, said.value)
    meta = dict(business.metadata_ or {})
    if bp.category:
        wanted = {"category_key": bp.category.category_key, "subcategory_key": bp.category.subcategory_key,
                  "source": bp.category.source}
        if meta.get("classification") != wanted:
            meta["classification"] = wanted
            business.metadata_ = meta
        # The P1 columns (Capability Universe §4.4) and the default operating
        # traits follow the settled kind; an owner's own trait choices survive.
        from platform_core.catalog.taxonomy import resolve
        from platform_core.services.business_classification import BusinessClassificationService

        sub = bp.category.subcategory_key or None
        if resolve(bp.category.category_key, sub) and (
            business.category_key != bp.category.category_key or business.subcategory_key != sub
        ):
            await BusinessClassificationService.set_classification(
                session, business, category_key=bp.category.category_key,
                subcategory_key=sub, actor_id=None, audit=False,
            )
            meta = dict(business.metadata_ or {})
            meta["classification"] = wanted
            business.metadata_ = meta


async def _queue_logo(
    session: AsyncSession, business: Business, bp: BusinessBlueprint, *, actor_id: UUID
) -> None:
    """Draw a requested logo now, in the background, while the owner carries on."""
    request = next(
        (r for r in bp.media_generation_requests if r.role == "logo" and r.status == "requested"),
        None,
    )
    if request is None or not image_generation_available():
        return
    await AsyncJobService.enqueue(
        session,
        job_type="interview.generate_logo",
        business_id=business.id,
        payload={"business_id": str(business.id), "actor_id": str(actor_id)},
        max_attempts=1,
    )
    request.status = "queued"


class BusinessInterviewService:
    @staticmethod
    async def load_business(
        session: AsyncSession, business_id: UUID, *, lock: bool = False
    ) -> Business:
        query = select(Business).where(Business.id == business_id, Business.deleted_at.is_(None))
        if lock:
            query = query.with_for_update()
        business = (
            (await session.execute(query.execution_options(populate_existing=True)))
            .scalars()
            .first()
        )
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="interview")
        return business

    @staticmethod
    def read(business: Business) -> BusinessBlueprint:
        stored = (business.metadata_ or {}).get("interview")
        if stored:
            bp = BusinessBlueprint.model_validate(stored)
            if bp.business_id != business.id:
                raise ValidationError("Interview does not belong to this business")
            return bp
        bp = BusinessBlueprint(
            business_id=business.id,
            identity={
                "display_name": Fact(
                    value=business.display_name, source="PLATFORM", confirmation="confirmed"
                ),
            },
            remaining_questions=list(QUESTIONS),
        )
        bp.category = _category_seed(business)
        bp.name_pending = bool((business.metadata_ or {}).get("name_pending"))
        BusinessInterviewOrchestrator.open(bp)
        return bp

    @staticmethod
    async def save(session: AsyncSession, business: Business, bp: BusinessBlueprint) -> None:
        bp.updated_at = now()
        business.metadata_ = {**(business.metadata_ or {}), "interview": bp.model_dump(mode="json")}
        business.version += 1
        await session.flush()

    @staticmethod
    async def plan(
        session: AsyncSession, business: Business, bp: BusinessBlueprint
    ) -> GenerationPlan:
        entitlement = await BusinessEntitlementResolver.resolve(
            session, business.id, business=business
        )
        active = operational_modules(entitlement)
        rows = await WebsiteCompositionService.available_section_types(
            session, business_id=business.id
        )
        for row in rows:
            row["available"] = row["requires_module"] is None or row["requires_module"] in active
        plan = build_plan(
            business_type=classification_seed(bp), active_modules=active, capability_rows=rows
        )
        selected = bp.template_preferences.template_id
        if selected and bp.template_preferences.source == "USER_STATEMENT":
            template = TEMPLATES_BY_ID.get(selected)
            if not template or not set(template.required_modules) <= active:
                raise ValidationError(
                    "That design is not available with your current tools. Choose another design."
                )
            plan = replace(plan, template=template, template_reason="the owner chose this design")
        else:
            template = select_contextual_template(bp, plan)
            plan = replace(
                plan,
                template=template,
                template_reason="its composition best matches this Business Blueprint",
            )
        return plan

    @staticmethod
    async def response(
        session: AsyncSession,
        business: Business,
        bp: BusinessBlueprint,
        entitlement: ResolvedEntitlement | None = None,
    ) -> dict[str, Any]:
        # `execute` has already resolved this for the same request a few lines
        # earlier, and resolving twice was costing a measurable share of a
        # round trip on commands that cannot change module state at all — a
        # button that only records a choice was doing the platform's most
        # expensive read twice. `build` still re-resolves, because activating a
        # module is exactly the case where the first answer is stale.
        if entitlement is None:
            entitlement = await BusinessEntitlementResolver.resolve(
                session, business.id, business=business
            )
        resolve_recommendations(bp, entitlement, business.business_type)
        active = operational_modules(entitlement)
        logo_url = None
        logo = next((m for m in reversed(bp.media_assets) if m.role == "logo"), None)
        if logo:
            try:
                logo_url = (await MediaService.get(
                    session, business_id=business.id, asset_id=logo.asset_id))["url"]
            except Exception:  # noqa: BLE001 — a missing picture never breaks the page
                logo_url = None
        from platform_core.interview.coverage import floor_met

        applied = {name.casefold() for name in bp.applied_setup_offerings}
        return {
            "blueprint": bp.model_dump(mode="json"),
            "understanding": understanding(bp, business.business_type, logo_url),
            # What the owner named in the conversation that has not become a
            # draft catalogue item yet — offered, never created without asking.
            "setup_pending": [
                name for name, _, _ in _setup_rows(bp) if name and name.casefold() not in applied
            ] if bp.completion_state.status == "built" and bp.completion_state.confirmed else [],
            # Build is offered as soon as there is something honest to build —
            # and never taken away once offered.
            "build_available": bp.completion_state.ready_at is not None
            or floor_met(bp, business.business_type),
            "available_modules": [
                item.model_dump(mode="json") for item in available_modules(bp, entitlement)
            ],
            "classification_seed": classification_seed(bp),
            "templates": [
                t.serialize(
                    available=set(t.required_modules) <= active,
                    missing=tuple(sorted(set(t.required_modules) - active)),
                )
                for t in TEMPLATES_BY_ID.values()
            ],
            "voice": {
                "available": voice.is_configured(),
                "reason": "Talk to Locah instead of typing. You can switch between talking and "
                "typing at any time — it is the same setup either way."
                if voice.is_configured()
                else "Voice isn't available on this server. Chat saves the same interview state.",
            },
            "image_generation": {
                "available": image_generation_available(),
                "reason": "Locah can draw a logo if you have none, or cover artwork. It is "
                "marked as generated — never a photo of your business. Your own photos and "
                "logo always come first.",
            },
        }

    @staticmethod
    async def get(session: AsyncSession, business_id: UUID) -> dict[str, Any]:
        business = await BusinessInterviewService.load_business(session, business_id, lock=True)
        bp = BusinessInterviewService.read(business)
        if not (business.metadata_ or {}).get("interview"):
            await BusinessInterviewService.save(session, business, bp)
        result = await BusinessInterviewService.response(session, business, bp)
        await session.commit()
        return result

    @staticmethod
    def check_revision(bp: BusinessBlueprint, command: InterviewCommand) -> bool:
        if command.request_id in bp.applied_requests:
            return False
        if bp.revision != command.revision:
            raise ConflictError(
                "Your setup changed in another tab. Reload to keep the latest answers.",
                details={"current_revision": bp.revision},
            )
        return True

    @staticmethod
    async def execute(
        session: AsyncSession,
        business_id: UUID,
        command: InterviewCommand,
        *,
        actor_id: UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        business = await BusinessInterviewService.load_business(session, business_id)
        initial = BusinessInterviewService.read(business)
        if not BusinessInterviewService.check_revision(initial, command):
            return await BusinessInterviewService.response(session, business, initial)
        proposed = None
        if command.action == "turn":
            # No row locks or open DB transaction across a network/provider call.
            await session.commit()
            try:
                proposed = await BusinessInterviewOrchestrator.turn(
                    initial, command.text, field=command.field,
                    business_type=business.business_type,
                    image_available=image_generation_available(),
                    via=command.via,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        elif command.action == "draft" and command.draft and command.draft.op == "regenerate":
            await session.commit()
            proposed = await BusinessInterviewOrchestrator.regenerate_draft(
                initial, command.draft.field, command.draft.offering_name,
                business_type=business.business_type,
            )
        elif command.action == "refine":
            proposed = BusinessInterviewOrchestrator.refine(initial, business.business_type)
        business = await BusinessInterviewService.load_business(session, business_id, lock=True)
        bp = BusinessInterviewService.read(business)
        if not BusinessInterviewService.check_revision(bp, command):
            return await BusinessInterviewService.response(session, business, bp)
        if proposed is not None:
            # A logo can finish drawing while the model was thinking about this
            # turn. Keep what the worker wrote; everything else is this turn's.
            _carry_media(bp, proposed)
            bp = proposed
            BusinessInterviewOrchestrator.project(bp, business.business_type)
        entitlement = await BusinessEntitlementResolver.resolve(
            session, business_id, business=business
        )
        previous_unsupported = {
            gap.normalized_intent for gap in initial.unsupported_requests
        }
        resolve_recommendations(bp, entitlement, business.business_type)
        if proposed is not None and command.action == "turn":
            surface_new_unsupported_requests(bp, previous_unsupported)
        if command.action == "confirm":
            BusinessInterviewOrchestrator.confirm(bp, business.business_type)
        elif command.action == "review":
            from platform_core.interview.coverage import floor_met

            if not floor_met(bp, business.business_type):
                raise ValidationError("Tell Locah what you sell or offer first — then it can build.")
            bp.confirm_requested = True
        elif command.action == "correct":
            from platform_core.interview.corrections import CorrectionError, apply_correction

            if command.slot is None:
                raise ValidationError("Choose what to change")
            try:
                apply_correction(bp, command.slot, command.values, command.text)
            except CorrectionError as exc:
                raise ValidationError(str(exc)) from exc
            BusinessInterviewOrchestrator.project(bp, business.business_type)
            resolve_recommendations(bp, entitlement, business.business_type)
        elif command.action == "keep_tools":
            # "Keep recommended": the owner's approval of what was recommended and
            # is included in their access. Approval is not activation — tools are
            # switched on at build, and only those the business is entitled to.
            for item in bp.recommended_modules:
                if item.status == "NOT_CURRENTLY_AVAILABLE" or item.module_id in bp.declined_modules:
                    continue
                if item.module_id not in bp.approved_modules:
                    bp.approved_modules.append(item.module_id)
            resolve_recommendations(bp, entitlement, business.business_type)
        elif command.action == "draft":
            if command.draft is None:
                raise ValidationError("Nothing to change")
            if command.draft.op != "regenerate":
                _apply_draft(bp, command.draft)
        elif command.action == "choices":
            allowed = {item.module_id for item in bp.recommended_modules}
            allowed.update(item.module_id for item in available_modules(bp, entitlement))
            if not set(command.choices) <= allowed:
                raise ValidationError("Choose only tools available for this business")
            for module, choice in command.choices.items():
                bp.approved_modules = [m for m in bp.approved_modules if m != module]
                bp.declined_modules = [m for m in bp.declined_modules if m != module]
                (bp.approved_modules if choice == "approved" else bp.declined_modules).append(
                    module
                )
        elif command.action == "template":
            if command.template_id not in TEMPLATES_BY_ID:
                raise ValidationError("Unknown design")
            bp.template_preferences.template_id = command.template_id
            bp.template_preferences.source = "USER_STATEMENT"
            await BusinessInterviewService.plan(session, business, bp)
        elif command.action == "media":
            if command.media is None:
                raise ValidationError("Choose an uploaded image")
            asset = await MediaService.get(
                session, business_id=business_id, asset_id=command.media.asset_id
            )
            if asset["status"] != "ready" or command.media.source != "USER_UPLOAD":
                raise ValidationError("Finish uploading this image first")
            if len(bp.media_assets) >= 20:
                raise ValidationError("You can attach up to 20 images during setup")
            bp.media_assets = [
                m
                for m in bp.media_assets
                if m.asset_id != command.media.asset_id
                and not (m.role == command.media.role and m.role in {"hero", "logo"})
            ]
            bp.media_assets.append(command.media)
            if command.media.role == "logo":
                bp.logo_state = "uploaded"
        elif command.action == "image":
            if not image_generation_available():
                raise ValidationError(
                    "Image generation is not configured. You can upload an image instead."
                )
            if bp.completion_state.status == "built":
                raise ValidationError(
                    "Use the website editor to request more artwork after building."
                )
            role = command.image_role
            if role == "logo" and any(m.role == "logo" for m in bp.media_assets):
                raise ValidationError("You already added a logo. Your own logo is used.")
            bp.media_generation_requests = [
                r for r in bp.media_generation_requests if r.role != role
            ] + [MediaGenerationRequest(role=role, status="requested")]
            if role == "logo":
                bp.logo_state = "generation_requested"
                bp.discovery.setdefault("media.logo", TargetState()).status = "answered"
        elif command.action == "build":
            await BusinessInterviewService.build(
                session, business, bp, actor_id=actor_id, correlation_id=correlation_id
            )
        elif command.action == "setup":
            await BusinessInterviewService.setup_offerings(
                session, business, bp, actor_id=actor_id, correlation_id=correlation_id
            )
        elif command.action == "catalogue":
            from platform_core.interview.taxonomy import apply_edits

            try:
                touched = apply_edits(bp, command.catalogue)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            if touched and bp.completion_state.status == "built":
                await _sync_catalogue_into_draft(session, business.id, bp)
        elif command.action == "document":
            # The owner attached their menu / catalogue / price list. It is read
            # in the background; nothing reaches the catalogue until they accept it.
            from platform_core.interview import documents

            if command.document_id is None:
                raise ValidationError("Choose the file to read")
            asset = await MediaService.get(session, business_id=business_id, asset_id=command.document_id)
            if asset["purpose"] != "document" or asset["status"] != "ready":
                raise ValidationError("Finish uploading this file first")
            if documents.begin(bp, command.document_id):
                await AsyncJobService.enqueue(
                    session, job_type="interview.read_document", business_id=business_id,
                    payload={"business_id": str(business_id), "asset_id": str(command.document_id)},
                    max_attempts=1,
                )
        elif command.action == "document_apply":
            from platform_core.interview import documents

            if command.document_id is None:
                raise ValidationError("Choose the file to use")
            try:
                touched = documents.apply(bp, command.document_id, command.accept)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            if touched and bp.completion_state.status == "built":
                await _sync_catalogue_into_draft(session, business.id, bp)
        if initial.completion_state.status == "built" and command.action in {"turn", "media", "correct",
                                                                               "catalogue"}:
            await BusinessInterviewService.talk_to_website(
                session, business, bp, command, actor_id=actor_id, correlation_id=correlation_id)
        await _queue_logo(session, business, bp, actor_id=actor_id)
        await _sync_business(session, business, bp)
        bp.revision += 1
        bp.applied_requests = (bp.applied_requests + [command.request_id])[-30:]
        await BusinessInterviewService.save(session, business, bp)
        await AuditService.record(
            session,
            event_type="business.interview.updated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="business",
            resource_id=business_id,
            action=command.action,
            after_state={
                "revision": bp.revision,
                "session_id": str(bp.session_id),
                "completion": bp.completion_state.status,
                "turn_count": bp.turn_count,
            },
        )
        result = await BusinessInterviewService.response(
            session, business, bp, None if command.action == "build" else entitlement
        )
        await session.commit()
        return result

    @staticmethod
    async def talk_to_website(
        session: AsyncSession,
        business: Business,
        bp: BusinessBlueprint,
        command: InterviewCommand,
        *,
        actor_id: UUID,
        correlation_id: str,
    ) -> list[str]:
        """After the website exists, talking to LOCAH changes it — through structured state.

        The message is read for website edits (feel, prices, what leads, new
        items, the story, the cover photo, the headline); each is applied to the
        Blueprint, then only the touched parts of the live draft are updated
        from a fresh deterministic composition. Wording the model wrote and
        anything the owner edited by hand elsewhere on the page are kept.
        """
        from platform_core.interview import website_edits as we

        done: list[str] = []
        if command.action == "turn":
            if we.take_story(bp, command.text):
                done.append("story:set")
            done += we.apply(bp, we.read(command.text))
            said = we.reply(done, bp) if "story:set" not in done else \
                "Thank you — that's your story on the website now. Have a look."
            if said and bp.messages and bp.messages[-1].role == "assistant":
                bp.messages[-1] = bp.messages[-1].model_copy(update={"text": said})
            if not done and bp.last_turn is not None:
                # A business fact said after building (a new number, new hours)
                # still reaches the website.
                done.append("facts")
        elif command.action == "media":
            done.append("photo:hero" if command.media and command.media.role == "hero" else "facts")
        else:
            done.append("facts")
        if done:
            await BusinessInterviewService._apply_to_draft(
                session, business, bp, done, actor_id=actor_id)
        return done

    @staticmethod
    async def _apply_to_draft(
        session: AsyncSession, business: Business, bp: BusinessBlueprint, done: list[str], *, actor_id: UUID
    ) -> None:
        from platform_core.interview.creative_director import direct
        from platform_core.interview.site_composer import compose_site
        from platform_core.services.website import SectionService, WebsiteVersionService
        from platform_core.services.website_composition import WebsiteCompositionService

        kinds = {d.split(":", 1)[0] for d in done}
        plan = await BusinessInterviewService.plan(session, business, bp)
        fresh = compose_site(bp, direct(bp, business.business_type), with_draft(bp, None),
                             business_type=business.business_type, contact=public_contact(bp),
                             active_modules=plan.active_modules)
        aggregate = await WebsiteService.get_aggregate(session, business_id=business.id)
        pages = aggregate["draft"]["pages"]
        if not pages:
            return
        page = next((p for p in pages if p.get("slug") == "home"), pages[0])
        current: dict[str, dict[str, Any]] = {}
        for section in page["sections"]:
            current.setdefault(section["section_type_id"], section)
        new: dict[str, dict[str, Any]] = {}
        for section in fresh["pages"][0]["sections"]:
            new.setdefault(section["section_type_id"], section)

        async def patch(section_type: str, payload: dict[str, Any]) -> None:
            if section_type in current and payload:
                await SectionService.patch_section(session, business_id=business.id,
                                                   section_id=UUID(str(current[section_type]["id"])),
                                                   actor_id=actor_id, payload=payload)

        if "feel" in kinds:
            design_keys = {"primary_color", "accent_color", "background_color", "text_color", "surface_alt_color",
                           "muted_color", "palette_mode", "design_family", "design_variant", "palette_key",
                           "palette_hue", "rhythm", "image_treatment", "surface", "footer_style", "type_system",
                           "reference_profile", "card_style", "nav_style", "hero_style", "personality",
                           "creative_direction", "motion_intensity"}
            theme = {**(aggregate["draft"].get("theme") or {}),
                     **{k: v for k, v in fresh["theme_hints"].items() if k in design_keys}}
            await WebsiteVersionService.update_draft_chrome(session, business_id=business.id, actor_id=actor_id,
                                                            theme=theme)
            for section_type in ("hero", "product_showcase", "category_showcase"):
                if section_type in current and section_type in new and \
                        current[section_type].get("layout_variant") != new[section_type].get("layout_variant"):
                    await patch(section_type, {"layout_variant": new[section_type].get("layout_variant")})
        if kinds & {"prices", "add", "facts"}:
            for section_type in ("product_showcase", "category_showcase", "fulfilment_strip", "contact"):
                if section_type in current and section_type in new:
                    kept = dict(current[section_type].get("content") or {})
                    fresh_content = dict(new[section_type].get("content") or {})
                    written = {str(i.get("name")): i for i in kept.get("items") or [] if isinstance(i, dict)}
                    for key in ("items", "categories"):
                        if key in fresh_content:
                            # Fresh structure (names, prices), the words already written kept.
                            fresh_content[key] = [{**row, **({"description": written[str(row.get("name"))]
                                                              ["description"]} if str(row.get("name")) in written
                                                             and written[str(row.get("name"))].get("description")
                                                             else {})}
                                                  for row in fresh_content[key] if isinstance(row, dict)]
                    for key in ("title", "subtitle"):
                        if kept.get(key):
                            fresh_content[key] = kept[key]
                    await patch(section_type, {"content": fresh_content})
                elif section_type in new and section_type not in current and "add" in kinds:
                    await WebsiteCompositionService.add_section(
                        session, business_id=business.id, page_id=UUID(str(page["id"])), actor_id=actor_id,
                        section_type_id=section_type, content=new[section_type]["content"],
                        layout_variant=new[section_type].get("layout_variant"), position=1)
        if "story" in kinds:
            if "story:reset" in done and "about" in current:
                await patch("about", {"is_visible": False})
            if "story:set" in done and "about" in new:
                if "about" in current:
                    await patch("about", {"content": new["about"]["content"], "is_visible": True,
                                          "layout_variant": new["about"].get("layout_variant")})
                else:
                    await WebsiteCompositionService.add_section(
                        session, business_id=business.id, page_id=UUID(str(page["id"])), actor_id=actor_id,
                        section_type_id="about", content=new["about"]["content"],
                        layout_variant=new["about"].get("layout_variant"))
        if kinds & {"photo", "headline"} and "hero" in new:
            hero = dict(current.get("hero", {}).get("content") or {})
            for key in ("image_asset_id", "headline", "headline_accent"):
                if key in new["hero"]["content"]:
                    hero[key] = new["hero"]["content"][key]
            await patch("hero", {"content": hero, "layout_variant": new["hero"].get("layout_variant")})
        if "lead" in kinds and bp.website_prefs.lead_section:
            refreshed = await WebsiteService.get_aggregate(session, business_id=business.id)
            home = next((p for p in refreshed["draft"]["pages"] if p["id"] == page["id"]), None)
            if home:
                order = [s for s in home["sections"]]
                lead = next((s for s in order[1:] if s["section_type_id"] == bp.website_prefs.lead_section), None)
                if lead:
                    order.remove(lead)
                    order.insert(1, lead)
                    await WebsiteCompositionService.reorder_sections(
                        session, business_id=business.id, page_id=UUID(str(page["id"])), actor_id=actor_id,
                        section_ids=[UUID(str(s["id"])) for s in order])

    @staticmethod
    async def setup_offerings(
        session: AsyncSession,
        business: Business,
        bp: BusinessBlueprint,
        *,
        actor_id: UUID,
        correlation_id: str,
    ) -> None:
        """Apply an explicitly accepted proposal as private, unpriced drafts.

        Names were checked against the owner's words when added to the Website
        draft. Website descriptions are marketing copy, not operational facts,
        so they are intentionally not copied to the catalogue.
        """
        if bp.completion_state.status != "built" or not bp.completion_state.confirmed:
            raise ValidationError("Build and confirm your business before setting up items")
        if "offerings-catalog" not in bp.approved_modules:
            # Chosen during onboarding, or switched on later in the Workspace —
            # either way it is the owner's own choice of the catalogue.
            from platform_core.services.module_readiness import module_operational

            if not await module_operational(session, business.id, "offerings-catalog"):
                raise ValidationError("Choose the online catalogue before setting up items")
        from platform_core.services.offering import OfferingService

        from platform_core.catalog.offering_kinds import FIRST_LAUNCH_KINDS
        from platform_core.interview.playbooks import playbook_for

        existing = await OfferingService.list_for_business(session, business.id)
        known = {item.title.strip().casefold() for item in existing}
        applied = {name.casefold() for name in bp.applied_setup_offerings}
        # What this trade sells (a salon's services, a restaurant's menu items),
        # so a draft can be booked or ordered as it should. The owner can change
        # the kind; a trade whose kind is not a catalogue kind keeps the default.
        offer_kind = playbook_for(bp).offer_kind
        typed = {"offering_type": offer_kind} if offer_kind in FIRST_LAUNCH_KINDS else {}
        for name, price, unit in _setup_rows(bp):
            if not name or name.casefold() in applied:
                continue
            if name.casefold() not in known:
                payload: dict[str, Any] = {
                    "title": name, "status": "draft", "visibility": "private", "price_type": "enquiry", **typed,
                }
                amount = re.sub(r"[^\d.]", "", price)
                if amount:
                    # A price the owner gave (in the chat or typed in the panel).
                    payload.update({"price_type": "fixed", "price_amount": amount})
                    if unit:
                        payload["unit_of_measure"] = unit[:40]
                await OfferingService.create_offering(
                    session,
                    business_id=business.id,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    payload=payload,
                )
                known.add(name.casefold())
            if len(bp.applied_setup_offerings) < 12:
                bp.applied_setup_offerings.append(name)

    @staticmethod
    async def build(
        session: AsyncSession,
        business: Business,
        bp: BusinessBlueprint,
        *,
        actor_id: UUID,
        correlation_id: str,
    ) -> None:
        from platform_core.interview.coverage import floor_met

        BusinessInterviewOrchestrator.project(bp, business.business_type)
        if bp.completion_state.ready_at is None and not floor_met(bp, business.business_type):
            raise ValidationError("Tell Locah what you sell or offer first — then it can build.")
        if bp.name_pending:
            raise ValidationError("Add your business's name first — it's what the website shows.")
        # Pressing Build on the summary is the confirmation. Tool choices never
        # hold the website back: tools not chosen stay off and can be set up later.
        BusinessInterviewOrchestrator.confirm(bp, business.business_type)
        bp.confirm_requested = False
        existing = (
            (
                await session.execute(
                    select(WebsiteGenerationJob).where(
                        WebsiteGenerationJob.business_id == business.id,
                        WebsiteGenerationJob.status.in_(("pending", "running")),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing:
            raise ConflictError(
                "Personalization is already queued. Your existing preview is available."
            )
        if bp.completion_state.status == "built":
            return
        entitlement = await BusinessEntitlementResolver.resolve(
            session, business.id, business=business
        )
        active = {
            m
            for m, state in entitlement.module_states.items()
            if state.activation_state == "active" and state.entitled
        }
        from platform_core.catalog.modules import MODULES as _CATALOGUE

        # Approved but not built yet (Capability Universe modules still to
        # come) stay approved and off: nothing unbuilt is ever switched on.
        pending = {
            m for m in set(bp.approved_modules) & set(entitlement.entitled_modules)
            if m not in _CATALOGUE or (_CATALOGUE[m].built and not _CATALOGUE[m].future)
        }
        while pending:
            ready = {
                mid
                for mid in pending
                if set(ModuleRegistry.get_or_raise(mid).dependencies) <= active
            }
            if not ready:
                # A chosen tool whose prerequisite isn't chosen stays approved but
                # off; the website is built regardless and says only what works.
                break
            for mid in sorted(ready):
                if mid not in active:
                    await ModuleService.enable_module(
                        session,
                        business_id=business.id,
                        module_id=mid,
                        actor_id=actor_id,
                        entitlements=BusinessEntitlementResolver.to_entitlement_set(entitlement),
                        correlation_id=correlation_id,
                    )
                active.add(mid)
            pending -= ready
        from platform_core.services.business_settings import BusinessSettingsService
        from platform_core.services.business_configuration import BusinessConfigurationService

        # Discovery can confirm the business from structured answers without
        # producing the legacy free-text description fact. Do not fabricate a
        # profile description or fail the entire website build in that case.
        description = bp.known_facts.get("description")
        profile: dict[str, Any] = {"description": description.value} if description else {}
        contact = public_contact(bp)
        if contact:
            profile["contact"] = contact
        if profile:
            await BusinessSettingsService.patch_profile(
                session,
                business_id=business.id,
                raw=profile,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        await _hours_to_location(session, business.id, bp, actor_id=actor_id, correlation_id=correlation_id)
        seed = classification_seed(bp)
        if seed != business.business_type:
            await BusinessConfigurationService.patch_business_type(
                session,
                business_id=business.id,
                payload={"business_type": seed},
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        for media in bp.media_assets:
            # Revalidate at use time, not just attachment time.
            asset = await MediaService.get(
                session, business_id=business.id, asset_id=media.asset_id
            )
            if asset["status"] != "ready":
                raise ValidationError("An attached image is no longer ready")
            if media.role == "logo":
                await BusinessSettingsService.patch_branding(
                    session,
                    business_id=business.id,
                    raw={"logo_asset_id": str(media.asset_id)},
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
        plan = await BusinessInterviewService.plan(session, business, bp)
        bp.template_preferences.template_id = plan.template.id
        immediate_strategy = derive_strategy(bp, plan)
        # An owner-requested cover picture is now part of the site's media plan
        # (drawn by personalization in the site's own visual world), not a
        # separate job racing it.
        if any(r.role == "hero" and r.status == "requested" for r in bp.media_generation_requests):
            if bp.visual_consent == "unknown":
                bp.visual_consent = "draft_visuals"
            bp.media_generation_requests = [
                r for r in bp.media_generation_requests if not (r.role == "hero" and r.status == "requested")]
        # A design the owner picked by hand is honoured as it is; otherwise the
        # site is composed from its own creative direction, not a template.
        creative = bp.template_preferences.source != "USER_STATEMENT"
        if creative:
            from platform_core.interview.creative_director import direct
            from platform_core.interview.media_director import plan_media
            from platform_core.interview.site_composer import compose_site

            # Pictures are planned before the design is chosen: a site that will
            # have them (the owner's, or drafts) gets an image-led composition.
            direction = direct(bp, business.business_type)
            plan_media(bp, direction)
            payload = compose_site(
                bp, direction, with_draft(bp, None), business_type=business.business_type,
                contact=public_contact(bp), active_modules=plan.active_modules,
                meta={"stage": "immediate", "creative_strategy": "deterministic",
                      "reference_profile": direction.reference_profile, "fallback_used": False},
            )
        else:
            payload = build_preview(bp, plan, immediate_strategy)
        website = await WebsiteResolver.resolve_website(session, business_id=business.id)
        job = WebsiteGenerationJob(
            business_id=business.id,
            status="pending",
            triggered_by=actor_id,
            prompt_version=GENERATION_PLAN_VERSION,
        )
        session.add(job)
        await session.flush()
        draft = await WebsiteService.replace_draft_from_generation(
            session,
            business_id=business.id,
            website=website,
            payload=payload,
            generated_by="interview_template",
            generation_job_id=job.id,
        )
        bp.completion_state.status = "built"
        bp.completion_state.first_preview_at = now()
        bp.completion_state.generation_job_id = job.id
        from platform_core.interview.draft_merge import base_fingerprints

        written = await WebsiteService.get_aggregate(session, business_id=business.id)
        job.intake = {
            "blueprint": bp.model_dump(mode="json"),
            "base_version_id": str(draft.id),
            "base_updated_at": draft.updated_at.isoformat(),
            # What the build wrote, section by section: personalization replaces
            # only what the owner has not changed since (draft_merge).
            "base_fingerprints": base_fingerprints(written["draft"]),
            "design_strategy": immediate_strategy.model_dump(mode="json"),
            "design_strategy_version": DESIGN_STRATEGY_VERSION,
            "generation_plan_version": GENERATION_PLAN_VERSION,
            "composer": "creative-v2" if creative else "template-v1",
        }
        await AsyncJobService.enqueue(
            session,
            job_type="website.generate",
            business_id=business.id,
            payload={
                "generation_job_id": str(job.id),
                "business_id": str(business.id),
                "correlation_id": correlation_id,
            },
            max_attempts=2,
        )
        get_logger("business.interview").info(
            "interview.preview_ready",
            business_id=str(business.id),
            time_to_preview_ms=int((now() - bp.created_at).total_seconds() * 1000),
            time_to_completion_ms=int(
                ((bp.completion_state.completed_at or now()) - bp.created_at).total_seconds() * 1000
            ),
            turn_count=bp.turn_count,
            template_id=plan.template.id,
            design_strategy_version=DESIGN_STRATEGY_VERSION,
            generation_plan_version=GENERATION_PLAN_VERSION,
        )

    @staticmethod
    async def _personalize_creative(
        session: AsyncSession,
        job: WebsiteGenerationJob,
        bp: BusinessBlueprint,
        business: Business,
        plan: GenerationPlan,
        correlation_id: str,
        started: float,
    ) -> dict[str, Any]:
        """Creative direction + words (one model call), then the pictures, then the page.

        Order (v4): the model chooses the design language first; the pictures
        are then drawn in THAT direction's visual world, so every picture on
        the site belongs to one shoot. If the pictures the design planned for
        could not be made, the composition is re-chosen for a site without
        them rather than left with an empty image-led hero.
        """
        from platform_core.interview.creative_director import (
            CreativeChoices,
            direct,
            generate_creative_plan,
        )
        from platform_core.interview.draft_merge import merge
        from platform_core.interview.media_director import (
            draw_missing,
            owner_photos,
            pictures_expected,
            plan_media,
            record,
            slug,
        )
        from platform_core.interview.site_composer import compose_site
        from platform_core.services.usage_meter import CapReached, UsageMeterService
        from platform_core.website.media_prompts import PROMPT_VERSION

        ai_capped = await UsageMeterService.over_cap(session, job.business_id, "model_tokens")
        await session.commit()  # no transaction held open across the provider calls
        expected = pictures_expected(bp)
        baseline = direct(bp, business.business_type, media_expected=expected)
        fallback: str | None = None
        provider: Any = None
        latency_ms = 0
        try:
            if ai_capped:
                raise CapReached("model_tokens")  # the owner's monthly AI limit: keep the baseline
            direction, copy, provider, latency_ms = await generate_creative_plan(
                bp, business.business_type, media_expected=expected)
            creative_source = direction.source
        except Exception as exc:  # noqa: BLE001 — the pictures still improve the site
            fallback = type(exc).__name__
            direction, copy, creative_source = baseline, None, "deterministic"
        trade = _trade(bp, direction.archetype)
        plan_media(bp, direction)
        images_started = time.monotonic()
        drawn = await draw_missing(bp, direction, trade)
        images_ms = int((time.monotonic() - images_started) * 1000)
        drawn_ok = 0
        for slot, image, reason in drawn:
            if image is None:
                record(bp, slot, None, reason)
                continue
            asset = await MediaService.persist_generated(
                session, business_id=job.business_id, actor_id=job.triggered_by or business.primary_owner_identity_id,
                purpose="website", mime_type=image.mime_type, body=image.bytes,
                alt_text=f"Illustrative picture: {slot.subject or 'cover'}"[:200],
                original_filename=f"draft-{slug(slot.key)}.png",
                generated_for=slot.key, generation_job_id=job.id, prompt_version=PROMPT_VERSION,
            )
            record(bp, slot, UUID(asset["id"]))
            drawn_ok += 1
        hero_ready = any(p.key == "hero" and p.status == "ready" for p in bp.media_plan) or bool(
            [m for m in owner_photos(bp) if m.role == "hero"])
        recomposed = expected and not hero_ready
        if recomposed:
            # The design planned for pictures that could not be made (quota,
            # provider down): choose the composition for a site without them.
            direction = direct(bp, business.business_type,
                               CreativeChoices(**direction.model_choices) if direction.model_choices else None,
                               media_expected=False)
            if creative_source == "ai":
                direction.source = "ai"
            plan_media(bp, direction)
        meta = {
            "stage": "personalised", "creative_strategy": creative_source,
            "reference_profile": direction.reference_profile, "archetype": direction.archetype,
            "fallback_used": bool(fallback), "fallback_reason": fallback,
            "validation_repairs": direction.repairs,
            "media_plan": [{"key": p.key, "truth": p.truth_class, "source": p.source, "status": p.status}
                           for p in bp.media_plan],
            "media_drawn": drawn_ok, "media_failed": len(drawn) - drawn_ok,
            "creative_latency_ms": latency_ms, "image_latency_ms": images_ms,
        }
        if provider is not None:
            job.ai_provider = provider.provider_name
            job.model_name = provider.model_name
        job.provider_usage = {**dict(getattr(provider, "last_usage", None) or {}), **meta}
        if provider is not None:
            await UsageMeterService.record_model_usage(
                session, job.business_id, getattr(provider, "last_usage", None),
                key=f"interview_personalization:{job.id}:{job.attempt_count}", feature="interview_personalization",
            )

        locked = await BusinessInterviewService.load_business(session, job.business_id, lock=True)
        snapshot = job.intake or {}
        draft = (
            (
                await session.execute(
                    select(WebsiteVersion)
                    .where(
                        WebsiteVersion.business_id == job.business_id,
                        WebsiteVersion.version_type == "draft",
                        WebsiteVersion.superseded_at.is_(None),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .first()
        )
        # The pictures belong to the business whatever happens to this draft,
        # and the page is composed from the LIVE Blueprint: anything the owner
        # said since pressing Build is in it.
        live = BusinessInterviewService.read(locked)
        drawn_keys = {r.key for r in bp.media_generation_requests if r.role == "visual"}
        live.media_generation_requests = [
            r for r in live.media_generation_requests if not (r.role == "visual" and r.key in drawn_keys)
        ] + [r for r in bp.media_generation_requests if r.role == "visual"]
        known = {m.asset_id for m in live.media_assets}
        live.media_assets.extend(m for m in bp.media_assets if m.asset_id not in known)
        removed = {p.key for p in live.media_plan if p.approval == "removed"}
        live.media_plan = [p.model_copy(update={"approval": "removed", "status": "skipped"})
                           if p.key in removed else p for p in bp.media_plan]
        await BusinessInterviewService.save(session, locked, live)
        payload = compose_site(
            live, direction, with_draft(live, copy), business_type=business.business_type,
            contact=public_contact(live), active_modules=plan.active_modules, meta=meta,
        )
        kept: list[str] = []
        if not draft or str(draft.id) != snapshot["base_version_id"]:
            # The owner replaced the whole draft (another design): theirs stands.
            job.status = "superseded"
            job.fallback_reason = "Owner replaced the draft; personalization was not applied."
        elif fallback and not drawn_ok and not recomposed:
            job.status = "fallback_used"
            job.fallback_reason = fallback
            job.result_version_id = draft.id
        else:
            merged: dict[str, Any] | None = payload
            if draft.updated_at.isoformat() != snapshot["base_updated_at"]:
                aggregate = await WebsiteService.get_aggregate(session, business_id=job.business_id)
                base = snapshot.get("base_fingerprints")
                merged, kept = merge(payload, aggregate["draft"], base) if base else (None, [])
            if merged is None:
                job.status = "superseded"
                job.fallback_reason = "Owner edits preserved; personalization was not applied."
            else:
                website = await WebsiteResolver.resolve_website(session, business_id=job.business_id)
                generated = await WebsiteService.replace_draft_from_generation(
                    session, business_id=job.business_id, website=website, payload=merged,
                    generated_by="interview_personalization", generation_job_id=job.id,
                )
                job.result_version_id = generated.id
                job.status = "completed"
                job.fallback_reason = fallback
        job.provider_usage = {
            **(job.provider_usage or {}),
            "owner_edits_kept": kept,
            "personalization_latency_ms": int((time.monotonic() - started) * 1000),
            "total_time_to_personalized_preview_ms": int((now() - bp.created_at).total_seconds() * 1000),
        }
        job.completed_at = now()
        await session.flush()
        await OutboxService.publish(
            session, event_type="website.draft_generated", business_id=job.business_id,
            correlation_id=correlation_id,
            payload={"business_id": str(job.business_id), "job_id": str(job.id), "status": job.status,
                     "composer": "creative-v2", "reference_profile": direction.reference_profile,
                     "strategy_source": creative_source},
        )
        get_logger("business.interview").info(
            "interview.website_personalized", business_id=str(job.business_id), job_id=str(job.id),
            status=job.status, composer="creative-v2", archetype=direction.archetype,
            reference_profile=direction.reference_profile, model=job.model_name,
            strategy_source=creative_source, fallback_reason=job.fallback_reason,
            media_drawn=drawn_ok, media_failed=len(drawn) - drawn_ok, image_latency_ms=images_ms,
            creative_latency_ms=latency_ms, owner_edits_kept=kept,
            personalization_latency_ms=job.provider_usage.get("personalization_latency_ms"),
        )
        return {"status": job.status, "job_id": str(job.id)}

    @staticmethod
    async def personalize_job(
        session: AsyncSession, job: WebsiteGenerationJob, correlation_id: str
    ) -> dict[str, Any]:
        snapshot = job.intake or {}
        bp = BusinessBlueprint.model_validate(snapshot["blueprint"])
        business = await BusinessInterviewService.load_business(session, job.business_id)
        plan = await BusinessInterviewService.plan(session, business, bp)
        job.status = "running"
        job.started_at = now()
        job.attempt_count = (job.attempt_count or 0) + 1
        fallback = None
        strategy_source = "deterministic"
        personalization_started = time.monotonic()
        if snapshot.get("composer") == "creative-v2":
            return await BusinessInterviewService._personalize_creative(
                session, job, bp, business, plan, correlation_id, personalization_started)
        try:
            result, copy, provider = await generate_website_plan(bp, plan)
            payload = build_preview(bp, plan, result.strategy, copy)
            job.ai_provider = provider.provider_name
            job.model_name = provider.model_name
            provider_usage = dict(getattr(provider, "last_usage", None) or {})
            provider_usage.update(
                {
                    "design_strategy_version": DESIGN_STRATEGY_VERSION,
                    "generation_plan_version": GENERATION_PLAN_VERSION,
                    "strategy_latency_ms": result.latency_ms,
                    "strategy_repair_count": result.quality.repair_count,
                    "strategy_validation_issue_count": len(result.quality.issues),
                    "website_quality_valid": payload["theme_hints"]["quality"]["valid"],
                    "website_quality_issue_count": len(
                        payload["theme_hints"]["quality"]["issues"]
                    ),
                }
            )
            job.provider_usage = provider_usage
            strategy_source = result.strategy.source
        except Exception as exc:
            fallback = type(exc).__name__
            payload = build_preview(bp, plan, derive_strategy(bp, plan))
        # Business row first, then the draft: the same order the artwork job
        # takes, so the two never deadlock and the later one places the artwork.
        locked = await BusinessInterviewService.load_business(session, job.business_id, lock=True)
        # Lock and refresh the *exact* immediate preview. Edits before the worker
        # starts count too; compare against enqueue time, not job.started_at.
        draft = (
            (
                await session.execute(
                    select(WebsiteVersion)
                    .where(
                        WebsiteVersion.business_id == job.business_id,
                        WebsiteVersion.version_type == "draft",
                        WebsiteVersion.superseded_at.is_(None),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .first()
        )
        if (
            not draft
            or str(draft.id) != snapshot["base_version_id"]
            or draft.updated_at.isoformat() != snapshot["base_updated_at"]
        ):
            job.status = "superseded"
            job.fallback_reason = "Owner edits preserved; personalization was not applied."
        elif fallback:
            # The first preview is already the safe fallback. Do not replace it.
            job.status = "fallback_used"
            job.fallback_reason = fallback
            job.result_version_id = draft.id
        else:
            website = await WebsiteResolver.resolve_website(session, business_id=job.business_id)
            generated = await WebsiteService.replace_draft_from_generation(
                session,
                business_id=job.business_id,
                website=website,
                payload=payload,
                generated_by="interview_personalization",
                generation_job_id=job.id,
            )
            job.result_version_id = generated.id
            job.status = "completed"
            job.fallback_reason = None  # an earlier failed attempt is not this result
        from platform_core.interview.media import place_ready_artwork

        await place_ready_artwork(session, job.business_id, BusinessInterviewService.read(locked))
        job.provider_usage = {
            **(job.provider_usage or {}),
            "personalization_latency_ms": int(
                (time.monotonic() - personalization_started) * 1000
            ),
            "total_time_to_personalized_preview_ms": int(
                (now() - bp.created_at).total_seconds() * 1000
            ),
        }
        job.completed_at = now()
        await session.flush()
        await OutboxService.publish(
            session,
            event_type="website.draft_generated",
            business_id=job.business_id,
            correlation_id=correlation_id,
            payload={
                "business_id": str(job.business_id),
                "job_id": str(job.id),
                "status": job.status,
                "template_id": plan.template.id,
                "design_strategy_version": DESIGN_STRATEGY_VERSION,
                "generation_plan_version": GENERATION_PLAN_VERSION,
                "strategy_source": strategy_source,
            },
        )
        get_logger("business.interview").info(
            "interview.website_personalized",
            business_id=str(job.business_id),
            job_id=str(job.id),
            status=job.status,
            template_id=plan.template.id,
            model=job.model_name,
            strategy_source=strategy_source,
            fallback_reason=job.fallback_reason,
            personalization_latency_ms=(job.provider_usage or {}).get(
                "personalization_latency_ms"
            ),
            total_time_to_personalized_preview_ms=(job.provider_usage or {}).get(
                "total_time_to_personalized_preview_ms"
            ),
            strategy_repair_count=(job.provider_usage or {}).get("strategy_repair_count"),
            prompt_tokens=(job.provider_usage or {}).get("prompt_tokens"),
            completion_tokens=(job.provider_usage or {}).get("completion_tokens"),
        )
        return {"status": job.status, "job_id": str(job.id)}
