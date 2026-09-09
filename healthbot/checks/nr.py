#!/usr/bin/env python3

# Third party imports

from newrelic_api import Applications

# Local import
from healthbot.api.logs import logger
from healthbot.settings import get_settings


def get_newrelic_status(
    api_key: str = None, summary: str = "end_user_summary", name_filter: str = None
):
    # A failed lookup is logged and returned as an explicit empty dict; the
    # caller decides what a missing summary means. Swallowing it silently is
    # how a dead API key looked like a healthy site for years.
    try:
        app = get_newrelic_app(api_key=api_key, name_filter=name_filter).get("applications")[0]
        return {"id": app.get("id"), "summary": app.get(summary)}

    except Exception as err:
        logger.error(f"New Relic {summary} lookup failed: {err!r}")
        return {}


def get_newrelic_app(api_key: str = None, name_filter: str = None) -> Applications:
    # Unset lists every application the key can see and the caller takes the
    # first, which is only right for an account with one; site.yml's
    # new_relic_app_filter names it where there are more.
    app = Applications(api_key)
    # HB_NR_API_URL points the client at a stand-in (IT/local's stub). URL is
    # a plain class attribute on newrelic_api's Resource, so an instance
    # override is the whole seam; unset means the real API, unchanged.
    nr_api_url = get_settings().nr_api_url
    if nr_api_url:
        app.URL = nr_api_url if nr_api_url.endswith("/") else f"{nr_api_url}/"
    return app.list(filter_name=name_filter)


def get_new_relic_data(secrets: dict, name_filter: str = None) -> dict:

    result = {}

    for summary, message_key in {
        "application_summary": "app",
        "end_user_summary": "web",
    }.items():
        data = get_newrelic_status(
            api_key=secrets.get("new_relic_api"),
            summary=summary,
            name_filter=name_filter,
        )
        # summary can be missing (lookup failed) or None (app exists but the
        # summary has no data yet) — either way there is nothing to merge, and
        # can_notify treats the absent keys as "could not check".
        summary_data = data.get("summary")
        if not summary_data:
            logger.error(f"New Relic returned no {summary}; metrics for '{message_key}' omitted")
            continue
        for key, item in summary_data.items():
            result.update({f"{message_key}_{key}": item})

    return result


if __name__ == "__main__":
    logger.info("You called me directly :)")
