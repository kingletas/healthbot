# Standard library imports
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from os import path

import yaml

from healthbot import config_d
from healthbot.aws.client import AwsClient
from healthbot.cache import Cache
from healthbot.config_files import get_env_tag_suffix

# Local imports
from healthbot.logs import logger


class EC2Check(AwsClient):
    service_code: str = "ec2"

    def __init__(self, aws_profile: str | None = None) -> None:
        super().__init__(aws_profile=aws_profile)

    def get_instance_name_from_tag(self, tags: dict) -> str | None:
        """The instance's Name tag, or None when it has none."""
        for tag in tags or []:
            if tag.get("Key") == "Name":
                return tag.get("Value")
        return None

    def get_ec2_instances(self, environment: str, name: str) -> list:

        custom_filter = [
            {"Name": "tag:Environment", "Values": [environment]},
            {"Name": "tag:Name", "Values": [name]},
        ]

        response = self.client.describe_instances(Filters=custom_filter)
        data = []

        for reservation in response.get("Reservations"):
            for instance in reservation.get("Instances"):
                instance_id = instance.get("InstanceId")
                data.append(
                    {
                        "namespace_class": "ec2",
                        "dimension_value": instance_id,
                        "status": instance.get("State").get("Name"),
                        # An untagged instance is keyed by its id. The old
                        # fallback was the sentence "Name tag not assigned",
                        # which the alert then shouted as a heading.
                        "object_key": self.get_instance_name_from_tag(instance.get("Tags"))
                        or instance_id,
                    }
                )
        return data


class CloudWatchCheck(AwsClient):
    service_code: str = "cloudwatch"

    def __init__(self, aws_profile: str | None = None) -> None:
        super().__init__(aws_profile=aws_profile)

    def get_aws_metrics(
        self,
        namespace_class: str,
        dimension_value: str,
        object_key: str,
        seconds: int = 300,
        period: int = 60,
        metrics_file: str = "metrics.yml",
        config_d: str = config_d,
    ):
        namespace_class = namespace_class.upper()
        # boto3 wants aware datetimes; naive local time shifts the window
        now = datetime.now(UTC)
        start_time = now - timedelta(seconds=seconds)
        end_time = now

        config_data = load_metrics_config(path.join(config_d, metrics_file))

        data = {}
        namespace_object = config_data.get(namespace_class.upper())
        for metric in namespace_object.get("metrics"):
            namespace = namespace_object.get("namespace").lower()
            query_data = [
                {
                    "Id": f"{namespace}_{metric.lower()}",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": f"AWS/{namespace.upper()}",
                            "MetricName": metric,
                            "Dimensions": [
                                {
                                    "Name": namespace_object.get("dimensions.name"),
                                    "Value": dimension_value,
                                }
                            ],
                        },
                        "Period": period,
                        "Stat": "Average",
                    },
                }
            ]
            logger.debug(query_data)
            # ScanBy makes the ordering explicit so [0] is the newest
            # datapoint. .pop() was reporting the oldest one in the window
            response = self.client.get_metric_data(
                MetricDataQueries=query_data,
                StartTime=start_time,
                EndTime=end_time,
                ScanBy="TimestampDescending",
            )

            values = response.get("MetricDataResults")[0].get("Values")
            if len(values) > 0:
                data[metric] = round(values[0], 2)

        logger.debug(data)
        return {object_key: data} if len(data) > 0 else None


@lru_cache(maxsize=4)
def load_metrics_config(metrics_config: str) -> dict:
    with open(metrics_config) as fp:
        return yaml.safe_load(fp)


def get_metric_data(tag_name: str, db_cluster_identifier: str, environment: str) -> dict:
    cache = Cache(db=0)
    cache_key = "ec2_metrics"
    aws_metrics = {}
    ec2_metrics = cache.get(cache_key)
    if ec2_metrics is None:
        ec2 = EC2Check()
        ec2_metrics = ec2.get_ec2_instances(
            environment=f"{environment.title()}-{get_env_tag_suffix()}",
            name=f"*{tag_name.upper()}*",
        )
        cache.set(cache_key, ec2_metrics)

    cloudwatch = CloudWatchCheck()
    metrics = [
        {
            "namespace_class": "RDS",
            "object_key": "RDS",
            "dimension_value": db_cluster_identifier,
        },
        *ec2_metrics,
    ]

    # The heading each source gets in the alert: metrics.yml's own label for a
    # shared namespace such as RDS, and the instance's Name tag for an EC2 box,
    # which is already the key. Nothing read these labels before.
    namespaces = load_metrics_config(path.join(config_d, "metrics.yml"))
    metric_labels = {}

    for metric in metrics:
        object_key = metric.get("object_key")
        result = cloudwatch.get_aws_metrics(
            namespace_class=metric.get("namespace_class"),
            dimension_value=metric.get("dimension_value"),
            object_key=object_key,
        )
        if result is not None:
            aws_metrics = {**aws_metrics, **result}
            namespace_class = str(metric.get("namespace_class")).upper()
            namespace = namespaces.get(namespace_class, {})
            # An EC2 row is already keyed by the instance's own name, so only
            # a row keyed by the bare namespace takes the namespace label.
            is_namespace_key = str(object_key).upper() == namespace_class
            metric_labels[object_key] = (
                namespace.get("label") if is_namespace_key else None
            ) or object_key

    logger.debug(f"AWS metrics: {aws_metrics}")

    return {"aws_metrics": aws_metrics, "metric_labels": metric_labels}
