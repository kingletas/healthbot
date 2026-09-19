# Changelog

Entries say what changed for somebody running HealthBot. The reasoning behind a change is in its commit message. You'll find the detail there, not here.

## Unreleased

Nothing's tagged yet. Everything below has landed on `main` and will be the
first release's notes.

### Added

- **`make tf-local` plans the infrastructure against a local AWS emulator.** It
  needs no AWS account and no credentials: point a LocalStack-compatible
  emulator at `172.17.0.1:4566`, or set `HB_LOCAL_AWS_ENDPOINT` to wherever
  yours listens, then run it. It proves the configuration is coherent and that
  every data source resolves. **It does not prove anything about real AWS** —
  the plan is against an emulator, and that difference is real.

- **A guide for deploying on AWS.** `docs/on-aws.md` takes you from an empty
  account to a systemd timer running the bot every five minutes: the tools, what
  has to exist in the account first, the credentials to collect, then Packer,
  Terraform and the playbook in order.
- **Service level objectives.** Five are declared in `healthbot/config/slo.yml`:
  checkout, the canary sweep, both latencies and the monitor's own availability.
  Every run emits a good or bad event per objective.
- **OpenTelemetry.** Set `HB_OTEL_ENABLED=1` and an `OTEL_EXPORTER_OTLP_ENDPOINT`
  and each run exports its check spans, business metrics and a heartbeat. With neither set the telemetry layer does nothing, so an existing deployment doesn't change at all.
- **Burn-rate alerting.** Prometheus rules under `IT/observability/` page at
  14.4× and raise a ticket at 6×, plus `HealthBotSilent`, a dead-man's switch
  that fires when the heartbeat stops.
- **DORA metrics.** `healthbot-dora record deploy|incident|resolve` appends to a
  journal; `healthbot-dora export` computes deployment frequency, lead time
  against real commit times, change-failure rate and time to restore.
- **A local environment that runs the real bot.** `IT/local/` brings up a stub
  storefront, Mattermost standing in for Slack, and an AWS emulator, so
  `main()` runs end to end on a laptop, checkout journey and alert delivery
  included. Nine integration tests drive it.
- **A test suite.** 75 tests where there had been one assertion, covering the
  AWS, ping, notification and telemetry boundaries.
- **Two CI workflows**, path-gated: the Python gate builds and uploads the wheel,
  and the infrastructure gate validates Terraform and the playbook without
  credentials.

### Changed

- **Both CloudWatch alarms are named after the deployment, not the instance.**
  They were `awsec2-<instance-id>-status-check` and
  `<instance-id>-highCPUUtilization`; they are now
  `<name>-<environment>-status-check` and
  `<name>-<environment>-cpu-utilization-high`. **On an existing deployment the
  next apply destroys and recreates both alarms**, so read the plan first and
  re-point anything keyed on the old names, such as a dashboard or an SNS
  subscription. **A recreated alarm starts in `INSUFFICIENT_DATA` and cannot
  fire until it has collected enough data** — about 15 minutes for the status
  check and about an hour for CPU — and the status check's default action is an
  EC2 reboot, so for that window a hung instance is not rebooted and nobody is
  told. It is worth paying once: the old names changed whenever the instance
  was replaced, so the same blind window happened on **every** AMI build, and
  the alarms could not be referenced from a module at all.

- **One CI workflow, and it runs `make check`.** `ci.yml` replaces
  `healthbot-ci.yml` and `infra-ci.yml`, so the runner checks exactly what
  you check locally. tfsec is no longer part of CI: it was set to never fail.
- **The AMI is a base image, and the bot is installed onto it afterwards.** The
  Packer build ran the deploy playbook as well, so a host was configured twice
  and the image build needed a wheel that only exists on the machine you deploy
  from. It now lays down the operating system packages and stops, which also
  means **a new version of HealthBot no longer needs a new image**.
- **The local stack keeps its own CloudWatch datapoints fresh.** A `feeder`
  service runs the bot's own `healthbot-local feed` once a minute, so there is
  no manual step between `seed` and a run. It was a `feed &` you had to
  remember, and forgetting it made the AWS metrics read as uncollected.
- **The deploy records itself in the DORA journal**, on the control machine
  where the git repository is. It records only when pip actually installed
  something: a converged re-run deployed nothing, and counting it would have
  inflated deployment frequency, which is the one way that journal could read
  better than the truth. `healthbot_record_deploy: false` turns it off.
- **The package is laid out the way Python expects.** Every module is
  `snake_case`. `CacheAwareHelper.py` is `cache.py`, `UtilsHelper.py` is
  `config_files.py`, `AwsAware.py` is `aws/client.py`. The `helper/`, `api/`
  and `interfaces/` trees are gone: AWS plumbing is under `healthbot/aws/`,
  and each notification channel is one module carrying its message and its
  sender. Classes lost the suffixes that were doing no work, so
  `SlackNotificationAware` is `SlackNotifier` and `NotificationAwareInterface`
  is `Notifier`. **If you imported from HealthBot, every path has moved**;
  the four console scripts are unchanged.
- **`ruff` now gates the naming too.** `N`, `A`, `SIM`, `RET`, `RUF`, `C4` and
  `PIE` joined the rule set, so the layout above cannot drift back quietly.
- **The playbook installs into a virtualenv at `/opt/healthbot`.** Not the
  system Python: 24.04 refuses that outright (PEP 668), and on any release it
  keeps twenty of our dependencies out of the OS interpreter. The systemd unit
  runs the console script by absolute path.
- **The AMI is Ubuntu 24.04.** The Packer filter named impish 21.10, which
  reached end of life in July 2022. That is an unpatched base image, and a
  Python three minor versions below what the wheel installs on. Noble is the first
  LTS whose stock `python3` is 3.12.
- **`awscli` is no longer installed on the host.** Ubuntu dropped the package
  at 24.04 and the bot never used it: every AWS call goes through boto3.
- **`healthbot/config/ga.yml` is gone.** It described Universal Analytics
  dimensions for an API Google withdrew, and nothing had read it for years.
- **`IT/packer/etc/example.hcl` is tracked**, so `packer validate` works from
  a fresh clone with no AWS account and no var file of your own.
- **Jinja2 is no longer a runtime dependency.** Nothing templated anything once the Slack message stopped being a template.
- **Python 3.8 to 3.12, Poetry to uv, black/pylint/tox to ruff.** `uv sync`
  builds the environment from `uv.lock`; `make check` is the whole gate.
- **Selenium to Playwright.** The checkout check doesn't need geckodriver or a distro Firefox any more. `playwright install chromium` is the whole browser setup.
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

- **The dead-man's switch can fire.** `HealthBotSilent` asked whether the
  heartbeat's rate was zero. In production the bot is a systemd oneshot, so
  every run is a separate process with its own series carrying a single
  sample, and a rate over any of them is zero however healthy the bot is: the
  alert was true all the time and told you nothing. It now asks whether the
  heartbeat is there at all, which is what a stopped bot actually looks like.
  It pages about twenty minutes after the last run, which is the collector's
  `metric_expiration` plus the alert's `for`, and stays quiet through a
  collector restart. **If you have this alert routed anywhere, it was firing
  or suppressed for reasons that had nothing to do with HealthBot**, and it
  will now behave.
- **Check and run durations land in buckets that can tell them apart.** Both
  histograms used the OpenTelemetry defaults, which start at five seconds,
  and every check here finishes far inside that first bucket, so
  `histogram_quantile` returned the same interpolated 4.75 seconds for every
  check on every dashboard. They now carry explicit boundaries that resolve
  the range a run occupies and reach the ceilings the code declares: the 30
  second ping timeout, the 15 second browser step, and the 300 seconds
  systemd gives the whole run. **Existing history is not converted**: the old
  buckets stay in Prometheus, so a quantile spanning the change reads across
  two different sets of boundaries until the old data ages out.
- **The check duration panel shows a quantile again.** It was taking a rate
  over per-run series, which is zero on a oneshot, so it drew nothing at all.
  It now takes the quantile over the runs inside a fifteen minute window.
- **Panels draw the number that pages you.** Active users, both response
  times and the runs-reporting panel now carry their alert threshold as a
  line, and hold it in view even when the value is nowhere near it. Response
  times carry a unit instead of a note in the title, so the app and web
  panels can be compared.
- **The SLO headline reads in words.** Each tile names the objective from
  `config/slo.yml` and the target it is measured against, rather than
  printing a metric key and leaving the colour to carry the verdict. The
  `healthbot_slo_target` gauge now carries `description` and `objective`
  labels to make that possible.
- **A gauge panel draws one line, not one per run.** Each oneshot run emits
  its own series, so the active-users and response-time panels drew a fresh
  differently-coloured line for every run inside the collector's retention.
  They now show the worst run in view, which is the question the alert asks.

- **The instance can read its own fleet and publish its own alerts.** The role
  Terraform attaches granted Secrets Manager, KMS, CloudWatch and SSM, but not
  `ec2:DescribeInstances` or `sns:Publish`, both of which every run makes. The
  AWS metrics came back empty, which is treated as a failed signal and alerts,
  and then the SNS half of that alert was refused.
- **The example Packer variables tag the image the way Terraform looks for it.**
  They said `sre` and the AMI lookup filters on `SRE`. AWS tag filters match
  exactly, case included, so an image built from the example as-is was invisible
  to the apply that wanted it.
- **An unwritable log directory no longer kills the import.** `healthbot.logs`
  created its directory as an import side effect, so a process that could not
  write there, such as a container running as a system account with no home
  or a read-only install, died on the import rather than on anything it was
  asked to do. It now costs the log file, says so on stderr, and the run continues.
- **The playbook stops copying and deleting the same wheel every run.** It
  staged the wheel and then deleted it at the end, so those two tasks reported
  changed for ever and no run could report `changed=0`. The staged wheel stays
  and superseded ones are removed instead.
- **The local stack no longer publishes Redis to the network.** It was bound
  to every interface with no password, which put the config cache, and the
  alert-gate state with it, where anybody on the network could write a
  suppression and silence a real outage. Every port in `IT/local` and `IT/observability`
  binds to loopback now.
- **A traceback no longer prints the value of every local variable.** Loguru
  turns that on by default, so one uncaught error anywhere below the Secrets
  Manager read would write the Slack token, the Twilio token, the New Relic
  key and the Google service-account key into the journal and the log file.
  The frames are kept; the values are not.
- **The wheel was shipping without one of its modules.** `.gitignore` carried
  an unanchored `secrets.py`, and the build reads that file rather than git's
  index, so `healthbot/aws/secrets.py` was quietly left out of a build that
  reported success. `make check` now refuses a commit where any tracked file
  matches an ignore rule.
- **`ansible-playbook` could not install the wheel at all.** It copied the
  wheel to `/tmp/healthbot.whl` to stay version-independent, and pip refuses a
  wheel whose filename is not `name-version-pytag-abitag-plattag.whl`. The
  staged file keeps the name `uv build` gave it.
- **The playbook is idempotent.** A second run reported two changed tasks
  forever: a `raw` bootstrap that always claims to have changed something, and
  an unconditional `state: restarted` on fail2ban. The first reports what apt
  actually did; the second is `state: started` with a handler that restarts
  only when the jail configuration moves.
- **The Slack alert arrives on a locked phone with its text intact.** It was
  sent as blocks and nothing else, so push notifications and screen readers
  got the bot's name and no content, at the exact moment an alert most needs
  to say something. Every alert now carries a one-line summary alongside.
- **Terraform pins the providers it actually uses.** `cloudinit` and `random`
  were never declared, so only the lock file stopped `init -upgrade` crossing
  a major version.
- **A standing alert backs off instead of repeating every five minutes.** An
  outage that lasted an afternoon sent the same message about fifty times, on
  Slack, SMS and SNS. Repeats now go out after 15 minutes, then 30, then
  hourly: six messages in four hours rather than forty-nine.

  Three rules make that safe to add. **A change in what is wrong always
  speaks**, so checkout going down during a traffic surge is a new alert and
  not a suppressed repeat. **Recovery has to hold**: two consecutive clean
  runs, because a threshold resting on its limit flaps and a backoff that
  resets on the first good run never engages. And **a gate that cannot read
  its own state sends anyway**, because the failure mode has to be a
  duplicate message, never a silent outage.
- **Redis is a cache again, not a dependency.** The client carried no timeout,
  so a hung Redis hung a five-minute batch job, which is the exact failure
  `REQUEST_TIMEOUT_SECONDS` exists to prevent for HTTP. It has connect and
  operation timeouts, and a read that fails is a miss: every caller has a
  source of truth behind it, so the run costs a round trip instead of dying.
- **The Slack message is built as data and serialised once.** It was a Jinja
  template emitting JSON by hand, which is what produced the trailing commas.
  `json.dumps` on a list of blocks makes the whole class of bug impossible.
  A metric that could not be collected now reads `_not collected_` rather than
  rendering blank, because `*ms* Response time` looked like a measurement of
  nothing.

- **The Google Analytics check reads GA4.** It had been calling Universal
  Analytics (`analytics/v3`, `rt:activeUsers`, a `ga:` view id), which stopped
  serving data in July 2023 and was withdrawn a year later, so the metric could
  only ever come back empty. It now calls the GA4 Data API's
  `runRealtimeReport`. **The secret's `view_ids` becomes `ga_property_id`**: a
  GA4 property, numeric or `properties/<id>`.
- **A Google outage costs one metric instead of the whole run.** The check
  raised, and nothing caught it before `main()`, so an API error took the
  checkout and canary results down with it. It returns `None` now, which is
  the "cannot tell" signal the alerting and the SLOs already understand.
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
  anything. It exits non-zero now, and charges only the monitor objective: a
  run that crashed says nothing about the site.
- **A signal that could not be collected now alerts** instead of passing
  silently.
- **A connection failure during the ping sweep folds in as status 0** rather
  than aborting the whole sweep.
- **Credentials are fetched fresh every run and never cached.** Only plain
  parameter values go to Redis.
- **The Slack message is valid JSON.** The metrics loop left a trailing comma
  after its last field, and another after its last metric class, so what Slack received wasn't parseable.
- **A release run by hand only accepts a version.** The workflow pasted its version input and the tag name straight into a shell script, so a crafted value ran as code. Both now reach the script through the environment, and anything that is not `1.2.3` or `1.2.3-rc.1` stops the run.
- **The local stub container runs as its own user and reports its health.** `docker compose ps` in `IT/local/` shows it as healthy once its APIs answer, rather than only as running.
