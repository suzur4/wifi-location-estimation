"""Tests for evaluation accounting and independent, reproducible holdouts."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from wifi_location.experiments import evaluate, split_data
from wifi_location.filters import preprocess
from wifi_location.models import Estimate, Observation
from wifi_location.simulation import generate


def test_session_batch_split_keeps_all_areas_together_and_is_reproducible():
    data = generate(seed=42, sessions=12, samples_per_area=2)
    parts = split_data(data, mode="session", seed=7)
    assert parts == split_data(data, mode="session", seed=7)
    assert parts != split_data(data, mode="session", seed=8)
    groups = [{o.session_id.split("-")[1] for o in part} for part in parts]
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert sum(map(len, parts)) == len(data)
    for part in parts:
        for batch in {o.session_id.split("-")[1] for o in part}:
            assert len({o.area for o in part if o.session_id.split("-")[1] == batch}) == 6


@pytest.mark.parametrize("mode,key", [("date", lambda o: o.timestamp.date()), ("device", lambda o: o.device_id)])
def test_date_and_device_holdout_groups_do_not_overlap(mode, key):
    data = generate(sessions=12, samples_per_area=2)
    parts = split_data(data, mode=mode)
    groups = [{key(o) for o in part} for part in parts]
    assert all(groups)
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert sum(map(len, parts)) == len(data)
    if mode == "date":
        assert max(groups[0]) < min(groups[1]) < min(groups[2])


@pytest.mark.parametrize("mode", ["session", "date", "device"])
def test_not_enough_groups_is_explained(mode):
    with pytest.raises(ValueError, match="groups"):
        split_data(generate(sessions=1, samples_per_area=1), mode=mode)


@pytest.mark.parametrize("method", ["mean", "median", "ema", "kalman"])
def test_filtering_evaluation_splits_cannot_learn_future_samples(method):
    data = generate(sessions=12, samples_per_area=3)
    train, validation, test = split_data(data)
    before = preprocess(train, method)
    altered_test = [replace(o, readings={ap: -15 for ap in o.readings}) for o in test]
    preprocess(altered_test, method)
    preprocess(validation, method)
    assert preprocess(train, method) == before
    session = [o for o in train if o.session_id == train[0].session_id]
    earlier = preprocess(session[:-1], method)
    assert preprocess(session, method)[:-1] == earlier


class FixedPredictions:
    def __init__(self, predictions):
        self.predictions = iter(predictions)

    def predict(self, observation, now):
        # Evaluation must use each sample's timestamp, rather than wall clock.
        assert now == observation.timestamp
        return next(self.predictions)


def labelled(areas):
    return [Observation(datetime(2026, 11, 4, tzinfo=timezone.utc), {}, area=area) for area in areas]


def test_metrics_use_all_sample_denominators_and_display_precision():
    model = FixedPredictions([Estimate("east", "ok"), Estimate("east", "ok"), Estimate(reason="stale"), Estimate("west", "ok")])
    metrics, predictions = evaluate(model, labelled(["east", "west", "east", "west"]))
    assert len(predictions) == metrics["count"] == 4
    assert metrics["accuracy"] == .5
    assert metrics["false_display_rate"] == .25
    assert metrics["unknown_rate"] == .25
    assert metrics["precision"] == pytest.approx(2/3)
    assert metrics["accuracy"]+metrics["false_display_rate"]+metrics["unknown_rate"] == 1
    assert metrics["reasons"] == {"ok": 3, "stale": 1}
    assert metrics["latency_ms"] >= 0


def test_all_unknown_precision_is_undefined():
    metrics, _ = evaluate(FixedPredictions([Estimate(), Estimate()]), labelled(["east", "west"]))
    assert metrics["accuracy"] == 0
    assert metrics["false_display_rate"] == 0
    assert metrics["unknown_rate"] == 1
    assert metrics["precision"] is None


def test_empty_evaluation_rejected():
    with pytest.raises(ValueError, match="nonempty"):
        evaluate(FixedPredictions([]), [])
