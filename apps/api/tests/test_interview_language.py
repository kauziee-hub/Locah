"""One conversation, three ways of talking: English, Tamil script and Tanglish.

The Business interview is one orchestration for every language. An owner who
asks to switch ("Tamil la pesalama?", "தமிழ்ல பேசலாமா?", "English la continue
pannunga") gets the same conversation in the language they asked for: nothing
restarts, nothing they said is lost, the question that was open stays open, and
what is extracted is the same structured Blueprint whatever language the
replies are in.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from platform_core.interview import reader as rd
from platform_core.interview.conversation import LANGUAGE_SWITCHED, SYSTEM_PROMPT
from platform_core.interview.models import BusinessBlueprint, Fact
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine


class Down:
    """The model cannot be reached: every rule here must hold without it."""

    provider_name = "down"
    model_name = "down"
    last_usage = None

    async def generate_structured(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


class Model:
    """A model that answers in English whatever it is asked, and records the context it was given."""

    provider_name = "fixture"
    model_name = "fixture"
    last_usage = {"prompt_tokens": 1, "completion_tokens": 1}

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.payloads: list[dict[str, Any]] = []

    async def generate_structured(self, prompt: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.payloads.append(json.loads(prompt))
        return self.answer


def blueprint(name: str = "Glow Studio") -> BusinessBlueprint:
    bp = BusinessBlueprint(
        business_id=uuid4(),
        identity={"display_name": Fact(value=name, source="PLATFORM", confirmation="confirmed")},
    )
    Engine.open(bp)
    return bp


def facts(bp: BusinessBlueprint) -> dict[str, str]:
    return {k: v.value for k, v in {**bp.known_facts, **bp.unconfirmed_facts}.items()}


def last_reply(bp: BusinessBlueprint) -> str:
    return str(next(m.text for m in reversed(bp.messages) if m.role == "assistant"))


# ------------------------------------------------------------------ the conversation from the work order
@pytest.mark.asyncio
async def test_english_tanglish_english_is_one_conversation_with_nothing_lost() -> None:
    bp = await Engine.turn(blueprint(), "I run a salon in Chennai.", provider=Down(), business_type="salon")
    before = facts(bp)
    pending = bp.asks[-1].ask
    asked = len(bp.asks)

    bp = await Engine.turn(bp, "Tamil la pesalama?", provider=Down(), business_type="salon")
    reply = last_reply(bp)
    assert reply.startswith(LANGUAGE_SWITCHED["ta_en"])  # "Kandippa, Tamil la continue pannalaam."
    assert bp.language_preference == "ta_en" and bp.language_style == "ta_en"
    # A language request answers nothing and skips nothing: the same question is still open.
    assert facts(bp) == before
    assert bp.asks[-1].ask == pending and len(bp.asks) == asked

    bp = await Engine.turn(bp, "Haircut, facial and bridal makeup iruku.", provider=Down(), business_type="salon")
    assert bp.language_style == "ta_en"  # the request holds though this message is mostly English
    # The owner's own names, untranslated — and "iruku" ("we have") is not part of one.
    assert rd.offering_names(facts(bp)["offerings"]) == ["Haircut", "Facial", "Bridal makeup"]
    assert not last_reply(bp).startswith(LANGUAGE_SWITCHED["ta_en"])
    collected = facts(bp)

    bp = await Engine.turn(bp, "English la continue pannunga.", provider=Down(), business_type="salon")
    assert last_reply(bp).startswith(LANGUAGE_SWITCHED["en"])
    assert bp.language_preference == "en"
    assert facts(bp) == collected  # switching back answers nothing and loses nothing

    bp = await Engine.turn(bp, "Mostly weekends, we open at 10", provider=Down(), business_type="salon")
    assert bp.language_style == "en"
    # Same schema, whatever was spoken.
    assert BusinessBlueprint.model_validate(bp.model_dump(mode="json")) == bp


@pytest.mark.asyncio
async def test_tamil_script_request_gets_tamil_script() -> None:
    bp = await Engine.turn(blueprint(), "தமிழ்ல பேசலாமா?", provider=Down(), business_type="salon")
    reply = last_reply(bp)
    assert reply.startswith(LANGUAGE_SWITCHED["ta"])
    assert rd.language_of(reply) == "ta"
    assert bp.language_preference == "ta"
    assert bp.asks[-1].ask == "opening"  # the opening question, asked again in Tamil


@pytest.mark.asyncio
async def test_tamil_then_english_switches_back_without_restarting() -> None:
    bp = await Engine.turn(blueprint(), "தமிழ்ல பேசலாமா?", provider=Down(), business_type="salon")
    bp = await Engine.turn(bp, "நாங்க சலூன் நடத்துறோம், ஹேர்கட் மற்றும் ஃபேஷியல் பண்றோம்", provider=Down(),
                           business_type="salon")
    tamil_facts = facts(bp)
    assert tamil_facts, "a Tamil answer is understood"
    turns = bp.turn_count
    bp = await Engine.turn(bp, "Can we continue in English?", provider=Down(), business_type="salon")
    assert last_reply(bp).startswith(LANGUAGE_SWITCHED["en"])
    assert bp.turn_count == turns + 1 and bp.messages[0].role == "assistant"  # same conversation
    assert facts(bp) == tamil_facts


@pytest.mark.asyncio
async def test_a_request_with_business_content_switches_and_is_still_understood() -> None:
    bp = await Engine.turn(blueprint(), "Tamil la pesalama? Naan oru salon vechirukken, haircut and facial pannuvom",
                           provider=Down(), business_type="salon")
    assert bp.language_preference == "ta_en"
    assert not last_reply(bp).startswith(LANGUAGE_SWITCHED["ta_en"])  # an answer, not only a request
    understood = " ".join(facts(bp).values())
    assert "salon" in understood.lower()
    assert "pesalama" not in understood.lower()  # the request is not a fact about the business
    assert bp.messages[-2].text.startswith("Tamil la pesalama?")  # the transcript keeps what was typed


@pytest.mark.asyncio
async def test_mixed_language_without_a_request_mirrors_the_owner() -> None:
    bp = await Engine.turn(blueprint(), "Naan oru salon vechirukken, Anna Nagar la. Haircut and facial pannuvom.",
                           provider=Down(), business_type="salon")
    assert bp.language_preference == "auto"
    assert bp.language_style == "ta_en"
    assert "salon" in " ".join(facts(bp).values()).lower()


@pytest.mark.asyncio
async def test_talking_about_tamil_is_not_asking_to_talk_in_it() -> None:
    bp = await Engine.turn(blueprint(), "We sell Tamil meals and our staff are mostly Tamil speaking",
                           provider=Down(), business_type="restaurant")
    assert bp.language_preference == "auto"
    assert "Tamil meals" in " ".join(facts(bp).values())


# ------------------------------------------------------------------ with a model
@pytest.mark.asyncio
async def test_the_model_is_told_the_reply_language_and_english_wording_is_not_used_after_tamil() -> None:
    model = Model({
        "language": "en",
        "facts": [{"field": "offerings", "quote": "Haircut and facial", "mode": "append"}],
        "acknowledgement": "Got it.",
        "next_target": "none",
        "next_question": "",
    })
    bp = await Engine.turn(blueprint(), "Tamil la pesalama?", provider=model, business_type="salon")
    assert model.payloads == []  # the switch itself needs no model call
    bp = await Engine.turn(bp, "Haircut and facial", provider=model, business_type="salon")
    assert model.payloads[-1]["reply_language"] == "ta_en"
    assert bp.language_style == "ta_en"  # the model's "en" reading does not override the request
    assert not last_reply(bp).startswith("Got it.")  # English wording is not used after Tamil was asked for
    assert "Haircut and facial" in " ".join(facts(bp).values())  # the owner's words, never translated


def test_the_prompt_explains_reply_language_and_that_a_switch_answers_nothing() -> None:
    assert "reply_language" in SYSTEM_PROMPT
    assert "only asks to change the conversation's language answers nothing" in SYSTEM_PROMPT
    assert "never translate a quote" in SYSTEM_PROMPT


# ------------------------------------------------------------------ recognising a request
@pytest.mark.parametrize(("text", "expected"), [
    ("Tamil la pesalama?", ("ta_en", True)),
    ("தமிழ்ல பேசலாமா?", ("ta", True)),
    ("தமிழில் பேசுங்கள்", ("ta", True)),
    ("Tamil la continue panalam", ("ta_en", True)),
    ("English la continue pannunga.", ("en", True)),
    ("Can we talk in Tamil?", ("ta_en", True)),
    ("Please continue in Tamil script", ("ta", True)),
    ("Reply in English", ("en", True)),
    ("Tamil la pesalama? Naan salon vechirukken", ("ta_en", False)),
    ("We sell Tamil meals", None),
    ("Tamil Nadu la shop iruku", None),
    ("My customers are mostly Tamil speaking", None),
    ("Classes in Tamil", None),
    ("Tamil la paneer biryani iruku", None),
    ("We teach in Tamil and English medium", None),
])
def test_language_requests_are_recognised_by_their_shape(text: str, expected: tuple[str, bool] | None) -> None:
    assert rd.language_request(text) == expected


@pytest.mark.parametrize(("said", "names"), [
    ("Haircut, facial and bridal makeup iruku.", ["Haircut", "Facial", "Bridal makeup"]),
    ("Enga kitta dosa, idli and filter coffee iruku", ["Dosa", "Idli", "Filter coffee"]),
    ("Wedding photography pannuvom", ["Wedding photography"]),
    ("ஹேர்கட், ஃபேஷியல் இருக்கு", ["ஹேர்கட்", "ஃபேஷியல்"]),
    # A name that merely contains such a word keeps it.
    ("Iruku Restaurant special, Venum Kitchen thali", ["Iruku Restaurant special", "Venum Kitchen thali"]),
])
def test_tamil_and_tanglish_lists_name_only_what_is_sold(said: str, names: list[str]) -> None:
    assert rd.offering_names(said) == names
