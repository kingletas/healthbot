"""Twilio: the SMS, and the client that sends it."""

from dataclasses import dataclass

from twilio.rest import Client

from healthbot.notifications.base import Message, Notifier


@dataclass
class TwilioMessage(Message):
    to: str = ""
    body: str = ""
    from_: str = ""


class TwilioNotifier(Notifier):
    def __init__(self, logger, account_sid: str, token: str) -> None:
        super().__init__(client=Client(account_sid, token), logger=logger)

    def send(self, message: TwilioMessage) -> str:
        """Sends the SMS and returns the Twilio message sid."""
        self.logger.debug(f"Sending {message.body} to {message.to}")
        sent = self.client.api.account.messages.create(
            body=message.body, from_=message.from_, to=message.to
        )
        return sent.sid
