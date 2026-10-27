#!/usr/bin/env python3

"""
The alert history: one line for every decision the gate makes, kept after the
gate's own state is gone, and the numbers read back from it.

Every condition, time and figure here is invented.
"""

# Standard library imports
import json
from datetime import UTC, datetime

# Third party imports
import pytest

# Local imports
from healthbot import alert_history
from healthbot.alerting import STATE_KEY, AlertGate

from .test_alerting import FakeCache

START = datetime(2030, 1, 14, 9, 0, tzinfo=UTC).timestamp()


def at(minutes: float) -> float:
    return START + minutes * 60


def lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def history(tmp_path):
    return tmp_path / "alert-history.jsonl"


def run(cache, history, minutes, failing):
    return AlertGate(cache=cache, now=at(minutes), history=str(history)).should_notify(failing)


# --------------------------------------------------------------------------
# What the gate writes
# --------------------------------------------------------------------------


def test_one_condition_s_whole_life_is_written_in_order(history):
    cache = FakeCache()
    down = ("is_checkout_up",)
    assert run(cache, history, 0, down) is True
    assert run(cache, history, 5, down) is False
    assert run(cache, history, 15, down) is True
    assert run(cache, history, 20, ()) is False
    assert run(cache, history, 25, ()) is False

    written = lines(history)
    assert [w["event"] for w in written] == ["raised", "held", "repeat", "clean", "recovered"]
    assert {w["condition"] for w in written} == {"is_checkout_up"}
    assert written[0]["at"] == "2030-01-14T09:00:00+00:00"
    assert written[2]["repeats"] == 1
    assert written[3]["clean_runs"] == 1
    recovered = written[-1]
    assert recovered["raised_at"] == "2030-01-14T09:00:00+00:00"
    assert recovered["at"] == "2030-01-14T09:25:00+00:00"
    assert recovered["repeats"] == 1


def test_the_record_survives_the_clear_that_deletes_the_gate_s_state(history):
    cache = FakeCache()
    run(cache, history, 0, ("canary_ok",))
    run(cache, history, 5, ())
    run(cache, history, 10, ())

    assert STATE_KEY not in cache.store
    assert [w["event"] for w in lines(history)] == ["raised", "clean", "recovered"]


def test_a_healthy_run_with_nothing_standing_writes_nothing(history):
    for minutes in (0, 5, 10):
        run(FakeCache(), history, minutes, ())

    assert not history.exists()


def test_a_new_condition_says_which_one_it_replaced(history):
    cache = FakeCache()
    run(cache, history, 0, ("web_response_time",))
    run(cache, history, 5, ("canary_ok", "web_response_time"))

    replaced = lines(history)[-1]
    assert replaced["event"] == "raised"
    assert replaced["condition"] == "canary_ok|web_response_time"
    assert replaced["replaces"] == "web_response_time"


def test_a_history_that_cannot_be_written_never_changes_what_is_sent(tmp_path):
    blocked = tmp_path / "not-a-file"
    blocked.mkdir()
    cache = FakeCache()

    assert run(cache, blocked, 0, ("is_checkout_up",)) is True
    assert cache.store[STATE_KEY]["condition"] == "is_checkout_up"
    assert run(cache, blocked, 5, ("is_checkout_up",)) is False


def test_an_unreadable_state_store_still_sends_and_still_writes(history):
    broken = FakeCache(broken=True)
    assert run(broken, history, 0, ("is_checkout_up",)) is True
    assert run(broken, history, 5, ("is_checkout_up",)) is True

    assert [w["event"] for w in lines(history)] == ["raised", "raised"]


# --------------------------------------------------------------------------
# What is read back
# --------------------------------------------------------------------------

# January: three incidents. One cleared in ten minutes with no repeat sent, one
# took 75 minutes and two repeats, one was replaced by a different condition.
# February: one incident, still standing.
FIXTURE = [
    {"at": "2030-01-03T10:00:00+00:00", "event": "raised", "condition": "canary_ok", "repeats": 0},
    {
        "at": "2030-01-03T10:05:00+00:00",
        "event": "clean",
        "condition": "canary_ok",
        "clean_runs": 1,
    },
    {
        "at": "2030-01-03T10:10:00+00:00",
        "event": "recovered",
        "condition": "canary_ok",
        "raised_at": "2030-01-03T10:00:00+00:00",
        "repeats": 0,
    },
    {
        "at": "2030-01-09T08:00:00+00:00",
        "event": "raised",
        "condition": "is_checkout_up",
        "repeats": 0,
    },
    {
        "at": "2030-01-09T08:15:00+00:00",
        "event": "repeat",
        "condition": "is_checkout_up",
        "repeats": 1,
    },
    {
        "at": "2030-01-09T08:45:00+00:00",
        "event": "repeat",
        "condition": "is_checkout_up",
        "repeats": 2,
    },
    {
        "at": "2030-01-09T09:15:00+00:00",
        "event": "recovered",
        "condition": "is_checkout_up",
        "raised_at": "2030-01-09T08:00:00+00:00",
        "repeats": 2,
    },
    {
        "at": "2030-01-20T12:00:00+00:00",
        "event": "raised",
        "condition": "web_response_time",
        "repeats": 0,
    },
    {
        "at": "2030-01-20T12:05:00+00:00",
        "event": "raised",
        "condition": "canary_ok|web_response_time",
        "replaces": "web_response_time",
        "repeats": 0,
    },
    {
        "at": "2030-01-20T12:10:00+00:00",
        "event": "held",
        "condition": "canary_ok|web_response_time",
    },
    {
        "at": "2030-02-02T07:00:00+00:00",
        "event": "raised",
        "condition": "ga_active_users",
        "repeats": 0,
    },
]


@pytest.fixture
def fixture_history(tmp_path):
    path = tmp_path / "alert-history.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in FIXTURE))
    return path


def test_pages_a_month_count_every_message_sent(fixture_history):
    months = alert_history.summarise(alert_history.load(str(fixture_history))[0])
    assert months["2030-01"]["pages"] == 6
    assert months["2030-02"]["pages"] == 1


def test_time_to_clear_is_read_from_raised_to_recovered(fixture_history):
    months = alert_history.summarise(alert_history.load(str(fixture_history))[0])
    january = months["2030-01"]
    assert january["recovered"] == 2
    assert january["clear_minutes"] == [10.0, 75.0]
    assert january["replaced"] == 1


def test_cleared_before_its_first_repeat_is_counted_under_that_name(fixture_history):
    months = alert_history.summarise(alert_history.load(str(fixture_history))[0])
    assert months["2030-01"]["cleared_before_first_repeat"] == 1
    assert months["2030-02"]["recovered"] == 0


def test_the_report_names_what_it_counts_and_never_claims_more(
    fixture_history, capsys, monkeypatch
):
    monkeypatch.setenv("HB_ALERT_HISTORY", str(fixture_history))
    assert alert_history.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "2030-01" in out and "6 pages" in out
    assert "cleared before its first repeat: 1 of 2 recovered (50%)" in out
    assert "median time to clear 42 min" in out
    assert "1 replaced by a different condition" in out
    assert "2030-02" in out and "none recovered yet" in out
    assert "without action" not in out


def test_a_line_that_is_not_a_record_is_counted_and_skipped(tmp_path, capsys, monkeypatch):
    path = tmp_path / "alert-history.jsonl"
    path.write_text(
        json.dumps(FIXTURE[0]) + "\nnot json\n" + json.dumps({"event": "raised"}) + "\n"
    )
    monkeypatch.setenv("HB_ALERT_HISTORY", str(path))
    assert alert_history.main(["report"]) == 0
    assert "2 lines skipped" in capsys.readouterr().out


def test_no_history_yet_says_so(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HB_ALERT_HISTORY", str(tmp_path / "none.jsonl"))
    assert alert_history.main(["report"]) == 0
    assert "No alert history" in capsys.readouterr().out
