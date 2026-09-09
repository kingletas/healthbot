#!/usr/bin/env python3

# Standard Library imports
import base64
import json
import sys

from healthbot import slo, telemetry
from healthbot.api.logs import logger
from healthbot.checks.aws import get_metric_data
from healthbot.checks.ga import GaCheck

# Local Imports
from healthbot.checks.nr import get_new_relic_data
from healthbot.checks.pings import ping_site
from healthbot.checks.site import validate_checkout
from healthbot.helper.ParameterStoreAwareHelper import ParameterStoreAwareHelper
from healthbot.helper.SecretsAwareHelper import SecretsAwareHelper
from healthbot.helper.UtilsHelper import get_base_url, get_config, get_header
from healthbot.notifications.NotificationManager import can_notify, send_notifications
from healthbot.settings import get_settings


def get_message_data(secrets: dict, hb_prefix: str, param_store, site_config: dict) -> dict:

    environment: str = param_store.getParameter(f"{hb_prefix}environment")
    tag_name: str = param_store.getParameter(f"{hb_prefix}tag_name")
    db_identifier: str = param_store.getParameter(f"{hb_prefix}db_identifier")

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

    with telemetry.check_span("google_analytics"):
        ga_data = {
            "ga_active_users": (
                GaCheck(
                    json_secret=ga_auth_secrets,
                    api_name="analytics",
                    api_version="v3",
                    scopes=[scope],
                )
            ).get_active_users(view_ids=secrets.get("view_ids"))
        }

    with telemetry.check_span("checkout") as check:
        is_checkout_up = validate_checkout(
            base_url=get_base_url(), search_term=site_config.get("search_term")
        )
        if is_checkout_up is not True:
            check.set_status("fail")

    with telemetry.check_span("pings") as check:
        ping_ok = ping_site()
        if not ping_ok:
            check.set_status("fail")

    return {
        **ga_data,
        **aws_data,
        "header": get_header(),
        "is_checkout_up": is_checkout_up,
        "logo_url": site_config.get("logo_url"),
        "logo_alt": site_config.get("logo_alt"),
        "ping_ok": ping_ok,
        **new_relic_data,
    }


def main() -> int:
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
                param_store = ParameterStoreAwareHelper()
                hb_prefix: str = get_settings().param_prefix

                if hb_prefix is None:
                    hb_prefix = site_config.get("secrets_namespace_prefix")

                secret_name = param_store.getParameter(f"{hb_prefix}secret_name")
                secrets = (SecretsAwareHelper()).get_secret(name=secret_name)
                message_data = get_message_data(
                    secrets=secrets,
                    param_store=param_store,
                    hb_prefix=hb_prefix,
                    site_config=site_config,
                )

                telemetry.record_business_metrics(message_data)
                telemetry.record_slo_events(slo.evaluate_run(message_data, run_completed=True))

                notification_data = {
                    "send_slack": can_notify(message_data),
                    "message_data": message_data,
                    "send_sms": (message_data.get("is_checkout_up") is False),
                    "sms_message": site_config.get("sms_alert_message"),
                    "send_sns": (message_data.get("is_checkout_up") is False),
                    "sns_subject": message_data.get("header"),
                    "sns_message": site_config.get("sms_alert_message"),
                    "sns_attributes": {},
                }

                send_notifications(secrets=secrets, notifications=notification_data)
        except Exception as err:
            logger.exception(err)
            # A crashed run says nothing about the site, so only the monitor
            # SLI takes the bad event — the site SLIs get no event at all
            # rather than a fake one.
            telemetry.record_slo_events([("monitor_availability", False)])
            return 1

        return 0
    finally:
        telemetry.shutdown_telemetry()


if __name__ == "__main__":
    sys.exit(main())
