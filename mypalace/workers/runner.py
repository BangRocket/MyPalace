"""Worker process entrypoint.

Run with:
    python -m palace.workers.runner

The runner is intentionally simple: one event loop, one polling
coroutine, sequential job processing. For higher throughput run
multiple worker processes — SKIP LOCKED gives them safe concurrency
out of the box.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from mypalace.config import settings
from mypalace.observability.logging import configure_logging
from mypalace.observability.metrics import job_total
from mypalace.workers.handlers import HANDLER_REGISTRY
from mypalace.workers.queue import (
    claim_next,
    complete_job,
    fail_job,
)

logger = logging.getLogger(__name__)
_shutdown = asyncio.Event()


async def process_one() -> bool:
    """Claim and process one job. Returns True iff a job was attempted
    (so the loop can sleep only when the queue is empty)."""
    job = await claim_next()
    if job is None:
        return False

    handler = HANDLER_REGISTRY.get(job.kind)
    if handler is None:
        # Unknown kind — treat as permanent failure.
        await fail_job(
            job.id, f"unknown job kind: {job.kind}",
            tenant_id=job.tenant_id, permanent=True,
        )
        job_total.labels(kind=job.kind, outcome="failed_unknown").inc()
        return True

    try:
        result = await handler(job.payload_json or {}, job.tenant_id)
        await complete_job(job.id, result, tenant_id=job.tenant_id)
        job_total.labels(kind=job.kind, outcome="completed").inc()
    except Exception as e:
        permanent = job.attempts >= settings.worker_max_attempts
        await fail_job(job.id, repr(e), tenant_id=job.tenant_id, permanent=permanent)
        outcome = "failed_permanent" if permanent else "failed_retry"
        job_total.labels(kind=job.kind, outcome=outcome).inc()
        logger.warning(
            "job %s (%s) attempt %d/%d failed: %r",
            job.id, job.kind, job.attempts, settings.worker_max_attempts, e,
        )
    return True


async def run() -> None:
    """Main worker loop. Polls every ``worker_poll_interval`` when idle;
    immediately tries again after processing a job."""
    configure_logging()
    logger.info(
        "Palace worker starting (poll=%.1fs, lease=%ds, max_attempts=%d, "
        "kinds=%s)",
        settings.worker_poll_interval,
        settings.worker_lease_seconds,
        settings.worker_max_attempts,
        sorted(HANDLER_REGISTRY.keys()),
    )

    while not _shutdown.is_set():
        try:
            did_work = await process_one()
        except Exception:
            logger.exception("worker iteration crashed; backing off")
            did_work = False

        if did_work:
            # Loop right away — there might be more.
            continue
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                _shutdown.wait(), timeout=settings.worker_poll_interval,
            )

    logger.info("Palace worker shutting down")


def _install_signal_handlers() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            # Windows lacks signal handler support on the event loop
            loop.add_signal_handler(sig, _shutdown.set)


def main() -> None:
    asyncio.run(_main())


async def _main() -> None:
    _install_signal_handlers()
    await run()


if __name__ == "__main__":
    main()
