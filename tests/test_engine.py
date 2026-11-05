from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from wifi_location.algorithms import Engine
from wifi_location.filters import Kalman1D, preprocess, robust_mean
from wifi_location.models import Observation
from wifi_location.selection import select_aps, strongest_aps
from wifi_location.simulation import generate, AP_AREAS


NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def observation(readings=None, area="east", session="s1", seconds=0, **kwargs):
    return Observation(NOW+timedelta(seconds=seconds), readings or {}, session_id=session, area=area, **kwargs)


def training():
    return [observation({"a": -40, "b": -75}, "east", f"e{i}") for i in range(5)] + [
        observation({"a": -75, "b": -40}, "west", f"w{i}") for i in range(5)]


def test_mean_median_and_robust_mean():
    observations = [observation({"a": value}, seconds=i) for i, value in enumerate([-50, -52, -100])]
    assert preprocess(observations, "mean")[-1].readings["a"] == pytest.approx(-202/3)
    assert preprocess(observations, "median")[-1].readings["a"] == -52
    assert robust_mean([-50, -50, -100]) == -50


def test_kalman_numerical_update():
    kalman = Kalman1D(q=1, r=4, initial_variance=4)
    assert kalman.update(-50) == -50
    assert kalman.update(-60) == pytest.approx(-50 + 5/9*(-10))
    assert kalman.variance == pytest.approx(20/9)
    with pytest.raises(ValueError):
        Kalman1D(r=0)


@pytest.mark.parametrize("method", ["mean", "median", "robust_mean", "ema", "kalman"])
def test_filter_causal_session_device_and_missing_reset(method):
    first = observation({"a": -40}, seconds=0)
    middle = observation({}, seconds=1)
    last = observation({"a": -80}, seconds=2)
    processed = preprocess([first, middle, last], method)
    assert processed[1].readings == {}
    assert processed[-1].readings["a"] == -80
    separate = observation({"a": -90}, session="s2", seconds=3)
    assert preprocess([first, separate], method)[-1].readings["a"] == -90
    device = observation({"a": -95}, device_id="another", seconds=3)
    assert preprocess([first, device], method)[-1].readings["a"] == -95
    future = observation({"a": -10}, seconds=100)
    assert preprocess([first, future], method)[0].readings == first.readings


@pytest.mark.parametrize("algorithm", ["1nn", "knn", "weighted_knn", "rank", "gaussian"])
def test_fingerprint_classification(algorithm):
    engine = Engine(training(), {"a": "east", "b": "west"}, algorithm=algorithm)
    estimate = engine.predict(observation({"a": -42, "b": -73}), now=NOW)
    assert estimate.area == "east"
    assert estimate.reason == "ok"
    assert sum(estimate.scores.values()) == pytest.approx(1)


def test_baselines():
    engine = Engine(training(), {"a": "east", "b": "west"}, algorithm="connected_ap")
    assert engine.predict(observation({}, connected_ap="b"), now=NOW).area == "west"
    assert engine.predict(observation({}, connected_ap="x"), now=NOW).reason == "unmapped_ap"
    engine = Engine(training(), {"a": "east", "b": "west"}, algorithm="strongest_ap")
    assert engine.predict(observation({"a": -42, "b": -73}), now=NOW).area == "east"


@pytest.mark.parametrize("algorithm", ["connected_ap", "strongest_ap", "knn"])
def test_measurement_expires_at_exactly_three_minutes(algorithm):
    model = Engine(training(), {"a": "east", "b": "west"}, algorithm=algorithm)
    sample = observation({"a": -40, "b": -75}, connected_ap="a")
    assert model.predict(sample, now=NOW + timedelta(seconds=179.999)).area == "east"
    assert model.predict(sample, now=NOW + timedelta(seconds=180)).reason == "stale"


def test_strongest_ap_works_from_mapping_without_fingerprints():
    mapping = {"new-a": "east", "new-b": "west"}
    sample = observation({"new-a": -40, "new-b": -70})
    # Empty training and training predating the new mapped APs both work.
    for fingerprints in [[], training()]:
        engine = Engine(fingerprints, mapping, algorithm="strongest_ap")
        assert engine.predict(sample, now=NOW).area == "east"
    engine = Engine([], mapping, algorithm="strongest_ap")
    assert engine.predict(observation({"new-a": -40}), now=NOW).reason == "insufficient_data"
    assert engine.predict(observation({"unmapped": -40}), now=NOW).reason == "unmapped_ap"


def test_strongest_ap_respects_selection_and_does_not_hide_unmapped_strong_signal():
    mapping = {"a": "east", "b": "west", "c": "north"}
    sample = observation({"a": -40, "b": -60, "c": -30, "unmapped": -20})
    unselected = Engine([], mapping, algorithm="strongest_ap")
    assert unselected.predict(sample, now=NOW).reason == "unmapped_ap"
    selected = Engine([], mapping, algorithm="strongest_ap", selected_aps=["a", "b"])
    assert selected.predict(sample, now=NOW).area == "east"
    insufficient = Engine([], mapping, algorithm="strongest_ap", selected_aps=["a"])
    assert insufficient.predict(sample, now=NOW).reason == "insufficient_data"


def test_gaussian_excludes_areas_without_enough_shared_observed_aps():
    data = [observation({"a": -80, "b": -80}, "east", "e"),
            observation({"c": -100, "d": -100}, "west", "w")]
    sample = observation({"a": -100, "b": -100})
    engine = Engine(data, {}, algorithm="gaussian")
    result = engine.predict(sample, now=NOW)
    assert result.area == "east"
    assert "west" not in result.scores
    # One shared AP in each row cannot jointly satisfy a two-AP requirement.
    split_data = [observation({"a": -100, "c": -100}, "west", "w1"),
                  observation({"b": -100, "d": -100}, "west", "w2")]
    result = Engine([data[0], *split_data], {}, algorithm="gaussian").predict(sample, now=NOW)
    assert result.area == "east"
    assert "west" not in result.scores


def test_gaussian_returns_unknown_if_no_area_has_sufficient_shared_aps():
    data = [observation({"a": -80, "c": -80}, "east", "e"),
            observation({"b": -100, "d": -100}, "west", "w")]
    result = Engine(data, {}, algorithm="gaussian").predict(observation({"a": -90, "b": -90}), now=NOW)
    assert result.area == "unknown"
    assert result.reason == "insufficient_overlap"


def test_unknown_gates():
    engine = Engine(training(), {"a": "east", "b": "west"})
    assert engine.predict(observation({"a": -40}), now=NOW).area == "unknown"
    assert engine.predict(observation({"x": -40}), now=NOW).reason == "unmapped_ap"
    assert engine.predict(observation({"a": -110, "b": -110}), now=NOW).reason == "unfamiliar_pattern"
    assert engine.predict(observation({"a": -40, "b": -75}), now=NOW+timedelta(seconds=181)).reason == "stale"
    assert engine.predict(observation({"a": -40, "b": -75}, seconds=6), now=NOW).reason == "future_measurement"
    assert engine.predict(observation({"a": -40, "b": -75}, source="csv"), now=NOW).reason == "source_mismatch"


def test_ambiguity_and_partial_ap_missing():
    data = [observation({"a": -50, "b": -60, "c": -70}, "east", "e"),
            observation({"a": -60, "b": -50, "c": -70}, "west", "w")]
    engine = Engine(data, {}, k=2)
    assert engine.predict(observation({"a": -55, "b": -55}), now=NOW).reason == "ambiguous"
    engine = Engine(data, {}, algorithm="1nn")
    assert engine.predict(observation({"a": -50, "b": -60}), now=NOW).area == "east"


def test_1nn_does_not_break_exact_cross_area_ties_by_training_order():
    data = [observation({"a": -50, "b": -60}, "east", "e"),
            observation({"a": -60, "b": -50}, "west", "w")]
    for training_order in [data, list(reversed(data))]:
        engine = Engine(training_order, {}, algorithm="1nn", min_margin=0)
        result = engine.predict(observation({"a": -55, "b": -55}), now=NOW)
        assert result.area == "unknown"
        assert result.reason == "ambiguous"


def test_source_mix_rejected_and_aware_time_required():
    with pytest.raises(ValueError, match="sources"):
        Engine([*training(), replace(training()[0], source="ujindoorloc")], {})
    with pytest.raises(ValueError, match="timezone"):
        Observation(datetime(2026, 1, 1), {})


def test_simulation_reproducible_and_separate_stationary_runs():
    first = generate(seed=5, sessions=12, samples_per_area=3)
    assert first == generate(seed=5, sessions=12, samples_per_area=3)
    assert first != generate(seed=6, sessions=12, samples_per_area=3)
    assert len({x.device_id for x in first}) == 3
    assert len({x.timestamp.date() for x in first}) == 4
    for session in {x.session_id for x in first}:
        assert len({x.area for x in first if x.session_id == session}) == 1
    assert len(AP_AREAS) == 4


def test_ap_selection_training_only():
    data = training()
    assert select_aps(data, "all") == ["a", "b"]
    for method in ["strongest", "stable", "discriminative"]:
        assert len(select_aps(data, method, n=1)) == 1
    assert strongest_aps({"a": -50, "b": -40, "c": -90}, 2) == {"b": -40, "a": -50}


def test_filter_reduces_stationary_noise():
    rng = np.random.default_rng(15)
    data = [observation({"a": -60+float(rng.normal(0, 6))}, seconds=i) for i in range(150)]
    raw = [x.readings["a"] for x in data[10:]]
    filtered = [x.readings["a"] for x in preprocess(data, "kalman")[10:]]
    assert np.std(filtered) < np.std(raw)
