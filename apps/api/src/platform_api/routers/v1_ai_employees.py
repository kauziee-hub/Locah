"""AI employees — the owner's controls, the action feed and approvals (Capability Universe §8).

Reading the feed needs ``ai_employees.read``. Changing an AI employee's tools,
tier, limits or kill switch, pausing all of them and deciding approvals need
``ai_employees.manage`` — a person's permission; no AI employee holds it.
Approving a request that acts in another module also needs that module's own
permission (sending a purchase order needs ``procurement.approve``).

The AI Employee Sandbox (``/ai-employees/sandbox``) is a demonstration: it reads
the business's real records through public reads and asks the same runtime
decision a live employee would, but writes nothing and sends nothing. It needs
only ``ai_employees.read`` and works whether or not the AI staff module is on.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.ai_employees import collections, procurement, sandbox, test_mode
from platform_core.ai_employees.runtime import AIRuntime
from platform_core.exceptions import PermissionDenied, ResourceNotFound
from platform_core.models import AIAction
from platform_core.permissions import AI_EMPLOYEES_MANAGE, AI_EMPLOYEES_READ
from platform_core.services.audit import AuditService

router = APIRouter(prefix="/v1/b", tags=["ai-employees"])

# The module permission an approval acts with, per approval-only tool.
APPROVAL_NEEDS = {"request_po_send": "procurement.approve"}
RUNNERS = {"collections": collections.run, "procurement": procurement.run}


def _meta(actor: BusinessActorContext) -> dict[str, Any]:
    return {"correlation_id": actor.request.correlation_id}


class EmployeePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    autonomy: str | None = Field(default=None, pattern="^T[0-2]$")
    tools: list[str] | None = Field(default=None, max_length=20)
    limits: dict[str, int] | None = None


class PauseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool


class SandboxMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(pattern="^(whatsapp_manager|receptionist)$")
    message: str = Field(min_length=1, max_length=500)


class SandboxProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(order|booking|lead)$")
    summary: str = Field(default="", max_length=300)
    offering_id: UUID | None = None
    location_id: UUID | None = None
    quantity: int | None = Field(default=None, ge=1, le=50)
    starts_at: str | None = Field(default=None, max_length=40)
    ends_at: str | None = Field(default=None, max_length=40)
    mode: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=500)


class TestRecordIn(SandboxProposal):
    """Approve a proposal in Test Mode (AI Employee Studio)."""

    scenario: str = Field(pattern="^[a-z_]{2,40}$")


class TestPaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(pattern="^(succeed|fail)$")


def _sandbox_on() -> None:
    if not sandbox.enabled():
        raise ResourceNotFound("AI Employee Sandbox")


@router.get("/{business_id}/ai-employees")
async def overview(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await AIRuntime.overview(session, business_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.patch("/{business_id}/ai-employees/{kind}")
async def update_employee(
    business_id: UUID,
    kind: str,
    body: EmployeePatch,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    emp = await AIRuntime.update(session, business_id, kind, patch, actor_id=actor.request.identity_id)
    await AuditService.record(
        session, event_type="ai_employee.updated", actor_identity_id=actor.request.identity_id,
        actor_context="business", action="update", business_id=business_id, resource_type="ai_employee",
        resource_id=emp.id, after_state={"kind": kind, **patch})
    data = await AIRuntime.overview(session, business_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/pause")
async def pause_all(
    business_id: UUID,
    body: PauseBody,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await AIRuntime.set_pause(session, business_id, body.paused, actor_id=actor.request.identity_id)
    await AuditService.record(
        session, event_type="ai_employee.paused" if body.paused else "ai_employee.resumed",
        actor_identity_id=actor.request.identity_id, actor_context="business",
        action="pause" if body.paused else "resume", business_id=business_id, resource_type="ai_employee")
    data = await AIRuntime.overview(session, business_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/{kind}/run")
async def run_now(
    business_id: UUID,
    kind: str,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    runner = RUNNERS.get(kind)
    if runner is None:
        raise ResourceNotFound("AI employee that runs on demand")
    report = await runner(session, business_id, source=f"run by {actor.request.identity_id}")
    data = await AIRuntime.overview(session, business_id)
    await session.commit()
    return {"data": {**data, "report": report}, "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/actions/{action_id}/decision")
async def decide(
    business_id: UUID,
    action_id: UUID,
    body: DecisionBody,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    action = await session.get(AIAction, action_id)
    if action is None or action.business_id != business_id:
        raise ResourceNotFound("AI action")
    needed = APPROVAL_NEEDS.get(action.tool)
    if body.approve and needed and needed not in actor.request.effective_permissions:
        raise PermissionDenied(needed)
    decided = await AIRuntime.decide_approval(session, business_id, action_id, approve=body.approve,
                                              actor_id=actor.request.identity_id)
    await AuditService.record(
        session, event_type="ai_employee.approval_decided", actor_identity_id=actor.request.identity_id,
        actor_context="business", action="approve" if body.approve else "reject", business_id=business_id,
        resource_type="ai_action", resource_id=decided.id, after_state={"tool": decided.tool})
    data = await AIRuntime.overview(session, business_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.get("/{business_id}/ai-employees/sandbox")
async def sandbox_overview(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    return {"data": await sandbox.overview(session, business_id), "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/sandbox/simulate")
async def sandbox_simulate(
    business_id: UUID,
    body: SandboxMessage,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    data = await sandbox.simulate(session, business_id, scenario=body.scenario, message=body.message)
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/sandbox/approve")
async def sandbox_approve(
    business_id: UUID,
    body: SandboxProposal,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    proposal = body.model_dump(mode="json", exclude_none=True)
    return {"data": await sandbox.approve(session, business_id, proposal), "meta": _meta(actor)}


# ------------------------------------------------------------------ Test Mode
# Approved proposals become test records (ai_test_records) — never real
# orders, bookings or enquiries; payments go through the test adapter only.

@router.get("/{business_id}/ai-employees/test-records")
async def test_records(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    return {"data": {"records": await test_mode.records(session, business_id), "notice": test_mode.TEST_NOTICE},
            "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/test-records")
async def test_record_create(
    business_id: UUID,
    body: TestRecordIn,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    proposal = body.model_dump(mode="json", exclude_none=True, exclude={"scenario"})
    data = await test_mode.record(session, business_id, proposal, scenario=body.scenario,
                                  actor_id=actor.request.identity_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/test-records/{record_id}/pay")
async def test_record_pay(
    business_id: UUID,
    record_id: UUID,
    body: TestPaymentIn,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    data = await test_mode.pay(session, business_id, record_id, outcome=body.outcome,
                               actor_id=actor.request.identity_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/ai-employees/test-records/clear")
async def test_records_clear(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(AI_EMPLOYEES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _sandbox_on()
    cleared = await test_mode.clear(session, business_id, actor_id=actor.request.identity_id)
    await session.commit()
    return {"data": {"cleared": cleared}, "meta": _meta(actor)}
