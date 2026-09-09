#!/usr/bin/env python3

import healthbot.healthbot as hb

HEALTHY = {
    "ga_active_users": 100,
    "app_response_time": 400.0,
    "web_response_time": 2.0,
    "is_checkout_up": True,
    "ping_ok": True,
    "header": "All systems green",
}

THRESHOLDS = {"alert_limit": 700, "web_response_alert": 3.5, "app_response_alert": 800}


class FakeParamStore:
    def get_parameter(self, param, **kwargs):
        return "healthbot-secret" if param.endswith("secret_name") else "value"


class FakeSecrets:
    def get_secret(self, name):
        return {"slack_token": "xoxb"}


class FakeGate:
    """The gate's answer, without a Redis round trip."""

    speak = True

    def __init__(self, *args, **kwargs):
        pass

    def should_notify(self, failing):
        return FakeGate.speak


def _wire(monkeypatch, message_data=HEALTHY, boom=False, bad_run=False, speak=True):
    sent = {}
    monkeypatch.setattr(hb, "get_config", lambda name: {"secrets_namespace_prefix": "/hb/"})
    monkeypatch.setattr(hb, "ParameterStoreAwareHelper", FakeParamStore)
    monkeypatch.setattr(hb, "SecretsAwareHelper", FakeSecrets)
    monkeypatch.setattr(hb, "can_notify", lambda data: bad_run)
    monkeypatch.setattr(hb, "alert_thresholds", lambda: THRESHOLDS)
    monkeypatch.setattr(hb, "failing_signals", lambda data, thresholds: ("is_checkout_up",))
    FakeGate.speak = speak
    monkeypatch.setattr(hb, "AlertGate", FakeGate)

    def fake_message_data(**kwargs):
        if boom:
            raise RuntimeError("collector exploded")
        return dict(message_data)

    monkeypatch.setattr(hb, "get_message_data", fake_message_data)
    monkeypatch.setattr(
        hb, "send_notifications", lambda secrets, notifications: sent.update(notifications)
    )
    return sent


def test_a_clean_run_exits_zero_and_builds_the_notification(monkeypatch):
    sent = _wire(monkeypatch)
    assert hb.main() == 0
    assert sent["sns_subject"] == "All systems green"
    assert sent["send_sms"] is False


def test_checkout_down_arms_sms_and_sns(monkeypatch):
    sent = _wire(
        monkeypatch, message_data={**HEALTHY, "is_checkout_up": False}, bad_run=True, speak=True
    )
    assert hb.main() == 0
    assert sent["send_slack"] is True
    assert sent["send_sms"] is True
    assert sent["send_sns"] is True


def test_a_suppressed_repeat_sends_on_no_channel(monkeypatch):
    # The run is still bad and checkout is still down. The gate has already
    # said so recently, and SMS is the channel where repeating costs money as
    # well as attention.
    sent = _wire(
        monkeypatch, message_data={**HEALTHY, "is_checkout_up": False}, bad_run=True, speak=False
    )
    assert hb.main() == 0
    assert sent["send_slack"] is False
    assert sent["send_sms"] is False
    assert sent["send_sns"] is False


def test_a_crashed_run_exits_nonzero(monkeypatch):
    recorded = []
    _wire(monkeypatch, boom=True)
    monkeypatch.setattr(hb.telemetry, "record_slo_events", lambda events: recorded.extend(events))
    assert hb.main() == 1
    # Only the monitor SLI is charged; the site SLIs get no event at all
    assert recorded == [("monitor_availability", False)]
