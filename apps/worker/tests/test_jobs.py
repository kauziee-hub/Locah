"""Integration tests for async job and scheduled job worker lanes (Doc 12 §18)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from platform_core.db import get_database_url
from platform_worker.claiming import claim_job_batch
from platform_worker.job_runner import poll_and_execute_jobs
from platform_worker.scheduler import materialize_due_schedules


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    url = get_database_url()
    if not url:
        pytest.skip("DATABASE_URL not configured")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _insert_async_job(
    session: AsyncSession,
    *,
    job_type: str = "platform.noop",
    payload: dict[str, Any] | None = None,
    max_attempts: int = 5,
    status: str = "pending",
) -> uuid.UUID:
    job_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO platform_async_jobs (
                id, job_type, payload, status, max_attempts, next_attempt_at
            )
            VALUES (
                :id,
                :job_type,
                CAST(:payload AS jsonb),
                :status,
                :max_attempts,
                now()
            )
        """),
        {
            "id": str(job_id),
            "job_type": job_type,
            "payload": __import__("json").dumps(payload or {}),
            "status": status,
            "max_attempts": max_attempts,
        },
    )
    await session.commit()
    return job_id


async def _job_status(session: AsyncSession, job_id: uuid.UUID) -> tuple[str, int, str | None]:
    session.expire_all()
    result = await session.execute(
        text("""
            SELECT status, attempt_count, last_error
            FROM platform_async_jobs
            WHERE id = :id
        """),
        {"id": str(job_id)},
    )
    row = result.one()
    return str(row.status), int(row.attempt_count), row.last_error


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_async_job_claim_and_completion(db_session: AsyncSession) -> None:
    # A job_type nothing else uses, so the poll below can be scoped to it.
    # Unscoped, a poll claims the oldest-due jobs across the whole shared
    # database and this test races every other xdist worker for its own job;
    # the drain that used to paper over that was global work with the same
    # problem. Unknown job types acknowledge without side effects, so a unique
    # one runs the same path platform.noop did.
    isolated_type = f"platform.noop.{uuid.uuid4().hex[:12]}"
    job_id = await _insert_async_job(db_session, job_type=isolated_type, payload={"ok": True})

    status = "pending"
    for _ in range(25):
        await poll_and_execute_jobs(db_session, "test-job-worker", job_type=isolated_type)
        status, attempt_count, last_error = await _job_status(db_session, job_id)
        # Only the status ends the loop. A poll returning zero now means the job
        # was not claimable this instant, not that there is nothing to do - the
        # claim is scoped to a job_type nothing else uses, so the only row it can
        # ever return is this one. Breaking on zero made a slow first poll under
        # load look like a failure.
        if status == "completed":
            break
    assert status == "completed"
    assert attempt_count == 0
    assert last_error is None

    processed = await db_session.execute(
        text("""
            SELECT handler FROM platform_processed_events
            WHERE event_id = :id AND handler = :handler
        """),
        {"id": str(job_id), "handler": f"job_runner.{isolated_type}"},
    )
    assert processed.first() is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_async_job_retry_on_failure(db_session: AsyncSession) -> None:
    # This test asserts poll_and_execute_jobs's exact return count for a
    # single poll, so the batch must contain nothing but this job.
    # A job_type nothing else uses, so the poll below can be scoped to it.
    # Unscoped, a poll claims the oldest-due jobs across the whole shared
    # database and this test races every other xdist worker for its own job;
    # the drain that used to paper over that was global work with the same
    # problem. Unknown job types acknowledge without side effects, so a unique
    # one runs the same path platform.noop did.
    isolated_type = f"platform.noop.{uuid.uuid4().hex[:12]}"
    job_id = await _insert_async_job(
        db_session,
        job_type=isolated_type,
        payload={"__force_fail": True, "__force_fail_message": "transient failure"},
        max_attempts=5,
    )

    count = await poll_and_execute_jobs(db_session, "test-job-retry", job_type=isolated_type)
    assert count == 0

    status, attempt_count, last_error = await _job_status(db_session, job_id)
    assert status == "failed"
    assert attempt_count == 1
    assert last_error is not None
    assert "transient failure" in last_error

    # Not yet due because of backoff
    claimed = await claim_job_batch(db_session, "test-job-retry-2", job_type=isolated_type)
    claimed_ids = {str(row["id"]) for row in claimed}
    assert str(job_id) not in claimed_ids
    await db_session.rollback()

    # Make retry due immediately
    await db_session.execute(
        text("UPDATE platform_async_jobs SET next_attempt_at = now() WHERE id = :id"),
        {"id": str(job_id)},
    )
    await db_session.commit()

    # Still forced to fail — second attempt
    await poll_and_execute_jobs(db_session, "test-job-retry-3", job_type=isolated_type)
    status, attempt_count, _ = await _job_status(db_session, job_id)
    assert status == "failed"
    assert attempt_count == 2


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_async_job_dead_letter_on_max_attempts(db_session: AsyncSession) -> None:
    # Same backlog concern as test_async_job_retry_on_failure — this job's own
    # dead-letter row is self-contained regardless of backlog, but draining
    # first keeps the single poll below deterministic.
    # A job_type nothing else uses, so the poll below can be scoped to it.
    # Unscoped, a poll claims the oldest-due jobs across the whole shared
    # database and this test races every other xdist worker for its own job;
    # the drain that used to paper over that was global work with the same
    # problem. Unknown job types acknowledge without side effects, so a unique
    # one runs the same path platform.noop did.
    isolated_type = f"platform.noop.{uuid.uuid4().hex[:12]}"
    job_id = await _insert_async_job(
        db_session,
        job_type=isolated_type,
        payload={"__force_fail": True, "__force_fail_message": "terminal failure"},
        max_attempts=1,
    )

    await poll_and_execute_jobs(db_session, "test-job-dlq", job_type=isolated_type)
    status, attempt_count, last_error = await _job_status(db_session, job_id)
    assert status == "dead_letter"
    assert attempt_count == 1
    assert last_error is not None

    dlq = await db_session.execute(
        text("""
            SELECT source_table, event_type, final_error, attempt_count
            FROM platform_dead_letter_events
            WHERE source_id = :id AND source_table = 'platform_async_jobs'
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"id": str(job_id)},
    )
    row = dlq.one()
    assert row.source_table == "platform_async_jobs"
    assert row.event_type == isolated_type
    assert "terminal failure" in row.final_error
    assert int(row.attempt_count) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_scheduled_job_materialization(db_session: AsyncSession) -> None:
    # A unique type keeps this job separate from other test jobs. Do not
    # globally drain the shared queue: that can claim another test's row when
    # the suite runs in parallel.
    isolated_type = f"platform.noop.{uuid.uuid4().hex[:12]}"
    schedule_id = uuid.uuid4()
    await db_session.execute(
        text("""
            INSERT INTO platform_scheduled_jobs (
                id, schedule_type, payload, run_at, status
            )
            VALUES (
                :id,
                :schedule_type,
                '{"source": "schedule"}'::jsonb,
                now() - interval '1 century',
                'pending'
            )
        """),
        {"id": str(schedule_id), "schedule_type": isolated_type},
    )
    await db_session.commit()

    count = await materialize_due_schedules(db_session, "test-scheduler")
    assert count >= 1

    db_session.expire_all()
    schedule = await db_session.execute(
        text("""
            SELECT status, materialized_job_id
            FROM platform_scheduled_jobs
            WHERE id = :id
        """),
        {"id": str(schedule_id)},
    )
    srow = schedule.one()
    assert srow.status == "materialized"
    assert srow.materialized_job_id is not None

    job = await db_session.execute(
        text("""
            SELECT job_type, status, causation_id, payload
            FROM platform_async_jobs
            WHERE id = :id
        """),
        {"id": str(srow.materialized_job_id)},
    )
    jrow = job.one()
    assert jrow.job_type == isolated_type
    # Another xdist worker may already have acknowledged this no-op job after
    # materialization. Its identity and causation, not a transient queue
    # status, prove that this schedule produced the right job.
    assert jrow.status in {"pending", "processing", "completed"}
    assert str(jrow.causation_id) == str(schedule_id)

    # Materializing again must not duplicate THIS schedule. Other due rows on
    # a shared hosted database may still materialize in the same poll.
    again = await materialize_due_schedules(db_session, "test-scheduler")
    db_session.expire_all()
    reread = await db_session.execute(
        text("""
            SELECT status, materialized_job_id
            FROM platform_scheduled_jobs
            WHERE id = :id
        """),
        {"id": str(schedule_id)},
    )
    again_row = reread.one()
    assert again_row.status == "materialized"
    assert str(again_row.materialized_job_id) == str(srow.materialized_job_id)
    assert again >= 0

    # Scoped to the schedule's own job type for the same reason as the tests
    # above: an unscoped poll competes for the batch with every other worker.
    status = "pending"
    for _ in range(25):
        await poll_and_execute_jobs(
            db_session, "test-scheduler-exec", job_type=str(jrow.job_type)
        )
        status, _, _ = await _job_status(db_session, srow.materialized_job_id)
        if status == "completed":
            break
    assert status == "completed"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_concurrent_job_claim_safety(db_session: AsyncSession) -> None:
    # Our two claims are type-scoped, but other test workers use the production
    # unscoped poll against the same durable DB. If one of them gets our row
    # first, retry with a fresh row rather than misreport a duplicate claim.
    url = get_database_url()
    assert url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        for _ in range(3):
            isolated_type = f"platform.noop.{uuid.uuid4().hex[:12]}"
            job_id = await _insert_async_job(db_session, job_type=isolated_type)
            async with factory() as session_a, factory() as session_b:
                claimed_a = await claim_job_batch(session_a, "worker-a", limit=10, job_type=isolated_type)
                claimed_b = await claim_job_batch(session_b, "worker-b", limit=10, job_type=isolated_type)
                await session_a.commit()
                await session_b.commit()

            ids_a = {str(row["id"]) for row in claimed_a}
            ids_b = {str(row["id"]) for row in claimed_b}
            assert not (str(job_id) in ids_a and str(job_id) in ids_b)
            if str(job_id) in ids_a or str(job_id) in ids_b:
                return
            status, _, _ = await _job_status(db_session, job_id)
            assert status in {"processing", "completed"}, "Neither test worker nor another worker claimed the job"
        pytest.skip("Unscoped parallel workers claimed all three test rows before the two scoped claims")
    finally:
        await engine.dispose()


async def test_a_deployed_worker_acknowledges_a_test_job_without_running_it(monkeypatch) -> None:
    """A job a test run queued on the shared database never runs on a deployed worker."""
    from platform_worker.job_runner import _execute_job

    job = {"job_type": "interview.generate_logo", "payload": {"inert": True, "__force_fail": True}}
    monkeypatch.delenv("LOCAH_JOBS_INERT", raising=False)
    # None: inert jobs return before ever touching the session.
    await _execute_job(None, job)
    # The test process itself (inert, no paid keys) still drains its own jobs.
    monkeypatch.setenv("LOCAH_JOBS_INERT", "1")
    with pytest.raises(RuntimeError, match="forced job failure"):
        await _execute_job(None, job)


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_a_business_scoped_claim_never_takes_another_business_job(db_session: AsyncSession) -> None:
    # Under `pytest -n` every worker shares one database. A test draining "its"
    # jobs without a scope once ran another test's website.generate and
    # interview.read_document jobs, without that test's stubs.
    isolated_type = f"platform.scope-{uuid.uuid4().hex[:8]}"
    job_id = await _insert_async_job(db_session, job_type=isolated_type)
    other_business = str(uuid.uuid4())
    taken = await claim_job_batch(db_session, "test-scope", job_type=isolated_type, business_id=other_business)
    await db_session.commit()
    assert taken == []
    assert (await _job_status(db_session, job_id))[0] == "pending"
    claimed = await claim_job_batch(db_session, "test-scope", job_type=isolated_type)
    await db_session.commit()
    assert [row["id"] for row in claimed] == [job_id]


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_a_job_that_breaks_its_transaction_still_records_its_retry(
        db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A website build whose failed flush left the session broken could not
    record its retry, kept its lease, and was rebuilt every two minutes (owner
    lab, 2026-11-24: 14 builds, 320 model calls). Its own work is rolled back and
    the retry is recorded on a clean session."""
    from platform_worker import job_runner

    isolated_type = f"platform.noop.{uuid.uuid4().hex[:12]}"
    job_id = await _insert_async_job(db_session, job_type=isolated_type, max_attempts=3)

    async def breaks_the_transaction(session: AsyncSession, job: dict[str, Any]) -> None:
        await session.execute(text("SELECT * FROM a_table_that_does_not_exist"))

    monkeypatch.setattr(job_runner, "_execute_job", breaks_the_transaction)
    await poll_and_execute_jobs(db_session, "test-job-broken", job_type=isolated_type)
    status, attempt_count, last_error = await _job_status(db_session, job_id)
    assert status == "failed" and attempt_count == 1
    assert last_error and "a_table_that_does_not_exist" in last_error


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
async def test_a_website_build_holds_its_claim_for_as_long_as_a_build_takes(
        db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from platform_worker import job_runner

    job_id = await _insert_async_job(db_session, job_type="website.generate",
                                     payload={"generation_job_id": str(uuid.uuid4())})
    seen: dict[str, Any] = {}

    async def a_long_build(session: AsyncSession, job: dict[str, Any]) -> None:
        row = await session.execute(text(
            "SELECT EXTRACT(EPOCH FROM (leased_until - now())) FROM platform_async_jobs WHERE id = :id"),
            {"id": str(job["id"])})
        seen["lease_left"] = float(row.scalar_one())

    monkeypatch.setattr(job_runner, "_execute_job", a_long_build)
    monkeypatch.setattr(job_runner, "claim_job_batch", _only(job_id, job_runner.claim_job_batch))
    await poll_and_execute_jobs(db_session, "test-job-long")
    assert seen["lease_left"] > 600  # not the two-minute claim


def _only(job_id: uuid.UUID, claim: Any) -> Any:
    async def claim_this(session: AsyncSession, worker_id: str, **kwargs: Any) -> list[Any]:
        rows = (await session.execute(text(
            "UPDATE platform_async_jobs SET status = 'processing', leased_until = now() + interval '120 seconds', "
            "leased_by = :w WHERE id = :id RETURNING *"), {"w": worker_id, "id": str(job_id)})).mappings()
        return list(rows)
    return claim_this
