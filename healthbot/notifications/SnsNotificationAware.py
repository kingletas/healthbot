#!/usr/bin/env python3


# Third imports
from botocore.exceptions import ClientError

# Local imports
from healthbot.api.AwsAware import AwsAware
from healthbot.notifications.NotificationMessage import NotificationMessage

# message = SnsNotificationMessage("test", "test", "tes2t", {})

# print(*message)


class SnsNotificationAware(AwsAware):
    service_code: str = "sns"

    def __init__(self, logger, aws_profile: str = None) -> None:
        super().__init__(aws_profile=aws_profile)
        self.logger = logger

    def send(self, message: NotificationMessage) -> str:
        """
        Publishes a message to a topic.
        """
        try:
            self.logger.debug(f"Sending {message.Message}")
            response = self.client.publish(
                TopicArn=message.TopicArn,
                Message=message.Message,
                Subject=message.Subject,
                MessageAttributes=message.MessageAttributes,
            )["MessageId"]
        except ClientError as ex:
            self.logger.exception("Could not publish message to the topic.")
            raise ex
        else:
            return response
