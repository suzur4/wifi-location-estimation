"""Interchangeable baselines and fingerprint area classifiers.

Scores describe a model's relative support, not calibrated probabilities.
Unknown gates deliberately sacrifice coverage to reduce wrong displays.
"""

from collections import defaultdict
from datetime import datetime, timezone
import math
import numpy as np

from .models import Estimate, Observation


ALGORITHMS = ("connected_ap", "strongest_ap", "1nn", "knn", "weighted_knn", "rank", "gaussian")
MISSING_RSSI = -100.0


class Engine:
    def __init__(
        self, training: list[Observation], ap_areas: dict[str, str],
        algorithm: str = "knn", k: int = 5, min_aps: int = 2,
        max_age_seconds: float = 180, max_distance: float = 24,
        min_margin: float = .05, selected_aps: list[str] | None = None,
    ):
        if algorithm not in ALGORITHMS:
            raise ValueError(f"unknown algorithm: {algorithm}")
        if k < 1 or min_aps < 1:
            raise ValueError("k and min_aps must be positive")
        if not all(math.isfinite(x) for x in (max_age_seconds, max_distance, min_margin)):
            raise ValueError("thresholds must be finite")
        if max_age_seconds <= 0 or max_distance <= 0 or not 0 <= min_margin <= 1:
            raise ValueError("invalid reliability thresholds")
        self.training = [x for x in training if x.area and x.area != "unknown"]
        sources = {x.source for x in self.training}
        if len(sources) > 1:
            raise ValueError("different collection sources must not be mixed without validation")
        self.source = next(iter(sources), None)
        self.ap_areas, self.algorithm, self.k = dict(ap_areas), algorithm, k
        self.min_aps, self.max_age_seconds = min_aps, max_age_seconds
        self.max_distance, self.min_margin = max_distance, min_margin
        all_aps = {ap for observation in self.training for ap in observation.readings}
        self.aps = sorted(all_aps if selected_aps is None else all_aps.intersection(selected_aps))
        self.ap_indices = {ap: index for index, ap in enumerate(self.aps)}
        self.matrix = np.array([[x.readings.get(ap, MISSING_RSSI) for ap in self.aps] for x in self.training], dtype=float)
        self.presence = np.array([[ap in x.readings for ap in self.aps] for x in self.training], dtype=bool)
        self.labels = np.array([x.area for x in self.training])
        self._gaussian = {}
        for area in sorted(set(self.labels)):
            rows = self.matrix[self.labels == area]
            self._gaussian[str(area)] = (np.mean(rows, axis=0), np.maximum(np.var(rows, axis=0), 16.0))

    def predict(self, observation: Observation, now: datetime | None = None) -> Estimate:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        age = (now - observation.timestamp).total_seconds()
        if age < -5:
            return Estimate(reason="future_measurement")
        if age > self.max_age_seconds:
            return Estimate(reason="stale")
        if self.source is not None and observation.source != self.source:
            return Estimate(reason="source_mismatch")
        if self.algorithm == "connected_ap":
            area = self.ap_areas.get(observation.connected_ap or "")
            if area is None:
                return Estimate(reason="unmapped_ap")
            return Estimate(area=area, reason="ok", scores={area: 1.0})
        if not observation.readings:
            return Estimate(reason="insufficient_data")
        known = {ap: value for ap, value in observation.readings.items() if ap in self.aps}
        if not known:
            return Estimate(reason="unmapped_ap")
        if len(known) < self.min_aps:
            return Estimate(reason="insufficient_data")
        if self.algorithm == "strongest_ap":
            strongest = max(observation.readings, key=observation.readings.get)
            area = self.ap_areas.get(strongest)
            if area is None:
                return Estimate(reason="unmapped_ap")
            return Estimate(area=area, reason="ok", scores={area: 1.0})
        if not self.training or not self.aps:
            return Estimate(reason="no_training_data")
        query = np.array([known.get(ap, MISSING_RSSI) for ap in self.aps])
        distances = np.sqrt(np.mean((self.matrix - query) ** 2, axis=1))
        # Never match samples that share fewer than min_aps actual observations.
        query_indices = [self.ap_indices[ap] for ap in known]
        overlap = np.sum(self.presence[:, query_indices], axis=1)
        distances[overlap < self.min_aps] = np.inf
        nearest = float(np.min(distances))
        if not math.isfinite(nearest):
            return Estimate(reason="insufficient_overlap")
        if nearest > self.max_distance:
            return Estimate(reason="unfamiliar_pattern", distance=nearest)
        if self.algorithm == "1nn":
            tied = sorted(set(self.labels[np.isclose(distances, nearest, rtol=0, atol=1e-9)]))
            if len(tied) > 1:
                return Estimate(reason="ambiguous", distance=nearest,
                                scores={str(area): 1/len(tied) for area in tied})
        if self.algorithm == "gaussian":
            # Gaussian naive Bayes: one independent RSSI distribution per AP.
            log_support = {}
            for area, (mean, variance) in self._gaussian.items():
                log_support[area] = float(-.5 * np.sum(np.log(2*np.pi*variance) + (query-mean)**2/variance))
            highest = max(log_support.values())
            votes = {area: float(np.exp(max(value-highest, -700))) for area, value in log_support.items()}
        elif self.algorithm == "rank":
            # Pairwise ordering is insensitive to a uniform device RSSI offset.
            # A disagreement contributes 1, an equal reading contributes .5.
            pairs = [(a, b) for a in known for b in known if a < b]
            rank_distances = []
            for index, sample in enumerate(self.training):
                comparable = [(a, b) for a, b in pairs if a in sample.readings and b in sample.readings]
                if not comparable or not math.isfinite(float(distances[index])):
                    rank_distances.append(float("inf"))
                    continue
                disagreement = [abs(np.sign(known[a]-known[b])-np.sign(sample.readings[a]-sample.readings[b]))/2 for a,b in comparable]
                # Small RMS term deterministically resolves indistinguishable ranks.
                rank_distances.append(float(np.mean(disagreement)) + float(distances[index]) / 1000)
            order = np.argsort(rank_distances)[:self.k]
            votes = defaultdict(float)
            for index in order:
                if math.isfinite(rank_distances[index]):
                    votes[str(self.labels[index])] += 1 / (rank_distances[index] + .05)
        else:
            count = 1 if self.algorithm == "1nn" else self.k
            order = np.argsort(distances, kind="stable")[:count]
            votes = defaultdict(float)
            for index in order:
                distance = float(distances[index])
                if math.isfinite(distance):
                    weight = 1 / (distance + 1e-6) if self.algorithm == "weighted_knn" else 1.0
                    votes[str(self.labels[index])] += weight
        total = sum(votes.values())
        if total <= 0:
            return Estimate(reason="insufficient_overlap", distance=nearest)
        scores = {str(area): float(value / total) for area, value in votes.items()}
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        winner, first = ordered[0]
        second = ordered[1][1] if len(ordered) > 1 else 0.0
        margin = first-second
        if margin <= self.min_margin:
            return Estimate(reason="ambiguous", scores=scores, distance=nearest)
        return Estimate(area=winner, reason="ok", scores=scores, distance=nearest)
