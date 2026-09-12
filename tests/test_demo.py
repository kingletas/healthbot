#!/usr/bin/env python3

import random
from pathlib import Path

from healthbot import demo, dora

# Derived from this file rather than hardcoded: the absolute path this used to
# carry broke the moment the workspace was reorganised.
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_data_stays_in_plausible_ranges():
    rng = random.Random(1)
    for _ in range(50):
        data = demo.synth_message_data(rng, failure_rate=0.1)
        assert data["app_response_time"] >= 120.0
        assert data["web_response_time"] >= 0.8
        assert isinstance(data["is_checkout_up"], bool)


def test_emit_run_produces_a_complete_message(monkeypatch):
    data = demo.emit_run(random.Random(2), failure_rate=0.0)
    for key in ("ga_active_users", "app_response_time", "web_response_time", "is_checkout_up"):
        assert key in data


def test_seeding_guarantees_every_dora_panel_has_data(monkeypatch, tmp_path):
    monkeypatch.setenv("HB_DORA_EVENTS", str(tmp_path / "events.jsonl"))
    repo = str(REPO_ROOT)
    seeded = demo.seed_dora_journal(random.Random(3), repo=repo)
    assert seeded > 0

    events = dora.load_events(window_days=60)
    kinds = {e["kind"] for e in events}
    assert {"deploy", "incident", "resolve"} <= kinds

    metrics = dora.compute_metrics(events, window_days=30, repo=repo)
    assert set(metrics) >= {"deployment_frequency_per_day", "change_failure_ratio", "mttr_seconds"}

    # Second seed is a no-op, since the journal already has history
    assert demo.seed_dora_journal(random.Random(4), repo=repo) == 0
