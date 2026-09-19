"""
GA4 realtime active users.

Universal Analytics (analytics/v3, `rt:activeUsers`, a `ga:` view id) stopped
serving data in July 2023 and the API was withdrawn a year later. This reads
the GA4 Data API's runRealtimeReport instead, over REST through the discovery
client, so HB_GA_DISCOVERY_URL still redirects the whole call at a stand-in.
"""

# Third party imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Local imports
from healthbot.logs import logger
from healthbot.settings import get_settings

API_NAME = "analyticsdata"
API_VERSION = "v1beta"
ACTIVE_USERS_METRIC = "activeUsers"


class GaCheck:
    def __init__(
        self,
        json_secret: dict,
        scopes: list,
        api_name: str = API_NAME,
        api_version: str = API_VERSION,
    ) -> None:

        # google-auth replaces the long-deprecated oauth2client; same
        # service-account JSON, same scopes
        credentials = Credentials.from_service_account_info(json_secret, scopes=scopes)

        # HB_GA_DISCOVERY_URL redirects discovery at a stand-in. Static
        # discovery must be off with it, or the bundled document's rootUrl
        # would win and the override would silently do nothing. The token
        # endpoint needs no seam here, since google-auth takes it from token_uri
        # inside the service-account JSON.
        discovery_url = get_settings().ga_discovery_url
        build_args = {}
        if discovery_url:
            build_args = {"discoveryServiceUrl": discovery_url, "static_discovery": False}

        self.service = build(api_name, api_version, credentials=credentials, **build_args)

    def get_active_users(self, property_id: str) -> int | None:
        """
        Active users on the property right now, or None when it could not be read.

        None is the "cannot tell" signal the rest of the bot already
        understands: the alert fires on it and the SLO scores it bad. It is
        returned rather than raised so a Google outage costs this one metric
        instead of the whole run, which is how the New Relic and canary checks
        already behave.
        """
        if not property_id:
            logger.error("no GA4 property id configured; active users cannot be read")
            return None

        try:
            report = (
                self.service.properties()
                .runRealtimeReport(
                    property=as_property_path(property_id),
                    body={"metrics": [{"name": ACTIVE_USERS_METRIC}]},
                )
                .execute()
            )
        except Exception as err:
            logger.error(f"GA4 realtime report failed: {err!r}")
            return None

        return read_active_users(report)


def as_property_path(property_id: str) -> str:
    """The API wants `properties/123456`; a bare numeric id is accepted too."""
    property_id = str(property_id).strip()
    return property_id if property_id.startswith("properties/") else f"properties/{property_id}"


def read_active_users(report: dict) -> int | None:
    """
    The single total out of a runRealtimeReport with no dimensions.

    No rows means nobody is on the site, which is a real measurement of zero
    rather than a failure to measure, so it is 0. But a response with no rows
    *and* none of
    the report's own headers is not a realtime report at all, and answering 0
    to that would report an empty storefront as calmly as a real reading. The
    withdrawn Universal Analytics response looks exactly like this, so the
    distinction is the difference between noticing a regression and not.
    """
    rows = report.get("rows") or []
    if not rows:
        if "rowCount" not in report and "metricHeaders" not in report:
            logger.error(f"GA4 returned something that is not a realtime report: {report!r}")
            return None
        return 0

    values = rows[0].get("metricValues") or []
    if not values:
        logger.error(f"GA4 returned a row with no metric values: {report!r}")
        return None

    try:
        return int(values[0].get("value"))
    except (TypeError, ValueError):
        logger.error(f"GA4 returned a non-numeric active user count: {values[0]!r}")
        return None
