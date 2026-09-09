#!/usr/bin/env python3

# Standard imports
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from os import path

import yaml

from healthbot import config_d
from healthbot.api.AwsAware import AwsAware

# Local import
from healthbot.api.logs import logger
from healthbot.helper.CacheAwareHelper import CacheAwareHelper
from healthbot.helper.UtilsHelper import get_env_tag_suffix


class EC2Check(AwsAware):
    service_code: str = "ec2"

    def __init__(self, aws_profile: str = None) -> None:
        super().__init__(aws_profile=aws_profile)

    def get_instance_name_from_tag(self, tags: dict) -> str:
        tag_name = "Name tag not assigned"
        for tag in tags:
            if tag.get("Key") == "Name":
                tag_name = tag.get("Value")
                break

        return tag_name

    def get_ec2_instances(self, environment: str, name: str) -> list:

        custom_filter = [
            {"Name": "tag:Environment", "Values": [environment]},
            {"Name": "tag:Name", "Values": [name]},
        ]

        response = self.client.describe_instances(Filters=custom_filter)
        data = []

        for reservation in response.get("Reservations"):
            for instance in reservation.get("Instances"):
                data.append(
                    {
                        "namespace_class": "ec2",
                        "dimension_value": instance.get("InstanceId"),
                        "status": instance.get("State").get("Name"),
                        "object_key": self.get_instance_name_from_tag(instance.get("Tags")),
                    }
                )
        return data


class CloudWatchCheck(AwsAware):
    service_code: str = "cloudwatch"

    def __init__(self, aws_profile: str = None) -> None:
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
            # datapoint — .pop() was reporting the oldest one in the window
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
    cache = CacheAwareHelper(db=0)
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
        }
    ] + ec2_metrics

    for metric in metrics:
        result = cloudwatch.get_aws_metrics(
            namespace_class=metric.get("namespace_class"),
            dimension_value=metric.get("dimension_value"),
            object_key=metric.get("object_key"),
        )
        if result is not None:
            aws_metrics = {**aws_metrics, **result}

    logger.debug(f"AWS metrics: {aws_metrics}")

    return {"aws_metrics": aws_metrics}
