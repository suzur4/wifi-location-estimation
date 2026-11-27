"""Two ways to combine the GPS-like anchor model with RSSI fingerprints.

ModelFingerprint predicts each area's RSSI from distance and floors crossed
(a simplified multi-wall path-loss model), then shifts each prediction toward
the measured samples of that area. With few samples the physical prior
dominates; with many it approaches the measured area mean. Matching is done
in RSSI space, so no RSSI-to-distance conversion amplifies the noise.

Agreement shows an area only when every given model independently shows it.
Results are simulation-only.
"""

from datetime import datetime, timezone
import math

import numpy as np

from .models import Estimate, Observation


def fit_multiwall(training, anchors, area_positions, floor_height):
    """Least squares RSSI = p0 - 10 n log10(d) - floor_db * floors crossed; returns (p0, n, floor_db)."""
    rows, values = [], []
    for observation in training:
        position = area_positions.get(observation.area)
        if position is None:
            continue
        for ap, rssi in observation.readings.items():
            if ap in anchors:
                distance = max(math.dist(position, anchors[ap]), 1.0)
                floors = round(abs(position[2] - anchors[ap][2]) / floor_height)
                rows.append((1.0, -10 * math.log10(distance), -floors))
                values.append(rssi)
    matrix = np.array(rows)
    if len(rows) < 3 or np.linalg.matrix_rank(matrix) < 3:
        # Without readings across floors the floor term cannot be separated; drop it.
        if len({r[1] for r in rows}) < 2:
            raise ValueError("model fit needs readings from at least two distances")
        p0, n = np.linalg.lstsq(matrix[:, :2], values, rcond=None)[0]
        return float(p0), float(n), 0.0
    p0, n, floor_db = np.linalg.lstsq(matrix, values, rcond=None)[0]
    return float(p0), float(n), float(floor_db)


class ModelFingerprint:
    """Same predict() interface as Engine."""

    def __init__(self, training: list[Observation], anchors: dict, area_positions: dict,
                 floor_height: float = 4.0, shrink: float = 4.0, offset_free: bool = False,
                 min_aps: int = 2, max_distance: float = math.inf, min_margin: float = 0.0,
                 max_age_seconds: float = 180):
        if shrink < 0 or min_aps < 1:
            raise ValueError("shrink must be non-negative and min_aps positive")
        self.aps = sorted(anchors)
        self.areas = sorted(area_positions)
        self.offset_free, self.min_aps = offset_free, min_aps
        self.max_distance, self.min_margin, self.max_age_seconds = max_distance, min_margin, max_age_seconds
        self.params = fit_multiwall(training, anchors, area_positions, floor_height)
        p0, n, floor_db = self.params
        prior = np.array([[p0 - 10 * n * math.log10(max(math.dist(area_positions[area], anchors[ap]), 1.0))
                           - floor_db * round(abs(area_positions[area][2] - anchors[ap][2]) / floor_height)
                           for ap in self.aps] for area in self.areas])
        # Shrunk mean residual: sum / (count + shrink) moves toward the data as samples accumulate.
        sums, counts = np.zeros_like(prior), np.zeros_like(prior)
        for observation in training:
            if observation.area not in self.areas:
                continue
            row = self.areas.index(observation.area)
            for col, ap in enumerate(self.aps):
                if ap in observation.readings:
                    sums[row, col] += observation.readings[ap] - prior[row, col]
                    counts[row, col] += 1
        self.expected = prior + sums / (counts + shrink) if shrink > 0 else np.where(
            counts > 0, prior + sums / np.maximum(counts, 1), prior)

    def predict(self, observation: Observation, now: datetime | None = None) -> Estimate:
        now = now or datetime.now(timezone.utc)
        age = (now - observation.timestamp).total_seconds()
        if age < -5:
            return Estimate(reason="future_measurement")
        if age >= self.max_age_seconds:
            return Estimate(reason="stale")
        cols = [i for i, ap in enumerate(self.aps) if ap in observation.readings]
        if len(cols) < self.min_aps:
            return Estimate(reason="insufficient_data")
        query = np.array([observation.readings[self.aps[i]] for i in cols])
        gaps = query[None, :] - self.expected[:, cols]
        if self.offset_free:
            # Ignore a uniform shift, such as a different Wi-Fi adapter's gain.
            gaps = gaps - gaps.mean(axis=1, keepdims=True)
        rms = np.sqrt(np.mean(gaps ** 2, axis=1))
        order = np.argsort(rms, kind="stable")
        best, second = float(rms[order[0]]), float(rms[order[1]])
        weights = 1 / (rms + 1)
        scores = {area: float(w / weights.sum()) for area, w in zip(self.areas, weights)}
        if best > self.max_distance:
            return Estimate(reason="unfamiliar_pattern", distance=best)
        if second - best <= self.min_margin:
            return Estimate(reason="ambiguous", scores=scores, distance=best)
        return Estimate(area=self.areas[order[0]], reason="ok", scores=scores, distance=best)


class Agreement:
    """Show an area only when all models show the same one; otherwise unknown."""

    def __init__(self, *models):
        if len(models) < 2:
            raise ValueError("agreement needs at least two models")
        self.models = models

    def predict(self, observation: Observation, now: datetime | None = None) -> Estimate:
        estimates = [model.predict(observation, now) for model in self.models]
        for estimate in estimates:
            if estimate.reason != "ok":
                return Estimate(reason=estimate.reason, distance=estimate.distance)
        areas = {estimate.area for estimate in estimates}
        if len(areas) > 1:
            return Estimate(reason="ambiguous")
        return Estimate(area=areas.pop(), reason="ok", scores=estimates[0].scores, distance=estimates[0].distance)
