"""Internal measurement models. These must never be serialized as student profiles."""

from dataclasses import dataclass, field
from datetime import datetime
import math


@dataclass(frozen=True)
class Observation:
    timestamp: datetime
    readings: dict[str, float]
    device_id: str = "demo"
    session_id: str = "demo"
    area: str | None = None
    connected_ap: str | None = None
    source: str = "simulation"

    def __post_init__(self):
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        if not self.device_id.strip() or not self.session_id.strip() or not self.source.strip():
            raise ValueError("device_id, session_id and source must be nonempty")
        for ap, rssi in self.readings.items():
            if not ap or not math.isfinite(rssi) or not -120 <= rssi <= 0:
                raise ValueError("AP identifiers must be nonempty and RSSI finite in [-120, 0] dBm")


@dataclass(frozen=True)
class Estimate:
    area: str = "unknown"
    reason: str = "insufficient_data"
    scores: dict[str, float] = field(default_factory=dict)
    distance: float | None = None
