#!/usr/bin/env python3

# standard Imports
from dataclasses import dataclass

from healthbot.notifications.NotificationMessage import NotificationMessage


@dataclass
class TwilioMessage(NotificationMessage):
    to: str = ""
    message: str = ""
    from_: str = ""
