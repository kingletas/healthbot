"""
Healthy means CloudWatch has a recent datapoint, not that the process is up.

A feeder that is running but cannot reach MiniStack leaves the AWS check
reading "could not collect", which alerts about the wrong thing. Liveness
would report that container as fine; asking the emulator what it actually
holds does not.
"""

import sys
from datetime import UTC, datetime, timedelta

from healthbot.local_env import DB_CLUSTER, aws_client

# The bot reads the newest datapoint of the last five minutes and the feed
# publishes every minute, so three is late enough to survive one missed cycle
# and early enough to fire before a run would see an empty window.
STALE_AFTER = timedelta(minutes=3)


def newest_datapoint() -> datetime | None:
    now = datetime.now(UTC)
    points = aws_client("cloudwatch").get_metric_statistics(
        Namespace="AWS/RDS",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "DBClusterIdentifier", "Value": DB_CLUSTER}],
        StartTime=now - timedelta(minutes=15),
        EndTime=now,
        Period=60,
        Statistics=["Average"],
    )["Datapoints"]
    return max((point["Timestamp"] for point in points), default=None)


def main() -> int:
    try:
        newest = newest_datapoint()
    except Exception as err:
        print(f"cannot read cloudwatch: {err!r}", file=sys.stderr)
        return 1

    if newest is None:
        print("no datapoints published yet", file=sys.stderr)
        return 1

    age = (datetime.now(UTC) - newest).total_seconds()
    if age > STALE_AFTER.total_seconds():
        print(f"newest datapoint is {age:.0f}s old", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
