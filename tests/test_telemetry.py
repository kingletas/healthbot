#!/usr/bin/env python3

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from healthbot import telemetry

# One-time global SDK install with in-memory capture. The module-level
# instruments in telemetry.py were created against the proxy providers, so
# this also proves late setup binds them, the same mechanism
# setup_telemetry() relies on in production.
_reader = InMemoryMetricReader()
_spans = InMemorySpanExporter()
metrics.set_meter_provider(MeterProvider(metric_readers=[_reader]))
_tracer_provider = TracerProvider()
_tracer_provider.add_span_processor(SimpleSpanProcessor(_spans))
trace.set_tracer_provider(_tracer_provider)


def _collect():
    # One collection per call site: gauge points are consumed by a
    # collection, so reading metric-by-metric would drop all but the first
    data = _reader.get_metrics_data()
    points = {}
    for rm in data.resource_metrics if data else []:
        for scope in rm.scope_metrics:
            for metric in scope.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


def _metric_points(name):
    return _collect().get(name, [])


def test_run_span_records_heartbeat_and_duration():
    _spans.clear()
    with telemetry.run_span():
        pass
    beats = _metric_points("healthbot.heartbeat")
    assert beats and any(p.attributes["outcome"] == "success" for p in beats)
    assert any(s.name == "healthbot.run" for s in _spans.get_finished_spans())


def test_run_span_marks_a_crash_and_reraises():
    with pytest.raises(RuntimeError), telemetry.run_span():
        raise RuntimeError("boom")
    beats = _metric_points("healthbot.heartbeat")
    assert any(p.attributes["outcome"] == "error" for p in beats)


def test_check_span_statuses():
    _spans.clear()
    with telemetry.check_span("demo_pass"):
        pass
    with telemetry.check_span("demo_fail") as check:
        check.set_status("fail")
    with pytest.raises(ValueError), telemetry.check_span("demo_error"):
        raise ValueError("x")

    results = _metric_points("healthbot.check.result")
    by_check = {(p.attributes["check"], p.attributes["status"]) for p in results}
    assert {("demo_pass", "pass"), ("demo_fail", "fail"), ("demo_error", "error")} <= by_check

    statuses = {
        s.attributes.get("healthbot.check.status")
        for s in _spans.get_finished_spans()
        if s.name.startswith("healthbot.check.")
    }
    assert statuses == {"pass", "fail", "error"}


def test_business_and_slo_recorders():
    telemetry.record_business_metrics(
        {"ga_active_users": 321, "app_response_time": 450.0, "web_response_time": 2.1}
    )
    telemetry.record_slo_events([("checkout_availability", True), ("canary_availability", False)])
    telemetry.record_slo_targets({"checkout_availability": 0.99})
    telemetry.record_canary_statuses([("https://x/", 200), ("https://x/y", 503)])
    telemetry.record_dora({"mttr_seconds": 120.0})

    collected = _collect()
    users = collected["healthbot.site.active_users"]
    assert users and users[-1].value == 321
    events = collected["healthbot.slo.events"]
    assert {(p.attributes["slo"], p.attributes["result"]) for p in events} >= {
        ("checkout_availability", "good"),
        ("canary_availability", "bad"),
    }
    probes = collected["healthbot.canary.http.status"]
    assert any(p.attributes["status_code"] == "503" for p in probes)
    dora = collected["healthbot.dora.metric"]
    assert dora and dora[-1].attributes["metric"] == "mttr_seconds"


def test_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("HB_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert telemetry.is_enabled() is False
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert telemetry.is_enabled() is True
    monkeypatch.setenv("HB_OTEL_ENABLED", "0")
    assert telemetry.is_enabled() is False
