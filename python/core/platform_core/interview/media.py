"""Opt-in cover artwork and logo. Never synthesize photos of actual staff/products.

Two things an owner may ask Locah for, and only when they ask:

  hero  a wide picture for the top of the homepage — mood and material for the
        trade, never a picture of the business itself. By default a real
        photograph found online and checked (website.image_retrieval, marked
        STOCK_PHOTO); drawn (AI_GENERATED) only where IMAGE_PROVIDER=gemini;
  logo  a one-letter monogram, for an owner who has no logo yet. Only ever
        drawn (IMAGE_PROVIDER=gemini): a logo cannot be found.

Both are stored as ordinary media assets, and both lose to anything the owner
uploads: a hero section that already has a picture keeps it, and an uploaded
logo is never replaced.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.interview.capabilities import classification_seed
from platform_core.interview.models import (
    BusinessBlueprint,
    MediaGenerationRequest,
    MediaReference,
    now,
)
from platform_core.models import (
    WebsiteGenerationJob,
    WebsitePage,
    WebsiteSection,
    WebsiteVersion,
)
from platform_core.services.media import MediaService
from platform_core.website.image_generation import (
    GeneratedImage,
    generate_image_bytes,
    logo_prompt,
    FAILURE_REASONS,
    brand_logo_prompt,
    generate_image,
    picture_source,
)
from platform_core.website.image_retrieval import FoundImage
from platform_core.website.template_registry import TEMPLATES_BY_ID


class InterviewImageAdapter(Protocol):
    async def generate(
        self, prompt: str, *, aspect_ratio: str = "16:9"
    ) -> GeneratedImage | None: ...


class ExistingImageAdapter:
    async def generate(self, prompt: str, *, aspect_ratio: str = "16:9") -> GeneratedImage | None:
        return await generate_image_bytes(prompt, aspect_ratio=aspect_ratio, timeout_seconds=45)


def _palette(bp: BusinessBlueprint) -> tuple[str, ...]:
    template = TEMPLATES_BY_ID.get(bp.template_preferences.template_id or "")
    if template is None:
        return ()
    return (template.primary_color, template.accent_color)


def prompt_for(request: MediaGenerationRequest, bp: BusinessBlueprint) -> tuple[str, str]:
    """(prompt, aspect ratio) for one request. Nothing the owner said about
    staff, rooms or products is passed on — only the trade and the site's own
    visual world (the same shoot brief as every other picture on the site)."""
    from platform_core.interview.creative_director import direct
    from platform_core.interview.media_director import prompt_for as slot_prompt
    from platform_core.interview.media_director import plan_slots

    if request.role == "logo":
        palette = _palette(bp)
        name = str(bp.identity.get("display_name").value if bp.identity.get("display_name") else "")
        return logo_prompt(initial=name, primary=palette[0] if palette else None), "1:1"
    direction = direct(bp, media_expected=True)  # this job is drawing the picture
    hero = next(s for s in plan_slots(bp, direction) if s.key == "hero")
    return slot_prompt(hero, direction, classification_seed(bp).replace("_", " ")), hero.aspect


def _queued(bp: BusinessBlueprint, role: str) -> MediaGenerationRequest | None:
    return next(
        (r for r in bp.media_generation_requests if r.role == role and r.status == "queued"), None
    )


async def generate_interview_media(
    session: AsyncSession,
    *,
    business_id: UUID,
    actor_id: UUID,
    generation_job_id: UUID,
    adapter: InterviewImageAdapter | None = None,
) -> None:
    from platform_core.services.business_interview import BusinessInterviewService

    business = await BusinessInterviewService.load_business(session, business_id)
    bp = BusinessInterviewService.read(business)
    if bp.completion_state.generation_job_id != generation_job_id:
        return
    # Cover artwork only. A logo has its own job (interview.generate_logo), queued
    # the moment it is asked for; drawing it here too would pay for it twice.
    work = [r for r in (_queued(bp, "hero"),) if r is not None]
    if not work:
        return
    # Generate outside the row lock — a slow provider must not block the owner.
    drawn: dict[str, Any] = {}
    for request in work:
        if request.role == "hero" and adapter is None and picture_source() == "stock":
            drawn[request.role] = await find_hero_photo(bp)  # a FoundImage, or None
            continue
        prompt, aspect = prompt_for(request, bp)
        drawn[request.role] = await (adapter or ExistingImageAdapter()).generate(
            prompt, aspect_ratio=aspect
        )

    business = await BusinessInterviewService.load_business(session, business_id, lock=True)
    bp = BusinessInterviewService.read(business)
    if bp.completion_state.generation_job_id != generation_job_id:
        return
    for role, generated in drawn.items():
        request = _queued(bp, role)
        if request is None:
            continue
        if generated is None:
            request.status = "failed"
            request.reason = (
                "The logo could not be drawn. You can upload one any time."
                if role == "logo"
                else "Artwork could not be generated. Your website is usable without it."
            )
            continue
        if role == "logo":
            await _apply_logo(session, business_id, actor_id, bp, request, generated)
        elif isinstance(generated, FoundImage):
            await _apply_hero_found(
                session, business_id, actor_id, generation_job_id, bp, request, generated
            )
        else:
            await _apply_hero(
                session, business_id, actor_id, generation_job_id, bp, request, generated
            )
    bp.revision += 1
    await BusinessInterviewService.save(session, business, bp)


async def find_hero_photo(bp: BusinessBlueprint) -> FoundImage | None:
    """A verified real photograph for the cover, in the site's own visual world."""
    from platform_core.interview.creative_director import direct
    from platform_core.interview.media_director import plan_slots
    from platform_core.website.image_retrieval import brief_for_slot, retrieve_for_slot

    direction = direct(bp, media_expected=True)  # this job is finding the picture
    hero = next(s for s in plan_slots(bp, direction) if s.key == "hero")
    outcome = await retrieve_for_slot(
        brief_for_slot(hero, direction, classification_seed(bp).replace("_", " ")))
    return outcome.found


async def _apply_hero_found(
    session: AsyncSession,
    business_id: UUID,
    actor_id: UUID,
    generation_job_id: UUID,
    bp: BusinessBlueprint,
    request: MediaGenerationRequest,
    found: FoundImage,
) -> None:
    asset = await MediaService.persist_retrieved(
        session,
        business_id=business_id,
        actor_id=actor_id,
        purpose="website",
        url=found.url,
        page_url=found.page_url,
        mime_type=found.mime_type,
        alt_text="Photograph for the top of the website",
        credit=found.credit or f"{found.photographer} via {found.provider.title()}",
        width=found.width,
        height=found.height,
        generated_for="hero",
        generation_job_id=generation_job_id,
    )
    request.status = "ready"
    request.asset_id = UUID(asset["id"])
    bp.media_assets.append(
        MediaReference(
            asset_id=request.asset_id, role="hero", label="Stock photo · cover", source="STOCK_PHOTO",
        )
    )
    # Same hand-off as a drawn cover: personalization places it if it is still running.
    job = await session.get(WebsiteGenerationJob, generation_job_id)
    if job is not None and job.status in {"pending", "running"}:
        return
    await place_ready_artwork(session, business_id, bp)


async def _apply_hero(
    session: AsyncSession,
    business_id: UUID,
    actor_id: UUID,
    generation_job_id: UUID,
    bp: BusinessBlueprint,
    request: MediaGenerationRequest,
    generated: GeneratedImage,
) -> None:
    asset = await MediaService.persist_generated(
        session,
        business_id=business_id,
        actor_id=actor_id,
        purpose="website",
        mime_type=generated.mime_type,
        body=generated.bytes,
        alt_text="AI-generated decorative artwork",
        original_filename="cover-artwork.png",
    )
    request.status = "ready"
    request.asset_id = UUID(asset["id"])
    bp.media_assets.append(
        MediaReference(
            asset_id=request.asset_id,
            role="hero",
            label="AI-generated cover artwork",
            source="AI_GENERATED",
        )
    )
    # While personalization is still running the draft is not ours to touch:
    # changing it now would look like an owner edit and discard the
    # personalized site. Personalization places the artwork when it finishes.
    job = await session.get(WebsiteGenerationJob, generation_job_id)
    if job is not None and job.status in {"pending", "running"}:
        return
    await place_ready_artwork(session, business_id, bp)


async def place_ready_artwork(
    session: AsyncSession, business_id: UUID, bp: BusinessBlueprint
) -> bool:
    """Put ready generated artwork into the current draft's hero, if it has none.

    Callers hold the business row lock, then this takes the draft lock — the
    same order personalization uses — so the artwork job and personalization
    serialize, and whichever finishes second does the placing.
    """
    ready = next(
        (
            r
            for r in bp.media_generation_requests
            if r.role == "hero" and r.status == "ready" and r.asset_id
        ),
        None,
    )
    if ready is None:
        return False
    draft = (
        (
            await session.execute(
                select(WebsiteVersion)
                .where(
                    WebsiteVersion.business_id == business_id,
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
    if draft is None:
        return False
    hero = (
        (
            await session.execute(
                select(WebsiteSection)
                .join(WebsitePage)
                .where(
                    WebsitePage.website_version_id == draft.id,
                    WebsiteSection.section_type_id == "hero",
                )
                .order_by(WebsitePage.sort_order, WebsiteSection.sort_order)
            )
        )
        .scalars()
        .first()
    )
    # A picture the owner chose — or one they put there after the build — wins.
    if hero is None or (hero.content or {}).get("image_asset_id"):
        return False
    hero.content = {**(hero.content or {}), "image_asset_id": str(ready.asset_id)}
    draft.updated_at = now()
    return True


async def _apply_logo(
    session: AsyncSession,
    business_id: UUID,
    actor_id: UUID,
    bp: BusinessBlueprint,
    request: MediaGenerationRequest,
    generated: GeneratedImage,
) -> None:
    from platform_core.services.business_settings import BusinessSettingsService

    if any(m.role == "logo" and m.source == "USER_UPLOAD" for m in bp.media_assets):
        request.status = "failed"
        request.reason = "You uploaded your own logo, so it is used instead."
        return
    asset = await MediaService.persist_generated(
        session,
        business_id=business_id,
        actor_id=actor_id,
        purpose="brand",
        mime_type=generated.mime_type,
        body=generated.bytes,
        alt_text="AI-generated monogram logo",
        original_filename="generated-logo.png",
    )
    await BusinessSettingsService.patch_branding(
        session,
        business_id=business_id,
        raw={"logo_asset_id": asset["id"]},
        actor_id=actor_id,
        correlation_id=str(uuid4()),
    )
    request.status = "ready"
    request.asset_id = UUID(asset["id"])
    bp.media_assets.append(
        MediaReference(
            asset_id=request.asset_id, role="logo", label="AI-generated logo", source="AI_GENERATED"
        )
    )
    bp.logo_state = "generated"


# Name kept for callers and jobs from before logos could be drawn.
generate_interview_hero = generate_interview_media


# --------------------------------------------------------------- logo, now
#
# An owner who says "generate one" in the middle of the conversation should see
# a logo appear beside it — not learn after building that one was made. The
# request is queued as soon as it is recorded and drawn by the worker while the
# conversation carries on.

LogoDrawer = Callable[[str, str], Awaitable[tuple[GeneratedImage | None, str]]]


def logo_brief(bp: BusinessBlueprint) -> str:
    """The logo prompt, from brand context only — never the transcript."""
    from platform_core.interview.discovery import profile_type
    from platform_core.website.template_registry import templates_for_business_type

    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    name = bp.identity["display_name"].value if "display_name" in bp.identity else ""
    identity = bp.discovery.get("business.identity")
    category = ""
    if "classification" in facts:
        category = facts["classification"].value
    elif identity and identity.summary:
        category = identity.summary
    feel = bp.discovery.get("brand.feel")
    direction = (facts["brand"].value if "brand" in facts else "") or (feel.summary if feel else "")
    template = TEMPLATES_BY_ID.get(bp.template_preferences.template_id or "") or (
        templates_for_business_type(profile_type(bp))[0]
    )
    return str(brand_logo_prompt(
        name=name, category=category[:80], direction=direction,
        palette=(template.primary_color, template.accent_color),
    ))


async def generate_interview_logo(
    session: AsyncSession,
    *,
    business_id: UUID,
    actor_id: UUID,
    draw: LogoDrawer | None = None,
) -> str:
    """Draw the logo the owner asked for. Returns the outcome for the job log."""
    from platform_core.services.business_interview import BusinessInterviewService
    from platform_core.services.business_settings import BusinessSettingsService

    business = await BusinessInterviewService.load_business(session, business_id)
    bp = BusinessInterviewService.read(business)
    request = _queued(bp, "logo")
    if request is None:
        return "nothing_queued"
    prompt = logo_brief(bp)
    await session.commit()  # no row lock or open transaction across the provider call
    image, reason = await (draw or (lambda p, a: generate_image(p, aspect_ratio=a, timeout_seconds=60)))(prompt, "1:1")

    business = await BusinessInterviewService.load_business(session, business_id, lock=True)
    bp = BusinessInterviewService.read(business)
    request = _queued(bp, "logo")
    if request is None:
        return "superseded"
    if any(m.role == "logo" and m.source == "USER_UPLOAD" for m in bp.media_assets):
        request.status = "failed"
        request.reason = "You uploaded your own logo, so it is used instead."
    elif image is None:
        request.status = "failed"
        request.reason = FAILURE_REASONS.get(reason, FAILURE_REASONS["error"])
    else:
        asset = await MediaService.persist_generated(
            session, business_id=business_id, actor_id=actor_id, purpose="brand",
            mime_type=image.mime_type, body=image.bytes,
            alt_text="AI-generated logo", original_filename="generated-logo.png",
        )
        await BusinessSettingsService.patch_branding(
            session, business_id=business_id, raw={"logo_asset_id": asset["id"]},
            actor_id=actor_id, correlation_id=str(uuid4()),
        )
        request.status = "ready"
        request.asset_id = UUID(asset["id"])
        bp.media_assets.append(MediaReference(asset_id=request.asset_id, role="logo",
                                              label="AI-generated logo", source="AI_GENERATED"))
        bp.logo_state = "generated"
    # Saved without a revision bump: the owner may be typing, and a logo
    # arriving is not a reason to reject their next message as stale.
    await BusinessInterviewService.save(session, business, bp)
    return str(request.status)
