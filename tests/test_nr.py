#!/usr/bin/env python3

import healthbot.checks.nr as nr


def test_metrics_from_both_summaries_are_merged(monkeypatch):
    def fake_status(api_key=None, summary="end_user_summary", name_filter=None):
        return {"id": 1, "summary": {"response_time": 0.4, "apdex_score": 0.9}}

    monkeypatch.setattr(nr, "get_newrelic_status", fake_status)
    result = nr.get_new_relic_data(secrets={"new_relic_api": "key"})
    assert result["app_response_time"] == 0.4
    assert result["web_response_time"] == 0.4
    assert result["app_apdex_score"] == 0.9


def test_failed_lookup_omits_keys_instead_of_crashing(monkeypatch):
    # Regression: data.get("summary").items() raised AttributeError on None,
    # and a swallowed API failure produced an empty dict that crashed here.
    monkeypatch.setattr(nr, "get_newrelic_status", lambda **kwargs: {})
    assert nr.get_new_relic_data(secrets={}) == {}

    monkeypatch.setattr(nr, "get_newrelic_status", lambda **kwargs: {"id": 1, "summary": None})
    assert nr.get_new_relic_data(secrets={}) == {}
