"""
SLO definitions and per-run evaluation.

The four alert rules were always SLIs written as thresholds because there was
nowhere to record a measurement. This module turns one run's message data
into good/bad events per SLI; compliance and burn rates are computed by
Prometheus over the emitted counters.
"""

# Standard library imports
from functools import lru_cache
from os import path

# Third party imports
import yaml

# Local imports
from healthbot import config_d


@lru_cache(maxsize=1)
def load_slos(config_file: str | None = None) -> list:
    config_file = config_file or path.join(config_d, "slo.yml")
    with open(config_file) as fp:
        return yaml.safe_load(fp).get("slos")


def evaluate_run(message_data: dict, run_completed: bool, slos: list | None = None) -> list:
    """
    One (name, good) verdict per SLI for this run. A signal that could not be
    collected is a bad event, the same rule can_notify applies: "we cannot
    tell" never counts as good.
    """
    verdicts = []
    for slo in slos or load_slos():
        name = slo["name"]
        signal = slo["signal"]

        if signal == "run_completed":
            verdicts.append((name, bool(run_completed)))
            continue

        value = message_data.get(signal)
        if value is None:
            verdicts.append((name, False))
        elif slo["kind"] == "boolean":
            verdicts.append((name, value is True))
        else:  # below
            verdicts.append((name, float(value) < float(slo["threshold"])))

    return verdicts
