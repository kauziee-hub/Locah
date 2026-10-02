import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.context import EntitlementSet
from platform_core.entitlements.resolver import BusinessEntitlementResolver
from platform_core.models import Business, BusinessModuleState
from platform_core.services.audit import AuditService
from platform_core.services.outbox import OutboxService


class EntitlementService:
    @staticmethod
    async def get_effective(
        session: AsyncSession,
        business_id: uuid.UUID,
        *,
        business: Business | None = None,
        module_states: dict[str, BusinessModuleState] | None = None,
    ) -> EntitlementSet:
        resolved = await BusinessEntitlementResolver.resolve(
            session, business_id, business=business, module_states=module_states
        )
        return BusinessEntitlementResolver.to_entitlement_set(resolved)


class ModuleService:
    @staticmethod
    async def get_states(
        session: AsyncSession, business_id: uuid.UUID
    ) -> dict[str, BusinessModuleState]:
        result = await session.execute(
            select(BusinessModuleState).where(BusinessModuleState.business_id == business_id)
        )
        return {row.module_id: row for row in result.scalars().all()}

    @staticmethod
    async def enable_module(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        module_id: str,
        actor_id: uuid.UUID,
        entitlements: EntitlementSet,
        correlation_id: str | None = None,
    ) -> BusinessModuleState:
        if not entitlements.is_entitled(module_id):
            from platform_core.exceptions import EntitlementRequired

            raise EntitlementRequired(module_id)
        # Honesty rule (Capability Universe §2 rule 7; Business OS Guide §4): a
        # module whose data, API, permissions and UI are not built yet can be
        # registered and recommended, but never switched on.
        from platform_core.catalog.modules import MODULES

        info = MODULES.get(module_id)
        if info is not None and (info.future or not info.built):
            from platform_core.exceptions import ValidationError

            raise ValidationError(
                f"{info.label} is not available yet",
                details={"field": "module_id", "module_id": module_id, "reason": "not_built"},
            )

        result = await session.execute(
            select(BusinessModuleState).where(
                BusinessModuleState.business_id == business_id,
                BusinessModuleState.module_id == module_id,
            )
        )
        state = result.scalars().first()
        now = datetime.now(timezone.utc)
        # Doc 12 SS9.1: enabled -> (configuring -> ready, only "if configuration
        # required") -> active. No First Launch module declares a configuration
        # schema, so enabling completes the transition to `active`; leaving the
        # module in `enabled` would strand it permanently short of
        # ModuleStateInfo.is_operational() and deny gate [7] forever.
        if state is None:
            state = BusinessModuleState(
                business_id=business_id,
                module_id=module_id,
                activation_state="active",
                enabled_at=now,
                activated_at=now,
            )
            session.add(state)
        else:
            state.activation_state = "active"
            state.enabled_at = now
            state.activated_at = now
            state.deactivated_at = None
        await session.flush()
        await AuditService.record(
            session,
            event_type="module.enabled",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="module",
            resource_id=state.id,
            action="enable",
            after_state={"module_id": module_id},
        )
        # The domain fact, in the same transaction: what the module contributes
        # to the Marketplace listing and the public website follows from it
        # (marketplace.index, website.revalidate subscribers). An audit row is
        # history; it reaches no subscriber.
        await OutboxService.publish(
            session,
            event_type="module.enabled",
            payload={"business_id": str(business_id), "module_id": module_id, "source": "business"},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return state

    @staticmethod
    async def deactivate_module(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        module_id: str,
        actor_id: uuid.UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> BusinessModuleState:
        from platform_core.catalog.modules import MODULES, storefront_modules

        if module_id in storefront_modules():
            from platform_core.exceptions import ValidationError

            info = MODULES.get(module_id)
            raise ValidationError(
                f"{info.label if info else module_id} is part of every business and stays on",
                details={"field": "module_id", "module_id": module_id, "reason": "storefront"},
            )
        result = await session.execute(
            select(BusinessModuleState).where(
                BusinessModuleState.business_id == business_id,
                BusinessModuleState.module_id == module_id,
            )
        )
        state = result.scalars().first()
        if state is None:
            from platform_core.exceptions import ResourceNotFound

            raise ResourceNotFound("Module state")
        state.activation_state = "deactivated"
        state.deactivated_at = datetime.now(timezone.utc)
        state.deactivated_reason = reason
        await session.flush()
        await AuditService.record(
            session,
            event_type="module.deactivated",
            actor_identity_id=actor_id,
            actor_context="business",
            business_id=business_id,
            resource_type="module",
            resource_id=state.id,
            action="deactivate",
            after_state={"module_id": module_id, "reason": reason},
        )
        # Deactivation stops new operations and keeps every record (Doc 08
        # §7.4 rule 6); the event takes its public actions away everywhere.
        await OutboxService.publish(
            session,
            event_type="module.deactivated",
            payload={"business_id": str(business_id), "module_id": module_id, "source": "business"},
            business_id=business_id,
            correlation_id=correlation_id,
        )
        return state
