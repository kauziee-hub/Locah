"""Empty lists speak about THIS business: its own items, whether its website
can bring the first one in yet, and what to do now — in the Workspace's
language."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.services.empty_states import WORDS, compose
from platform_testing.phase_b import create_business, new_identity

client = TestClient(app)


def test_a_cafe_with_items_and_no_website_yet() -> None:
    out = compose(sellable=["Banana Walnut Bread", "Filter Coffee", "Pasta"], bookable=[], all_items=["Banana Walnut Bread"],
                  site_live=False, customers_word="Customers")
    assert out["orders"]["body"] == ("When someone orders Banana Walnut Bread or Filter Coffee — once your website "
                                     "is published, it lands here.")
    assert [a["href"] for a in out["orders"]["actions"]] == ["/website", "/orders/new"]
    # Nothing to book yet: the first step, not a promise.
    assert out["bookings"]["actions"] == [{"label": "Add a service", "href": "/offerings/new"}]


def test_a_salon_with_a_live_website() -> None:
    out = compose(sellable=[], bookable=["Haircut", "Bridal makeup"], all_items=["Haircut", "Bridal makeup"],
                  site_live=True, customers_word="Clients")
    assert out["bookings"]["body"] == ("When a customer picks a time for Haircut or Bridal makeup from your website, "
                                       "it appears here for you to confirm.")
    assert out["bookings"]["actions"] == []  # nothing to do: the website already takes them
    assert out["customers"]["title"] == "No clients yet" and out["customers"]["body"].startswith("Clients appear")
    assert out["orders"]["actions"][0]["href"] == "/offerings/new"


@pytest.mark.parametrize("lang", ["ta", "hi"])
def test_every_language_has_every_word(lang: str) -> None:
    assert set(WORDS[lang]) == set(WORDS["en"])
    out = compose(sellable=["Dosa"], bookable=["Haircut"], all_items=["Dosa"], site_live=False,
                  customers_word="Customers", lang=lang)
    assert "Dosa" in out["orders"]["body"] and "Haircut" in out["bookings"]["body"]
    # Nothing listed yet: the enquiry line still reads as a sentence, never a gap.
    bare = compose(sellable=[], bookable=[], all_items=[], site_live=False, customers_word="Customers", lang=lang)
    assert WORDS[lang]["what_you_offer"] in bare["leads"]["body"] and "  " not in bare["leads"]["body"]


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
def test_the_api_names_the_business_items(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("offerings-catalog", "orders"))
    client.post(f"/v1/platform/businesses/{bid}/products", json={
        "title": "Filter Coffee", "offering_type": "menu_item", "status": "active", "visibility": "public",
        "price_amount": 40, "price_type": "fixed"}, headers=owner)
    r = client.get(f"/v1/platform/businesses/{bid}/empty-states", headers=owner)
    assert r.status_code == 200, r.text
    assert "Filter Coffee" in r.json()["data"]["orders"]["body"]
    ta = client.get(f"/v1/platform/businesses/{bid}/empty-states?lang=ta", headers=owner).json()["data"]
    assert ta["orders"]["title"] == WORDS["ta"]["orders_title"]
    assert client.get(f"/v1/platform/businesses/{bid}/empty-states?lang=fr", headers=owner).status_code == 422
