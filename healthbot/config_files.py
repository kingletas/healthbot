# Standard library imports
from os import path

# Third party imports
import yaml

# Local imports
from healthbot import DEFAULT_ENV_TAG_SUFFIX, config_d
from healthbot.cache import Cache
from healthbot.errors import ConfigurationError
from healthbot.settings import get_settings

cache = Cache(db=0)


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
    # The cache key is the resolved path, not the bare filename. Otherwise a
    # run with HB_CONFIG_DIR set could be served the previous run's cached
    # copy of the other directory's file and the override would half-apply.
    file_config = resolve_config_file(config_path)
    cached = cache.get(file_config)

    if cached is None:
        with open(file_config) as fp:
            cached = yaml.safe_load(fp)
        cache.set(file_config, cached)

    return cached


def check_site_config(config: dict) -> None:
    """
    Refuses a site.yml that can't drive a run, before any check has started.

    Each message names the key and the edit. A run that only finds out halfway
    through has already spent a browser journey on it.
    """
    for key, was in (("base_url", None), ("canary_urls", "ping_urls")):
        if config.get(key) is not None:
            continue
        hint = (
            f"Rename {was} to {key}."
            if was and config.get(was) is not None
            else f"Add {key} to it."
        )
        raise ConfigurationError(f"site.yml has no {key}, so there is nothing to check. {hint}")


def with_trailing_slash(base_url: str) -> str:
    """
    The base URL with exactly one trailing slash.

    Callers join a path onto it by concatenation, so a base URL written
    without the slash aimed the canary sweep at https://store.example.comcheckout,
    which answers nothing and pages.
    """
    return f"{(base_url or '').rstrip('/')}/"


def get_base_url(config_path: str = "site.yml") -> str:
    config = get_config(config_path)
    return with_trailing_slash(config.get("base_url"))


def get_env_tag_suffix(config_path: str = "site.yml") -> str:
    """The suffix appended to the environment to form the EC2 tag:Environment value."""
    return get_config(config_path).get("environment_tag_suffix") or DEFAULT_ENV_TAG_SUFFIX


def get_header() -> str:
    return get_config("slack_messages.yml").get("header.message")
