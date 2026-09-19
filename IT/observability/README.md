# HealthBot local observability stack

OTLP in, Grafana out: the bot (or the synthetic demo) emits OpenTelemetry to the collector, the collector exposes Prometheus metrics, Prometheus computes SLO burn rates and alerts, Grafana shows the provisioned dashboards.

```text
healthbot / healthbot-demo / healthbot-dora
        │ OTLP http :4318
        ▼
otel-collector ──:8889──> prometheus (rules: burn rates, compliance, dead-man)
                               │
                               ▼
                           grafana :3000  (HealthBot SRE · HealthBot DORA)
```

## Run it

> `../local/docker-compose.yml` *includes* this file, so if you want the full local environment (Mattermost, the API stubs, and a shared emulator playing AWS) start the stack from `IT/local` instead, because running both compose projects at once collides on every published port. This stack alone is the right choice when all you need is the telemetry pipeline and the demo emitter.

```bash
docker compose up -d
```

```bash
HB_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 OTEL_METRIC_EXPORT_INTERVAL=15000 uv run healthbot-demo --interval 15
```

Then open <http://localhost:3000> (anonymous admin, local only). The dashboards are in the **HealthBot** folder. Prometheus with the rules and alerts is at <http://localhost:9090>.

The demo emits synthetic runs **through the production telemetry code path**, with the same spans, metrics and SLO evaluation, and seeds a 30-day DORA journal on first start (real commit shas from this repo, so lead time is computed against real commit times). A real bot run works against this stack identically: set the same two environment variables on the host running `healthbot`.

## DORA in production

The journal is an append-only JSONL at `HB_DORA_EVENTS` (default `~/.local/share/healthbot/dora-events.jsonl`). Wire it into the deploy path with one line, e.g. at the end of the Ansible playbook:

```bash
healthbot-dora record deploy --sha "$(git rev-parse HEAD)"
```

and record incidents/resolves by hand or from alerting hooks:

```bash
healthbot-dora record incident
```

```bash
healthbot-dora record resolve
```

`healthbot-dora export --window-days 30` computes the four metrics and pushes them through the same OTLP pipeline. Run it from cron or a systemd timer.

## SLOs

Objectives live in `healthbot/config/slo.yml` and are emitted as the `healthbot_slo_target` gauge, so the Prometheus rules never hardcode a target. Burn-rate alerting is multi-window multi-burn-rate (SRE Workbook §5.5): **page** at 14.4× (1h + 5m), **ticket** at 6× (6h + 30m), plus `HealthBotSilent`, the dead-man's switch, when the heartbeat stops.

> The burn thresholds are conventions until enough real data exists to backtest them; see the volume-backtest lesson in the vault before paging anyone.

## Gotchas

- **Grafana is wide open** (`GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`). Local convenience only; never reuse this compose file anywhere shared.
- The collector's `metric_expiration` is 10m because DORA gauges only arrive every ~10th demo run; drop-outs on the DORA panels mean the exporter stopped, not that the metric went to zero.
- **The bot is a oneshot in production, and the pipeline is built around that.** Each run is a separate process, so it exports what it measured as a delta under a stable `instance` label (the hostname, or `HB_OTEL_INSTANCE_ID`), and the collector's `deltatocumulative` processor adds those deltas into one counter per machine. Without both halves the runs scatter into one single-sample series each, `rate()` and `increase()` return zero or NaN, and every burn-rate alert goes quiet for ever. Changing one half alone is worse than changing neither: a stable id on cumulative exports makes every run write the same 1 onto the same series.
- **`deltatocumulative` keeps a stream for `max_stale` (1h here), which is longer than the gap between runs on a 5m timer plus its 60s jitter.** Shorter than that gap and the running total is dropped and restarted between ordinary runs.
- **`HealthBotSilent` asks whether the heartbeat is present, not how fast it is ticking, and that is still true now the counters accumulate.** A series is dropped one `metric_expiration` after its last update, and a rate over a series that is gone is empty rather than zero, so the rate-shaped expression is the one that cannot fire. Absence pages one `metric_expiration` plus the alert's `for` after the last run.
- **`count()` over a healthbot counter is a liveness test, not a count of runs.** There is one series per machine now, so it answers *is anything reporting*. Counting runs is `increase(healthbot_heartbeat_total[...])`.
- Traces currently go to the collector's debug log. Adding Tempo or Jaeger is a one-exporter change in `otel-collector.yaml`.
