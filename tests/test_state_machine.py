from datetime import datetime, timedelta, timezone

import pytest

from wifi_location.models import Estimate
from wifi_location.state_machine import FsmConfig, FsmState, Phase, expire, observe


START = datetime(2026, 11, 7, tzinfo=timezone.utc)
CONFIG = FsmConfig(confirmations=2)


def accepted(area="east", scores=None):
    return Estimate(area, "ok", {area: 1.0} if scores is None else scores)


def step(state, seconds, estimate=None, *, age=0, aps=3, config=CONFIG):
    timestamp = START + timedelta(seconds=seconds)
    return observe(state, estimate or accepted(), observed_at=timestamp,
                   now=timestamp + timedelta(seconds=age), observed_aps=aps, config=config)


def test_only_confirmed_area_is_displayed_and_changed_candidate_hides_old_area():
    first = step(FsmState(), 0)
    assert (first.phase, first.confirmations, first.display_area) == (Phase.CANDIDATE, 1, None)
    assert first.reason == "fsm_pending"
    confirmed = step(first, 1)
    assert (confirmed.phase, confirmed.confirmations, confirmed.display_area) == (Phase.CONFIRMED, 2, "east")
    assert step(confirmed, 2).confirmations == 2
    changed = step(confirmed, 2, accepted("west"))
    assert (changed.phase, changed.confirmations, changed.display_area) == (Phase.CANDIDATE, 1, None)
    assert step(changed, 3, accepted("west")).display_area == "west"


@pytest.mark.parametrize("bad_estimate,aps,reason", [
    (Estimate(reason="ambiguous"), 3, "ambiguous"),
    (accepted(), 1, "fsm_insufficient_aps"),
    (accepted(scores={"east": .5, "west": .5}), 3, "fsm_low_margin"),
])
def test_rejected_observation_clears_previous_confirmation(bad_estimate, aps, reason):
    confirmed = step(step(FsmState(), 0), 1)
    rejected = step(confirmed, 2, bad_estimate, aps=aps)
    assert (rejected.phase, rejected.confirmations, rejected.display_area) == (Phase.UNKNOWN, 0, None)
    assert rejected.reason == reason
    assert step(rejected, 3).confirmations == 1


@pytest.mark.parametrize("count", [float("nan"), float("inf"), 2.0, True, -1])
def test_invalid_observed_ap_count_cannot_confirm(count):
    state = step(FsmState(), 0, aps=count, config=FsmConfig(confirmations=1, min_aps=1))
    assert state.phase == Phase.UNKNOWN
    assert state.reason == "fsm_insufficient_aps"


@pytest.mark.parametrize("scores", [
    {}, {"east": float("nan")}, {"east": float("inf")}, {"east": True}, {"east": "1"},
    {"east": .8}, {"east": 1.1, "west": -.1}, {"east": .4, "west": .6}, {"west": 1.0},
])
def test_invalid_or_inconsistent_model_scores_cannot_confirm(scores):
    state = step(FsmState(), 0, accepted(scores=scores), config=FsmConfig(confirmations=1))
    assert state.phase == Phase.UNKNOWN
    assert state.reason == "fsm_low_margin"


def test_confirmation_count_and_minimum_margin_are_configurable():
    config = FsmConfig(confirmations=1, min_margin=.25)
    assert step(FsmState(), 0, accepted(scores={"east": .6, "west": .4}), config=config).reason == "fsm_low_margin"
    assert step(FsmState(), 1, accepted(scores={"east": .625, "west": .375}), config=config).display_area == "east"


def test_repeated_ticks_duplicates_old_and_future_events_do_not_count():
    first = step(FsmState(), 1)
    for second in (1, 2, 3):
        assert expire(first, now=START + timedelta(seconds=second), config=CONFIG) is first
    same_in_tokyo = first.observed_at.astimezone(timezone(timedelta(hours=9)))
    assert observe(first, accepted("west"), observed_at=same_in_tokyo, now=START,
                   observed_aps=3, config=CONFIG) is first
    assert step(first, 0, age=2) is first
    assert step(first, 8, age=-6) is first
    assert step(first, 2).phase == Phase.CONFIRMED


def test_ttl_boundary_and_fresh_evidence_after_a_gap_even_without_a_tick():
    config = FsmConfig(confirmations=2, max_age_seconds=10)
    confirmed = step(step(FsmState(), 0, config=config), 1, config=config)
    assert expire(confirmed, now=START + timedelta(seconds=10, milliseconds=999), config=config).display_area == "east"
    expired = expire(confirmed, now=START + timedelta(seconds=11), config=config)
    assert (expired.phase, expired.area, expired.confirmations, expired.reason) == (Phase.STALE, None, 0, "stale")
    assert step(confirmed, 11, config=config).phase == Phase.CANDIDATE
    assert step(expired, 11, config=config).confirmations == 1
    assert step(FsmState(), 0, age=10, config=config).phase == Phase.STALE
    assert expire(expired, now=START, config=config) is expired


def test_server_clock_rollback_hides_a_measurement_now_too_far_in_the_future():
    confirmed = step(step(FsmState(), 0), 1)
    invalid = expire(confirmed, now=START - timedelta(seconds=5), config=CONFIG)
    assert (invalid.phase, invalid.display_area, invalid.reason) == (Phase.UNKNOWN, None, "future_measurement")
    assert invalid.observed_at == confirmed.observed_at
    assert step(invalid, 2).phase == Phase.CANDIDATE


@pytest.mark.parametrize("values", [
    {"confirmations": 0}, {"confirmations": True}, {"min_aps": 0}, {"max_age_seconds": float("inf")},
    {"max_age_seconds": 0}, {"min_margin": float("nan")}, {"min_margin": -1},
])
def test_invalid_policy_configuration_is_rejected(values):
    with pytest.raises(ValueError):
        FsmConfig(**values)
