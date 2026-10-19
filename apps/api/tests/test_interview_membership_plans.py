"""The plans an owner tells LOCAH reach Memberships with their length.

Owner lab (gym): "Monthly 3500, quarterly 9500, annual 32000" became catalogue
items with no length, Memberships said "Create a plan first", and the owner
had to make every plan again.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest

from platform_core.services.business_interview import _membership_plan_payload


@pytest.mark.parametrize(("name", "said", "kind", "days", "sessions"), [
    ("Monthly", "", "access", 30, None),
    ("Quarterly", "", "access", 90, None),
    ("Annual", "", "access", 365, None),
    ("Open gym, monthly", "per month", "access", 30, None),
    ("Half-yearly", "", "access", 180, None),
    ("12-class pack", "Small-group strength, valid six weeks", "session_pack", 42, 12),
])
def test_a_plan_with_its_length_said_becomes_a_memberships_plan(name: str, said: str, kind: str, days: int,
                                                                sessions: int | None) -> None:
    plan = _membership_plan_payload(name, "3500", said)
    assert plan is not None
    assert (plan["plan_kind"], plan["duration_days"], plan.get("sessions_included")) == (kind, days, sessions)
    assert plan["status"] == "draft", "the owner makes it live"


@pytest.mark.parametrize(("name", "amount"), [
    ("12 classes", "4800"),     # a pack with no validity said: nothing is guessed
    ("PT 12 sessions", "14400"),
    ("Drop-in class", "500"),   # no length at all
    ("Monthly", ""),            # no price
])
def test_nothing_is_guessed(name: str, amount: str) -> None:
    assert _membership_plan_payload(name, amount, "") is None


async def _draft(business_id: str, actor: Any, payload: dict[str, Any]) -> None:
    from platform_core.db import get_database_url
    from platform_core.services.business_interview import _membership_plan_draft
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    url = get_database_url()
    assert url
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        await _membership_plan_draft(session, UUID(business_id), payload, actor_id=actor, correlation_id=str(uuid4()))
        await session.commit()
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_the_plan_is_a_draft_in_memberships_once_and_the_owner_makes_it_live(monkeypatch: Any) -> None:
    from fastapi.testclient import TestClient
    from platform_api.main import app
    from platform_testing.phase_b import create_business, new_identity

    client = TestClient(app)
    me, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog", "payments", "memberships"))
    monthly = _membership_plan_payload("Monthly", "3500", "")
    assert monthly is not None
    asyncio.run(_draft(bid, me, monthly))
    asyncio.run(_draft(bid, me, monthly))
    plans = client.get(f"/v1/platform/businesses/{bid}/membership-plans", headers=owner).json()["data"]
    assert [(p["name"], p["duration_days"], p["status"]) for p in plans] == [("Monthly", 30, "draft")]
    live = client.patch(f"/v1/platform/businesses/{bid}/membership-plans/{plans[0]['id']}", json={"status": "active"},
                        headers=owner)
    assert live.status_code == 200, live.text
    assert live.json()["data"]["status"] == "active"
