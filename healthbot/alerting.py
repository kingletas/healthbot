"""
How often a standing alert is allowed to speak.

failing_signals decides what is bad this run. It says nothing about whether
anybody needs telling again, so an outage that lasts an afternoon sent the
same message every five minutes on Slack, SMS and SNS, around fifty of them,
unread after the fifth. The burn-rate rules in IT/observability already
back off; the path a person actually reads did not.

Three rules, and the second and third are what make the first safe:

  A repeat backs off. 15, 30 minutes, then hourly for as long as it lasts, so
  a long outage stays visible without becoming wallpaper. The first step is
  three timer intervals on purpose: a wait of one interval is not a backoff,
  it is the same message with extra arithmetic.

  A change in *what* is wrong always speaks. The state is keyed on the set of
  failing signals, so checkout going down during a traffic surge is a new
  alert and not a repeat of the old one.

  Recovery has to hold before it counts. A threshold sitting exactly on its
  limit flaps, and a backoff that resets on the first good run never engages;
  it just re-enters as a fresh escalation. Two consecutive clean runs clear it.
"""

# Standard library imports
import time
from collections.abc import Callable
from typing import NamedTuple

from healthbot.cache import Cache

# Local imports
from healthbot.logs import logger

# The alert state lives apart from the config cache (db 0) and the parameter
# cache (db 1), so flushing either cannot silence a page.
ALERT_STATE_DB: int = 2
STATE_KEY: str = "alert_state"

# Minutes between repeats of the same standing alert, then the last value
# forever. Four numbers a person can hold, and the first is longer than the
# timer's own interval or the gate would pass every run straight through.
BACKOFF_MINUTES: tuple = (0, 15, 30, 60)

# Clean runs required before a condition counts as recovered. One is not
# enough: a signal resting on its threshold clears and re-fires constantly,
# and every re-entry would read as a brand new incident.
RECOVERY_RUNS: int = 2

# Long enough to outlive any plausible outage, short enough that state from a
# forgotten incident cannot suppress a real one months later.
STATE_TTL_MINUTES: int = 60 * 24 * 7

# What a failing signal's name carries when the check collected nothing at all.
UNCOLLECTED_SUFFIX: str = ":uncollected"


class Signal(NamedTuple):
    """One thing that can page, and the words a reader gets told about it."""

    label: str
    unit: str
    limit_key: str | None
    failure: str
    is_failing: Callable

    def describe(self, value, thresholds: dict) -> str:
        """One line a person can act on: what is wrong, and what the limit was."""
        if value is None:
            return f"{self.label} couldn't be collected"
        if self.limit_key is None:
            return self.failure
        limit = thresholds.get(self.limit_key)
        return f"{self.label}: {value}{self.unit}, limit {limit}{self.unit}"


# What "bad" means, one entry per signal, beside the words a person reads for
# it. A tuple of names next to a chain of branches can drift: a name listed
# with no branch behind it never fails and nothing says so. One table cannot,
# and it is what makes the gate and the alert agree on what is wrong.
SIGNALS: dict = {
    "is_checkout_up": Signal(
        "Checkout",
        "",
        None,
        "Checkout didn't complete",
        lambda value, limits: value is False,
    ),
    "canary_ok": Signal(
        "Canary URLs",
        "",
        None,
        "A canary URL didn't answer 200",
        lambda value, limits: not value,
    ),
    "ga_active_users": Signal(
        "Active users",
        "",
        "active_users_alert",
        "",
        lambda value, limits: value >= limits["active_users_alert"],
    ),
    "app_response_time": Signal(
        "App response time",
        "ms",
        "app_response_alert",
        "",
        lambda value, limits: float(value) >= limits["app_response_alert"],
    ),
    "web_response_time": Signal(
        "Web response time",
        "s",
        "web_response_alert",
        "",
        lambda value, limits: float(value) >= limits["web_response_alert"],
    ),
}


def describe_failing(failing: tuple, message_data: dict, thresholds: dict) -> list:
    """
    Each failing signal as a line a person can act on, in the order given.

    The run already works out exactly why it is paging. This is what carries
    that into the message instead of leaving the reader to compare a table of
    numbers against a threshold file by eye.
    """
    lines = []
    for name in failing:
        signal_name = name.removesuffix(UNCOLLECTED_SUFFIX)
        signal = SIGNALS.get(signal_name)
        if signal is None:
            continue
        value = None if name.endswith(UNCOLLECTED_SUFFIX) else message_data.get(signal_name)
        lines.append(signal.describe(value, thresholds))
    return lines


def failing_signals(message_data: dict, thresholds: dict) -> tuple:
    """
    Which signals are bad this run, as a stable sorted tuple.

    A signal that could not be collected counts as failing under its own name,
    which is the project's rule everywhere, and it means a New Relic outage and a
    genuinely slow site are different conditions, so one does not suppress the
    other's first alert.
    """
    failing = []

    for name, signal in SIGNALS.items():
        value = message_data.get(name)
        if value is None:
            failing.append(f"{name}{UNCOLLECTED_SUFFIX}")
        elif signal.is_failing(value, thresholds):
            failing.append(name)

    return tuple(sorted(failing))


class AlertGate:
    """Decides whether a bad run is worth telling anybody about again."""

    def __init__(self, cache: Cache | None = None, now: float | None = None) -> None:
        self.cache = cache if cache is not None else Cache(db=ALERT_STATE_DB)
        self.now = now if now is not None else time.time()

    def read_state(self) -> dict:
        state = self.cache.get(STATE_KEY)
        return state if isinstance(state, dict) else {}

    def write_state(self, state: dict) -> None:
        self.cache.set(STATE_KEY, state, duration=STATE_TTL_MINUTES)

    def should_notify(self, failing: tuple) -> bool:
        """
        Whether to send. Recording the decision is part of making it, so this
        writes the new state before returning.

        Unreadable state means send. A suppressor that cannot remember must
        never suppress: the failure has to be a duplicate message, not a
        silent outage.
        """
        state = self.read_state()
        condition = "|".join(failing)

        if not failing:
            self.clear(state)
            return False

        if state.get("condition") != condition:
            logger.info(f"alerting: new condition {condition!r}")
            self.write_state(
                {"condition": condition, "sent_at": self.now, "repeats": 0, "clean_runs": 0}
            )
            return True

        due_in = BACKOFF_MINUTES[min(state.get("repeats", 0) + 1, len(BACKOFF_MINUTES) - 1)]
        elapsed_minutes = (self.now - state.get("sent_at", 0)) / 60

        if elapsed_minutes < due_in:
            logger.info(
                f"alerting: {condition!r} still failing, next repeat in "
                f"{due_in - elapsed_minutes:.0f} min"
            )
            # A run that stays bad resets the recovery count: the two clean
            # runs have to be consecutive or they prove nothing.
            state["clean_runs"] = 0
            self.write_state(state)
            return False

        state["sent_at"] = self.now
        state["repeats"] = state.get("repeats", 0) + 1
        state["clean_runs"] = 0
        self.write_state(state)
        logger.info(f"alerting: {condition!r} still failing, repeat {state['repeats']}")
        return True

    def clear(self, state: dict) -> None:
        if not state.get("condition"):
            return

        clean_runs = state.get("clean_runs", 0) + 1
        if clean_runs < RECOVERY_RUNS:
            logger.info(
                f"alerting: clean run {clean_runs} of {RECOVERY_RUNS} "
                f"before {state['condition']!r} counts as recovered"
            )
            state["clean_runs"] = clean_runs
            self.write_state(state)
            return

        logger.info(f"alerting: {state['condition']!r} recovered")
        self.cache.delete(STATE_KEY)
