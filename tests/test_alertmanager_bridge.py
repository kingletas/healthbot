#!/usr/bin/env python3
"""
healthbot.notifications.alertmanager_bridge: the webhook receiver for
Alertmanager's firing and resolved alert groups. No network and no real Secrets
Manager here -- every AWS and Slack seam is a fake, in the same shape as
test_notification_senders.py's FakeWebClient. What matters is that the quiet
path (a payload with nothing to send) and the loud path (a real alert) both
answer without ever letting an exception reach Alertmanager as a crash: this
is a server that must keep listening no matter what one bad request does.
"""

import io
import json
from typing import ClassVar

import pytest

import healthbot.notifications.alertmanager_bridge as bridge
from healthbot.errors import ConfigurationError
from healthbot.logs import logger

GOOD_SECRET = {"slack_token": "xoxb-1", "slack_channel": "#host-alerts"}

FIRING_PAYLOAD = {
    "status": "firing",
    "groupLabels": {"alertname": "HostMemoryPressureHigh"},
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HostMemoryPressureHigh", "severity": "ticket"},
            "annotations": {"summary": "Memory pressure at or above the 10% target"},
        }
    ],
}

RESOLVED_PAYLOAD = {
    "status": "resolved",
    "groupLabels": {"alertname": "HostPressureExporterSilent"},
    "alerts": [
        {
            "status": "resolved",
            "labels": {"alertname": "HostPressureExporterSilent", "severity": "page"},
            "annotations": {"summary": "The host-pressure exporter has stopped reporting"},
        }
    ],
}


# --- fakes, in the same shape as test_notification_senders.py's FakeWebClient ---


class FakeParameterStore:
    """Returns a fixed secret_name, or raises the way a missing SSM parameter does."""

    def __init__(self, value=None, raises=None):
        self._value = value
        self._raises = raises

    def get_parameter(self, param):
        if self._raises:
            raise self._raises
        return self._value


class FakeSecretsManager:
    """Returns a fixed secret dict, or raises the way a missing secret does."""

    def __init__(self, secret=None, raises=None):
        self._secret = secret
        self._raises = raises

    def get_secret(self, name):
        if self._raises:
            raise self._raises
        return self._secret


class FakeSlackNotifier:
    """Records what it was asked to send; optionally fails the way Slack can."""

    sent: ClassVar[list] = []  # class-level so a test can point at it without a fixture

    def __init__(self, log, token):
        self.token = token

    def send(self, message):
        FakeSlackNotifier.sent.append((self.token, message))


class RaisingSlackNotifier:
    def __init__(self, log, token):
        pass

    def send(self, message):
        raise RuntimeError("Slack refused the message")


class FakeHandler:
    """
    Just enough of http.server.BaseHTTPRequestHandler for do_POST to run
    without a socket: a path, a body on rfile, a Content-Length header, and
    somewhere to record what was sent back. do_POST() never touches anything
    else on self, so this is the whole surface it needs.
    """

    def __init__(self, path="/alert", body: bytes = b""):
        self.path = path
        self.rfile = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))}
        self.responses = []

    def send_response(self, code):
        self.responses.append(code)

    def end_headers(self):
        pass

    @property
    def status(self):
        assert len(self.responses) == 1, f"expected exactly one response, got {self.responses}"
        return self.responses[0]


DEFAULT_CREDENTIALS = (GOOD_SECRET["slack_token"], GOOD_SECRET["slack_channel"])


def post(monkeypatch, payload_or_bytes, credentials=DEFAULT_CREDENTIALS):
    """Drive do_POST with a JSON payload (or raw bytes) and a stubbed credential lookup."""
    if isinstance(payload_or_bytes, bytes):
        body = payload_or_bytes
    else:
        body = json.dumps(payload_or_bytes).encode()
    monkeypatch.setattr(bridge, "read_slack_credentials", lambda: credentials)
    handler = FakeHandler(body=body)
    bridge.Handler.do_POST(handler)
    return handler


# --- alert_line and AlertmanagerMessage --------------------------------------


def test_alert_line_marks_firing_with_the_red_triangle():
    line = bridge.alert_line(FIRING_PAYLOAD["alerts"][0])
    assert line.startswith(":small_red_triangle_down:")
    assert "HostMemoryPressureHigh" in line
    assert "(firing)" in line


def test_alert_line_marks_resolved_with_the_checkmark():
    line = bridge.alert_line(RESOLVED_PAYLOAD["alerts"][0])
    assert line.startswith(":white_check_mark:")
    assert "(resolved)" in line


def test_alert_line_falls_back_to_description_when_there_is_no_summary():
    alert = {"labels": {"alertname": "X"}, "annotations": {"description": "the long form"}}
    assert "the long form" in bridge.alert_line(alert)


def test_firing_message_header_says_firing():
    message = bridge.AlertmanagerMessage(FIRING_PAYLOAD, channel="#c")
    assert message.channel == "#c"
    assert message.text.startswith("Firing: HostMemoryPressureHigh")
    blocks = json.loads(message.message)
    assert blocks[0]["text"]["text"] == "Firing: HostMemoryPressureHigh"


def test_resolved_message_header_says_resolved():
    message = bridge.AlertmanagerMessage(RESOLVED_PAYLOAD, channel="#c")
    assert message.text.startswith("Resolved: HostPressureExporterSilent")


# --- do_POST: routing and malformed bodies -----------------------------------


def test_wrong_path_is_404_and_sends_nothing(monkeypatch):
    def fail_if_called():
        pytest.fail("read_slack_credentials should not be reached for the wrong path")

    monkeypatch.setattr(bridge, "read_slack_credentials", fail_if_called)
    handler = FakeHandler(path="/not-alert", body=b"{}")
    bridge.Handler.do_POST(handler)
    assert handler.status == 404


def test_invalid_json_is_400_and_sends_nothing(monkeypatch):
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, b"not json at all")
    assert handler.status == 400
    assert FakeSlackNotifier.sent == []


def test_a_payload_with_no_alerts_is_400_and_sends_nothing(monkeypatch):
    # Alertmanager's real webhook always carries at least one alert in a
    # group; an empty one is not something worth turning into a Slack post.
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, {"status": "firing", "alerts": []})
    assert handler.status == 400
    assert FakeSlackNotifier.sent == []


def test_a_json_body_that_is_not_an_object_is_400_not_a_crash(monkeypatch):
    # Valid JSON, wrong shape: a list has no .get(), which used to be the
    # kind of body that only a try/except deep in AlertmanagerMessage caught.
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, [1, 2, 3])
    assert handler.status == 400
    assert FakeSlackNotifier.sent == []


def test_an_empty_body_defaults_to_an_empty_object_and_is_400(monkeypatch):
    # rfile.read(0) is b"", and json.loads(b"" or b"{}") is the documented
    # fallback -- an empty POST must not raise JSONDecodeError.
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, b"")
    assert handler.status == 400
    assert FakeSlackNotifier.sent == []


# --- do_POST: the credential lookup failing -----------------------------------


def test_no_credentials_yet_is_503_and_sends_nothing(monkeypatch):
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, FIRING_PAYLOAD, credentials=None)
    assert handler.status == 503
    assert FakeSlackNotifier.sent == []


# --- do_POST: the loud path, and Slack failing --------------------------------


def test_a_firing_payload_sends_one_message_and_answers_200(monkeypatch):
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, FIRING_PAYLOAD)
    assert handler.status == 200
    assert len(FakeSlackNotifier.sent) == 1
    token, message = FakeSlackNotifier.sent[0]
    assert token == GOOD_SECRET["slack_token"]
    assert message.channel == GOOD_SECRET["slack_channel"]
    assert "HostMemoryPressureHigh" in message.text


def test_a_resolved_payload_sends_one_message_and_answers_200(monkeypatch):
    FakeSlackNotifier.sent.clear()
    monkeypatch.setattr(bridge, "SlackNotifier", FakeSlackNotifier)
    handler = post(monkeypatch, RESOLVED_PAYLOAD)
    assert handler.status == 200
    assert len(FakeSlackNotifier.sent) == 1
    _, message = FakeSlackNotifier.sent[0]
    assert "Resolved" in message.text


def test_slack_failing_answers_502_instead_of_crashing(monkeypatch):
    # The load-bearing assertion: do_POST returns a response rather than
    # letting RuntimeError propagate out of the handler, which is what would
    # take the whole server down on the next alert Slack happens to refuse.
    monkeypatch.setattr(bridge, "SlackNotifier", RaisingSlackNotifier)
    handler = post(monkeypatch, FIRING_PAYLOAD)
    assert handler.status == 502


def test_slack_failing_logs_the_error(monkeypatch):
    # A 502 with no trace anywhere is its own kind of silent failure --
    # loguru does not feed stdlib logging (caplog) by default, so this reads
    # the message straight off a sink added for the assertion.
    monkeypatch.setattr(bridge, "SlackNotifier", RaisingSlackNotifier)
    seen = []
    sink_id = logger.add(lambda message: seen.append(message), level="ERROR")
    try:
        post(monkeypatch, FIRING_PAYLOAD)
    finally:
        logger.remove(sink_id)
    assert any("send failed" in str(m) for m in seen)


# --- read_slack_credentials: the two prefix branches and the failure modes ---


def test_read_slack_credentials_uses_the_configured_param_prefix(monkeypatch):
    monkeypatch.setenv("HB_PARAM_PREFIX", "/custom/prefix/")
    seen_params = []

    def fake_parameter_store():
        class PS:
            def get_parameter(self, param):
                seen_params.append(param)
                return "my-secret"

        return PS()

    monkeypatch.setattr(bridge, "ParameterStore", fake_parameter_store)
    monkeypatch.setattr(bridge, "SecretsManager", lambda: FakeSecretsManager(secret=GOOD_SECRET))

    result = bridge.read_slack_credentials()

    assert seen_params == ["/custom/prefix/secret_name"]
    assert result == (GOOD_SECRET["slack_token"], GOOD_SECRET["slack_channel"])


def test_read_slack_credentials_falls_back_to_site_yml_prefix(monkeypatch):
    monkeypatch.delenv("HB_PARAM_PREFIX", raising=False)
    site_config = {"secrets_namespace_prefix": "/from/site/"}
    monkeypatch.setattr(bridge, "get_config", lambda name: site_config)
    seen_params = []

    def fake_parameter_store():
        class PS:
            def get_parameter(self, param):
                seen_params.append(param)
                return "my-secret"

        return PS()

    monkeypatch.setattr(bridge, "ParameterStore", fake_parameter_store)
    monkeypatch.setattr(bridge, "SecretsManager", lambda: FakeSecretsManager(secret=GOOD_SECRET))

    bridge.read_slack_credentials()

    assert seen_params == ["/from/site/secret_name"]


def test_read_slack_credentials_is_none_when_the_ssm_parameter_is_missing(monkeypatch):
    monkeypatch.setenv("HB_PARAM_PREFIX", "/p/")
    monkeypatch.setattr(
        bridge,
        "ParameterStore",
        lambda: FakeParameterStore(raises=ConfigurationError("no such parameter")),
    )
    assert bridge.read_slack_credentials() is None


def test_read_slack_credentials_is_none_when_the_secret_is_missing(monkeypatch):
    monkeypatch.setenv("HB_PARAM_PREFIX", "/p/")
    monkeypatch.setattr(bridge, "ParameterStore", lambda: FakeParameterStore(value="secret-name"))
    monkeypatch.setattr(
        bridge,
        "SecretsManager",
        lambda: FakeSecretsManager(raises=ConfigurationError("no such secret")),
    )
    assert bridge.read_slack_credentials() is None


@pytest.mark.parametrize(
    "secret",
    [
        pytest.param({}, id="empty"),
        pytest.param({"slack_token": "xoxb-1"}, id="no-channel"),
        pytest.param({"slack_channel": "#c"}, id="no-token"),
        pytest.param({"slack_token": "", "slack_channel": "#c"}, id="blank-token"),
    ],
)
def test_read_slack_credentials_is_none_when_the_secret_has_no_usable_pair(monkeypatch, secret):
    monkeypatch.setenv("HB_PARAM_PREFIX", "/p/")
    monkeypatch.setattr(bridge, "ParameterStore", lambda: FakeParameterStore(value="secret-name"))
    monkeypatch.setattr(bridge, "SecretsManager", lambda: FakeSecretsManager(secret=secret))
    assert bridge.read_slack_credentials() is None


def test_read_slack_credentials_returns_the_pair_when_both_are_present(monkeypatch):
    monkeypatch.setenv("HB_PARAM_PREFIX", "/p/")
    monkeypatch.setattr(bridge, "ParameterStore", lambda: FakeParameterStore(value="secret-name"))
    monkeypatch.setattr(bridge, "SecretsManager", lambda: FakeSecretsManager(secret=GOOD_SECRET))
    assert bridge.read_slack_credentials() == ("xoxb-1", "#host-alerts")
