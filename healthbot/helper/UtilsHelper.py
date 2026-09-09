#!/usr/bin/env python3

# Standard imports
from os import path

# Third party imports
import yaml

# Local imports
from healthbot import DEFAULT_ENV_TAG_SUFFIX, config_d
from healthbot.api.logs import logger
from healthbot.helper.CacheAwareHelper import CacheAwareHelper
from healthbot.settings import get_settings

cache = CacheAwareHelper(db=0)


def resolve_config_file(config_path: str) -> str:
    """
    HB_CONFIG_DIR wins when it holds the file; anything it does not carry
    falls back to the packaged config, so a local override directory only
    needs the files whose values differ (site.yml, mostly).
    """
    override_dir = get_settings().config_dir
    if override_dir:
        candidate = path.join(override_dir, config_path)
        if path.exists(candidate):
            return candidate
    return path.join(config_d, config_path)


def get_config(config_path: str):
    """
    Get and parse the configuration file
    """
    # The cache key is the resolved path, not the bare filename — otherwise a
    # run with HB_CONFIG_DIR set could be served the previous run's cached
    # copy of the other directory's file and the override would half-apply.
    file_config = resolve_config_file(config_path)
    cached = cache.get(file_config)

    if cached is None:
        with open(file_config) as fp:
            cached = yaml.safe_load(fp)
        cache.save(file_config, cached)

    return cached


def get_base_url(config_path: str = "site.yml") -> str:
    config = get_config(config_path)
    return config.get("base_url")


def get_env_tag_suffix(config_path: str = "site.yml") -> str:
    """The suffix appended to the environment to form the EC2 tag:Environment value."""
    return get_config(config_path).get("environment_tag_suffix") or DEFAULT_ENV_TAG_SUFFIX


def get_header() -> str:
    return get_config("slack_messages.yml").get("header.message")


if __name__ == "__main__":
    logger.info("You called me directly :)")
