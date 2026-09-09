#!/usr/bin/env python3

# Third Party imports
from botocore.exceptions import ClientError

from healthbot.api.AwsAware import AwsAware

# Local import
from healthbot.api.logs import logger
from healthbot.helper.CacheAwareHelper import CacheAwareHelper


class ParameterStoreAwareHelper(AwsAware):
    service_code: str = "ssm"

    def __init__(self, aws_profile: str = None, cache: CacheAwareHelper = None) -> None:
        AwsAware.__init__(self, aws_profile=aws_profile)
        # Composed, not inherited: the old double inheritance declared its
        # bases in the opposite order to SecretsAwareHelper and hand-called
        # both __init__s, so the MRO was irrelevant and it worked by accident.
        self.cache = cache or CacheAwareHelper(db=1)

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
                    self.cache.save(param, cached)

        return cached
