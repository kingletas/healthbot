#!/usr/bin/env python3

import healthbot.notifications.manager as nm
from healthbot.alerting import failing_signals

THRESHOLDS = {"active_users_alert": 700, "web_response_alert": 3.5, "app_response_alert": 800}

HEALTHY = {
    "is_checkout_up": True,
    "canary_ok": True,
    "ga_active_users": 100,
    "app_response_time": 400.0,
    "web_response_time": 2.0,
}


def _bad(message_data: dict) -> bool:
    """What the run asks: is anything about this run worth telling somebody."""
    return bool(failing_signals(message_data, THRESHOLDS))


def test_healthy_run_does_not_notify():
    assert _bad(HEALTHY) is False


def test_checkout_down_notifies():
    assert _bad({**HEALTHY, "is_checkout_up": False}) is True


def test_a_failing_canary_sweep_notifies():
    # Regression: the alert decision used to be a second chain of branches
    # with no branch for the canary sweep, so every URL could 503 while the
    # objective burned and nobody was told.
    assert _bad({**HEALTHY, "canary_ok": False}) is True


def test_each_threshold_breach_notifies():
    assert _bad({**HEALTHY, "ga_active_users": 700}) is True
    assert _bad({**HEALTHY, "app_response_time": 800.0}) is True
    assert _bad({**HEALTHY, "web_response_time": 3.5}) is True


def test_missing_signal_notifies_instead_of_crashing():
    # Regression: float(None) used to raise TypeError inside the alert
    # decision, and a missing key meant the check silently passed.
    for key in ("ga_active_users", "app_response_time", "web_response_time", "canary_ok"):
        broken = dict(HEALTHY)
        broken[key] = None
        assert _bad(broken) is True
        del broken[key]
        assert _bad(broken) is True


def test_sns_subject_is_read_from_the_right_key(monkeypatch):
    # Regression for the sns_subect typo: Subject arrived as None on every SNS
    # notification.
    sent = {}

    class FakeSns:
        def __init__(self, logger, aws_profile=None):
            pass

        def send(self, message):
            sent["message"] = message

    monkeypatch.setattr(nm, "SnsNotifier", FakeSns)
    nm.send_notifications(
        secrets={"topic_arn": "arn:aws:sns:us-east-2:1:t"},
        notifications={
            "send_sns": True,
            "sns_subject": "checkout is down",
            "sns_message": "body",
            "sns_attributes": {},
        },
    )
    assert sent["message"].subject == "checkout is down"
    assert sent["message"].body == "body"


def test_no_channels_send_without_their_secrets(monkeypatch):
    # No twilio/slack/sns secrets present: nothing should be constructed
    wanted = {"send_sms": True, "send_slack": True, "send_sns": True}
    nm.send_notifications(secrets={}, notifications=wanted)
