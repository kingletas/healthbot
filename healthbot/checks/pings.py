#!/usr/bin/env python3

# Standard imports
import asyncio
import time

# Third party imports
from aiohttp import ClientError, ClientSession, ClientTimeout
from requests import codes

# Local import
from healthbot import telemetry
from healthbot.api.logs import logger
from healthbot.helper.UtilsHelper import get_config

# A hung origin must not hang the run — the timer fires again in five minutes
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
    # The site being down arrives here as ClientError, not just TimeoutError —
    # both must fold into the result instead of aborting the whole run.
    try:
        async with session.get(url) as response:
            logger.debug(f"{response.status}: {url}")
            return response.status
    except (TimeoutError, ClientError) as err:
        logger.error(f"{url} unreachable: {err!r}")
        return UNREACHABLE


async def work() -> list:
    base_url = get_config("site.yml").get("base_url")
    urls = [base_url + ping_url for ping_url in get_config("site.yml").get("ping_urls")]

    urls.insert(0, base_url)

    timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    session_args = {"cookies": get_cookies(), "headers": get_headers(), "timeout": timeout}
    async with ClientSession(**session_args) as session:
        statuses = await asyncio.gather(*(check_url(session, url) for url in urls))
        return list(zip(urls, statuses, strict=True))


def all_ok(statuses: list) -> bool:
    """
    Every URL answered 200. An empty result — the all-requests-failed case —
    is a failure, not a KeyError.
    """
    return len(statuses) > 0 and all(status == codes.ok for status in statuses)


def ping_site() -> bool:
    start_time = time.time()
    results = asyncio.run(work())
    logger.debug("--- %s seconds ---" % (time.time() - start_time))

    telemetry.record_probe_statuses(results)
    return all_ok([status for _, status in results])


if __name__ == "__main__":
    logger.debug("You called me directly :)")
