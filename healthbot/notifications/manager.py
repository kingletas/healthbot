# Standard library imports
from functools import lru_cache

from healthbot.config_files import get_config
from healthbot.errors import ConfigurationError

# Local imports
from healthbot.logs import logger
from healthbot.notifications.slack import SlackMessage, SlackNotifier
from healthbot.notifications.sns import SnsMessage, SnsNotifier
from healthbot.notifications.twilio import TwilioMessage, TwilioNotifier

# The three alert thresholds site.yml must carry, and how each is read. The
# old name is here so a site.yml written before the rename says what to edit
# rather than failing on a missing key.
THRESHOLDS = {
    "active_users_alert": (int, "alert_limit"),
    "web_response_alert": (float, None),
    "app_response_alert": (int, None),
}


@lru_cache(maxsize=1)
def alert_thresholds() -> dict:
    # Loaded lazily: reading site.yml goes through the Redis-backed config
    # cache, and doing it at import time meant the module could not even be
    # imported without a running Redis.
    site_config = get_config("site.yml")
    thresholds = {}

    for key, (cast, old_key) in THRESHOLDS.items():
        value = site_config.get(key)
        if value is None:
            hint = (
                f"Rename {old_key} to {key}."
                if old_key and site_config.get(old_key) is not None
                else f"Add {key} to it."
            )
            raise ConfigurationError(f"site.yml has no {key}, so nothing can page on it. {hint}")
        thresholds[key] = cast(value)

    return thresholds


def can_notify(current: dict) -> bool:
    """
    Checks if an alert should be triggered by the system.

    A signal that could not be collected (missing key or None) triggers the
    alert too: "we cannot tell whether the site is healthy" must page, not
    crash on float(None) or silently pass.
    """
    thresholds = alert_thresholds()

    ga_active_users = current.get("ga_active_users")
    app_response_time = current.get("app_response_time")
    web_response_time = current.get("web_response_time")

    missing = [
        name
        for name, value in (
            ("ga_active_users", ga_active_users),
            ("app_response_time", app_response_time),
            ("web_response_time", web_response_time),
        )
        if value is None
    ]
    if missing:
        logger.error(f"signals could not be collected, alerting: {', '.join(missing)}")
        return True

    return (
        current.get("is_checkout_up") is False
        or ga_active_users >= thresholds["active_users_alert"]
        or float(app_response_time) >= thresholds["app_response_alert"]
        or float(web_response_time) >= thresholds["web_response_alert"]
    )


def send_notifications(secrets: dict, notifications: dict) -> None:
    """Sends whichever notifications the run asked for and has credentials for."""
    # SMS
    if "twilio_token" in secrets and notifications.get("send_sms"):
        TwilioNotifier(
            logger,
            account_sid=secrets.get("twilio_account"),
            token=secrets.get("twilio_token"),
        ).send(
            TwilioMessage(
                to=secrets.get("twilio_to"),
                body=notifications.get("sms_message"),
                from_=secrets.get("twilio_from"),
            )
        )

    # Slack
    if "slack_token" in secrets and notifications.get("send_slack"):
        SlackNotifier(logger, token=secrets.get("slack_token")).send(
            SlackMessage(
                message_data=notifications.get("message_data"),
                channel=secrets.get("slack_channel"),
                failing_lines=notifications.get("failing_lines"),
            )
        )

    # SNS
    if "topic_arn" in secrets and notifications.get("send_sns"):
        # No profile: the deployed host uses its instance role, and a laptop
        # sets boto3's own AWS_PROFILE. The key this read was never set.
        SnsNotifier(logger).send(
            SnsMessage(
                topic_arn=secrets.get("topic_arn"),
                body=notifications.get("sns_message"),
                subject=notifications.get("sns_subject"),
                attributes=notifications.get("sns_attributes"),
            )
        )
