"""SNS: the topic message, and the client that publishes it."""

from dataclasses import dataclass

from botocore.exceptions import ClientError

from healthbot.aws.client import AwsClient
from healthbot.notifications.base import Message


@dataclass
class SnsMessage(Message):
    topic_arn: str = ""
    body: str = ""
    subject: str = ""
    attributes: dict | None = None


class SnsNotifier(AwsClient):
    service_code: str = "sns"

    def __init__(self, logger, aws_profile: str | None = None) -> None:
        super().__init__(aws_profile=aws_profile)
        self.logger = logger

    def send(self, message: SnsMessage) -> str:
        """Publishes the message to its topic and returns the SNS message id."""
        try:
            self.logger.debug(f"Sending {message.body}")
            return self.client.publish(
                TopicArn=message.topic_arn,
                Message=message.body,
                Subject=message.subject,
                MessageAttributes=message.attributes,
            )["MessageId"]
        except ClientError:
            self.logger.exception("Could not publish message to the topic.")
            raise
