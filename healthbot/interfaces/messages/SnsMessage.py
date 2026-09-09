#!/usr/bin/env python3

# standard Imports
from dataclasses import dataclass

from healthbot.notifications.NotificationMessage import NotificationMessage


@dataclass
class SnsMessage(NotificationMessage):
    TopicArn: str = ""
    Message: str = ""
    Subject: str = ""
    MessageAttributes: dict = None
