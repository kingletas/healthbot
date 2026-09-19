# Standard library imports
import asyncio
import time

# Third party imports
from aiohttp import ClientError, ClientSession, ClientTimeout
from requests import codes

# Local imports
from healthbot import telemetry
from healthbot.config_files import get_config, with_trailing_slash
from healthbot.errors import ConfigurationError
from healthbot.logs import logger

# A hung origin must not hang the run, because the timer fires again in five
# and the runs would stack.
REQUEST_TIMEOUT_SECONDS: int = 30

# Sentinel status for a request that never produced a response (DNS failure,
# connection refused, timeout). It is deliberately not a valid HTTP status so
# the all-200 check fails on it.
UNREACHABLE: int = 0


def get_cookies(config_path: str = "cookies.yml") -> dict:
    return get_config(config_path)


def get_headers(config_path: str = "headers.yml") -> dict:
    return {header.get("name"): header.get("value") for header in get_config(config_path)}


async def check_url(session, url: str) -> int:
    # The site being down arrives here as ClientError, not just TimeoutError:
    # both must fold into the result instead of aborting the whole run.
    try:
        async with session.get(url) as response:
            logger.debug(f"{response.status}: {url}")
            return response.status
    except (TimeoutError, ClientError) as err:
        logger.error(f"{url} unreachable: {err!r}")
        return UNREACHABLE


async def work() -> list:
    site_config = get_config("site.yml")
    base_url = with_trailing_slash(site_config.get("base_url"))
    canary_urls = site_config.get("canary_urls")

    if canary_urls is None:
        raise ConfigurationError(
            "site.yml has no canary_urls, so there is nothing to sweep. "
            "Add canary_urls with the paths to check, or rename an older "
            "ping_urls to canary_urls."
        )

    urls = [base_url + path.lstrip("/") for path in canary_urls]
    urls.insert(0, base_url)

    timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    session_args = {"cookies": get_cookies(), "headers": get_headers(), "timeout": timeout}
    async with ClientSession(**session_args) as session:
        statuses = await asyncio.gather(*(check_url(session, url) for url in urls))
        return list(zip(urls, statuses, strict=True))


def all_ok(statuses: list) -> bool:
    """
    Every URL answered 200. An empty result, the all-requests-failed case,
    is a failure, not a KeyError.
    """
    return len(statuses) > 0 and all(status == codes.ok for status in statuses)


def check_canary_urls() -> bool:
    start_time = time.time()
    results = asyncio.run(work())
    logger.debug("--- %s seconds ---" % (time.time() - start_time))

    telemetry.record_canary_statuses(results)
    return all_ok([status for _, status in results])
