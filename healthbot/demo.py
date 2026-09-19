"""
Synthetic runs through the real telemetry pipeline.

The real checks need AWS, New Relic, GA and a browser; this generator needs
none of them, but it emits through exactly the same spans, metrics and SLO
evaluation as production, so the collector → Prometheus → Grafana stack in
IT/observability can be seen working end to end on a laptop.

Usage:
    HB_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \\
        OTEL_METRIC_EXPORT_INTERVAL=15000 healthbot-demo --interval 15

Options: --iterations N (default 0 = run until interrupted), --interval
seconds between runs, --failure-rate for how often a check degrades, --seed
for reproducibility.
"""

# Standard library imports
import argparse
import json
import random
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from os import path

# Local imports
from healthbot import dora, slo, telemetry
from healthbot.logs import logger
from healthbot.settings import get_settings

DEMO_URLS = [
    "/",
    "checkout",
    "checkout/cart",
    "customer/account/login/",
    "shirts.html",
]


def synth_message_data(rng: random.Random, failure_rate: float) -> dict:
    hour = datetime.now(UTC).hour
    # crude diurnal curve so the active-users panel has a shape
    daylight = max(0.2, 1 - abs(hour - 15) / 12)
    data = {
        "ga_active_users": int(rng.gauss(450 * daylight, 60)),
        "app_response_time": max(120.0, rng.gauss(480, 90)),
        "web_response_time": max(0.8, rng.gauss(2.4, 0.5)),
        "is_checkout_up": True,
        "ping_ok": True,
    }
    roll = rng.random()
    if roll < failure_rate / 2:
        data["is_checkout_up"] = False
    elif roll < failure_rate:
        data["web_response_time"] = rng.uniform(3.6, 6.0)
    elif roll < failure_rate * 1.5:
        data["app_response_time"] = rng.uniform(820, 1500)
    return data


def emit_run(rng: random.Random, failure_rate: float) -> dict:
    message_data = synth_message_data(rng, failure_rate)

    with telemetry.run_span():
        telemetry.record_slo_targets(slo.load_slos())

        for name in ("new_relic", "aws_metrics", "google_analytics"):
            with telemetry.check_span(name):
                time.sleep(rng.uniform(0.005, 0.03))

        with telemetry.check_span("checkout") as check:
            time.sleep(rng.uniform(0.01, 0.05))
            if message_data["is_checkout_up"] is not True:
                check.set_status("fail")

        with telemetry.check_span("pings") as check:
            probe_results = []
            for url in DEMO_URLS:
                status = 200
                if not message_data["ping_ok"] or rng.random() < failure_rate / 4:
                    status = rng.choice([500, 503, 0])
                probe_results.append((url, status))
            telemetry.record_probe_statuses(probe_results)
            if any(status != 200 for _, status in probe_results):
                message_data["ping_ok"] = False
                check.set_status("fail")

        telemetry.record_business_metrics(message_data)
        telemetry.record_slo_events(slo.evaluate_run(message_data, run_completed=True))

    return message_data


def recent_shas(repo: str, count: int = 20) -> list:
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", f"-{count}", "--format=%H %cI"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.split() for line in out.stdout.strip().splitlines()]
    except subprocess.CalledProcessError:
        return []


def seed_dora_journal(rng: random.Random, repo: str) -> int:
    """
    Seed ~30 days of plausible deploy/incident history so the DORA panels
    have something to show. Uses real shas from the repo when available, so
    lead time is computed against real commit times. No-op if the journal
    already has events.
    """
    if path.exists(dora.events_file()) and dora.load_events(window_days=365):
        return 0

    shas = recent_shas(repo)
    now = datetime.now(UTC)
    seeded = 0
    day = 30
    while day > 0:
        at = now - timedelta(days=day, hours=rng.uniform(0, 8))
        # Only join a real commit when it plausibly precedes this deploy by
        # under two weeks. This repo's history has multi-year gaps, and a
        # 3-year "lead time" teaches the wrong lesson on the dashboard
        candidates = [
            sha
            for sha, committed in shas
            if timedelta(0) < (at - datetime.fromisoformat(committed)) < timedelta(days=14)
        ]
        sha = rng.choice(candidates) if candidates else None
        status = "failed" if rng.random() < 0.12 else "success"
        dora.record_event("deploy", at=at.isoformat(), sha=sha, status=status)
        seeded += 1
        if status == "failed":
            incident_at = at + timedelta(minutes=rng.uniform(5, 30))
            dora.record_event("incident", at=incident_at.isoformat())
            resolve_at = incident_at + timedelta(minutes=rng.uniform(20, 180))
            dora.record_event("resolve", at=resolve_at.isoformat())
            seeded += 2
        day -= rng.choice([1, 2, 2, 3])

    # Guarantee all four DORA panels have data regardless of the roll of the
    # dice above: at least one failure/incident/resolve, and at least one
    # deploy joined to a commit made in the last two weeks (for lead time).
    events = dora.load_events(window_days=60)
    if not any(e["kind"] == "incident" for e in events):
        incident_at = now - timedelta(days=3)
        dora.record_event("deploy", at=incident_at.isoformat(), status="failed")
        dora.record_event("incident", at=(incident_at + timedelta(minutes=10)).isoformat())
        dora.record_event("resolve", at=(incident_at + timedelta(minutes=95)).isoformat())
        seeded += 3
    fresh = [
        sha
        for sha, committed in shas
        if timedelta(0) < (now - datetime.fromisoformat(committed)) < timedelta(days=14)
    ]
    if fresh and not any(e.get("sha") for e in events):
        dora.record_event("deploy", at=(now - timedelta(hours=2)).isoformat(), sha=fresh[0])
        seeded += 1
    return seeded


def main() -> int:
    parser = argparse.ArgumentParser(prog="healthbot-demo", description=__doc__)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--iterations", type=int, default=0, help="0 = until interrupted")
    parser.add_argument("--failure-rate", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--repo", default=get_settings().dora_repo)
    args = parser.parse_args()

    if not telemetry.setup_telemetry():
        logger.error(
            "telemetry is disabled: set HB_OTEL_ENABLED=1 and "
            "OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://localhost:4318)"
        )
        return 1

    rng = random.Random(args.seed)
    seeded = seed_dora_journal(rng, args.repo)
    if seeded:
        logger.info(f"seeded {seeded} DORA events into {dora.events_file()}")

    count = 0
    try:
        while args.iterations == 0 or count < args.iterations:
            message_data = emit_run(rng, args.failure_rate)
            count += 1
            if count % 10 == 1:
                metrics = dora.compute_metrics(dora.load_events(30), window_days=30, repo=args.repo)
                telemetry.record_dora(metrics)
                logger.info(f"DORA: {json.dumps(metrics)}")
            logger.info(f"run {count}: {json.dumps(message_data)}")
            if args.iterations == 0 or count < args.iterations:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        telemetry.shutdown_telemetry()

    return 0


if __name__ == "__main__":
    sys.exit(main())
