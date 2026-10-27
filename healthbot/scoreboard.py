"""
The showcase scoreboard: one Grafana dashboard fed only by series the tools
already write, and a weekly snapshot of it committed to the showcase repository.

SOURCES names every series the dashboard may read, the tool that writes it and
the file where it is written, so a panel that reads anything else is caught by
`unknown_series` before it ships. A panel whose source is not built yet is a
text panel that says so.

`healthbot-scoreboard snapshot` asks Grafana for the dashboard, each panel's
data over the last seven days and the deploy annotations in them, writes them to
snapshots/scoreboard/YYYY-Www.json in the repository HB_SNAPSHOT_REPO names,
named for the ISO week the seven days start in, and commits that one file as
HB_SNAPSHOT_AUTHOR. With no author set it commits
nothing: who signs a commit nobody typed is a decision, not a default.
"""

# Standard library imports
import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Third party imports
import requests

# Local application imports
from healthbot.logs import add_file_sink
from healthbot.settings import get_settings

UID = "showcase-scoreboard"
WINDOW = timedelta(days=7)
SNAPSHOTS = Path("snapshots") / "scoreboard"

# Each series the scoreboard may read: the tool that writes it, and the file,
# relative to this repository, where its name is written.
SOURCES = {
    "slo:healthbot_compliance:ratio_30d": (
        "HealthBot",
        "IT/observability/prometheus/rules/slo.yml",
    ),
    "healthbot_slo_target": ("HealthBot", "healthbot/telemetry.py"),
    "healthbot_dora_metric": ("healthbot-dora", "healthbot/telemetry.py"),
}

# PromQL words that are not series: operators, modifiers, and what follows by,
# on, without, ignoring and group_left/group_right, which are label names.
_KEYWORDS = {
    "and",
    "or",
    "unless",
    "bool",
    "offset",
    "by",
    "without",
    "on",
    "ignoring",
    "group_left",
    "group_right",
}
_LABEL_LISTS = re.compile(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)")
_MATCHERS = re.compile(r"\{[^}]*\}")
_RANGES = re.compile(r"\[[^\]]*\]")
_STRINGS = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")
_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")


def series_in(expr: str) -> set[str]:
    """The series names a PromQL expression reads."""
    text = _STRINGS.sub(" ", expr)
    text = _MATCHERS.sub(" ", text)
    text = _RANGES.sub(" ", text)
    text = _LABEL_LISTS.sub(" ", text)
    names = set()
    for found in _NAME.finditer(text):
        name, after = found.group(), text[found.end() :].lstrip()[:1]
        if after == "(" or name in _KEYWORDS:
            continue
        names.add(name)
    return names


def unknown_series(dashboard: dict) -> list[tuple[str, str]]:
    """(panel title, series) for each series a panel reads that SOURCES does not name."""
    unknown = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            for name in sorted(series_in(target.get("expr", ""))):
                if name not in SOURCES:
                    unknown.append((panel.get("title", ""), name))
    return unknown


def parse_author(author: str | None) -> tuple[str, str]:
    """('Name', 'email') from 'Name <email>', or SystemExit naming what is missing."""
    found = re.fullmatch(r"\s*([^<>]+?)\s*<([^<>\s]+@[^<>\s]+)>\s*", author or "")
    if not found:
        raise SystemExit(
            "healthbot-scoreboard: set HB_SNAPSHOT_AUTHOR to 'Name <email>'; "
            "a snapshot is committed as that author and as nobody else"
        )
    return found.group(1), found.group(2)


def gather(grafana: str, now: datetime) -> dict:
    """The dashboard, each panel's data over the window and the deploys in it."""
    start, end = now - WINDOW, now
    board = requests.get(f"{grafana}/api/dashboards/uid/{UID}", timeout=30)
    board.raise_for_status()
    dashboard = board.json()["dashboard"]
    data = {}
    for panel in dashboard.get("panels", []):
        queries = [
            {
                "refId": t.get("refId", "A"),
                "datasource": t.get("datasource"),
                "expr": t["expr"],
                "maxDataPoints": 500,
                "intervalMs": 3_600_000,
            }
            for t in panel.get("targets", [])
            if t.get("expr")
        ]
        if not queries:
            continue
        answer = requests.post(
            f"{grafana}/api/ds/query",
            json={
                "from": str(int(start.timestamp() * 1000)),
                "to": str(int(end.timestamp() * 1000)),
                "queries": queries,
            },
            timeout=60,
        )
        answer.raise_for_status()
        data[str(panel.get("id"))] = answer.json()
    held = requests.get(
        f"{grafana}/api/annotations",
        params={
            "tags": "deploy",
            "from": int(start.timestamp() * 1000),
            "to": int(end.timestamp() * 1000),
            "limit": 1000,
        },
        timeout=30,
    )
    held.raise_for_status()
    return {
        "taken": now.isoformat(),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "dashboard": dashboard,
        "data": data,
        "deploys": held.json(),
    }


def snapshot(
    grafana: str, repo: str, author: str | None, now: datetime | None = None
) -> Path | None:
    """Writes and commits the snapshot of the seven days before NOW, named for
    the ISO week those days start in. Returns its path, or None when
    the week's file already held exactly this."""
    name, email = parse_author(author)
    now = now or datetime.now(UTC)
    # Run on a Monday, the window is the whole of the week before, and the file
    # carries that week's name rather than the one just begun.
    year, week, _ = (now - WINDOW).isocalendar()
    relative = SNAPSHOTS / f"{year}-W{week:02d}.json"
    target = Path(repo) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(gather(grafana, now), indent=2, sort_keys=True) + "\n")
    git = ["git", "-C", repo]
    subprocess.run([*git, "add", "--", str(relative)], check=True)
    if subprocess.run([*git, "diff", "--cached", "--quiet", "--", str(relative)]).returncode == 0:
        return None
    subprocess.run(
        [
            *git,
            "-c",
            f"user.name={name}",
            "-c",
            f"user.email={email}",
            "commit",
            "-q",
            "-m",
            f"Scoreboard snapshot, {year} week {week:02d}",
            "--",
            str(relative),
        ],
        check=True,
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(prog="healthbot-scoreboard", description=__doc__)
    parser.add_argument("command", choices=["snapshot"])
    parser.add_argument("--repo", help="the showcase repository (default HB_SNAPSHOT_REPO)")
    args = parser.parse_args()
    add_file_sink()

    settings = get_settings()
    repo = args.repo or settings.snapshot_repo
    if not repo or not (Path(repo) / ".git").exists():
        print(
            "healthbot-scoreboard: name a git checkout with --repo or HB_SNAPSHOT_REPO",
            file=sys.stderr,
        )
        return 2
    written = snapshot(settings.grafana_url, repo, settings.snapshot_author)
    print(
        f"committed {written}" if written else "this week's snapshot is already committed as it is"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
