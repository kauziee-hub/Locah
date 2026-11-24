"""Create Business by talking to LOCAH — one interview, however it starts.

Phase A: the owner can start by talking (no form, no category, no name), by
picking a category first, or by voice — and it is the same Blueprint, the
same planner and the same readiness either way. Nothing here calls a model:
the provider is either scripted or down.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest

from platform_core.ai_guard import blocked_calls
from platform_core.interview import voice
from platform_core.interview.corrections import CorrectionError, apply_correction
from platform_core.interview.models import BusinessBlueprint, CategorySeed, Fact
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine
from platform_core.interview.reader import business_name, corrects_kind
from platform_core.interview.understanding import understanding


class Down:
    """The model is unreachable: the deterministic reader is the whole understanding."""

    provider_name = "down"
    model_name = "down"
    last_usage = None

    async def generate_structured(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider unreachable")


def unnamed() -> BusinessBlueprint:
    bp = BusinessBlueprint(
        business_id=uuid.uuid4(),
        identity={"display_name": Fact(value="New business", source="PLATFORM", confirmation="confirmed")},
        name_pending=True,
    )
    Engine.open(bp)
    return bp


async def say(bp: BusinessBlueprint, text: str, via: str = "text") -> BusinessBlueprint:
    return await Engine.turn(bp, text, provider=Down(), business_type="not_sure", via=via)


# ------------------------------------------------------------ talk first


@pytest.mark.asyncio
async def test_talk_first_reads_the_kind_says_it_back_and_asks_the_name_once() -> None:
    bp = unnamed()
    # No name to address them by yet: the opening does not invent one.
    assert bp.messages[0].text.startswith("Tell me about your business in your own words")

    bp = await say(bp, "We run a small gym in Anna Nagar. Mostly monthly memberships, personal training "
                       "and some group classes.")
    # The kind is read from what they said — shown as "Looks like…", correctable.
    assert bp.category is not None and bp.category.subcategory_key == "gym"
    assert bp.category.source == "inferred" and bp.category.group == "Fitness & wellness"
    u = understanding(bp)
    assert u["business"]["category"] == "Gym" and u["business"]["category_source"] == "inferred"
    assert u["business"]["name_pending"] is True and u["business"]["name"] == ""
    # Understand first, then ask: a read-back, then the one missing essential.
    reply = bp.messages[-1].text
    assert reply.startswith("Got it — a gym in Anna Nagar")
    assert "What's the gym called?" in reply
    assert bp.asks[-1].ask == "name"

    bp = await say(bp, "Grit Barbell Club")
    assert not bp.name_pending and bp.identity["display_name"].value == "Grit Barbell Club"
    assert bp.messages[-1].text.startswith("Grit Barbell Club — lovely.")
    # Asked once, never again.
    assert sum(1 for a in bp.asks if a.ask == "name") == 1


@pytest.mark.asyncio
async def test_a_name_said_in_the_first_answer_is_never_asked_for() -> None:
    bp = unnamed()
    bp = await say(bp, "Grit Barbell Club is a strength gym in Velachery — powerlifting, strength classes "
                       "and personal training.")
    assert bp.identity["display_name"].value == "Grit Barbell Club" and not bp.name_pending
    assert not any(a.ask == "name" for a in bp.asks)
    assert "called?" not in bp.messages[-1].text


@pytest.mark.asyncio
async def test_building_needs_the_name_and_asks_for_it_instead_of_failing() -> None:
    bp = unnamed()
    bp = await say(bp, "We sell chicken, mutton and seafood by kg and deliver nearby.")
    bp = await say(bp, "That's all, build it.")
    assert "called?" in bp.messages[-1].text and bp.name_pending


# ------------------------------------------------------------ category first


def test_category_first_acknowledges_the_pick_and_asks_about_the_shop() -> None:
    bp = unnamed()
    bp.category = CategorySeed(category_key="fresh_grocery", subcategory_key="meat_shop", label="Meat shop",
                               group="Fresh food & grocery")
    Engine.open(bp)
    assert bp.messages[0].text.startswith("Got it — a meat shop. Tell me a little about the shop —")


# ------------------------------------------------------ changing the kind


@pytest.mark.asyncio
async def test_the_owner_corrects_the_kind_mid_interview_without_restarting() -> None:
    bp = unnamed()
    bp = await say(bp, "Grit Barbell Club is a gym in Anna Nagar with memberships and personal training. "
                       "People WhatsApp us to book a trial.")
    assert bp.category and bp.category.subcategory_key == "gym"
    asked_before = [a.ask for a in bp.asks]
    offers_before = understanding(bp)["offer"]["groups"]
    ready_before = bp.completion_state.ready_at

    bp = await say(bp, "No, actually we're mainly a physiotherapy centre with a small gym.")
    assert bp.category and bp.category.subcategory_key == "physiotherapy"
    assert bp.category.source == "owner_picked"
    assert bp.messages[-1].text.startswith("Got it — a physiotherapy centre. I've updated that.")
    # Nothing the owner said is lost, nothing is asked again, readiness never goes down.
    assert understanding(bp)["offer"]["groups"] == offers_before
    assert [a.ask for a in bp.asks][: len(asked_before)] == asked_before
    assert bp.completion_state.ready_at == ready_before or ready_before is None
    assert "physiotherapy" not in [a.ask for a in bp.asks]


def test_a_mention_of_customers_is_not_a_correction_of_the_kind() -> None:
    assert corrects_kind("No, actually we're mainly a physiotherapy centre")
    assert corrects_kind("We are not a gym, we're a yoga studio")
    assert not corrects_kind("Mostly textile mills and builders")
    assert not corrects_kind("We mostly sell chicken")


def test_structured_change_of_name_and_category() -> None:
    bp = unnamed()
    apply_correction(bp, "name", [], "Ishant Proteins")
    assert bp.identity["display_name"].value == "Ishant Proteins" and not bp.name_pending
    apply_correction(bp, "category", ["fresh_grocery", "meat_shop"])
    assert bp.category and bp.category.label == "Meat shop" and bp.category.source == "owner_picked"
    with pytest.raises(CorrectionError):
        apply_correction(bp, "category", ["no_such", "thing"])
    with pytest.raises(CorrectionError):
        apply_correction(bp, "name", [], "9876543210")


@pytest.mark.parametrize("text, name", [
    ("Grit Barbell Club is a strength gym in Velachery", "Grit Barbell Club"),
    ("We are Ishant Proteins, a meat shop in Chennai", "Ishant Proteins"),
    ("It's called Nalla Veedu Kitchen and we make meals", "Nalla Veedu Kitchen"),
    ("Aranya Homes builds villas and apartments on OMR", "Aranya Homes"),
    ("We sell chicken, mutton and seafood by kg", ""),
    ("We run a small gym in Anna Nagar", ""),
    ("This is Kavya, I make cakes at home", ""),
    ("Monthly 2500, quarterly 6500", ""),
])
def test_the_name_is_kept_only_when_it_is_plainly_said(text: str, name: str) -> None:
    assert business_name(text) == name


# ------------------------------------------------------ voice and text


@pytest.mark.asyncio
async def test_voice_then_text_then_voice_is_one_conversation() -> None:
    bp = unnamed()
    bp = await say(bp, "Ishant Proteins sells chicken, mutton and seafood by kg. People order on WhatsApp.",
                   via="voice")
    spoken_turn = bp.turn_count
    # A typed reply continues exactly where the spoken one left off.
    last_question = bp.asks[-1].ask
    bp = await say(bp, "We deliver around Nookampalayam and Perumbakkam, people can also pick up.")
    assert bp.turn_count == spoken_turn + 1
    assert [m.via for m in bp.messages if m.role == "user"] == ["voice", "text"]
    assert bp.asks[-1].ask != last_question  # never the same question twice
    bp = await say(bp, "Nookampalayam Road, Chennai. WhatsApp 8754722026.", via="voice")
    u = understanding(bp)
    assert [a["id"] for a in u["actions"]] == ["order_whatsapp"]
    assert u["contact"]["phone"] == "+91 87547 22026"
    assert not blocked_calls()


# ------------------------------------------ the old failures, never again


@pytest.mark.asyncio
async def test_equipment_never_becomes_an_action_and_all_india_never_becomes_hours() -> None:
    bp = unnamed()
    bp = await say(bp, "Wift is a gym equipment app. GYm equipment, available trainers, dumbells, contact section")
    bp = await say(bp, "All india")
    bp = await say(bp, "Freshness and energy")
    u = understanding(bp)
    labels = " ".join(a["label"] for a in u["actions"]).lower()
    assert "dumbbell" not in labels and "dumbell" not in labels and "equipment" not in labels
    assert "contact section" not in labels
    assert u["contact"]["hours"] == ""
    assert u["contact"]["phone"] == ""
    offered = " ".join(g["name"].lower() for g in u["offer"]["groups"])
    assert "contact section" not in offered
    assert any("contact" in c.lower() for c in u["content"])


# ------------------------------------------------ recorded voice for tests


def test_replay_voice_exists_only_while_paid_ai_is_switched_off(tmp_path, monkeypatch) -> None:
    script = tmp_path / "voice.json"
    script.write_text(json.dumps({"utterances": ["We sell chicken and mutton.", "Grit"]}), encoding="utf-8")
    monkeypatch.setenv("VOICE_PROVIDER", "replay")
    monkeypatch.setenv("LOCAH_VOICE_REPLAY_FILE", str(script))
    assert os.environ.get("LOCAH_TEST_NO_EXTERNAL_AI") == "1"
    assert voice.is_configured()
    monkeypatch.setenv("LOCAH_TEST_NO_EXTERNAL_AI", "0")
    assert not voice.is_configured()


@pytest.mark.asyncio
async def test_replay_voice_session_hands_out_utterances_and_no_credential(tmp_path, monkeypatch) -> None:
    script = tmp_path / "voice.json"
    script.write_text(json.dumps({"utterances": ["We sell chicken and mutton."]}), encoding="utf-8")
    monkeypatch.setenv("VOICE_PROVIDER", "replay")
    monkeypatch.setenv("LOCAH_VOICE_REPLAY_FILE", str(script))
    session = await voice.create_voice_session(unnamed())
    assert session == {"provider": "replay", "utterances": ["We sell chicken and mutton."], "expires_at": None}
    assert not blocked_calls()


@pytest.mark.parametrize(("said", "name"), [
    ("Hi, we are Thenkuzhal Bakes, a small bakery in Mylapore, Chennai. We bake breads.", "Thenkuzhal Bakes"),
    ("Hello! This is Saffron Table, a restaurant in Kochi", "Saffron Table"),
    ("Hi im ravi, we run Ravi Meat Stall in Adyar", "Ravi Meat Stall"),
    ("Vanakkam, naanga Grit Barbell Club, Velachery la gym", "Grit Barbell Club"),
    ("Good morning! Lotus Dental Care is a family dental clinic in Anna Nagar.", "Lotus Dental Care"),
    ("This is Kavya, I make cakes at home", ""),
    ("Hi, chicken mutton fish all available", ""),
    ("Biryani, parotta and meals available, call us", ""),
])
def test_the_name_is_heard_after_a_greeting_or_an_introduction(said: str, name: str) -> None:
    # Found by the owner-journey certification: "Hi, we are Thenkuzhal Bakes, …"
    # was asked "What's the bakery called?" eleven times.
    from platform_core.interview.reader import business_name

    assert business_name(said) == name


@pytest.mark.parametrize(("said", "name"), [
    ("Amber Room Salon in RS Puram, Coimbatore. Haircut, colour, facials and bridal makeup.", "Amber Room Salon"),
    ("Hearth & Honey Bakery in Aundh, Pune. Breads, baguettes, cookies.", "Hearth & Honey Bakery"),
    ("Fresh Chicken in Chromepet daily", ""),
    ("Best Salon in Coimbatore for brides", ""),
    ("Haircut in RS Puram", ""),
])
def test_a_name_that_ends_in_its_trade_is_heard_before_the_place(said: str, name: str) -> None:
    # Certification: the salon opened with its name and place and was still
    # asked "What's the salon called?".
    from platform_core.interview.reader import business_name

    assert business_name(said) == name


def test_a_name_that_ends_in_its_trade_still_says_what_kind_of_business_it_is() -> None:
    # Certification: once "Amber Room Salon" was heard as the name, the name was
    # taken out before reading the kind, and "bridal makeup" made the salon a
    # makeup artist's portfolio. A trade word ending the name stays as evidence.
    from platform_core.interview.models import Message
    from platform_core.interview.orchestrator import _update_category

    said = "Amber Room Salon in RS Puram, Coimbatore. Haircut, colour, facials and bridal makeup."
    bp = BusinessBlueprint(business_id=uuid.uuid4(), identity={
        "display_name": Fact(value="Amber Room Salon", source="USER_STATEMENT", confirmation="confirmed")})
    bp.messages = [Message(role="user", text=said)]
    _update_category(bp, said)
    assert bp.category is not None and bp.category.subcategory_key == "salon"

    gym = "Grit Barbell Club, a gym in Anna Nagar."
    bp = BusinessBlueprint(business_id=uuid.uuid4(), identity={
        "display_name": Fact(value="Grit Barbell Club", source="USER_STATEMENT", confirmation="confirmed")})
    bp.messages = [Message(role="user", text=gym)]
    _update_category(bp, gym)
    assert bp.category is not None and bp.category.subcategory_key == "gym"


def test_an_education_charity_asking_for_donations_and_volunteers_is_not_refused() -> None:
    # Certification: the NGO's first reply was "That request is not supported
    # today" (online donations — a built module — and volunteer sign-ups, which
    # the enquiry form takes), and it was read as a school selling fee plans.
    from platform_core.catalog.taxonomy import infer_from_text
    from platform_core.interview.capabilities import _gaps
    from platform_core.interview.models import CapabilityIntent

    said = ("Thozhi Learning Trust, Kannagi Nagar, Chennai. Free after-school learning centres for children, "
            "scholarships for girls. Need online donations and volunteer sign-ups.")
    assert infer_from_text(said) == ("education_ngo", 0.82)
    assert infer_from_text("After-school tuition for class 10 students in Adyar")[0] != "education_ngo"
    bp = BusinessBlueprint(business_id=uuid.uuid4())
    bp.requested_capabilities = [
        CapabilityIntent(intent="donations", original_request="Need online donations"),
        CapabilityIntent(intent="volunteer_signups", original_request="volunteer sign-ups"),
        CapabilityIntent(intent="live_drone_delivery", original_request="drone delivery"),
    ]
    assert [g.normalized_intent for g in _gaps(bp)] == ["live_drone_delivery"]
