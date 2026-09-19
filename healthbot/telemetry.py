"""
OpenTelemetry layer: emit, then notify.

Every run produces one root span with a child span per check, plus the metric
set the SRE stack consumes (Prometheus via the OTel Collector). Disabled by
default: nothing is exported unless HB_OTEL_ENABLED is truthy or an
OTEL_EXPORTER_OTLP_ENDPOINT is set, so a host without a collector behaves
exactly as before.
"""

# Standard library imports
import time
from contextlib import contextmanager
from os import environ

# Third party imports
from opentelemetry import metrics, trace

# Local imports
from healthbot import __app_name__, __version__
from healthbot.settings import get_settings

_configured = False

# Instruments are created against the API's proxy providers, so creating them
# at import time is safe: they no-op until setup_telemetry() installs the SDK.
_tracer = trace.get_tracer(__app_name__, __version__)
_meter = metrics.get_meter(__app_name__, __version__)

# Boundaries that resolve the range a run measures and reach the ceilings
# the code declares: 30s the ping timeout, 15s a Playwright step, 300s the
# systemd TimeoutStartSec the whole run gets.
CHECK_DURATION_BUCKETS = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2,
    5,
    10,
    15,
    30,
)
RUN_DURATION_BUCKETS = (0.5, 1, 2, 3, 5, 10, 30, 60, 120, 180, 240, 300)

run_duration = _meter.create_histogram(
    "healthbot.run.duration", unit="s", description="Wall time of one full run"
)
check_duration = _meter.create_histogram(
    "healthbot.check.duration", unit="s", description="Wall time of one check"
)
check_result = _meter.create_counter(
    "healthbot.check.result", description="Check outcomes by status (pass/fail/error)"
)
probe_status = _meter.create_counter(
    "healthbot.probe.http.status", description="Canary URL responses by status code"
)
heartbeat = _meter.create_counter(
    "healthbot.heartbeat", description="Dead-man's switch: one tick per completed run"
)
slo_events = _meter.create_counter(
    "healthbot.slo.events", description="Per-run SLO verdicts (good/bad) per SLI"
)
slo_target = _meter.create_gauge(
    "healthbot.slo.target", description="Configured objective per SLI, as a ratio"
)
active_users = _meter.create_gauge(
    "healthbot.site.active_users", description="GA realtime active users"
)
# Deliberately unitless: the app tier reports milliseconds and the web tier
# seconds, exactly as New Relic hands them over. Normalising here would make
# the emitted numbers disagree with site.yml's thresholds
response_time = _meter.create_gauge(
    "healthbot.apm.response_time", description="New Relic response time by tier"
)
dora_gauge = _meter.create_gauge(
    "healthbot.dora.metric", description="DORA metrics computed over the export window"
)


def duration_views() -> list:
    """
    Binds the boundaries above to the two duration histograms. Every other
    instrument keeps the SDK default, which no view here matches.
    """
    # Imported here so the disabled path never touches the SDK
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View

    return [
        View(
            instrument_name="healthbot.run.duration",
            aggregation=ExplicitBucketHistogramAggregation(RUN_DURATION_BUCKETS),
        ),
        View(
            instrument_name="healthbot.check.duration",
            aggregation=ExplicitBucketHistogramAggregation(CHECK_DURATION_BUCKETS),
        ),
    ]


def is_enabled() -> bool:
    flag = get_settings().otel_enabled
    if flag is not None:
        return flag
    return bool(environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def setup_telemetry() -> bool:
    """
    Install the SDK providers. Returns whether telemetry is live. Idempotent.
    """
    global _configured
    if _configured or not is_enabled():
        return _configured

    # Imported here so the disabled path never touches the SDK
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": __app_name__,
            "service.version": __version__,
            "deployment.environment": get_settings().environment,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[reader], views=duration_views())
    )

    _configured = True
    return True


def shutdown_telemetry() -> None:
    """
    Force-flush and shut down. A five-minute batch job exits before the
    default export interval, so without this every run's telemetry is lost:
    the most common way OTel-in-cron fails, and it fails silently.
    """
    if not _configured:
        return
    trace.get_tracer_provider().shutdown()
    metrics.get_meter_provider().shutdown()


class CheckState:
    def __init__(self) -> None:
        self.status: str = "pass"

    def set_status(self, status: str) -> None:
        self.status = status


@contextmanager
def run_span():
    started = time.monotonic()
    outcome = "success"
    with _tracer.start_as_current_span("healthbot.run"):
        try:
            yield
        except Exception:
            outcome = "error"
            raise
        finally:
            run_duration.record(time.monotonic() - started, {"outcome": outcome})
            heartbeat.add(1, {"outcome": outcome})


@contextmanager
def check_span(name: str):
    """
    Times one check and records its five-status result. An exception is an
    'error' outcome, a distinct thing from 'fail', and is re-raised.
    """
    state = CheckState()
    started = time.monotonic()
    with _tracer.start_as_current_span(f"healthbot.check.{name}") as span:
        try:
            yield state
        except Exception:
            state.status = "error"
            raise
        finally:
            elapsed = time.monotonic() - started
            span.set_attribute("healthbot.check.status", state.status)
            check_duration.record(elapsed, {"check": name, "status": state.status})
            check_result.add(1, {"check": name, "status": state.status})


def record_probe_statuses(results: list) -> None:
    for url, status in results:
        probe_status.add(1, {"url": url, "status_code": str(status)})


def record_business_metrics(message_data: dict) -> None:
    users = message_data.get("ga_active_users")
    if users is not None:
        active_users.set(users)
    for tier in ("app", "web"):
        value = message_data.get(f"{tier}_response_time")
        if value is not None:
            response_time.set(float(value), {"tier": tier})


def record_slo_events(events: list) -> None:
    for name, good in events:
        slo_events.add(1, {"slo": name, "result": "good" if good else "bad"})


def record_slo_targets(objectives: list) -> None:
    """
    Emits each objective with the sentence slo.yml already carries and the
    target as a printable percentage, so a dashboard names an SLI in words
    and can show what it is measured against.
    """
    for objective in objectives:
        target = float(objective["target"])
        slo_target.set(
            target,
            {
                "slo": objective["name"],
                "description": objective["description"],
                "objective": f"{target * 100:g}%",
            },
        )


def record_dora(values: dict) -> None:
    for metric_name, value in values.items():
        dora_gauge.set(float(value), {"metric": metric_name})
