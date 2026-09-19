#!/usr/bin/env python3

"""
The alert gate: when a standing alert is allowed to speak again.

Suppression is the dangerous half of alerting, so the cases that matter most
here are the ones where it must *not* suppress: an unreadable state store, a
condition that changed, and a recovery that has not held.
"""

# Third party imports
import pytest

# Local imports
from healthbot.alerting import BACKOFF_MINUTES, RECOVERY_RUNS, AlertGate, failing_signals

THRESHOLDS = {"active_users_alert": 700, "web_response_alert": 3.5, "app_response_alert": 800}

HEALTHY = {
    "is_checkout_up": True,
    "canary_ok": True,
    "ga_active_users": 100,
    "app_response_time": 400.0,
    "web_response_time": 2.0,
}


class FakeCache:
    """An in-memory stand-in. `broken` makes every operation fail like Redis."""

    def __init__(self, broken: bool = False):
        self.store = {}
        self.broken = broken

    def get(self, key):
        return None if self.broken else self.store.get(key)

    def set(self, key, value, duration: int = 0):
        if not self.broken:
            self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


def gate(cache, minutes: float = 0.0) -> AlertGate:
    return AlertGate(cache=cache, now=minutes * 60)


# --------------------------------------------------------------------------
# What counts as failing
# --------------------------------------------------------------------------


def test_a_healthy_run_has_no_failing_signals():
    assert failing_signals(HEALTHY, THRESHOLDS) == ()


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"is_checkout_up": False}, ("is_checkout_up",)),
        ({"canary_ok": False}, ("canary_ok",)),
        ({"ga_active_users": 900}, ("ga_active_users",)),
        ({"app_response_time": 900.0}, ("app_response_time",)),
        ({"web_response_time": 4.0}, ("web_response_time",)),
        ({"ga_active_users": None}, ("ga_active_users:uncollected",)),
    ],
)
def test_each_signal_is_named_on_its_own(override, expected):
    assert failing_signals({**HEALTHY, **override}, THRESHOLDS) == expected


def test_an_uncollected_signal_is_a_different_condition_from_a_bad_one():
    # A New Relic outage and a genuinely slow site are not the same incident,
    # so neither may suppress the other's first alert.
    uncollected = failing_signals({**HEALTHY, "app_response_time": None}, THRESHOLDS)
    slow = failing_signals({**HEALTHY, "app_response_time": 900.0}, THRESHOLDS)

    assert uncollected != slow


def test_the_signal_order_is_stable():
    both = failing_signals({**HEALTHY, "is_checkout_up": False, "canary_ok": False}, THRESHOLDS)

    assert both == ("canary_ok", "is_checkout_up")


# --------------------------------------------------------------------------
# When it speaks
# --------------------------------------------------------------------------


def test_a_healthy_run_says_nothing():
    cache = FakeCache()

    assert gate(cache).should_notify(()) is False


def test_the_first_bad_run_always_speaks():
    cache = FakeCache()

    assert gate(cache).should_notify(("is_checkout_up",)) is True


def test_the_next_run_is_suppressed():
    cache = FakeCache()
    gate(cache, minutes=0).should_notify(("is_checkout_up",))

    # Five minutes later, the timer's own interval, which is too soon.
    assert gate(cache, minutes=5).should_notify(("is_checkout_up",)) is False


def test_repeats_back_off_along_the_declared_curve():
    cache = FakeCache()
    clock = 0.0
    gate(cache, minutes=clock).should_notify(("is_checkout_up",))

    spoken_at = []
    # Walk five minutes at a time, the way the timer does, for four hours.
    for _ in range(48):
        clock += 5
        if gate(cache, minutes=clock).should_notify(("is_checkout_up",)):
            spoken_at.append(clock)

    # 15, 30 then hourly: six messages in four hours, not forty-nine.
    assert spoken_at == [15.0, 45.0, 105.0, 165.0, 225.0]
    assert BACKOFF_MINUTES[-1] == 60


def test_a_changed_condition_always_speaks_immediately():
    cache = FakeCache()
    gate(cache, minutes=0).should_notify(("ga_active_users",))

    # One minute later, well inside the backoff, but checkout has now gone
    # down too, and that is new information.
    assert gate(cache, minutes=1).should_notify(("ga_active_users", "is_checkout_up")) is True


# --------------------------------------------------------------------------
# Recovery, and the failure modes that make suppression safe
# --------------------------------------------------------------------------


def test_recovery_has_to_hold_before_it_counts():
    cache = FakeCache()
    gate(cache, minutes=0).should_notify(("web_response_time",))

    # A threshold sitting on its limit flaps. One clean run must not reset the
    # backoff, or every re-entry reads as a fresh incident and it never engages.
    gate(cache, minutes=5).should_notify(())
    assert gate(cache, minutes=10).should_notify(("web_response_time",)) is False


def test_two_clean_runs_clear_it_and_the_next_failure_is_new():
    cache = FakeCache()
    gate(cache, minutes=0).should_notify(("web_response_time",))

    for run in range(RECOVERY_RUNS):
        gate(cache, minutes=5 * (run + 1)).should_notify(())

    assert gate(cache, minutes=20).should_notify(("web_response_time",)) is True


def test_a_bad_run_resets_the_recovery_count():
    # Bad, clean, bad, clean is one clean run in a row and not two, so the
    # condition is still armed rather than cleared.
    cache = FakeCache()
    gate(cache, minutes=0).should_notify(("canary_ok",))
    gate(cache, minutes=5).should_notify(())
    gate(cache, minutes=10).should_notify(("canary_ok",))
    gate(cache, minutes=15).should_notify(())

    state = gate(cache, minutes=15).read_state()
    assert state["condition"] == "canary_ok"
    assert state["clean_runs"] == 1


def test_an_unreadable_state_store_never_suppresses():
    # The whole reason this is safe to add. A suppressor that cannot remember
    # must send: the failure has to be a duplicate message, not a silent outage.
    cache = FakeCache(broken=True)

    for minute in (0, 5, 10, 15):
        assert gate(cache, minutes=minute).should_notify(("is_checkout_up",)) is True
