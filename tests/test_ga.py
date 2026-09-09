#!/usr/bin/env python3

"""
The GA4 realtime check: which service it builds, and how it reads the report.

Universal Analytics was withdrawn in July 2024, so the thing that matters most
here is that the check asks for analyticsdata/v1beta and nothing else — a
regression to analytics/v3 would pass every other test in the suite and return
nothing in production.
"""

# Third party imports
import pytest

# Local imports
import healthbot.checks.ga as ga


class FakeReport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def properties(self):
        return self

    def runRealtimeReport(self, property, body):  # noqa: N803 — the API's own parameter name
        self.calls.append({"property": property, "body": body})
        return self

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.response


def make_check(monkeypatch, service):
    monkeypatch.setattr(
        ga.Credentials, "from_service_account_info", classmethod(lambda cls, info, scopes: "creds")
    )
    monkeypatch.setattr(ga, "build", lambda *args, **kwargs: service)
    return ga.GaCheck(scopes=["s"], json_secret={})


def test_builds_the_ga4_data_api_not_universal_analytics(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        ga.Credentials, "from_service_account_info", classmethod(lambda cls, info, scopes: "creds")
    )
    monkeypatch.setattr(
        ga, "build", lambda name, version, **kw: captured.update(name=name, version=version)
    )

    ga.GaCheck(scopes=["s"], json_secret={})

    assert captured == {"name": "analyticsdata", "version": "v1beta"}


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("123456", "properties/123456"),
        ("properties/123456", "properties/123456"),
        ("  123456  ", "properties/123456"),
        (123456, "properties/123456"),
    ],
)
def test_property_path_accepts_either_form(given, expected):
    assert ga.as_property_path(given) == expected


def test_reads_the_count_and_asks_for_the_right_property(monkeypatch):
    service = FakeReport({"rows": [{"metricValues": [{"value": "137"}]}], "rowCount": 1})
    check = make_check(monkeypatch, service)

    assert check.get_active_users("123456") == 137
    assert service.calls[0]["property"] == "properties/123456"
    assert service.calls[0]["body"] == {"metrics": [{"name": "activeUsers"}]}


def test_no_rows_is_zero_users_not_a_failure_to_measure(monkeypatch):
    # Nobody on the site is a real reading. Returning None would page.
    check = make_check(monkeypatch, FakeReport({"rowCount": 0, "metricHeaders": []}))

    assert check.get_active_users("123456") == 0


def test_the_withdrawn_universal_analytics_shape_is_not_read_as_zero(monkeypatch):
    # The old API answered with a totals object and no rows. Reading that as
    # "0 active users" would report a regression as a quiet storefront.
    check = make_check(
        monkeypatch,
        FakeReport(
            {"kind": "analytics#realtimeData", "totalsForAllResults": {"rt:activeUsers": "137"}}
        ),
    )

    assert check.get_active_users("123456") is None


@pytest.mark.parametrize(
    "response",
    [
        {"rows": [{}]},
        {"rows": [{"metricValues": [{"value": "not a number"}]}]},
        {"rows": [{"metricValues": [{"value": None}]}]},
    ],
)
def test_an_unreadable_response_is_none(monkeypatch, response):
    check = make_check(monkeypatch, FakeReport(response))

    assert check.get_active_users("123456") is None


def test_an_api_error_costs_this_metric_and_not_the_run(monkeypatch):
    # The old code let the exception out of the check, so a Google outage
    # failed the whole run — checkout included.
    check = make_check(monkeypatch, FakeReport(error=RuntimeError("503")))

    assert check.get_active_users("123456") is None


def test_no_property_configured_is_none(monkeypatch):
    check = make_check(monkeypatch, FakeReport({"rows": []}))

    assert check.get_active_users(None) is None
    assert check.get_active_users("") is None
