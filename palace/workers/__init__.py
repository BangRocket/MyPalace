"""Background workers (phase 4 slice 3).

Postgres-backed job queue. The web process can opt to enqueue jobs
(`enqueue_handled`) instead of running them inline (`run_async`); a
separate worker process picks them up via SELECT ... FOR UPDATE SKIP
LOCKED, dispatches to the registered handler for the job's kind, and
records completion or failure.

To run the worker:
    python -m palace.workers.runner

Set ``PALACE_WORKER_QUEUE_ENABLED=true`` to switch the route handlers
that currently call ``run_async`` over to ``enqueue_handled``.
"""

from palace.workers.handlers import HANDLER_REGISTRY, register_handler
from palace.workers.queue import claim_next, complete_job, enqueue, extend_lease, fail_job

__all__ = [
    "HANDLER_REGISTRY",
    "claim_next",
    "complete_job",
    "enqueue",
    "extend_lease",
    "fail_job",
    "register_handler",
]
