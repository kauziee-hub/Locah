"""Release regressions for the actual interview engine with its model unavailable."""

from __future__ import annotations

import pytest

from test_talk_with_locah import NILA, facts, fresh, groups, reply, say


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "what have you understood so far?", "summarize my business",
    "enna purinjudhu?", "இதுவரை என்ன புரிந்தது?",
])
async def test_recap_preserves_facts_and_answers_the_owner(question: str) -> None:
    bp = await say(fresh(), NILA)
    before = facts(bp)
    names = groups(bp)
    bp = await say(bp, question)
    assert facts(bp) == before
    assert groups(bp) == names
    assert "Nila" in reply(bp)
    assert not reply(bp).startswith("Added.")


@pytest.mark.asyncio
async def test_tools_question_explains_evidence_without_selecting_modules() -> None:
    bp = await say(fresh(), NILA)
    before = facts(bp)
    choices = {r.module_id: r.choice for r in bp.recommended_modules}
    bp = await say(bp, "which tools would help me?")
    assert facts(bp) == before
    assert {r.module_id: r.choice for r in bp.recommended_modules} == choices
    assert "From what you've told me" in reply(bp)
    assert "Nothing turns on until you choose" in reply(bp)


@pytest.mark.asyncio
async def test_new_offering_is_added_without_erasing_existing_catalogue() -> None:
    bp = await say(fresh(), NILA)
    bp = await say(bp, "we also sell sandwiches now")
    assert {"Coffee", "Pasta", "Cakes", "Sandwiches"} <= set(groups(bp))
    assert bp.identity["display_name"].value == "Nila Cafe"
    assert facts(bp)["opening_hours"] == "Every day 9 am–10 pm"


@pytest.mark.asyncio
async def test_started_delivery_is_an_addition_not_a_restart() -> None:
    from platform_core.interview.understanding import fulfilment

    bp = await say(fresh(), "I run Nila Cafe in Anna Nagar, we sell coffee and cakes, pickup only, open 9 to 10")
    bp = await say(bp, "we also started delivery")
    assert "delivery" in fulfilment(bp)
    assert bp.identity["display_name"].value == "Nila Cafe"
    assert {"Coffee", "Cakes"} <= set(groups(bp))


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["hmm not sure", "what's the weather today"])
async def test_vague_or_irrelevant_input_preserves_business(message: str) -> None:
    bp = await say(fresh(), NILA)
    before = facts(bp)
    bp = await say(bp, message)
    assert facts(bp) == before
    assert not reply(bp).startswith("Added.")


def test_recognizing_meta_questions_does_not_swallow_fact_statements() -> None:
    from platform_core.interview.orchestrator import _meta_question

    assert not _meta_question("We delivered 50 orders so far")
    assert not _meta_question("We also sell sandwiches now. What have you understood?")
