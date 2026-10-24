#!/usr/bin/env python3

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


def test_commit_time_is_none_when_git_is_not_installed(monkeypatch, tmp_path):
    no_git = tmp_path / "bin"
    no_git.mkdir()
    monkeypatch.setenv("PATH", str(no_git))
    assert dora.commit_time("abc123", repo=str(tmp_path)) is None


def _said(level="WARNING"):
    from healthbot.logs import logger

    lines = []
    return lines, logger.add(lambda message: lines.append(message.record["message"]), level=level)


def test_a_host_with_no_git_says_so_once_and_not_as_a_bad_commit(monkeypatch, tmp_path):
    from healthbot.logs import logger

    no_git = tmp_path / "bin"
    no_git.mkdir()
    monkeypatch.setenv("PATH", str(no_git))
    monkeypatch.setattr(dora, "_git_missing_said", False)
    lines, sink = _said()
    try:
        for sha in ("abc123", "def456", "abc789"):
            assert dora.commit_time(sha, repo=str(tmp_path)) is None
    finally:
        logger.remove(sink)
    assert lines == ["git is not installed, so DORA lead time is left out"]


def test_a_bad_commit_with_git_present_still_names_the_commit(monkeypatch, tmp_path):
    from healthbot.logs import logger

    monkeypatch.setattr(dora, "_git_missing_said", False, raising=False)
    lines, sink = _said()
    try:
        assert dora.commit_time("0" * 40, repo=str(Path(__file__).resolve().parents[1])) is None
    finally:
        logger.remove(sink)
    assert any("cannot resolve commit time for" in line for line in lines)
    assert not any("git is not installed" in line for line in lines)
