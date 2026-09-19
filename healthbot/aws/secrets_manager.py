# Standard library imports
import base64
import json

# Third party imports
from botocore.exceptions import ClientError, NoCredentialsError

from healthbot.aws.client import AwsClient

# Local imports
from healthbot.errors import ConfigurationError

# What each botocore error code means for the person reading it, and what
# they do next. Anything not listed keeps its own code in the message.
SECRET_FIXES = {
    "ResourceNotFoundException": (
        "Create it, or correct the secret_name setting in Parameter Store."
    ),
    "AccessDeniedException": "Give the run's IAM role secretsmanager:GetSecretValue on it.",
    "DecryptionFailure": "Give the run's IAM role kms:Decrypt on the key that encrypts it.",
}


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
        except NoCredentialsError as err:
            raise ConfigurationError(
                f"There are no AWS credentials, so the secret {name} can't be read. "
                "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or point "
                "AWS_ENDPOINT_URL at a local emulator."
            ) from err
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "unknown")
            fix = SECRET_FIXES.get(code, f"AWS reported {code}.")
            raise ConfigurationError(
                f"AWS Secrets Manager can't give us the secret {name}. {fix}"
            ) from err

        return json.loads(secret)
