#!/usr/bin/env python3

# Standard imports
from functools import lru_cache

# Local import
from healthbot.api.logs import logger
from healthbot.helper.UtilsHelper import get_config
from healthbot.interfaces.messages.SlackMessage import SlackMessage
from healthbot.interfaces.messages.SnsMessage import SnsMessage
from healthbot.interfaces.messages.TwilioMessage import TwilioMessage
from healthbot.notifications.SlackNotificationAware import SlackNotificationAware
from healthbot.notifications.SnsNotificationAware import SnsNotificationAware
from healthbot.notifications.TwilioNotificationAware import TwilioNotificationAware


@lru_cache(maxsize=1)
def alert_thresholds() -> dict:
    # Loaded lazily: reading site.yml goes through the Redis-backed config
    # cache, and doing it at import time meant the module could not even be
    # imported without a running Redis.
    site_config = get_config("site.yml")
    return {
        "alert_limit": int(site_config.get("alert_limit")),
        "web_response_alert": float(site_config.get("web_response_alert")),
        "app_response_alert": int(site_config.get("app_response_alert")),
    }


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
        or ga_active_users >= thresholds["alert_limit"]
        or float(app_response_time) >= thresholds["app_response_alert"]
        or float(web_response_time) >= thresholds["web_response_alert"]
    )


def send_notifications(secrets: dict, notifications: dict) -> None:
    """Sends whichever notifications the run asked for and has credentials for."""
    # SMS
    if "twilio_token" in secrets and notifications.get("send_sms"):
        message = TwilioMessage(
            to=secrets.get("twilio_to"),
            message=notifications.get("sms_message"),
            from_=secrets.get("twilio_from"),
        )

        twlio_mgr = TwilioNotificationAware(
            logger,
            account_sid=secrets.get("twilio_account"),
            token=secrets.get("twilio_token"),
        )
        twlio_mgr.send(message)

    # Slack
    if "slack_token" in secrets and notifications.get("send_slack"):
        slack_message = SlackMessage(
            message_data=notifications.get("message_data"),
            channel=secrets.get("slack_channel"),
        )

        slack_mgr = SlackNotificationAware(logger, token=secrets.get("slack_token"))
        slack_mgr.send(slack_message)

    # SNS
    if "topic_arn" in secrets and notifications.get("send_sns"):
        sns_message = SnsMessage(
            secrets.get("topic_arn"),
            Message=notifications.get("sns_message"),
            Subject=notifications.get("sns_subject"),
            MessageAttributes=notifications.get("sns_attributes"),
        )
        sns_mgr = SnsNotificationAware(logger, notifications.get("aws_profile"))

        sns_mgr.send(sns_message)


if __name__ == "__main__":
    logger.info("You called me directly :)")
