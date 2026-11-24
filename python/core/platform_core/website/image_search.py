"""Finding real photographs for a website's picture slots: Unsplash and Pixabay.

LOCAH asks photo APIs rather than a general web search: each returns a direct
image URL, its size, a description or tags, the photographer and the licence.
Sources sit behind `ImageSearchProvider`, normalised into one `ImageCandidate`,
so the retrieval loop (`website.image_retrieval`) and the website never see a
provider's own response shape:

* `unsplash` — editorial photography; the stronger source for a hero, a story
  or a cinematic picture. Needs `UNSPLASH_ACCESS_KEY` (server only; the secret
  key is for OAuth, which public search does not use). Its rules: show the
  photo from the URL Unsplash returns (hotlink, never re-host), credit the
  photographer and Unsplash with referral links, and call the photo's
  `download_location` when the photo is chosen for a site — not when it is
  merely found (`track_selection`).
* `pixabay` — breadth for specific products, categories and niche trades.
  Needs `PIXABAY_API_KEY` (server only). Its rules: cache searches for 24
  hours, and never hotlink permanently — a chosen picture is copied into
  LOCAH's own storage (`ImageCandidate.must_store`); credit the source.
* `multi` (the default) — both, side by side: for a slot that matters both are
  searched and their candidates compete in one pool; the judge picks.

A provider with no key is skipped; with none at all, real photographs are not
configured and the site is built without them. Search results are evidence to
evaluate, never proof a picture is suitable, and every string in them is
untrusted data. Keys never appear in a log line or an error message.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from platform_core.logging import get_logger

_log = get_logger("website.image_search")

UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/"
# Unsplash asks that every link back to it carries these, utm_source being the
# registered app's name ("LOCAH Website Builder", registered 2026-11-24).
REFERRAL = {"utm_source": "locah_website_builder", "utm_medium": "referral"}
# Hosts a candidate's image URL may point at. The URL comes from a third-party
# API response and is fetched (HEAD, thumbnail) by the server, so it is checked
# against an allowlist first: https only, and never an internal address.
DEFAULT_ALLOWED_HOSTS = "images.unsplash.com,api.unsplash.com,pixabay.com,cdn.pixabay.com"
SOURCE_NAMES = {"unsplash": "Unsplash", "pixabay": "Pixabay"}
SOURCE_HOMES = {"unsplash": "https://unsplash.com/", "pixabay": "https://pixabay.com/"}
USER_AGENT = "LOCAH-web-builder/1.0 (https://locah.store; image search for small-business websites)"
# Pixabay requires searches to be cached for 24 hours; its picture links stay
# valid about as long, so a cached result is never older than that.
CACHE_TTL_SECONDS = 23 * 3600
# Unsplash's demo tier allows 50 requests an hour: leave room for the
# download tracking of the photos a build chooses.
UNSPLASH_RESERVE = 6


def _with_query(url: str, **params: Any) -> str:
    """`url` with `params` added (existing ones such as Unsplash's ixid kept)."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True)
class ImageCandidate:
    """One photograph a search returned, with what is known about it."""

    provider: str
    photo_id: str
    image_url: str  # Unsplash: the URL the site shows (hotlinked). Pixabay: the file to copy into storage.
    preview_url: str  # a small rendition for the vision check
    page_url: str  # where the photograph lives at the source
    width: int
    height: int
    description: str  # the source's own words or tags (untrusted)
    photographer: str
    average_color: str = ""
    licence: str = ""
    photographer_url: str = ""
    download_location: str = ""  # Unsplash: called when the photo is chosen
    query: str = ""  # the search that found it

    @property
    def ratio(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.photo_id}"

    @property
    def must_store(self) -> bool:
        """Pixabay forbids permanent hotlinking: a chosen picture is copied into storage."""
        return self.provider == "pixabay"

    def credit_line(self) -> str:
        who = self.photographer or "Unknown photographer"
        if self.provider == "unsplash":
            return f"Photo by {who} on Unsplash"
        if self.provider == "pixabay":
            return f"Image by {who} from Pixabay"
        return f"{who} via {SOURCE_NAMES.get(self.provider, self.provider.title())}"

    def credit(self) -> dict[str, str]:
        """What the website shows to credit the picture, with the links each source asks for."""
        home = SOURCE_HOMES.get(self.provider, "")
        referral = self.provider == "unsplash"
        return {
            "line": self.credit_line(),
            "name": self.photographer or "Unknown photographer",
            "name_url": _with_query(self.photographer_url, **REFERRAL) if self.photographer_url and referral
            else self.photographer_url,
            "source": SOURCE_NAMES.get(self.provider, self.provider.title()),
            "source_url": _with_query(home, **REFERRAL) if home and referral else home,
            "page_url": self.page_url,
        }


class ImageSearchProvider(Protocol):
    provider_name: str
    # How to word a query for this service; shown to the query writer.
    query_hint: str

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0, fresh: bool = False) -> list[ImageCandidate]: ...

    async def track_selection(self, candidate: ImageCandidate) -> None: ...


class ImageSearchError(RuntimeError):
    """The search service refused or failed. A slot with no result stays empty."""


# --------------------------------------------------------------------- caching
class SearchCache(Protocol):
    def get(self, key: str) -> list[dict[str, Any]] | None: ...

    def put(self, key: str, rows: list[dict[str, Any]]) -> None: ...


class MemoryCache:
    """Searches kept for CACHE_TTL_SECONDS in this process. Pixabay requires a
    24-hour cache; an identical query in a re-render costs no request."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS, limit: int = 4000) -> None:
        self._rows: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._ttl, self._limit = ttl, limit

    def get(self, key: str) -> list[dict[str, Any]] | None:
        hit = self._rows.get(key)
        if hit is None or time.monotonic() - hit[0] > self._ttl:
            self._rows.pop(key, None)
            return None
        return hit[1]

    def put(self, key: str, rows: list[dict[str, Any]]) -> None:
        if len(self._rows) >= self._limit:
            for stale in sorted(self._rows, key=lambda k: self._rows[k][0])[: self._limit // 10]:
                self._rows.pop(stale, None)
        self._rows[key] = (time.monotonic(), rows)


_CACHE: SearchCache = MemoryCache()


def set_search_cache(cache: SearchCache) -> None:
    """Swap the process cache (a shared store in production, a fresh one in tests)."""
    global _CACHE
    _CACHE = cache


def _cache_key(provider: str, query: str, orientation: str, per_page: int, page: int) -> str:
    raw = f"{provider}|{' '.join(query.casefold().split())}|{orientation}|{per_page}|{page}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cached(provider: str, query: str, orientation: str, per_page: int, page: int,
            fresh: bool) -> list[ImageCandidate] | None:
    if fresh:
        return None
    rows = _CACHE.get(_cache_key(provider, query, orientation, per_page, page))
    if rows is None:
        return None
    try:
        return [ImageCandidate(**row) for row in rows]
    except TypeError:
        return None


def _remember(provider: str, query: str, orientation: str, per_page: int, page: int,
              found: list[ImageCandidate]) -> None:
    _CACHE.put(_cache_key(provider, query, orientation, per_page, page), [asdict(c) for c in found])


# --------------------------------------------------------------------- hosts
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


# --------------------------------------------------------------------- Unsplash
_UNSPLASH_ORIENTATION = {"landscape": "landscape", "portrait": "portrait", "square": "squarish"}


class UnsplashSearch:
    provider_name = "unsplash"
    query_hint = ("A short phrase of what the photograph shows and how it feels, the way an editor would "
                  "search, e.g. 'fresh fish on crushed ice dark moody' or 'baker shaping sourdough morning light'.")

    def __init__(self, access_key: str) -> None:
        self._key = access_key
        self.remaining: int | None = None  # requests left this hour, from the last response

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Client-ID {self._key}", "Accept-Version": "v1", "User-Agent": USER_AGENT}

    def _note_limit(self, response: httpx.Response) -> None:
        try:
            self.remaining = int(response.headers.get("X-Ratelimit-Remaining", ""))
        except ValueError:
            pass

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0, fresh: bool = False) -> list[ImageCandidate]:
        size = max(1, min(per_page, 30))
        cached = _cached(self.provider_name, query, orientation, size, page, fresh)
        if cached is not None:
            return cached
        if self.remaining is not None and self.remaining <= UNSPLASH_RESERVE:
            raise ImageSearchError("unsplash hourly limit nearly used up")
        params: dict[str, Any] = {"query": query[:120], "page": page, "per_page": size,
                                  "order_by": "relevant", "content_filter": "high"}
        if orientation in _UNSPLASH_ORIENTATION:
            params["orientation"] = _UNSPLASH_ORIENTATION[orientation]
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(UNSPLASH_SEARCH_URL, params=params, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            _log.warning("website.image_search.failed", provider="unsplash", error=type(exc).__name__)
            raise ImageSearchError("the photo search could not be reached") from exc
        self._note_limit(response)
        if response.status_code >= 400:
            _log.warning("website.image_search.failed", provider="unsplash", status_code=response.status_code)
            raise ImageSearchError(f"the photo search refused the request ({response.status_code})")
        try:
            found = parse_unsplash(response.json(), query)
        except ValueError as exc:
            raise ImageSearchError("the photo search returned something that is not JSON") from exc
        _remember(self.provider_name, query, orientation, size, page, found)
        return found

    async def track_selection(self, candidate: ImageCandidate) -> None:
        """Tell Unsplash this photo was chosen for a site (its API guidelines require it)."""
        if candidate.provider != self.provider_name or not candidate.download_location:
            return
        if urlsplit(candidate.download_location).hostname != "api.unsplash.com":
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(candidate.download_location, headers=self._headers())
            self._note_limit(response)
            if response.status_code >= 400:
                _log.warning("website.image_search.track_failed", provider="unsplash",
                             status_code=response.status_code)
        except Exception as exc:  # noqa: BLE001 — tracking must never break a build
            _log.warning("website.image_search.track_failed", provider="unsplash", error=type(exc).__name__)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_unsplash(payload: Any, query: str = "") -> list[ImageCandidate]:
    """Candidates from an Unsplash search. Unsplash+ (paid) photos and rows that
    lack a field are dropped."""
    rows = payload.get("results") if isinstance(payload, dict) else None
    out: list[ImageCandidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("premium") or row.get("plus"):
            continue
        urls = _object(row.get("urls"))
        links = _object(row.get("links"))
        user = _object(row.get("user"))
        user_links = _object(user.get("links"))
        raw = str(urls.get("raw") or "")
        preview = str(urls.get("small") or urls.get("regular") or "")
        try:
            width, height = int(row.get("width") or 0), int(row.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if not (row.get("id") and raw and preview and width > 0 and height > 0):
            continue
        out.append(ImageCandidate(
            provider="unsplash", photo_id=str(row["id"]),
            # Unsplash's own URL, resized through its image service: the ixid stays.
            image_url=_with_query(raw, w=2400, q=80, fm="jpg", fit="max"), preview_url=preview,
            page_url=str(links.get("html") or ""), width=width, height=height,
            description=str(row.get("alt_description") or row.get("description") or "")[:300],
            photographer=str(user.get("name") or "")[:120], average_color=str(row.get("color") or "")[:9],
            licence="Unsplash License", photographer_url=str(user_links.get("html") or ""),
            download_location=str(links.get("download_location") or ""), query=query[:120],
        ))
    return out


# --------------------------------------------------------------------- Pixabay
_PIXABAY_ORIENTATION = {"landscape": "horizontal", "portrait": "vertical"}
# Words that describe a photograph's style, not its subject: Pixabay matches
# tags, so they only narrow a search to nothing.
_STYLE_WORDS = frozenset(
    "editorial cinematic moody dark bright warm cool natural light lighting soft dramatic minimal minimalist "
    "aesthetic professional photography photo shot style mood atmosphere morning evening golden hour shallow "
    "depth field detailed detail texture close closeup up premium luxury elegant authentic real candid lifestyle "
    "with of the and a an in on at for from by overhead flat lay angle low high background copy space".split())


def pixabay_terms(query: str, limit: int = 4) -> str:
    """A search phrase as Pixabay tags: the subject words, at most `limit`."""
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z'-]+", query.casefold()) if w not in _STYLE_WORDS]
    return " ".join(list(dict.fromkeys(words))[:limit])[:100]


class PixabaySearch:
    provider_name = "pixabay"
    query_hint = "Two to four plain keywords naming the subject, e.g. 'fish market ice' or 'raw chicken'."

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0, fresh: bool = False) -> list[ImageCandidate]:
        terms = pixabay_terms(query) or query[:100]
        size = max(3, min(per_page, 200))
        cached = _cached(self.provider_name, terms, orientation, size, page, fresh)
        if cached is not None:
            return cached
        params: dict[str, Any] = {"key": self._key, "q": terms, "image_type": "photo", "per_page": size,
                                  "page": page, "safesearch": "true", "order": "popular"}
        if orientation in _PIXABAY_ORIENTATION:
            params["orientation"] = _PIXABAY_ORIENTATION[orientation]
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(PIXABAY_SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT})
        except Exception as exc:  # noqa: BLE001 — never the exception text: its URL carries the key
            _log.warning("website.image_search.failed", provider="pixabay", error=type(exc).__name__)
            raise ImageSearchError("the photo search could not be reached") from None
        if response.status_code >= 400:
            _log.warning("website.image_search.failed", provider="pixabay", status_code=response.status_code)
            raise ImageSearchError(f"the photo search refused the request ({response.status_code})")
        try:
            found = parse_pixabay(response.json(), query)
        except ValueError as exc:
            raise ImageSearchError("the photo search returned something that is not JSON") from exc
        _remember(self.provider_name, terms, orientation, size, page, found)
        return found

    async def track_selection(self, candidate: ImageCandidate) -> None:
        """Pixabay asks nothing when a picture is chosen: it is copied into storage instead."""
        del candidate


def parse_pixabay(payload: Any, query: str = "") -> list[ImageCandidate]:
    """Candidates from a Pixabay search: photos only, at the size the API gives
    (the long edge of `largeImageURL` is 1280px)."""
    rows = payload.get("hits") if isinstance(payload, dict) else None
    out: list[ImageCandidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("type") or "photo") != "photo":
            continue
        large = str(row.get("largeImageURL") or "")
        preview = str(row.get("webformatURL") or "")
        try:
            width, height = int(row.get("imageWidth") or 0), int(row.get("imageHeight") or 0)
        except (TypeError, ValueError):
            continue
        if not (row.get("id") and large and preview and width > 0 and height > 0):
            continue
        scale = min(1.0, 1280 / max(width, height))
        user, user_id = str(row.get("user") or ""), str(row.get("user_id") or "")
        out.append(ImageCandidate(
            provider="pixabay", photo_id=str(row["id"]), image_url=large, preview_url=preview,
            page_url=str(row.get("pageURL") or ""), width=int(width * scale), height=int(height * scale),
            description=str(row.get("tags") or "")[:300], photographer=user[:120],
            licence="Pixabay Content License",
            photographer_url=f"https://pixabay.com/users/{user}-{user_id}/" if user and user_id else "",
            query=query[:120],
        ))
    return out


# --------------------------------------------------------------------- both
class MultiSearch:
    """Several sources, searched side by side; their candidates compete in one pool.

    `only` limits a search to some sources (a slot that does not need the
    editorial source spares its hourly quota); a source that fails or is out of
    quota is skipped as long as another answered.
    """

    provider_name = "multi"
    query_hint = ("A short phrase of what the photograph shows and how it feels, e.g. 'fresh fish on crushed ice "
                  "dark moody'. It is sent to an editorial photo service as written and to a tag-based one as "
                  "its subject words.")

    def __init__(self, providers: list[ImageSearchProvider]) -> None:
        self.providers = providers

    def names(self) -> list[str]:
        return [p.provider_name for p in self.providers]

    async def search(self, query: str, *, orientation: str, per_page: int, page: int = 1,
                     timeout_seconds: float = 12.0, fresh: bool = False,
                     only: set[str] | frozenset[str] | None = None) -> list[ImageCandidate]:
        chosen = [p for p in self.providers if not only or p.provider_name in only]
        results = await asyncio.gather(
            *(p.search(query, orientation=orientation, per_page=per_page, page=page,
                       timeout_seconds=timeout_seconds, fresh=fresh) for p in chosen),
            return_exceptions=True)
        lists = [r for r in results if isinstance(r, list)]
        if chosen and not lists:
            raise ImageSearchError("no photo source answered")
        merged: list[ImageCandidate] = []
        for i in range(max((len(r) for r in lists), default=0)):
            merged += [r[i] for r in lists if i < len(r)]
        return merged

    async def track_selection(self, candidate: ImageCandidate) -> None:
        for p in self.providers:
            if p.provider_name == candidate.provider:
                await p.track_selection(candidate)


# --------------------------------------------------------------------- selection
def search_provider_name() -> str:
    """`unsplash`, `pixabay`, or `multi` (both; the default, and what `auto` means)."""
    chosen = (os.getenv("IMAGE_SEARCH_PROVIDER") or "multi").strip().lower()
    return "multi" if chosen in {"auto", ""} else chosen


def _key(name: str) -> str:
    return os.getenv(name, "").strip()


def get_search_provider() -> ImageSearchProvider | None:
    """The configured source(s); a source without a key is skipped, none at all is None."""
    name = search_provider_name()
    providers: list[ImageSearchProvider] = []
    if name in {"multi", "unsplash"} and _key("UNSPLASH_ACCESS_KEY"):
        providers.append(UnsplashSearch(_key("UNSPLASH_ACCESS_KEY")))
    if name in {"multi", "pixabay"} and _key("PIXABAY_API_KEY"):
        providers.append(PixabaySearch(_key("PIXABAY_API_KEY")))
    if not providers:
        return None
    return providers[0] if len(providers) == 1 else MultiSearch(providers)


def search_configured() -> bool:
    name = search_provider_name()
    return (name in {"multi", "unsplash"} and bool(_key("UNSPLASH_ACCESS_KEY"))) or (
        name in {"multi", "pixabay"} and bool(_key("PIXABAY_API_KEY")))
