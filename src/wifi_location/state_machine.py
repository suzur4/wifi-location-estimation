"""Decide whether one PC's latest area estimate is ready to display."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from numbers import Real

from .models import Estimate


class Phase(str, Enum):
    UNKNOWN = "UNKNOWN"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    STALE = "STALE"


@dataclass(frozen=True)
class FsmConfig:
    confirmations: int = 3
    max_age_seconds: float = 180
    min_aps: int = 2
    min_margin: float = 0.0

    def __post_init__(self):
        if type(self.confirmations) is not int or self.confirmations < 1:
            raise ValueError("confirmations must be a positive integer")
        if type(self.min_aps) is not int or self.min_aps < 1:
            raise ValueError("min_aps must be a positive integer")
        if not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be finite and positive")
        if not 0 <= self.min_margin <= 1:
            raise ValueError("min_margin must be between 0 and 1")


@dataclass(frozen=True)
class FsmState:
    phase: Phase = Phase.UNKNOWN
    area: str | None = None
    confirmations: int = 0
    observed_at: datetime | None = None
    reason: str = "fsm_reset"

    @property
    def display_area(self) -> str | None:
        return self.area if self.phase == Phase.CONFIRMED else None


def _seconds_between(later: datetime, earlier: datetime) -> float:
    if later.utcoffset() is None or earlier.utcoffset() is None:
        raise ValueError("FSM timestamps must include a timezone")
    return (later.astimezone(timezone.utc) - earlier.astimezone(timezone.utc)).total_seconds()


def expire(state: FsmState, *, now: datetime, config: FsmConfig) -> FsmState:
    """Clear old evidence at the freshness limit. A tick never confirms an area."""
    if state.observed_at is None or state.phase == Phase.STALE:
        return state
    age = _seconds_between(now, state.observed_at)
    if age >= config.max_age_seconds:
        return FsmState(Phase.STALE, observed_at=state.observed_at, reason="stale")
    if age < -5:
        return FsmState(observed_at=state.observed_at, reason="future_measurement")
    return state


def _has_margin(estimate: Estimate, minimum: float) -> bool:
    # Model scores are normalized support values, not confidence probabilities.
    scores = estimate.scores
    if estimate.area not in scores or any(
        not isinstance(value, Real) or isinstance(value, bool) or not 0 <= value <= 1
        for value in scores.values()
    ):
        return False
    if not math.isclose(sum(scores.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        return False
    other = max((value for area, value in scores.items() if area != estimate.area), default=0.0)
    margin = scores[estimate.area] - other
    return margin > 0 and (margin >= minimum or math.isclose(margin, minimum, rel_tol=0, abs_tol=1e-12))


def observe(
    state: FsmState, estimate: Estimate, *, observed_at: datetime,
    now: datetime, observed_aps: int, config: FsmConfig,
) -> FsmState:
    """Advance once per newer observation. Old or future events add no evidence."""
    state = expire(state, now=now, config=config)
    age = _seconds_between(now, observed_at)
    if age < -5 or (state.observed_at is not None and _seconds_between(observed_at, state.observed_at) <= 0):
        return state
    if age >= config.max_age_seconds:
        return FsmState(Phase.STALE, observed_at=observed_at, reason="stale")
    if not estimate.area or estimate.area == "unknown" or estimate.reason != "ok":
        reason = estimate.reason if estimate.reason != "ok" else "insufficient_data"
        return FsmState(observed_at=observed_at, reason=reason)
    if type(observed_aps) is not int or observed_aps < config.min_aps:
        return FsmState(observed_at=observed_at, reason="fsm_insufficient_aps")
    if not _has_margin(estimate, config.min_margin):
        return FsmState(observed_at=observed_at, reason="fsm_low_margin")
    count = min(config.confirmations, state.confirmations + 1) if state.area == estimate.area else 1
    if count >= config.confirmations:
        return FsmState(Phase.CONFIRMED, estimate.area, count, observed_at, "ok")
    return FsmState(Phase.CANDIDATE, estimate.area, count, observed_at, "fsm_pending")
