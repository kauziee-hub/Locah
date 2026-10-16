"""Media asset service (Doc 12 §15).

Two-step upload, so the API never touches binary content:

    request_upload()  -> validates, pre-creates a `pending` media_assets row,
                         returns a signed upload URL
    (client PUTs the bytes straight to Supabase Storage)
    complete_upload() -> verifies the object landed, flips the row to `ready`
                         and records its public URL

**Permission model.** There is no `media.*` permission in the canonical First
Launch catalogue (Doc 12 §8.2), and inventing one would be a registry change.
Instead an upload declares a `purpose`, and each purpose maps to the permission
that already governs the thing the asset is for — the same shape as the AUD-10
payment-source fix. Adding a purpose without a permission raises, rather than
silently falling open.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.media.supabase_storage import (
    ALLOWED_MIME_TYPES,
    DOCUMENT_BUCKET,
    DOCUMENT_MIME_TYPES,
    EXTENSION_BY_MIME,
    MAX_DOCUMENT_BYTES,
    MAX_FILE_BYTES,
    create_signed_upload_url,
    object_exists,
    private_object_size,
    public_url,
)
from platform_core.models import MediaAsset
from platform_core.permissions import BUSINESS_UPDATE, OFFERINGS_UPDATE, WEBSITE_EDIT
from platform_core.services.audit import AuditService

# purpose -> the existing canonical permission that already governs it
PURPOSE_PERMISSIONS: dict[str, str] = {
    "website": WEBSITE_EDIT,
    "brand": BUSINESS_UPDATE,
    "profile": BUSINESS_UPDATE,
    "offering": OFFERINGS_UPDATE,
    # A menu, catalogue, price list or brochure the owner gives LOCAH to read.
    "document": BUSINESS_UPDATE,
}
PURPOSES = frozenset(PURPOSE_PERMISSIONS)


def _field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


class MediaService:
    @staticmethod
    def permission_for(purpose: str) -> str:
        permission = PURPOSE_PERMISSIONS.get(purpose)
        if permission is None:
            raise ValidationError(
                "Unknown upload purpose",
                details={"errors": [_field_error("purpose", "Not a supported purpose")]},
            )
        return permission

    @staticmethod
    async def request_upload(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        identity_id: uuid.UUID,
        supabase_user_id: uuid.UUID,
        user_jwt: str,
        purpose: str,
        mime_type: str,
        size_bytes: int | None = None,
        original_filename: str | None = None,
        alt_text: str | None = None,
    ) -> dict[str, Any]:
        MediaService.permission_for(purpose)

        normalized_mime = (mime_type or "").strip().lower()
        document = purpose == "document"
        allowed = DOCUMENT_MIME_TYPES if document else ALLOWED_MIME_TYPES
        if normalized_mime not in allowed:
            raise ValidationError(
                "Unsupported file type",
                details={
                    "errors": [
                        _field_error(
                            "mime_type",
                            "Attach a PDF or a photo (JPEG, PNG or WebP)" if document
                            else "Only JPEG, PNG, WebP and GIF images are accepted",
                        )
                    ]
                },
            )
        limit = MAX_DOCUMENT_BYTES if document else MAX_FILE_BYTES
        if size_bytes is not None and size_bytes > limit:
            raise ValidationError(
                "File is too large",
                details={"errors": [_field_error("size_bytes", f"Maximum size is {limit // (1024 * 1024)}MB")]},
            )

        asset_id = uuid.uuid4()
        extension = EXTENSION_BY_MIME[normalized_mime]
        # Storage RLS scopes writes to the caller's own uid prefix.
        storage_key = f"{supabase_user_id}/{asset_id}.{extension}"

        asset = MediaAsset(
            id=asset_id,
            business_id=business_id,
            uploader_identity_id=identity_id,
            original_filename=(original_filename or None),
            mime_type=normalized_mime,
            size_bytes=size_bytes,
            bucket=DOCUMENT_BUCKET if document else "media",
            storage_key=storage_key,
            alt_text=(alt_text or None),
            purpose=purpose,
            status="pending",
            source_type="owner_uploaded",
            approval_state="approved",
        )
        session.add(asset)
        await session.flush()

        signed = await create_signed_upload_url(
            user_jwt=user_jwt, bucket=asset.bucket, storage_key=storage_key
        )
        return {"asset": MediaService.serialize(asset), "upload": signed}

    @staticmethod
    async def complete_upload(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        asset_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> dict[str, Any]:
        asset = await MediaService._get(session, business_id=business_id, asset_id=asset_id)
        if asset.status == "ready":
            return MediaService.serialize(asset)

        private = asset.bucket == DOCUMENT_BUCKET
        size = await (private_object_size if private else object_exists)(
            bucket=asset.bucket, storage_key=asset.storage_key)
        if size is None:
            # Commit before raising: the router commits *after* a successful
            # call, so without this the rollback would leave the asset stuck
            # on `pending` forever. `failed` is not terminal — asking again
            # after a genuine upload re-checks and can still succeed.
            asset.status = "failed"
            await session.commit()
            raise ValidationError(
                "Upload did not complete",
                details={"errors": [_field_error("asset_id", "No stored object for this asset")]},
            )

        asset.status = "ready"
        asset.size_bytes = size or asset.size_bytes
        # A private document never gets a public URL.
        asset.public_url = None if private else public_url(asset.bucket, asset.storage_key)
        asset.updated_at = datetime.now(timezone.utc)
        await session.flush()

        await AuditService.record(
            session,
            event_type="media.asset_uploaded",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="media_asset",
            resource_id=asset.id,
            action="upload",
            after_state={
                "purpose": asset.purpose,
                "mime_type": asset.mime_type,
                "size_bytes": asset.size_bytes,
            },
        )
        return MediaService.serialize(asset)

    @staticmethod
    async def _get(
        session: AsyncSession, *, business_id: uuid.UUID, asset_id: uuid.UUID
    ) -> MediaAsset:
        result = await session.execute(
            select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.business_id == business_id,
                MediaAsset.deleted_at.is_(None),
            )
        )
        asset = result.scalars().first()
        if asset is None:
            raise ResourceNotFound("Media asset")
        return asset

    @staticmethod
    async def get(
        session: AsyncSession, *, business_id: uuid.UUID, asset_id: uuid.UUID
    ) -> dict[str, Any]:
        return MediaService.serialize(
            await MediaService._get(session, business_id=business_id, asset_id=asset_id)
        )

    @staticmethod
    async def resolve_many(
        session: AsyncSession, *, business_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> list[dict[str, Any]]:
        """This business's own ready pictures among `asset_ids`, in that order
        (each with its url and whether it is an unapproved draft LOCAH drew)."""
        if not asset_ids:
            return []
        rows = (
            await session.execute(
                select(MediaAsset).where(
                    MediaAsset.id.in_(asset_ids),
                    MediaAsset.business_id == business_id,
                    MediaAsset.status == "ready",
                    MediaAsset.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        by_id = {a.id: a for a in rows}
        return [{"id": str(i), **MediaService._resolved(by_id[i])} for i in asset_ids if i in by_id]

    @staticmethod
    async def list_for_business(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        purpose: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(MediaAsset).where(
            MediaAsset.business_id == business_id,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status == "ready",
        )
        if purpose:
            stmt = stmt.where(MediaAsset.purpose == purpose)
        stmt = stmt.order_by(MediaAsset.created_at.desc()).limit(min(limit, 200))
        result = await session.execute(stmt)
        return [MediaService.serialize(a) for a in result.scalars().all()]

    # Asset ids in section content resolve to URLs OUTSIDE `content`. Injecting
    # a url into content would break the next PATCH round-trip, because
    # validate_section_content rejects fields absent from the SectionType schema.
    ASSET_CONTENT_KEYS = ("image_asset_id", "og_image_asset_id", "logo_asset_id")
    # Lists whose rows may carry their own `image_asset_id`, resolved as
    # `assets["items.3"]` / `assets["categories.0"]`.
    NESTED_ASSET_LISTS = ("items", "categories")

    @staticmethod
    async def attach_section_asset_urls(
        session: AsyncSession,
        sections: list[dict[str, Any]],
        *,
        business_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Add `section["assets"] = {content_key: {url, alt_text, draft}}` for any asset id present.

        `business_id` scopes resolution so one Business cannot surface another's
        asset by writing its id into a section.
        """
        wanted: set[uuid.UUID] = set()
        for section in sections:
            content = section.get("content") or {}
            for key in MediaService.ASSET_CONTENT_KEYS:
                raw = content.get(key)
                if not raw:
                    continue
                try:
                    wanted.add(uuid.UUID(str(raw)))
                except ValueError:
                    continue
            for raw in (content.get("image_asset_ids") or [])[:20]:
                try:
                    wanted.add(uuid.UUID(str(raw)))
                except ValueError:
                    continue
            # Pictures inside a section's items: a category card, a product card.
            for list_key in MediaService.NESTED_ASSET_LISTS:
                for row in (content.get(list_key) or [])[:48]:
                    raw = row.get("image_asset_id") if isinstance(row, dict) else None
                    if not raw:
                        continue
                    try:
                        wanted.add(uuid.UUID(str(raw)))
                    except ValueError:
                        continue
        if not wanted:
            return sections

        stmt = select(MediaAsset).where(
            MediaAsset.id.in_(wanted),
            MediaAsset.status == "ready",
            MediaAsset.deleted_at.is_(None),
        )
        if business_id is not None:
            # A section may only resolve its own Business's assets.
            stmt = stmt.where(MediaAsset.business_id == business_id)
        result = await session.execute(stmt)
        by_id = {str(a.id): a for a in result.scalars().all()}
        for section in sections:
            content = section.get("content") or {}
            resolved: dict[str, Any] = {}
            for key in MediaService.ASSET_CONTENT_KEYS:
                asset = by_id.get(str(content.get(key) or ""))
                if asset is not None and asset.public_url:
                    resolved[key] = MediaService._resolved(asset)
            for index, raw in enumerate((content.get("image_asset_ids") or [])[:20]):
                asset = by_id.get(str(raw))
                if asset is not None and asset.public_url:
                    resolved[f"image_asset_id_{index}"] = MediaService._resolved(asset)
            for list_key in MediaService.NESTED_ASSET_LISTS:
                for index, row in enumerate((content.get(list_key) or [])[:48]):
                    raw = row.get("image_asset_id") if isinstance(row, dict) else None
                    asset = by_id.get(str(raw or ""))
                    if asset is not None and asset.public_url:
                        resolved[f"{list_key}.{index}"] = MediaService._resolved(asset)
            if resolved:
                section["assets"] = resolved
        return sections

    @staticmethod
    async def persist_generated(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        purpose: str,
        mime_type: str,
        body: bytes,
        alt_text: str | None,
        original_filename: str,
        generated_for: str | None = None,
        generation_job_id: uuid.UUID | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        """Persist platform-generated image bytes as a ready media asset.

        User uploads still use the signed-URL path. This is only for images
        the platform produced (Gemini drafts) so they follow the same
        ownership and public-URL rules as an owner upload — and carry their
        provenance: generated, for which slot, by which job and prompt version,
        and a draft until the owner approves or replaces it.
        """
        from platform_core.media.supabase_storage import (
            EXTENSION_BY_MIME,
            put_generated_object,
            public_url,
        )

        MediaService.permission_for(purpose)
        normalized_mime = (mime_type or "image/jpeg").strip().lower()
        if normalized_mime not in ALLOWED_MIME_TYPES:
            normalized_mime = "image/jpeg"
        asset_id = uuid.uuid4()
        extension = EXTENSION_BY_MIME.get(normalized_mime, "jpg")
        storage_key = f"generated/{business_id}/{asset_id}.{extension}"
        await put_generated_object(
            bucket="media",
            storage_key=storage_key,
            body=body,
            mime_type=normalized_mime,
        )
        asset = MediaAsset(
            id=asset_id,
            business_id=business_id,
            uploader_identity_id=actor_id,
            original_filename=original_filename,
            mime_type=normalized_mime,
            size_bytes=len(body),
            bucket="media",
            storage_key=storage_key,
            public_url=public_url("media", storage_key),
            alt_text=alt_text,
            purpose=purpose,
            status="ready",
            source_type="gemini_generated",
            generated_for=(generated_for or None),
            generation_job_id=generation_job_id,
            prompt_version=(prompt_version or None),
            approval_state="draft",
        )
        session.add(asset)
        await session.flush()
        await AuditService.record(
            session,
            event_type="media.asset_generated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="media_asset",
            resource_id=asset.id,
            action="generate",
            after_state={"purpose": purpose, "size_bytes": len(body)},
        )
        return MediaService.serialize(asset)

    @staticmethod
    async def persist_retrieved(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        purpose: str,
        url: str,
        page_url: str,
        mime_type: str,
        alt_text: str | None,
        credit: str,
        width: int | None = None,
        height: int | None = None,
        generated_for: str | None = None,
        generation_job_id: uuid.UUID | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        """Record a real photograph found online as a ready media asset.

        Nothing is downloaded or stored: the asset's `public_url` IS the verified
        stock URL (website.image_retrieval checked it serves an image), and the
        bucket is `external` so no storage code looks for an object. Sections
        still hold only the asset id (Doc 12 §12.6), so the renderer and the
        editor treat it like any other picture. Provenance: `stock_photo`, the
        photo's page in `storage_key`, the photographer's credit in
        `original_filename`.
        """
        from platform_core.website.image_search import url_allowed

        MediaService.permission_for(purpose)
        if not url_allowed(url):
            raise ValidationError("A found picture must be an https link on an allowed photo host")
        normalized_mime = (mime_type or "image/jpeg").strip().lower()
        if normalized_mime not in ALLOWED_MIME_TYPES:
            normalized_mime = "image/jpeg"
        asset = MediaAsset(
            id=uuid.uuid4(),
            business_id=business_id,
            uploader_identity_id=actor_id,
            original_filename=credit[:200] or None,
            mime_type=normalized_mime,
            size_bytes=None,
            width=width,
            height=height,
            bucket="external",
            storage_key=(page_url or url)[:1000],
            public_url=url,
            alt_text=alt_text,
            purpose=purpose,
            status="ready",
            source_type="stock_photo",
            generated_for=(generated_for or None),
            generation_job_id=generation_job_id,
            prompt_version=(prompt_version or None),
            approval_state="draft",
        )
        session.add(asset)
        await session.flush()
        await AuditService.record(
            session,
            event_type="media.asset_retrieved",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="media_asset",
            resource_id=asset.id,
            action="retrieve",
            after_state={"purpose": purpose, "source": "stock_photo", "slot": generated_for},
        )
        return MediaService.serialize(asset)

    @staticmethod
    async def approve_draft(
        session: AsyncSession, *, business_id: uuid.UUID, asset_id: uuid.UUID
    ) -> dict[str, Any]:
        """The owner keeps a picture LOCAH drew. It stays marked as generated."""
        asset = await MediaService._get(session, business_id=business_id, asset_id=asset_id)
        if asset.source_type not in {"gemini_generated", "stock_photo"}:
            raise ValidationError("Only a draft picture LOCAH made needs approving")
        asset.approval_state = "approved"
        await session.flush()
        return MediaService.serialize(asset)

    @staticmethod
    def _resolved(asset: MediaAsset) -> dict[str, Any]:
        # `draft`: a picture LOCAH drew that the owner has not approved yet —
        # the editor says so, and offers to replace, keep or remove it.
        return {"url": asset.public_url, "alt_text": asset.alt_text,
                "draft": getattr(asset, "source_type", None) == "gemini_generated"
                and getattr(asset, "approval_state", None) == "draft"}

    @staticmethod
    def serialize(asset: MediaAsset) -> dict[str, Any]:
        return {
            "id": str(asset.id),
            "business_id": str(asset.business_id) if asset.business_id else None,
            "purpose": asset.purpose,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "alt_text": asset.alt_text,
            "width": asset.width,
            "height": asset.height,
            "status": asset.status,
            "url": asset.public_url,
            # Provenance: never present a draft LOCAH drew as the owner's photo.
            "source_type": asset.source_type,
            "generated_for": asset.generated_for,
            "approval_state": asset.approval_state,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        }
