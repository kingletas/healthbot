"""What every notification channel shares: the message it carries, and the sender."""

from typing import Any


class Message:
    """A payload one channel knows how to send. Subclasses declare the fields."""


class Notifier:
    """A channel that can deliver a Message. Subclasses supply their own client."""

    def __init__(self, logger: Any | None = None, client: Any | None = None) -> None:
        self.client = client
        self.logger = logger

    def send(self, message: Message) -> str | None:
        raise NotImplementedError
