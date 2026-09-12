# Third party imports
from botocore.exceptions import ClientError

from healthbot.aws.client import AwsClient
from healthbot.cache import Cache

# Local imports
from healthbot.logs import logger


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

            except ClientError as e:
                logger.error(e)
                raise e

            else:
                cached = response["Parameters"][0]["Value"]
                if not is_sensitive:
                    self.cache.set(param, cached)

        return cached
