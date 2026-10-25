#!/usr/bin/env python3

import pytest

import healthbot.site_run as site_run
from healthbot.errors import ConfigurationError

SLOS = [
    {"name": "checkout_availability", "signal": "is_checkout_up", "kind": "boolean"},
    {"name": "canary_availability", "signal": "canary_ok", "kind": "boolean"},
    {"name": "web_latency", "signal": "web_response_time", "kind": "below", "threshold": 3.5},
    {"name": "app_latency", "signal": "app_response_time", "kind": "below", "threshold": 800},
    {"name": "monitor_availability", "signal": "run_completed", "kind": "boolean"},
]


def _wire(monkeypatch, checkout=True, canary=True, config=None, boom=False):
    """Records what the run emits, with the browser and the sweep replaced."""
    emitted = {"targets": None, "events": []}
    monkeypatch.setattr(site_run.slo, "load_slos", lambda: SLOS)
    monkeypatch.setattr(
        site_run,
        "get_config",
        lambda name: (
            config
            if config is not None
            else {"base_url": "https://shop.example/", "canary_urls": ["checkout"]}
        ),
    )
    monkeypatch.setattr(site_run, "get_base_url", lambda: "https://shop.example/")

    def fake_checkout(**kwargs):
        if boom:
            raise RuntimeError("browser exploded")
        return checkout

    monkeypatch.setattr(site_run, "validate_checkout", fake_checkout)
    monkeypatch.setattr(site_run, "check_canary_urls", lambda: canary)
    monkeypatch.setattr(site_run, "add_file_sink", lambda: None)
    monkeypatch.setattr(
        site_run.telemetry, "record_slo_targets", lambda slos: emitted.update(targets=slos)
    )
    monkeypatch.setattr(
        site_run.telemetry, "record_slo_events", lambda events: emitted["events"].extend(events)
    )
    return emitted


def test_judges_only_the_slis_it_collects(monkeypatch):
    emitted = _wire(monkeypatch)
    assert site_run.main([]) == 0
    assert [s["name"] for s in emitted["targets"]] == [
        "checkout_availability",
        "canary_availability",
        "monitor_availability",
    ]
    names = [name for name, _ in emitted["events"]]
    assert "web_latency" not in names and "app_latency" not in names


def test_a_healthy_store_is_three_good_events(monkeypatch):
    emitted = _wire(monkeypatch)
    assert site_run.main([]) == 0
    assert emitted["events"] == [
        ("checkout_availability", True),
        ("canary_availability", True),
        ("monitor_availability", True),
    ]


def test_a_store_that_cannot_sell_exits_0_with_a_bad_checkout_event(monkeypatch):
    emitted = _wire(monkeypatch, checkout=False)
    assert site_run.main([]) == 0
    assert ("checkout_availability", False) in emitted["events"]
    assert ("monitor_availability", True) in emitted["events"]


def test_a_failed_sweep_is_a_bad_canary_event(monkeypatch):
    emitted = _wire(monkeypatch, canary=False)
    assert site_run.main([]) == 0
    assert ("canary_availability", False) in emitted["events"]


def test_a_site_yml_without_base_url_is_refused_and_charges_only_the_monitor(monkeypatch):
    emitted = _wire(monkeypatch, config={"canary_urls": ["checkout"]})
    assert site_run.main([]) == 1
    assert emitted["events"] == [("monitor_availability", False)]


def test_a_crash_charges_only_the_monitor(monkeypatch):
    emitted = _wire(monkeypatch, boom=True)
    assert site_run.main([]) == 1
    assert emitted["events"] == [("monitor_availability", False)]


def test_help_answers_before_any_check(monkeypatch, capsys):
    monkeypatch.setattr(
        site_run, "validate_checkout", lambda **kwargs: pytest.fail("a check ran for --help")
    )
    with pytest.raises(SystemExit) as stopped:
        site_run.main(["--help"])
    assert stopped.value.code == 0
    assert "seen only from outside" in capsys.readouterr().out


def test_site_slos_drops_what_this_run_cannot_collect():
    assert [s["name"] for s in site_run.site_slos(SLOS)] == [
        "checkout_availability",
        "canary_availability",
        "monitor_availability",
    ]


def test_configuration_error_is_the_errors_module_one():
    assert site_run.ConfigurationError is ConfigurationError
