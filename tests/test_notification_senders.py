#!/usr/bin/env python3

import json

import pytest

import healthbot.notifications.SlackNotificationAware as slack_mod
import healthbot.notifications.TwilioNotificationAware as twilio_mod
from healthbot.api.logs import logger
from healthbot.interfaces.messages.SlackMessage import SlackMessage
from healthbot.interfaces.messages.SnsMessage import SnsMessage
from healthbot.interfaces.messages.TwilioMessage import TwilioMessage
from healthbot.notifications.SnsNotificationAware import SnsNotificationAware


def test_slack_message_renders_the_template():
    message = SlackMessage(
        message_data={
            "header": "All systems green",
            "ga_active_users": 100,
            "app_response_time": 400,
            "web_response_time": 2.0,
            "is_checkout_up": True,
            "ping_ok": True,
            "aws_metrics": {},
        },
        channel="#alerts",
    )
    assert message.channel == "#alerts"
    assert "All systems green" in message.message


# Slack is handed the rendered string as `blocks`, so anything the template can
# emit has to parse. Asserting a substring is present does not catch a stray
# comma, which is how the metrics loop shipped invalid JSON.
@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"aws_metrics": {}}, id="no-metrics"),
        pytest.param({"aws_metrics": {"ec2": {"CPU": 1}}}, id="one-class"),
        pytest.param(
            {"aws_metrics": {"ec2": {"CPU": 1, "Memory": 2}, "rds": {"CPU": 3}}},
            id="several-classes",
        ),
        pytest.param(
            {"aws_metrics": {}, "logo_url": "https://example.com/logo.png", "logo_alt": "Example"},
            id="with-logo",
        ),
    ],
)
def test_slack_message_is_valid_json(extra):
    message = SlackMessage(
        message_data={
            "header": "All systems green",
            "ga_active_users": 100,
            "app_response_time": 400,
            "web_response_time": 2.0,
            "is_checkout_up": True,
            "ping_ok": True,
            **extra,
        },
        channel="#alerts",
    )

    blocks = json.loads(message.message)
    assert isinstance(blocks, list)


def test_slack_message_omits_the_logo_when_none_is_configured():
    data = {
        "header": "All systems green",
        "ga_active_users": 100,
        "app_response_time": 400,
        "web_response_time": 2.0,
        "is_checkout_up": True,
        "ping_ok": True,
        "aws_metrics": {},
    }

    without = json.loads(SlackMessage(message_data={**data, "logo_url": ""}, channel="#c").message)
    with_logo = json.loads(
        SlackMessage(
            message_data={
                **data,
                "logo_url": "https://example.com/logo.png",
                "logo_alt": "Example",
            },
            channel="#c",
        ).message
    )

    assert [e["type"] for e in without[1]["elements"]] == ["mrkdwn", "mrkdwn"]
    assert with_logo[1]["elements"][0]["image_url"] == "https://example.com/logo.png"


def test_slack_sender_posts_blocks_to_the_channel(monkeypatch):
    calls = {}

    class FakeWebClient:
        def __init__(self, token):
            calls["token"] = token

        def chat_postMessage(self, channel, blocks):
            calls["channel"] = channel
            calls["blocks"] = blocks
            return {"ok": True}

    monkeypatch.setattr(slack_mod, "WebClient", FakeWebClient)
    sender = slack_mod.SlackNotificationAware(logger, token="xoxb-1")

    message = SlackMessage.__new__(SlackMessage)
    message.channel = "#alerts"
    message.message = "[]"
    sender.send(message)

    assert calls == {"token": "xoxb-1", "channel": "#alerts", "blocks": "[]"}


def test_twilio_sender_sends_the_sms(monkeypatch):
    sent = {}

    class FakeTwilioClient:
        def __init__(self, sid, token):
            sent["sid"] = sid

            class Messages:
                def create(self, body, from_, to):
                    sent.update({"body": body, "from": from_, "to": to})

                    class R:
                        sid = "SM123"

                    return R()

            class Account:
                messages = Messages()

            class Api:
                account = Account()

            self.api = Api()

    monkeypatch.setattr(twilio_mod, "Client", FakeTwilioClient)
    sender = twilio_mod.TwilioNotificationAware(logger, account_sid="AC1", token="t")
    result = sender.send(TwilioMessage(to="+15550001", message="checkout down", from_="+15550002"))

    assert result == "SM123"
    assert sent["body"] == "checkout down"
    assert sent["to"] == "+15550001"


def test_sns_sender_publishes_with_subject():
    published = {}

    class FakeSnsClient:
        def publish(self, TopicArn, Message, Subject, MessageAttributes):
            published.update(TopicArn=TopicArn, Message=Message, Subject=Subject)
            return {"MessageId": "m-1"}

    sender = object.__new__(SnsNotificationAware)
    sender.client = FakeSnsClient()
    sender.logger = logger

    message = SnsMessage("arn:x", Message="body", Subject="checkout is down", MessageAttributes={})
    assert sender.send(message) == "m-1"
    assert published["Subject"] == "checkout is down"
