"""
SLO definitions and per-run evaluation.

The four alert rules were always SLIs written as thresholds because there was
nowhere to record a measurement. This module turns one run's message data
into good/bad events per SLI; compliance and burn rates are computed by
Prometheus over the emitted counters.
"""

# Standard library imports
from functools import lru_cache

# Third party imports
import yaml

# Local imports
from healthbot.alerting import SIGNALS
from healthbot.config_files import resolve_config_file
from healthbot.logs import logger


@lru_cache(maxsize=1)
def load_slos(config_file: str | None = None) -> list:
    # Resolved the way every other config file is, so HB_CONFIG_DIR reaches
    # slo.yml too. It used to join the packaged directory directly, which made
    # the objectives the one file an override could not touch.
    config_file = config_file or resolve_config_file("slo.yml")
    with open(config_file) as fp:
        return yaml.safe_load(fp).get("slos")


def report_threshold_drift(thresholds: dict, slos: list | None = None) -> list:
    """
    One line for each objective that disagrees with the alert guarding it.

    slo.yml deliberately restates site.yml's latency values, because an
    objective is a declared contract rather than whatever the alert config says
    this week. Nothing compared the two, so the drift that comment calls a
    decision to surface surfaced nowhere. Silent when they agree.
    """
    drifts = []
    for slo in slos or load_slos():
        signal = SIGNALS.get(slo.get("signal"))
        if signal is None or signal.limit_key is None or "threshold" not in slo:
            continue
        limit = thresholds.get(signal.limit_key)
        if limit is None or float(limit) == float(slo["threshold"]):
            continue
        drifts.append(
            f"{slo['name']} is measured against {slo['threshold']}{signal.unit} in slo.yml, "
            f"but the alert fires at {limit}{signal.unit} in site.yml. "
            "Change whichever one is wrong."
        )

    for drift in drifts:
        logger.warning(drift)
    return drifts


def targets(slos: list | None = None) -> dict:
    return {slo["name"]: slo["target"] for slo in (slos or load_slos())}


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
