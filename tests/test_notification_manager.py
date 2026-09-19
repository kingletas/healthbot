#!/usr/bin/env python3

import healthbot.notifications.manager as nm

THRESHOLDS = {"active_users_alert": 700, "web_response_alert": 3.5, "app_response_alert": 800}

HEALTHY = {
    "is_checkout_up": True,
    "ga_active_users": 100,
    "app_response_time": 400.0,
    "web_response_time": 2.0,
}


def _patch_thresholds(monkeypatch):
    monkeypatch.setattr(nm, "alert_thresholds", lambda: THRESHOLDS)


def test_healthy_run_does_not_notify(monkeypatch):
    _patch_thresholds(monkeypatch)
    assert nm.can_notify(HEALTHY) is False


def test_checkout_down_notifies(monkeypatch):
    _patch_thresholds(monkeypatch)
    assert nm.can_notify({**HEALTHY, "is_checkout_up": False}) is True


def test_each_threshold_breach_notifies(monkeypatch):
    _patch_thresholds(monkeypatch)
    assert nm.can_notify({**HEALTHY, "ga_active_users": 700}) is True
    assert nm.can_notify({**HEALTHY, "app_response_time": 800.0}) is True
    assert nm.can_notify({**HEALTHY, "web_response_time": 3.5}) is True


def test_missing_signal_notifies_instead_of_crashing(monkeypatch):
    # Regression: float(None) used to raise TypeError inside the alert
    # function itself, and a missing key meant the check silently passed.
    _patch_thresholds(monkeypatch)
    for key in ("ga_active_users", "app_response_time", "web_response_time"):
        broken = dict(HEALTHY)
        broken[key] = None
        assert nm.can_notify(broken) is True
        del broken[key]
        assert nm.can_notify(broken) is True


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
