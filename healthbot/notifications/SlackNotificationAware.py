#!/usr/bin/env python3

# Third party imports
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from healthbot.interfaces.notification.NotificationAwareInterface import (
    NotificationAwareInterface,
)

# Local imports
from healthbot.notifications.NotificationMessage import NotificationMessage
from healthbot.settings import get_settings


class SlackNotificationAware(NotificationAwareInterface):
    def __init__(self, logger, token: str) -> None:
        # HB_SLACK_API_URL points the client at a stand-in (IT/local's shim,
        # which relays chat.postMessage into Mattermost); unset means Slack.
        slack_api_url = get_settings().slack_api_url
        if slack_api_url:
            client = WebClient(token=token, base_url=slack_api_url)
        else:
            client = WebClient(token=token)
        super().__init__(client=client, logger=logger)

    def send(self, message: NotificationMessage) -> str:
        """
        Sends a slack notification
        """
        try:
            self.logger.debug(f"Sending {message.message}")
            response = self.client.chat_postMessage(channel=message.channel, blocks=message.message)
            assert response["ok"] is True

        except SlackApiError as e:
            assert e.response["ok"] is False
            assert e.response["error"]
            self.logger.error(f"Got an error: {e.response['error']}")
