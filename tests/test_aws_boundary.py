#!/usr/bin/env python3

import json

import boto3
import pytest
from moto import mock_aws

from healthbot.aws.parameter_store import ParameterStore
from healthbot.aws.secrets_manager import SecretsManager
from healthbot.checks.aws import CloudWatchCheck, EC2Check


@pytest.fixture(autouse=True)
def aws_region(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


class FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, duration: int = 0):
        self.store[key] = value


@mock_aws
def test_ec2_instances_are_found_by_tags():
    ec2 = boto3.client("ec2", region_name="us-east-2")
    image = ec2.describe_images()["Images"][0]["ImageId"]
    instance = ec2.run_instances(
        ImageId=image,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Environment", "Value": "Stage-FLEET"},
                    {"Key": "Name", "Value": "EXAMPLE-WEB-1"},
                ],
            }
        ],
    )["Instances"][0]

    found = EC2Check().get_ec2_instances(environment="Stage-FLEET", name="*EXAMPLE-WEB*")
    assert len(found) == 1
    assert found[0]["dimension_value"] == instance["InstanceId"]
    assert found[0]["object_key"] == "EXAMPLE-WEB-1"
    assert found[0]["namespace_class"] == "ec2"


@mock_aws
def test_cloudwatch_metrics_come_back_keyed_by_object(tmp_path):
    config = tmp_path / "metrics.yml"
    config.write_text(
        "EC2:\n"
        "    namespace: ec2\n"
        "    dimensions.name: InstanceId\n"
        "    metrics:\n"
        "        - CPUUtilization\n"
    )
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-2")
    # moto quirk: a datapoint stamped "now" falls outside a window that ends
    # at now, so backdate it into the query window explicitly
    from datetime import UTC, datetime, timedelta

    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-123"}],
                "Timestamp": datetime.now(UTC) - timedelta(seconds=90),
                "Value": 42.0,
            }
        ],
    )

    result = CloudWatchCheck().get_aws_metrics(
        namespace_class="ec2",
        dimension_value="i-123",
        object_key="web-1",
        config_d=str(tmp_path),
    )
    assert result == {"web-1": {"CPUUtilization": 42.0}}


@mock_aws
def test_parameters_cache_plain_values_and_never_sensitive_ones():
    ssm = boto3.client("ssm", region_name="us-east-2")
    ssm.put_parameter(Name="/hb/environment", Value="stage", Type="String")
    ssm.put_parameter(Name="/hb/token", Value="hunter2", Type="SecureString")

    cache = FakeCache()
    helper = ParameterStore(cache=cache)

    assert helper.get_parameter("/hb/environment") == "stage"
    assert cache.store["/hb/environment"] == "stage"

    # Regression for the inversion: sensitive values were the only thing the
    # old code persisted to Redis
    assert helper.get_parameter("/hb/token", with_decryption=True, is_sensitive=True) == "hunter2"
    assert "/hb/token" not in cache.store


@mock_aws
def test_secrets_are_fetched_fresh_and_never_cached():
    sm = boto3.client("secretsmanager", region_name="us-east-2")
    sm.create_secret(Name="hb-test", SecretString=json.dumps({"slack_token": "xoxb-1"}))

    helper = SecretsManager()
    assert helper.get_secret("hb-test") == {"slack_token": "xoxb-1"}
    # The plaintext-blob-in-Redis cache is gone with the inheritance
    assert not hasattr(helper, "cache")
