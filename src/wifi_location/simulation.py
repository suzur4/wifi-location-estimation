"""Reproducible synthetic stationary Wi-Fi fingerprints, never real school data.

Coordinates are arbitrary metres. Path loss follows 20*log10(distance), with
floor and partition attenuation, random noise, occasional outliers/missing
APs, device bias, and session/day drift. Sessions independently place a PC in
one area: no movement trajectories or real AP/device identifiers are created.
"""

from datetime import datetime, timedelta, timezone
import numpy as np

from .models import Observation


AREAS = ["1F-west", "1F-east", "2F-west", "2F-east", "3F-west", "3F-east"]
AP_AREAS = {"AP_A": "1F-west", "AP_B": "1F-east", "AP_C": "3F-west", "AP_D": "3F-east"}
AP_COORDS = {"AP_A": (0, 0, 0), "AP_B": (24, 0, 0), "AP_C": (0, 0, 8), "AP_D": (24, 0, 8)}


def generate(seed: int = 42, sessions: int = 12, samples_per_area: int = 16) -> list[Observation]:
    """Generate sessions * six areas * samples_per_area observations.

    Each session batch receives one day and one device; the 3-device/4-day
    cycle is deterministic. session_id identifies one stationary area run.
    """
    if sessions < 1 or samples_per_area < 1:
        raise ValueError("sessions and samples_per_area must be positive")
    rng = np.random.default_rng(seed)
    base = datetime(2026, 10, 1, 0, tzinfo=timezone.utc)
    device_offsets = [-3.0, 0.0, 4.0]
    result = []
    for session in range(sessions):
        device_index = session % 3
        day = session // 3
        drift = float(rng.normal(0, 1.8))
        for area_index, area in enumerate(AREAS):
            floor, side = divmod(area_index, 2)
            position = (side*24 + float(rng.normal(0, 1.5)), float(rng.normal(0, 1.0)), floor*4)
            mean = {}
            for ap, coords in AP_COORDS.items():
                distance = max(float(np.linalg.norm(np.array(position)-np.array(coords))), 1)
                floor_walls = abs(position[2]-coords[2]) / 4
                partition = 4 if abs(position[0]-coords[0]) > 12 else 0
                mean[ap] = -33 - 20*np.log10(distance) - 5*floor_walls - partition + device_offsets[device_index] + drift
            strongest = max(mean, key=mean.get)
            run_id = f"sim-s{session:02d}-{area}"
            for sample in range(samples_per_area):
                readings = {}
                for ap, center in mean.items():
                    if rng.random() < .08:
                        continue
                    value = center + float(rng.normal(0, 3.5))
                    if rng.random() < .045:
                        value += float(rng.normal(0, 16))
                    readings[ap] = float(np.clip(value, -110, -15))
                result.append(Observation(
                    timestamp=base + timedelta(days=day, hours=area_index, seconds=sample*3 + (session % 3)*120),
                    readings=readings, device_id=f"sim-pc-{device_index+1}", session_id=run_id,
                    area=area, connected_ap=strongest, source="simulation",
                ))
    return result
