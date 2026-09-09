#!/usr/bin/env python3

"""
DORA metrics from an append-only event journal.

`healthbot-dora record deploy|incident|resolve` appends one JSON line per
event; `healthbot-dora export` computes the four DORA metrics over a window
and emits them through the same OTel pipeline as everything else. Lead time
comes from git: a deploy recorded with --sha is joined to that commit's
author time.

The journal lives at HB_DORA_EVENTS (default
~/.local/share/healthbot/dora-events.jsonl) — deliberately a flat file, so a
deploy can be recorded from the Ansible playbook with one line and no
service dependency.
"""

# Standard imports
import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from os import makedirs, path

# Local imports
from healthbot import telemetry
from healthbot.api.logs import logger
from healthbot.settings import get_settings


def events_file() -> str:
    return get_settings().dora_events


def record_event(kind: str, at: str = None, sha: str = None, status: str = "success") -> dict:
    event = {
        "kind": kind,
        "at": at or datetime.now(UTC).isoformat(),
        "sha": sha,
        "status": status,
    }
    target = events_file()
    makedirs(path.dirname(target), exist_ok=True)
    with open(target, "a") as fp:
        fp.write(json.dumps(event) + "\n")
    return event


def load_events(window_days: int, now: datetime = None) -> list:
    target = events_file()
    if not path.exists(target):
        return []
    now = now or datetime.now(UTC)
    events = []
    with open(target) as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            at = datetime.fromisoformat(event["at"])
            if (now - at).total_seconds() <= window_days * 86400:
                event["at_dt"] = at
                events.append(event)
    return events


def commit_time(sha: str, repo: str = None) -> datetime | None:
    repo = repo or get_settings().dora_repo
    try:
        out = subprocess.run(
            ["git", "-C", repo, "show", "-s", "--format=%cI", sha],
            capture_output=True,
            text=True,
            check=True,
        )
        return datetime.fromisoformat(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        logger.error(f"cannot resolve commit time for {sha!r} in {repo!r}")
        return None


def compute_metrics(events: list, window_days: int, repo: str = None) -> dict:
    """
    The four DORA metrics over the window. Absent data yields an absent key,
    never a fake zero — an empty journal is "no data", not "elite performer".
    """
    deploys = [e for e in events if e["kind"] == "deploy"]
    metrics = {}

    if deploys:
        metrics["deployment_frequency_per_day"] = round(len(deploys) / window_days, 4)
        failed = [d for d in deploys if d.get("status") == "failed"]
        metrics["change_failure_ratio"] = round(len(failed) / len(deploys), 4)

        lead_times = []
        for deploy in deploys:
            if deploy.get("sha"):
                committed = commit_time(deploy["sha"], repo=repo)
                if committed is not None:
                    lead_times.append((deploy["at_dt"] - committed).total_seconds())
        if lead_times:
            metrics["lead_time_seconds"] = round(sum(lead_times) / len(lead_times), 1)

    # MTTR: pair each incident with the first resolve after it
    incidents = sorted((e for e in events if e["kind"] == "incident"), key=lambda e: e["at_dt"])
    resolves = sorted((e for e in events if e["kind"] == "resolve"), key=lambda e: e["at_dt"])
    durations = []
    for incident in incidents:
        match = next((r for r in resolves if r["at_dt"] > incident["at_dt"]), None)
        if match is not None:
            durations.append((match["at_dt"] - incident["at_dt"]).total_seconds())
            resolves.remove(match)
    if durations:
        metrics["mttr_seconds"] = round(sum(durations) / len(durations), 1)

    return metrics


def export(window_days: int, repo: str = None) -> dict:
    metrics = compute_metrics(load_events(window_days), window_days, repo=repo)
    telemetry.setup_telemetry()
    telemetry.record_dora(metrics)
    telemetry.shutdown_telemetry()
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(prog="healthbot-dora", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="append one event to the journal")
    record.add_argument("kind", choices=["deploy", "incident", "resolve"])
    record.add_argument("--sha", help="commit deployed (enables lead time)")
    record.add_argument("--status", choices=["success", "failed"], default="success")
    record.add_argument("--at", help="ISO timestamp, default now")

    exporter = sub.add_parser("export", help="compute the window and emit via OTLP")
    exporter.add_argument("--window-days", type=int, default=30)
    exporter.add_argument("--repo", help="git repo for lead time (default HB_DORA_REPO or cwd)")

    args = parser.parse_args()

    if args.command == "record":
        event = record_event(args.kind, at=args.at, sha=args.sha, status=args.status)
        print(json.dumps(event))
    else:
        metrics = export(args.window_days, repo=args.repo)
        print(json.dumps(metrics, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
