"""Customer domain service (Stage 4)."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, ResourceNotFound, ResourceStateDenied, ValidationError
from platform_core.gates import assert_business_mutable
from platform_core.models import CustomerContact
from platform_core.resolvers.customer_resolver import CustomerResolver
from platform_core.resolvers.location_resolver import LocationResolver
from platform_core.services.audit import AuditService
from platform_core.services.business import BusinessService
from platform_core.services.customer_timeline import CustomerTimelineService
from platform_core.services.outbox import OutboxService
from platform_core.validation.customer import (
    validate_customer_create_payload,
    validate_customer_patch_payload,
)


class CustomerService:
    @staticmethod
    def serialize_contact(contact: CustomerContact) -> dict[str, Any]:
        return cast(dict[str, Any], CustomerResolver.serialize_contact(contact))

    @staticmethod
    def _check_version(contact: CustomerContact, expected_version: int | None) -> None:
        if expected_version is None:
            return
        if contact.version != expected_version:
            raise ConflictError(
                "Stale customer version",
                details={
                    "expected_version": expected_version,
                    "current_version": contact.version,
                },
            )

    @staticmethod
    async def _publish(
        session: AsyncSession,
        *,
        event_type: str,
        audit_action: str,
        business_id: uuid.UUID,
        contact: CustomerContact,
        actor_id: uuid.UUID,
        correlation_id: str,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any],
        extra_payload: dict[str, Any] | None = None,
        actor_context: str = "business",
    ) -> None:
        payload: dict[str, Any] = {
            "business_id": str(business_id),
            "customer_id": str(contact.id),
            "version": contact.version,
            "after": after_state,
        }
        if extra_payload:
            payload.update(extra_payload)
        if contact.phone:
            payload.setdefault("phone", contact.phone)
        await OutboxService.publish(
            session,
            event_type=event_type,
            payload=payload,
            business_id=business_id,
            correlation_id=correlation_id,
        )
        await AuditService.record(
            session,
            event_type=event_type,
            actor_identity_id=actor_id,
            actor_context=actor_context,
            business_id=business_id,
            resource_type="customer",
            resource_id=contact.id,
            action=audit_action,
            before_state=before_state,
            after_state=after_state,
        )

    @staticmethod
    async def _assert_unique_contact(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        phone: str | None,
        email: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        if phone:
            query = select(CustomerContact.id).where(
                CustomerContact.business_id == business_id,
                CustomerContact.phone == phone,
                CustomerContact.deleted_at.is_(None),
            )
            if exclude_id:
                query = query.where(CustomerContact.id != exclude_id)
            if (await session.execute(query)).scalars().first():
                raise ConflictError(
                    "Customer with this phone already exists",
                    details={"phone": phone},
                )
        if email:
            query = select(CustomerContact.id).where(
                CustomerContact.business_id == business_id,
                CustomerContact.email == email,
                CustomerContact.deleted_at.is_(None),
            )
            if exclude_id:
                query = query.where(CustomerContact.id != exclude_id)
            if (await session.execute(query)).scalars().first():
                raise ConflictError(
                    "Customer with this email already exists",
                    details={"email": email},
                )

    @staticmethod
    async def list_for_business(
        session: AsyncSession,
        business_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        location_id: uuid.UUID | None = None,
        tag: str | None = None,
    ) -> list[CustomerContact]:
        query = select(CustomerContact).where(
            CustomerContact.business_id == business_id,
            CustomerContact.deleted_at.is_(None),
        )
        if status is not None:
            query = query.where(CustomerContact.status == status)
        if location_id is not None:
            query = query.where(CustomerContact.preferred_location_id == location_id)
        if tag:
            query = query.where(CustomerContact.tags.any(" ".join(tag.split()).lower()))
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    CustomerContact.display_name.ilike(term),
                    CustomerContact.phone.ilike(term),
                    CustomerContact.email.ilike(term),
                )
            )
        query = query.order_by(CustomerContact.display_name)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        try:
            contact = await CustomerResolver.resolve(
                session, business_id=business_id, contact_id=contact_id
            )
        except ResourceNotFound:
            return None
        return cast(dict[str, Any] | None, CustomerResolver.serialize_contact(contact))

    @staticmethod
    async def find_or_create_contact(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        correlation_id: str,
        actor_id: uuid.UUID,
        display_name: str,
        email: str | None,
        phone: str | None,
        actor_context: str = "business",
    ) -> CustomerContact:
        """Resolve an existing contact by email/phone within the business, or
        create one. Used by guest checkout/booking — never sets identity_id."""
        base = select(CustomerContact).where(
            CustomerContact.business_id == business_id,
            CustomerContact.deleted_at.is_(None),
        )
        for column, value in (
            (CustomerContact.email, email),
            (CustomerContact.phone, phone),
        ):
            if value:
                # Matching looks at the whole book, even for a member limited to their assignments.
                found = (
                    await session.execute(base.where(column == value).execution_options(skip_assignment_scope=True))
                ).scalars().first()
                if found is not None:
                    return found
        return await CustomerService.create_customer(
            session,
            business_id=business_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            actor_context=actor_context,
            payload={
                "display_name": display_name,
                "email": email,
                "phone": phone,
                "identity_id": None,
            },
        )

    @staticmethod
    async def create_customer(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        actor_context: str = "business",
    ) -> CustomerContact:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="create_customer")

        validated = validate_customer_create_payload(payload)
        if validated["preferred_location_id"]:
            await LocationResolver.resolve_active(
                session,
                business_id=business_id,
                location_id=validated["preferred_location_id"],
                action="set_preferred_location",
            )

        await CustomerService._assert_unique_contact(
            session,
            business_id=business_id,
            phone=validated["phone"],
            email=validated["email"],
        )

        contact = CustomerContact(
            business_id=business_id,
            display_name=validated["display_name"],
            phone=validated["phone"],
            email=validated["email"],
            status=validated["status"],
            tags=validated["tags"],
            identity_id=validated["identity_id"],
            preferred_location_id=validated["preferred_location_id"],
        )
        session.add(contact)
        await session.flush()

        await CustomerTimelineService.record_entry(
            session,
            business_id=business_id,
            contact_id=contact.id,
            activity_type="customer.registered",
            summary={"display_name": contact.display_name},
        )

        after = CustomerResolver.serialize_contact(contact)
        await CustomerService._publish(
            session,
            event_type="customer.created",
            audit_action="create",
            business_id=business_id,
            contact=contact,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=None,
            after_state=after,
            actor_context=actor_context,
        )
        if contact.tags:
            await CustomerService._publish(
                session,
                event_type="customer.tagged",
                audit_action="tag",
                business_id=business_id,
                contact=contact,
                actor_id=actor_id,
                correlation_id=correlation_id,
                before_state=None,
                after_state=after,
                extra_payload={"tags": contact.tags},
                actor_context=actor_context,
            )
        return contact

    @staticmethod
    async def update_customer(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> CustomerContact:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="update_customer")

        contact = await CustomerResolver.resolve_operable(
            session, business_id=business_id, contact_id=contact_id
        )
        CustomerService._check_version(contact, expected_version)

        patch = validate_customer_patch_payload(payload)
        if not patch:
            return contact

        if patch.get("preferred_location_id"):
            await LocationResolver.resolve_active(
                session,
                business_id=business_id,
                location_id=patch["preferred_location_id"],
                action="set_preferred_location",
            )

        new_phone = patch.get("phone", contact.phone)
        new_email = patch.get("email", contact.email)
        if not new_phone and not new_email:
            raise ValidationError(
                "Customer requires at least one contact method",
                details={
                    "errors": [
                        {"field": "phone", "message": "Provide phone or email"},
                        {"field": "email", "message": "Provide phone or email"},
                    ]
                },
            )

        if "phone" in patch or "email" in patch:
            await CustomerService._assert_unique_contact(
                session,
                business_id=business_id,
                phone=patch.get("phone", contact.phone),
                email=patch.get("email", contact.email),
                exclude_id=contact.id,
            )

        before = CustomerResolver.serialize_contact(contact)
        old_tags = list(contact.tags or [])
        for key, value in patch.items():
            setattr(contact, key, value)
        contact.version += 1
        await session.flush()

        after = CustomerResolver.serialize_contact(contact)
        await CustomerService._publish(
            session,
            event_type="customer.updated",
            audit_action="update",
            business_id=business_id,
            contact=contact,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
            extra_payload={"changed_fields": sorted(patch.keys())},
        )
        if "tags" in patch and list(contact.tags or []) != old_tags:
            await CustomerService._publish(
                session,
                event_type="customer.tagged",
                audit_action="tag",
                business_id=business_id,
                contact=contact,
                actor_id=actor_id,
                correlation_id=correlation_id,
                before_state={"tags": old_tags},
                after_state={"tags": list(contact.tags or [])},
                extra_payload={"tags": list(contact.tags or [])},
            )
        return contact

    @staticmethod
    async def block_customer(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        expected_version: int | None = None,
    ) -> CustomerContact:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="block_customer")

        contact = await CustomerResolver.resolve_operable(
            session, business_id=business_id, contact_id=contact_id, action="block"
        )
        CustomerService._check_version(contact, expected_version)

        if contact.status == "blocked":
            return contact

        before = CustomerResolver.serialize_contact(contact)
        contact.status = "blocked"
        contact.version += 1
        await session.flush()

        after = CustomerResolver.serialize_contact(contact)
        await CustomerService._publish(
            session,
            event_type="customer.blocked",
            audit_action="block",
            business_id=business_id,
            contact=contact,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
        )
        return contact

    @staticmethod
    async def archive_customer(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        expected_version: int | None = None,
    ) -> CustomerContact:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="archive_customer")

        contact = await CustomerResolver.resolve(
            session, business_id=business_id, contact_id=contact_id
        )
        CustomerService._check_version(contact, expected_version)

        if contact.status == "archived":
            return contact

        before = CustomerResolver.serialize_contact(contact)
        contact.status = "archived"
        contact.version += 1
        await session.flush()

        after = CustomerResolver.serialize_contact(contact)
        await CustomerService._publish(
            session,
            event_type="customer.archived",
            audit_action="archive",
            business_id=business_id,
            contact=contact,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
        )
        return contact

    @staticmethod
    async def restore_customer(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        contact_id: uuid.UUID,
        actor_id: uuid.UUID,
        correlation_id: str,
        expected_version: int | None = None,
    ) -> CustomerContact:
        business = await BusinessService.get_by_id(session, business_id)
        if business is None:
            raise ResourceNotFound("Business")
        assert_business_mutable(business.state, action="restore_customer")

        contact = await CustomerResolver.resolve(
            session, business_id=business_id, contact_id=contact_id
        )
        CustomerService._check_version(contact, expected_version)

        # Restore brings back an archived record and lifts a block: both make
        # the customer active again (there is no separate "unblock").
        if contact.status not in ("archived", "blocked"):
            raise ResourceStateDenied(
                "customer",
                contact.status,
                action="restore",
                allowed_states=["archived", "blocked"],
            )

        before = CustomerResolver.serialize_contact(contact)
        contact.status = "active"
        contact.version += 1
        await session.flush()

        after = CustomerResolver.serialize_contact(contact)
        await CustomerService._publish(
            session,
            event_type="customer.restored",
            audit_action="restore",
            business_id=business_id,
            contact=contact,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before,
            after_state=after,
        )
        return contact

    @staticmethod
    async def export_customers(
        session: AsyncSession,
        business_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        contacts = await CustomerService.list_for_business(
            session, business_id, status=status
        )
        return [CustomerResolver.serialize_contact(c) for c in contacts]
