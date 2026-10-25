"""
A run for a store HealthBot can only see from outside: the browser checkout
journey and the canary sweep, and nothing that needs AWS, New Relic or Google
Analytics. It is for a store with none of those, such as a showcase on one
machine.

It emits the same telemetry as the full run for the SLIs it can judge, and
only those: an SLI whose signal this run never collects gets no event, rather
than the bad event the full run gives a signal it failed to collect. It sends
no notifications; alerting on its SLIs is Prometheus and Alertmanager's job.
"""

# Standard library imports
import argparse
import sys

from healthbot import __version__, slo, telemetry
from healthbot.checks.canary import check_canary_urls
from healthbot.checks.site import validate_checkout
from healthbot.config_files import check_site_config, get_base_url, get_config
from healthbot.errors import ConfigurationError
from healthbot.logs import add_file_sink, logger

# The signals this run collects, and the SLIs that read only these.
SITE_SIGNALS = frozenset({"is_checkout_up", "canary_ok", "run_completed"})


def site_slos(slos: list) -> list:
    """The SLIs this run can judge: those whose signal it collects."""
    return [objective for objective in slos if objective["signal"] in SITE_SIGNALS]


def run_checks(site_config: dict) -> dict:
    with telemetry.check_span("checkout") as check:
        is_checkout_up = validate_checkout(
            base_url=get_base_url(), search_term=site_config.get("search_term")
        )
        if is_checkout_up is not True:
            check.set_status("fail")

    with telemetry.check_span("canary") as check:
        canary_ok = check_canary_urls()
        if not canary_ok:
            check.set_status("fail")

    return {"is_checkout_up": is_checkout_up, "canary_ok": canary_ok}


HELP = """\
Check that a customer can buy something, for a store seen only from outside.

One run walks the checkout in a real browser and sweeps the canary URLs, then
emits the checkout, canary and monitor SLIs as telemetry. It reads no AWS,
New Relic or Google Analytics, and it notifies nobody: alerts come from the
Prometheus rules on its SLIs.

A run exits 0 whether the store is up or down. A non-zero exit means
HealthBot itself broke, not that the store did.

Settings, all optional:
  HB_CONFIG_DIR     a directory holding this store's site.yml
  HB_LOG_LEVEL      DEBUG, INFO (the default), WARNING or ERROR
  HB_LOG_DIR        where the log and the failed-checkout evidence go
  HB_OTEL_ENABLED   1 to emit telemetry, with OTEL_EXPORTER_OTLP_ENDPOINT set
  HB_OTEL_INSTANCE_ID  who this monitor reports as, the hostname by default
"""


def parse_args(argv: list | None = None) -> None:
    """Answers --help and --version, and refuses anything else, before any check runs."""
    parser = argparse.ArgumentParser(
        prog="healthbot-site",
        description=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"healthbot {__version__}")
    parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    parse_args(argv)
    add_file_sink()
    telemetry.setup_telemetry()
    try:
        slos = site_slos(slo.load_slos())
        try:
            with telemetry.run_span():
                telemetry.record_slo_targets(slos)
                site_config = get_config("site.yml")
                check_site_config(site_config)
                signals = run_checks(site_config)
                telemetry.record_slo_events(
                    slo.evaluate_run(signals, run_completed=True, slos=slos)
                )
        except ConfigurationError as err:
            logger.error(str(err))
            telemetry.record_slo_events([("monitor_availability", False)])
            return 1
        except Exception as err:
            # A crashed run says nothing about the store: only the monitor SLI is charged.
            logger.exception(err)
            telemetry.record_slo_events([("monitor_availability", False)])
            return 1
        return 0
    finally:
        telemetry.shutdown_telemetry()


if __name__ == "__main__":
    sys.exit(main())
