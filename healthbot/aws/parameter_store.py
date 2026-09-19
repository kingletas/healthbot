# Third party imports
from botocore.exceptions import ClientError, NoCredentialsError

from healthbot.aws.client import AwsClient
from healthbot.cache import Cache

# Local imports
from healthbot.errors import ConfigurationError


class ParameterStore(AwsClient):
    service_code: str = "ssm"

    def __init__(self, aws_profile: str | None = None, cache: Cache | None = None) -> None:
        AwsClient.__init__(self, aws_profile=aws_profile)
        # Composed, not inherited: the old double inheritance declared its
        # bases in the opposite order to SecretsManager and hand-called
        # both __init__s, so the MRO was irrelevant and it worked by accident.
        self.cache = cache or Cache(db=1)

    def get_parameter(self, param: str, with_decryption=False, is_sensitive=False):
        # Cache plain configuration, never sensitive values. The old logic
        # was exactly inverted: it persisted only what was flagged sensitive
        # and re-fetched everything else on every run.
        cached = None if is_sensitive else self.cache.get(param)

        if cached is None:
            try:
                # Get the requested parameter
                response = self.client.get_parameters(Names=[param], WithDecryption=with_decryption)

            except NoCredentialsError as err:
                raise ConfigurationError(
                    "There are no AWS credentials, so the run settings can't be read. "
                    "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or point "
                    "AWS_ENDPOINT_URL at a local emulator."
                ) from err

            except ClientError as err:
                code = err.response.get("Error", {}).get("Code", "unknown")
                raise ConfigurationError(
                    f"AWS refused to read the setting {param} ({code}). "
                    "Check the run's IAM permissions and its region."
                ) from err

            # SSM does not raise for a name that does not exist. It returns
            # the name under InvalidParameters and no value for it.
            if param in response.get("InvalidParameters", []):
                raise ConfigurationError(
                    f"The setting {param} is not in AWS Parameter Store. "
                    "Create it, or point HB_PARAM_PREFIX at the prefix that holds yours."
                )

            cached = response["Parameters"][0]["Value"]
            if not is_sensitive:
                self.cache.set(param, cached)

        return cached
