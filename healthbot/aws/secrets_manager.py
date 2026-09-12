# Standard library imports
import base64
import json

# Third party imports
from botocore.exceptions import ClientError

from healthbot.aws.client import AwsClient

# Local imports
from healthbot.logs import logger


class SecretsManager(AwsClient):
    service_code: str = "secretsmanager"

    def __init__(self, aws_profile: str | None = None) -> None:
        AwsClient.__init__(self, aws_profile=aws_profile)

    def get_secret(self, name: str) -> dict:
        # Fetched fresh on every run, on purpose. This used to cache the whole
        # decrypted blob, meaning Slack, Twilio, New Relic and the GA service
        # account, as plaintext JSON in Redis on a 60-minute TTL. The cache saved
        # milliseconds and bought a plaintext credential store on the host.
        try:
            secrets = self.client.get_secret_value(SecretId=name)
            # Decrypts secret using the associated KMS CMK.
            # Depending on whether the secret is a string or binary,
            # one of these fields will be populated.
            if "SecretString" in secrets:
                secret = secrets.get("SecretString")
            else:
                secret = base64.b64decode(secrets.get("SecretBinary"))
        except ClientError as e:
            logger.error(e)
            raise e

        return json.loads(secret)
