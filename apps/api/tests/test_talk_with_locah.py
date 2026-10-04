"""Talk with LOCAH without the model: one message can say many things, only
what is missing is asked, corrections change only what they correct and are
said back, and Tanglish is understood the same way as English.

The opening from the work order: "I run Nila Cafe in Anna Nagar, we sell
coffee, pasta and cakes, dine-in, pickup and delivery, open 9 to 10." — then
"Actually on weekends we're open till 11".
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from platform_core.interview import hours
from platform_core.interview import reader as rd
from platform_core.interview.conversation import ACKS
from platform_core.interview.models import BusinessBlueprint
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine
from platform_core.interview.understanding import fulfilment

NILA = ("I run Nila Cafe in Anna Nagar, we sell coffee, pasta and cakes, dine-in, pickup and delivery, "
        "open 9 to 10.")
NILA_TA = ("Naan Nila Cafe nadathuren Anna Nagar la, coffee, pasta, cakes iruku, dine-in, pickup and delivery "
           "pannuvom, kaalai 9 to raathiri 10 open")


class Down:
    """The model cannot be reached: every rule here holds without it."""

    provider_name = "down"
    model_name = "down"
    last_usage = None

    async def generate_structured(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


def fresh() -> BusinessBlueprint:
    """A business that has no name yet, as "Talk to LOCAH" starts one."""
    bp = BusinessBlueprint(business_id=uuid4(), name_pending=True)
    Engine.open(bp)
    return bp


async def say(bp: BusinessBlueprint, text: str) -> BusinessBlueprint:
    return await Engine.turn(bp, text, provider=Down(), business_type=None)


def facts(bp: BusinessBlueprint) -> dict[str, str]:
    return {k: v.value for k, v in {**bp.known_facts, **bp.unconfirmed_facts}.items()}


def reply(bp: BusinessBlueprint) -> str:
    return str(next(m.text for m in reversed(bp.messages) if m.role == "assistant"))


def groups(bp: BusinessBlueprint) -> list[str]:
    return [g.name for g in bp.taxonomy.groups] if bp.taxonomy else []


# ------------------------------------------------------------------ one message, many facts
@pytest.mark.asyncio
async def test_one_sentence_gives_the_name_place_range_ways_and_hours() -> None:
    bp = await say(fresh(), NILA)
    assert bp.name_pending is False and bp.identity["display_name"].value == "Nila Cafe"
    assert facts(bp)["locations"] == "Anna Nagar"
    assert facts(bp)["opening_hours"] == "Every day 9 am–10 pm"
    assert groups(bp) == ["Coffee", "Pasta", "Cakes"]  # never "Dine" from "dine-in"
    assert set(fulfilment(bp)) >= {"delivery", "pickup"}
    # The café's own address is not where it delivers.
    area = bp.discovery.get("fulfilment.area")
    assert area is None or area.status != "answered" or "Nila" not in (area.summary or "")


@pytest.mark.asyncio
async def test_only_what_is_missing_is_asked_next() -> None:
    bp = await say(fresh(), NILA)
    text = reply(bp)
    assert "called" not in text  # the name was said
    assert "dropping in" not in text and "order ahead" not in text  # dine-in, pickup and delivery were said
    assert "WhatsApp" in text and "website" in text  # what is open: how those orders reach them


# ------------------------------------------------------------------ corrections
@pytest.mark.asyncio
async def test_weekend_hours_change_only_the_weekend_and_are_said_back() -> None:
    bp = await say(await say(fresh(), NILA), "Actually on weekends we're open till 11")
    assert facts(bp)["opening_hours"] == "Mon–Fri 9 am–10 pm; Sat–Sun 9 am–11 pm"
    assert reply(bp).startswith("Updated — hours: Mon–Fri 9 am–10 pm; Sat–Sun 9 am–11 pm.")
    # The owner's words are kept as the evidence.
    assert "weekends" in (bp.unconfirmed_facts["opening_hours"].evidence or "")


@pytest.mark.asyncio
async def test_a_payment_reply_is_never_the_delivery_area() -> None:
    bp = await say(await say(await say(fresh(), NILA), "Actually on weekends we're open till 11"),
                   "you can pay by UPI or cash")
    area = bp.discovery.get("fulfilment.area")
    assert area is None or area.status != "answered"
    payment = bp.discovery.get("commerce.payment")
    assert payment is not None and payment.status == "answered" and "UPI" in (payment.summary or "")


# ------------------------------------------------------------------ Tanglish
@pytest.mark.asyncio
async def test_tanglish_opening_is_read_like_the_english_one() -> None:
    bp = await say(fresh(), NILA_TA)
    assert bp.identity["display_name"].value == "Nila Cafe"
    assert facts(bp)["locations"] == "Anna Nagar"
    assert facts(bp)["opening_hours"] == "Every day 9 am–10 pm"
    assert groups(bp) == ["Coffee", "Pasta", "Cakes"]
    assert bp.language_style == "ta_en"
    assert "eppadi order" in reply(bp)  # asked in Tanglish, and only how orders come in


@pytest.mark.asyncio
async def test_tanglish_weekend_correction_stays_in_tanglish() -> None:
    bp = await say(await say(fresh(), NILA_TA), "weekend la 11 varaikum open")
    assert facts(bp)["opening_hours"] == "Mon–Fri 9 am–10 pm; Sat–Sun 9 am–11 pm"
    assert reply(bp).startswith("Maathitten — timing:")
    assert bp.language_style == "ta_en"


@pytest.mark.asyncio
async def test_hours_given_when_the_name_was_asked_are_not_the_name() -> None:
    bp = await say(fresh(), "I run a cafe in Anna Nagar, we sell coffee and cakes")
    assert bp.name_pending and bp.asks[-1].ask == "name"
    bp = await say(bp, "weekend la 11 varaikum open")
    assert bp.name_pending  # still waiting for a real name
    bp = await say(bp, "Nila Cafe")
    assert bp.identity["display_name"].value == "Nila Cafe"


@pytest.mark.asyncio
async def test_we_accept_upi_is_how_people_pay_not_how_they_order() -> None:
    bp = await say(await say(fresh(), NILA_TA), "UPI, cash rendum vaanguvom")
    action = bp.discovery.get("commerce.action")
    assert action is None or action.status != "answered"
    payment = bp.discovery.get("commerce.payment")
    assert payment is not None and payment.status == "answered"


# ------------------------------------------------------------------ the way LOCAH talks
@pytest.mark.asyncio
async def test_acknowledgements_vary_and_a_summary_comes_mid_way() -> None:
    bp = fresh()
    for text in (NILA, "Mostly on WhatsApp", "Around Anna Nagar and Mogappair", "UPI and cash",
                 "9876543210"):
        bp = await say(bp, text)
    said = [m.text for m in bp.messages if m.role == "assistant"]
    stock = {a for a in ACKS["en"]}
    openers = [next((a for a in stock if s.startswith(a)), "") for s in said]
    assert all(a != b or not a for a, b in zip(openers, openers[1:])), openers
    assert any("shape of it" in s or "So far" in s or "so far" in s for s in said[1:]), said


# ------------------------------------------------------------------ the readers
@pytest.mark.parametrize(("said", "week"), [
    ("open 9 to 10", "Every day 9 am–10 pm"),
    ("10 am to 9 pm, closed on Sundays", "Mon–Sat 10 am–9 pm; Sun closed"),
    ("Weekdays 7 am - 9 pm, weekends 8 to 2", "Mon–Fri 7 am–9 pm; Sat–Sun 8 am–2 pm"),
    ("lunch 12 to 3, dinner 7 to 11, closed on Mondays", "Mon closed; Tue–Sun noon–3 pm, 7 pm–11 pm"),
    ("open 5:30 am to 10 pm every day", "Every day 5:30 am–10 pm"),
    ("we're open from 11 am till midnight", "Every day 11 am–midnight"),
    ("24/7", "Every day open 24 hours"),
    ("kaalai 9 mudhal raathiri 10 varaikum open", "Every day 9 am–10 pm"),
    ("காலை 9 முதல் இரவு 10 வரை திறந்திருக்கும்", "Every day 9 am–10 pm"),
])
def test_hours_are_read_as_a_week(said: str, week: str) -> None:
    found = hours.parse(said)
    assert found is not None and hours.describe(found) == week


@pytest.mark.parametrize("said", ["we deliver within 5 to 7 km", "till 11", "closed on Mondays", "Anna Nagar"])
def test_what_is_not_a_schedule_is_not_hours(said: str) -> None:
    assert hours.parse(said) is None


@pytest.mark.parametrize(("change", "week"), [
    ("Actually on weekends we're open till 11", "Mon–Fri 9 am–10 pm; Sat–Sun 9 am–11 pm"),
    ("closed on mondays", "Mon closed; Tue–Sun 9 am–10 pm"),
    ("on Sundays we open at 8", "Mon–Sat 9 am–10 pm; Sun 8 am–10 pm"),
    ("sunday leave", "Mon–Sat 9 am–10 pm; Sun closed"),
])
def test_a_correction_changes_only_the_days_it_names(change: str, week: str) -> None:
    found = hours.parse(change, hours.parse("open 9 to 10"))
    assert found is not None and hours.describe(found) == week


@pytest.mark.parametrize(("said", "name"), [
    (NILA, "Nila Cafe"),
    ("We run Nila Cafe & Bakehouse in Anna Nagar", "Nila Cafe & Bakehouse"),
    ("I run a cafe called Nila Cafe in Anna Nagar", "Nila Cafe"),
    (NILA_TA, "Nila Cafe"),
    ("Enga kadai per Kavya Cakes dhaan", "Kavya Cakes"),
    ("I run a small bakery in Adyar", ""),
    ("Haircut, facial and bridal makeup iruku.", ""),
    ("We have Chicken, mutton and fish", ""),
])
def test_the_name_is_read_only_when_it_is_said(said: str, name: str) -> None:
    assert rd.business_name(said) == name


def test_offerings_stop_where_the_ways_and_hours_start() -> None:
    assert rd.offer_statement(NILA) == ["Coffee", "Pasta", "Cakes"]
    assert rd.offering_names("Silk saree collection, cotton sarees") == ["Silk saree collection", "Cotton sarees"]
    assert rd.ta_offer_list("Enga kitta dosa, idli and filter coffee iruku") == ["Dosa", "Idli", "Filter coffee"]


def test_a_delivery_area_needs_a_delivery_verb_when_volunteered() -> None:
    assert rd.service_area_said(NILA) == ""
    assert rd.service_area_said("we deliver around Anna Nagar and Mogappair, pickup also") == "Anna Nagar and Mogappair"
    assert rd.service_area("you can pay by UPI or cash") == ""


# ------------------------------------------------------------------ into the business
def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


async def _hand_off(business_id: str, said: str, actor: Any) -> None:
    from platform_core.db import get_database_url
    from platform_core.interview.models import Fact
    from platform_core.services.business_interview import _hours_to_location
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from uuid import UUID

    url = get_database_url()
    assert url
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool)
    bp = BusinessBlueprint(business_id=UUID(business_id))
    bp.unconfirmed_facts["opening_hours"] = Fact(value=said, source="USER_STATEMENT")
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        await _hours_to_location(session, UUID(business_id), bp, actor_id=actor, correlation_id=str(uuid4()))
        await session.commit()
    await engine.dispose()


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_build_gives_the_location_the_hours_said_but_never_overwrites_saved_ones(monkeypatch: Any) -> None:
    from fastapi.testclient import TestClient
    from platform_api.main import app
    from platform_testing.phase_b import create_business, new_identity, primary_location

    client = TestClient(app)
    me, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog",))
    loc = primary_location(client, owner, bid)

    def saved() -> dict[str, Any]:
        r = client.get(f"/v1/platform/businesses/{bid}/locations/{loc}", headers=owner)
        assert r.status_code == 200, r.text
        return dict(r.json()["data"].get("hours") or {})

    _run(_hand_off(bid, "Mon–Fri 9 am–10 pm; Sat–Sun 9 am–11 pm", me))
    assert saved()["mon"] == [["09:00", "22:00"]] and saved()["sun"] == [["09:00", "23:00"]]
    # Hours the owner set themselves stay as they are.
    _run(_hand_off(bid, "Every day 7 am–8 pm", me))
    assert saved()["mon"] == [["09:00", "22:00"]]
