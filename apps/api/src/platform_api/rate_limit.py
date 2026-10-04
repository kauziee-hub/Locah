"""IP-based sliding-window rate limiting (Doc 11 §21.1 gate 8).

Deliberately dependency-free: a small in-process sliding-window counter rather
than `slowapi` (which pulls in `slowapi` + `limits` + `Deprecated`) or a Redis
limiter (new infrastructure). The work order asked for the least-infra option.

TRADE-OFF, and it is a real one: the window state lives in this process's
memory. That means:
  * limits are per-replica, not global — two API instances each allow the
    full quota;
  * a restart clears all windows.
For a single-instance pre-launch deploy this is fine. For multi-replica
production, swap `_WINDOWS` for a shared store (Redis `INCR` + `EXPIRE`, or
Postgres) — the `RateLimiter.check` signature does not change, only where the
timestamps are kept. This is noted here so it is a decision, not a surprise.

Matching is by path prefix + method, so no route signature is touched. Each
bucket has its own limit; a request that matches no bucket is not limited.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class Bucket:
    name: str
    methods: frozenset[str]
    prefixes: tuple[str, ...]
    # `contains` lets a bucket match mid-path segments (e.g. ".../payments"
    # on a `/v1/platform/businesses/{id}/payments` route) without listing
    # every id-bearing prefix.
    contains: tuple[str, ...] = ()
    limit: int = 60
    window_seconds: int = 60

    def matches(self, method: str, path: str) -> bool:
        if method not in self.methods:
            return False
        if self.prefixes and path.startswith(self.prefixes):
            return True
        if self.contains and any(seg in path for seg in self.contains):
            return True
        return False


# Order matters: first match wins, so put the tightest/most-specific first.
BUCKETS: tuple[Bucket, ...] = (
    Bucket(name="business_interview", methods=frozenset({"POST"}), prefixes=(),
           contains=("/interview",), limit=20, window_seconds=60),
    # Catalogue import reading — a PDF or photo is one AI call per upload.
    Bucket(name="catalogue_import_read", methods=frozenset({"POST"}), prefixes=(),
           contains=("/catalogue-import/read",), limit=10, window_seconds=60),
    # Website AI generation — expensive, provider-backed, low legitimate rate.
    Bucket(
        name="website_generate",
        methods=frozenset({"POST"}),
        prefixes=(),
        contains=("/website/generate",),
        limit=5,
        window_seconds=60,
    ),
    # Payment creation — money-moving intake.
    Bucket(
        name="payment_create",
        methods=frozenset({"POST"}),
        prefixes=(),
        contains=("/payments",),
        limit=20,
        window_seconds=60,
    ),
    # Payment provider webhooks — providers retry on non-2xx, so not too tight.
    Bucket(
        name="payment_webhook",
        methods=frozenset({"POST"}),
        prefixes=("/v1/webhooks/",),
        limit=60,
        window_seconds=60,
    ),
    # Public write: guest checkout / booking intake, quotes, availability.
    Bucket(
        name="public_write",
        methods=frozenset({"POST", "PUT", "PATCH", "DELETE"}),
        prefixes=("/v1/public/",),
        limit=20,
        window_seconds=60,
    ),
    # Identity bootstrap — the surface a client hits right after Supabase auth.
    Bucket(
        name="identity",
        methods=frozenset({"GET", "POST"}),
        prefixes=("/me", "/v1/me"),
        limit=30,
        window_seconds=60,
    ),
    # Public read: marketplace, public websites, search.
    Bucket(
        name="public_read",
        methods=frozenset({"GET"}),
        prefixes=("/v1/public/", "/v1/b/"),
        limit=120,
        window_seconds=60,
    ),
)


class RateLimiter:
    """The window store + decision logic, separated from the ASGI plumbing
    so it can be unit-tested and so the storage backend can be swapped."""

    def __init__(self) -> None:
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, bucket: Bucket, client_key: str, now: float | None = None) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). retry_after is 0 when allowed."""
        now = time.monotonic() if now is None else now
        cutoff = now - bucket.window_seconds
        key = (bucket.name, client_key)
        window = self._windows[key]
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= bucket.limit:
            retry_after = max(1, int(window[0] + bucket.window_seconds - now) + 1)
            return False, retry_after
        window.append(now)
        return True, 0

    def reset(self) -> None:
        self._windows.clear()


def client_key(scope: Scope) -> str:
    """Public buckets must not trust a caller-supplied X-Forwarded-For.

    Direct connections use the socket peer. When the process sits behind a
    reverse proxy (Railway), set RATE_LIMIT_TRUST_XFF=1 so the *last*
    X-Forwarded-For hop — the one that proxy appended — is used. Left-hand
    spoofed hops are ignored.
    """
    import os

    client = scope.get("client")
    peer = str(client[0]) if client else "unknown"
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    forwarded = headers.get("x-forwarded-for")
    trust = os.getenv("RATE_LIMIT_TRUST_XFF", "").strip().lower() in {"1", "true", "yes"}
    if trust and forwarded:
        hops = [part.strip() for part in forwarded.split(",") if part.strip()]
        if hops:
            return str(hops[-1])
    return peer


def _bucket_for(method: str, path: str) -> Bucket | None:
    for bucket in BUCKETS:
        if bucket.matches(method, path):
            return bucket
    return None


class RateLimitMiddleware:
    """Pure-ASGI so it runs before routing and can short-circuit with a 429
    that still carries the platform error envelope + `Retry-After`."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter | None = None) -> None:
        self.app = app
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        bucket = _bucket_for(scope["method"], scope["path"])
        if bucket is None:
            await self.app(scope, receive, send)
            return

        allowed, retry_after = self.limiter.check(bucket, client_key(scope))
        if allowed:
            await self.app(scope, receive, send)
            return

        correlation_id = ""
        for k, v in scope.get("headers", []):
            if k.decode().lower() == "x-correlation-id":
                correlation_id = v.decode()
                break

        body = (
            b'{"error":{"code":"RATE_LIMITED",'
            b'"message":"Too many requests. Slow down and retry after the delay.",'
            b'"details":{"bucket":"' + bucket.name.encode() + b'",'
            b'"retry_after_seconds":' + str(retry_after).encode() + b'}},'
            b'"meta":{"correlation_id":"' + correlation_id.encode() + b'"}}'
        )
        headers = [
            (b"content-type", b"application/json"),
            (b"retry-after", str(retry_after).encode()),
        ]
        if correlation_id:
            headers.append((b"x-correlation-id", correlation_id.encode()))

        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": body})
