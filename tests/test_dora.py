#!/usr/bin/env python3

import json
from datetime import UTC, datetime, timedelta

from healthbot import dora


def _use_tmp_journal(monkeypatch, tmp_path):
    journal = tmp_path / "events.jsonl"
    monkeypatch.setenv("HB_DORA_EVENTS", str(journal))
    return journal


def test_record_appends_one_json_line_per_event(monkeypatch, tmp_path):
    journal = _use_tmp_journal(monkeypatch, tmp_path)
    dora.record_event("deploy", sha="abc123")
    dora.record_event("incident")
    lines = journal.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "deploy"


def test_window_filters_old_events(monkeypatch, tmp_path):
    _use_tmp_journal(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    dora.record_event("deploy", at=(now - timedelta(days=40)).isoformat())
    dora.record_event("deploy", at=(now - timedelta(days=5)).isoformat())
    assert len(dora.load_events(window_days=30)) == 1


def test_metrics_over_a_synthetic_window():
    now = datetime.now(UTC)

    def event(kind, days_ago, **extra):
        at = now - timedelta(days=days_ago)
        return {"kind": kind, "at": at.isoformat(), "at_dt": at, "sha": None, **extra}

    events = [
        event("deploy", 20, status="success"),
        event("deploy", 10, status="failed"),
        event("deploy", 5, status="success"),
        event("incident", 10),
        {
            "kind": "resolve",
            "at": (now - timedelta(days=10) + timedelta(hours=2)).isoformat(),
            "at_dt": now - timedelta(days=10) + timedelta(hours=2),
            "sha": None,
        },
    ]
    metrics = dora.compute_metrics(events, window_days=30)
    assert metrics["deployment_frequency_per_day"] == 0.1
    assert metrics["change_failure_ratio"] == round(1 / 3, 4)
    assert metrics["mttr_seconds"] == 7200.0
    # no shas -> no lead time, and no fake zero either
    assert "lead_time_seconds" not in metrics


def test_lead_time_joins_deploys_to_real_commits(monkeypatch, tmp_path):
    # Use this repo's own HEAD commit as the deployed sha
    import subprocess

    repo = str(tmp_path)
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(
        ["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env=git_env,
    )
    sha = subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    deploy_at = datetime.now(UTC) + timedelta(hours=1)
    events = [
        {
            "kind": "deploy",
            "at": deploy_at.isoformat(),
            "at_dt": deploy_at,
            "sha": sha,
            "status": "success",
        }
    ]
    metrics = dora.compute_metrics(events, window_days=30, repo=repo)
    assert 3000 < metrics["lead_time_seconds"] < 4200


def test_empty_journal_reports_no_data_not_zeroes():
    assert dora.compute_metrics([], window_days=30) == {}
