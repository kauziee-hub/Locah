"""The edge proxy issues a certificate only for LOCAH's hosts and live business sites.

Run it as the RLS-enforcing platform_api role (TEST_API_DATABASE_URL, as CI does):
with the postgres bypass role a first version passed here and refused every
business in production, because RLS hid the website row.

Caddy's on-demand TLS asks /v1/public/tls/allowed before issuing for a host it
has not seen (infra/deploy/oracle/Caddyfile). A made-up subdomain, a business
whose site is not published, a nested name or another domain gets a 404.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi.testclient import TestClient
from platform_api.main import app
from test_website_certification import _business_with_draft, _run, owner  # noqa: F401


def _slug(bid: str) -> str:
    async def read(factory: Any) -> str:
        from platform_core.models import Business

        async with factory() as session:
            business = await session.get(Business, uuid.UUID(bid))
            assert business is not None
            return str(business.slug)

    return str(_run(read))


def _allowed(client: TestClient, domain: str) -> int:
    return int(client.get("/v1/public/tls/allowed", params={"domain": domain}).status_code)


def test_only_locah_hosts_and_published_sites_get_a_certificate(
        owner: dict[str, str], monkeypatch: Any) -> None:  # noqa: F811
    monkeypatch.setenv("WEBSITE_CERTIFICATION", "off")
    monkeypatch.setenv("PLATFORM_DOMAIN", "locah.store")
    client = TestClient(app)
    live = _business_with_draft(client, owner)
    assert client.post(f"/v1/b/{live}/website/publish", headers=owner).status_code == 200
    # A business has a public URL once it is unlisted (or discoverable); a fresh one is private.
    assert client.post(f"/v1/b/{live}/marketplace/visibility", json={"visibility": "unlisted"},
                       headers=owner).status_code == 200
    draft_only = _business_with_draft(client, owner)
    assert client.post(f"/v1/b/{draft_only}/marketplace/visibility", json={"visibility": "unlisted"},
                       headers=owner).status_code == 200
    private = _business_with_draft(client, owner)
    assert client.post(f"/v1/b/{private}/website/publish", headers=owner).status_code == 200

    for host in ("locah.store", "www.locah.store", "app.locah.store", "API.locah.store.", "admin.locah.store"):
        assert _allowed(client, host) == 200, host
    # A certificate exactly when the public renderer serves the site. A private
    # business is hidden by RLS, so it is refused only on the platform_api role.
    rls = bool(os.environ.get("API_DATABASE_URL"))
    for bid, expected in ((live, 200), (draft_only, 404), (private, 404 if rls else None)):
        page = client.get(f"/v1/public/websites/{_slug(bid)}").status_code
        assert _allowed(client, f"{_slug(bid)}.locah.store") == page
        if expected is not None:
            assert page == expected
    for host in ("nobody-here-xyz.locah.store", f"a.{_slug(live)}.locah.store", f"{_slug(live)}.example.com",
                 "evil-locah.store", "", "-bad-.locah.store"):
        assert _allowed(client, host) == 404, host


def test_without_a_platform_domain_nothing_is_issued(monkeypatch: Any) -> None:
    monkeypatch.setenv("PLATFORM_DOMAIN", "localhost")
    assert _allowed(TestClient(app), "localhost") == 404
