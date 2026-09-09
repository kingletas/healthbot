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

- **Jinja2 is no longer a runtime dependency.** Nothing templated anything once the Slack message stopped being a template.
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

- **A standing alert backs off instead of repeating every five minutes.** An
  outage that lasted an afternoon sent the same message about fifty times, on
  Slack, SMS and SNS. Repeats now go out after 15 minutes, 30, then hourly —
  six messages in four hours rather than forty-nine.

  Three rules make that safe to add. **A change in what is wrong always
  speaks**, so checkout going down during a traffic surge is a new alert and
  not a suppressed repeat. **Recovery has to hold**: two consecutive clean
  runs, because a threshold resting on its limit flaps and a backoff that
  resets on the first good run never engages. And **a gate that cannot read
  its own state sends anyway** — the failure mode has to be a duplicate
  message, never a silent outage.
- **Redis is a cache again, not a dependency.** The client carried no timeout,
  so a hung Redis hung a five-minute batch job — the exact failure
  `REQUEST_TIMEOUT_SECONDS` exists to prevent for HTTP. It has connect and
  operation timeouts, and a read that fails is a miss: every caller has a
  source of truth behind it, so the run costs a round trip instead of dying.
- **The Slack message is built as data and serialised once.** It was a Jinja
  template emitting JSON by hand, which is what produced the trailing commas.
  `json.dumps` on a list of blocks makes the whole class of bug impossible.
  A metric that could not be collected now reads `_not collected_` rather than
  rendering blank — `*ms* Response time` looked like a measurement of nothing.

- **The Google Analytics check reads GA4.** It had been calling Universal
  Analytics — `analytics/v3`, `rt:activeUsers`, a `ga:` view id — which stopped
  serving data in July 2023 and was withdrawn a year later, so the metric could
  only ever come back empty. It now calls the GA4 Data API's
  `runRealtimeReport`. **The secret's `view_ids` becomes `ga_property_id`**: a
  GA4 property, numeric or `properties/<id>`.
- **A Google outage costs one metric instead of the whole run.** The check
  raised, and nothing caught it before `main()`, so an API error took the
  checkout and canary results down with it. It returns `None` now — the
  "cannot tell" signal the alerting and the SLOs already understand.
- **The playbook installs the browser the checkout check drives.** Nothing ever
  did, so on a fresh host the browser failed to launch, the check caught it,
  and checkout was reported down on every run forever.
- **The bot no longer runs as root.** An unprivileged `healthbot` account owns
  the run, with the browser in a shared `/opt/ms-playwright` it can read.
- **Logs and failure evidence leave the installed package.** They were written
  inside `site-packages`, which a read-only install refuses and nobody thinks
  to look in. `HB_LOG_DIR` decides now, and systemd's `LogsDirectory` gives the
  deployed unit `/var/log/healthbot`.
- **A slow run is no longer killed and recorded as a failure.** `Type=oneshot`
  inherits a 90-second start timeout; a checkout journey plus four API calls
  can outrun it, and the site takes the blame for the monitor. It is 300s.

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
