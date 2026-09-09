#!/usr/bin/env python3

"""
The Slack alert, built as data and serialised once.

This used to be a Jinja template that emitted JSON by hand, which produced
invalid JSON for as long as it existed: a comma after the last field of the
metrics loop, and another after the last metric class. Building the blocks as
Python objects and calling json.dumps makes that whole class of bug
impossible rather than fixed.
"""

# Standard imports
import json
from dataclasses import dataclass

# Local imports
from healthbot.notifications.NotificationMessage import NotificationMessage

# What a metric reads as when the check could not collect it. The template
# rendered an empty string, so a missing New Relic response arrived as
# "*ms* Response time" — which reads as a measurement of nothing rather than
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
            "Checkout may be down",
        )
    )
    elements.append(
        status_line(
            bool(message_data.get("ping_ok")),
            "All configured URLs are running",
            "Some pings didn't complete",
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
        "text": mrkdwn("*User flow Stats*:"),
        "fields": [
            mrkdwn("Google Analytics: "),
            mrkdwn(f"{value_or_missing(message_data, 'ga_active_users')} active users"),
            mrkdwn("New Relic APM: "),
            mrkdwn(tier_summary(message_data, "app", "ms")),
            mrkdwn("New Relic Browser: "),
            mrkdwn(tier_summary(message_data, "web", "s")),
        ],
    }


def metric_blocks(aws_metrics: dict) -> list:
    blocks = []
    for class_key, metrics in (aws_metrics or {}).items():
        fields = []
        for metric, value in metrics.items():
            fields.append(mrkdwn(str(metric)))
            fields.append(mrkdwn(f"*{value}*"))
        blocks.append(
            {"type": "section", "text": mrkdwn(f"*{str(class_key).upper()}*:"), "fields": fields}
        )
    return blocks


def build_blocks(message_data: dict) -> list:
    """The whole alert, as Slack block-kit objects."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": str(message_data.get("header") or "HealthBot"),
                "emoji": True,
            },
        },
        context_block(message_data),
        user_flow_block(message_data),
        {"type": "section", "text": mrkdwn("*Nerd Stats*")},
        *metric_blocks(message_data.get("aws_metrics")),
    ]


@dataclass
class SlackMessage(NotificationMessage):
    def __init__(self, message_data: dict, channel: str) -> None:
        super().__init__()

        self.channel = channel
        self.blocks = build_blocks(message_data)
        self.message = json.dumps(self.blocks)
