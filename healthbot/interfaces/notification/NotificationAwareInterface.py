#!/usr/bin/env python3

# Local imports
from healthbot.notifications.NotificationMessage import NotificationMessage


class NotificationAwareInterface:
    def __init__(self, logger: any = None, client: any = None) -> None:
        self.client = client
        self.logger = logger

    def send(self, message: NotificationMessage) -> str:
        raise NotImplementedError
