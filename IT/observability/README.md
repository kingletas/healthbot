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
- **The bot is a oneshot in production, so every run is its own series with a single sample and `rate()` over any of them is zero.** `HealthBotSilent` asks whether the heartbeat is present rather than how fast it is ticking, and pages one `metric_expiration` plus its `for` after the last run. Panels count or aggregate the runs in a window for the same reason.
- Traces currently go to the collector's debug log. Adding Tempo or Jaeger is a one-exporter change in `otel-collector.yaml`.
