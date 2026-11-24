"""The drawing rule: a drawn picture never pretends to be the business.

Founder's firm rule (Website Quality Program, 2026-11-24): generated images may
show scenery, the region, mood, texture or abstract art — never rooms, food,
dishes, staff, products, interiors or amenities a visitor would read as the
real business. Real things come from the owner's uploads or from stock.

Found the day it was written: a hotel's drawn cover came back as a bedroom, and
the stay's "passages" were briefed as breakfast on a veranda and a coffee cup.
Enforced twice — in what a build asks for (`drawing_for`) and at the provider
boundary for every caller (`unsafe_drawing`).
"""

from __future__ import annotations

import base64

import httpx
import pytest
from test_interview_language import Down, blueprint

from platform_core.interview.creative_director import direct
from platform_core.interview.media_director import draw_missing, drawing_for, plan_slots
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine
from platform_core.website import image_generation
from platform_core.website.image_generation import brand_logo_prompt, logo_prompt
from platform_core.website.media_prompts import ShootBrief, build_prompt, unsafe_drawing

pytestmark = pytest.mark.usefixtures("stubbed_ai_transport")

TRADES = [
    ("Pepper Vine Kitchen", "restaurant", "pepper vine kichen kochi, kerala food biriyani appam stew, we deliver",
     "chicken biriyani 240 appam 50 duck roast 420 veg stew 180"),
    ("Crumb & Co", None, "crumb and co bakery in adyar chennai, fresh bread puffs and cakes daily",
     "plum cake 450 veg puff 25 sourdough loaf 180"),
    ("Glow Studio", "salon", "glow studio salon in rs puram coimbatore, haircut facial bridal makeup",
     "ladies cut 900 gents 450 facial 1500"),
    ("Mistwood Estate Retreat", "hotel",
     "mistwood estate retreat coorg madikeri, 14 rooms in our cofee estate, cottages + pool vilas",
     "bunglow room 7500 valley cotage 9500 pool vila 18500 per nite"),
    ("Grit Barbell Club", "gym", "grit barbell club, strength gym in indiranagar bangalore, coaching",
     "monthly 2500 quarterly 6500 personal training 8000"),
    ("Sunrise Dental", "clinic", "sunrise dental clinic in t nagar chennai, cleaning, braces, implants",
     "cleaning 800 braces consult 500 implants from 25000"),
    ("Neelambari Handlooms", "retail", "neelambari handlooms kanchipuram silk sarees and cotton sarees shop",
     "kanchi silk saree 12000 cotton saree 1800"),
    ("Raghavan & Co", "professional_service", "raghavan and co chartered accountants in mylapore, gst, audit",
     "gst filing 1500 a month, audit on quote"),
]


async def _owner(name: str, kind: str | None, opening: str, catalogue: str):  # noqa: ANN202
    bp = blueprint(name)
    for said in (opening, catalogue):
        bp = await Engine.turn(bp, said, provider=Down(), business_type=kind)
    return bp


def _their_things(bp) -> list[str]:  # noqa: ANN001
    names = [g.name for g in bp.taxonomy.groups] + [i.name for g in bp.taxonomy.groups for i in g.items]
    return [n.casefold() for n in names if n and len(n) >= 4]


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "kind", "opening", "catalogue"), TRADES, ids=[t[0] for t in TRADES])
async def test_no_drawing_shows_what_the_business_sells_or_has(
        name: str, kind: str | None, opening: str, catalogue: str) -> None:
    bp = await _owner(name, kind, opening, catalogue)
    direction = direct(bp, kind)
    mood = [s for s in plan_slots(bp, direction) if s.truth_class == "mood"]
    assert mood, "every site has a cover"
    for slot in mood:
        prompt = drawing_for(slot, bp, direction)
        assert unsafe_drawing(prompt) == "", (name, slot.key, prompt)
        low = prompt.casefold()
        assert not any(thing in low for thing in _their_things(bp)), (name, slot.key, prompt)


@pytest.mark.asyncio
async def test_a_stays_drawn_cover_is_its_regions_open_land() -> None:
    from platform_core.interview.models import Fact

    bp = await _owner(*TRADES[3][:2], *TRADES[3][2:])
    bp.known_facts["locations"] = Fact(value="Madikeri, Coorg", source="USER_STATEMENT", confirmation="confirmed")
    direction = direct(bp, "hotel")
    hero = next(s for s in plan_slots(bp, direction) if s.key == "hero")
    prompt = drawing_for(hero, bp, direction)
    assert "hills" in prompt and "Coorg" in prompt and "landscape" in prompt


@pytest.mark.asyncio
async def test_a_build_draws_mood_slots_only() -> None:
    bp = await _owner(*TRADES[0])
    asked: list[str] = []

    async def drawer(prompt: str, aspect: str) -> tuple[None, str]:
        asked.append(prompt)
        return None, "unavailable"

    drawn = await draw_missing(bp, direct(bp, "restaurant"), "restaurant", draw=drawer)
    assert drawn and all(slot.truth_class == "mood" for slot, _, _ in drawn)
    assert all(unsafe_drawing(p) == "" for p in asked), asked


BRIEF = ShootBrief(world="home-style South Indian food in clay bowls", light="soft daylight", lens="50mm",
                   grade="warm", palette=())


@pytest.mark.parametrize("subject", [
    "chicken biriyani in a clay pot", "a hotel bedroom with a king bed", "a stylist cutting hair",
    "the shop's shelves of sarees", "breakfast on a veranda table", "a strength gym interior",
])
def test_the_boundary_names_what_a_prompt_would_show(subject: str) -> None:
    assert unsafe_drawing(build_prompt(subject=subject, purpose="hero", truth_class="mood", brief=BRIEF,
                                       trade="business"))


def test_a_logo_is_not_a_scene_and_passes() -> None:
    assert unsafe_drawing(logo_prompt(initial="M", primary="#1f3d34")) == ""
    assert unsafe_drawing(brand_logo_prompt(name="Pepper Vine Kitchen", category="restaurant")) == ""


class _Recorder:
    def __init__(self) -> None:
        self.calls = 0

    def client(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        recorder = self

        class _Client:
            async def __aenter__(self):  # noqa: ANN204
                return self

            async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
                return False

            async def post(self, url, headers, json):  # noqa: ANN001, ANN201
                recorder.calls += 1
                return httpx.Response(200, json={"result": {"image": base64.b64encode(b"\xff\xd8").decode()},
                                                 "success": True})

        return _Client()


@pytest.mark.asyncio
async def test_an_unsafe_drawing_is_refused_before_any_provider_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_core.website.image_generation import draw_fallback, generate_image

    recorder = _Recorder()
    monkeypatch.setattr(image_generation.httpx, "AsyncClient", recorder.client)
    monkeypatch.setenv("IMAGE_FALLBACK", "cloudflare")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    unsafe = build_prompt(subject="a plate of appam and stew", purpose="hero", truth_class="mood", brief=BRIEF,
                          trade="restaurant")
    assert await draw_fallback(unsafe) == (None, "rejected")
    assert await generate_image(unsafe) == (None, "rejected")
    assert recorder.calls == 0


@pytest.mark.asyncio
async def test_a_place_led_sites_passages_are_different_views_of_its_land() -> None:
    """Three "light on a plain wall" passages came back as one empty room three times."""
    bp = await _owner(*TRADES[3])
    direction = direct(bp, "hotel")
    mood = [s for s in plan_slots(bp, direction) if s.truth_class == "mood"]
    prompts = [drawing_for(s, bp, direction) for s in mood]
    assert len(set(prompts)) == len(prompts), prompts
    assert all(unsafe_drawing(p) == "" for p in prompts)


def test_a_wall_or_floor_is_an_interior() -> None:
    assert unsafe_drawing(build_prompt(subject="soft light across a plain wall", purpose="story",
                                       truth_class="mood", brief=BRIEF, trade="business"))


@pytest.mark.asyncio
async def test_a_drawing_is_labelled_with_the_provider_that_drew_it() -> None:
    """Cloudflare drawings were recorded as gemini_generated (audit, 2026-11-24)."""
    from uuid import uuid4

    from platform_core.interview.media_director import plan_media, record
    from platform_core.website.image_generation import GeneratedImage, drawn_by

    flux = GeneratedImage(mime_type="image/jpeg", bytes=b"", model="@cf/black-forest-labs/flux-1-schnell",
                          latency_ms=1, prompt="")
    nano = GeneratedImage(mime_type="image/png", bytes=b"", model="gemini-3.1-flash-image", latency_ms=1, prompt="")
    assert (drawn_by(flux), drawn_by(nano)) == ("cloudflare", "gemini")

    bp = await _owner(*TRADES[3])
    direction = direct(bp, "hotel")
    plan_media(bp, direction)
    hero = next(s for s in plan_slots(bp, direction) if s.key == "hero")
    record(bp, hero, uuid4(), drawn_by="cloudflare")
    assert next(p for p in bp.media_plan if p.key == "hero").source == "cloudflare_generated"
    plan_media(bp, direction)  # re-planned (a rebuild): still who drew it
    assert next(p for p in bp.media_plan if p.key == "hero").source == "cloudflare_generated"
