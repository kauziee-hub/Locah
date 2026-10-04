import os
import re
from typing import Any, AsyncIterator
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from contextlib import asynccontextmanager
from platform_core.db import create_worker_session_factory
from platform_core.exceptions import PlatformError
from platform_core.logging import configure as configure_logging, get_logger
from platform_api.errors import platform_error_handler
from platform_api.observability import RequestLogMiddleware
from platform_api.rate_limit import RateLimitMiddleware
from platform_api.routers import (
    me,
    v1_me,
    v1_businesses,
    v1_business,
    v1_team_modules,
    v1_admin,
    v1_platform_members,
    v1_platform_invitations,
    v1_platform_settings,
    v1_platform_configuration,
    v1_platform_entitlements,
    v1_platform_permissions,
    v1_platform_locations,
    v1_platform_employees,
    v1_platform_customers,
    v1_platform_offerings,
    v1_platform_inventory,
    v1_platform_inventory_field,
    v1_payment_collect,
    v1_platform_stock,
    v1_platform_supply,
    v1_platform_orders,
    v1_platform_booking_resources,
    v1_platform_bookings,
    v1_platform_payments,
    v1_platform_projects,
    v1_platform_quotes,
    webhooks_payments,
    webhooks_whatsapp,
    v1_website,
    v1_public_websites,
    v1_public_quotes,
    v1_public_search,
    v1_marketplace,
    v1_fulfilment,
    v1_public_checkout,
    v1_workforce,
    v1_public_bookings,
    v1_platform_leads,
    v1_platform_memberships,
    v1_platform_notifications,
    v1_media,
    v1_business_interview,
    v1_taxonomy,
    v1_business_classification,
    v1_platform_primitives,
    v1_team_roles,
    v1_public_join,
    v1_workspace_home,
    v1_public_enquiries,
    v1_platform_invoicing,
    v1_platform_ledger,
    v1_platform_messaging,
    v1_platform_pos,
    v1_platform_kitchen,
    v1_reviews,
    v1_admin_reviews,
    v1_compliance,
    v1_stages,
    v1_jobs,
    v1_academics,
    v1_queue,
    v1_tasks,
    v1_dispatch,
    v1_platform_loyalty,
    v1_platform_marketing,
    v1_ai_employees,
    v1_catalogue_import,
    v1_attendance,
    v1_documents,
)

# Database lifecycle state
db_engine = None
db_session_factory = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
    global db_engine, db_session_factory

    # AUD-11: structlog must be configured (redaction processor installed)
    # before the first line ships.
    configure_logging()
    from platform_core.ai_guard import external_ai_disabled, install_transport_guard

    # A backstop for LOCAH_TEST_NO_EXTERNAL_AI: it checks the switch on every
    # request, so installing it in a process where the switch is off is inert.
    install_transport_guard()
    get_logger("platform_api").info(
        "api.startup", rate_limit=os.getenv("RATE_LIMIT_ENABLED", "1") != "0",
        external_ai_disabled=external_ai_disabled(),
    )

    # Warm the Supabase JWKS cache so the first authenticated request doesn't
    # pay the fetch. Best-effort; the ES256 verify path retries on miss.
    from anyio import to_thread

    from platform_api.jwt_verify import warm_jwks_cache

    await to_thread.run_sync(warm_jwks_cache)

    if os.getenv("DATABASE_URL"):
        try:
            # role="user" → the NOBYPASSRLS platform_api connection. The API
            # request path is subject to row-level policies (AUD-02).
            db_engine, db_session_factory = create_worker_session_factory(role="user")
        except Exception as e:
            get_logger("platform_api").error("api.db_session_factory_init_failed", error=str(e))
            db_engine = None
            db_session_factory = None

    app.state.db_session_factory = db_session_factory
    # AUD-02 follow-up: get_db_session binds one Connection per request off
    # this engine directly (rather than handing out Engine-bound Sessions),
    # so an in-request commit() can't silently swap the physical connection
    # under the session and strip the RLS GUCs bind_session_context set. See
    # the comment on get_db_session for the full mechanism. db_session_factory
    # stays published too — /health/ready and /health/worker only ever run one
    # transaction per call, so the swap risk doesn't apply to them.
    app.state.db_engine = db_engine

    yield

    # Clear the advertised factory/engine before disposing. Leaving a disposed
    # engine on app.state makes get_db_session hand out sessions bound to a
    # closed event loop and suppresses its NullPool fallback — which breaks
    # every later bare-TestClient(app) test in the same process once any
    # `with TestClient(app)` test has run lifespan.
    app.state.db_session_factory = None
    app.state.db_engine = None
    if db_engine:
        await db_engine.dispose()
    db_engine = None
    db_session_factory = None


app = FastAPI(
    title="Multi-Tenant Platform API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Rate limiting (Doc 11 §21.1 gate 8). Added BEFORE CORS so CORS ends up the
# outer layer (Starlette wraps last-added first): a 429 short-circuited here
# still travels back out through CORS and gets its headers, so a browser sees
# the 429 rather than an opaque network error. Opt out per-process with
# RATE_LIMIT_ENABLED=0 — the test suite does, so parallel workers hammering
# shared buckets don't trip each other.
if os.getenv("RATE_LIMIT_ENABLED", "1") != "0":
    app.add_middleware(RateLimitMiddleware)

# AUD-11: request-line logging + correlation-id propagation. Added after the
# rate limiter so it stays inside CORS but wraps the limiter — a 429 still gets
# a log line and an X-Correlation-Id.
app.add_middleware(RequestLogMiddleware)

# Standard CORS. Credentials cannot be used with wildcard origins.
#
# The allowlist is assembled rather than merely read, because the set of origins
# that legitimately call this API is a consequence of the platform domain
# (Document 10 SS12): the public site, Workspace, Admin, and every Business
# website on `{slug}.<domain>`. An explicit CORS_ALLOWED_ORIGINS is still
# honoured and is added to, so a staging or preview origin can be named without
# giving up the derived ones.
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://localhost:3002",
    ).split(",")
    if origin.strip()
]

_platform_domain = (os.getenv("PLATFORM_DOMAIN") or "").strip().lower().lstrip(".")
# Business websites are one subdomain each, so they cannot be enumerated ahead
# of time. A regex bounded to the platform domain is narrower than a wildcard
# and still admits exactly the hosts the platform itself issues.
_cors_origin_regex: str | None = None
if _platform_domain and _platform_domain != "localhost":
    for _host in (
        _platform_domain,
        f"www.{_platform_domain}",
        f"app.{_platform_domain}",
        f"admin.{_platform_domain}",
    ):
        _origin = f"https://{_host}"
        if _origin not in _cors_origins:
            _cors_origins.append(_origin)
    _escaped = re.escape(_platform_domain)
    _cors_origin_regex = rf"^https://[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.{_escaped}$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(v1_me.router)
app.include_router(v1_businesses.router)
app.include_router(v1_platform_members.router)
app.include_router(v1_platform_invitations.router)
app.include_router(v1_platform_settings.router)
app.include_router(v1_platform_configuration.router)
app.include_router(v1_platform_entitlements.router)
app.include_router(v1_platform_permissions.router)
app.include_router(v1_platform_locations.router)
app.include_router(v1_platform_employees.router)
app.include_router(v1_platform_customers.router)
app.include_router(v1_platform_offerings.router)
app.include_router(v1_platform_inventory.router)
app.include_router(v1_platform_inventory_field.router)
app.include_router(v1_platform_stock.router)
app.include_router(v1_platform_supply.router)
app.include_router(v1_payment_collect.router)
app.include_router(v1_payment_collect.public_router)
app.include_router(v1_platform_orders.router)
app.include_router(v1_platform_booking_resources.router)
app.include_router(v1_platform_bookings.router)
app.include_router(v1_workforce.router)
app.include_router(v1_platform_payments.router)
app.include_router(v1_platform_projects.router)
app.include_router(v1_platform_quotes.router)
app.include_router(webhooks_payments.router)
app.include_router(webhooks_whatsapp.router)
app.include_router(v1_website.router)
app.include_router(v1_public_websites.router)
app.include_router(v1_public_quotes.router)
app.include_router(v1_public_search.router)
app.include_router(v1_marketplace.router)
app.include_router(v1_fulfilment.router)
app.include_router(v1_public_checkout.router)
app.include_router(v1_public_bookings.router)
app.include_router(v1_business.router)
app.include_router(v1_team_modules.router)
app.include_router(v1_admin.router)
app.include_router(v1_platform_leads.router)
app.include_router(v1_platform_memberships.router)
app.include_router(v1_platform_notifications.router)
app.include_router(v1_media.router)
app.include_router(v1_business_interview.router)
app.include_router(v1_taxonomy.router)
app.include_router(v1_business_classification.router)
app.include_router(v1_platform_primitives.router)
app.include_router(v1_team_roles.router)
app.include_router(v1_public_join.router)
app.include_router(v1_workspace_home.router)
app.include_router(v1_public_enquiries.router)
app.include_router(v1_platform_invoicing.router)
app.include_router(v1_platform_invoicing.public_router)
app.include_router(v1_platform_ledger.router)
app.include_router(v1_platform_ledger.public_router)
app.include_router(v1_platform_messaging.router)
app.include_router(v1_platform_pos.router)
app.include_router(v1_platform_kitchen.router)
app.include_router(v1_reviews.router)
app.include_router(v1_reviews.public_router)
app.include_router(v1_admin_reviews.router)
app.include_router(v1_compliance.router)
app.include_router(v1_compliance.public_router)
app.include_router(v1_stages.router)
app.include_router(v1_jobs.router)
app.include_router(v1_academics.router)
app.include_router(v1_academics.portal_router)
app.include_router(v1_queue.router)
app.include_router(v1_tasks.router)
app.include_router(v1_dispatch.router)
app.include_router(v1_platform_loyalty.router)
app.include_router(v1_platform_marketing.router)
app.include_router(v1_attendance.router)
app.include_router(v1_ai_employees.router)
app.include_router(v1_catalogue_import.router)
app.include_router(v1_documents.router)
app.include_router(v1_documents.public_router)
app.include_router(v1_documents.download_router)

app.add_exception_handler(PlatformError, platform_error_handler)


@app.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness_check() -> dict[str, Any]:
    """
    Liveness check to verify the process is alive.
    """
    return {"status": "ok", "message": "Liveness check passed"}


@app.get("/health/ready")
async def readiness_check(request: Request, response: Response) -> dict[str, Any]:
    """
    Readiness check to verify DB connection and required services.
    """
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if not session_factory:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "error",
            "database": "not_configured",
            "message": "Database is not configured",
        }

    try:
        async with session_factory() as session:
            # Perform a quick select to verify connectivity
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": f"Database connectivity failed: {str(e)}"}


@app.get("/health/worker")
async def worker_health_check(request: Request, response: Response) -> dict[str, Any]:
    """Worker/outbox lag health gate (Doc 12 §22.2)."""
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if not session_factory:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "error",
            "worker": "not_configured",
            "message": "Database is not configured",
        }

    lag_threshold_seconds = int(os.getenv("WORKER_LAG_THRESHOLD_SECONDS", "300"))
    try:
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT COALESCE(
                        EXTRACT(EPOCH FROM (now() - MIN(created_at))),
                        0
                    )::int AS lag_seconds,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending_count
                    FROM platform_outbox_events
                    WHERE status IN ('pending', 'processing')
                """)
            )
            row = result.one()
            lag_seconds = int(row.lag_seconds or 0)
            pending_count = int(row.pending_count or 0)
        if lag_seconds > lag_threshold_seconds and pending_count > 0:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "error",
                "worker": "lag_exceeded",
                "lag_seconds": lag_seconds,
                "pending_count": pending_count,
            }
        return {
            "status": "ok",
            "worker": "healthy",
            "lag_seconds": lag_seconds,
            "pending_count": pending_count,
        }
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": f"Worker health check failed: {str(e)}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("platform_api.main:app", host="0.0.0.0", port=8000, reload=True)
