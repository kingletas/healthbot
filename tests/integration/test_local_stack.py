#!/usr/bin/env python3

"""
End-to-end against the IT/local docker stack: Mattermost, the stub APIs and
the fake storefront, plus the shared MiniStack that plays AWS. Excluded from
the default run; needs:

    docker run -d --name ministack -p 4566:4566 localstack/localstack:4.9
    cd IT/local && docker compose up -d --build
    uv run healthbot-local seed
    uv run pytest -m integration

The crown jewel here is test_full_run: the production main(), every check
live, exit code 0, and the alert relay observable in Mattermost.
"""

import time
from os import environ, path

import pytest
import requests

pytestmark = pytest.mark.integration

# The same overrides the seeder reads, so pointing one of them at a stack on
# different ports cannot leave the tests asserting against another. Hardcoded,
# they skipped the whole suite on any machine where 8080 was already taken.
AWS_ENDPOINT = environ.get("HB_LOCAL_AWS_ENDPOINT", "http://172.17.0.1:4566")
STORE = environ.get("HB_LOCAL_STORE_BASE", "http://localhost:8080")
API = environ.get("HB_LOCAL_API_BASE", "http://localhost:8081")
MATTERMOST = environ.get("HB_LOCAL_MATTERMOST", "http://localhost:8065")
REPO_ROOT = path.dirname(path.dirname(path.dirname(path.abspath(__file__))))
LOCAL_CONFIG = environ.get("HB_CONFIG_DIR") or path.join(REPO_ROOT, "IT", "local", "config")


@pytest.fixture(scope="module", autouse=True)
def stack_or_skip():
    try:
        # Plain HTTP on purpose: this is the docker bridge address, the
        # emulator serves no TLS, and the credentials are the literal
        # string "test". semgrep exempts "localhost" but not 172.17.0.1.
        # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http  # noqa: E501
        health = requests.get(f"{AWS_ENDPOINT}/_localstack/health", timeout=3)
        requests.get(f"{API}/health", timeout=3).raise_for_status()
        requests.get(STORE, timeout=3).raise_for_status()
    except requests.RequestException as err:
        pytest.skip(f"IT/local stack not running: {err!r}")
    if health.status_code != 200:
        pytest.skip("MiniStack answered but is not healthy")


@pytest.fixture(autouse=True)
def local_run_env(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", AWS_ENDPOINT)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("HB_CONFIG_DIR", LOCAL_CONFIG)
    monkeypatch.setenv("HB_NR_API_URL", f"{API}/nr/v2/")
    monkeypatch.setenv("HB_SLACK_API_URL", f"{API}/slack/")
    monkeypatch.setenv("HB_GA_DISCOVERY_URL", f"{API}/ga/discovery")
    # Telemetry stays off in the test run: the observability stack is
    # exercised by healthbot-demo, and OTLP export retries would slow a
    # collector-less test run down for nothing.
    monkeypatch.setenv("HB_OTEL_ENABLED", "0")


def control(**switches) -> None:
    requests.post(f"{API}/control", json=switches, timeout=5).raise_for_status()


@pytest.fixture(autouse=True)
def calm_state():
    control(checkout_down=False, canary_down=False, ga_surge=False, nr_slow=False)
    clear_alert_state()
    yield
    control(checkout_down=False, canary_down=False, ga_surge=False, nr_slow=False)
    clear_alert_state()


def clear_alert_state() -> None:
    """
    Forget that anything was alerted about.

    The gate suppresses a repeat of the same condition for fifteen minutes,
    which is the point of it, and it would make this suite pass once and then
    quietly stop asserting anything on the second run of the afternoon.
    """
    from healthbot.alerting import ALERT_STATE_DB, STATE_KEY
    from healthbot.cache import Cache

    Cache(db=ALERT_STATE_DB).delete(STATE_KEY)


def mattermost_posts() -> list:
    """The town-square posts, via the admin the stub container bootstraps."""
    login = requests.post(
        f"{MATTERMOST}/api/v4/users/login",
        # The throwaway account the stub container bootstraps in the local
        # Mattermost. Local-only by construction; never reused anywhere.
        json={
            "login_id": "sre@local.test",
            "password": "SuperSecret-123",  # pragma: allowlist secret
        },
        timeout=10,
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.headers['Token']}"}
    team = requests.get(f"{MATTERMOST}/api/v4/teams/name/sre", headers=headers, timeout=10).json()
    channel = requests.get(
        f"{MATTERMOST}/api/v4/teams/{team['id']}/channels/name/town-square",
        headers=headers,
        timeout=10,
    ).json()
    posts = requests.get(
        f"{MATTERMOST}/api/v4/channels/{channel['id']}/posts", headers=headers, timeout=10
    ).json()
    return list(posts["posts"].values())


def test_seeded_aws_is_readable_through_the_bots_own_helpers():
    from healthbot.aws.parameter_store import ParameterStore
    from healthbot.aws.secrets_manager import SecretsManager

    param_store = ParameterStore()
    prefix = "/healthbot-sm/manager/"
    secret_name = param_store.get_parameter(f"{prefix}secret_name")
    assert secret_name == "healthbot-local"

    secrets = SecretsManager().get_secret(name=secret_name)
    assert "slack_token" in secrets and "ga_auth_secrets" in secrets


def test_storefront_carries_the_checkout_journey():
    home = requests.get(STORE, timeout=5)
    assert 'id="search"' in home.text

    results = requests.get(f"{STORE}/catalogsearch/result/", params={"q": "shirt"}, timeout=5)
    assert "products-grid" in results.text and "product-item-photo" in results.text

    checkout = requests.get(f"{STORE}/checkout", timeout=5)
    assert "<title>Checkout</title>" in checkout.text


def test_chaos_switch_takes_checkout_down_and_back():
    control(checkout_down=True)
    assert "<title>Checkout</title>" not in requests.get(f"{STORE}/checkout", timeout=5).text
    control(checkout_down=False)
    assert "<title>Checkout</title>" in requests.get(f"{STORE}/checkout", timeout=5).text


def test_full_run():
    """
    The production main(), all five checks against the local stack. A healthy
    stack must produce exit code 0, and because the stub NR/GA values are
    calm, no alert should be relayed into Mattermost by this run.
    """
    from healthbot.healthbot import main

    before = len(mattermost_posts())
    assert main([]) == 0
    assert len(mattermost_posts()) == before  # calm run, no alert


def test_staged_outage_pages_into_mattermost():
    """
    Flip the ga_surge switch (active users over site.yml's active_users_alert) and
    the run must alert with exit 0, because the *site* is degraded rather than
    the monitor, and
    with the Slack blocks relayed into Mattermost by the shim.
    """
    from healthbot.healthbot import main

    before = len(mattermost_posts())
    control(ga_surge=True)
    assert main([]) == 0
    time.sleep(1)  # relay is async fire-and-forget from the run's view
    posts = mattermost_posts()
    assert len(posts) == before + 1
    newest = max(posts, key=lambda post: post["create_at"])
    # Assert real rendered content, not just the bot's name, because the shim's
    # own fallback placeholder contains "HealthBot", which once let a broken
    # relay pass this test.
    assert "Why this alert fired" in newest["message"]
    assert "Checkout" in newest["message"]
    # The push line, which the shim labels and puts first. It named only the
    # checkout journey and the canary sweep, so a surge reached a locked phone
    # reading "all checks passed".
    assert "Active users: 934, limit 700" in newest["message"].splitlines()[0]
    # The surge count itself, not just the words around it: `*None*` also
    # contains the label, so the loose assertion passed while Universal
    # Analytics was returning nothing at all.
    assert "*934*" in newest["message"]


def test_ga4_realtime_report_is_read_through_the_real_client():
    """
    The GA4 Data API path, end to end: discovery document, signed JWT, the
    runRealtimeReport POST and the response parse, all through the same
    googleapiclient the deployed bot uses.

    Both values are asserted because reaching the endpoint is not the same as
    parsing it. The withdrawn Universal Analytics call returned its total under
    a different key entirely, so a check that only proved "a number came back"
    would not have noticed.
    """
    import base64
    import json

    from healthbot.aws.parameter_store import ParameterStore
    from healthbot.aws.secrets_manager import SecretsManager
    from healthbot.checks.ga import GaCheck

    param_store = ParameterStore()
    secret_name = param_store.get_parameter("/healthbot-sm/manager/secret_name")
    secrets = SecretsManager().get_secret(name=secret_name)
    service_account = json.loads(base64.b64decode(secrets["ga_auth_secrets"]).decode("ascii"))
    check = GaCheck(
        json_secret=service_account,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )

    control(ga_surge=False)
    assert check.get_active_users(secrets["ga_property_id"]) == 137

    control(ga_surge=True)
    assert check.get_active_users(secrets["ga_property_id"]) == 934


def test_sns_alert_lands_on_the_local_topic():
    """
    checkout_down makes send_sns true; verify against the emulator that the
    topic exists and the publish path does not error (message delivery is
    covered by the exit code, since MiniStack accepts the publish).
    """
    import boto3

    from healthbot.healthbot import main

    control(checkout_down=True)
    assert main([]) == 0

    sns = boto3.client("sns", endpoint_url=AWS_ENDPOINT, region_name="us-east-1")
    topics = [t["TopicArn"] for t in sns.list_topics()["Topics"]]
    assert any(arn.endswith("healthbot-local-alerts") for arn in topics)


def test_secret_blob_never_lands_in_redis():
    """
    The L-series principle pinned against the live stack: after a full run,
    no Redis key in any db may contain the Slack token or the GA blob.
    """
    import redis

    for db in range(3):
        client = redis.Redis(host="localhost", port=6379, db=db)
        for key in client.scan_iter():
            value = client.get(key)
            if value is None:
                continue
            text = value.decode("utf-8", errors="replace")
            assert "xoxb-local-dev-token" not in text  # pragma: allowlist secret
            assert "ga_auth_secrets" not in text or "private_key" not in text


def test_localstack_accepts_aws_namespace_datapoints():
    """
    The whole CloudWatch leg depends on the emulator allowing publishes into
    AWS/* namespaces (real AWS refuses them). If this ever regresses on an
    emulator upgrade, this is the test that says so by name. Kept under its
    original name: it guards the behaviour, not the vendor.
    """
    import boto3

    cloudwatch = boto3.client("cloudwatch", endpoint_url=AWS_ENDPOINT, region_name="us-east-1")
    metrics = cloudwatch.list_metrics(Namespace="AWS/RDS")["Metrics"]
    names = {metric["MetricName"] for metric in metrics}
    assert {"DatabaseConnections", "CPUUtilization"} <= names


def test_full_json_of_status_command():
    from healthbot import local_env

    assert local_env.status() == 0
