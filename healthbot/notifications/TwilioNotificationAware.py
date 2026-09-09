#!/usr/bin/env python3

# Third Party imports
from twilio.rest import Client

# Local imports
from healthbot.interfaces.notification.NotificationAwareInterface import (
    NotificationAwareInterface,
)
from healthbot.notifications.NotificationMessage import NotificationMessage


class TwilioNotificationAware(NotificationAwareInterface):
    def __init__(self, logger, account_sid: str, token: str) -> None:
        client = Client(account_sid, token)
        super().__init__(client=client, logger=logger)

    def send(self, message: NotificationMessage) -> str:
        """
        Sends an SMS notification
        """

        self.logger.debug(f"Sending {message.message} to {message.to}")

        message = self.client.api.account.messages.create(
            body=message.message, from_=message.from_, to=message.to
        )

        return message.sid
