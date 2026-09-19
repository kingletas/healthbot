#!/usr/bin/env python3
"""The settings and messages a person reads, checked as strings rather than shapes."""

import pytest

from healthbot import slo
from healthbot.config_files import check_site_config, with_trailing_slash
from healthbot.errors import ConfigurationError
from healthbot.healthbot import parse_args
from healthbot.notifications import manager

SLOS = [
    {"name": "web_latency", "signal": "web_response_time", "kind": "below", "threshold": 3.5},
    {"name": "app_latency", "signal": "app_response_time", "kind": "below", "threshold": 800},
    {"name": "canary_availability", "signal": "canary_ok", "kind": "boolean"},
]


@pytest.mark.parametrize(
    "written,expected",
    [
        ("https://store.example.com", "https://store.example.com/"),
        ("https://store.example.com/", "https://store.example.com/"),
        ("https://store.example.com//", "https://store.example.com/"),
    ],
)
def test_a_base_url_ends_in_one_slash_however_it_was_written(written, expected):
    assert with_trailing_slash(written) == expected


def test_matching_thresholds_report_no_drift():
    # The quiet case: slo.yml and site.yml agree, and nothing is said.
    thresholds = {"web_response_alert": 3.5, "app_response_alert": 800}
    assert slo.report_threshold_drift(thresholds, slos=SLOS) == []


def test_a_threshold_that_has_drifted_says_both_numbers():
    thresholds = {"web_response_alert": 4.5, "app_response_alert": 800}
    drifts = slo.report_threshold_drift(thresholds, slos=SLOS)

    assert len(drifts) == 1
    assert "3.5s in slo.yml" in drifts[0]
    assert "4.5s in site.yml" in drifts[0]


def test_a_renamed_threshold_says_what_to_rename(monkeypatch):
    monkeypatch.setattr(
        manager,
        "get_config",
        lambda name: {"alert_limit": 700, "web_response_alert": 3.5, "app_response_alert": 800},
    )
    manager.alert_thresholds.cache_clear()

    with pytest.raises(ConfigurationError) as err:
        manager.alert_thresholds()

    assert "Rename alert_limit to active_users_alert" in str(err.value)
    manager.alert_thresholds.cache_clear()


def test_a_missing_threshold_says_what_to_add(monkeypatch):
    monkeypatch.setattr(
        manager, "get_config", lambda name: {"web_response_alert": 3.5, "app_response_alert": 800}
    )
    manager.alert_thresholds.cache_clear()

    with pytest.raises(ConfigurationError) as err:
        manager.alert_thresholds()

    assert "Add active_users_alert to it" in str(err.value)
    manager.alert_thresholds.cache_clear()


def test_help_and_version_answer_without_running_a_check(capsys):
    # The onboarding guide's first command. It used to start a production run.
    with pytest.raises(SystemExit) as exited:
        parse_args(["--version"])
    assert exited.value.code == 0
    assert "healthbot" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exited:
        parse_args(["--help"])
    assert exited.value.code == 0
    assert "A healthy run says nothing" in capsys.readouterr().out


def test_an_unknown_argument_is_refused():
    with pytest.raises(SystemExit) as exited:
        parse_args(["--nope"])
    assert exited.value.code == 2


def test_a_site_config_without_canary_urls_says_what_to_rename():
    with pytest.raises(ConfigurationError) as err:
        check_site_config({"base_url": "https://x/", "ping_urls": ["checkout"]})

    assert "Rename ping_urls to canary_urls" in str(err.value)


def test_a_complete_site_config_passes_quietly():
    assert check_site_config({"base_url": "https://x/", "canary_urls": []}) is None
