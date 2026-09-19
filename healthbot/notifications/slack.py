"""
Slack: the alert as block-kit data, and the client that posts it.

The message used to be a Jinja template that emitted JSON by hand, which
produced invalid JSON for as long as it existed: a comma after the last field
of the metrics loop, and another after the last metric class. Building the
blocks as Python objects and calling json.dumps makes that whole class of bug
impossible rather than fixed.
"""

import json

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from healthbot.notifications.base import Message, Notifier
from healthbot.settings import get_settings

# What a metric reads as when the check could not collect it. The template
# rendered an empty string, so a missing New Relic response arrived as
# "*ms* Response time", which reads as a measurement of nothing rather than
# a failure to measure.
NOT_COLLECTED = "_not collected_"


def mrkdwn(text: str) -> dict:
    return {"type": "mrkdwn", "text": text}


def value_or_missing(message_data: dict, key: str, suffix: str = "") -> str:
    value = message_data.get(key)
    return NOT_COLLECTED if value is None else f"*{value}{suffix}*"


def status_line(ok: bool, up_text: str, down_text: str) -> dict:
    mark = ":white_check_mark:" if ok else ":small_red_triangle_down:"
    return mrkdwn(f"{mark} {up_text if ok else down_text}")


def context_block(message_data: dict) -> dict:
    elements = []

    logo_url = message_data.get("logo_url")
    if logo_url:
        elements.append(
            {
                "type": "image",
                "image_url": logo_url,
                "alt_text": message_data.get("logo_alt") or "",
            }
        )

    elements.append(
        status_line(
            message_data.get("is_checkout_up") is True,
            "Checkout is up and running.",
            "Checkout may be down.",
        )
    )
    elements.append(
        status_line(
            bool(message_data.get("canary_ok")),
            "Every canary URL answered 200.",
            "A canary URL didn't answer 200.",
        )
    )

    return {"type": "context", "elements": elements}


def tier_summary(message_data: dict, tier: str, unit: str) -> str:
    return "\n".join(
        [
            f"{value_or_missing(message_data, f'{tier}_response_time', unit)} Response time",
            f"{value_or_missing(message_data, f'{tier}_throughput')} Transactions",
            f"{value_or_missing(message_data, f'{tier}_apdex_score')} apdex score",
        ]
    )


def user_flow_block(message_data: dict) -> dict:
    return {
        "type": "section",
        "text": mrkdwn("*What customers are seeing*"),
        "fields": [
            mrkdwn("Active users (Google Analytics): "),
            mrkdwn(value_or_missing(message_data, "ga_active_users")),
            mrkdwn("App tier (New Relic APM): "),
            mrkdwn(tier_summary(message_data, "app", "ms")),
            mrkdwn("Web tier (New Relic Browser): "),
            mrkdwn(tier_summary(message_data, "web", "s")),
        ],
    }


def why_block(failing_lines: list) -> dict | None:
    """
    What is wrong, with each value beside its limit.

    Without it the reader gets a table of numbers and has to hold the
    thresholds in their head to work out which one tripped.
    """
    if not failing_lines:
        return None
    return {
        "type": "section",
        "text": mrkdwn(
            "*Why this alert fired*\n" + "\n".join(f"• {line}" for line in failing_lines)
        ),
    }


def metric_blocks(aws_metrics: dict, labels: dict | None = None) -> list:
    """
    One section per AWS source, headed by the name a person would recognise.

    The heading is the instance's Name tag, or metrics.yml's label for the
    namespace, or the instance id. An untagged instance used to put the
    sentence "NAME TAG NOT ASSIGNED" in the message as if it were a heading.
    """
    labels = labels or {}
    blocks = []
    for class_key, metrics in (aws_metrics or {}).items():
        fields = []
        for metric, value in metrics.items():
            fields.append(mrkdwn(str(metric)))
            fields.append(mrkdwn(f"*{value}*"))
        heading = labels.get(class_key) or str(class_key)
        blocks.append({"type": "section", "text": mrkdwn(f"*{heading}*"), "fields": fields})
    return blocks


def summary_text(message_data: dict, failing_lines: list | None = None) -> str:
    """
    The one line that reaches a push notification and a screen reader.

    Slack renders blocks and nothing else, so an alert sent with blocks alone
    arrives on a locked phone as the bot's name and no content, which is the
    moment an alert most needs to say something. It says what is wrong, for
    every signal that can page, because an alert that reports success is worse
    than one that reports nothing.
    """
    header = str(message_data.get("header") or "HealthBot")
    if not failing_lines:
        return f"{header}: nothing is failing"
    return f"{header}: {'; '.join(failing_lines)}"


def build_blocks(message_data: dict, failing_lines: list | None = None) -> list:
    """The whole alert, as Slack block-kit objects."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": str(message_data.get("header") or "HealthBot"),
                "emoji": True,
            },
        },
        context_block(message_data),
    ]
    why = why_block(failing_lines or [])
    if why:
        blocks.append(why)
    blocks.append(user_flow_block(message_data))
    blocks.append({"type": "section", "text": mrkdwn("*Infrastructure*")})
    blocks.extend(metric_blocks(message_data.get("aws_metrics"), message_data.get("metric_labels")))
    return blocks


class SlackMessage(Message):
    def __init__(self, message_data: dict, channel: str, failing_lines: list | None = None) -> None:
        self.channel = channel
        self.blocks = build_blocks(message_data, failing_lines)
        self.message = json.dumps(self.blocks)
        self.text = summary_text(message_data, failing_lines)


class SlackNotifier(Notifier):
    def __init__(self, logger, token: str) -> None:
        # HB_SLACK_API_URL points the client at a stand-in (IT/local's shim,
        # which relays chat.postMessage into Mattermost); unset means Slack.
        slack_api_url = get_settings().slack_api_url
        if slack_api_url:
            client = WebClient(token=token, base_url=slack_api_url)
        else:
            client = WebClient(token=token)
        super().__init__(client=client, logger=logger)

    def send(self, message: Message) -> None:
        """Posts the alert to the configured channel."""
        self.logger.debug(f"Sending {message.message}")
        try:
            self.client.chat_postMessage(
                channel=message.channel, blocks=message.message, text=message.text
            )
        except SlackApiError as err:
            # Slack refusing one message is not worth taking the run down:
            # the run's own exit status already reports the site, and the
            # other channels still have their turn.
            self.logger.error(f"Slack refused the message: {err.response['error']}")
