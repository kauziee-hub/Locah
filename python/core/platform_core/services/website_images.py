"""Fill missing Website/Offering images after structured generation.

Runs as `media.generate_website_images` (off unless AUTO_GENERATE_WEBSITE_IMAGES=1)
and backs the editor's "Generate a picture". Never writes an external URL into
section content. Every prompt comes from the site's own shoot brief
(media_director.section_image_prompt), so an editor picture matches the rest of
the site. If the image provider or Storage is unavailable, the draft stays as
it is — the renderer already handles a missing picture.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.logging import get_logger
from platform_core.models import Business, BusinessProfile, Offering, WebsitePage, WebsiteSection, WebsiteVersion
from platform_core.services.media import MediaService
from platform_core.interview.media_director import REAL_PHOTO_MESSAGE, image_policy, section_image_prompt
from platform_core.website.media_prompts import PROMPT_VERSION
from platform_core.website.image_generation import generate_image_bytes

_log = get_logger("website.images")
_MAX_OFFERING_IMAGES = 6


class WebsiteImageService:
    @staticmethod
    async def fill_missing(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        business = await session.get(Business, business_id)
        if business is None:
            return {"ok": False, "reason": "business_missing"}
        profile = (
            await session.execute(
                select(BusinessProfile).where(BusinessProfile.business_id == business_id)
            )
        ).scalars().first()
        display_name = business.display_name
        business_type = business.business_type
        description = profile.description if profile else None

        hero = await WebsiteImageService._fill_hero(
            session,
            business_id=business_id,
            actor_id=actor_id,
            display_name=display_name,
            business_type=business_type,
            description=description,
        )
        offerings = await WebsiteImageService._fill_offerings(
            session,
            business_id=business_id,
            actor_id=actor_id,
            display_name=display_name,
            business_type=business_type,
        )
        _log.info(
            "website.images.filled",
            business_id=str(business_id),
            correlation_id=correlation_id,
            hero=hero,
            offerings=offerings,
        )
        return {"ok": True, "hero": hero, "offerings": offerings}

    @staticmethod
    async def _theme_of(session: AsyncSession, section: WebsiteSection) -> dict[str, Any]:
        """The theme of the draft this section belongs to (its creative direction)."""
        page = await session.get(WebsitePage, section.page_id)
        version = await session.get(WebsiteVersion, page.website_version_id) if page else None
        return dict(version.theme or {}) if version else {}

    @staticmethod
    async def generate_section_image(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        section_id: uuid.UUID,
        list_key: str | None = None,
        index: int | None = None,
    ) -> dict[str, Any]:
        """Draw one picture for a section — its own, or one card's (`list_key`, `index`).

        Only where `image_policy` says a drawn picture is honest; a factual slot
        (a named project, real work, a gallery) answers `needs_real_photo`.
        """
        business = await session.get(Business, business_id)
        if business is None:
            return {"ok": False, "reason": "business_missing"}
        section = await session.get(WebsiteSection, section_id)
        # Tenant isolation: only this business's own sections.
        if section is None or section.business_id != business_id:
            return {"ok": False, "reason": "section_missing"}
        theme = await WebsiteImageService._theme_of(session, section)
        policy = image_policy(theme, section.section_type_id, section.layout_variant)
        content = dict(section.content or {})
        subject = ""
        row: dict[str, Any] | None = None
        if list_key is not None:
            rows = content.get(list_key)
            if (list_key not in MediaService.NESTED_ASSET_LISTS or not isinstance(rows, list) or index is None
                    or not 0 <= index < len(rows) or not isinstance(rows[index], dict)):
                return {"ok": False, "reason": "item_missing"}
            row = dict(rows[index])
            subject = str(row.get("name") or "")[:120]
            wanted = policy.get("items")
        else:
            wanted = policy.get("self")
        if wanted is None:
            return {"ok": False, "reason": "no_picture_here"}
        planned = section_image_prompt(theme, section.section_type_id, _trade(business), subject=subject) \
            if wanted == "draw" else None
        if planned is None:
            return {"ok": False, "reason": "needs_real_photo", "detail": REAL_PHOTO_MESSAGE}
        prompt, aspect = planned
        generated = await generate_image_bytes(prompt, aspect_ratio=aspect)
        if generated is None:
            return {
                "ok": False,
                "reason": "generation_unavailable",
                "detail": "Image generation did not return a picture. You can upload one instead.",
            }
        slot = f"editor:{section.section_type_id}" + (f":{list_key}.{index}" if list_key is not None else "")
        asset = await MediaService.persist_generated(
            session,
            business_id=business_id,
            actor_id=actor_id,
            purpose="website",
            mime_type=generated.mime_type,
            body=generated.bytes,
            alt_text=f"Illustrative picture: {subject}"[:200] if subject else "Illustrative picture",
            original_filename="generated-section.png",
            generated_for=slot,
            prompt_version=PROMPT_VERSION,
        )
        if row is not None and list_key is not None and index is not None:
            row["image_asset_id"] = asset["id"]
            rows = list(content[list_key])
            rows[index] = row
            content[list_key] = rows
        else:
            content["image_asset_id"] = asset["id"]
        section.content = content
        flag_modified(section, "content")
        await session.flush()
        return {"ok": True, "asset": asset}

    @staticmethod
    async def _fill_hero(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        display_name: str,
        business_type: str | None,
        description: str | None,
    ) -> str:
        draft = (
            await session.execute(
                select(WebsiteVersion).where(
                    WebsiteVersion.business_id == business_id,
                    WebsiteVersion.version_type == "draft",
                    WebsiteVersion.superseded_at.is_(None),
                )
            )
        ).scalars().first()
        if draft is None:
            return "no_draft"
        sections = (
            await session.execute(
                select(WebsiteSection)
                .join(WebsitePage, WebsitePage.id == WebsiteSection.page_id)
                .where(
                    WebsitePage.website_version_id == draft.id,
                    WebsiteSection.section_type_id.in_(("hero", "about")),
                )
            )
        ).scalars().all()
        target = None
        for section in sections:
            content = section.content or {}
            if not content.get("image_asset_id"):
                target = section
                break
        if target is None:
            return "already_present"
        del display_name, description
        planned = section_image_prompt(draft.theme or {}, target.section_type_id, business_type or "")
        if planned is None:
            return "needs_real_photo"
        generated = await generate_image_bytes(planned[0], aspect_ratio=planned[1])
        if generated is None:
            return "generation_failed"
        try:
            asset = await MediaService.persist_generated(
                session,
                business_id=business_id,
                actor_id=actor_id,
                purpose="website",
                mime_type=generated.mime_type,
                body=generated.bytes,
                alt_text="Illustrative picture",
                original_filename="generated-section.png",
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("website.images.hero_persist_failed", error=str(exc)[:300])
            return "persist_failed"
        content = dict(target.content or {})
        content["image_asset_id"] = asset["id"]
        target.content = content
        flag_modified(target, "content")
        await session.flush()
        return "generated"

    @staticmethod
    async def _fill_offerings(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        display_name: str,
        business_type: str | None,
    ) -> dict[str, int]:
        rows = (
            await session.execute(
                select(Offering).where(
                    Offering.business_id == business_id,
                    Offering.deleted_at.is_(None),
                    Offering.status != "archived",
                )
            )
        ).scalars().all()
        generated_count = 0
        skipped = 0
        failed = 0
        del display_name
        draft = (
            await session.execute(
                select(WebsiteVersion).where(
                    WebsiteVersion.business_id == business_id,
                    WebsiteVersion.version_type == "draft",
                    WebsiteVersion.superseded_at.is_(None),
                )
            )
        ).scalars().first()
        theme = dict(draft.theme or {}) if draft else {}
        for offering in rows:
            if generated_count >= _MAX_OFFERING_IMAGES:
                skipped += 1
                continue
            existing = list(offering.image_asset_ids or [])
            if existing:
                skipped += 1
                continue
            drawn = await WebsiteImageService._draw_offering(
                session, business_id=business_id, actor_id=actor_id, theme=theme,
                business_type=business_type, offering=offering)
            if not drawn["ok"]:
                # a project or a piece of work needs a real photo; anything else failed
                if drawn["reason"] == "needs_real_photo":
                    skipped += 1
                else:
                    failed += 1
                continue
            offering.image_asset_ids = [uuid.UUID(drawn["asset"]["id"])]
            flag_modified(offering, "image_asset_ids")
            generated_count += 1
        await session.flush()
        return {"generated": generated_count, "skipped": skipped, "failed": failed}

    @staticmethod
    async def _draw_offering(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        theme: dict[str, Any],
        business_type: str | None,
        offering: Offering,
    ) -> dict[str, Any]:
        """One illustrative picture of one real offering, stored as a draft media
        asset the owner can keep, replace or remove. The subject is the
        offering's own title — never an invented detail."""
        planned = section_image_prompt(theme, "product_showcase", business_type or "", subject=offering.title)
        if planned is None:
            return {"ok": False, "reason": "needs_real_photo", "detail": REAL_PHOTO_MESSAGE}
        generated = await generate_image_bytes(planned[0], aspect_ratio=planned[1])
        if generated is None:
            return {"ok": False, "reason": "generation_unavailable",
                    "detail": "Image generation did not return a picture. You can upload one instead."}
        try:
            asset = await MediaService.persist_generated(
                session,
                business_id=business_id,
                actor_id=actor_id,
                purpose="offering",
                mime_type=generated.mime_type,
                body=generated.bytes,
                alt_text=f"Illustrative picture: {offering.title}"[:200],
                original_filename=f"generated-{offering.id}.jpg",
                generated_for=f"offering:{offering.id}",
                prompt_version=PROMPT_VERSION,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("website.images.offering_persist_failed", error=str(exc)[:300])
            return {"ok": False, "reason": "persist_failed",
                    "detail": "The picture could not be saved. You can upload one instead."}
        return {"ok": True, "asset": asset}

    @staticmethod
    async def generate_offering_image(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        offering_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        """The owner's "Draw a picture" for one offering. The new picture goes
        first; earlier pictures are kept. Saved through the catalogue's own
        update (version, audit, `offering.updated`), so the website and
        Marketplace refresh like after any other edit."""
        from platform_core.services.offering import OfferingService

        business = await session.get(Business, business_id)
        offering = await session.get(Offering, offering_id)
        if business is None or offering is None or offering.business_id != business_id                 or offering.deleted_at is not None:
            return {"ok": False, "reason": "offering_missing"}
        draft = (
            await session.execute(
                select(WebsiteVersion).where(
                    WebsiteVersion.business_id == business_id,
                    WebsiteVersion.version_type == "draft",
                    WebsiteVersion.superseded_at.is_(None),
                )
            )
        ).scalars().first()
        drawn = await WebsiteImageService._draw_offering(
            session, business_id=business_id, actor_id=actor_id, theme=dict(draft.theme or {}) if draft else {},
            business_type=business.business_type, offering=offering)
        if not drawn["ok"]:
            return drawn
        new_id = uuid.UUID(drawn["asset"]["id"])
        await OfferingService.patch_offering(
            session, business_id=business_id, offering_id=offering_id, actor_id=actor_id,
            correlation_id=correlation_id,
            payload={"image_asset_ids": [new_id, *[a for a in (offering.image_asset_ids or []) if a != new_id]]})
        return drawn


def _trade(business: Business) -> str:
    return (business.business_type or "a small local business").replace("_", " ")

