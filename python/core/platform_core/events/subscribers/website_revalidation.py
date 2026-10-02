"""Tell the public web app that a business's website changed (Doc 12 §11.5,
§11.7, §17.2: "ISR with revalidation on WebsitePublished event").

The web app (apps/web) caches each published site and tags it
``website:{slug}``. Before this subscriber nothing ever invalidated that tag, so
a publish — or a module switched on or off, which changes which actions and
sections the live site may show — stayed invisible for up to the cache's
fallback window. The web app is a separate deployment, so it is told over HTTP
through its own revalidation endpoint, authenticated with a shared secret.

What it reacts to is what the site renders from: the published version, the
modules behind its actions and tool sections, the offerings and plans it lists,
the business's locations and identity. That is the Marketplace projection's
trigger set (subscribers/marketplace_index.py), plus the site's own languages.

Configuration (both or neither):
  WEB_REVALIDATE_URL     e.g. https://<web origin>/api/revalidate
  WEB_REVALIDATE_SECRET  the same value the web app has as REVALIDATE_SECRET
Without them (local development, tests) the handler does nothing and the web
app's own short fallback window applies.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.events.registry import EventContext, subscribe
from platform_core.events.subscribers.marketplace_index import TRIGGERS as MARKETPLACE_TRIGGERS
from platform_core.logging import get_logger

_log = get_logger("website.revalidate")

_TRIGGERS = tuple(dict.fromkeys(MARKETPLACE_TRIGGERS + ("website.languages.changed",)))


@subscribe(  # type: ignore[untyped-decorator]  # same mypy false positive as every @subscribe site
    "website.revalidate",
    *_TRIGGERS,
    description="Ask the public web app to drop its cached copy of the business's website",
)
async def revalidate(session: AsyncSession, event: EventContext) -> None:
    url = os.getenv("WEB_REVALIDATE_URL", "").strip()
    secret = os.getenv("WEB_REVALIDATE_SECRET", "").strip()
    if not url or not secret:
        return
    from platform_core.models import Business

    business = await session.get(Business, event.require_business_id())
    if business is None or not business.slug:
        return
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(url, json={"slug": business.slug, "reason": event.event_type},
                                 headers={"x-locah-revalidate-secret": secret})
    if resp.status_code >= 500:
        # The web app is down or restarting: retry with the outbox's backoff.
        raise RuntimeError(f"web revalidation returned {resp.status_code}")
    if resp.status_code >= 400:
        # A wrong secret or URL is a deployment mistake; retrying cannot fix it.
        _log.warning("website.revalidate_refused", status=resp.status_code, slug=business.slug)
