"""After the website exists, talking to LOCAH changes it — against a real database.

Build a meat shop's first website through the ordinary interview (no model:
every turn takes the deterministic path), then edit it by talking:
"make it warmer", "don't show prices", "put delivery higher", "we also sell
prawns", "that isn't our story" (and the new story). Each edit must land in
the stored draft as structured change — theme, section content, order,
visibility — never as generated source.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from test_start_conversation import owner  # noqa: F401 — the signed-in owner fixture

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")


class Talk:
    def __init__(self, client: TestClient, headers: dict[str, str], business_id: str) -> None:
        self.client, self.headers, self.id = client, headers, business_id
        self.revision = client.get(f"/v1/b/{business_id}/interview", headers=headers).json()["data"][
            "blueprint"]["revision"]

    def send(self, action: str, **body: Any) -> dict[str, Any]:
        res = self.client.post(f"/v1/b/{self.id}/interview", headers=self.headers, json={
            "revision": self.revision, "request_id": str(uuid.uuid4()), "action": action, **body})
        assert res.status_code == 200, res.text
        data: dict[str, Any] = res.json()["data"]
        self.revision = data["blueprint"]["revision"]
        return data

    def say(self, text: str) -> dict[str, Any]:
        return self.send("turn", text=text)

    def site(self) -> dict[str, Any]:
        res = self.client.get(f"/v1/b/{self.id}/website", headers=self.headers)
        assert res.status_code == 200, res.text
        draft: dict[str, Any] = res.json()["data"]["draft"]
        return draft


def sections(draft: dict[str, Any]) -> list[dict[str, Any]]:
    home = next(p for p in draft["pages"] if p["slug"] == "home")
    return list(home["sections"])


def every_section(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """The home page's sections, then each inner page's (the story lives on /about)."""
    pages = sorted(draft["pages"], key=lambda p: p["slug"] != "home")
    return [s for p in pages for s in p["sections"]]


def of(draft: dict[str, Any], section_type: str) -> dict[str, Any]:
    return next(s for s in every_section(draft) if s["section_type_id"] == section_type)


def test_talking_after_the_website_exists_changes_it(owner) -> None:  # noqa: F811
    with TestClient(app) as client:
        started = client.post("/v1/platform/businesses/start", headers=owner, json={
            "category_key": "fresh_grocery", "subcategory_key": "meat_shop"}).json()["data"]
        business_id = started["business"]["id"]
        headers = {**owner, "X-Business-Id": business_id, "X-Operating-Context": "business"}
        talk = Talk(client, headers, business_id)
        talk.say("Ishant Proteins is a meat shop. We sell chicken, mutton and fish by the kg and people "
                 "order on WhatsApp.")
        talk.send("correct", slot="name", values=[], text="Ishant Proteins")
        talk.say("We deliver around Nookampalayam and Perumbakkam, people can also pick up from the shop.")
        talk.say("Nookampalayam Road, Chennai. WhatsApp 8754722026.")
        data = talk.send("catalogue", catalogue=[{"group": "Chicken", "price": "240", "unit": "per kg"}])
        assert data["build_available"] is True
        data = talk.send("build")
        assert data["blueprint"]["completion_state"]["status"] == "built"
        before = talk.site()
        first_family = before["theme"].get("design_family")
        assert first_family

        # "Make it warmer": the palette (and if needed the family) changes; nothing else.
        data = talk.say("Can you make the website warmer?")
        assert data["blueprint"]["messages"][-1]["text"].startswith("Done — I've made the website warmer")
        assert data["blueprint"]["completion_state"]["status"] == "built"
        warmer = talk.site()
        assert warmer["theme"].get("palette_hue") in {"orange", "red", "yellow", "pink"} or \
            warmer["theme"].get("palette_key") in {"terracotta_olive", "forest_turmeric", "butter_green"}
        assert of(warmer, "hero")["content"]["headline"] == of(before, "hero")["content"]["headline"]

        # "Don't show prices": no price anywhere in the range.
        talk.say("Don't show prices on the website.")
        range_ = of(talk.site(), "product_showcase" if any(
            s["section_type_id"] == "product_showcase" for s in sections(talk.site())) else "category_showcase")
        text = str(range_["content"])
        assert "₹" not in text and "240" not in text

        # "Put delivery higher": how ordering works comes right after the hero.
        talk.say("Put delivery higher please.")
        order = [s["section_type_id"] for s in sections(talk.site())]
        assert order[0] == "hero" and order[1] == "fulfilment_strip", order

        # "We also sell prawns": a new item, in the group it belongs to.
        data = talk.say("We also sell prawns.")
        assert "prawns" in data["blueprint"]["messages"][-1]["text"].lower()
        assert "Prawns" in str(talk.site())

        # "That isn't our story", then the story.
        data = talk.say("That isn't our story.")
        assert "What would you like people to know" in data["blueprint"]["messages"][-1]["text"]
        data = talk.say("We have cut meat fresh every morning for eight years, only after you order.")
        # The story is told where this site's design tells it: an About section,
        # or the home page's statement — the owner's sentence, set large. Saying
        # "that's your story on the website now" must mean it is there.
        story = next(s for s in every_section(talk.site())
                     if s["section_type_id"] in {"about", "statement"} and "eight years" in str(s["content"]))
        assert story["is_visible"] is True
