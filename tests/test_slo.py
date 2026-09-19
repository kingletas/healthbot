#!/usr/bin/env python3

from healthbot.slo import evaluate_run, load_slos

HEALTHY = {
    "is_checkout_up": True,
    "canary_ok": True,
    "web_response_time": 2.0,
    "app_response_time": 400.0,
}


def test_the_five_slos_are_defined_with_targets():
    names = {slo["name"] for slo in load_slos()}
    assert names == {
        "checkout_availability",
        "canary_availability",
        "web_latency",
        "app_latency",
        "monitor_availability",
    }
    assert all(0 < slo["target"] <= 1 for slo in load_slos())
    assert all(slo["description"] for slo in load_slos())


def test_a_healthy_run_is_good_everywhere():
    assert all(good for _, good in evaluate_run(HEALTHY, run_completed=True))


def test_threshold_breaches_are_bad():
    verdicts = dict(evaluate_run({**HEALTHY, "web_response_time": 3.5}, run_completed=True))
    assert verdicts["web_latency"] is False
    verdicts = dict(evaluate_run({**HEALTHY, "app_response_time": 800}, run_completed=True))
    assert verdicts["app_latency"] is False


def test_a_missing_signal_is_bad_not_good():
    broken = dict(HEALTHY)
    del broken["canary_ok"]
    verdicts = dict(evaluate_run(broken, run_completed=True))
    assert verdicts["canary_availability"] is False
    assert verdicts["checkout_availability"] is True


def test_run_completed_drives_the_monitor_sli():
    assert dict(evaluate_run(HEALTHY, run_completed=False))["monitor_availability"] is False
