"""Finding real photographs online for a website's picture slots.

LOCAH asks a photo API rather than a general web search: it returns a direct
image URL, its size, a description, the photographer and the licence, where a web
search returns pages and snippets and the images on them are usually somebody's
copyright. Sources sit behind `ImageSearchProvider` so one can be swapped for
another without touching the retrieval loop (`website.image_retrieval`):

* `commons` — Wikimedia Commons. No key. Only freely licensed files (public
  domain, CC0, CC BY, CC BY-SA); the licence and credit travel with each result.
* `pexels` — Pexels. Needs `PEXELS_API_KEY` (their key signup may be paused).

`IMAGE_SEARCH_PROVIDER=auto` (the default) uses Pexels when a key is set and
Commons otherwise.

Search results are evidence to evaluate, never proof a picture is suitable, and
every string in them (description, photographer, page) is untrusted data.

The field names below follow each service's published response; the Pexels path
has not been exercised against the live service without a key.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from platform_core.logging import get_logger

_log = get_logger("website.image_search")

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
# Hosts a candidate's image URL may point at. The URL comes from a third-party
# API response and is fetched (HEAD, thumbnail) by the server, so it is checked
# against an allowlist first: https only, and never an internal address.
DEFAULT_ALLOWED_HOSTS = "images.pexels.com,upload.wikimedia.org,thumb.wikimedia.org"
# Licences a Commons file may carry (prefix match, lower case). Non-commercial
# and no-derivatives variants are always refused: a business site is commercial.
DEFAULT_ALLOWED_LICENCES = "public domain,cc0,pd,cc by"
SOURCE_NAMES = {"pexels": "Pexels", "commons": "Wikimedia Commons"}
# Wikimedia asks every client to say who it is.
USER_AGENT = "LOCAH-web-builder/1.0 (https://locah.store; image search for small-business websites)"


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

    def credit_line(self) -> str:
        """Who made it, where it is from and under what licence — kept with the asset."""
        source = SOURCE_NAMES.get(self.provider, self.provider.title())
        who = self.photographer or "Unknown author"
        line = f"{who} via {source}"
        return f"{line} ({self.licence})" if self.provider != "pexels" and self.licence else line

    @property
    def ratio(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.photo_id}"


class ImageSearchProvider(Protocol):
    provider_name: str
    # How to word a query for this service; shown to the query writer.
    query_hint: str

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
    """The source in use: the configured one, or for `auto` Pexels if keyed, else Commons."""
    chosen = (os.getenv("IMAGE_SEARCH_PROVIDER") or "auto").strip().lower()
    if chosen == "auto":
        return "pexels" if os.getenv("PEXELS_API_KEY", "").strip() else "commons"
    return chosen


def search_configured() -> bool:
    name = search_provider_name()
    return name == "commons" or (name == "pexels" and bool(os.getenv("PEXELS_API_KEY", "").strip()))


def licence_ok(name: str) -> bool:
    low = " ".join(name.casefold().split())
    if not low or "-nc" in low or "-nd" in low or " nc" in low or " nd" in low:
        return False
    allowed = [a.strip().casefold() for a in
               (os.getenv("IMAGE_ALLOWED_LICENCES", "").strip() or DEFAULT_ALLOWED_LICENCES).split(",") if a.strip()]
    return any(low.startswith(a) for a in allowed)


class PexelsSearch:
    provider_name = "pexels"
    query_hint = "Two to five plain words describing what the photograph shows."

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


def _plain(value: Any) -> str:
    """Text from a Commons metadata field, which arrives as HTML."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


class CommonsSearch:
    """Wikimedia Commons file search. No key; freely licensed files only."""

    provider_name = "commons"
    FULL_WIDTH = 1280  # one standard thumbnail width serves as both the check and the page
    # Commons matches EVERY word against a file's title and description: a long
    # descriptive query finds nothing, a short one finds the right file.
    query_hint = ("One to three plain nouns, e.g. 'fresh chicken' or 'butcher counter'. Every word must appear "
                  "in a file's title or description, so never add adjectives, settings or lighting words.")

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0) -> list[ImageCandidate]:
        """The query as given; if nothing matches every word, the same query with fewer."""
        words = query.split()
        attempts = [query] + [" ".join(words[:n]) for n in (3, 2) if 1 < n < len(words)]
        for attempt in attempts:
            found = await self._search(attempt, per_page=per_page, page=page, timeout_seconds=timeout_seconds)
            if found:
                return found
        return []

    async def _search(self, query: str, *, per_page: int, page: int, timeout_seconds: float) -> list[ImageCandidate]:
        size = max(1, min(per_page, 50))
        params: dict[str, Any] = {
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{query[:120]} filetype:bitmap", "gsrlimit": size, "gsroffset": (page - 1) * size,
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": self.FULL_WIDTH,
            "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription|Credit",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(COMMONS_API_URL, params=params, headers={"User-Agent": USER_AGENT})
        except Exception as exc:  # noqa: BLE001
            _log.warning("website.image_search.failed", provider="commons", error=type(exc).__name__)
            raise ImageSearchError("the photo search could not be reached") from exc
        if response.status_code >= 400:
            _log.warning("website.image_search.failed", provider="commons", status_code=response.status_code)
            raise ImageSearchError(f"the photo search refused the request ({response.status_code})")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImageSearchError("the photo search returned something that is not JSON") from exc
        return parse_commons(payload)


def parse_commons(payload: Any) -> list[ImageCandidate]:
    """Candidates from a Commons response, best match first. Anything that is not a
    photograph-shaped, freely licensed file with a usable thumbnail is dropped."""
    query = payload.get("query") if isinstance(payload, dict) else None
    pages = query.get("pages") if isinstance(query, dict) else None
    rows = sorted((p for p in (pages.values() if isinstance(pages, dict) else []) if isinstance(p, dict)),
                  key=lambda p: int(p.get("index") or 0))
    out: list[ImageCandidate] = []
    for row in rows:
        infos = row.get("imageinfo")
        info = infos[0] if isinstance(infos, list) and infos and isinstance(infos[0], dict) else {}
        raw_meta = info.get("extmetadata")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}

        def field(name: str, meta: dict[str, Any] = meta) -> str:
            item = meta.get(name)
            return _plain(item.get("value") if isinstance(item, dict) else "")

        licence = field("LicenseShortName")
        thumb = str(info.get("thumburl") or "")
        try:
            width, height = int(info.get("width") or 0), int(info.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if (info.get("mime") != "image/jpeg" or not thumb or width <= 0 or height <= 0
                or not licence_ok(licence)):
            continue
        title = re.sub(r"^File:|\.[A-Za-z]{3,4}$", "", str(row.get("title") or "")).replace("_", " ")
        # The page gets the 1280px rendition; the vision check only needs to see the
        # subject, so it gets a 500px one (a few tens of KB instead of a few hundred).
        preview = re.sub(r"/\d+px-", "/500px-", thumb, count=1) if "/thumb/" in thumb else thumb
        out.append(ImageCandidate(
            provider="commons", photo_id=str(row.get("pageid") or title), image_url=thumb, preview_url=preview,
            page_url=str(info.get("descriptionurl") or ""), width=width, height=height,
            description=f"{title}. {field('ImageDescription')}"[:300], photographer=field("Artist")[:120],
            licence=licence[:60],
        ))
    return out


def get_search_provider() -> ImageSearchProvider | None:
    name = search_provider_name()
    if name == "commons":
        return CommonsSearch()
    if name == "pexels":
        key = os.getenv("PEXELS_API_KEY", "").strip()
        if key:
            return PexelsSearch(key)
    return None
