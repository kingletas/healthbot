#!/usr/bin/env python3
"""Deploys read from an invented mdp ledger, back to normal on an invented
checkout series with a known answer, Grafana annotations against a stand-in,
and the DORA journal kept per environment."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from healthbot import deploys, dora

T0 = datetime(2026, 3, 2, 2, 0, tzinfo=UTC)


def _record(seq, minutes, event, release, env="showcase", **extra):
    at = (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": 1,
        "seq": seq,
        "recorded_at": at,
        "prev_hash": "0" * 64,
        "hash": "f" * 64,
        "event": event,
        "env_name": env,
        "release": release,
        "actor": {"git_email": "deployer@example.test", "os_user": "deploy"},
        **extra,
    }


def _ledger(tmp_path, records):
    path = tmp_path / "audit.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + "not json\n")
    return str(path)


@pytest.fixture
def ledger(tmp_path):
    return _ledger(
        tmp_path,
        [
            _record(1, 0, "deploy.started", "20260302_1_showcase", branch="main", goes_live=True),
            _record(2, 3, "build.succeeded", "20260302_1_showcase", commit="a1b2c3d"),
            _record(3, 4, "maintenance.enabled", "20260302_1_showcase"),
            _record(4, 5, "cutover.succeeded", "20260302_1_showcase", maintenance_window=True),
            _record(5, 6, "deploy.finished", "20260302_1_showcase", outcome="success"),
            _record(6, 60, "deploy.started", "20260302_2_showcase"),
            _record(7, 64, "health.failed", "20260302_2_showcase", hosts=["web-2"]),
            _record(8, 66, "deploy.rolled_back", "20260302_2_showcase", trigger="health_check"),
            _record(9, 70, "deploy.started", "20260302_3_staging", env="staging"),
            _record(10, 72, "deploy.failed", "20260302_3_staging", env="staging", phase="upload"),
            _record(11, 90, "deploy.started", "20260302_4_showcase"),
        ],
    )


def test_a_deploy_is_every_record_of_one_release_from_its_start_to_its_end(ledger):
    found = deploys.read_ledger(ledger)
    assert [d.release for d in found] == [
        "20260302_1_showcase",
        "20260302_2_showcase",
        "20260302_3_staging",
    ]
    first = found[0]
    assert (first.env, first.outcome, first.commit) == ("showcase", "success", "a1b2c3d")
    assert first.ended - first.started == timedelta(minutes=6)
    assert first.maintenance_seconds == 60


def test_a_rollback_and_a_failure_are_failed_deploys(ledger):
    found = {d.release: d for d in deploys.read_ledger(ledger)}
    assert found["20260302_2_showcase"].outcome == "rolled_back"
    assert found["20260302_3_staging"].outcome == "failed"
    assert found["20260302_2_showcase"].failed and not found["20260302_1_showcase"].failed


def test_a_deploy_still_running_is_left_for_the_next_read(ledger):
    assert "20260302_4_showcase" not in {d.release for d in deploys.read_ledger(ledger)}


def _series(values, start=T0 - timedelta(minutes=30), step=timedelta(minutes=5)):
    return [(start + i * step, v) for i, v in enumerate(values)]


def test_back_to_normal_is_the_first_of_three_samples_within_ten_percent_of_the_baseline():
    # Baseline 4.0 s for the half hour before; slow after the deploy, then
    # back within 10% from 20 minutes after its end.
    before = [4.0] * 6
    after = [9.0, 7.0, 4.3, 5.0, 4.2, 4.1, 4.4]
    series = _series(before + after)
    started, ended = T0, T0 + timedelta(minutes=0)
    assert deploys.back_to_normal(series, started, ended) == 20 * 60


def test_back_to_normal_is_none_while_checkout_is_still_slow():
    series = _series([4.0] * 6 + [9.0, 4.0, 8.0, 4.0, 4.0])
    assert deploys.back_to_normal(series, T0, T0) is None


def test_back_to_normal_is_none_with_no_baseline_to_compare_with():
    series = _series([4.0] * 5, start=T0)
    assert deploys.back_to_normal(series, T0, T0) is None


def test_an_annotation_spans_the_deploy_and_says_how_it_went(ledger):
    first = deploys.read_ledger(ledger)[0]
    note = deploys.annotation(first, 1200)
    assert note["time"] == int(first.started.timestamp() * 1000)
    assert note["timeEnd"] == int(first.ended.timestamp() * 1000)
    assert note["tags"] == [
        "deploy",
        "env:showcase",
        "outcome:success",
        "release:20260302_1_showcase",
    ]
    assert "6.0 min" in note["text"] and "maintenance window 60 s" in note["text"]
    assert "back to normal 20.0 min after" in note["text"]


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class _Grafana:
    """Grafana's annotation API and Prometheus's range query, stood in for."""

    def __init__(self, held=(), series=()):
        self.held = set(held)
        self.posted = []
        self.series = list(series)

    def get(self, url, params=None, timeout=None):
        if url.endswith("/api/annotations"):
            return _Response([{"id": 1}] if params["tags"] in self.held else [])
        values = [[t.timestamp(), str(v)] for t, v in self.series]
        return _Response({"data": {"result": [{"values": values}] if values else []}})

    def post(self, url, json=None, timeout=None):
        self.posted.append(json)
        return _Response({"id": len(self.posted)})


def test_annotate_posts_each_deploy_once(monkeypatch, ledger):
    stand_in = _Grafana(held={"release:20260302_2_showcase"})
    monkeypatch.setattr(deploys.requests, "get", stand_in.get)
    monkeypatch.setattr(deploys.requests, "post", stand_in.post)
    later = T0 + timedelta(days=1)
    posted = deploys.annotate(
        deploys.read_ledger(ledger), "http://grafana.test", "http://prom.test", now=later
    )
    assert posted == 2
    assert [p["tags"][-1] for p in stand_in.posted] == [
        "release:20260302_1_showcase",
        "release:20260302_3_staging",
    ]


def test_annotate_waits_for_checkout_to_settle_after_a_recent_deploy(monkeypatch, ledger):
    stand_in = _Grafana()
    monkeypatch.setattr(deploys.requests, "get", stand_in.get)
    monkeypatch.setattr(deploys.requests, "post", stand_in.post)
    just_after = T0 + timedelta(minutes=80)
    deploys.annotate(
        deploys.read_ledger(ledger), "http://grafana.test", "http://prom.test", now=just_after
    )
    assert stand_in.posted == []


def test_dora_gets_each_deploy_once_labelled_with_its_environment(monkeypatch, tmp_path, ledger):
    journal = tmp_path / "dora.jsonl"
    monkeypatch.setenv("HB_DORA_EVENTS", str(journal))
    found = deploys.read_ledger(ledger)
    assert deploys.record_dora(found) == 3
    assert deploys.record_dora(found) == 0
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [(e["env"], e["status"]) for e in events] == [
        ("showcase", "success"),
        ("showcase", "failed"),
        ("staging", "failed"),
    ]
    assert events[0]["sha"] == "a1b2c3d"


def test_dora_counts_one_environment_without_the_others():
    at = datetime.now(UTC)
    events = [
        {"kind": "deploy", "at_dt": at, "status": "success", "env": "showcase", "sha": None},
        {"kind": "deploy", "at_dt": at, "status": "failed", "env": "showcase", "sha": None},
        {"kind": "deploy", "at_dt": at, "status": "failed", "env": "staging", "sha": None},
        {"kind": "deploy", "at_dt": at, "status": "success", "sha": None},
    ]
    showcase = dora.compute_metrics(events, window_days=1, env="showcase")
    assert showcase["deployment_frequency_per_day"] == 2
    assert showcase["change_failure_ratio"] == 0.5
    assert dora.compute_metrics(events, window_days=1)["deployment_frequency_per_day"] == 4


def test_every_provisioned_dashboard_shows_the_deploys_this_posts(ledger):
    from pathlib import Path

    dashboards = sorted(
        (Path(__file__).parent.parent / "IT/observability/grafana/dashboards").glob("*.json")
    )
    assert dashboards
    tag = deploys.annotation(deploys.read_ledger(ledger)[0], None)["tags"][0]
    for path in dashboards:
        shown = json.loads(path.read_text()).get("annotations", {}).get("list", [])
        assert any(tag in (a.get("target") or {}).get("tags", []) for a in shown), path.name


def test_a_ledger_that_is_not_there_is_said_in_one_line(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "nowhere.jsonl"
    monkeypatch.setattr("sys.argv", ["healthbot-deploys", "list", "--ledger", str(missing)])
    assert deploys.main() == 2
    assert capsys.readouterr().err.strip() == f"healthbot-deploys: there is no ledger at {missing}"
