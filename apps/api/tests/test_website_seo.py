"""Local SEO facts on the public website payload (award-sites conversion-seo.md).

The web app builds each page's JSON-LD, title and share card from
`business.place` and `business.trade`. These tests prove the API hands over the
main location's own saved facts — the week's hours as HH:MM spans, the address
in parts, the map pin, the town people search by — and the trade from the
platform taxonomy, and nothing it was not given.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_testing.phase_b import TEST_JWT_SECRET, new_identity

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")

client = TestClient(app)

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat")
SPLIT_DAY = [["11:00", "15:00"], ["18:30", "23:00"]]
ADDRESS = {"line1": "12, 2nd Avenue", "locality": "Anna Nagar", "city": "Chennai", "state": "Tamil Nadu",
           "postal_code": "600040", "country": "IN"}


@pytest.fixture
def owner(monkeypatch: Any) -> dict[str, str]:
    monkeypatch.setenv("WEBSITE_PREVIEW_SECRET", TEST_JWT_SECRET)
    return cast(dict[str, str], new_identity(monkeypatch)[1])


def _business(owner: dict[str, str], **kind: str) -> tuple[str, str]:
    body: dict[str, Any] = {"display_name": f"Seo Co {uuid.uuid4().hex[:8]}",
                            "business_type": kind.pop("business_type", "other"), **kind}
    made = client.post("/v1/platform/businesses", json=body, headers=owner)
    assert made.status_code == 200, made.text
    business = made.json()["data"]["business"]
    shown = client.post(f"/v1/b/{business['id']}/marketplace/visibility", json={"visibility": "unlisted"},
                        headers=owner)
    assert shown.status_code == 200, shown.text
    return str(business["id"]), str(business["slug"])


def _publish(bid: str, owner: dict[str, str]) -> None:
    published = client.post(f"/v1/b/{bid}/website/publish", headers=owner)
    assert published.status_code == 200, published.text


def _save_location(bid: str, owner: dict[str, str], **fields: Any) -> None:
    loc = client.get(f"/v1/platform/businesses/{bid}/locations", headers=owner).json()["data"][0]["id"]
    saved = client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}", headers=owner, json=fields)
    assert saved.status_code == 200, saved.text


def _home(slug: str) -> dict[str, Any]:
    page = client.get(f"/v1/public/websites/{slug}")
    assert page.status_code == 200, page.text
    return cast(dict[str, Any], page.json()["data"])


def _set_cover_line(bid: str, owner: dict[str, str], eyebrow: str) -> None:
    """The home page's cover (its first hero) says where the business is."""
    site = client.get(f"/v1/b/{bid}/website", headers=owner).json()["data"]
    home = next(p for p in site["draft"]["pages"] if p["slug"] == "home")
    hero = next((s for s in home.get("sections") or [] if s["section_type_id"] == "hero"), None)
    content = {"headline": "Biryani, slow-cooked", "eyebrow": eyebrow}
    if hero is None:
        added = client.post(f"/v1/b/{bid}/website/pages/{home['id']}/sections", headers=owner,
                            json={"section_type_id": "hero", "content": content})
        assert added.status_code == 200, added.text
        return
    patched = client.patch(f"/v1/b/{bid}/website/sections/{hero['id']}", headers=owner,
                           json={"content": {**(hero.get("content") or {}), **content}})
    assert patched.status_code == 200, patched.text


def test_the_payload_carries_the_locations_week_address_pin_town_and_trade(owner: dict[str, str]) -> None:
    bid, slug = _business(owner, business_type="restaurant", category_key="food_service",
                          subcategory_key="biryani_shop")
    _publish(bid, owner)
    _save_location(bid, owner, address=ADDRESS, timezone="Asia/Kolkata", latitude=13.085, longitude=80.21,
                   hours={**{d: SPLIT_DAY for d in WEEKDAYS}, "note": "Closed on Pongal"})

    data = _home(slug)
    place = data["business"]["place"]
    # The week exactly as saved: HH:MM spans per day, Sunday left out (closed),
    # the note is words, not hours.
    assert place["hours"] == {d: SPLIT_DAY for d in WEEKDAYS}
    assert place["timezone"] == "Asia/Kolkata"
    assert place["geo"] == {"lat": 13.085, "lng": 80.21}
    assert place["address_parts"] == {"street": "12, 2nd Avenue", "area": "Anna Nagar", "city": "Chennai",
                                      "state": "Tamil Nadu", "postal_code": "600040", "country": "IN"}
    assert place["locality"] == "Anna Nagar, Chennai"
    # The words a visitor reads are unchanged beside the facts.
    assert place["address"] == "12, 2nd Avenue, Anna Nagar, Chennai, Tamil Nadu, 600040"
    assert place["hours_summary"].startswith("Mon") and "Sun closed" in place["hours_summary"]
    assert data["business"]["trade"] == {"category": "food_service", "subcategory": "biryani_shop",
                                         "label": "Biryani shop", "playbook": "restaurant"}
    # The facts travel on the business, never into a section's stored content.
    for section in data["page"]["sections"]:
        assert not {"hours", "geo", "address_parts", "timezone", "locality"} & set(section["content"])


def test_nothing_saved_means_nothing_said(owner: dict[str, str]) -> None:
    bid, slug = _business(owner, business_type="retail")
    _publish(bid, owner)

    business = _home(slug)["business"]
    place = business.get("place") or {}
    assert not {"hours", "timezone", "geo", "address_parts"} & set(place)
    assert "locality" not in place
    assert business["trade"] is None


def test_a_digital_only_business_keeps_its_hours_but_gives_no_address_or_pin(owner: dict[str, str]) -> None:
    bid, slug = _business(owner, business_type="education", category_key="education",
                          subcategory_key="tuition_centre")
    _publish(bid, owner)
    _save_location(bid, owner, address=ADDRESS, latitude=13.085, longitude=80.21, timezone="Asia/Kolkata",
                   hours={d: [["16:00", "20:00"]] for d in WEEKDAYS})
    traits = client.patch(f"/v1/platform/businesses/{bid}/traits", headers=owner,
                          json={"traits": {"digital_only": True}})
    assert traits.status_code == 200, traits.text

    data = _home(slug)
    place = data["business"]["place"]
    assert data["capabilities"]["show_address"] is False
    assert place["hours"] == {d: [["16:00", "20:00"]] for d in WEEKDAYS}
    assert not {"address", "address_parts", "geo"} & set(place)
    # The city it works from, never the street or the neighbourhood.
    assert place["locality"] == "Chennai"


def test_the_town_comes_from_the_cover_only_when_it_names_a_known_town(owner: dict[str, str]) -> None:
    said, slug = _business(owner, business_type="salon", category_key="beauty", subcategory_key="salon")
    _set_cover_line(said, owner, "RS Puram, Coimbatore")
    _publish(said, owner)
    assert _home(slug)["business"]["place"]["locality"] == "RS Puram, Coimbatore"

    unsure, other = _business(owner, business_type="salon", category_key="beauty", subcategory_key="salon")
    _set_cover_line(unsure, owner, "Since 1987")
    _publish(unsure, owner)
    assert "locality" not in (_home(other)["business"].get("place") or {})
