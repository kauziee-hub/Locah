"""Composing a website draft: adding, removing, reordering and duplicating sections.

Why this is a separate service
------------------------------
`WebsiteService.patch_section` can change what a section *says*. Nothing until
now could change what a page is *made of* — there was no way to add a section,
remove one, or move one. That is the floor the whole editing experience stands
on, and without it the Workspace could only ever be a form over a fixed layout
that generation happened to produce.

What governs it
---------------
Structure is not freehand. Every section is an instance of a platform-defined
SectionType, and this service will only ever create one of those: the id must
exist in `website_section_types`, the variant must be one the type declares, and
the content must validate against the type's own JSON schema. A prompt, a
mis-click or a bad AI response cannot introduce a section the renderer does not
know how to draw.

Capability, not decoration
--------------------------
`website_section_types.contributing_module` records which module actually feeds
a section its data. A Menu is fed by the offerings catalogue; an Enquiry form is
fed by Leads. Offering a business a section whose module is switched off would
put an empty shelf on their website and a control in Workspace that cannot
work — so `available_section_types` asks the module registry what is live and
returns only what this business can genuinely publish.

Existing sections are deliberately not policed the same way. A business that
turns Leads off should not have its enquiry form silently deleted; the renderer
already declines to draw what has no data behind it, and the owner keeps the
choice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.gates import assert_business_mutable
from platform_core.models import (
    BusinessModuleState,
    WebsitePage,
    WebsiteSection,
    WebsiteSectionType,
)
from platform_core.resolvers.website_resolver import WebsiteResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService

# A page with more sections than this is not a page any more. The cap exists so
# a runaway loop or a careless AI response cannot produce something unrenderable.
MAX_SECTIONS_PER_PAGE = 40

ACTIVE_MODULE_STATES = frozenset({"enabled", "ready", "active"})


class WebsiteCompositionService:
    # ------------------------------------------------------------- reading

    @staticmethod
    async def _active_modules(session: AsyncSession, business_id: uuid.UUID) -> set[str]:
        """Switched on AND entitled. A stale activation row without an
        Entitlement contributes nothing to the website (Doc 08 §20.2).

        Setup completeness is deliberately not required: an owner may place a
        Menu before the first item exists. Until the module is ready the
        section is a placeholder in the preview and absent from the live site
        (WebsitePublishService.load_public_page, Doc 12 §11.9)."""
        from platform_core.services.entitlement import EntitlementService

        rows = await session.execute(
            select(BusinessModuleState.module_id, BusinessModuleState.activation_state).where(
                BusinessModuleState.business_id == business_id
            )
        )
        switched_on = {row[0] for row in rows.all() if row[1] in ACTIVE_MODULE_STATES}
        entitlements = await EntitlementService.get_effective(session, business_id)
        return {m for m in switched_on if entitlements.is_entitled(m)}

    @staticmethod
    async def active_modules(session: AsyncSession, *, business_id: uuid.UUID) -> set[str]:
        """What this business has switched on.

        Public because generation needs the same answer this service gives when
        it refuses a hand-added section. Two rules that must agree are best
        served by one rule.
        """
        return await WebsiteCompositionService._active_modules(session, business_id)

    @staticmethod
    async def available_section_types(
        session: AsyncSession, *, business_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """What this business may add to a page, and what it may not — with the reason.

        Unavailable types are returned rather than hidden. An owner who wonders
        why their site has no Menu is better served by "turn on the offerings
        catalogue" than by a control that silently does not exist.
        """
        active = await WebsiteCompositionService._active_modules(session, business_id)
        rows = (
            (
                await session.execute(
                    select(WebsiteSectionType).order_by(
                        WebsiteSectionType.sort_order.asc(), WebsiteSectionType.id.asc()
                    )
                )
            )
            .scalars()
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            needed = row.contributing_module or row.requires_module
            available = needed is None or needed in active
            out.append(
                {
                    "id": row.id,
                    "label": row.label,
                    "description": row.description,
                    "allowed_variants": list(row.allowed_variants or []),
                    "requires_module": needed,
                    "available": available,
                    "unavailable_reason": None if available else "module_not_active",
                }
            )
        return out

    # -------------------------------------------------------------- writing

    @staticmethod
    async def _draft_page(
        session: AsyncSession, *, business_id: uuid.UUID, page_id: uuid.UUID
    ) -> WebsitePage:
        """Resolve a page that belongs to the editable draft.

        A published version is what customers are reading right now. Structure is
        changed on the draft and becomes public at publish, never before.
        """
        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="edit website structure")
        page = await WebsiteResolver.resolve_page(
            session, business_id=business_id, page_id=page_id
        )
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id, for_update=True
        )
        if page.website_version_id != draft.id:
            raise ValidationError(
                "Only the draft can be edited",
                details={"code": "not_draft"},
            )
        draft.updated_at = datetime.now(timezone.utc)
        return page

    @staticmethod
    async def _sections_for_page(
        session: AsyncSession, page_id: uuid.UUID
    ) -> list[WebsiteSection]:
        return list(
            (
                await session.execute(
                    select(WebsiteSection)
                    .where(WebsiteSection.page_id == page_id)
                    .order_by(WebsiteSection.sort_order.asc())
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def add_section(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        page_id: uuid.UUID,
        actor_id: uuid.UUID,
        section_type_id: str,
        content: dict[str, Any] | None = None,
        layout_variant: str | None = None,
        position: int | None = None,
    ) -> WebsiteSection:
        from platform_core.validation.website import validate_section_content

        page = await WebsiteCompositionService._draft_page(
            session, business_id=business_id, page_id=page_id
        )

        section_type = await WebsiteResolver.load_section_type(session, section_type_id)
        if section_type is None:
            raise ResourceNotFound("Section type")

        needed = section_type.contributing_module or section_type.requires_module
        if needed is not None:
            active = await WebsiteCompositionService._active_modules(session, business_id)
            if needed not in active:
                raise ValidationError(
                    f"{section_type.label} needs the {needed} module to be active",
                    details={"code": "module_not_active", "module_id": needed},
                )

        allowed = list(section_type.allowed_variants or [])
        variant = layout_variant or (allowed[0] if allowed else None)
        if variant is not None and allowed and variant not in allowed:
            raise ValidationError(
                "That layout is not one this section offers",
                details={"code": "unknown_variant", "allowed": allowed},
            )

        validated = validate_section_content(
            section_type_id,
            content or {},
            content_schema=section_type.content_schema,
        )

        existing = await WebsiteCompositionService._sections_for_page(session, page.id)
        if len(existing) >= MAX_SECTIONS_PER_PAGE:
            raise ValidationError(
                "This page already has as many sections as it can hold",
                details={"code": "page_full", "max": MAX_SECTIONS_PER_PAGE},
            )

        # `position` is an index among the sections a person can see, not a raw
        # sort_order — the editor knows "third from the top", not the numbering.
        index = len(existing) if position is None else max(0, min(int(position), len(existing)))
        section = WebsiteSection(
            business_id=business_id,
            page_id=page.id,
            section_type_id=section_type_id,
            layout_variant=variant,
            content=validated,
            # Doc 12 §11.1/§11.9: which module's public read contract fills it.
            module_binding={"module": needed} if needed else None,
            is_visible=True,
            sort_order=index,
        )
        session.add(section)
        ordered = existing[:index] + [section] + existing[index:]
        WebsiteCompositionService._renumber(ordered)
        await session.flush()

        await AuditService.record(
            session,
            event_type="website.section_added",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_section",
            resource_id=section.id,
            action="added",
            after_state={
                "section_type_id": section_type_id,
                "page_id": str(page.id),
                "position": index,
            },
        )
        return section

    @staticmethod
    async def remove_section(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        section_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> uuid.UUID:
        section = await WebsiteResolver.resolve_section(
            session, business_id=business_id, section_id=section_id
        )
        page = await WebsiteCompositionService._draft_page(
            session, business_id=business_id, page_id=section.page_id
        )
        before = WebsiteResolver.serialize_section(section)

        remaining = [
            s
            for s in await WebsiteCompositionService._sections_for_page(session, page.id)
            if s.id != section.id
        ]
        await session.delete(section)
        WebsiteCompositionService._renumber(remaining)
        await session.flush()

        await AuditService.record(
            session,
            event_type="website.section_removed",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_section",
            resource_id=section_id,
            action="removed",
            before_state=before,
        )
        return uuid.UUID(str(page.id))

    @staticmethod
    async def duplicate_section(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        section_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> WebsiteSection:
        """Copy a section, placed directly beneath the original.

        Duplicating is how somebody builds a page of three similar blocks
        without retyping the shape of each one. The copy takes the original's
        content wholesale — including its image references, which are assets of
        the same business and so are simply pointed at twice.
        """
        source = await WebsiteResolver.resolve_section(
            session, business_id=business_id, section_id=section_id
        )
        page = await WebsiteCompositionService._draft_page(
            session, business_id=business_id, page_id=source.page_id
        )

        existing = await WebsiteCompositionService._sections_for_page(session, page.id)
        if len(existing) >= MAX_SECTIONS_PER_PAGE:
            raise ValidationError(
                "This page already has as many sections as it can hold",
                details={"code": "page_full", "max": MAX_SECTIONS_PER_PAGE},
            )

        copy = WebsiteSection(
            business_id=business_id,
            page_id=page.id,
            section_type_id=source.section_type_id,
            layout_variant=source.layout_variant,
            content=dict(source.content or {}),
            module_binding=dict(source.module_binding) if source.module_binding else None,
            is_visible=source.is_visible,
            sort_order=source.sort_order + 1,
        )
        session.add(copy)
        index = next((i for i, s in enumerate(existing) if s.id == source.id), len(existing) - 1)
        ordered = existing[: index + 1] + [copy] + existing[index + 1 :]
        WebsiteCompositionService._renumber(ordered)
        await session.flush()

        await AuditService.record(
            session,
            event_type="website.section_added",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_section",
            resource_id=copy.id,
            action="duplicated",
            after_state={"from_section_id": str(source.id), "page_id": str(page.id)},
        )
        return copy

    @staticmethod
    async def reorder_sections(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        page_id: uuid.UUID,
        actor_id: uuid.UUID,
        section_ids: list[uuid.UUID],
    ) -> list[WebsiteSection]:
        """Set the order of a page from a complete list of its sections.

        The caller sends the whole order rather than "move this one up". A drag
        produces a new arrangement, and sending that arrangement is both what the
        editor already knows and the only form that cannot half-apply: the list
        must name every section on the page exactly once, or nothing moves.
        """
        page = await WebsiteCompositionService._draft_page(
            session, business_id=business_id, page_id=page_id
        )
        existing = await WebsiteCompositionService._sections_for_page(session, page.id)
        by_id = {s.id: s for s in existing}

        if len(section_ids) != len(existing) or set(section_ids) != set(by_id):
            raise ValidationError(
                "The new order must list every section on this page exactly once",
                details={
                    "code": "incomplete_order",
                    "expected": len(existing),
                    "received": len(section_ids),
                },
            )

        before = [str(s.id) for s in existing]
        ordered = [by_id[sid] for sid in section_ids]
        WebsiteCompositionService._renumber(ordered)
        await session.flush()

        await AuditService.record(
            session,
            event_type="website.sections_reordered",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website_page",
            resource_id=page.id,
            action="reordered",
            before_state={"order": before},
            after_state={"order": [str(s.id) for s in ordered]},
        )
        return ordered

    @staticmethod
    def _renumber(sections: list[WebsiteSection]) -> None:
        """Rewrite sort_order as a dense 0..n-1 run.

        Gaps and ties are what make a list render in an order nobody chose, so
        the sequence is normalised on every structural change rather than
        patched incrementally.
        """
        for index, section in enumerate(sections):
            if section.sort_order != index:
                section.sort_order = index
                flag_modified(section, "sort_order")


class WebsiteTemplateService:
    """Choosing a template, and applying it to the draft.

    A template enters the website through exactly the same door a generated site
    does — `replace_draft_from_generation` — so both are validated the same way,
    versioned the same way, and produce the same editable draft. There is one
    website pipeline with two entrances, not two pipelines.
    """

    @staticmethod
    async def list_for_business(
        session: AsyncSession, *, business_id: uuid.UUID
    ) -> dict[str, Any]:
        from platform_core.website.generation_plan import select_template
        from platform_core.website.template_registry import templates_for_business_type

        business = await BusinessService.get_by_id(session, business_id)
        active = await WebsiteCompositionService._active_modules(session, business_id)
        ranked = templates_for_business_type(business.business_type)
        # The same choice generation makes, so the picker's "suits your
        # business" and the site the AI actually builds never disagree. It also
        # stops the card that says "suits your business" being the same card
        # that says "needs Offerings turned on first".
        recommended, _reason = select_template(
            business_type=business.business_type, active_modules=active
        )

        out: list[dict[str, Any]] = []
        for template in ranked:
            missing = tuple(m for m in template.required_modules if m not in active)
            out.append(template.serialize(available=not missing, missing=missing))
        return {
            "templates": out,
            "recommended_template_id": recommended.id,
            "business_type": business.business_type,
        }

    @staticmethod
    async def apply(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        template_id: str,
        actor_id: uuid.UUID,
    ) -> Any:
        """Replace the draft with a template's composition.

        This discards the current draft, which is the honest meaning of
        "choose this template instead". The published site is untouched — a
        business that has already published keeps serving what it published
        until it publishes again.
        """
        from platform_core.services.website import WebsiteService
        from platform_core.validation.website import validate_generation_payload
        from platform_core.website.template_registry import (
            TEMPLATES_BY_ID,
            template_to_generation_payload,
        )

        template = TEMPLATES_BY_ID.get(template_id)
        if template is None:
            raise ResourceNotFound("Website template")

        business = await BusinessService.get_by_id(session, business_id)
        assert_business_mutable(business.state, action="apply website template")

        active = await WebsiteCompositionService._active_modules(session, business_id)
        missing = [m for m in template.required_modules if m not in active]
        if missing:
            raise ValidationError(
                f"{template.name} needs {', '.join(missing)} before it is worth using",
                details={"code": "module_not_active", "missing_modules": missing},
            )

        # The description lives on the Business Profile, which is also where
        # generation reads it from — a template fills its copy from the same
        # facts the AI would, so neither invents anything the owner did not say.
        from platform_core.models import BusinessProfile

        profile = (
            (
                await session.execute(
                    select(BusinessProfile).where(BusinessProfile.business_id == business_id)
                )
            )
            .scalars()
            .first()
        )
        description = None
        if profile is not None:
            description = profile.description or profile.tagline

        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        # Deliberately NOT put through the capability fence that generation
        # uses. A template whose own `required_modules` are missing was already
        # refused above; what remains is a composition the owner looked at in
        # the picker and chose. Dropping a section from it would break that
        # preview's promise, and would cost the owner something for nothing: a
        # list section with no records renders as nothing at all on the public
        # site, and fills itself in the moment the module is switched on.
        #
        # Generation is the opposite case and is fenced, because there the
        # model picks the sections, nobody previewed them, and it writes hero
        # and CTA copy that refers to them.
        payload = validate_generation_payload(
            template_to_generation_payload(
                template,
                business_name=business.display_name,
                description=description,
            )
        )
        version = await WebsiteService.replace_draft_from_generation(
            session,
            business_id=business_id,
            website=website,
            payload=payload,
            generated_by=f"template:{template.id}",
            generation_job_id=None,
        )

        await AuditService.record(
            session,
            event_type="website.template_applied",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="website",
            resource_id=website.id,
            action="template_applied",
            after_state={"template_id": template.id, "version_id": str(version.id)},
        )
        return version
