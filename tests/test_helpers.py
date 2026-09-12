#!/usr/bin/env python3

from healthbot.cache import Cache
from healthbot.checks.aws import EC2Check, load_metrics_config
from healthbot.notifications.sns import SnsMessage
from healthbot.notifications.twilio import TwilioMessage


def test_cache_keys_are_prefixed_and_normalized():
    helper = Cache()  # constructing does not connect
    key = helper.prepare_key("site.yml")
    assert key.startswith("healthbot_")
    assert key == helper.prepare_key("site.yml")
    assert key != helper.prepare_key("metrics.yml")


def test_instance_name_comes_from_the_name_tag():
    check = object.__new__(EC2Check)
    tags = [{"Key": "Environment", "Value": "x"}, {"Key": "Name", "Value": "web-1"}]
    assert check.get_instance_name_from_tag(tags) == "web-1"
    assert check.get_instance_name_from_tag([]) == "Name tag not assigned"


def test_metrics_config_loads_and_is_cached(tmp_path):
    config = tmp_path / "metrics.yml"
    config.write_text("EC2:\n    namespace: ec2\n    metrics:\n        - CPUUtilization\n")
    first = load_metrics_config(str(config))
    assert first["EC2"]["metrics"] == ["CPUUtilization"]
    # Regression for the per-metric re-parse: the second read must be the
    # cached object, not a fresh parse.
    assert load_metrics_config(str(config)) is first


def test_message_dataclasses_carry_their_fields():
    sns = SnsMessage(topic_arn="arn:x", body="m", subject="s", attributes={})
    assert (sns.topic_arn, sns.body, sns.subject) == ("arn:x", "m", "s")

    sms = TwilioMessage(to="+1", body="m", from_="+2")
    assert (sms.to, sms.body, sms.from_) == ("+1", "m", "+2")
