"""Asynchronous job lane — claim, execute, retry, dead-letter."""

from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_worker.claiming import claim_job_batch

# Jobs that run longer than the claim's lease (claiming.LEASE_SECONDS): a website
# build searches, judges and may draw pictures for minutes. Its lease is
# lengthened before it runs, or another poll re-claims and rebuilds it while it
# is still running.
LONG_JOB_LEASE_SECONDS = {"website.generate": 900}


def _payload_as_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        loaded = json.loads(payload)
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _payload_as_json(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload if payload is not None else {})


async def _already_processed(session: AsyncSession, job_id: str, handler: str) -> bool:
    result = await session.execute(
        text("""
            SELECT 1 FROM platform_processed_events
            WHERE event_id = :event_id AND handler = :handler
            LIMIT 1
        """),
        {"event_id": job_id, "handler": handler},
    )
    return result.first() is not None


async def _record_processed(session: AsyncSession, job_id: str, handler: str) -> None:
    await session.execute(
        text("""
            INSERT INTO platform_processed_events (event_id, handler)
            VALUES (:event_id, :handler)
            ON CONFLICT (event_id, handler) DO NOTHING
        """),
        {"event_id": job_id, "handler": handler},
    )


async def _execute_job(session: AsyncSession, job: dict[str, Any]) -> None:
    """Dispatch known job types; unknown types acknowledge without side effects."""
    payload = _payload_as_dict(job.get("payload"))
    if payload.get("inert") and os.getenv("LOCAH_JOBS_INERT") != "1":
        # Queued by a test run against a shared database. A deployed worker
        # acknowledges it and never executes it: running it would spend a paid
        # provider on a fake business. The test process itself (inert too, and
        # holding no paid keys) may still drain its own jobs.
        return
    if payload.get("__force_fail"):
        message = str(payload.get("__force_fail_message") or "forced job failure")
        raise RuntimeError(message)

    job_type = str(job.get("job_type") or "")
    if job_type == "website.generate":
        from uuid import UUID

        from platform_core.services.website_generation import WebsiteGenerationService

        generation_job_id = payload.get("generation_job_id")
        if not generation_job_id:
            raise RuntimeError("website.generate payload missing generation_job_id")
        await WebsiteGenerationService.execute_job(
            session,
            generation_job_id=UUID(str(generation_job_id)),
            correlation_id=str(payload.get("correlation_id") or job.get("id")),
        )
    elif job_type == "marketplace.reconcile":
        from platform_core.services.marketplace_indexing import MarketplaceIndexingService

        await MarketplaceIndexingService.reconcile_all(
            session,
            correlation_id=str(payload.get("correlation_id") or job.get("id")),
            limit=int(payload.get("limit") or 100),
        )
        if payload.get("recurring"):
            # A one-off reconcile (a test, an operator) does not start a chain.
            await MarketplaceIndexingService.schedule_next_reconcile(
                session, minutes=int(os.getenv("MARKETPLACE_RECONCILE_MINUTES") or 30)
            )
    elif job_type == "memberships.sweep":
        # P2-02: the daily lifecycle check, deliveries at cutoff, AMC visits,
        # month-end postpaid bills. Books its own next run.
        from platform_core.memberships.sweep import ensure_scheduled, sweep_all

        await sweep_all(session)
        if payload.get("recurring"):
            await ensure_scheduled(session, minutes=int(os.getenv("MEMBERSHIPS_SWEEP_MINUTES") or 60))
    elif job_type == "ai_employees.sweep":
        # The daily run for AI employees on a schedule (collections, procurement).
        # Books its own next run.
        from platform_core.ai_employees.sweep import ensure_scheduled, sweep_all

        await sweep_all(session)
        if payload.get("recurring"):
            await ensure_scheduled(session, minutes=int(os.getenv("AI_EMPLOYEES_SWEEP_MINUTES") or 1440))
    elif job_type == "marketplace.reindex":
        from uuid import UUID

        from platform_core.services.marketplace_indexing import MarketplaceIndexingService

        business_id = payload.get("business_id")
        if not business_id:
            raise RuntimeError("marketplace.reindex payload missing business_id")
        await MarketplaceIndexingService.reindex_business(
            session,
            business_id=UUID(str(business_id)),
            correlation_id=str(payload.get("correlation_id") or job.get("id")),
            trigger="async_job",
        )
    elif job_type == "interview.generate_logo":
        # A logo the owner asked for mid-conversation, drawn while they carry on.
        from uuid import UUID
        from platform_core.interview.media import generate_interview_logo
        await generate_interview_logo(session, business_id=UUID(payload["business_id"]),
                                      actor_id=UUID(payload["actor_id"]))
    elif job_type == "interview.read_document":
        # The owner's menu / catalogue / price list, read while they carry on.
        from uuid import UUID
        from platform_core.interview.documents import read_owner_document
        await read_owner_document(session, business_id=UUID(payload["business_id"]),
                                  asset_id=UUID(payload["asset_id"]))
    elif job_type in {"interview.generate_media", "interview.generate_hero"}:
        # generate_hero is the name jobs queued before logos existed still carry.
        from uuid import UUID
        from platform_core.interview.media import generate_interview_media
        await generate_interview_media(session, business_id=UUID(payload["business_id"]),
            actor_id=UUID(payload["actor_id"]), generation_job_id=UUID(payload["generation_job_id"]))
    elif job_type == "media.generate_website_images":
        from uuid import UUID

        from platform_core.services.website_images import WebsiteImageService

        business_id = payload.get("business_id")
        actor_id = payload.get("actor_id")
        if not business_id or not actor_id:
            raise RuntimeError("media.generate_website_images payload missing ids")
        await WebsiteImageService.fill_missing(
            session,
            business_id=UUID(str(business_id)),
            actor_id=UUID(str(actor_id)),
            correlation_id=str(payload.get("correlation_id") or job.get("id")),
        )


async def _mark_completed(session: AsyncSession, job_id: str) -> None:
    await session.execute(
        text("""
            UPDATE platform_async_jobs
            SET status = 'completed',
                completed_at = now(),
                leased_until = NULL,
                leased_by = NULL,
                last_error = NULL
            WHERE id = :id
        """),
        {"id": job_id},
    )


async def _mark_retry(
    session: AsyncSession, job_id: str, attempt_count: int, error: str
) -> None:
    backoff = min(2**attempt_count * 30, 3600)
    await session.execute(
        text("""
            UPDATE platform_async_jobs
            SET status = 'failed',
                attempt_count = :attempt_count,
                next_attempt_at = now() + make_interval(secs => :backoff),
                last_error = :error,
                leased_until = NULL,
                leased_by = NULL
            WHERE id = :id
        """),
        {
            "id": job_id,
            "attempt_count": attempt_count,
            "backoff": backoff,
            "error": error,
        },
    )


async def _mark_dead_letter(session: AsyncSession, job: dict[str, Any], error: str) -> None:
    attempt_count = int(job.get("attempt_count", 0)) + 1
    await session.execute(
        text("""
            UPDATE platform_async_jobs
            SET status = 'dead_letter',
                attempt_count = :attempt_count,
                last_error = :error,
                leased_until = NULL,
                leased_by = NULL
            WHERE id = :id
        """),
        {"id": job["id"], "attempt_count": attempt_count, "error": error},
    )
    await session.execute(
        text("""
            INSERT INTO platform_dead_letter_events
                (source_table, source_id, event_type, payload, final_error, attempt_count)
            VALUES (
                'platform_async_jobs',
                :id,
                :event_type,
                CAST(:payload AS jsonb),
                :error,
                :attempt_count
            )
        """),
        {
            "id": job["id"],
            "event_type": job.get("job_type", "unknown"),
            "payload": _payload_as_json(job.get("payload")),
            "error": error,
            "attempt_count": attempt_count,
        },
    )


async def poll_and_execute_jobs(
    session: AsyncSession, worker_id: str, job_type: str | None = None, business_id: str | None = None
) -> int:
    """Claim and process a batch of async jobs. Returns jobs transitioned this poll.

    `job_type` is optional isolation for tests, passed straight through to
    claim_job_batch which has carried it for the same reason. Production omits
    it so a worker drains the whole lane. A test that omits it claims the
    oldest-due jobs across the entire shared database, so under `pytest -n` it
    competes with every other worker for the batch, and asserting on its own
    job becomes a race it usually but not always wins — and runs other
    tests' jobs without their stubs. `business_id` scopes a test to its own.
    """
    jobs = await claim_job_batch(session, worker_id, job_type=job_type, business_id=business_id)
    if not jobs:
        return 0
    # The claim is committed before anything runs, and each job is settled in
    # its own transaction: a job that fails rolls back its own work only, and
    # its retry is recorded on a clean session. (A build whose failed flush left
    # the session broken could not record its retry, kept its lease, and was
    # rebuilt every two minutes — 14 times and 320 model calls, 2026-11-24.)
    await session.commit()

    processed = 0
    for job in jobs:
        job_id = str(job["id"])
        job_type = str(job.get("job_type") or "unknown")
        handler = f"job_runner.{job_type}"
        try:
            lease = LONG_JOB_LEASE_SECONDS.get(job_type)
            if lease:
                await session.execute(
                    text("UPDATE platform_async_jobs SET leased_until = now() + make_interval(secs => :s) "
                         "WHERE id = :id"), {"s": lease, "id": job_id})
                await session.commit()
            if await _already_processed(session, job_id, handler):
                await _mark_completed(session, job_id)
                await session.commit()
                processed += 1
                continue

            await _execute_job(session, dict(job))
            await _record_processed(session, job_id, handler)
            await _mark_completed(session, job_id)
            await session.commit()
            processed += 1
        except Exception as exc:
            await session.rollback()
            attempt = int(job.get("attempt_count", 0)) + 1
            max_attempts = int(job.get("max_attempts", 5))
            if attempt >= max_attempts:
                await _mark_dead_letter(session, dict(job), str(exc))
            else:
                await _mark_retry(session, job_id, attempt, str(exc))
            await session.commit()
    return processed
