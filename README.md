# HealthBot

[![CI](https://github.com/kingletas/healthbot/actions/workflows/healthbot-ci.yml/badge.svg)](https://github.com/kingletas/healthbot/actions/workflows/healthbot-ci.yml)
[![Infra CI](https://github.com/kingletas/healthbot/actions/workflows/infra-ci.yml/badge.svg)](https://github.com/kingletas/healthbot/actions/workflows/infra-ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

HealthBot is a Python SRE bot that probes the storefront from the outside, through New Relic, AWS CloudWatch, Google Analytics, a real-browser checkout journey and a canary URL sweep. It evaluates the results against declared SLOs, emits OpenTelemetry, and notifies through Slack, SMS and SNS. It ships its own infrastructure: Terraform, Packer and Ansible under `IT/`, a local observability stack under `IT/observability/`, and a full local environment under `IT/local/` (Mattermost, API stubs, and the shared MiniStack playing AWS) in which the production bot runs end to end.

**New here? [docs/from-nothing.md](docs/from-nothing.md) gets you from a clone to a real alert in about twenty minutes, with no AWS account, no credentials, and no storefront of your own.**

## Everything runs through `make`

```bash
make            # the target list
make install    # the virtualenv from uv.lock, plus the browser the checkout check drives
make check      # everything a commit has to pass: ruff, ansible-lint, the suite, terraform, packer
make up seed    # the local environment, and the data a run expects to find
```

## The checks

| Check | Source | Feeds |
|---|---|---|
| `checks/site.py` | Headless Chromium (Playwright): search → product → add to cart → checkout page. A failure leaves a screenshot, the page HTML and a replayable trace under `logs/` | `is_checkout_up` |
| `checks/pings.py` | Async sweep of the base URL + `ping_urls` from `site.yml`; a connection failure folds in as status 0 instead of aborting the run | `ping_ok` |
| `checks/nr.py` | New Relic APM + browser summaries | `app_*`/`web_*` metrics |
| `checks/ga.py` | GA4 realtime active users, through the Data API's `runRealtimeReport`, service account via google-auth. A property that cannot be read is `None`, which alerts rather than passing | `ga_active_users` |
| `checks/aws.py` | CloudWatch metrics for the tagged EC2 fleet + RDS cluster (newest datapoint, UTC window) | `aws_metrics` |

Alert thresholds live in `healthbot/config/site.yml`, currently `alert_limit: 700` active users, `app_response_alert: 800` ms and `web_response_alert: 3.5` s. A signal that couldn't be collected triggers the alert rather than passing silently. A run that crashes exits non-zero (`Type=oneshot` in the systemd unit records it) and charges only the monitor SLO, never the site's.

A standing alert backs off rather than repeating: 15 minutes, then 30, then hourly, so an outage lasting an afternoon doesn't send fifty identical messages. A change in *what* is failing always speaks immediately, recovery needs two consecutive clean runs before it counts, and a gate that can't read its own state sends rather than suppressing.

## How HealthBot is laid out

```text
healthbot/
  healthbot.py       main(): the run, in order
  settings.py        every HB_* variable, validated (pydantic-settings)
  config_files.py    the packaged YAML, with an override directory
  cache.py           the Redis cache, which is a cache and never a dependency
  alerting.py        whether a bad run is worth telling anybody about again
  slo.py  telemetry.py  dora.py  demo.py  local_env.py
  aws/               client.py · parameter_store.py · secrets_manager.py
  checks/            site.py · pings.py · nr.py · ga.py · aws.py
  notifications/     base.py · manager.py · slack.py · sns.py · twilio.py
  config/            the shipped YAML: site, slo, cookies, headers, messages
IT/
  terraform/  packer/  ansible/  local/  observability/
```

One module per notification channel, each carrying its own message shape and
the client that sends it. One module per check, named for what it reads.

## SLOs, telemetry, DORA

Objectives are declared in `healthbot/config/slo.yml` (checkout 99%, canary 99.5%, both latencies 99%, monitor availability 99.9%). Every run emits per-SLI good/bad events plus a heartbeat through OpenTelemetry when `HB_OTEL_ENABLED=1` and an `OTEL_EXPORTER_OTLP_ENDPOINT` are set; without them the telemetry layer is a no-op and nothing changes. Prometheus computes multi-window burn rates from the emitted targets, paging at 14.4× and raising a ticket at 6×, plus `HealthBotSilent`, the dead-man's switch that fires when the heartbeat stops.

DORA metrics come from an append-only journal: `healthbot-dora record deploy|incident|resolve` (one line in the deploy path), `healthbot-dora export` to compute deployment frequency, lead time (joined to real git commit times), change-failure rate and MTTR.

The full local stack (OTel Collector → Prometheus with its rules → Grafana with two provisioned dashboards) lives in `IT/observability/`, along with `healthbot-demo`, which drives the whole pipeline with synthetic runs through the production code path. See `IT/observability/README.md`.

## Running it locally, for real

`IT/local/` extends the observability stack into a complete local environment: MiniStack plays AWS (SSM, Secrets Manager, EC2, CloudWatch, SNS) from the shared `dev-services` stack, Mattermost plays Slack, and a stub container plays New Relic, Google Analytics and the storefront, so the production `main()` runs end to end on a laptop, checkout journey and alert delivery included.

```bash
cd IT/local && docker compose up -d --build
uv run healthbot-local seed
uv run healthbot-local run-env      # prints the fully-wired run command
```

Alerts land in Mattermost's `~town-square` at `http://localhost:8065`; chaos switches on the stub (`POST :8081/control`) stage outages on demand. The integration suite runs the whole loop: `uv run pytest -m integration` (nine tests, auto-skipped when the stack is down). See `IT/local/README.md` for the seams and the gotchas.

## Runtime configuration

All `HB_*` environment variables are validated by `healthbot/settings.py` (pydantic-settings): `HB_PARAM_PREFIX` (falls back to `site.yml`'s `secrets_namespace_prefix`), `HB_ENVIRONMENT`, `HB_OTEL_ENABLED`, `HB_DORA_EVENTS` and `HB_DORA_REPO`, plus the local-stack seams `HB_CONFIG_DIR`, `HB_NR_API_URL`, `HB_SLACK_API_URL` and `HB_GA_DISCOVERY_URL`, each a no-op when unset. On a deployed host they arrive via `/etc/healthbot.env`, templated by Ansible from `group_vars`. Run parameters come from SSM Parameter Store (plain values cached in Redis, sensitive ones never), and credentials from Secrets Manager, fetched fresh every run and never cached.

The Secrets Manager blob carries `ga_property_id`: a GA4 property, numeric or `properties/<id>`. It replaced the Universal Analytics view id, which hasn't worked since Google withdrew that API in July 2024.

## Requirements

### Python

Dependencies are managed with [uv](https://docs.astral.sh/uv/), which also installs the required Python (pinned in `.python-version`, currently 3.12):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, from the repo root:

```bash
uv sync
```

That creates `.venv` from `uv.lock` (runtime plus the dev group: ruff, pytest, pre-commit, ansible-lint, moto). Day-to-day commands:

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

### Browser (Playwright)

The checkout check drives a Playwright-bundled Chromium, so you need neither geckodriver nor a distro Firefox:

```bash
uv run playwright install --with-deps chromium
```

### Terraform

Terraform `~> 1.10` is required (the S3 backend uses `use_lockfile`), with the AWS provider pinned `~> 6.61`. Install per the [HashiCorp guide](https://developer.hashicorp.com/terraform/install), then verify with `terraform version`.

The backend is a partial configuration, because the state bucket is yours rather than this repository's, so it isn't committed here. Copy the example and point `init` at it:

```bash
cd IT/terraform && cp backend.hcl.example backend.hcl && terraform init -backend-config=backend.hcl
```

### Ansible

```bash
python -m pip install --user ansible
```

Or use the repo's own dev group, where `uv run ansible-lint` and `uv run ansible-playbook` both work.

### Packer

Install per the [HashiCorp guide](https://developer.hashicorp.com/packer/install). The template's plugins (`amazon`, and `ansible` for the `ansible-local` provisioner) install with:

```bash
cd IT/packer && packer init .
```

`etc/example.hcl` is tracked, so you can check the template without an AWS account and without writing a var file first:

```bash
packer validate -var-file=etc/example.hcl .
```

### AWS CLI

HealthBot itself never shells out to the CLI, because every AWS call goes through boto3, so a deployed host does not need it. You want it on your own machine for `terraform` and `packer`:

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install -u
aws configure
```

## Build and deploy

The deployable artifact is built, never stored in the repo:

```bash
uv build
```

CI uploads the same wheel as the `healthbot-wheel` artifact on every build. The playbook picks the newest `dist/healthbot-*.whl` (override with `healthbot_wheel_glob`) and refuses to deploy when none exists:

```bash
cd IT/ansible && ansible-playbook -i inventory playbook.yml
```

The playbook installs the wheel into its own virtualenv at `/opt/healthbot` rather than the system Python, which 24.04 marks externally managed and which has no business carrying twenty of our dependencies. It also installs the Playwright browser into `/opt/ms-playwright`, fail2ban, an unprivileged `healthbot` service account, the templated `/etc/healthbot.env`, and the systemd pair. The timer (every 5 minutes, with jitter) is the only thing that starts the service. The play is idempotent: a second run reports `changed=0`.

Infrastructure: build the AMI under `IT/packer` by copying the tracked example first, `cp etc/example.hcl etc/dev.hcl`, then `packer build -var-file=etc/dev.hcl .`. `IT/terraform` provisions the host, network wiring and KMS key. Credentials are seeded into Secrets Manager once and rotated there, never re-applied by Terraform. The AMI is Ubuntu 24.04 because that is the first LTS whose stock `python3` is 3.12, which is what `requires-python` asks for.

## CI

Two path-gated workflows: `healthbot-ci.yml` (ruff, format check, import smoke test, pytest, `uv build` + artifact) and `infra-ci.yml` (credential-free `terraform init -backend=false` + fmt + validate, `packer fmt` + `init` + `validate`, tfsec, ansible-lint). The pre-commit config mirrors the same gates locally.
