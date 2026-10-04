import asyncio
import os
import signal
import socket
import sys
from typing import Any

from sqlalchemy import text

from platform_core.db import create_worker_session_factory
from platform_core.logging import bind_request_context, clear_request_context
from platform_core.logging import configure as configure_logging
from platform_core.logging import get_logger
from platform_worker.job_runner import poll_and_execute_jobs
from platform_worker.outbox_consumer import poll_and_dispatch_outbox, poll_and_run_deliveries
from platform_worker.scheduler import materialize_due_schedules

# Global flag for graceful shutdown
running = True

logger = get_logger("platform_worker")


def handle_shutdown_signal(sig: int, frame: Any) -> None:
    global running
    logger.info("worker.shutdown_signal", signal=sig)
    running = False


async def shutdown_tasks(sig: Any) -> None:
    global running
    logger.info("worker.shutdown_signal", signal=sig.name)
    running = False


async def _poll_lanes(session_factory: Any, worker_id: str) -> None:
    """Run the worker lanes sequentially with separate sessions."""
    async with session_factory() as session:
        outbox_count = await poll_and_dispatch_outbox(session, worker_id)
        if outbox_count:
            logger.info("worker.outbox_processed", count=outbox_count)

    # Separate session and separate lane from the fan-out above: a handler that
    # raises must not roll back the delivery rows that were just created for it.
    async with session_factory() as session:
        delivery_count = await poll_and_run_deliveries(session, worker_id)
        if delivery_count:
            logger.info("worker.deliveries_processed", count=delivery_count)

    async with session_factory() as session:
        schedule_count = await materialize_due_schedules(session, worker_id)
        if schedule_count:
            logger.info("worker.schedules_materialized", count=schedule_count)

    # Payment webhooks whose effect could not be applied yet: retried with
    # backoff, then dead-lettered — never lost (services/payment_webhook.py).
    async with session_factory() as session:
        from platform_core.services.payment_webhook import PaymentWebhookService

        webhook_count = await PaymentWebhookService.run_due(session, worker_id)
        if webhook_count:
            logger.info("worker.payment_webhooks_retried", count=webhook_count)

    async with session_factory() as session:
        job_count = await poll_and_execute_jobs(session, worker_id)
        if job_count:
            logger.info("worker.async_jobs_processed", count=job_count)

    # Automation ladders (Capability Universe §24 #4): renewals, reminders,
    # dunning and recalls run as due steps here — one engine, no per-module crons.
    async with session_factory() as session:
        from platform_core.automation import AutomationEngine

        step_count = await AutomationEngine.run_due(session, worker_id)
        if step_count:
            logger.info("worker.automation_steps_processed", count=step_count)


async def main() -> None:
    global running

    # AUD-11: configure structlog (redaction processor installed) before the
    # first log line ships.
    configure_logging()
    from platform_core.ai_guard import install_transport_guard

    # Inert unless LOCAH_TEST_NO_EXTERNAL_AI is set; then no paid call leaves.
    install_transport_guard()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # A `def` with an explicit default, not a lambda: add_signal_handler's
            # callback parameter is too loosely typed for mypy to infer a
            # lambda's parameter type from context, and `--python-platform`
            # only checks this branch on non-Windows.
            def _on_signal(s: signal.Signals = sig) -> None:
                asyncio.create_task(shutdown_tasks(s))

            loop.add_signal_handler(sig, _on_signal)
    else:
        signal.signal(signal.SIGINT, handle_shutdown_signal)
        signal.signal(signal.SIGTERM, handle_shutdown_signal)

    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    bind_request_context(correlation_id=worker_id)
    logger.info("worker.starting", worker_id=worker_id)

    if not os.getenv("DATABASE_URL"):
        logger.error("worker.database_url_missing")
        sys.exit(1)

    try:
        engine, session_factory = create_worker_session_factory(role="service")
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        logger.info("worker.db_connected")
    except Exception as e:
        logger.error("worker.db_init_failed", error=str(e))
        sys.exit(1)

    poll_interval = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2"))
    logger.info("worker.polling", interval_seconds=poll_interval)

    while running:
        try:
            await _poll_lanes(session_factory, worker_id)
        except Exception as e:
            logger.error("worker.poll_error", error=str(e), exc_info=e)
        await asyncio.sleep(poll_interval)

    logger.info("worker.disposing_engine")
    await engine.dispose()
    clear_request_context()
    logger.info("worker.shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        get_logger("platform_worker").info("worker.keyboard_interrupt")
