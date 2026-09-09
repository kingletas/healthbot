# Changelog

Entries say what changed for somebody running HealthBot. The reasoning behind a change is in its commit message — you'll find the detail there, not here.

## Unreleased

Nothing's tagged yet. Everything below has landed on `main` and will be the
first release's notes.

### Added

- **Service level objectives.** Five are declared in `healthbot/config/slo.yml` —
  checkout, the canary sweep, both latencies and the monitor's own availability.
  Every run emits a good or bad event per objective.
- **OpenTelemetry.** Set `HB_OTEL_ENABLED=1` and an `OTEL_EXPORTER_OTLP_ENDPOINT`
  and each run exports its check spans, business metrics and a heartbeat. With neither set the telemetry layer does nothing, so an existing deployment doesn't change at all.
- **Burn-rate alerting.** Prometheus rules under `IT/observability/` page at
  14.4× and raise a ticket at 6×, plus `HealthBotSilent` — a dead-man's switch
  that fires when the heartbeat stops.
- **DORA metrics.** `healthbot-dora record deploy|incident|resolve` appends to a
  journal; `healthbot-dora export` computes deployment frequency, lead time
  against real commit times, change-failure rate and time to restore.
- **A local environment that runs the real bot.** `IT/local/` brings up a stub
  storefront, Mattermost standing in for Slack, and an AWS emulator, so
  `main()` runs end to end on a laptop — checkout journey and alert delivery
  included. Nine integration tests drive it.
- **A test suite.** 75 tests where there had been one assertion, covering the
  AWS, ping, notification and telemetry boundaries.
- **Two CI workflows**, path-gated: the Python gate builds and uploads the wheel,
  and the infrastructure gate validates Terraform and the playbook without
  credentials.

### Changed

- **Python 3.8 to 3.12, Poetry to uv, black/pylint/tox to ruff.** `uv sync`
  builds the environment from `uv.lock`; `make check` is the whole gate.
- **Selenium to Playwright.** The checkout check doesn't need geckodriver or a distro Firefox any more — `playwright install chromium` is the whole browser setup.
  A failed journey now leaves a screenshot, the page HTML and a replayable trace
  under `healthbot/logs/` instead of a bare `False`.
- **The deployable artifact is built, never stored.** The playbook installs the
  newest `dist/healthbot-*.whl` and refuses to deploy when none exists, in place
  of a hand-built wheel committed to the repository.
- **Configuration is an example, not one site's.** The shipped `site.yml` points
  at `store.example.com`; a deployment supplies its own through `HB_CONFIG_DIR`.
  The Terraform backend is a partial configuration, so the state bucket is given
  at `init` time.
- **`HB_*` variables are validated.** `healthbot/settings.py` parses them with
  pydantic-settings, so a misspelled variable is an error at startup rather than
  a silent default.

### Fixed

- **A crashed run doesn't report success any more.** A total failure exited 0, and
  systemd recorded a clean run every five minutes for a bot that never checked
  anything. It exits non-zero now, and charges only the monitor objective — a run
  that crashed says nothing about the site.
- **A signal that could not be collected now alerts** instead of passing
  silently.
- **A connection failure during the ping sweep folds in as status 0** rather
  than aborting the whole sweep.
- **Credentials are fetched fresh every run and never cached.** Only plain
  parameter values go to Redis.
- **The Slack message is valid JSON.** The metrics loop left a trailing comma
  after its last field, and another after its last metric class, so what Slack received wasn't parseable.
