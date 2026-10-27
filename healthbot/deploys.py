"""
Deploys read from mdp's ledger: one annotation per deploy on every dashboard,
how long checkout took to get back to normal after it, and a DORA event.

mdp (magento-deploy-playbook) appends one JSON record per step to its audit
log; its docs/ledger.md is the field reference. A deploy is every record that
shares a `release`, from `deploy.started` to the record that ends it:
`deploy.finished`, `deploy.failed` or `deploy.rolled_back`. A deploy with no
end yet is still running, and is left for the next read.

`healthbot-deploys annotate` posts each finished deploy to Grafana as a region
annotation tagged `deploy`, which every provisioned dashboard shows, and skips
one already posted, so it can run after every deploy or on a timer. A deploy
whose checkout has not settled waits up to two hours for a later read.
`healthbot-deploys dora` appends each finished deploy to the DORA journal once,
labelled with its environment, so `healthbot-dora export --env` keeps the
showcase's deploys apart from any other environment's.

Back to normal is the time from a deploy's end until checkout's average
duration is within 10% of what it was in the half hour before the deploy
began, and stays there for three samples in a row. HealthBot measures
checkout once a run, so the answer is no finer than its run interval.
"""

# Standard library imports
import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from os import path

# Third party imports
import requests

# Local imports
from healthbot import dora
from healthbot.logs import add_file_sink, logger
from healthbot.settings import get_settings

ENDS = {"deploy.finished", "deploy.failed", "deploy.rolled_back"}
# Checkout's average duration over ten minutes, from the histogram every run records.
CHECKOUT_SECONDS = (
    'sum(rate(healthbot_check_duration_seconds_sum{check="checkout"}[10m]))'
    ' / sum(rate(healthbot_check_duration_seconds_count{check="checkout"}[10m]))'
)
BASELINE = timedelta(minutes=30)
TOLERANCE = 1.10
HOLD = 3
# How long after a deploy checkout is watched for, and an annotation waits for it to settle.
SETTLE = timedelta(hours=2)


@dataclass
class Deploy:
    release: str
    env: str
    started: datetime
    ended: datetime
    outcome: str
    commit: str | None
    maintenance_seconds: float | None

    @property
    def failed(self) -> bool:
        return self.outcome != "success"


def _at(record: dict) -> datetime:
    return datetime.fromisoformat(record["recorded_at"].replace("Z", "+00:00"))


def read_ledger(path: str) -> list[Deploy]:
    """Every finished deploy in the ledger, oldest first."""
    by_release: dict[str, list[dict]] = {}
    with open(path) as fp:
        for number, line in enumerate(fp, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"{path} line {number} is not JSON, so it is left out")
                continue
            if record.get("release"):
                by_release.setdefault(record["release"], []).append(record)

    deploys = []
    for release, records in by_release.items():
        records.sort(key=lambda r: r.get("seq", 0))
        start = next((r for r in records if r.get("event") == "deploy.started"), None)
        end = next((r for r in reversed(records) if r.get("event") in ENDS), None)
        if start is None or end is None:
            continue
        if end["event"] == "deploy.finished":
            outcome = end.get("outcome") or "success"
        else:
            outcome = "failed" if end["event"] == "deploy.failed" else "rolled_back"
        built = next((r for r in records if r.get("commit")), {})
        window_up = next((r for r in records if r.get("event") == "maintenance.enabled"), None)
        cutover = next((r for r in records if r.get("event") == "cutover.succeeded"), None)
        maintenance = None
        if window_up and cutover:
            maintenance = (_at(cutover) - _at(window_up)).total_seconds()
        deploys.append(
            Deploy(
                release=release,
                env=start.get("env_name") or "",
                started=_at(start),
                ended=_at(end),
                outcome=outcome,
                commit=built.get("commit"),
                maintenance_seconds=maintenance,
            )
        )
    return sorted(deploys, key=lambda d: d.started)


def back_to_normal(
    series: list[tuple[datetime, float]], started: datetime, ended: datetime
) -> float | None:
    """
    Seconds from the deploy's end until checkout is back within TOLERANCE of
    its baseline for HOLD samples in a row, or None when there is no baseline
    to compare with or it has not come back yet.
    """
    before = [v for t, v in series if started - BASELINE <= t < started]
    if not before:
        return None
    ceiling = statistics.median(before) * TOLERANCE
    after = [(t, v) for t, v in series if t >= ended]
    for i in range(len(after) - HOLD + 1):
        if all(v <= ceiling for _, v in after[i : i + HOLD]):
            return (after[i][0] - ended).total_seconds()
    return None


def checkout_series(prometheus: str, start: datetime, end: datetime, step: int = 60) -> list:
    """Checkout's average duration from Prometheus, as (time, seconds) pairs."""
    response = requests.get(
        f"{prometheus}/api/v1/query_range",
        params={
            "query": CHECKOUT_SECONDS,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step,
        },
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    if not result:
        return []
    return [
        (datetime.fromtimestamp(float(t), UTC), float(v))
        for t, v in result[0]["values"]
        if v not in ("NaN", "+Inf")
    ]


def annotation(deploy: Deploy, normal_after: float | None) -> dict:
    """The Grafana region annotation for one deploy."""
    minutes = (deploy.ended - deploy.started).total_seconds() / 60
    lines = [f"Deploy {deploy.release} ({deploy.env}): {deploy.outcome}, {minutes:.1f} min"]
    if deploy.maintenance_seconds is not None:
        lines.append(f"maintenance window {deploy.maintenance_seconds:.0f} s")
    if normal_after is None:
        lines.append("checkout not back to normal yet, or no baseline to compare with")
    else:
        lines.append(f"checkout back to normal {normal_after / 60:.1f} min after")
    return {
        "time": int(deploy.started.timestamp() * 1000),
        "timeEnd": int(deploy.ended.timestamp() * 1000),
        "tags": [
            "deploy",
            f"env:{deploy.env}",
            f"outcome:{deploy.outcome}",
            f"release:{deploy.release}",
        ],
        "text": "; ".join(lines),
    }


def annotate(
    deploys: list[Deploy], grafana: str, prometheus: str, now: datetime | None = None
) -> int:
    """Post each deploy Grafana does not hold yet. Returns how many were posted."""
    now = now or datetime.now(UTC)
    posted = 0
    for deploy in deploys:
        tag = f"release:{deploy.release}"
        held = requests.get(
            f"{grafana}/api/annotations", params={"tags": tag, "limit": 1}, timeout=30
        )
        held.raise_for_status()
        if held.json():
            continue
        series = checkout_series(
            prometheus, deploy.started - BASELINE, min(now, deploy.ended + SETTLE)
        )
        normal_after = back_to_normal(series, deploy.started, deploy.ended)
        # An annotation is posted once, so one whose checkout has not settled
        # waits for a later read.
        if normal_after is None and now - deploy.ended < SETTLE:
            continue
        sent = requests.post(
            f"{grafana}/api/annotations",
            json=annotation(deploy, normal_after),
            timeout=30,
        )
        sent.raise_for_status()
        posted += 1
    return posted


def record_dora(deploys: list[Deploy]) -> int:
    """Append each deploy the DORA journal does not hold yet. Returns how many were added."""
    held = set()
    for event in dora.load_events(window_days=36500):
        if event.get("release"):
            held.add(event["release"])
    added = 0
    for deploy in deploys:
        if deploy.release in held:
            continue
        dora.record_event(
            "deploy",
            at=deploy.ended.isoformat(),
            sha=deploy.commit,
            status="failed" if deploy.failed else "success",
            env=deploy.env,
            release=deploy.release,
        )
        added += 1
    return added


def main() -> int:
    parser = argparse.ArgumentParser(prog="healthbot-deploys", description=__doc__)
    parser.add_argument("command", choices=["list", "annotate", "dora"])
    parser.add_argument("--ledger", help="mdp's audit log (default HB_MDP_LEDGER)")
    args = parser.parse_args()
    add_file_sink()

    settings = get_settings()
    ledger = args.ledger or settings.mdp_ledger
    if not ledger:
        print(
            "healthbot-deploys: name mdp's audit log with --ledger or HB_MDP_LEDGER",
            file=sys.stderr,
        )
        return 2
    if not path.isfile(ledger):
        print(f"healthbot-deploys: there is no ledger at {ledger}", file=sys.stderr)
        return 2
    deploys = read_ledger(ledger)

    if args.command == "list":
        for deploy in deploys:
            when = deploy.started.isoformat()
            print(f"{when}  {deploy.env:<12} {deploy.outcome:<12} {deploy.release}")
    elif args.command == "annotate":
        posted = annotate(deploys, settings.grafana_url, settings.prometheus_url)
        print(f"{posted} deploy(s) annotated, {len(deploys) - posted} already there")
    else:
        added = record_dora(deploys)
        print(f"{added} deploy(s) added to the DORA journal, {len(deploys) - added} already there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
