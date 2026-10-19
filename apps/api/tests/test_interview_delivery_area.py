"""Where the owner delivers is said back in plain words (BUGS.md B8).

The Owner Simulation Lab's meat shop wrote "delivery near Chromepet and
Pallavaram"; LOCAH replied "…with delivery around Near Chromepet". The
owner's own preposition ("near", "around", "within", "in") belongs to their
sentence, never to the place: it is not kept, not capitalised and not said
twice. A radius keeps its own word ("within 5 km of Adyar"). Nothing here
calls a model: the provider is scripted or down.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest

from platform_core.interview import reader as rd
from platform_core.interview.models import BusinessBlueprint, Fact, TargetState
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine
from platform_core.interview.site_composer import ordering_facts
from platform_core.interview.understanding import buying, delivery_area, read_back

# What the owner wrote -> the places -> how LOCAH words it after "delivery".
SAID = [
    ("delivery near Chromepet", "Chromepet", "around Chromepet"),
    ("delivery near Chromepet and Pallavaram", "Chromepet and Pallavaram", "around Chromepet and Pallavaram"),
    ("we deliver within 5 km of Adyar", "5 km of Adyar", "within 5 km of Adyar"),
    ("home delivery in Velachery and Guindy", "Velachery and Guindy", "around Velachery and Guindy"),
    ("We deliver in and around Adyar", "Adyar", "around Adyar"),
]
IDS = [s for s, _, _ in SAID]
# The shapes B8 produced: a preposition kept inside the place, or two in a row.
DOUBLED = re.compile(r"(?i:\b(?:around|within|near|in)\s+(?:near|around|within|in)\b)|\b(?:Near|Within|Around)\b|"
                     r"(?i:\b(?:around|within)\s+(?:home\s+)?deliver)")
OPENING = "Velan Fresh Meats, Chromepet, Chennai. We sell chicken mutton fish, {area}. People order on WhatsApp."


class Down:
    """The model cannot be reached: the rules read the owner's words."""

    provider_name = "down"
    model_name = "down"
    last_usage = None

    async def generate_structured(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


class Model:
    """A scripted model answer, filed the way DeepSeek filed it in the lab run."""

    provider_name = "fixture"
    model_name = "fixture"
    last_usage = {"prompt_tokens": 1, "completion_tokens": 1}

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    async def generate_structured(self, prompt: Any, schema: Any, model_config: Any,
                                  timeout_seconds: Any) -> dict[str, Any]:
        return self.answer


def fresh() -> BusinessBlueprint:
    bp = BusinessBlueprint(business_id=uuid4(), name_pending=True)
    Engine.open(bp)
    return bp


def answered(said: str, summary: str = "") -> BusinessBlueprint:
    """A meat shop whose delivery area was answered with the owner's own words."""
    bp = BusinessBlueprint(
        business_id=uuid4(),
        identity={"display_name": Fact(value="Velan Fresh Meats", source="PLATFORM", confirmation="confirmed")},
    )
    bp.known_facts = {"locations": Fact(value="Chromepet, Chennai", source="USER_STATEMENT", confirmation="confirmed")}
    bp.discovery["fulfilment.mode"] = TargetState(status="answered", summary="Delivery", quote="We deliver")
    # The model's summary is written to the owner ("You deliver near …"); the
    # quote is the owner's exact words.
    bp.discovery["fulfilment.area"] = TargetState(status="answered", summary=summary or f"You {said}", quote=said)
    return bp


def reply(bp: BusinessBlueprint) -> str:
    return str(next(m.text for m in reversed(bp.messages) if m.role == "assistant"))


@pytest.mark.parametrize(("said", "places", "words"), SAID, ids=IDS)
def test_the_places_are_read_without_the_owners_preposition(said: str, places: str, words: str) -> None:
    assert rd.service_area(said) == places
    assert rd.area_phrase(places) == words


@pytest.mark.parametrize("area", ["Near Chromepet", "near Chromepet", "around Chromepet", "in Chromepet"])
def test_a_place_that_still_carries_a_preposition_is_never_said_twice(area: str) -> None:
    assert rd.area_phrase(area) == "around Chromepet"


def test_a_radius_keeps_its_own_word() -> None:
    assert rd.area_phrase("5 km of Adyar") == "within 5 km of Adyar"
    assert rd.area_phrase("within 5 km") == "within 5 km"
    assert rd.area_phrase("5 to 7 km") == "within 5 to 7 km"
    assert rd.area_phrase("3 km kulla") == "within 3 km"
    # "nearby" names no place, so it is not taken for "near".
    assert rd.service_area_said("we deliver nearby") == ""


@pytest.mark.parametrize(("said", "places", "words"), SAID, ids=IDS)
def test_the_read_back_and_the_side_panel_say_the_area_once(said: str, places: str, words: str) -> None:
    bp = answered(said)
    assert delivery_area(bp) == places
    assert {"kind": "delivery", "text": f"Delivery {words}"} in buying(bp)
    sentence = read_back(bp)
    assert f"with delivery {words}" in sentence, sentence
    assert not DOUBLED.search(sentence), sentence


@pytest.mark.asyncio
async def test_the_lab_meat_shop_opening_is_said_back_as_written() -> None:
    """The lab run, with the model's answer as it was filed: quote "delivery near …"."""
    said = "delivery near Chromepet and Pallavaram"
    model = Model({
        "business_name": "Velan Fresh Meats",
        "facts": [{"field": "offerings", "quote": "chicken mutton fish", "mode": "replace"},
                  {"field": "locations", "quote": "Chromepet, Chennai", "mode": "replace"}],
        "answered": [{"target": "fulfilment.mode", "summary": "You deliver", "quote": said, "status": "answered"},
                     {"target": "fulfilment.area", "summary": "You deliver near Chromepet and Pallavaram",
                      "quote": said, "status": "answered"}],
        "acknowledgement": "Got it.", "next_target": "offerings.structure",
        "next_question": "Do people choose the cut too?",
    })
    bp = await Engine.turn(fresh(), OPENING.format(area=said), provider=model, business_type=None)
    text = reply(bp)
    assert "a meat shop in Chromepet, Chennai" in text
    assert "with delivery around Chromepet and Pallavaram" in text, text
    assert not DOUBLED.search(text), text


@pytest.mark.asyncio
@pytest.mark.parametrize(("said", "places", "words"), SAID[1:4], ids=IDS[1:4])
async def test_an_area_volunteered_in_the_opening_is_read_without_the_model(
        said: str, places: str, words: str) -> None:
    bp = await Engine.turn(fresh(), OPENING.format(area=said), provider=Down(), business_type=None)
    assert delivery_area(bp) == places  # never "We sell chicken mutton fish"
    text = reply(bp)
    assert f"with delivery {words}" in text, text
    assert not DOUBLED.search(text), text
    # Where it delivers is not where the shop is: never "a meat shop in Velachery".
    assert not re.search(r"\bshop in (?:Velachery|Adyar|Pallavaram)\b", text), text


@pytest.mark.parametrize(("said", "body"), [
    ("delivery near Chromepet and Pallavaram", "Delivered around Chromepet and Pallavaram."),
    ("we deliver within 5 km of Adyar", "Delivered within 5 km of Adyar."),
    ("home delivery in Velachery and Guindy", "Delivered around Velachery and Guindy."),
    ("We sell chicken mutton fish, home delivery in Velachery and Guindy.", "Delivered around Velachery and Guindy."),
])
def test_the_website_says_the_area_once(said: str, body: str) -> None:
    strip = ordering_facts(answered(said), "retail")
    delivery = next(i for i in strip if i["kind"] == "delivery")
    assert delivery["body"] == body
