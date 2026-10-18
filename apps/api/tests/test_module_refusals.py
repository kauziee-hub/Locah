"""Each way switching a tool on can be refused says its own reason.

Certification (owner edits): an unknown tool and a future tool were both
refused as "Entitlement required" — the plan check ran before the tool was
known to exist or to be built.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from platform_core.context import EntitlementSet
from platform_core.exceptions import EntitlementRequired, ResourceNotFound, ValidationError
from platform_core.services.entitlement import ModuleService


def _enable(module_id: str, entitled: frozenset[str]) -> Any:
    # The checks refuse before any database work; a session is never reached.
    return asyncio.run(ModuleService.enable_module(
        None,  # type: ignore[arg-type]
        business_id=uuid.uuid4(), module_id=module_id, actor_id=uuid.uuid4(),
        entitlements=EntitlementSet(modules=entitled)))


def test_an_unknown_tool_is_not_found() -> None:
    with pytest.raises(ResourceNotFound):
        _enable("not-a-tool", frozenset({"not-a-tool"}))


def test_a_future_tool_is_not_available_yet_whatever_the_plan() -> None:
    with pytest.raises(ValidationError) as refused:
        _enable("payroll", frozenset())
    assert refused.value.detail["details"]["reason"] == "not_built"  # type: ignore[index]


def test_a_built_tool_outside_the_plan_needs_the_entitlement() -> None:
    with pytest.raises(EntitlementRequired):
        _enable("bookings", frozenset())
