"""Scheduled backup worker (phase 9 slice 3).

Standalone process. Run with:
    python -m mypalace.workers.backup

On each tick: enumerate every tenant, stream the same NDJSON export the
/v1/admin/export endpoint produces, gzip it to disk under
PALACE_BACKUP_DIR, and prune files older than PALACE_BACKUP_RETAIN_DAYS.

Why a separate process instead of a job in the existing queue:
- Backups are large and long-running; sharing the main worker's slot
  would block reflection / synthesis jobs for minutes.
- Schedule is fixed-interval, not event-driven; the queue would need a
  scheduler in front of it anyway.
- Restartable independently — operators can pause backups without
  affecting application work.

Disabled by default. Set PALACE_BACKUP_ENABLED=true to enable.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from mypalace.api.portability import _stream_export
from mypalace.config import settings
from mypalace.database import async_session
from mypalace.models import Tenant
from mypalace.observability.logging import configure_logging

logger = logging.getLogger(__name__)
_shutdown = asyncio.Event()


async def _list_tenant_ids() -> list[str]:
    """Fetch every tenant id (alphabetical for stable ordering)."""
    async with async_session() as db:
        result = await db.execute(select(Tenant.id).order_by(Tenant.id))
        return list(result.scalars().all())


def _backup_path(backup_dir: Path, tenant_id: str, ts: datetime) -> Path:
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    return backup_dir / f"{tenant_id}-{stamp}.ndjson.gz"


async def backup_tenant(tenant_id: str, backup_dir: Path, ts: datetime) -> Path:
    """Stream export for one tenant; gzip to disk; return path."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    out_path = _backup_path(backup_dir, tenant_id, ts)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")

    bytes_written = 0
    start = time.perf_counter()
    with gzip.open(tmp_path, "wb") as f:
        async for chunk in _stream_export(tenant_id):
            f.write(chunk)
            bytes_written += len(chunk)
    tmp_path.rename(out_path)  # atomic publish
    elapsed = time.perf_counter() - start
    logger.info(
        "backup wrote tenant=%s bytes=%d elapsed=%.2fs path=%s",
        tenant_id, bytes_written, elapsed, out_path,
    )
    return out_path


def prune_old_backups(backup_dir: Path, retain_days: int) -> int:
    """Delete *.ndjson.gz files older than retain_days. Returns count pruned.

    Uses mtime, not the timestamp embedded in the filename — clock-skew
    safe and consistent with what `find -mtime` would do.
    """
    if not backup_dir.exists():
        return 0
    cutoff = time.time() - (retain_days * 86400)
    pruned = 0
    for path in backup_dir.glob("*.ndjson.gz"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                pruned += 1
                logger.info("backup pruned old=%s", path.name)
        except OSError as e:
            logger.warning("backup prune failed path=%s err=%r", path, e)
    return pruned


async def run_once(backup_dir: Path, retain_days: int) -> dict[str, int]:
    """One full backup pass: every tenant + prune. Returns summary counts."""
    ts = datetime.now(UTC)
    tenant_ids = await _list_tenant_ids()
    succeeded = 0
    failed = 0
    for tid in tenant_ids:
        try:
            await backup_tenant(tid, backup_dir, ts)
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.exception("backup failed tenant=%s err=%r", tid, e)
    pruned = prune_old_backups(backup_dir, retain_days)
    return {
        "tenants_total": len(tenant_ids),
        "succeeded": succeeded,
        "failed": failed,
        "pruned": pruned,
    }


async def run() -> None:
    """Main loop. Sleeps interval_hours between passes; honors shutdown."""
    configure_logging()
    if not settings.backup_enabled:
        logger.warning(
            "PALACE_BACKUP_ENABLED is false; backup worker exiting.",
        )
        return

    backup_dir = Path(settings.backup_dir)
    interval_seconds = settings.backup_interval_hours * 3600
    retain_days = settings.backup_retain_days

    logger.info(
        "backup worker starting dir=%s interval_h=%d retain_d=%d",
        backup_dir, settings.backup_interval_hours, retain_days,
    )

    while not _shutdown.is_set():
        try:
            summary = await run_once(backup_dir, retain_days)
            logger.info("backup pass summary=%s", summary)
        except Exception:
            logger.exception("backup pass crashed; will retry next interval")

        next_run = datetime.now(UTC) + timedelta(seconds=interval_seconds)
        logger.info("backup next run at %s", next_run.isoformat())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_shutdown.wait(), timeout=interval_seconds)

    logger.info("backup worker shutting down")


def _install_signal_handlers() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _shutdown.set)


async def _main() -> None:
    _install_signal_handlers()
    await run()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
