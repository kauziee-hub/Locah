"""The interview evaluation as a gate: seventeen owners, two modes, zero AI calls.

See platform_testing/interview_eval.py for how a persona is scripted and
scored; `main()` there writes the transcripts to acceptance-out/interview-transcripts/.
"""

from __future__ import annotations

import pytest

from platform_core.ai_guard import blocked_calls
from platform_testing.interview_eval import run_persona
from platform_testing.interview_personas import ALL_PERSONAS as PERSONAS


@pytest.mark.asyncio
@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.key)
async def test_each_owner_gets_an_expert_short_interview(persona) -> None:
    run = await run_persona(persona, "model")
    assert not run.red_flags, run.red_flags
    lo, hi = persona.follow_ups
    assert run.checkpoint_after is not None and lo <= run.checkpoint_after <= hi, run.asks
    assert run.score >= 85, run.breakdown
    assert not blocked_calls()


@pytest.mark.asyncio
@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.key)
async def test_with_the_model_down_nothing_is_misfiled_and_build_still_comes(persona) -> None:
    run = await run_persona(persona, "down")
    assert not run.red_flags, run.red_flags
    assert run.checkpoint_after is not None and run.checkpoint_after <= 7, run.asks
    assert run.score >= 75, run.breakdown
