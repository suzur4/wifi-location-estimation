from datetime import datetime, timezone
import math

import numpy as np
import pytest

from wifi_location.hybrid import Agreement, ModelFingerprint, fit_multiwall
from wifi_location.models import Estimate, Observation
from wifi_location.simulation import AP_COORDS, AREA_POSITIONS

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
P0, N, FLOOR_DB = -34.0, 2.0, 6.0


def clean(area, shift=0.0, aps=None):
    """Noise-free readings from the multi-wall model."""
    position = AREA_POSITIONS[area]
    readings = {}
    for ap, xyz in AP_COORDS.items():
        if aps is None or ap in aps:
            floors = round(abs(position[2] - xyz[2]) / 4)
            readings[ap] = P0 - 10 * N * math.log10(max(math.dist(position, xyz), 1.0)) - FLOOR_DB * floors + shift
    return Observation(NOW, readings, area=area)


def training():
    return [clean(area) for area in AREA_POSITIONS]


def test_fit_recovers_distance_and_floor_terms():
    p0, n, floor_db = fit_multiwall(training(), AP_COORDS, AREA_POSITIONS, 4.0)
    assert (p0, n, floor_db) == pytest.approx((P0, N, FLOOR_DB), abs=1e-6)


def test_clean_readings_give_correct_area():
    model = ModelFingerprint(training(), AP_COORDS, AREA_POSITIONS)
    for area in AREA_POSITIONS:
        estimate = model.predict(clean(area), NOW)
        assert (estimate.area, estimate.reason) == (area, "ok")


def test_correction_moves_from_prior_to_measured_mean():
    # One area measures 10 dB weaker than the model on every AP, many times.
    data = training() + [clean("2F-east", shift=-10.0) for _ in range(200)]
    prior_heavy = ModelFingerprint(data, AP_COORDS, AREA_POSITIONS, shrink=1e9)
    data_heavy = ModelFingerprint(data, AP_COORDS, AREA_POSITIONS, shrink=0)
    row = prior_heavy.areas.index("2F-east")
    measured = np.mean([[o.readings[ap] for ap in data_heavy.aps] for o in data if o.area == "2F-east"], axis=0)
    assert np.allclose(data_heavy.expected[row], measured)
    assert not np.allclose(prior_heavy.expected[row], measured)


def test_offset_free_ignores_a_uniform_device_shift():
    strict = ModelFingerprint(training(), AP_COORDS, AREA_POSITIONS, max_distance=3.0)
    free = ModelFingerprint(training(), AP_COORDS, AREA_POSITIONS, max_distance=3.0, offset_free=True)
    shifted = clean("3F-west", shift=8.0)
    assert strict.predict(shifted, NOW).reason == "unfamiliar_pattern"
    assert free.predict(shifted, NOW).area == "3F-west"


def test_too_few_aps_is_unknown():
    model = ModelFingerprint(training(), AP_COORDS, AREA_POSITIONS, min_aps=2)
    estimate = model.predict(clean("1F-west", aps={"AP_A"}), NOW)
    assert (estimate.area, estimate.reason) == ("unknown", "insufficient_data")


class Fixed:
    def __init__(self, estimate):
        self.estimate = estimate

    def predict(self, observation, now=None):
        return self.estimate


def test_agreement_shows_only_shared_answers():
    observation = clean("1F-west")
    east, west = Estimate(area="1F-east", reason="ok"), Estimate(area="1F-west", reason="ok")
    assert Agreement(Fixed(west), Fixed(west)).predict(observation, NOW).area == "1F-west"
    assert Agreement(Fixed(west), Fixed(east)).predict(observation, NOW).reason == "ambiguous"
    stale = Agreement(Fixed(west), Fixed(Estimate(reason="stale"))).predict(observation, NOW)
    assert (stale.area, stale.reason) == ("unknown", "stale")
    with pytest.raises(ValueError):
        Agreement(Fixed(west))
