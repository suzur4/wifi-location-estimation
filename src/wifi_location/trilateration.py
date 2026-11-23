"""Anchor trilateration from RSSI, for comparison with fingerprinting.

GPS measures signal travel time with precise clocks. Here only RSSI exists, so
each anchor's distance comes from a log-distance path-loss model fitted to
labelled training data, and the position is the least-squares point that best
matches those distances. Simplification for this simulation: anchors and PCs
share one vertical plane, so coordinates along an axis where every anchor has
the same value are fixed to that value. Results are simulation-only.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math

import numpy as np

from .models import Estimate, Observation


@dataclass(frozen=True)
class PathLoss:
    """RSSI = p0 - 10 * n * log10(distance in metres)."""
    p0: float
    n: float

    def distance(self, rssi: float) -> float:
        return 10 ** ((self.p0 - rssi) / (10 * self.n))


def fit_path_loss(training: list[Observation], anchors: dict, area_positions: dict) -> PathLoss:
    """Least-squares fit of p0 and n from labelled samples; walls are not modelled."""
    logs, values = [], []
    for observation in training:
        position = area_positions.get(observation.area)
        if position is None:
            continue
        for ap, rssi in observation.readings.items():
            if ap in anchors:
                logs.append(math.log10(max(math.dist(position, anchors[ap]), 1.0)))
                values.append(rssi)
    if len(set(logs)) < 2:
        raise ValueError("path-loss fit needs readings from at least two distances")
    slope, intercept = np.polyfit(logs, values, 1)
    if slope >= 0:
        raise ValueError("fitted RSSI does not fall with distance")
    return PathLoss(float(intercept), float(-slope / 10))


class Trilaterator:
    """Same predict() interface as Engine, so experiments can evaluate both alike."""

    def __init__(self, training: list[Observation], anchors: dict, area_positions: dict,
                 min_anchors: int = 3, max_residual: float = math.inf, min_margin: float = 0.0,
                 max_age_seconds: float = 180, grid_step: float = 0.5, padding: float = 6.0):
        if min_anchors < 3:
            raise ValueError("a position in a plane needs at least three anchors")
        self.anchors = {ap: tuple(map(float, xyz)) for ap, xyz in anchors.items()}
        self.area_positions = {area: np.array(xyz, dtype=float) for area, xyz in area_positions.items()}
        self.model = fit_path_loss(training, self.anchors, area_positions)
        self.min_anchors, self.max_residual, self.min_margin = min_anchors, max_residual, min_margin
        self.max_age_seconds = max_age_seconds
        # Candidate positions: a grid around the anchors, flat along axes where they do not vary.
        points = np.array(list(self.anchors.values()))
        axes = []
        for low, high in zip(points.min(axis=0), points.max(axis=0)):
            axes.append(np.array([low]) if high - low < 1e-9
                        else np.arange(low - padding, high + padding + grid_step / 2, grid_step))
        self.grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)

    def locate(self, readings: dict[str, float]) -> tuple[np.ndarray, float]:
        """Grid point minimising the RMS gap between grid and RSSI distances, and that RMS (m)."""
        known = [ap for ap in readings if ap in self.anchors]
        targets = np.array([self.model.distance(readings[ap]) for ap in known])
        anchors = np.array([self.anchors[ap] for ap in known])
        gaps = np.linalg.norm(self.grid[:, None, :] - anchors[None, :, :], axis=2) - targets
        rms = np.sqrt(np.mean(gaps ** 2, axis=1))
        best = int(np.argmin(rms))
        return self.grid[best], float(rms[best])

    def predict(self, observation: Observation, now: datetime | None = None) -> Estimate:
        now = now or datetime.now(timezone.utc)
        age = (now - observation.timestamp).total_seconds()
        if age < -5:
            return Estimate(reason="future_measurement")
        if age > self.max_age_seconds:
            return Estimate(reason="stale")
        known = {ap: value for ap, value in observation.readings.items() if ap in self.anchors}
        if len(known) < self.min_anchors:
            return Estimate(reason="insufficient_data")
        point, residual = self.locate(known)
        if residual > self.max_residual:
            return Estimate(reason="unfamiliar_pattern", distance=residual)
        offsets = {area: float(np.linalg.norm(point - centre)) for area, centre in self.area_positions.items()}
        ordered = sorted(offsets, key=lambda area: (offsets[area], area))
        # Scores are relative closeness for display, not probabilities.
        weights = {area: 1 / (offsets[area] + 1) for area in offsets}
        total = sum(weights.values())
        scores = {area: weights[area] / total for area in weights}
        if offsets[ordered[1]] - offsets[ordered[0]] <= self.min_margin:
            return Estimate(reason="ambiguous", scores=scores, distance=residual)
        return Estimate(area=ordered[0], reason="ok", scores=scores, distance=residual)
