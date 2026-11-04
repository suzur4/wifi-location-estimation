"""AP choices fitted only on training data, except per-query signal strength."""

from collections import defaultdict
import numpy as np

from .models import Observation


def select_aps(training: list[Observation], method: str = "all", n: int = 4) -> list[str]:
    """Return AP IDs using all/strongest/stable/discriminative training scores.

    Discriminative score is between-area variance / within-area variance.
    Stable score uses within-area variance to avoid rejecting useful spatial
    differences. APs seen in fewer than two labelled areas rank last.
    """
    if n < 1:
        raise ValueError("n must be positive")
    grouped = defaultdict(lambda: defaultdict(list))
    for observation in training:
        if observation.area:
            for ap, rssi in observation.readings.items():
                grouped[ap][observation.area].append(rssi)
    if method == "all":
        return sorted(grouped)
    if method not in {"strongest", "stable", "discriminative"}:
        raise ValueError(f"unknown AP selection: {method}")
    scores = {}
    for ap, by_area in grouped.items():
        values = [x for area_values in by_area.values() for x in area_values]
        within = float(np.mean([np.var(x) for x in by_area.values()]))
        between = float(np.var([np.mean(x) for x in by_area.values()]))
        if method == "strongest":
            score = float(np.mean(values))
        elif len(by_area) < 2:
            score = -float("inf")
        elif method == "stable":
            score = -within
        else:
            score = between / max(within, 1.0)
        scores[ap] = score
    return sorted(scores, key=lambda ap: (-scores[ap], ap))[:n]


def strongest_aps(readings: dict[str, float], n: int) -> dict[str, float]:
    """Select strongest N APs independently for this observation."""
    if n < 1:
        raise ValueError("n must be positive")
    return dict(sorted(readings.items(), key=lambda item: (-item[1], item[0]))[:n])
