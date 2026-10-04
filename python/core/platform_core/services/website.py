"""Website service — provision, load, and draft assembly (Stage 2 / core-website)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from platform_core.gates import assert_business_mutable
from platform_core.models import Website, WebsitePage, WebsiteSection, WebsiteVersion
from platform_core.resolvers.website_resolver import WebsiteResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService


def normalize_page_slug(raw: str) -> str:
    """Canonicalise a generated page slug to the bare form the rest of the
    system stores and looks up (``home``, ``menu``), never a path (``/menu``).

    Generation output is model-authored, so it arrives in whichever shape the
    provider felt like emitting. The public page lookup matches on the bare
    slug, so a stored ``/menu`` is unreachable — every sub-page 404s while the
    home page survives only on the ``page_type == "home"`` fallback.
    """
    slug = raw.strip().strip("/").lower()
    return slug or "home"


class WebsiteService:
    @staticmethod
    async def provision_for_business(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> tuple[Website, WebsiteVersion]:
        """Create Website + empty draft version. Never blocks on AI (Doc 12 §12.1)."""
        existing = await session.execute(
            select(Website).where(Website.business_id == business_id)
        )
        website = existing.scalars().first()
        if website is not None:
            draft = await WebsiteResolver.resolve_draft_version(
                session, business_id=business_id, website_id=website.id
            )
            return website, draft

        website = Website(business_id=business_id, status="draft")
        session.add(website)
        await session.flush()
        from platform_core.models import Business

        business = await session.get(Business, business_id)
        name = (business.display_name if business else "") or "Welcome"

        draft = WebsiteVersion(
            website_id=website.id,
            business_id=business_id,
            version_type="draft",
            navigation=[],
            theme={},
            generated_by=None,
        )
        session.add(draft)
        await session.flush()

        home = WebsitePage(
            website_version_id=draft.id,
            business_id=business_id,
            slug="home",
            title="Home",
            page_type="home",
            seo_title=None,
            seo_description=None,
            sort_order=0,
        )
        session.add(home)
        await session.flush()
        session.add(
            WebsiteSection(
                page_id=home.id,
                business_id=business_id,
                section_type_id="hero",
                layout_variant="centered",
                # Customer-facing from the first moment: the business's own name,
                # never instructions to the owner (those live in the editor).
                content={"headline": name},
                sort_order=0,
                is_visible=True,
            )
        )
        await session.flush()
        return website, draft

    @staticmethod
    async def get_aggregate(
        session: AsyncSession, *, business_id: uuid.UUID
    ) -> dict[str, Any]:
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id
        )
        pages = await WebsiteResolver.list_pages(session, version_id=draft.id)
        page_payloads: list[dict[str, Any]] = []
        for page in pages:
            sections = await WebsiteResolver.list_sections(session, page_id=page.id)
            page_payloads.append(WebsiteResolver.serialize_page(page, sections))
        # Asset ids -> public URLs, alongside `content` (never inside it), so
        # the Workspace preview can show uploaded images.
        from platform_core.services.media import MediaService

        from platform_core.interview.media_director import image_policy

        for payload in page_payloads:
            await MediaService.attach_section_asset_urls(
                session, payload.get("sections") or [], business_id=business_id
            )
            # Which pictures each section can carry, and whether one may be
            # drawn — the editor follows this, never its own list.
            for section in payload.get("sections") or []:
                section["image_policy"] = image_policy(
                    dict(draft.theme or {}), str(section.get("section_type_id") or ""),
                    section.get("layout_variant"))
        published = None
        if website.published_version_id:
            result = await session.execute(
                select(WebsiteVersion).where(WebsiteVersion.id == website.published_version_id)
            )
            pub = result.scalars().first()
            if pub:
                published = WebsiteResolver.serialize_version(pub)
        return {
            "website": WebsiteResolver.serialize_website(website),
            "draft": {
                **WebsiteResolver.serialize_version(draft),
                "pages": page_payloads,
            },
            "published": published,
        }

    @staticmethod
    async def replace_draft_from_generation(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        website: Website,
        payload: dict[str, Any],
        generated_by: str,
        generation_job_id: uuid.UUID | None,
    ) -> WebsiteVersion:
        # Soft-replace under the partial unique index (one live draft per
        # website). Concurrent callers serialize on SELECT FOR UPDATE of the
        # live row; if both still collide on INSERT, retry rather than leave
        # the owner with a failed generation and the previous draft stuck.
        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                async with session.begin_nested():
                    return await WebsiteService._insert_live_draft(
                        session,
                        business_id=business_id,
                        website=website,
                        payload=payload,
                        generated_by=generated_by,
                        generation_job_id=generation_job_id,
                    )
            except IntegrityError as exc:
                last_error = exc
        raise last_error or RuntimeError("Could not replace the website draft")

    @staticmethod
    async def _insert_live_draft(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        website: Website,
        payload: dict[str, Any],
        generated_by: str,
        generation_job_id: uuid.UUID | None,
    ) -> WebsiteVersion:
        # Lock the current live draft (if any) so a second replacement waits
        # for this transaction instead of both inserting against the unique
        # index and both losing.
        await session.execute(
            select(WebsiteVersion.id)
            .where(
                WebsiteVersion.website_id == website.id,
                WebsiteVersion.version_type == "draft",
                WebsiteVersion.superseded_at.is_(None),
            )
            .with_for_update()
        )
        await session.execute(
            update(WebsiteVersion)
            .where(
                WebsiteVersion.website_id == website.id,
                WebsiteVersion.version_type == "draft",
                WebsiteVersion.superseded_at.is_(None),
            )
            .values(superseded_at=func.now())
        )
        draft = WebsiteVersion(
            website_id=website.id,
            business_id=business_id,
            version_type="draft",
            navigation=payload.get("navigation") or [],
            theme=payload.get("theme_hints") or {},
            generated_by=generated_by,
            generation_job_id=generation_job_id,
        )
        session.add(draft)
        await session.flush()

        for sort_order, page_data in enumerate(payload.get("pages") or []):
            page = WebsitePage(
                website_version_id=draft.id,
                business_id=business_id,
                slug=normalize_page_slug(str(page_data["slug"])),
                title=str(page_data["title"]),
                page_type=str(page_data["page_type"]),
                seo_title=page_data.get("seo_title"),
                seo_description=page_data.get("seo_description"),
                sort_order=int(page_data.get("sort_order", sort_order)),
                is_published=True,
            )
            session.add(page)
            await session.flush()
            for sec_order, section_data in enumerate(page_data.get("sections") or []):
                session.add(
                    WebsiteSection(
                        page_id=page.id,
                        business_id=business_id,
                        section_type_id=str(section_data["section_type_id"]),
                        layout_variant=section_data.get("layout_variant"),
                        content=section_data.get("content") or {},
                        module_binding=section_data.get("module_binding"),
                        sort_order=int(section_data.get("sort_order", sec_order)),
                        is_visible=bool(section_data.get("is_visible", True)),
                    )
                )
        await session.flush()
        return draft


class WebsiteVersionService:
    @staticmethod
    async def update_draft_chrome(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        navigation: list[Any] | None = None,
        theme: dict[str, Any] | None = None,
    ) -> WebsiteVersion:
        from platform_core.validation.website import assert_no_unsafe_content

        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="edit website")
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id, for_update=True
        )
        before = WebsiteResolver.serialize_version(draft)
        if navigation is not None:
            assert_no_unsafe_content(navigation, path="navigation")
            draft.navigation = navigation
            flag_modified(draft, "navigation")
        if theme is not None:
            assert_no_unsafe_content(theme, path="theme")
            draft.theme = theme
            flag_modified(draft, "theme")
        await session.flush()
        # Bump the live draft so an in-flight generation job will not clobber
        # owner edits when it later tries to soft-replace this version.
        draft.updated_at = datetime.now(timezone.utc)
        await AuditService.record(
            session,
            event_type="website.content_edited",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_version",
            resource_id=draft.id,
            action="edited",
            before_state=before,
            after_state=WebsiteResolver.serialize_version(draft),
        )
        return draft


class PageService:
    @staticmethod
    async def patch_page(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        page_id: uuid.UUID,
        actor_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> WebsitePage:
        from platform_core.validation.website import validate_page_patch

        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="edit website page")
        page = await WebsiteResolver.resolve_page(
            session, business_id=business_id, page_id=page_id
        )
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id, for_update=True
        )
        if page.website_version_id != draft.id:
            from platform_core.exceptions import ValidationError

            raise ValidationError("Only draft pages can be edited")
        validated = validate_page_patch(payload)
        before = WebsiteResolver.serialize_page(page)
        for key, value in validated.items():
            setattr(page, key, value)
        await session.flush()
        draft.updated_at = datetime.now(timezone.utc)
        await AuditService.record(
            session,
            event_type="website.content_edited",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_page",
            resource_id=page.id,
            action="edited",
            before_state=before,
            after_state=WebsiteResolver.serialize_page(page),
        )
        return page


class SectionService:
    @staticmethod
    async def patch_section(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        section_id: uuid.UUID,
        actor_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> WebsiteSection:
        from platform_core.validation.website import validate_section_content, validate_section_patch

        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="edit website section")
        section = await WebsiteResolver.resolve_section(
            session, business_id=business_id, section_id=section_id
        )
        page = await WebsiteResolver.resolve_page(
            session, business_id=business_id, page_id=section.page_id
        )
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id, for_update=True
        )
        if page.website_version_id != draft.id:
            from platform_core.exceptions import ValidationError

            raise ValidationError("Only draft sections can be edited")
        validated = validate_section_patch(payload)
        before = WebsiteResolver.serialize_section(section)
        if "content" in validated or "layout_variant" in validated:
            section_type = await WebsiteResolver.load_section_type(
                session, section.section_type_id
            )
        else:
            section_type = None
        if "layout_variant" in validated and section_type:
            allowed = list(section_type.allowed_variants or [])
            variant = validated["layout_variant"]
            if variant is not None and allowed and variant not in allowed:
                from platform_core.exceptions import ValidationError

                raise ValidationError(
                    "That layout is not one this section offers",
                    details={"code": "unknown_variant", "allowed": allowed},
                )
        if "content" in validated:
            schema = section_type.content_schema if section_type else None
            validated["content"] = validate_section_content(
                section.section_type_id, validated["content"], content_schema=schema
            )
        for key, value in validated.items():
            setattr(section, key, value)
            # JSONB replacements are not always detected as dirty without this.
            if key in {"content", "module_binding"}:
                flag_modified(section, key)
        await session.flush()
        draft.updated_at = datetime.now(timezone.utc)
        await AuditService.record(
            session,
            event_type="website.content_edited",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_section",
            resource_id=section.id,
            action="edited",
            before_state=before,
            after_state=WebsiteResolver.serialize_section(section),
        )
        return section
