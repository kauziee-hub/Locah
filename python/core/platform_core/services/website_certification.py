"""Website quality certification: a verdict on one exact draft, and the publish rule.

A built draft is rendered, judged against the reference standard and gated
(pass / repair / fail_closed) — today by the certification harness
(platform_testing.certify), later by a certification worker. The verdict is
recorded with a fingerprint of the draft it judged, so any edit after it
leaves the certificate stale.

``WEBSITE_CERTIFICATION`` decides what publish does with it:

- ``off`` (default) — certification is not consulted;
- ``record`` — publish goes ahead; a missing, stale or failed certificate is
  logged, so a run can say which sites *would* have been held back;
- ``enforce`` — publish refuses a draft without a current passing certificate,
  and the refusal carries the gate's requests to the owner ("We need 2–3
  photographs of your actual clinic…") instead of a weak site going live.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ValidationError
from platform_core.logging import get_logger
from platform_core.models import WebsiteCertification, WebsiteVersion
from platform_core.resolvers.website_resolver import WebsiteResolver

Mode = Literal["off", "record", "enforce"]
STATUSES = frozenset({"pass", "repair", "fail_closed"})


def mode() -> Mode:
    value = os.getenv("WEBSITE_CERTIFICATION", "off").strip().lower()
    return value if value in {"record", "enforce"} else "off"  # type: ignore[return-value]


async def fingerprint(session: AsyncSession, *, version_id: uuid.UUID) -> str:
    """What a visitor would be shown from this draft: theme, navigation, every
    page and every section's content, order and visibility. Ids and timestamps
    are left out, so the same site rebuilt identically keeps its print."""
    version = await session.get(WebsiteVersion, version_id)
    if version is None:
        raise ValidationError("That website draft does not exist")
    pages: list[dict[str, Any]] = []
    for page in await WebsiteResolver.list_pages(session, version_id=version_id):
        sections = await WebsiteResolver.list_sections(session, page_id=page.id)
        pages.append({
            "slug": page.slug, "title": page.title, "type": page.page_type, "seo": [page.seo_title,
                                                                                 page.seo_description],
            "og": str(page.og_image_asset_id or ""), "live": page.is_published, "order": page.sort_order,
            "sections": [{
                "type": s.section_type_id, "variant": s.layout_variant, "content": s.content,
                "binding": s.module_binding, "order": s.sort_order, "visible": s.is_visible,
            } for s in sorted(sections, key=lambda s: (s.sort_order, str(s.id)))],
        })
    canonical = json.dumps({"theme": version.theme, "navigation": version.navigation,
                            "pages": sorted(pages, key=lambda p: (p["order"], p["slug"]))},
                           sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WebsiteCertificationService:
    @staticmethod
    async def record(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        verdict: dict[str, Any],
        source: str,
        result: dict[str, Any] | None = None,
    ) -> WebsiteCertification:
        """Record the gate's verdict on the business's current draft."""
        status = str(verdict.get("status") or "")
        if status not in STATUSES:
            raise ValidationError("A certification verdict is pass, repair or fail_closed",
                                  details={"status": status})
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id)
        requests = [str(r)[:600] for r in verdict.get("owner_requests") or []][:6]
        row = WebsiteCertification(
            business_id=business_id, website_id=website.id, version_id=draft.id,
            fingerprint=await fingerprint(session, version_id=draft.id), status=status,
            score=float(verdict["score"]) if isinstance(verdict.get("score"), (int, float)) else None,
            blocked_on=verdict.get("blocked_on") if verdict.get("blocked_on") in {"owner", "platform"} else None,
            owner_requests=requests,
            result=result if result is not None else {
                k: verdict.get(k) for k in ("reasons", "counts", "dimension_failures", "thresholds",
                                            "rounds_used", "max_rounds", "owner_request_details")
                if verdict.get(k) is not None},
            source=source[:60],
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def current(session: AsyncSession, *, business_id: uuid.UUID) -> dict[str, Any] | None:
        """The latest verdict on the current draft, and whether it still describes it."""
        website = await WebsiteResolver.resolve_website(session, business_id=business_id)
        draft = await WebsiteResolver.resolve_draft_version(
            session, business_id=business_id, website_id=website.id)
        row = (await session.execute(
            select(WebsiteCertification)
            .where(WebsiteCertification.business_id == business_id,
                   WebsiteCertification.website_id == website.id)
            .order_by(WebsiteCertification.created_at.desc()).limit(1)
        )).scalars().first()
        if row is None:
            return None
        stale = row.version_id != draft.id or row.fingerprint != await fingerprint(session, version_id=draft.id)
        return {
            "status": row.status, "score": float(row.score) if row.score is not None else None,
            "blocked_on": row.blocked_on, "owner_requests": list(row.owner_requests or []),
            "stale": stale, "source": row.source, "certified_at": row.created_at.isoformat()
            if row.created_at else None,
        }

    @staticmethod
    async def assert_publishable(session: AsyncSession, *, business_id: uuid.UUID) -> None:
        """The publish rule for the current ``WEBSITE_CERTIFICATION`` mode."""
        current_mode = mode()
        if current_mode == "off":
            return
        found = await WebsiteCertificationService.current(session, business_id=business_id)
        if found is None:
            reason, message = "certification_missing", (
                "Your website is still being checked against LOCAH's quality standard. "
                "It goes live as soon as it passes.")
        elif found["stale"]:
            reason, message = "certification_stale", (
                "Your website changed since it was last checked. It is checked again before it goes live.")
        elif found["status"] != "pass":
            reason, message = "certification_failed", (
                "Your website is not at LOCAH's quality standard yet, so it has not gone live. "
                + (" ".join(found["owner_requests"][:2]) if found["owner_requests"]
                   else "LOCAH is improving it and will check it again."))
        else:
            return
        if current_mode == "record":
            get_logger("website.certification").warning(
                "website.publish_uncertified", business_id=str(business_id), reason=reason)
            return
        raise ValidationError(message, details={
            "reason": reason,
            "owner_requests": (found or {}).get("owner_requests") or [],
            "score": (found or {}).get("score"),
        })
