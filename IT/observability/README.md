# HealthBot local observability stack

OTLP in, Grafana out: the bot (or the synthetic demo) emits OpenTelemetry to the collector, the collector exposes Prometheus metrics, Prometheus computes SLO burn rates and alerts, Grafana shows the provisioned dashboards.

```text
healthbot / healthbot-demo / healthbot-dora / a host-pressure exporter
        │ OTLP http :4318
        ▼
otel-collector ──:8889──> prometheus (rules: burn rates, compliance, dead-man)
                               │                    │
                               ▼                    ▼ (the two host-pressure
                           grafana :3000        alertmanager :9093   alerts only)
                       (HealthBot SRE · DORA ·       │
                        Host Pressure)                ▼
                                          alertmanager-bridge :9095 (native,
                                          not a container -- see below)
                                                       │
                                                       ▼
                                                     Slack
```

**A host-pressure exporter** is a second kind of producer into this
same collector, alongside the bot: something running on the host being
watched posts one OTLP/HTTP JSON metrics request per sample, on the
interface `prometheus/rules/host-pressure.yml` documents in its own header
(`host_psi_pct`, `host_mem_available_pct`, `host_load1`, `host_cpu_count`,
`host_pressure_level`, resource `service.name` "host-pressure-exporter").
That file carries the SLO (memory PSI `some avg60` under 10% for 99% of
minutes) and its two alerts; `grafana/dashboards/host-pressure.json` is its
panel. Nothing here assumes a particular exporter -- any process that speaks
the interface drives these rules.

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

> The burn thresholds are conventions, not measurements. Nothing here has been backtested against real traffic, so a threshold that looks right may fire constantly or never at all, and neither is visible until it happens. Collect real data first, replay it against these numbers, and move them before routing any of this to a person.

## Alertmanager and the Slack bridge

Alertmanager owns *who* gets told and how often -- `alertmanager/alertmanager.yml`'s
`group_interval`/`repeat_interval` back off a standing alert and speak on a
change, natively, rather than reimplementing `healthbot/alerting.py`'s
`AlertGate` for rule-based alerts. **Only the two host-pressure alerts are
routed anywhere.** HealthBot's own burn-rate and dead-man's-switch rules
(`prometheus/rules/slo.yml`) fall through to a null receiver on purpose:
`todos.md` already says routing those is blocked on 30 days of real
telemetry to backtest the thresholds against, and this stack must not start
paging on unproven numbers as a side effect of Alertmanager existing.

The Slack delivery itself is `healthbot-alertmanager-bridge`
(`healthbot/notifications/alertmanager_bridge.py`): Alertmanager's webhook
receiver posts each firing/resolved group to it, and it sends one Slack
message per group through `SlackNotifier` -- the same client class a real
`healthbot` run uses. It reads `slack_token`/`slack_channel` the same way
`healthbot.py`'s own main flow does (Parameter Store's `secret_name` pointer,
then Secrets Manager), so there is exactly one place the estate manages that
credential. **It is deliberately not a container**: it needs the AWS
endpoint and credentials a real run needs, and runs as its own native
systemd user service (`alertmanager-bridge/healthbot-alertmanager-bridge.service`)
bound to the docker bridge address (`172.17.0.1`, reachable from the
`alertmanager` container and the host, not the LAN) so Alertmanager can reach
it without another container in the path.

Locally, point it at `IT/local`'s Mattermost stand-in the same way a real
bot run does: `HB_SLACK_API_URL=http://localhost:8081/slack/` plus the AWS
env `healthbot-local run-env` prints, and `uv run healthbot-local seed` has
already seeded `slack_token`/`slack_channel` (`town-square`) under the
`healthbot-local` secret name for you.

## Gotchas

- **Grafana is wide open** (`GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`). Local convenience only; never reuse this compose file anywhere shared.
- The collector's `metric_expiration` is 10m because DORA gauges only arrive every ~10th demo run; drop-outs on the DORA panels mean the exporter stopped, not that the metric went to zero.
- **The bot is a oneshot in production, and the pipeline is built around that.** Each run is a separate process, so it exports what it measured as a delta under a stable `instance` label (the hostname, or `HB_OTEL_INSTANCE_ID`), and the collector's `deltatocumulative` processor adds those deltas into one counter per machine. Without both halves the runs scatter into one single-sample series each, `rate()` and `increase()` return zero or NaN, and every burn-rate alert goes quiet for ever. Changing one half alone is worse than changing neither: a stable id on cumulative exports makes every run write the same 1 onto the same series.
- **`deltatocumulative` keeps a stream for `max_stale` (1h here), which is longer than the gap between runs on a 5m timer plus its 60s jitter.** Shorter than that gap and the running total is dropped and restarted between ordinary runs.
- **`HealthBotSilent` asks whether the heartbeat is present, not how fast it is ticking, and that is still true now the counters accumulate.** A series is dropped one `metric_expiration` after its last update, and a rate over a series that is gone is empty rather than zero, so the rate-shaped expression is the one that cannot fire. Absence pages one `metric_expiration` plus the alert's `for` after the last run.
- **`count()` over a healthbot counter is a liveness test, not a count of runs.** There is one series per machine now, so it answers *is anything reporting*. Counting runs is `increase(healthbot_heartbeat_total[...])`.
- **The demo and a real bot on one machine report as the same instance**, because both take the hostname, so the demo's synthetic runs add to the real counters. Give the demo its own `HB_OTEL_INSTANCE_ID` when both point at one collector.
- Traces currently go to the collector's debug log. Adding Tempo or Jaeger is a one-exporter change in `otel-collector.yaml`.
