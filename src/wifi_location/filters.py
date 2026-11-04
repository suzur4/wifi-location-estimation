"""Causal RSSI filters for stationary sessions, never position/trajectory filters.

Kalman model: x[t] = x[t-1] + w, z[t] = x[t] + v, with w~N(0,Q),
v~N(0,R). Q permits RSSI drift, R expresses measurement noise, and initial
variance expresses uncertainty before the first measurement. Parameters use
squared dBm units. A filter is reset after an AP disappears or a session ends.
"""

from collections import defaultdict, deque
from dataclasses import replace
import math
import statistics

from .models import Observation


class Kalman1D:
    def __init__(self, q: float = 1, r: float = 16, initial_variance: float = 25):
        if not all(math.isfinite(x) for x in (q, r, initial_variance)):
            raise ValueError("Kalman parameters must be finite")
        if q < 0 or r <= 0 or initial_variance < 0:
            raise ValueError("require Q >= 0, R > 0, initial_variance >= 0")
        self.q, self.r, self.variance = q, r, initial_variance
        self.value: float | None = None

    def update(self, measurement: float) -> float:
        if not math.isfinite(measurement):
            raise ValueError("measurement must be finite")
        if self.value is None:
            self.value = float(measurement)
            return self.value
        prior_variance = self.variance + self.q
        gain = prior_variance / (prior_variance + self.r)
        self.value += gain * (measurement - self.value)
        self.variance = (1 - gain) * prior_variance
        return self.value


def robust_mean(values: list[float]) -> float:
    """Mean after excluding points beyond 3 scaled median absolute deviations."""
    center = statistics.median(values)
    mad = statistics.median([abs(x - center) for x in values])
    # The floor handles repeated measurements with one extreme value.
    cutoff = max(3 * 1.4826 * mad, 3.0)
    kept = [x for x in values if abs(x - center) <= cutoff]
    return statistics.mean(kept)


def preprocess(
    observations: list[Observation], method: str = "none", window: int = 5,
    alpha: float = .35, q: float = 1, r: float = 16, initial_variance: float = 25,
) -> list[Observation]:
    """Filter in timestamp order within (source, device, session).

    Return results in input order. An AP absent from the current sample is
    absent from its output, and its previous filter state is discarded.
    Separate calls do not share any state (e.g. train/validation/test).
    """
    if method == "raw":
        method = "none"
    if method not in {"none", "mean", "median", "robust_mean", "ema", "kalman"}:
        raise ValueError(f"unknown preprocessing method: {method}")
    if window < 1 or not 0 < alpha <= 1:
        raise ValueError("window >= 1 and 0 < alpha <= 1 required")
    Kalman1D(q, r, initial_variance)  # validate even for an empty series
    groups: dict[tuple, list[tuple[int, Observation]]] = defaultdict(list)
    for index, observation in enumerate(observations):
        groups[(observation.source, observation.device_id, observation.session_id)].append((index, observation))
    result: list[Observation | None] = [None] * len(observations)
    for entries in groups.values():
        histories: dict[str, deque] = {}
        ema_values: dict[str, float] = {}
        kalman: dict[str, Kalman1D] = {}
        for index, observation in sorted(entries, key=lambda x: x[1].timestamp):
            present = set(observation.readings)
            for state in (histories, ema_values, kalman):
                for ap in list(state):
                    if ap not in present:
                        del state[ap]
            readings = {}
            for ap, value in observation.readings.items():
                history = histories.setdefault(ap, deque(maxlen=window))
                history.append(float(value))
                if method == "none":
                    filtered = value
                elif method == "mean":
                    filtered = statistics.mean(history)
                elif method == "median":
                    filtered = statistics.median(history)
                elif method == "robust_mean":
                    filtered = robust_mean(list(history))
                elif method == "ema":
                    filtered = alpha * value + (1-alpha) * ema_values.get(ap, value)
                    ema_values[ap] = filtered
                else:
                    filtered = kalman.setdefault(ap, Kalman1D(q, r, initial_variance)).update(value)
                readings[ap] = float(filtered)
            result[index] = replace(observation, readings=readings)
    return [observation for observation in result if observation is not None]
