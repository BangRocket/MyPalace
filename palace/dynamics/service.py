"""DynamicsService — DB-touching wrapper around the FSRS-6 math.

Mirrors mypalclara's MemoryDynamicsManager surface but uses the
async SQLAlchemy session pattern shared with the rest of Palace.

Composite scoring formula (slice-3 design):
    composite = 0.6 * semantic + 0.4 * fsrs_score
    fsrs_score = (0.7 * retrievability + 0.3 * storage_strength) * importance_weight
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from palace.database import async_session
from palace.dynamics.fsrs import (
    FsrsParams,
    Grade,
    MemoryState,
    calculate_memory_score,
    retrievability,
    review,
)
from palace.models import DEFAULT_TENANT_ID, MemoryAccessLog, MemoryDynamics, utcnow

# Composite score weights — kept in module so tests can pin them.
SEMANTIC_WEIGHT = 0.6
DYNAMICS_WEIGHT = 0.4


def _now_naive() -> datetime:
    """FSRS math operates in naive UTC datetimes; the DB columns are TZ-aware
    so we convert at the boundary."""
    return datetime.now(UTC).replace(tzinfo=None)


def _to_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


class DynamicsService:
    """FSRS dynamics service. All methods are async and use async_session."""

    async def get_dynamics(
        self,
        memory_id: str,
        user_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> MemoryDynamics | None:
        async with async_session() as db:
            result = await db.execute(
                select(MemoryDynamics).where(
                    MemoryDynamics.memory_id == memory_id,
                    MemoryDynamics.user_id == user_id,
                    MemoryDynamics.tenant_id == tenant_id,
                ),
            )
            return result.scalar_one_or_none()

    async def ensure_dynamics(
        self,
        memory_id: str,
        user_id: str,
        is_key: bool = False,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> MemoryDynamics:
        async with async_session() as db:
            result = await db.execute(
                select(MemoryDynamics).where(
                    MemoryDynamics.memory_id == memory_id,
                    MemoryDynamics.user_id == user_id,
                    MemoryDynamics.tenant_id == tenant_id,
                ),
            )
            dynamics = result.scalar_one_or_none()
            if dynamics is None:
                dynamics = MemoryDynamics(
                    tenant_id=tenant_id,
                    memory_id=memory_id,
                    user_id=user_id,
                    is_key=is_key,
                )
                db.add(dynamics)
                await db.commit()
                await db.refresh(dynamics)
            return dynamics

    async def promote(
        self,
        memory_id: str,
        user_id: str,
        grade: int = 3,
        signal_type: str = "used_in_response",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> MemoryDynamics:
        """Apply an FSRS review to a memory. Auto-creates the dynamics row if
        missing. Logs an access record."""
        async with async_session() as db:
            result = await db.execute(
                select(MemoryDynamics).where(
                    MemoryDynamics.memory_id == memory_id,
                    MemoryDynamics.user_id == user_id,
                    MemoryDynamics.tenant_id == tenant_id,
                ),
            )
            dynamics = result.scalar_one_or_none()

            if dynamics is None:
                dynamics = MemoryDynamics(
                    tenant_id=tenant_id,
                    memory_id=memory_id,
                    user_id=user_id,
                )
                db.add(dynamics)
                await db.flush()

            now_naive = _now_naive()
            last_review_naive = _to_naive(dynamics.last_accessed_at)

            current_state = MemoryState(
                stability=dynamics.stability,
                difficulty=dynamics.difficulty,
                retrieval_strength=dynamics.retrieval_strength,
                storage_strength=dynamics.storage_strength,
                last_review=last_review_naive,
                review_count=dynamics.access_count,
            )

            if last_review_naive is not None:
                days_elapsed = (now_naive - last_review_naive).total_seconds() / 86400.0
            else:
                days_elapsed = 0.0
            current_r = retrievability(days_elapsed, dynamics.stability)

            grade_enum = Grade(grade)
            result_obj = review(current_state, grade_enum, now_naive, FsrsParams())

            dynamics.stability = result_obj.new_state.stability
            dynamics.difficulty = result_obj.new_state.difficulty
            dynamics.retrieval_strength = result_obj.new_state.retrieval_strength
            dynamics.storage_strength = result_obj.new_state.storage_strength
            dynamics.last_accessed_at = utcnow()
            dynamics.access_count = dynamics.access_count + 1
            dynamics.updated_at = utcnow()

            access_log = MemoryAccessLog(
                tenant_id=tenant_id,
                memory_id=memory_id,
                user_id=user_id,
                grade=grade,
                signal_type=signal_type,
                retrievability_at_access=current_r,
            )
            db.add(access_log)
            await db.commit()
            await db.refresh(dynamics)
            return dynamics

    async def demote(
        self,
        memory_id: str,
        user_id: str,
        reason: str = "user_correction",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> MemoryDynamics:
        """Mark memory as failed recall — equivalent to promote(grade=AGAIN)."""
        return await self.promote(
            memory_id=memory_id,
            user_id=user_id,
            grade=Grade.AGAIN.value,
            signal_type=reason,
            tenant_id=tenant_id,
        )

    async def score(
        self,
        memory_id: str,
        user_id: str,
        semantic_score: float,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict:
        """Composite ranking score combining semantic similarity with FSRS state.

        Auto-creates the dynamics row if missing (so first-score gets defaults
        rather than collapsing to pure semantic).
        """
        dynamics = await self.ensure_dynamics(memory_id, user_id, tenant_id=tenant_id)

        last_review_naive = _to_naive(dynamics.last_accessed_at)
        now_naive = _now_naive()
        if last_review_naive is not None:
            days_elapsed = (now_naive - last_review_naive).total_seconds() / 86400.0
        else:
            days_elapsed = 0.0
        current_r = retrievability(days_elapsed, dynamics.stability)

        importance = dynamics.importance_weight if dynamics.importance_weight else 1.0
        fsrs_score = calculate_memory_score(
            current_r,
            dynamics.storage_strength,
            importance,
        )
        composite = SEMANTIC_WEIGHT * semantic_score + DYNAMICS_WEIGHT * fsrs_score

        return {
            "composite_score": composite,
            "fsrs_score": fsrs_score,
            "retrievability": current_r,
            "storage_strength": dynamics.storage_strength,
        }

    async def prune_access_logs(
        self,
        retention_days: int = 90,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> int:
        """Delete access log rows older than retention_days. Returns count."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        async with async_session() as db:
            stmt = delete(MemoryAccessLog).where(
                MemoryAccessLog.accessed_at < cutoff,
                MemoryAccessLog.tenant_id == tenant_id,
            )
            result = await db.execute(stmt)
            await db.commit()
            return int(result.rowcount or 0)


# Singleton — matches the slice 1/2 service pattern.
dynamics_service = DynamicsService()
