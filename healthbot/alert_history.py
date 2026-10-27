"""
Every decision the alert gate makes, kept after the gate has forgotten it.

The gate's own state is one Redis key that is deleted when an alert clears and
expires after a week, so nothing it holds can say how many pages went out last
month, how long they took to clear, or how many cleared before anybody could
have acted. This is the record that can: one JSON line appended per decision,
to HB_ALERT_HISTORY (default ~/.local/share/healthbot/alert-history.jsonl).

    raised      a condition sent for the first time, or a different one that
                replaced the last (named under `replaces`)
    repeat      the same condition sent again, its backoff due
    held        the same condition, held back until its next repeat is due
    clean       a clean run counted toward recovery
    recovered   the clean runs held, and the gate let the condition go

A run with nothing standing writes nothing, so a healthy month is a short file.

HealthBot never learns whether anybody acted on a page, so the report never
says "cleared without action". What it counts is an alert that recovered before
its first repeat was sent, under exactly that name: the pages nobody could have
acted on in time.

Nothing rebuilds this file. Back the path up, or point HB_ALERT_HISTORY at
something that is already backed up.

    healthbot-alert-history report      pages a month, time to clear, and how many
                                        cleared before their first repeat
"""

# Standard library imports
import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from os import makedirs, path

# Local imports
from healthbot.logs import add_file_sink, logger
from healthbot.settings import get_settings

EVENTS = ("raised", "repeat", "held", "clean", "recovered")
PAGES = ("raised", "repeat")


def history_file() -> str:
    return get_settings().alert_history


def stamp(when: float) -> str:
    """A run's clock as the record writes it: UTC, to the second."""
    return datetime.fromtimestamp(when, UTC).replace(microsecond=0).isoformat()


def append(record: dict, target: str | None = None) -> None:
    """One line, appended. A record that cannot be written is said and dropped:
    the history is for counting afterwards, and must never change what is sent."""
    target = target or history_file()
    try:
        makedirs(path.dirname(target) or ".", exist_ok=True)
        with open(target, "a") as fp:
            fp.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning(f"alerting: the alert history at {target} could not be written: {exc}")


def load(target: str) -> tuple[list[dict], int]:
    """The records in a history file, and how many lines were not records."""
    records, skipped = [], 0
    if not path.exists(target):
        return records, skipped
    with open(target) as fp:
        for line in fp:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                datetime.fromisoformat(record["at"])
                if record["event"] not in EVENTS or not isinstance(record.get("condition"), str):
                    raise ValueError(record["event"])
            except (ValueError, KeyError, TypeError):
                skipped += 1
                continue
            records.append(record)
    return records, skipped


def month_of(stamped: str) -> str:
    return stamped[:7]


def summarise(records: list[dict]) -> dict:
    """Per calendar month (UTC): pages sent, incidents recovered and how long each
    took, how many recovered before their first repeat, and how many were replaced
    by a different condition rather than cleared."""
    months: dict = {}

    def month(key: str) -> dict:
        return months.setdefault(
            key,
            {
                "pages": 0,
                "recovered": 0,
                "clear_minutes": [],
                "cleared_before_first_repeat": 0,
                "replaced": 0,
            },
        )

    for record in records:
        this = month(month_of(record["at"]))
        if record["event"] in PAGES:
            this["pages"] += 1
        if record["event"] == "raised" and record.get("replaces"):
            this["replaced"] += 1
        if record["event"] == "recovered":
            this["recovered"] += 1
            raised_at = record.get("raised_at")
            if raised_at:
                took = datetime.fromisoformat(record["at"]) - datetime.fromisoformat(raised_at)
                this["clear_minutes"].append(took.total_seconds() / 60)
            if record.get("repeats", 0) == 0:
                this["cleared_before_first_repeat"] += 1
    for this in months.values():
        this["clear_minutes"].sort()
    return dict(sorted(months.items()))


def counted(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def report(months: dict, skipped: int) -> str:
    if not months:
        return "No alert history yet: nothing has been sent or held since it was first kept."
    out = []
    for key, this in months.items():
        line = [f"{key}: {counted(this['pages'], 'page')}"]
        if this["recovered"]:
            before = this["cleared_before_first_repeat"]
            share = round(100 * before / this["recovered"])
            line.append(f"{this['recovered']} recovered")
            if this["clear_minutes"]:
                line.append(
                    f"median time to clear {statistics.median(this['clear_minutes']):.0f} min, "
                    f"longest {this['clear_minutes'][-1]:.0f} min"
                )
            recovered = this["recovered"]
            line.append(
                f"cleared before its first repeat: {before} of {recovered} recovered ({share}%)"
            )
        else:
            line.append("none recovered yet")
        if this["replaced"]:
            line.append(f"{this['replaced']} replaced by a different condition")
        out.append("; ".join(line))
    if skipped:
        out.append(f"{counted(skipped, 'line')} skipped: not records this tool wrote")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="healthbot-alert-history",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "report",
        help="pages a month, time to clear, and how many cleared before their first repeat",
    )
    parser.parse_args(argv)
    add_file_sink()

    records, skipped = load(history_file())
    print(report(summarise(records), skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
