#!/usr/bin/env python3

import json

import pytest

import healthbot.notifications.slack as slack_mod
import healthbot.notifications.twilio as twilio_mod
from healthbot.alerting import describe_failing, failing_signals
from healthbot.logs import logger
from healthbot.notifications.slack import SlackMessage
from healthbot.notifications.sns import SnsMessage, SnsNotifier
from healthbot.notifications.twilio import TwilioMessage

THRESHOLDS = {"active_users_alert": 700, "web_response_alert": 3.5, "app_response_alert": 800}


def test_slack_message_renders_the_template():
    message = SlackMessage(
        message_data={
            "header": "All systems green",
            "ga_active_users": 100,
            "app_response_time": 400,
            "web_response_time": 2.0,
            "is_checkout_up": True,
            "canary_ok": True,
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
            "canary_ok": True,
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
        "canary_ok": True,
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


def test_a_metric_that_could_not_be_collected_says_so(monkeypatch):
    # The template rendered a missing value as an empty string, so a New Relic
    # outage arrived as "*ms* Response time", a measurement of nothing rather
    # than a failure to measure.
    message = SlackMessage(
        message_data={
            "header": "h",
            "is_checkout_up": True,
            "canary_ok": True,
            "aws_metrics": {},
        },
        channel="#c",
    )

    fields = " ".join(f["text"] for f in json.loads(message.message)[2]["fields"])
    assert fields.count("_not collected_") == 7
    assert "**" not in fields


def test_metric_classes_become_one_section_each():
    message = SlackMessage(
        message_data={
            "header": "h",
            "is_checkout_up": True,
            "canary_ok": True,
            "aws_metrics": {"rds": {"CPUUtilization": 27.0}, "ec2": {"CPUUtilization": 19.0}},
        },
        channel="#c",
    )

    blocks = json.loads(message.message)
    headings = [b["text"]["text"] for b in blocks[4:]]
    assert headings == ["*rds*", "*ec2*"]
    assert blocks[4]["fields"] == [
        {"type": "mrkdwn", "text": "CPUUtilization"},
        {"type": "mrkdwn", "text": "*27.0*"},
    ]


def test_slack_sender_posts_blocks_to_the_channel(monkeypatch):
    calls = {}

    class FakeWebClient:
        def __init__(self, token):
            calls["token"] = token

        # slack_sdk's own method name.
        def chat_postMessage(self, channel, blocks, text):  # noqa: N802
            calls["channel"] = channel
            calls["blocks"] = blocks
            calls["text"] = text
            return {"ok": True}

    monkeypatch.setattr(slack_mod, "WebClient", FakeWebClient)
    sender = slack_mod.SlackNotifier(logger, token="xoxb-1")

    message = SlackMessage.__new__(SlackMessage)
    message.channel = "#alerts"
    message.message = "[]"
    message.text = "HealthBot: all checks passed"
    sender.send(message)

    assert calls == {
        "token": "xoxb-1",
        "channel": "#alerts",
        "blocks": "[]",
        "text": "HealthBot: all checks passed",
    }


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
    sender = twilio_mod.TwilioNotifier(logger, account_sid="AC1", token="t")
    result = sender.send(TwilioMessage(to="+15550001", body="checkout down", from_="+15550002"))

    assert result == "SM123"
    assert sent["body"] == "checkout down"
    assert sent["to"] == "+15550001"


def test_sns_sender_publishes_with_subject():
    published = {}

    class FakeSnsClient:
        # boto3's own parameter names; a fake that renames them tests nothing.
        def publish(self, TopicArn, Message, Subject, MessageAttributes):  # noqa: N803
            published.update(TopicArn=TopicArn, Message=Message, Subject=Subject)
            return {"MessageId": "m-1"}

    sender = object.__new__(SnsNotifier)
    sender.client = FakeSnsClient()
    sender.logger = logger

    message = SnsMessage(topic_arn="arn:x", body="body", subject="checkout is down", attributes={})
    assert sender.send(message) == "m-1"
    assert published["Subject"] == "checkout is down"


def test_the_alert_carries_a_text_fallback_for_push_and_screen_readers():
    # Blocks alone arrive on a locked phone as the bot's name and nothing
    # else. Slack warns about this; an alerting tool cannot afford it.
    healthy = {"header": "HealthBot", "is_checkout_up": True, "canary_ok": True, "aws_metrics": {}}

    up = SlackMessage(message_data=healthy, channel="#c")
    assert up.text == "HealthBot: nothing is failing"

    down = SlackMessage(
        message_data={**healthy, "is_checkout_up": False},
        channel="#c",
        failing_lines=["Checkout: failing"],
    )
    assert down.text == "HealthBot: Checkout: failing"


def test_a_latency_page_never_says_the_checks_passed():
    # The push line used to look at checkout and the canary sweep only, so a
    # run paging on response time arrived on a locked phone reading
    # "all checks passed".
    slow = {
        "header": "HealthBot",
        "is_checkout_up": True,
        "canary_ok": True,
        "aws_metrics": {},
        "app_response_time": 2300.0,
    }
    failing = failing_signals(slow, THRESHOLDS)
    message = SlackMessage(
        message_data=slow,
        channel="#c",
        failing_lines=describe_failing(failing, slow, THRESHOLDS),
    )

    assert "passed" not in message.text
    assert "App response time: 2300.0ms, limit 800ms" in message.text


def test_the_alert_says_why_it_fired_with_the_limit_beside_the_value():
    slow = {
        "header": "HealthBot",
        "is_checkout_up": True,
        "canary_ok": True,
        "aws_metrics": {},
        "web_response_time": 6.2,
    }
    failing = failing_signals(slow, THRESHOLDS)
    message = SlackMessage(
        message_data=slow,
        channel="#c",
        failing_lines=describe_failing(failing, slow, THRESHOLDS),
    )

    why = [b for b in json.loads(message.message) if "Why this alert fired" in str(b)]
    assert len(why) == 1
    assert "Web response time: 6.2s, limit 3.5s" in why[0]["text"]["text"]


def test_an_uncollected_signal_says_so_rather_than_naming_a_number():
    blind = {"header": "HealthBot", "is_checkout_up": True, "canary_ok": True, "aws_metrics": {}}
    failing = failing_signals(blind, THRESHOLDS)
    lines = describe_failing(failing, blind, THRESHOLDS)

    assert "App response time: couldn't be collected" in lines


def test_an_untagged_instance_is_headed_by_its_id_not_a_sentence():
    message = SlackMessage(
        message_data={
            "header": "h",
            "is_checkout_up": True,
            "canary_ok": True,
            "aws_metrics": {"i-0abc": {"CPUUtilization": 19.0}, "RDS": {"Deadlocks": 0.0}},
            "metric_labels": {"i-0abc": "i-0abc", "RDS": "RDS Stats"},
        },
        channel="#c",
    )

    headings = [b["text"]["text"] for b in json.loads(message.message)[4:]]
    assert headings == ["*i-0abc*", "*RDS Stats*"]
