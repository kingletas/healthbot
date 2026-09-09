# IT/local — the full local environment

Everything a real `healthbot` run touches, emulated on one laptop. Where `IT/observability` renders what the bot *emits*, this stack stands in for what the bot *consumes* — so the production `main()`, all five checks, runs end to end with exit codes, alerts and telemetry you can watch.

AWS is played by **MiniStack, which this compose file does not define**. It is the shared workstation emulator at `~/Services/dev-services`, started once for the machine rather than once per project, and reached on the docker bridge address `172.17.0.1:4566`. Start it before this stack.

| Stand-in | Plays | Where |
|---|---|---|
| MiniStack (shared, from `dev-services`) | SSM Parameter Store, Secrets Manager, EC2, CloudWatch, SNS | `172.17.0.1:4566` |
| Mattermost (preview image) | Slack — messages land in `~town-square` | `:8065` |
| stub container | the storefront (Playwright checkout journey + pings) | `:8080` |
| stub container | New Relic v2 API, GA discovery/token/realtime, the Slack→Mattermost shim, chaos switches | `:8081` |
| included from `../observability` | otel-collector, Prometheus, Grafana, Redis | `:4318` `:9090` `:3000` `:6379` |

## Quickstart

The shared emulator first — it is not part of this compose project:

```bash
docker compose -f ~/Services/dev-services/docker-compose.yaml up -d ministack
```

```bash
cd IT/local && docker compose up -d --build
```

```bash
uv run healthbot-local seed
```

```bash
uv run healthbot-local status
```

Then run the bot itself — `healthbot-local run-env` prints this with every seam spelled out:

```bash
AWS_ENDPOINT_URL=http://172.17.0.1:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 HB_CONFIG_DIR=IT/local/config HB_NR_API_URL=http://localhost:8081/nr/v2/ HB_SLACK_API_URL=http://localhost:8081/slack/ HB_GA_DISCOVERY_URL=http://localhost:8081/ga/discovery HB_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run healthbot
```

A healthy stack exits 0 with no alert. Between runs, `healthbot-local feed` keeps CloudWatch datapoints fresh (the bot reads the newest datapoint of the last five minutes, so a stale seed means an empty `aws_metrics`).

Mattermost is at <http://localhost:8065> — `sre@local.test` / `SuperSecret-123`, bootstrapped by the stub container (first user, team `sre`, incoming webhook into `~town-square`). Grafana and Prometheus are the observability stack's usual `:3000` and `:9090`.

## How the bot is redirected

Each seam is one `HB_*` variable, validated in `healthbot/settings.py`, and each is a no-op when unset — which is the production state:

| Variable | Redirects | Mechanism |
|---|---|---|
| `AWS_ENDPOINT_URL` | every boto3 client | native botocore support; no code seam at all |
| `HB_CONFIG_DIR` | `site.yml` (base URL, ping URLs) | override dir with per-file fallback to the packaged config |
| `HB_NR_API_URL` | New Relic | instance override of `newrelic_api`'s `Resource.URL` class attribute |
| `HB_SLACK_API_URL` | Slack | `WebClient(base_url=…)` — the shim relays `chat.postMessage` into Mattermost |
| `HB_GA_DISCOVERY_URL` | Google Analytics | `discoveryServiceUrl` + `static_discovery=False`; the token endpoint follows from `token_uri` inside the seeded service-account JSON |

The seeded GA service account carries a throwaway RSA key generated fresh on every `seed` — google-auth signs a real JWT with it and the stub accepts anything well-formed. Twilio is deliberately absent from the local secret blob: its SDK has no endpoint seam, so the SMS branch stays skipped locally and is covered by the unit suite.

## Staging an outage

The stub exposes chaos switches; flip one, run the bot, watch the alert arrive in Mattermost and the SLO burn in Grafana:

```bash
curl -s -X POST http://localhost:8081/control -d '{"ga_surge": true}'
```

| Switch | Effect | What alerts |
|---|---|---|
| `checkout_down` | checkout page loses its title | `is_checkout_up` → Slack/Mattermost + SNS |
| `pings_down` | every non-checkout page 503s | `ping_ok` |
| `ga_surge` | 934 active users (over `alert_limit` 700) | Slack/Mattermost |
| `nr_slow` | 2300 ms APM / 6.2 s browser | both latency thresholds |

`GET /control` shows the current state; POST with `false` to calm it back down.

## Tests

```bash
uv run pytest -m integration
```

Nine tests, skipped automatically when the stack is not up. The suite seeds nothing — run `healthbot-local seed` first. The two worth knowing by name: `test_full_run` executes the production `main()` against the whole stack and asserts exit 0 with no alert; `test_staged_outage_pages_into_mattermost` flips `ga_surge` and asserts the rendered alert actually arrived in `~town-square`, not merely that the send did not error.

The unit suite (`uv run pytest`, no marker) never touches this stack — `-m 'not integration'` is the configured default.

## Gotchas

- **The AWS emulator is shared and lives elsewhere** — `~/Services/dev-services`, one MiniStack for the whole workstation. Nothing here defines it, so bring it up separately, and on a collision with another project leave it running and agree who turns it off. It replaced a private LocalStack 4.9 that had been exited for eleven hours with nobody owning it; the auth-token constraint that forced that pin is gone, because MiniStack has no token concept.
- **The health path is still `/_localstack/health`, and that is correct.** MiniStack serves LocalStack's API surface on the same port, so the path is compatibility, not a leftover. Do not rename it — and do not look for `cloudwatch` in the health list either: MiniStack names services by their AWS API namespace, so CloudWatch appears as `monitoring`.
- **The CloudWatch leg depends on the emulator accepting publishes into `AWS/*` namespaces**, which real AWS refuses. `test_localstack_accepts_aws_namespace_datapoints` exists to name this if an emulator upgrade ever regresses it; it keeps its original name because it guards the behaviour, not the vendor.
- **A datapoint is not readable the instant it is published.** MiniStack indexes `put_metric_data` with a sub-second lag, so publishing and reading back in the same breath can return an empty window. Nothing in the normal flow is that tight — `seed` then a run is seconds apart — but a test that does both in one function needs to allow for it.
- **The seeded AWS resources now sit in a shared account.** Every name HealthBot creates is prefixed or suffixed distinctly (`/healthbot-sm/manager/*`, `healthbot-local`, `healthbot-local-alerts`, the `EXAMPLE-WEB-01` instance tagged `Local-FLEET`), and seeding stays idempotent, so a reseed does not disturb another project. MiniStack supports multi-account and multi-region if stronger isolation is ever needed.
- **slack_sdk sends `chat.postMessage` as a JSON body when blocks are attached**, urlencoded otherwise. The shim accepts both; the first version read only form data and every alert degraded to a placeholder — and the placeholder contained the word "HealthBot", which let the original content assertion pass. Hence the pointedly specific asserts in `test_staged_outage_pages_into_mattermost`.
- **`PUBLIC_API_BASE` on the stub container must be the host-visible base** (`http://localhost:8081`), because it is templated into the GA discovery document that the host-side bot follows back. The compose-internal hostname would only work for another container.
- **`healthbot-local` cannot be pointed at real AWS.** Clients are built with an explicit endpoint pinned to a local host and static dummy credentials; a non-local endpoint is a hard refusal, no override flag. This is deliberate — see the standing rule about never executing against AWS.
- **Everything here is local-only convenience.** Anonymous-admin Grafana, fixed Mattermost credentials, dummy AWS keys: never reuse any of it anywhere shared.
- **Starting this stack alongside a separately-started `IT/observability` stack collides on every port** — this compose file *includes* that one, so bring observability down first (`docker compose -p observability down`) and let IT/local own its containers.
- **Mattermost here is still HealthBot's own**, and it is deliberately *not* migrated to the shared one — the stub container bootstraps it with specific credentials and a `~town-square` channel. It binds `127.0.0.1:8065` rather than `0.0.0.0:8065` so it can run beside the shared Mattermost on `172.17.0.1:8065`; a `0.0.0.0` bind covers the bridge address too, which is why the two used to be mutually exclusive.
