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


class FakeParamStore:
    def get_parameter(self, param, **kwargs):
        return "healthbot-secret" if param.endswith("secret_name") else "value"


class FakeSecrets:
    def get_secret(self, name):
        return {"slack_token": "xoxb"}


def _wire(monkeypatch, message_data=HEALTHY, boom=False):
    sent = {}
    monkeypatch.setattr(hb, "get_config", lambda name: {"secrets_namespace_prefix": "/hb/"})
    monkeypatch.setattr(hb, "ParameterStoreAwareHelper", FakeParamStore)
    monkeypatch.setattr(hb, "SecretsAwareHelper", FakeSecrets)
    monkeypatch.setattr(hb, "can_notify", lambda data: False)

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
    sent = _wire(monkeypatch, message_data={**HEALTHY, "is_checkout_up": False})
    assert hb.main() == 0
    assert sent["send_sms"] is True
    assert sent["send_sns"] is True


def test_a_crashed_run_exits_nonzero(monkeypatch):
    recorded = []
    _wire(monkeypatch, boom=True)
    monkeypatch.setattr(hb.telemetry, "record_slo_events", lambda events: recorded.extend(events))
    assert hb.main() == 1
    # Only the monitor SLI is charged; the site SLIs get no event at all
    assert recorded == [("monitor_availability", False)]
