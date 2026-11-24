"""May the edge proxy issue a TLS certificate for this host? (Caddy on-demand TLS)

Every business is served at `{slug}.<PLATFORM_DOMAIN>`, so certificates are
issued on a host's first visit rather than up front. Before issuing, the proxy
asks here (`ask` in infra/deploy/oracle/Caddyfile); only LOCAH's own hosts and
the slug of a business with a published, undeleted website get a yes — anyone
can point a name at the server, and a certificate authority's rate limits must
not be spent on made-up ones.

200: issue. 404: do not. No body either way; nothing about a business leaks.
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_core.context_resolver import bind_public_context
from platform_core.models import Website
from platform_core.services.business import BusinessService

router = APIRouter(prefix="/v1/public/tls", tags=["edge"])

# LOCAH's own surfaces under the platform domain.
OWN_HOSTS = ("", "www", "app", "api", "admin")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def platform_domain() -> str:
    domain = (os.getenv("PLATFORM_DOMAIN") or "").strip().lower().rstrip(".")
    return domain if "." in domain and not domain.replace(".", "").isdigit() else ""


@router.get("/allowed", status_code=200)
async def tls_allowed(
    domain: str = Query(default="", max_length=253),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    platform = platform_domain()
    host = domain.strip().lower().rstrip(".")
    if not platform or not (host == platform or host.endswith("." + platform)):
        return Response(status_code=404)
    label = host[: -len(platform)].rstrip(".")
    if label in OWN_HOSTS:
        return Response(status_code=200)
    if not _LABEL.fullmatch(label):
        return Response(status_code=404)
    # The same steps and test as the public renderer (WebsitePublishService.
    # load_public_page): the API connects as the RLS-enforcing platform_api role,
    # which sees a website only inside its own business's public context.
    business = await BusinessService.get_by_slug(session, label)
    if business is None or business.deleted_at is not None:
        return Response(status_code=404)
    await bind_public_context(session, business.id)
    published = (await session.execute(
        select(Website.id).where(Website.business_id == business.id, Website.status == "published",
                                 Website.published_version_id.is_not(None)).limit(1))).first()
    return Response(status_code=200 if published else 404)
