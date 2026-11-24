"""The static hard gates over every current draft and published site, read-only.

    DATABASE_URL=postgresql+asyncpg://postgres@localhost:54329/locah_certify \\
        uv run --no-env-file --project apps/api python tools/certify/shadow_gate.py

Prints one line per site: which gates it fails and why. Nothing is written.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from platform_core.models import Business, MediaAsset, WebsiteVersion
from platform_core.services.website_certification import _draft_pages
from platform_core.website import quality_gate


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost" not in url and "127.0.0.1" not in url:
        sys.exit("DATABASE_URL must point at a local database")
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    held = 0
    async with factory() as session:
        rows = (await session.execute(
            select(WebsiteVersion, Business.slug)
            .join(Business, Business.id == WebsiteVersion.business_id)
            .where(WebsiteVersion.superseded_at.is_(None),
                   WebsiteVersion.version_type.in_(("draft", "published")))
            .order_by(Business.slug, WebsiteVersion.version_type))).all()
        for version, slug in rows:
            pages = await _draft_pages(session, version.id)
            ids = [uuid.UUID(a) for p in pages for s in p["sections"]
                   for a, _ in quality_gate.pictures(s["content"]) if len(a) == 36]
            sources = {str(i): str(t) for i, t in (await session.execute(
                select(MediaAsset.id, MediaAsset.source_type).where(MediaAsset.id.in_(ids)))).all()} if ids else {}
            verdict = quality_gate.check(pages, sources)
            held += verdict["status"] != "pass"
            print(f"{verdict['status']:6} {version.version_type:9} {slug}")
            for f in verdict["failures"][:6]:
                print(f"         {f['gate']:18} {f['page']:12} {f.get('section', ''):18} {f['detail'][:90]}")
        print(f"\n{held} of {len(rows)} would be held back by the static gates")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
