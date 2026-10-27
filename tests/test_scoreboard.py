"""The showcase scoreboard reads only what the tools write, and its weekly
snapshot is committed as the author it is given and as nobody else."""

# Standard library imports
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from healthbot import scoreboard

ROOT = Path(__file__).parent.parent
BOARD = ROOT / "IT/observability/grafana/dashboards/showcase-scoreboard.json"
AUTHOR = "Showcase snapshot <snapshot@example.test>"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)


def _board() -> dict:
    return json.loads(BOARD.read_text())


def test_every_series_the_scoreboard_reads_is_named_with_its_tool():
    assert scoreboard.unknown_series(_board()) == []


@pytest.mark.parametrize("name", sorted(scoreboard.SOURCES))
def test_each_named_source_file_writes_its_series(name):
    """The file a source names holds the series, as a recording rule or as the
    OTLP instrument Prometheus renames with underscores."""
    _tool, where = scoreboard.SOURCES[name]
    text = (ROOT / where).read_text()
    assert name in text or name.replace("_", ".") in text


def test_a_panel_reading_a_series_no_tool_writes_is_caught():
    board = {
        "panels": [{"title": "CPU", "targets": [{"expr": "rate(node_cpu_seconds_total[5m])"}]}]
    }
    assert scoreboard.unknown_series(board) == [("CPU", "node_cpu_seconds_total")]


@pytest.mark.parametrize(
    ("expr", "names"),
    [
        ('max(healthbot_dora_metric{metric="lead_time_seconds"})', {"healthbot_dora_metric"}),
        (
            "1 - (1 - slo:healthbot_compliance:ratio_30d) / on (slo) group_left (description)"
            " clamp_min(1 - max by (slo, description) (healthbot_slo_target), 0.0001)",
            {"slo:healthbot_compliance:ratio_30d", "healthbot_slo_target"},
        ),
        ("sum(rate(a_total[5m])) or vector(0)", {"a_total"}),
    ],
)
def test_series_in_reads_names_and_skips_functions_labels_and_keywords(expr, names):
    assert scoreboard.series_in(expr) == names


def test_every_panel_says_where_its_data_comes_from_or_that_it_waits():
    for panel in _board()["panels"]:
        assert panel.get("description"), panel["title"]
        if panel["type"] == "text":
            assert panel["options"]["content"].startswith("**Not built yet.**"), panel["title"]
        else:
            assert any(tool in panel["description"] for tool in ("HealthBot", "healthbot-")), panel[
                "title"
            ]


class _Grafana:
    """Stands in for Grafana's dashboard, query and annotation endpoints."""

    def __init__(self, value=0.97):
        self.value = value
        self.asked = []

    def get(self, url, params=None, timeout=None):
        self.asked.append(url)
        if url.endswith("/api/annotations"):
            # As Grafana answers when a person is logged in: who posted it, beside the deploy.
            return _Response(
                [
                    {
                        "id": 1,
                        "tags": ["deploy", "outcome:finished"],
                        "text": "Deploy r1",
                        "userId": 3,
                        "login": "someone",
                        "email": "someone@example.test",
                        "avatarUrl": "/avatar/0123abcd",
                    }
                ]
            )
        return _Response({"dashboard": _board()})

    def post(self, url, json=None, timeout=None):
        self.asked.append(url)
        return _Response(
            {
                "results": {
                    q["refId"]: {"frames": [{"values": [self.value]}]} for q in json["queries"]
                }
            }
        )


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository that reads none of this machine's git settings, so no global
    hook or identity takes part."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_a_snapshot_is_committed_as_its_author_and_committer(monkeypatch, repo):
    stand_in = _Grafana()
    monkeypatch.setattr(scoreboard.requests, "get", stand_in.get)
    monkeypatch.setattr(scoreboard.requests, "post", stand_in.post)
    written = scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=NOW)
    assert written == repo / "snapshots/scoreboard/2026-W09.json"
    assert _git(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>") == f"{AUTHOR}|{AUTHOR}"
    assert (
        _git(repo, "show", "--name-only", "--format=", "HEAD")
        == "snapshots/scoreboard/2026-W09.json"
    )


def test_a_snapshot_holds_the_dashboard_each_panels_data_and_the_weeks_deploys(monkeypatch, repo):
    stand_in = _Grafana()
    monkeypatch.setattr(scoreboard.requests, "get", stand_in.get)
    monkeypatch.setattr(scoreboard.requests, "post", stand_in.post)
    held = json.loads(
        scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=NOW).read_text()
    )
    assert held["dashboard"]["uid"] == "showcase-scoreboard"
    queried = {str(p["id"]) for p in _board()["panels"] if p.get("targets")}
    assert set(held["data"]) == queried
    assert held["deploys"] == [
        {"id": 1, "tags": ["deploy", "outcome:finished"], "text": "Deploy r1"}
    ]
    assert held["from"] == "2026-02-25T12:00:00+00:00"


def test_with_no_author_nothing_is_written_or_committed(monkeypatch, repo):
    stand_in = _Grafana()
    monkeypatch.setattr(scoreboard.requests, "get", stand_in.get)
    with pytest.raises(SystemExit, match="HB_SNAPSHOT_AUTHOR"):
        scoreboard.snapshot("http://grafana.test", str(repo), None, now=NOW)
    assert stand_in.asked == []
    assert not (repo / "snapshots").exists()


@pytest.mark.parametrize("author", ["Showcase snapshot", "<snapshot@example.test>", "a <b>", ""])
def test_an_author_that_is_not_name_and_email_is_refused(author):
    with pytest.raises(SystemExit):
        scoreboard.parse_author(author)


def test_the_same_week_unchanged_makes_no_second_commit(monkeypatch, repo):
    stand_in = _Grafana()
    monkeypatch.setattr(scoreboard.requests, "get", stand_in.get)
    monkeypatch.setattr(scoreboard.requests, "post", stand_in.post)
    scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=NOW)
    assert scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=NOW) is None
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


def test_a_monday_run_is_named_for_the_week_its_data_covers(monkeypatch, repo):
    stand_in = _Grafana()
    monkeypatch.setattr(scoreboard.requests, "get", stand_in.get)
    monkeypatch.setattr(scoreboard.requests, "post", stand_in.post)
    monday = datetime(2026, 3, 9, 7, 0, tzinfo=UTC)  # the first morning of week 11
    written = scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=monday)
    assert written.name == "2026-W10.json"


def test_a_later_run_in_the_same_week_replaces_that_weeks_file(monkeypatch, repo):
    monkeypatch.setattr(scoreboard.requests, "get", _Grafana().get)
    monkeypatch.setattr(scoreboard.requests, "post", _Grafana(0.97).post)
    scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=NOW)
    monkeypatch.setattr(scoreboard.requests, "post", _Grafana(0.95).post)
    scoreboard.snapshot("http://grafana.test", str(repo), AUTHOR, now=NOW)
    assert _git(repo, "rev-list", "--count", "HEAD") == "2"
    assert len(list((repo / "snapshots/scoreboard").iterdir())) == 1
