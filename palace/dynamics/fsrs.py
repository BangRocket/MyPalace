"""FSRS-6 spaced repetition algorithm implementation.

Free Spaced Repetition Scheduler (FSRS) is an evidence-based scheduling algorithm
that uses a power-law forgetting curve to predict memory retention.

This implementation is based on FSRS v6 from the Anki FSRS project.

Ported character-for-character from mypalclara/core/memory/dynamics/fsrs.py
(slice-3 design D1) — math is well-tested upstream and rewriting risks
subtle off-by-one errors. Keep this file isolated so FSRS-7 can be swapped in
later.

References:
- https://github.com/open-spaced-repetition/fsrs4anki
- https://arxiv.org/abs/2402.12291 (FSRS paper)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum


class Grade(IntEnum):
    """FSRS review grades.

    The grade represents how well the memory was recalled:
    - AGAIN: Complete failure to recall
    - HARD: Recalled with significant difficulty
    - GOOD: Recalled correctly with some effort
    - EASY: Recalled effortlessly
    """

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass
class FsrsParams:
    """FSRS-6 parameters.

    These are the default parameters from Anki FSRS research.
    They can be customized per user through optimization if desired.

    The 21 parameters control various aspects of the scheduling:
    - w[0-3]: Initial stability after first review for grades Again/Hard/Good/Easy
    - w[4-7]: Initial difficulty parameters
    - w[8-10]: Stability increase factors
    - w[11-13]: Difficulty adjustment factors
    - w[14-16]: Retrievability decay factors
    - w[17-20]: Additional stability modifiers
    """

    w: tuple[float, ...] = (
        0.212,  # w[0]: Initial stability for Again
        1.2931,  # w[1]: Initial stability for Hard
        2.3065,  # w[2]: Initial stability for Good
        8.2956,  # w[3]: Initial stability for Easy
        6.4133,  # w[4]: Initial difficulty mean
        0.8334,  # w[5]: Initial difficulty modifier
        3.0194,  # w[6]: Stability increase base
        0.001,  # w[7]: Stability increase grade modifier
        1.8722,  # w[8]: Stability after lapse multiplier
        0.1666,  # w[9]: Hard penalty
        0.796,  # w[10]: Easy bonus
        1.4835,  # w[11]: Difficulty after success
        0.0614,  # w[12]: Difficulty after failure
        0.2629,  # w[13]: Difficulty constraint
        1.6483,  # w[14]: Short-term stability factor
        0.6014,  # w[15]: Long-term stability factor
        1.8729,  # w[16]: Stability growth rate
        0.5425,  # w[17]: Difficulty growth rate
        0.0912,  # w[18]: Stability decay on lapse
        0.0658,  # w[19]: Difficulty decay on lapse
        0.1542,  # w[20]: Power-law decay exponent (retrievability)
    )


@dataclass
class MemoryState:
    """Current state of a memory item.

    Attributes:
        stability: Days until retrievability drops to 90% (S)
        difficulty: Inherent difficulty 1-10 (D)
        retrieval_strength: Current ability to recall (R_r) - decays over time
        storage_strength: Consolidated long-term strength (R_s) - grows with practice
        last_review: When the memory was last accessed
        review_count: Total number of reviews
    """

    stability: float = 1.0
    difficulty: float = 5.0
    retrieval_strength: float = 1.0
    storage_strength: float = 0.5
    last_review: datetime | None = None
    review_count: int = 0


@dataclass
class ReviewResult:
    """Result of applying a review to a memory state.

    Attributes:
        new_state: Updated memory state after review
        retrievability_before: R value before the review
        next_review_days: Recommended days until next review
    """

    new_state: MemoryState
    retrievability_before: float
    next_review_days: float


def retrievability(
    days_elapsed: float,
    stability: float,
    w20: float = 0.1542,
) -> float:
    """Calculate probability of recall using FSRS-6 power-law decay.

    The forgetting curve follows a power-law decay:
    R(t) = (1 + t/S * factor)^(-w20)

    Where:
    - t is elapsed time in days
    - S is stability (days for R to drop to 90%)
    - w20 is the decay exponent
    - factor is derived from the 90% retention definition

    Args:
        days_elapsed: Days since last review
        stability: Current stability value
        w20: Power-law decay exponent (default from FSRS-6)

    Returns:
        Retrievability between 0 and 1 (probability of recall)
    """
    if days_elapsed <= 0:
        return 1.0
    if stability <= 0:
        return 0.0

    # Factor derived from: R(S) = 0.9 -> (1 + S/S * factor)^(-w20) = 0.9
    # -> (1 + factor)^(-w20) = 0.9
    # -> factor = 0.9^(-1/w20) - 1
    factor = math.pow(0.9, -1.0 / w20) - 1.0

    return math.pow(1.0 + factor * days_elapsed / stability, -w20)


def initial_stability(grade: Grade, params: FsrsParams) -> float:
    """Calculate initial stability for a new memory item.

    Args:
        grade: First review grade
        params: FSRS parameters

    Returns:
        Initial stability value
    """
    # w[0-3] contain initial stability for grades 1-4
    return params.w[grade.value - 1]


def initial_difficulty(grade: Grade, params: FsrsParams) -> float:
    """Calculate initial difficulty for a new memory item.

    D0 = w[4] - exp(w[5] * (grade - 1)) + 1

    Args:
        grade: First review grade
        params: FSRS parameters

    Returns:
        Initial difficulty (1-10)
    """
    d0 = params.w[4] - math.exp(params.w[5] * (grade.value - 1)) + 1
    return _constrain_difficulty(d0)


def _constrain_difficulty(d: float) -> float:
    """Constrain difficulty to valid range [1, 10]."""
    return max(1.0, min(10.0, d))


def _mean_reversion(d: float, params: FsrsParams) -> float:
    """Apply mean reversion to difficulty.

    Prevents difficulty from drifting too far from the mean.
    """
    return params.w[13] * params.w[4] + (1 - params.w[13]) * d


def update_difficulty(
    current_difficulty: float,
    grade: Grade,
    params: FsrsParams,
) -> float:
    """Update difficulty after a review.

    D' = w[13] * D0 + (1 - w[13]) * (D + w[11] * (grade - 3))

    Args:
        current_difficulty: Current difficulty value
        grade: Review grade
        params: FSRS parameters

    Returns:
        Updated difficulty (1-10)
    """
    # Delta based on grade deviation from "Good" (3)
    delta = params.w[11] * (grade.value - 3)

    # Apply mean reversion
    new_d = _mean_reversion(current_difficulty + delta, params)

    return _constrain_difficulty(new_d)


def update_stability_success(
    current_stability: float,
    current_difficulty: float,
    current_retrievability: float,
    grade: Grade,
    params: FsrsParams,
) -> float:
    """Update stability after successful recall (grade >= 2).

    S' = S * (1 + exp(w[6]) * (11 - D) * S^(-w[7]) * (exp(w[8] * (1 - R)) - 1) * bonus)

    Where bonus depends on grade (hard penalty or easy bonus).

    Args:
        current_stability: Current stability value
        current_difficulty: Current difficulty value
        current_retrievability: Retrievability at time of review
        grade: Review grade (must be >= HARD)
        params: FSRS parameters

    Returns:
        Updated stability value
    """
    # Hard penalty or easy bonus
    if grade == Grade.HARD:
        bonus = params.w[9]  # Hard penalty (< 1)
    elif grade == Grade.EASY:
        bonus = params.w[10]  # Easy bonus (> 1)
    else:
        bonus = 1.0

    # Stability increase factor
    stability_factor = math.exp(params.w[6])

    # Difficulty factor (easier = larger increase)
    difficulty_factor = 11 - current_difficulty

    # Stability decay factor (higher stability = smaller increase)
    stability_decay = math.pow(current_stability, -params.w[7])

    # Retrievability factor (lower R = larger increase after success)
    retrievability_factor = math.exp(params.w[8] * (1 - current_retrievability)) - 1

    # Calculate new stability
    growth = stability_factor * difficulty_factor * stability_decay * retrievability_factor * bonus
    new_stability = current_stability * (1 + growth)

    return max(0.1, new_stability)  # Minimum stability of 0.1 days


def update_stability_failure(
    current_stability: float,
    current_difficulty: float,
    current_retrievability: float,
    params: FsrsParams,
) -> float:
    """Update stability after failed recall (grade = AGAIN).

    S' = w[14] * D^(-w[15]) * ((S + 1)^w[16] - 1) * exp(w[17] * (1 - R))

    This represents a "lapse" - the memory needs relearning.

    Args:
        current_stability: Current stability value
        current_difficulty: Current difficulty value
        current_retrievability: Retrievability at time of review
        params: FSRS parameters

    Returns:
        Updated stability value (typically lower)
    """
    # Post-lapse stability formula
    difficulty_factor = math.pow(current_difficulty, -params.w[15])
    stability_factor = math.pow(current_stability + 1, params.w[16]) - 1
    retrievability_factor = math.exp(params.w[17] * (1 - current_retrievability))

    new_stability = params.w[14] * difficulty_factor * stability_factor * retrievability_factor

    return max(0.1, min(new_stability, current_stability))  # Don't increase on failure


def update_dual_strength(
    current_retrieval: float,
    current_storage: float,
    grade: Grade,
    elapsed_days: float,
) -> tuple[float, float]:
    """Update dual-strength memory model (Bjork's New Theory of Disuse).

    Retrieval strength (R_r): How accessible the memory is NOW
    - Decays over time
    - Boosted by successful retrieval

    Storage strength (R_s): How well-learned the memory is
    - Grows with each successful retrieval
    - Grows MORE when retrieval strength is LOW (desirable difficulty)

    Args:
        current_retrieval: Current retrieval strength
        current_storage: Current storage strength
        grade: Review grade
        elapsed_days: Days since last review

    Returns:
        Tuple of (new_retrieval_strength, new_storage_strength)
    """
    # Retrieval strength decays exponentially
    decay_rate = 0.1 * (1 / (1 + current_storage))  # Higher storage = slower decay
    decayed_retrieval = current_retrieval * math.exp(-decay_rate * elapsed_days)

    if grade == Grade.AGAIN:
        # Failed recall: reset retrieval strength, small storage gain
        new_retrieval = 0.3
        new_storage = current_storage + 0.05
    else:
        # Successful recall: boost retrieval, increase storage
        # Desirable difficulty: lower retrieval = higher storage gain
        difficulty_bonus = max(0, 1 - decayed_retrieval)

        if grade == Grade.HARD:
            retrieval_boost = 0.5
            storage_gain = 0.1 + 0.1 * difficulty_bonus
        elif grade == Grade.GOOD:
            retrieval_boost = 0.7
            storage_gain = 0.15 + 0.15 * difficulty_bonus
        else:  # EASY
            retrieval_boost = 0.9
            storage_gain = 0.1 + 0.05 * difficulty_bonus  # Easy = less effort = less gain

        new_retrieval = min(1.0, decayed_retrieval + retrieval_boost)
        new_storage = min(1.0, current_storage + storage_gain)

    return new_retrieval, new_storage


def review(
    state: MemoryState,
    grade: Grade,
    review_time: datetime | None = None,
    params: FsrsParams | None = None,
) -> ReviewResult:
    """Apply a review to a memory state.

    This is the main entry point for updating a memory after recall.

    Args:
        state: Current memory state
        grade: Review grade
        review_time: When the review occurred (default: now)
        params: FSRS parameters (default: standard params)

    Returns:
        ReviewResult with updated state and metrics
    """
    if params is None:
        params = FsrsParams()
    if review_time is None:
        from datetime import UTC

        review_time = datetime.now(UTC).replace(tzinfo=None)

    # Calculate elapsed time
    if state.last_review is None:
        elapsed_days = 0.0
    else:
        elapsed_days = (review_time - state.last_review).total_seconds() / 86400.0

    # Calculate current retrievability
    if state.review_count == 0:
        current_r = 1.0
    else:
        current_r = retrievability(elapsed_days, state.stability, params.w[20])

    # First review: initialize
    if state.review_count == 0:
        new_stability = initial_stability(grade, params)
        new_difficulty = initial_difficulty(grade, params)
    else:
        # Update difficulty
        new_difficulty = update_difficulty(state.difficulty, grade, params)

        # Update stability based on grade
        if grade == Grade.AGAIN:
            new_stability = update_stability_failure(
                state.stability,
                state.difficulty,
                current_r,
                params,
            )
        else:
            new_stability = update_stability_success(
                state.stability,
                state.difficulty,
                current_r,
                grade,
                params,
            )

    # Update dual-strength model
    new_retrieval, new_storage = update_dual_strength(
        state.retrieval_strength,
        state.storage_strength,
        grade,
        elapsed_days,
    )

    # Create new state
    new_state = MemoryState(
        stability=new_stability,
        difficulty=new_difficulty,
        retrieval_strength=new_retrieval,
        storage_strength=new_storage,
        last_review=review_time,
        review_count=state.review_count + 1,
    )

    # Calculate next review interval (when R drops to ~90%)
    next_review_days = new_stability

    return ReviewResult(
        new_state=new_state,
        retrievability_before=current_r,
        next_review_days=next_review_days,
    )


def infer_grade_from_signal(signal_type: str, context: dict | None = None) -> Grade:
    """Infer review grade from a usage signal type.

    The memory system doesn't have explicit review UI, so we infer
    grades from implicit signals like:
    - Memory was used in a response (implicit recall)
    - User corrected the response (implicit failure)
    - Memory helped complete a task (strong success)

    Args:
        signal_type: Type of signal (see below)
        context: Optional additional context

    Signal types:
        - "used_in_response": Memory was retrieved and included in context
        - "mentioned_by_user": User explicitly referenced this memory
        - "user_correction": User corrected information from memory
        - "task_completed": Memory helped complete a user task
        - "explicit_recall": User explicitly asked to remember
        - "contradiction_detected": New info contradicts this memory
        - "time_decay": Passive decay (no actual review)

    Returns:
        Inferred grade
    """
    grade_map = {
        "used_in_response": Grade.GOOD,
        "mentioned_by_user": Grade.EASY,
        "user_correction": Grade.AGAIN,
        "task_completed": Grade.EASY,
        "explicit_recall": Grade.GOOD,
        "contradiction_detected": Grade.AGAIN,
        "implicit_reference": Grade.GOOD,
        "partial_recall": Grade.HARD,
    }

    return grade_map.get(signal_type, Grade.GOOD)


def calculate_memory_score(
    retrievability: float,
    storage_strength: float,
    importance_weight: float = 1.0,
) -> float:
    """Calculate a composite memory score for ranking.

    Combines retrievability and storage strength with optional
    importance weighting for search result ranking.

    Args:
        retrievability: Current R value (0-1)
        storage_strength: Storage strength R_s (0-1)
        importance_weight: Optional multiplier for key memories

    Returns:
        Composite score for ranking (higher = more relevant)
    """
    # Weighted combination: retrievability matters more for immediate use
    base_score = 0.7 * retrievability + 0.3 * storage_strength

    return base_score * importance_weight
