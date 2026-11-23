from datetime import datetime, timedelta, timezone
import hashlib
import math

import numpy as np
import pytest

from wifi_location.models import Observation
from wifi_location.simulation import AP_COORDS, AREA_POSITIONS, generate
from wifi_location.trilateration import PathLoss, Trilaterator, fit_path_loss

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
MODEL = PathLoss(p0=-35.0, n=2.2)


def clean(area, position=None):
    """Noise-free readings that follow MODEL exactly."""
    position = position or AREA_POSITIONS[area]
    readings = {ap: MODEL.p0 - 10 * MODEL.n * math.log10(max(math.dist(position, xyz), 1.0))
                for ap, xyz in AP_COORDS.items()}
    return Observation(NOW, readings, area=area)


def training():
    return [clean(area) for area in AREA_POSITIONS]


def test_fit_recovers_path_loss_from_clean_data():
    fitted = fit_path_loss(training(), AP_COORDS, AREA_POSITIONS)
    assert fitted.p0 == pytest.approx(MODEL.p0, abs=1e-6)
    assert fitted.n == pytest.approx(MODEL.n, abs=1e-6)


def test_clean_readings_give_correct_position_and_area():
    model = Trilaterator(training(), AP_COORDS, AREA_POSITIONS, grid_step=0.5)
    for area, centre in AREA_POSITIONS.items():
        point, residual = model.locate(clean(area).readings)
        assert np.allclose(point, centre, atol=0.5)
        assert residual < 0.5
        estimate = model.predict(clean(area), NOW)
        assert (estimate.area, estimate.reason) == (area, "ok")


def test_fewer_than_three_anchors_is_unknown():
    model = Trilaterator(training(), AP_COORDS, AREA_POSITIONS)
    observation = clean("1F-east")
    two = Observation(NOW, dict(list(observation.readings.items())[:2]), area="1F-east")
    estimate = model.predict(two, NOW)
    assert (estimate.area, estimate.reason) == ("unknown", "insufficient_data")


def test_inconsistent_distances_are_unknown():
    model = Trilaterator(training(), AP_COORDS, AREA_POSITIONS, max_residual=2.0)
    readings = dict(clean("1F-east").readings)
    readings["AP_A"] = -90.0  # claims to be far from AP_A while the others say close
    estimate = model.predict(Observation(NOW, readings), NOW)
    assert (estimate.area, estimate.reason) == ("unknown", "unfamiliar_pattern")


def test_stale_and_future_measurements_are_unknown():
    model = Trilaterator(training(), AP_COORDS, AREA_POSITIONS)
    old = Observation(NOW - timedelta(minutes=10), clean("1F-east").readings)
    future = Observation(NOW + timedelta(minutes=1), clean("1F-east").readings)
    assert model.predict(old, NOW).reason == "stale"
    assert model.predict(future, NOW).reason == "future_measurement"


def test_needs_three_anchors_by_design():
    with pytest.raises(ValueError):
        Trilaterator(training(), AP_COORDS, AREA_POSITIONS, min_anchors=2)


def test_same_seed_gives_same_estimates():
    data = generate(7, sessions=3, samples_per_area=2)
    first = [Trilaterator(data, AP_COORDS, AREA_POSITIONS).predict(o, o.timestamp) for o in data]
    second = [Trilaterator(data, AP_COORDS, AREA_POSITIONS).predict(o, o.timestamp) for o in data]
    assert first == second


def test_default_simulation_is_unchanged_by_environment_parameters():
    """generate(42) as it was before floor_db/partition_db/ap_offsets/shadowing_db were added.

    Which APs were heard and the labels must match exactly; RSSI values are
    compared with a tolerance because log10 can differ in the last bit
    between platforms and numerical libraries.
    """
    data = generate(42)
    layout = repr([(sorted(o.readings), o.area, o.session_id, o.device_id, o.timestamp.isoformat()) for o in data])
    assert hashlib.sha256(layout.encode()).hexdigest() == "72cebd56812ba43a06d67a2ce979d346a69376d6041f2afa15cac18607bf50f0"
    aps = ["AP_A", "AP_B", "AP_C", "AP_D"]
    matrix = np.array([[o.readings.get(ap, np.nan) for ap in aps] for o in data])
    assert np.nansum(matrix) == pytest.approx(-253256.9579129459, abs=1e-6)
    assert np.nanmean(matrix, axis=0) == pytest.approx([-59.315084409, -59.7461267811, -59.1839639699, -59.2191427285], abs=1e-8)
    assert [data[0].readings[ap] for ap in aps] == pytest.approx(
        [-47.04656888507219, -68.71330936791055, -60.63415062944183, -74.06665670228962], abs=1e-9)


def test_environment_change_only_shifts_the_changed_ap():
    base, changed = generate(42, sessions=2), generate(42, sessions=2, ap_offsets={"AP_B": -8.0})
    for before, after in zip(base, changed):
        assert before.readings.keys() == after.readings.keys()
        for ap, value in before.readings.items():
            if ap != "AP_B":
                assert after.readings[ap] == value
