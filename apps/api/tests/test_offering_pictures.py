"""Pictures for real offerings (work order §17).

An offering the owner adds after the site was built can get a picture from the
Offering page: drawn through the existing provider abstraction (stubbed here at
its boundary — the image bytes and the storage upload), stored as a real media
asset marked as a LOCAH draft, and attached to the offering through the
catalogue's own update. What must hold:

* the picture is of this offering (its title is the subject), saved as a
  generated draft with its slot, and listed on the offering with its url;
* earlier pictures are kept, the new one goes first;
* it is the catalogue's update: version moves, `offering.updated` is published;
* the public website shows it for that offering;
* without a working image provider nothing is attached and the owner is told
  to upload instead; another business's offering is never touched.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.website.image_generation import GeneratedImage
from platform_testing.phase_b import create_business, new_identity, sql

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
JPEG = GeneratedImage(mime_type="image/jpeg", bytes=b"\xff\xd8 drawn", model="stub", latency_ms=1, prompt="")


@pytest.fixture
def drawn(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import platform_core.media.supabase_storage as storage
    import platform_core.services.website_images as website_images

    prompts: list[str] = []

    async def generate(prompt: str, *, aspect_ratio: str = "16:9", **_: Any) -> GeneratedImage:
        prompts.append(prompt)
        return JPEG

    monkeypatch.setattr(website_images, "generate_image_bytes", generate)
    monkeypatch.setattr(storage, "put_generated_object", AsyncMock())
    monkeypatch.setattr(storage, "public_url", lambda bucket, key: f"https://storage.test/{bucket}/{key}")
    return prompts


def _shop(monkeypatch: Any) -> tuple[dict[str, str], str, str]:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, business_type="restaurant", modules=("offerings-catalog",))
    assert client.post(f"/v1/b/{bid}/marketplace/visibility", json={"visibility": "unlisted"},
                       headers=owner).status_code == 200
    item = client.post(f"/v1/platform/businesses/{bid}/products", json={
        "title": "Paneer Biryani", "offering_type": "menu_item", "status": "active", "visibility": "public",
        "price_amount": 220, "price_type": "fixed"}, headers=owner).json()["data"]
    return owner, bid, str(item["id"])


def test_an_owner_can_draw_a_picture_of_a_real_offering(monkeypatch: Any, drawn: list[str]) -> None:
    owner, bid, item = _shop(monkeypatch)
    base = f"/v1/platform/businesses/{bid}/products/{item}"
    version = client.get(base, headers=owner).json()["data"]["version"]

    r = client.post(f"{base}/generate-image", headers=owner)
    assert r.status_code == 200, r.text
    first = r.json()["data"]
    assert first["ok"] is True
    assert "Paneer Biryani" in drawn[0]  # the subject is the offering itself
    source, slot, approval, purpose = sql(
        "select source_type, generated_for, approval_state, purpose from media_assets where id = cast(:a as uuid)",
        a=first["asset"]["id"])[0]
    assert (source, slot, approval, purpose) == ("gemini_generated", f"offering:{item}", "draft", "offering")

    got = client.get(base, headers=owner).json()["data"]
    assert got["version"] == version + 1
    assert got["image_asset_ids"] == [first["asset"]["id"]]
    assert got["images"][0]["url"].startswith("https://storage.test/media/") and got["images"][0]["draft"] is True
    assert sql("select count(*) from platform_outbox_events where event_type = 'offering.updated' "
               "and payload->>'offering_id' = :o", o=item)[0][0] >= 1

    second = client.post(f"{base}/generate-image", headers=owner).json()["data"]
    ids = client.get(base, headers=owner).json()["data"]["image_asset_ids"]
    assert ids == [second["asset"]["id"], first["asset"]["id"]]  # newest first, nothing dropped

    slug = sql("select slug from businesses where id = cast(:b as uuid)", b=bid)[0][0]
    [row] = client.get(f"/v1/public/websites/{slug}/offerings").json()["data"]["offerings"]
    assert row["image_url"] == got["images"][0]["url"].replace(first["asset"]["id"], second["asset"]["id"])


def test_without_an_image_provider_nothing_is_attached(monkeypatch: Any) -> None:
    owner, bid, item = _shop(monkeypatch)
    base = f"/v1/platform/businesses/{bid}/products/{item}"
    r = client.post(f"{base}/generate-image", headers=owner)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["ok"] is False and data["reason"] == "generation_unavailable" and "upload" in data["detail"]
    assert client.get(base, headers=owner).json()["data"]["image_asset_ids"] == []


def test_another_business_offering_is_never_touched(monkeypatch: Any, drawn: list[str]) -> None:
    _, _, item = _shop(monkeypatch)
    other, other_bid, _ = _shop(monkeypatch)
    r = client.post(f"/v1/platform/businesses/{other_bid}/products/{item}/generate-image", headers=other)
    assert r.status_code == 404
    assert drawn == []
