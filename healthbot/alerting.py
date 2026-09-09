#!/usr/bin/env python3

"""
How often a standing alert is allowed to speak.

can_notify decides whether this run is bad. It says nothing about whether
anybody needs telling again, so an outage that lasts an afternoon sent the
same message every five minutes on Slack, SMS and SNS — around fifty of them,
and unread after the fifth. The burn-rate rules in IT/observability already
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
  limit flaps, and a backoff that resets on the first good run never engages —
  it just re-enters as a fresh escalation. Two consecutive clean runs clear it.
"""

# Standard imports
import time

# Local imports
from healthbot.api.logs import logger
from healthbot.helper.CacheAwareHelper import CacheAwareHelper

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

FAILURE_SIGNALS: tuple = (
    "is_checkout_up",
    "ping_ok",
    "ga_active_users",
    "app_response_time",
    "web_response_time",
)


def failing_signals(message_data: dict, thresholds: dict) -> tuple:
    """
    Which signals are bad this run, as a stable sorted tuple.

    A signal that could not be collected counts as failing under its own name,
    the same rule can_notify applies — and it means a New Relic outage and a
    genuinely slow site are different conditions, so one does not suppress the
    other's first alert.
    """
    failing = []

    for name in FAILURE_SIGNALS:
        value = message_data.get(name)
        if value is None:
            failing.append(f"{name}:uncollected")
            continue

        if name == "is_checkout_up" and value is False:
            failing.append(name)
        elif name == "ping_ok" and not value:
            failing.append(name)
        elif name == "ga_active_users" and value >= thresholds["alert_limit"]:
            failing.append(name)
        elif name == "app_response_time" and float(value) >= thresholds["app_response_alert"]:
            failing.append(name)
        elif name == "web_response_time" and float(value) >= thresholds["web_response_alert"]:
            failing.append(name)

    return tuple(sorted(failing))


class AlertGate:
    """Decides whether a bad run is worth telling anybody about again."""

    def __init__(self, cache: CacheAwareHelper = None, now: float = None) -> None:
        self.cache = cache if cache is not None else CacheAwareHelper(db=ALERT_STATE_DB)
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
        never suppress — the failure has to be a duplicate message, not a
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
