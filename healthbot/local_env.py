"""
Provision the IT/local stack so a real `healthbot` run works end to end on a
laptop: an AWS emulator plays AWS, Mattermost plays Slack, and the stub container
plays New Relic, Google Analytics and the storefront.

AWS is any LocalStack-compatible emulator, defined outside this project so
one instance serves the whole machine, and reached on the docker bridge
address so containers and the host resolve it identically.

Usage:
    healthbot-local seed            # create params, secret, EC2, SNS, metrics
    healthbot-local feed            # keep CloudWatch datapoints fresh (loop)
    healthbot-local status          # verify every dependency is answering
    healthbot-local run-env         # print the env vars a local run needs

Environment overrides:
    HB_LOCAL_AWS_ENDPOINT   AWS emulator URL     (default http://172.17.0.1:4566)
    HB_LOCAL_API_PORT       stub API host port   (default 8081, read by compose too)
    HB_LOCAL_STORE_PORT     storefront host port (default 8080, read by compose too)
    HB_LOCAL_API_BASE       stub API base        (default http://localhost:$HB_LOCAL_API_PORT)
    HB_LOCAL_STORE_BASE     fake storefront      (default http://localhost:$HB_LOCAL_STORE_PORT)
    HB_LOCAL_MATTERMOST     Mattermost URL       (default http://localhost:8065)

Every AWS client here is built with an explicit endpoint URL and static
dummy credentials, and the endpoint must resolve to a local host. This
script is structurally unable to touch real AWS, which is the point: the
standing rule is that nothing in this project executes against live AWS.
"""

# Standard library imports
import argparse
import base64
import json
import sys
import time
from datetime import UTC, datetime
from os import environ, makedirs, path
from urllib.parse import urlparse

# Third party imports
import boto3
import requests
import rsa
import yaml

# Local imports
from healthbot import DEFAULT_ENV_TAG_SUFFIX
from healthbot.config_files import with_trailing_slash
from healthbot.logs import add_file_sink, logger

AWS_ENDPOINT = environ.get("HB_LOCAL_AWS_ENDPOINT", "http://172.17.0.1:4566")
API_PORT = environ.get("HB_LOCAL_API_PORT", "8081")
STORE_PORT = environ.get("HB_LOCAL_STORE_PORT", "8080")
API_BASE = environ.get("HB_LOCAL_API_BASE", f"http://localhost:{API_PORT}")
STORE_BASE = environ.get("HB_LOCAL_STORE_BASE", f"http://localhost:{STORE_PORT}")
MATTERMOST = environ.get("HB_LOCAL_MATTERMOST", "http://localhost:8065")

REGION = "us-east-1"
PARAM_PREFIX = "/healthbot-sm/manager/"
SECRET_NAME = "healthbot-local"
ENVIRONMENT = "local"  # -> tag:Environment "Local-FLEET" via .title()
TAG_NAME = "web"  # -> tag:Name filter "*WEB*"
INSTANCE_NAME = "EXAMPLE-WEB-01"
DB_CLUSTER = "example-aurora-local"
TOPIC_NAME = "healthbot-local-alerts"

# Relative to the repository root, which is where run-env is documented to run.
LOCAL_CONFIG_DIR = path.join("IT", "local", "config")
DERIVED_CONFIG_DIR = path.join("local.d", "config")

# 172.17.0.1 is the docker bridge address a shared emulator binds to. It is
# reachable from the host and from every container, and not from the LAN. It
# is a local address in exactly the sense this guard means; no public AWS
# endpoint can resolve to it.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "172.17.0.1", "localstack", "ministack"}


def require_local(endpoint: str) -> None:
    host = urlparse(endpoint).hostname
    if host not in LOCAL_HOSTS:
        # Hard refusal, no override flag: a seeding tool that could be
        # pointed at a real account would be one typo away from writing SSM
        # parameters into production.
        raise SystemExit(f"refusing non-local AWS endpoint {endpoint!r} (host {host!r})")


def aws_client(service: str):
    require_local(AWS_ENDPOINT)
    # Static dummy credentials on purpose, never the ambient AWS profile,
    # so a mis-set HOME or exported real keys change nothing.
    return boto3.client(
        service,
        endpoint_url=AWS_ENDPOINT,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def make_ga_service_account() -> dict:
    """
    A syntactically real service account with a throwaway RSA key, generated
    fresh on every seed. google-auth signs a JWT with it and the stub's
    token endpoint accepts anything well-formed. Generated, never committed:
    a private key in the repo would train secret scanners to ignore alarms.
    """
    _, private_key = rsa.newkeys(2048)
    return {
        "type": "service_account",
        "project_id": "healthbot-local",
        "private_key_id": "local-dev-key-id",
        "private_key": private_key.save_pkcs1().decode("ascii"),
        "client_email": "healthbot@healthbot-local.iam.gserviceaccount.com",
        "client_id": "000000000000000000000",
        "token_uri": f"{API_BASE}/ga/token",
    }


def seed_ssm() -> None:
    ssm = aws_client("ssm")
    for name, value in {
        "environment": ENVIRONMENT,
        "tag_name": TAG_NAME,
        "db_identifier": DB_CLUSTER,
        "secret_name": SECRET_NAME,
    }.items():
        ssm.put_parameter(Name=f"{PARAM_PREFIX}{name}", Value=value, Type="String", Overwrite=True)
    logger.info(f"ssm: 4 parameters under {PARAM_PREFIX}")


def seed_ec2() -> str:
    ec2 = aws_client("ec2")
    tag_filters = [
        {"Name": "tag:Environment", "Values": [f"{ENVIRONMENT.title()}-{DEFAULT_ENV_TAG_SUFFIX}"]},
        {"Name": "tag:Name", "Values": [f"*{TAG_NAME.upper()}*"]},
    ]
    existing = ec2.describe_instances(Filters=tag_filters)
    for reservation in existing.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            if instance.get("State", {}).get("Name") == "running":
                logger.info(f"ec2: reusing {instance['InstanceId']}")
                return instance["InstanceId"]

    run = ec2.run_instances(
        ImageId="ami-00000000000000000",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": INSTANCE_NAME},
                    {
                        "Key": "Environment",
                        "Value": f"{ENVIRONMENT.title()}-{DEFAULT_ENV_TAG_SUFFIX}",
                    },
                ],
            }
        ],
    )
    instance_id = run["Instances"][0]["InstanceId"]
    logger.info(f"ec2: launched {instance_id} ({INSTANCE_NAME})")
    return instance_id


def seed_sns() -> str:
    sns = aws_client("sns")
    topic_arn = sns.create_topic(Name=TOPIC_NAME)["TopicArn"]  # idempotent
    logger.info(f"sns: {topic_arn}")
    return topic_arn


def seed_secret(topic_arn: str) -> None:
    ga_json = json.dumps(make_ga_service_account())
    blob = json.dumps(
        {
            # Slack keys; the shim relays chat.postMessage into Mattermost
            # and ignores the token; "town-square" is Mattermost's default
            # channel in the bootstrapped team.
            "slack_token": "xoxb-local-dev-token",  # pragma: allowlist secret
            "slack_channel": "town-square",
            "new_relic_api": "local-dev-nr-key",
            "ga_auth_secrets": base64.b64encode(ga_json.encode("ascii")).decode("ascii"),
            "ga_property_id": "000000001",
            "topic_arn": topic_arn,
            # Deliberately no twilio_* keys: the Twilio SDK has no endpoint
            # seam, so the SMS branch stays skipped locally and is covered by
            # the unit suite instead.
        }
    )
    sm = aws_client("secretsmanager")
    try:
        sm.create_secret(Name=SECRET_NAME, SecretString=blob)
        logger.info(f"secretsmanager: created {SECRET_NAME}")
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId=SECRET_NAME, SecretString=blob)
        logger.info(f"secretsmanager: refreshed {SECRET_NAME}")


def put_datapoints(instance_id: str) -> None:
    """
    One round of CloudWatch datapoints, shaped exactly like the queries in
    checks/aws.py expect (Average over the newest datapoint in a 5-minute
    window). The values wander a little so the dashboards are not flat.
    """
    cloudwatch = aws_client("cloudwatch")
    now = datetime.now(UTC)
    jitter = (now.minute % 10) - 5

    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                "Timestamp": now,
                "Value": 23.0 + jitter,
                "Unit": "Percent",
            }
        ],
    )
    cloudwatch.put_metric_data(
        Namespace="AWS/RDS",
        MetricData=[
            {
                "MetricName": metric,
                "Dimensions": [{"Name": "DBClusterIdentifier", "Value": DB_CLUSTER}],
                "Timestamp": now,
                "Value": value + jitter,
                "Unit": unit,
            }
            for metric, value, unit in (
                ("DatabaseConnections", 42.0, "Count"),
                ("CPUUtilization", 31.0, "Percent"),
                ("Deadlocks", 0.0, "Count"),
            )
        ],
    )


def drop_ec2_metrics_cache() -> None:
    # checks/aws.py caches the discovered instance list in Redis for an hour;
    # a reseed that launched a fresh instance must not serve last hour's ids.
    try:
        from healthbot.cache import Cache

        Cache(db=0).delete("ec2_metrics")
    except Exception as err:
        logger.warning(f"could not drop the ec2_metrics cache (redis down?): {err!r}")


def seed() -> int:
    seed_ssm()
    instance_id = seed_ec2()
    topic_arn = seed_sns()
    seed_secret(topic_arn)
    put_datapoints(instance_id)
    drop_ec2_metrics_cache()
    logger.info("seeded; run `healthbot-local run-env` for the run command")
    return 0


def feed(interval: int, iterations: int) -> int:
    """
    checks/aws.py reads the newest datapoint of the last five minutes, so
    something has to keep publishing or every run sees an empty window.
    """
    instance_id = seed_ec2()
    count = 0
    while iterations == 0 or count < iterations:
        put_datapoints(instance_id)
        count += 1
        logger.info(f"cloudwatch: datapoints published ({count})")
        if iterations != 0 and count >= iterations:
            break
        time.sleep(interval)
    return 0


def probe(name: str, url: str, ok) -> bool:
    try:
        response = requests.get(url, timeout=5)
        good = ok(response)
    except requests.RequestException as err:
        logger.error(f"{name}: unreachable ({err!r})")
        return False
    (logger.info if good else logger.error)(f"{name}: {'ok' if good else 'NOT ok'} ({url})")
    return good


def status() -> int:
    good = True

    good &= probe(
        # The path stays /_localstack/health: the emulator serves LocalStack's
        # API surface unchanged, and renaming it would probe nothing.
        "ministack",
        f"{AWS_ENDPOINT}/_localstack/health",
        lambda r: r.status_code == 200,
    )
    good &= probe("storefront", STORE_BASE, lambda r: r.status_code == 200)
    good &= probe("stub apis", f"{API_BASE}/health", lambda r: r.status_code == 200)
    good &= probe(
        "mattermost",
        f"{MATTERMOST}/api/v4/system/ping",
        lambda r: r.status_code == 200,
    )

    try:
        ssm = aws_client("ssm")
        names = [
            f"{PARAM_PREFIX}{n}"
            for n in ("environment", "tag_name", "db_identifier", "secret_name")
        ]
        found = ssm.get_parameters(Names=names)["Parameters"]
        logger.info(f"ssm: {len(found)}/4 parameters present")
        good &= len(found) == 4

        secret = aws_client("secretsmanager").get_secret_value(SecretId=SECRET_NAME)
        keys = sorted(json.loads(secret["SecretString"]).keys())
        logger.info(f"secretsmanager: {SECRET_NAME} carries {keys}")
    except Exception as err:
        logger.error(f"aws seed data missing, run `healthbot-local seed` ({err!r})")
        good = False

    return 0 if good else 1


def local_config_dir(root: str = "") -> str:
    """
    The config directory a local run should use: IT/local/config when its
    base_url is the storefront this stack serves, otherwise a copy under
    local.d with base_url pointed at the storefront's actual port.
    """
    tracked = path.join(root, LOCAL_CONFIG_DIR)
    with open(path.join(tracked, "site.yml")) as fp:
        site = yaml.safe_load(fp)

    base_url = with_trailing_slash(STORE_BASE)
    if with_trailing_slash(site.get("base_url")) == base_url:
        return tracked

    derived = path.join(root, DERIVED_CONFIG_DIR)
    makedirs(derived, exist_ok=True)
    site["base_url"] = base_url
    with open(path.join(derived, "site.yml"), "w") as fp:
        fp.write(f"# Generated by healthbot-local from {LOCAL_CONFIG_DIR}/site.yml.\n")
        yaml.safe_dump(site, fp, sort_keys=False)
    return derived


def run_env() -> int:
    """
    The full environment for a local end-to-end run, printed rather than
    exported so the operator sees exactly which seams are being redirected.
    """
    lines = [
        f"AWS_ENDPOINT_URL={AWS_ENDPOINT}",
        "AWS_ACCESS_KEY_ID=test",
        "AWS_SECRET_ACCESS_KEY=test",
        f"AWS_DEFAULT_REGION={REGION}",
        f"HB_CONFIG_DIR={local_config_dir()}",
        # The log and any failed-checkout evidence land in the repository's own
        # disposable directory, so the guide can name one exact path.
        "HB_LOG_DIR=local.d/evidence",
        f"HB_NR_API_URL={API_BASE}/nr/v2/",
        f"HB_SLACK_API_URL={API_BASE}/slack/",
        f"HB_GA_DISCOVERY_URL={API_BASE}/ga/discovery",
        "HB_OTEL_ENABLED=1",
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318",
    ]
    print(" \\\n".join(lines) + " \\\nuv run healthbot")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    feed_parser = sub.add_parser("feed")
    feed_parser.add_argument("--interval", type=int, default=60)
    feed_parser.add_argument("--iterations", type=int, default=0, help="0 = forever")
    sub.add_parser("status")
    sub.add_parser("run-env")
    args = parser.parse_args()
    add_file_sink()

    if args.command == "seed":
        return seed()
    if args.command == "feed":
        return feed(interval=args.interval, iterations=args.iterations)
    if args.command == "status":
        return status()
    return run_env()


if __name__ == "__main__":
    sys.exit(main())
