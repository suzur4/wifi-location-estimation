"""Offline collectors sharing one protocol. No network collection is enabled.

The long CSV format is intentionally readable by spreadsheet software. A row
with blank ap_id/rssi preserves a measurement where no AP was visible.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Protocol

from .models import Observation


FIELDS = ["timestamp", "area", "ap_id", "rssi", "source", "device_id", "session_id", "connected_ap"]


class DataSource(Protocol):
    def load(self) -> list[Observation]:
        """Return source-labelled measurements without publishing identity data."""
        ...


@dataclass
class CSVSource:
    path: str | Path

    def load(self) -> list[Observation]:
        return read_csv(self.path)


@dataclass
class SimulationSource:
    seed: int = 42
    sessions: int = 12
    samples_per_area: int = 16

    def load(self) -> list[Observation]:
        from .simulation import generate
        return generate(self.seed, self.sessions, self.samples_per_area)


@dataclass
class UJISource:
    path: str | Path

    def load(self) -> list[Observation]:
        return load_uji(self.path)


def write_csv(path: str | Path, observations: list[Observation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for observation in observations:
            common = dict(timestamp=observation.timestamp.isoformat(), area=observation.area or "",
                          source=observation.source, device_id=observation.device_id,
                          session_id=observation.session_id, connected_ap=observation.connected_ap or "")
            for ap, rssi in sorted(observation.readings.items()):
                writer.writerow({**common, "ap_id": ap, "rssi": rssi})
            if not observation.readings:
                writer.writerow({**common, "ap_id": "", "rssi": ""})


def read_csv(path: str | Path) -> list[Observation]:
    grouped: dict[tuple, dict] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = set(FIELDS)-{"connected_ap"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"CSV missing required columns: {sorted(required-set(reader.fieldnames or []))}")
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(row.get(field) is None for field in required):
                    raise ValueError("incorrect number of columns")
                timestamp = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
                area = row["area"].strip() or None
                source, device_id, session_id = (row[field].strip() for field in ("source", "device_id", "session_id"))
                connected_ap = (row.get("connected_ap") or "").strip() or None
                key = (timestamp, device_id, session_id, source)
                if key in grouped:
                    existing = grouped[key]
                    if existing["area"] != area or existing["connected_ap"] != connected_ap:
                        raise ValueError("conflicting metadata within one measurement")
                else:
                    grouped[key] = dict(timestamp=timestamp, readings={}, area=area, source=source,
                                        device_id=device_id, session_id=session_id, connected_ap=connected_ap)
                ap, raw_rssi = row["ap_id"].strip(), row["rssi"].strip()
                if bool(ap) != bool(raw_rssi):
                    raise ValueError("ap_id and rssi must both be present or both blank")
                if ap:
                    if ap in grouped[key]["readings"]:
                        raise ValueError(f"duplicate AP {ap} in one measurement")
                    grouped[key]["readings"][ap] = float(raw_rssi)
                Observation(**grouped[key])  # validate every row, including timestamps and ranges
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"CSV row {number}: {exc}") from exc
    return [Observation(**data) for data in grouped.values()]


def load_uji(path: str | Path) -> list[Observation]:
    """Load original UJIIndoorLoc training/validation CSV without mixing sources.

    100 means unobserved, never a +100 dBm signal. Targets are building/floor,
    not school rooms. Every row is independent: published rows do not provide
    a trustworthy stationary session sequence for causal smoothing.
    """
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        aps = sorted([name for name in fields if re.fullmatch(r"WAP\d{3}", name)])
        if not aps or not {"BUILDINGID", "FLOOR", "PHONEID", "TIMESTAMP"}.issubset(fields):
            raise ValueError("UJI CSV requires WAPnnn, BUILDINGID, FLOOR, PHONEID, TIMESTAMP columns")
        for number, row in enumerate(reader, 2):
            try:
                readings = {}
                for ap in aps:
                    value = float(row[ap])
                    if value != 100:
                        readings[ap] = value
                building, floor = int(row["BUILDINGID"]), int(row["FLOOR"])
                result.append(Observation(
                    timestamp=datetime.fromtimestamp(float(row["TIMESTAMP"]), timezone.utc),
                    readings=readings, device_id=f"uji-phone-{int(row['PHONEID'])}",
                    session_id=f"uji-{Path(path).name}-row-{number}",
                    area=f"building-{building}/floor-{floor}", source="ujindoorloc",
                ))
            except (ValueError, TypeError, OverflowError, OSError) as exc:
                raise ValueError(f"UJI row {number}: {exc}") from exc
    return result
