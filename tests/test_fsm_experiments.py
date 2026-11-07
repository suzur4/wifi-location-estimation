"""Protect the comparison's denominators, separation and causal replay handling."""

from datetime import timedelta

import pytest

from wifi_location.algorithms import Engine
from wifi_location.fsm_experiments import (
    TRAIN_SEEDS, TEST_SEEDS, VALIDATION_SEEDS, inference, metrics, scenarios, segment_delay,
)
from wifi_location.simulation import AP_AREAS, generate


def test_seed_sets_are_disjoint_and_challenges_reproducible():
    assert not set(TRAIN_SEEDS) & set(VALIDATION_SEEDS + TEST_SEEDS)
    assert not set(VALIDATION_SEEDS) & set(TEST_SEEDS)
    first = list(scenarios(31))
    assert first == list(scenarios(31))
    assert first != list(scenarios(32))
    assert sum(kind == "stationary" for _, kind, _ in first) == 18
    changed = next(events for _, kind, events in first if kind == "area_change")
    assert changed[11].truth != changed[12].truth
    assert changed[11].observation.session_id == changed[12].observation.session_id
    assert changed[12].now - changed[11].now == timedelta(seconds=3)


def test_kalman_does_not_filter_duplicate_or_reverse_order_observations_twice():
    engine = Engine(generate(seed=11, sessions=1), AP_AREAS)
    events = next(events for _, kind, events in scenarios(31) if kind == "replayed")
    output = list(inference(engine, events, filtered=True))
    replayed = [row for row in output if row[0].challenge in ("duplicate", "out_of_order")]
    assert len(replayed) == 2
    for event, latest, _, _, fresh in replayed:
        assert not fresh
        assert latest.timestamp == events[11].observation.timestamp
        assert latest.readings == output[11][1].readings


def test_expired_correct_area_is_wrong_display_and_unknown_is_not_correct():
    base = {"truth": "east", "trial": "trial", "challenge": "normal", "age_seconds": 0}
    rows = [{**base, "display": "east"}, {**base, "display": "west"},
            {**base, "display": "unknown"}, {**base, "display": "east", "age_seconds": 180}]
    result = metrics(rows)
    assert result["accuracy"] == .25
    assert result["false_display_rate"] == .5
    assert result["unknown_rate"] == .25
    assert result["expired_displays"] == 1
    assert result["display_precision"] == pytest.approx(1 / 3)


def test_delay_counts_new_observations_and_reports_censored_segment():
    base = {"trial": "trial", "truth": "east", "display": "unknown", "age_seconds": 0}
    rows = [{**base, "timestamp": "2026-11-07T00:00:00+00:00", "new_observation": True},
            {**base, "timestamp": "2026-11-07T00:00:01+00:00", "new_observation": False},
            {**base, "timestamp": "2026-11-07T00:00:03+00:00", "new_observation": True, "display": "east"}]
    result = segment_delay(rows)
    assert result["observations"] == 2
    assert result["seconds"] == 3
    assert segment_delay(rows[:2])["seconds"] is None
