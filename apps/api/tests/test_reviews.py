"""P1-09 review API trust path, exercised through the real restricted API role."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from platform_api.main import app
from platform_core.services.reviews import review_token
from platform_testing.phase_b import create_business, drain_events, new_identity, primary_location, sql

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)


def _reviewable_order(monkeypatch: Any) -> tuple[str, str, str, dict[str, str]]:
    _, owner = new_identity(monkeypatch)
    business_id = create_business(client, owner, modules=(
        "offerings-catalog", "orders", "payments", "customer-relationships",
    ))
    assert sql("SELECT activation_state FROM business_module_states WHERE business_id = :b AND module_id = 'reviews'",
               b=business_id) == [("active",)]
    visible = client.post(f"/v1/b/{business_id}/marketplace/visibility",
                          json={"visibility": "unlisted"}, headers=owner)
    assert visible.status_code == 200, visible.text
    base = f"/v1/platform/businesses/{business_id}"
    product_resp = client.post(f"{base}/products", json={
        "status": "active", "offering_type": "product", "title": "Notebook", "price_amount": 120,
    }, headers=owner)
    assert product_resp.status_code == 200, product_resp.text
    product = product_resp.json()["data"]
    contact_resp = client.post(f"{base}/customers", json={
        "display_name": "Anika Rao", "phone": "+919876501231",
    }, headers=owner)
    assert contact_resp.status_code == 200, contact_resp.text
    contact = contact_resp.json()["data"]
    created = client.post(f"{base}/orders", json={
        "location_id": primary_location(client, owner, business_id),
        "customer_contact_id": contact["id"],
        "items": [{"offering_id": product["id"], "quantity": 1}],
    }, headers=owner)
    assert created.status_code == 200, created.text
    order_id = created.json()["data"]["id"]
    for status in ("accepted", "preparing", "ready", "completed"):
        changed = client.post(f"{base}/orders/{order_id}/status", json={"status": status}, headers=owner)
        assert changed.status_code == 200, changed.text
    drain_events(business_id)
    invitation_id = sql("""SELECT id FROM reviews_invitations
                           WHERE business_id = :b AND source_id = :source""",
                        b=business_id, source=order_id)[0][0]
    token = review_token(UUID(business_id), invitation_id)
    slug = sql("SELECT slug FROM businesses WHERE id = :b", b=business_id)[0][0]
    return business_id, str(slug), token, owner


@DB
def test_reviewer_writes_and_updates_but_business_only_replies_features_and_reports(monkeypatch: Any) -> None:
    business_id, slug, token, owner = _reviewable_order(monkeypatch)
    public = f"/v1/public/websites/{slug}"
    base = f"/v1/platform/businesses/{business_id}"

    link = client.get(f"{public}/review/{token}")
    assert link.status_code == 200, link.text
    assert link.headers["cache-control"] == "no-store, private"
    assert link.json()["data"]["state"] == "open"
    written = client.post(f"{public}/review/{token}", json={"rating": 2, "body": "Delivery was late"})
    assert written.status_code == 200, written.text
    review = written.json()["data"]["review"]
    review_id = review["id"]
    assert review["rating"] == 2 and review["verified"] == "Verified order"
    assert client.post(f"{public}/review/{token}", json={"rating": 5}).status_code == 409

    public_list = client.get(f"{public}/reviews")
    assert public_list.status_code == 200, public_list.text
    assert public_list.json()["data"]["average"] == 2.0
    assert public_list.json()["data"]["count"] == 1
    business_list = client.get(f"{base}/reviews", headers=owner)
    assert business_list.status_code == 200, business_list.text
    assert business_list.json()["data"]["reviews"][0]["customer"]["phone"]
    home = client.get(f"{base}/home", headers=owner)
    assert home.status_code == 200, home.text
    needs = next(b for b in home.json()["data"]["bands"] if b["key"] == "now")
    low_item = next(i for i in needs["items"] if i["label"] == "low reviews waiting for your reply")
    assert "+919876501231" in low_item["detail"]
    assert client.put(f"{base}/reviews/{review_id}", json={"rating": 5}, headers=owner).status_code in {404, 405}
    assert client.delete(f"{base}/reviews/{review_id}", headers=owner).status_code in {404, 405}

    reply = client.put(f"{base}/reviews/{review_id}/reply", json={"body": "We are sorry and will call."},
                       headers=owner)
    assert reply.status_code == 200, reply.text
    home_after_reply = client.get(f"{base}/home", headers=owner).json()["data"]
    needs_after_reply = next(b for b in home_after_reply["bands"] if b["key"] == "now")
    assert all(i["label"] != "low reviews waiting for your reply" for i in needs_after_reply["items"])
    featured = client.put(f"{base}/reviews/{review_id}/feature", json={"featured": True}, headers=owner)
    assert featured.status_code == 200, featured.text
    assert client.get(f"{public}/reviews?featured=true").json()["data"]["count"] == 1
    # Featuring changes the strip, never the denominator of the true average.
    assert client.get(f"{public}/reviews?featured=true").json()["data"]["average"] == 2.0
    changed = client.put(f"{public}/review/{token}", json={"rating": 4, "body": "They fixed the delay"})
    assert changed.status_code == 200, changed.text
    assert client.get(f"{public}/reviews").json()["data"]["average"] == 4.0

    report = client.post(f"{base}/reviews/{review_id}/report",
                         json={"reason": "personal_data", "note": "Contains an address"}, headers=owner)
    assert report.status_code == 200, report.text
    assert report.json()["data"]["status"] == "open"


@DB
def test_declined_invitation_cannot_be_written(monkeypatch: Any) -> None:
    business_id, slug, token, _ = _reviewable_order(monkeypatch)
    url = f"/v1/public/websites/{slug}/review/{token}"
    declined = client.post(f"{url}/decline")
    assert declined.status_code == 200, declined.text
    assert declined.json()["data"]["state"] == "declined"
    assert client.post(url, json={"rating": 5}).status_code == 409
    # A fabricated token cannot read another customer review or even reveal
    # whether its business slug is valid.
    assert client.get(f"/v1/public/websites/{slug}/review/{'x' * 32}").status_code == 404
    assert sql("SELECT count(*) FROM reviews_reviews WHERE business_id = :b", b=business_id) == [(0,)]


@DB
def test_expired_or_no_longer_completed_interaction_cannot_be_reviewed(monkeypatch: Any) -> None:
    business_id, slug, token, _ = _reviewable_order(monkeypatch)
    url = f"/v1/public/websites/{slug}/review/{token}"
    sql("""UPDATE reviews_invitations SET expires_at = now() - interval '1 second'
           WHERE business_id = :b""", b=business_id)
    assert client.get(url).json()["data"]["state"] == "expired"
    assert client.post(url, json={"rating": 5}).status_code == 409

    sql("""UPDATE reviews_invitations SET expires_at = now() + interval '1 day'
           WHERE business_id = :b""", b=business_id)
    sql("""UPDATE orders_orders SET status = 'cancelled'
           WHERE id = (SELECT source_id FROM reviews_invitations WHERE business_id = :b LIMIT 1)""",
        b=business_id)
    assert client.post(url, json={"rating": 5}).status_code == 422
    assert sql("SELECT count(*) FROM reviews_reviews WHERE business_id = :b", b=business_id) == [(0,)]


@DB
def test_only_moderator_removes_and_reviewer_can_appeal_once(monkeypatch: Any) -> None:
    business_id, slug, token, owner = _reviewable_order(monkeypatch)
    url = f"/v1/public/websites/{slug}/review/{token}"
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR1EAAAAASUVORK5CYII="
    created = client.post(url, json={"rating": 1, "body": "Call me at 9999999999",
                                     "photos": [{"media_type": "image/png", "data_base64": png}]})
    assert created.status_code == 200, created.text
    review_id = created.json()["data"]["review"]["id"]
    photo_id = created.json()["data"]["review"]["photos"][0]
    base = f"/v1/platform/businesses/{business_id}"
    reported = client.post(f"{base}/reviews/{review_id}/report", json={"reason": "personal_data"}, headers=owner)
    assert reported.status_code == 200, reported.text
    assert client.get("/v1/admin/reviews/queue", headers=owner).status_code == 403
    assert client.post(f"/v1/admin/reviews/{review_id}/remove",
                       json={"reason": "personal_data"}, headers=owner).status_code == 403
    assert client.get(f"/v1/public/websites/{slug}/reviews/photos/{photo_id}").status_code == 200
    assert client.get(f"{base}/reviews/photos/{photo_id}", headers=owner).status_code == 200
    assert client.get(f"/v1/admin/reviews/photos/{photo_id}", headers=owner).status_code == 403

    admin_id, admin = new_identity(monkeypatch)
    sql("""INSERT INTO platform_admin_grants (identity_id, granted_by, reason)
           VALUES (:id, :id, 'Review moderation integration test')""", id=str(admin_id))
    queue = client.get("/v1/admin/reviews/queue", headers=admin)
    assert queue.status_code == 200, queue.text
    assert any(r["review"]["id"] == review_id for r in queue.json()["data"]["reports"])
    assert client.get(f"/v1/admin/reviews/photos/{photo_id}", headers=admin).status_code == 200
    photo_removed = client.post(f"/v1/admin/reviews/photos/{photo_id}/remove", headers=admin)
    assert photo_removed.status_code == 200, photo_removed.text
    assert client.get(f"/v1/public/websites/{slug}/reviews/photos/{photo_id}").status_code == 404
    removed = client.post(f"/v1/admin/reviews/{review_id}/remove",
                          json={"reason": "personal_data", "note": "Remove the phone number"}, headers=admin)
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["status"] == "removed"
    assert client.get(f"/v1/public/websites/{slug}/reviews").json()["data"]["count"] == 0
    assert client.get(url).json()["data"]["review"]["can_appeal"] is True
    appealed = client.post(f"{url}/appeal", json={"note": "Please remove my phone number instead"})
    assert appealed.status_code == 200, appealed.text
    assert client.post(f"{url}/appeal", json={"note": "Trying again"}).status_code == 409
    restored = client.post(f"/v1/admin/reviews/{review_id}/appeal",
                           json={"restore": True, "note": "Restored after review"}, headers=admin)
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["status"] == "published"
    assert client.get(f"/v1/public/websites/{slug}/reviews").json()["data"]["count"] == 1


@DB
def test_restricted_database_role_cannot_edit_rating_or_delete_review(monkeypatch: Any) -> None:
    business_id, slug, token, _ = _reviewable_order(monkeypatch)
    url = f"/v1/public/websites/{slug}/review/{token}"
    review_id = client.post(url, json={"rating": 3, "body": "A real review"}).json()["data"]["review"]["id"]
    # The RLS-enforcing `platform_api` connection: TEST_API_DATABASE_URL locally (the
    # database guard copies it to API_DATABASE_URL), API_DATABASE_URL in CI — and
    # only ever a local database.
    from platform_testing.database_guard import _is_local

    api_url = os.environ.get("TEST_API_DATABASE_URL") or os.environ.get("API_DATABASE_URL")
    if not api_url or not _is_local(api_url):
        pytest.skip("a local API_DATABASE_URL (platform_api role) is required for the restricted-role check")

    async def check() -> None:
        engine = create_async_engine(api_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT set_config('app.current_business_id', :b, true)"),
                                         {"b": business_id})
                with pytest.raises(DBAPIError):
                    await connection.execute(text("UPDATE reviews_reviews SET rating = 5 WHERE id = :id"),
                                             {"id": review_id})
                await connection.rollback()
                await connection.execute(text("SELECT set_config('app.current_business_id', :b, true)"),
                                         {"b": business_id})
                with pytest.raises(DBAPIError):
                    await connection.execute(text("DELETE FROM reviews_reviews WHERE id = :id"),
                                             {"id": review_id})
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())
    assert sql("SELECT rating FROM reviews_reviews WHERE id = :id", id=review_id) == [(3,)]
