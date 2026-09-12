#!/usr/bin/env python3

"""
The IT/local seams: each HB_* override redirects exactly one external
dependency, and each defaults to production behaviour when unset.
"""

import json

import boto3
import pytest
from moto import mock_aws

import healthbot.checks.nr as nr
import healthbot.config_files as utils
import healthbot.local_env as local_env
from healthbot import config_d
from healthbot.notifications.slack import SlackNotifier


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


# --------------------------------------------------------------------------
# HB_CONFIG_DIR
# --------------------------------------------------------------------------


def test_config_dir_override_wins_when_file_exists(monkeypatch, tmp_path):
    (tmp_path / "site.yml").write_text("base_url: http://localhost:8080/\n")
    monkeypatch.setenv("HB_CONFIG_DIR", str(tmp_path))
    assert utils.resolve_config_file("site.yml") == str(tmp_path / "site.yml")


def test_config_dir_falls_back_to_packaged_config(monkeypatch, tmp_path):
    # The override dir carries only site.yml; everything else must still
    # resolve to the packaged copy, or a local run would need a full mirror.
    monkeypatch.setenv("HB_CONFIG_DIR", str(tmp_path))
    resolved = utils.resolve_config_file("cookies.yml")
    assert resolved.startswith(config_d)


def test_config_dir_unset_is_the_packaged_config(monkeypatch):
    monkeypatch.delenv("HB_CONFIG_DIR", raising=False)
    assert utils.resolve_config_file("site.yml").startswith(config_d)


def test_config_cache_is_keyed_by_resolved_path(monkeypatch, tmp_path):
    # Regression guard: with the bare filename as the key, a run with
    # HB_CONFIG_DIR set would be served the cached copy of the *other*
    # directory's file and the override would half-apply.
    class FakeCache:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value, duration: int = 0):
            self.store[key] = value

    fake = FakeCache()
    monkeypatch.setattr(utils, "cache", fake)

    (tmp_path / "site.yml").write_text("base_url: http://localhost:8080/\n")

    monkeypatch.delenv("HB_CONFIG_DIR", raising=False)
    packaged = utils.get_config("site.yml")

    monkeypatch.setenv("HB_CONFIG_DIR", str(tmp_path))
    overridden = utils.get_config("site.yml")

    assert packaged["base_url"] != overridden["base_url"]
    assert len(fake.store) == 2


# --------------------------------------------------------------------------
# HB_NR_API_URL
# --------------------------------------------------------------------------


def test_nr_url_override_redirects_the_request(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True
        links = None

        def json(self):
            return {"applications": []}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setenv("HB_NR_API_URL", "http://localhost:8081/nr/v2")
    monkeypatch.setattr("newrelic_api.base.requests.get", fake_get)

    nr.get_newrelic_app(api_key="key", name_filter="example-web")
    # The trailing slash is added by the seam; Resource.URL is joined by
    # plain concatenation, so without it the path would be nr/v2applications…
    assert captured["url"].startswith("http://localhost:8081/nr/v2/applications.json")


def test_nr_url_unset_keeps_the_real_api(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True
        links = None

        def json(self):
            return {"applications": []}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.delenv("HB_NR_API_URL", raising=False)
    monkeypatch.setattr("newrelic_api.base.requests.get", fake_get)

    nr.get_newrelic_app(api_key="key")
    assert captured["url"].startswith("https://api.newrelic.com/v2/")


# --------------------------------------------------------------------------
# HB_SLACK_API_URL
# --------------------------------------------------------------------------


def test_slack_base_url_override(monkeypatch):
    monkeypatch.setenv("HB_SLACK_API_URL", "http://localhost:8081/slack/")
    sender = SlackNotifier(logger=None, token="xoxb-local")
    assert sender.client.base_url == "http://localhost:8081/slack/"


def test_slack_base_url_default_is_slack(monkeypatch):
    monkeypatch.delenv("HB_SLACK_API_URL", raising=False)
    sender = SlackNotifier(logger=None, token="xoxb-local")
    assert sender.client.base_url == "https://slack.com/api/"


# --------------------------------------------------------------------------
# HB_GA_DISCOVERY_URL
# --------------------------------------------------------------------------


def test_ga_discovery_override_disables_static_discovery(monkeypatch):
    import healthbot.checks.ga as ga

    captured = {}

    monkeypatch.setenv("HB_GA_DISCOVERY_URL", "http://localhost:8081/ga/discovery")
    monkeypatch.setattr(
        ga.Credentials, "from_service_account_info", classmethod(lambda cls, info, scopes: "creds")
    )
    monkeypatch.setattr(ga, "build", lambda *args, **kwargs: captured.update(kwargs) or "service")

    ga.GaCheck(scopes=["s"], json_secret={})
    assert captured["discoveryServiceUrl"] == "http://localhost:8081/ga/discovery"
    # Without this the bundled static document's rootUrl wins and the
    # override silently does nothing.
    assert captured["static_discovery"] is False


def test_ga_discovery_unset_builds_plain(monkeypatch):
    import healthbot.checks.ga as ga

    captured = {}

    monkeypatch.delenv("HB_GA_DISCOVERY_URL", raising=False)
    monkeypatch.setattr(
        ga.Credentials, "from_service_account_info", classmethod(lambda cls, info, scopes: "creds")
    )
    monkeypatch.setattr(ga, "build", lambda *args, **kwargs: captured.update(kwargs) or "service")

    ga.GaCheck(scopes=["s"], json_secret={})
    assert "discoveryServiceUrl" not in captured
    assert "static_discovery" not in captured


# --------------------------------------------------------------------------
# healthbot-local: the endpoint guard and the seeded shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://ssm.us-east-1.amazonaws.com",
        "https://secretsmanager.us-east-1.amazonaws.com",
        "https://monitoring.us-east-1.amazonaws.com",
        # Looks local, is not: the guard matches the host exactly rather than
        # by prefix, so a lookalike public host cannot slip through.
        "https://172.17.0.1.evil.example.com",
    ],
)
def test_seeder_refuses_non_local_endpoints(endpoint):
    with pytest.raises(SystemExit):
        local_env.require_local(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:4566",
        "http://127.0.0.1:4566",
        "http://localstack:4566",
        # The shared dev-services MiniStack binds to the docker bridge
        # address; without this the seeder refuses its own endpoint.
        "http://172.17.0.1:4566",
    ],
)
def test_seeder_accepts_local_endpoints(endpoint):
    local_env.require_local(endpoint)


def test_the_default_endpoint_passes_its_own_guard():
    # The guard and the default are edited in different places; a default that
    # the guard rejects would make every seed a hard exit.
    local_env.require_local(local_env.AWS_ENDPOINT)


@mock_aws
def test_seed_provisions_everything_the_bot_reads(monkeypatch):
    # moto does not intercept a custom endpoint URL, so the localhost-pinned
    # client factory is swapped for plain moto-mocked clients here, because the
    # seeded shape is what is under test; the endpoint guard has its own test.
    monkeypatch.setattr(
        local_env, "aws_client", lambda service: boto3.client(service, region_name=local_env.REGION)
    )
    monkeypatch.setattr(local_env, "drop_ec2_metrics_cache", lambda: None)
    assert local_env.seed() == 0

    ssm = boto3.client("ssm", region_name=local_env.REGION)
    params = {
        name: ssm.get_parameter(Name=f"{local_env.PARAM_PREFIX}{name}")["Parameter"]["Value"]
        for name in ("environment", "tag_name", "db_identifier", "secret_name")
    }
    assert params["environment"] == "local"
    assert params["secret_name"] == local_env.SECRET_NAME

    secret = boto3.client("secretsmanager", region_name=local_env.REGION).get_secret_value(
        SecretId=local_env.SECRET_NAME
    )
    blob = json.loads(secret["SecretString"])
    # Exactly the keys main() reads, and none of the Twilio ones, because the SDK
    # has no endpoint seam, so the SMS branch must stay skipped locally.
    assert {
        "slack_token",
        "slack_channel",
        "new_relic_api",
        "ga_auth_secrets",
        "ga_property_id",
    } <= set(blob)
    assert not any(key.startswith("twilio") for key in blob)

    # The instance is discoverable by the exact tag filters checks/aws.py uses
    ec2 = boto3.client("ec2", region_name=local_env.REGION)
    found = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Environment", "Values": ["Local-FLEET"]},
            {"Name": "tag:Name", "Values": ["*WEB*"]},
        ]
    )
    assert len(found["Reservations"]) == 1

    # Seeding twice must reuse, not multiply
    monkeypatch.setattr(local_env, "make_ga_service_account", lambda: {"token_uri": "x"})
    assert local_env.seed() == 0
    found = ec2.describe_instances(Filters=[{"Name": "tag:Environment", "Values": ["Local-FLEET"]}])
    assert len(found["Reservations"]) == 1
