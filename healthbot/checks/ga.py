#!/usr/bin/env python3

# Third party imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Local import
from healthbot.api.logs import logger
from healthbot.settings import get_settings


class GaCheck:
    def __init__(self, api_name: str, api_version: str, scopes: list, json_secret: str) -> None:

        # google-auth replaces the long-deprecated oauth2client; same
        # service-account JSON, same scopes
        credentials = Credentials.from_service_account_info(json_secret, scopes=scopes)

        # HB_GA_DISCOVERY_URL redirects discovery at a stand-in. Static
        # discovery must be off with it, or the bundled document's rootUrl
        # would win and the override would silently do nothing. The token
        # endpoint needs no seam here — google-auth takes it from token_uri
        # inside the service-account JSON.
        discovery_url = get_settings().ga_discovery_url
        build_args = {}
        if discovery_url:
            build_args = {"discoveryServiceUrl": discovery_url, "static_discovery": False}

        # Build the service object.
        self.service = build(api_name, api_version, credentials=credentials, **build_args)

    def build_request_body(
        self, view_id: int, ranges: dict, metrics: list, dimensions: list, sorts: list
    ):
        body = {
            "reportRequests": [
                {
                    "viewId": view_id,
                    "dateRanges": [
                        {"startDate": range.startDate, "endDate": range.endDate} for range in ranges
                    ],
                    "metrics": [{"name": metric} for metric in metrics],
                    "dimensions": [{"name": dimension} for dimension in dimensions],
                    "orderBys": [
                        {"fieldName": sort.fieldName, "sortOrder": sort.sortOrder} for sort in sorts
                    ],
                }
            ]
        }
        return body

    def get_active_users(self, view_ids: str) -> int:

        results = (
            self.service.data()
            .realtime()
            .get(ids=view_ids, metrics="rt:activeUsers", dimensions="rt:medium")
            .execute()
        )

        return int(results.get("totalsForAllResults").get("rt:activeUsers"))


if __name__ == "__main__":
    logger.info("You called me directly :)")
