#!/usr/bin/env python3

# standard Imports
from dataclasses import dataclass

from jinja2 import Environment, FileSystemLoader

from healthbot import templates_d
from healthbot.notifications.NotificationMessage import NotificationMessage


@dataclass
class SlackMessage(NotificationMessage):
    def __init__(self, message_data: dict, channel: str, template_name: str = "slack.j2") -> None:
        super().__init__()

        self.loader = FileSystemLoader(templates_d)
        self.env = Environment(loader=self.loader)
        self.template_name = template_name
        self.channel = channel
        self.message = self.build_message(message_data)

    def build_message(self, message: dict) -> str:
        template = self.env.get_template(self.template_name)

        return template.render(message)
