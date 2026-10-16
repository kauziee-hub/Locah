"""Finding real photographs online for a website's picture slots.

LOCAH asks a stock-photo API rather than a general web search: a stock API
returns a direct image URL, its size, a description and the photographer, under
a licence meant for this use, where a web search returns pages and snippets and
the images on them are usually somebody's copyright. The API sits behind
`ImageSearchProvider` so another source can be added without touching the
retrieval loop (`website.image_retrieval`).

Search results are evidence to evaluate, never proof a picture is suitable, and
every string in them (description, photographer, page) is untrusted data.

Provider: Pexels (`IMAGE_SEARCH_PROVIDER=pexels`, `PEXELS_API_KEY`). The field
names below follow Pexels' published `/v1/search` response; nothing here has
been exercised against the live service without a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from platform_core.logging import get_logger

_log = get_logger("website.image_search")

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
# Hosts a candidate's image URL may point at. The URL comes from a third-party
# API response and is fetched (HEAD, thumbnail) by the server, so it is checked
# against an allowlist first: https only, and never an internal address.
DEFAULT_ALLOWED_HOSTS = "images.pexels.com"


@dataclass(frozen=True)
class ImageCandidate:
    """One photograph a search returned, with what is known about it."""

    provider: str
    photo_id: str
    image_url: str  # the full-size URL that would be placed in the website
    preview_url: str  # a small rendition for the vision check
    page_url: str  # where the photograph lives
    width: int
    height: int
    description: str  # the source's own words (untrusted)
    photographer: str
    average_color: str = ""
    licence: str = "Pexels licence"

    @property
    def ratio(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.photo_id}"


class ImageSearchProvider(Protocol):
    provider_name: str

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0) -> list[ImageCandidate]: ...


class ImageSearchError(RuntimeError):
    """The search service refused or failed. A slot with no result stays empty."""


def allowed_hosts() -> frozenset[str]:
    raw = os.getenv("IMAGE_ALLOWED_HOSTS", "").strip() or DEFAULT_ALLOWED_HOSTS
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def url_allowed(url: str) -> bool:
    """https, on an allowlisted host, with no credentials or odd port."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (parts.scheme == "https" and (parts.hostname or "").lower() in allowed_hosts()
            and not parts.username and not parts.password and parts.port in (None, 443))


def search_provider_name() -> str:
    return (os.getenv("IMAGE_SEARCH_PROVIDER") or "pexels").strip().lower()


def search_configured() -> bool:
    return search_provider_name() == "pexels" and bool(os.getenv("PEXELS_API_KEY", "").strip())


class PexelsSearch:
    provider_name = "pexels"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0) -> list[ImageCandidate]:
        params: dict[str, Any] = {"query": query[:120], "per_page": max(1, min(per_page, 40)), "page": page}
        if orientation in {"landscape", "portrait", "square"}:
            params["orientation"] = orientation
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(PEXELS_SEARCH_URL, params=params,
                                            headers={"Authorization": self._api_key})
        except Exception as exc:  # noqa: BLE001
            _log.warning("website.image_search.failed", provider="pexels", error=type(exc).__name__)
            raise ImageSearchError("the photo search could not be reached") from exc
        if response.status_code >= 400:
            _log.warning("website.image_search.failed", provider="pexels", status_code=response.status_code)
            raise ImageSearchError(f"the photo search refused the request ({response.status_code})")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImageSearchError("the photo search returned something that is not JSON") from exc
        return parse_pexels(payload)


def parse_pexels(payload: Any) -> list[ImageCandidate]:
    """Candidates from a Pexels response. A row that lacks a field is dropped."""
    photos = payload.get("photos") if isinstance(payload, dict) else None
    out: list[ImageCandidate] = []
    for photo in photos if isinstance(photos, list) else []:
        if not isinstance(photo, dict):
            continue
        raw_src = photo.get("src")
        src: dict[str, Any] = raw_src if isinstance(raw_src, dict) else {}
        full = str(src.get("large2x") or src.get("large") or src.get("original") or "")
        preview = str(src.get("medium") or src.get("small") or src.get("large") or "")
        try:
            width, height = int(photo.get("width") or 0), int(photo.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if not (photo.get("id") and full and preview and width > 0 and height > 0):
            continue
        out.append(ImageCandidate(
            provider="pexels", photo_id=str(photo["id"]), image_url=full, preview_url=preview,
            page_url=str(photo.get("url") or ""), width=width, height=height,
            description=str(photo.get("alt") or "")[:300], photographer=str(photo.get("photographer") or "")[:120],
            average_color=str(photo.get("avg_color") or "")[:9],
        ))
    return out


def get_search_provider() -> ImageSearchProvider | None:
    if search_provider_name() == "pexels":
        key = os.getenv("PEXELS_API_KEY", "").strip()
        if key:
            return PexelsSearch(key)
    return None
