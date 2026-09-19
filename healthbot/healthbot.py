# Standard library imports
import argparse
import base64
import json
import sys

from healthbot import __version__, slo, telemetry
from healthbot.alerting import AlertGate, describe_failing, failing_signals
from healthbot.aws.parameter_store import ParameterStore
from healthbot.aws.secrets_manager import SecretsManager
from healthbot.checks.aws import get_metric_data
from healthbot.checks.canary import check_canary_urls
from healthbot.checks.ga import GaCheck

# Local imports
from healthbot.checks.nr import get_new_relic_data
from healthbot.checks.site import validate_checkout
from healthbot.config_files import check_site_config, get_base_url, get_config, get_header
from healthbot.errors import ConfigurationError
from healthbot.logs import logger
from healthbot.notifications.manager import alert_thresholds, send_notifications
from healthbot.settings import get_settings


def get_message_data(secrets: dict, hb_prefix: str, param_store, site_config: dict) -> dict:

    environment: str = param_store.get_parameter(f"{hb_prefix}environment")
    tag_name: str = param_store.get_parameter(f"{hb_prefix}tag_name")
    db_identifier: str = param_store.get_parameter(f"{hb_prefix}db_identifier")

    scope = site_config.get("ga_read_only_scope")

    ga_auth_secrets = json.loads(base64.b64decode(secrets.get("ga_auth_secrets")).decode("ascii"))

    with telemetry.check_span("new_relic") as check:
        new_relic_data = get_new_relic_data(
            secrets=secrets, name_filter=site_config.get("new_relic_app_filter") or None
        )
        if not new_relic_data:
            check.set_status("fail")

    with telemetry.check_span("aws_metrics"):
        aws_data = get_metric_data(
            tag_name=tag_name, environment=environment, db_cluster_identifier=db_identifier
        )

    with telemetry.check_span("google_analytics") as check:
        ga_data = {
            "ga_active_users": GaCheck(
                json_secret=ga_auth_secrets, scopes=[scope]
            ).get_active_users(property_id=secrets.get("ga_property_id"))
        }
        if ga_data["ga_active_users"] is None:
            check.set_status("fail")

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

    return {
        **ga_data,
        **aws_data,
        "header": get_header(),
        "is_checkout_up": is_checkout_up,
        "logo_url": site_config.get("logo_url"),
        "logo_alt": site_config.get("logo_alt"),
        "canary_ok": canary_ok,
        **new_relic_data,
    }


HELP = """\
Check whether a customer can buy something right now.

One run walks the checkout in a real browser, sweeps the canary URLs, reads
New Relic, Google Analytics and CloudWatch, and notifies if any of it is bad.
It takes no arguments: what it checks comes from site.yml, and where it looks
comes from AWS Parameter Store.

A healthy run says nothing and exits 0. A non-zero exit means HealthBot itself
broke, not that the store did.

Settings, all optional:
  HB_CONFIG_DIR     a directory of your own config files, packaged ones fill the gaps
  HB_PARAM_PREFIX   the Parameter Store prefix to read, when it is not site.yml's
  HB_LOG_LEVEL      DEBUG, INFO (the default), WARNING or ERROR
  HB_LOG_DIR        where the log and the failed-checkout evidence go
  HB_OTEL_ENABLED   1 to emit telemetry, with OTEL_EXPORTER_OTLP_ENDPOINT set
"""


def parse_args(argv: list | None = None) -> None:
    """Answers --help and --version, and refuses anything else, before any check runs."""
    parser = argparse.ArgumentParser(
        prog="healthbot",
        description=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"healthbot {__version__}")
    parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    # Arguments first, so --help and --version answer on a machine with no
    # credentials, no Redis and no network. This was the onboarding guide's
    # first command and it started a full production run.
    parse_args(argv)

    # This is the outermost boundary and the only place an exception is
    # allowed to die. It must exit non-zero: @logger.catch plus a bare except
    # meant a total import-or-run failure exited 0, and systemd recorded a
    # clean success every five minutes for a bot that never ran a check.
    telemetry.setup_telemetry()
    try:
        try:
            with telemetry.run_span():
                telemetry.record_slo_targets(slo.targets())

                site_config = get_config("site.yml")
                check_site_config(site_config)
                slo.report_threshold_drift(alert_thresholds())
                param_store = ParameterStore()
                hb_prefix: str = get_settings().param_prefix

                if hb_prefix is None:
                    hb_prefix = site_config.get("secrets_namespace_prefix")

                secret_name = param_store.get_parameter(f"{hb_prefix}secret_name")
                secrets = (SecretsManager()).get_secret(name=secret_name)
                message_data = get_message_data(
                    secrets=secrets,
                    param_store=param_store,
                    hb_prefix=hb_prefix,
                    site_config=site_config,
                )

                telemetry.record_business_metrics(message_data)
                telemetry.record_slo_events(slo.evaluate_run(message_data, run_completed=True))

                # The signals say this run is bad; the gate says whether
                # anybody needs telling again. A standing outage used to send
                # the same message every five minutes on all three channels.
                thresholds = alert_thresholds()
                failing = failing_signals(message_data, thresholds)
                speak = AlertGate().should_notify(failing)
                checkout_down = message_data.get("is_checkout_up") is False

                notification_data = {
                    "send_slack": speak,
                    "message_data": message_data,
                    # Why this alert fired, in the reader's words. The run
                    # already knows; it used to throw the answer away.
                    "failing_lines": describe_failing(failing, message_data, thresholds),
                    "send_sms": speak and checkout_down,
                    "sms_message": site_config.get("sms_alert_message"),
                    "send_sns": speak and checkout_down,
                    "sns_subject": message_data.get("header"),
                    "sns_message": site_config.get("sms_alert_message"),
                    "sns_attributes": {},
                }

                send_notifications(secrets=secrets, notifications=notification_data)
        except ConfigurationError as err:
            # Something the operator can fix, so its own message is the whole
            # report: one line, no traceback and no exception class name.
            logger.error(str(err))
            telemetry.record_slo_events([("monitor_availability", False)])
            return 1
        except Exception as err:
            logger.exception(err)
            # A crashed run says nothing about the site, so only the monitor
            # SLI takes the bad event, and the site SLIs get no event at all
            # rather than a fake one.
            telemetry.record_slo_events([("monitor_availability", False)])
            return 1

        return 0
    finally:
        telemetry.shutdown_telemetry()


if __name__ == "__main__":
    sys.exit(main())
