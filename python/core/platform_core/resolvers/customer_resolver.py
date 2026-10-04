"""Customer lookup resolver (Stage 4)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ResourceNotFound, ResourceStateDenied
from platform_core.models import CustomerContact, CustomerNote, CustomerTimelineEntry


class CustomerResolver:
    @staticmethod
    async def resolve(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> CustomerContact:
        result = await session.execute(
            select(CustomerContact).where(
                CustomerContact.id == contact_id,
                CustomerContact.business_id == business_id,
                CustomerContact.deleted_at.is_(None),
            )
        )
        contact = result.scalars().first()
        if contact is None:
            raise ResourceNotFound("Customer")
        return contact

    @staticmethod
    async def summaries(
        session: AsyncSession, *, business_id: uuid.UUID, contact_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """The customer module's public batch read for other modules' pages:
        id -> {id, name, phone}. Erased or deleted contacts are left out."""
        if not contact_ids:
            return {}
        rows = (await session.execute(select(CustomerContact).where(
            CustomerContact.business_id == business_id, CustomerContact.id.in_(contact_ids),
            CustomerContact.deleted_at.is_(None),
        ))).scalars().all()
        return {c.id: {"id": str(c.id), "name": c.display_name, "phone": c.phone} for c in rows}

    @staticmethod
    def require_operable(contact: CustomerContact, *, action: str = "update") -> None:
        if contact.status == "archived":
            raise ResourceStateDenied(
                "customer",
                contact.status,
                action=action,
                allowed_states=["active", "blocked"],
            )

    @staticmethod
    async def resolve_operable(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
        action: str = "update",
    ) -> CustomerContact:
        contact = await CustomerResolver.resolve(
            session, business_id=business_id, contact_id=contact_id
        )
        CustomerResolver.require_operable(contact, action=action)
        return contact

    @staticmethod
    def serialize_contact(contact: CustomerContact) -> dict[str, Any]:
        return {
            "id": str(contact.id),
            "business_id": str(contact.business_id),
            "display_name": contact.display_name,
            "phone": contact.phone,
            "email": contact.email,
            "status": contact.status,
            "tags": list(contact.tags or []),
            "identity_id": str(contact.identity_id) if contact.identity_id else None,
            "preferred_location_id": (
                str(contact.preferred_location_id) if contact.preferred_location_id else None
            ),
            "customer_since": contact.customer_since.isoformat(),
            "last_interaction_at": (
                contact.last_interaction_at.isoformat() if contact.last_interaction_at else None
            ),
            "version": contact.version,
            "created_at": contact.created_at.isoformat(),
            "updated_at": contact.updated_at.isoformat(),
        }

    @staticmethod
    def serialize_note(note: CustomerNote) -> dict[str, Any]:
        return {
            "id": str(note.id),
            "contact_id": str(note.contact_id),
            "body": note.body,
            "author_identity_id": str(note.author_identity_id),
            "version": note.version,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }

    @staticmethod
    def serialize_timeline_entry(entry: CustomerTimelineEntry) -> dict[str, Any]:
        return {
            "id": str(entry.id),
            "contact_id": str(entry.contact_id),
            "activity_type": entry.activity_type,
            "resource_type": entry.resource_type,
            "resource_id": str(entry.resource_id) if entry.resource_id else None,
            "location_id": str(entry.location_id) if entry.location_id else None,
            "summary": entry.summary or {},
            "occurred_at": entry.occurred_at.isoformat(),
        }
