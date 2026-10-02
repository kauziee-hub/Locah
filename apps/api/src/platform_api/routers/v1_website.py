"""Website APIs (Stage 2 — Doc 12 §11 / §12)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.permissions import WEBSITE_EDIT, WEBSITE_PUBLISH, WEBSITE_READ
from platform_core.resolvers.website_resolver import WebsiteResolver
from platform_core.services.business import BusinessService
from platform_core.services.website import PageService, SectionService, WebsiteService, WebsiteVersionService
from platform_core.services.website_composition import (
    WebsiteCompositionService,
    WebsiteTemplateService,
)
from platform_core.services.website_generation import WebsiteGenerationService
from platform_core.services.website_publish import WebsitePublishService
from platform_core.services.website_images import WebsiteImageService
from platform_core.website.questionnaire import get_questionnaire

router = APIRouter(prefix="/v1/b", tags=["website"])


class GenerateWebsiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake: dict[str, Any] | None = None


class PatchPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    is_published: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class PatchSectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] | None = None
    layout_variant: str | None = None
    is_visible: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class PatchThemeNavRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    navigation: list[dict[str, Any]] | None = None
    theme: dict[str, Any] | None = None


@router.get("/{business_id}/website/generation")
async def latest_generation(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    job = await WebsiteGenerationService.latest_job(session, business_id=business_id)
    return {
        "data": WebsiteGenerationService.serialize_job(job) if job is not None else None,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/website/questionnaire")
async def website_questionnaire(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    business = await BusinessService.get_by_id(session, business_id)
    return {
        "data": get_questionnaire(business.business_type),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/website/generate")
async def generate_website(
    business_id: UUID,
    body: GenerateWebsiteRequest | None = None,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    job = await WebsiteGenerationService.enqueue_generation(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
        auto=False,
        intake=body.intake if body else None,
    )
    await session.commit()
    return {
        "data": WebsiteGenerationService.serialize_job(job),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/website")
async def get_website(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await WebsiteService.get_aggregate(session, business_id=business_id)
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/website/pages/{page_id}")
async def patch_page(
    business_id: UUID,
    page_id: UUID,
    body: PatchPageRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    page = await PageService.patch_page(
        session,
        business_id=business_id,
        page_id=page_id,
        actor_id=actor.request.identity_id,
        payload=body.model_dump(exclude_unset=True),
    )
    await session.commit()
    return {
        "data": WebsiteResolver.serialize_page(page),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.patch("/{business_id}/website/sections/{section_id}")
async def patch_section(
    business_id: UUID,
    section_id: UUID,
    body: PatchSectionRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    section = await SectionService.patch_section(
        session,
        business_id=business_id,
        section_id=section_id,
        actor_id=actor.request.identity_id,
        payload=body.model_dump(exclude_unset=True),
    )
    await session.commit()
    return {
        "data": WebsiteResolver.serialize_section(section),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


class GenerateImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A card's picture: which list ("items" / "categories") and which row.
    list_key: str | None = Field(default=None, max_length=20)
    index: int | None = Field(default=None, ge=0, le=47)


@router.post("/{business_id}/website/sections/{section_id}/generate-image")
async def generate_section_image(
    business_id: UUID,
    section_id: UUID,
    body: GenerateImageRequest | None = None,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await WebsiteImageService.generate_section_image(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        section_id=section_id,
        list_key=body.list_key if body else None,
        index=body.index if body else None,
    )
    await session.commit()
    return {"data": result, "meta": {"correlation_id": actor.request.correlation_id}}


@router.patch("/{business_id}/website/theme")
async def patch_theme_navigation(
    business_id: UUID,
    body: PatchThemeNavRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    draft = await WebsiteVersionService.update_draft_chrome(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        navigation=body.navigation,
        theme=body.theme,
    )
    await session.commit()
    return {
        "data": WebsiteResolver.serialize_version(draft),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.get("/{business_id}/website/preview-token")
async def get_preview_token(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await WebsitePublishService.create_preview_token(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
    )
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/website/publish")
async def publish_website(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_PUBLISH)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await WebsitePublishService.publish(
        session,
        business_id=business_id,
        actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id,
    )
    await session.commit()
    return {
        "data": data,
        "meta": {"correlation_id": actor.request.correlation_id},
    }


class AddSectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_type_id: str = Field(min_length=1, max_length=60)
    content: dict[str, Any] | None = None
    layout_variant: str | None = None
    # Index among the sections a person can see, not a raw sort_order: the
    # editor knows "third from the top", never the numbering behind it.
    position: int | None = Field(default=None, ge=0)


class ReorderSectionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_ids: list[UUID] = Field(min_length=1, max_length=40)


@router.get("/{business_id}/website/section-types")
async def list_section_types(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """What this business may add to a page — and what it may not, with the reason.

    Unavailable types are returned rather than filtered out, so the editor can
    say "Menu needs your offerings catalogue" instead of silently lacking a
    control the owner has seen on somebody else's site.
    """
    types = await WebsiteCompositionService.available_section_types(
        session, business_id=business_id
    )
    return {
        "data": {"section_types": types},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/website/pages/{page_id}/sections")
async def add_section(
    business_id: UUID,
    page_id: UUID,
    body: AddSectionRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    section = await WebsiteCompositionService.add_section(
        session,
        business_id=business_id,
        page_id=page_id,
        actor_id=actor.request.identity_id,
        section_type_id=body.section_type_id,
        content=body.content,
        layout_variant=body.layout_variant,
        position=body.position,
    )
    await session.commit()
    return {
        "data": WebsiteResolver.serialize_section(section),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/website/sections/{section_id}/duplicate")
async def duplicate_section(
    business_id: UUID,
    section_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    section = await WebsiteCompositionService.duplicate_section(
        session,
        business_id=business_id,
        section_id=section_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    return {
        "data": WebsiteResolver.serialize_section(section),
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.delete("/{business_id}/website/sections/{section_id}")
async def remove_section(
    business_id: UUID,
    section_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    page_id = await WebsiteCompositionService.remove_section(
        session,
        business_id=business_id,
        section_id=section_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    return {
        "data": {"removed": str(section_id), "page_id": str(page_id)},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


@router.post("/{business_id}/website/pages/{page_id}/sections/reorder")
async def reorder_sections(
    business_id: UUID,
    page_id: UUID,
    body: ReorderSectionsRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    sections = await WebsiteCompositionService.reorder_sections(
        session,
        business_id=business_id,
        page_id=page_id,
        actor_id=actor.request.identity_id,
        section_ids=list(body.section_ids),
    )
    await session.commit()
    return {
        "data": {"sections": [WebsiteResolver.serialize_section(s) for s in sections]},
        "meta": {"correlation_id": actor.request.correlation_id},
    }


class ApplyTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=60)


@router.get("/{business_id}/website/templates")
async def list_templates(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Templates this business can start from, best fit first.

    Every template is returned, not only the matching ones: a caterer may want
    the editorial layout, and filtering it out would be the platform deciding
    taste on the owner's behalf. Ones whose modules are off come back marked,
    with the module named.
    """
    data = await WebsiteTemplateService.list_for_business(session, business_id=business_id)
    return {"data": data, "meta": {"correlation_id": actor.request.correlation_id}}


@router.post("/{business_id}/website/templates/apply")
async def apply_template(
    business_id: UUID,
    body: ApplyTemplateRequest,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Replace the draft with a template.

    This discards the current draft, which is the honest meaning of "use this
    one instead". A published site keeps serving what it published until the
    owner publishes again.
    """
    await WebsiteTemplateService.apply(
        session,
        business_id=business_id,
        template_id=body.template_id,
        actor_id=actor.request.identity_id,
    )
    await session.commit()
    aggregate = await WebsiteService.get_aggregate(session, business_id=business_id)
    return {"data": aggregate, "meta": {"correlation_id": actor.request.correlation_id}}


# ---------------------------------------------------------------- what the business's tools add (P1-10C)
_ACTION_WORDS = {
    "catalogue": "Customers can see what you offer, with prices",
    "order": "Customers can order online", "book": "Customers can book", "join": "Customers can see and join plans",
    "request_quote": "Customers can ask for a quote", "enquire": "Customers can send an enquiry",
    "site_visit": "Customers can ask for a site visit", "test_drive": "Customers can ask for a test drive",
    "donate": "Supporters can donate", "track": "Customers can track their order",
}
_ACTION_MODULE = {
    "catalogue": "offerings-catalog",
    "order": "orders", "book": "bookings", "join": "memberships", "request_quote": "quotes", "enquire": "leads",
    "site_visit": "leads", "test_drive": "leads", "donate": "orders", "track": "fulfilment",
}
# Actions worth a "not yet" line when their tool is on but unfinished; the
# others only exist for businesses that list the right things (a project, a car).
_ALWAYS_OFFERED = {"catalogue", "order", "book", "join", "request_quote", "enquire", "track"}
_SECTION_WORDS = {
    "offerings-catalog": "Your {catalogue}, from your real items and prices",
    "memberships": "Your plans, so people can join",
    "bookings": "A way to book", "reviews": "Your verified reviews", "leads": "An enquiry form",
}


class AutoSectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str = Field(min_length=1, max_length=60)
    hidden: bool


class LanguagesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(min_length=1, max_length=3)


@router.get("/{business_id}/website/capabilities")
async def website_capabilities(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """What customers can do on this site right now (from real module readiness),
    and the sections the business's tools add when its design has none."""
    from sqlalchemy import select

    from platform_core.website import capabilities as caps

    website = await WebsiteResolver.resolve_website(session, business_id=business_id)
    flags = await caps.site_capabilities(session, business_id)
    kinds, traits = flags.pop("_kinds", {}), flags.pop("_traits", [])
    version_id = website.published_version_id
    if version_id is None:
        from platform_core.models import WebsiteVersion

        version_id = (await session.execute(select(WebsiteVersion.id).where(
            WebsiteVersion.business_id == business_id, WebsiteVersion.version_type == "draft",
            WebsiteVersion.superseded_at.is_(None)))).scalars().first()
    types = await caps.section_types(session, version_id)
    reviews = await caps.published_review_count(session, business_id)
    would = caps.auto_sections({**flags, "_kinds": kinds}, types, hidden=[], published_reviews=reviews, traits=traits)
    hidden = {caps.LEGACY_HIDDEN.get(m, m) for m in website.auto_sections_hidden or []}
    catalogue = str(flags.get("catalogue_label") or "What we offer").lower()

    def section_words(module: str) -> str:
        return _SECTION_WORDS.get(module, module).format(catalogue=catalogue)

    from platform_core.services.module_readiness import readiness

    states = await readiness(session, business_id)
    actions = []
    for key, label in _ACTION_WORDS.items():
        module = _ACTION_MODULE[key]
        state = states.get(module) or {}
        if flags.get(key):
            actions.append({"key": key, "label": label, "live": True, "module": module, "next_step": None})
        elif key in _ALWAYS_OFFERED and state.get("enabled"):
            # Switched on but not set up yet: say the one thing still missing.
            todo = next((st["label"] for st in state.get("steps") or [] if not st["done"]), None)
            if not todo and state.get("blocked_by"):
                from platform_core.catalog.modules import MODULES

                needs = [MODULES[m].label if m in MODULES else m for m in state["blocked_by"]]
                todo = f"Finish setting up {' and '.join(needs)} first"
            if not todo and not state.get("entitled", True):
                todo = "Not included in your plan right now"
            if key == "order" and state.get("ready") and not (states.get("fulfilment") or {}).get("ready"):
                todo = "Turn on pickup or delivery (Pickup & delivery) so orders can be handed over"
            if key == "request_quote" and not (states.get("leads") or {}).get("ready"):
                todo = todo or "Switch on Enquiries so quote requests have somewhere to land"
            actions.append({"key": key, "label": label, "live": False, "module": module,
                            "next_step": todo or "Finish setting this up"})
    return {"data": {
        "primary": flags.get("primary"), "primary_label": flags.get("primary_label"),
        "actions": actions,
        "auto_sections": [{"module": s["module"], "section_type": s["section_type_id"],
                           "label": section_words(s["module"]),
                           "state": "hidden" if s["module"] in hidden else "showing"} for s in would]
        + [{"module": m, "section_type": None, "label": section_words(m), "state": "hidden"}
           for m in sorted(hidden) if m not in {s["module"] for s in would}],
    }, "meta": {"correlation_id": actor.request.correlation_id}}


@router.patch("/{business_id}/website/auto-sections")
async def set_auto_section(
    business_id: UUID, body: AutoSectionBody,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Show or hide a section a tool adds (the owner's design stays theirs)."""
    from platform_core.exceptions import ValidationError
    from platform_core.services.audit import AuditService
    from platform_core.services.outbox import OutboxService
    from platform_core.website.capabilities import AUTO_SECTION_MODULES

    if body.module not in AUTO_SECTION_MODULES:
        raise ValidationError("That tool does not add a section")
    website = await WebsiteResolver.resolve_website(session, business_id=business_id)
    from platform_core.website.capabilities import LEGACY_HIDDEN

    # A pre-catalogue "orders" entry hid the shop; it now means the catalogue.
    hidden = {LEGACY_HIDDEN.get(m, m) for m in website.auto_sections_hidden or []}
    hidden = hidden | {body.module} if body.hidden else hidden - {body.module}
    website.auto_sections_hidden = sorted(hidden)
    await AuditService.record(session, event_type="website.auto_section.changed",
                              actor_identity_id=actor.request.identity_id, actor_context="business",
                              business_id=business_id, resource_type="website", resource_id=website.id,
                              action="hide" if body.hidden else "show", after_state={"hidden": sorted(hidden)})
    await OutboxService.publish(session, event_type="website.auto_sections.changed",
                                payload={"business_id": str(business_id), "hidden": sorted(hidden)},
                                business_id=business_id, correlation_id=actor.request.correlation_id)
    await session.commit()
    return {"data": {"hidden": sorted(hidden)}, "meta": {"correlation_id": actor.request.correlation_id}}


@router.put("/{business_id}/website/languages")
async def set_languages(
    business_id: UUID, body: LanguagesBody,
    actor: BusinessActorContext = Depends(require_business_actor(WEBSITE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """The languages the site's own words come in; the first is shown first (P1-10E6)."""
    from platform_core.exceptions import ValidationError
    from platform_core.services.audit import AuditService
    from platform_core.services.outbox import OutboxService

    chosen = list(dict.fromkeys(body.languages))
    if any(x not in ("en", "ta", "hi") for x in chosen):
        raise ValidationError("Choose from English, Tamil and Hindi",
                              details={"field": "languages", "errors": [
                                  {"field": "languages", "message": "Choose from English, Tamil and Hindi"}]})
    website = await WebsiteResolver.resolve_website(session, business_id=business_id)
    before = list(website.languages or ["en"])
    website.languages = chosen
    await AuditService.record(session, event_type="website.languages.changed",
                              actor_identity_id=actor.request.identity_id, actor_context="business",
                              business_id=business_id, resource_type="website", resource_id=website.id,
                              action="update", before_state={"languages": before}, after_state={"languages": chosen})
    await OutboxService.publish(session, event_type="website.languages.changed",
                                payload={"business_id": str(business_id), "languages": chosen},
                                business_id=business_id, correlation_id=actor.request.correlation_id)
    await session.commit()
    return {"data": {"languages": chosen}, "meta": {"correlation_id": actor.request.correlation_id}}
