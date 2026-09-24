# Changelog

Entries say what changed for somebody running HealthBot. The reasoning behind a change is in its commit message. You'll find the detail there, not here.

## [Unreleased]

### Changed

- **The instance comes from the shared module library's `ec2-instance`,** at
  v0.7.0, and a `moved` block carries it across, so the plan updates it in
  place rather than replacing it. What the plan shows:
    - The instance is renamed from `<name> EC2 Instance` to `<name>-01`, and
      its root volume from `<name> EBS` to `<name>-01-root`.
    - Metadata settings the instance already had by default (a hop limit of
      1, instance tags off) are now stated.
    - The zone is no longer pinned to the region's first zone; the subnet
      decides it, as AWS requires.
- **A change to the boot configuration now replaces the instance,** because
  cloud-init reads it only on first boot. The module replaces destroy-first,
  so HealthBot is down for the time a new instance takes to boot.
- **The instance output is the public IP address,** or null without one. It
  was the public DNS name.
- **A plan stops if the instance's name would match HealthBot's own fleet
  filter,** `*<APP_ENVIRONMENT_TAG_NAME>*`, which would make it monitor itself.
  The instance carries the fleet's Environment tag, so only the name kept it
  out, and that was never checked.

Proved against a local emulator; we need more testing. The emulator stores an
instance without the subnet, encryption and public-IP settings it was asked
for, so the current configuration plans a replacement there too. The refactor
adds no forcing change beyond that drift.

## [0.2.0]: 2026-09-23

### Fixed

- **The package reports the version it was released as.** 0.1.0 was tagged
  while the package still called itself 0.1.2, and that is the number every
  span carried as `service.version`. A release now stops if the built package
  reports a different version from its tag.

### Changed

- **Vendor tokens no longer reach Terraform state.** The secret is written as a
  write-only value from variables marked `ephemeral`, so neither state nor a
  saved plan holds a token. Upgrading changes the existing secret version in
  place, emptying its `secret_string` from state, but only while your tfvars
  still match what the first apply wrote. **If the plan instead shows the
  secret version being replaced, your tfvars differ from what the first apply
  wrote, and applying makes them the current secret.** The provider compares
  the two and forces the replacement; how `ignore_changes = [secret_string]`
  acts in that case is not proved, and the plan shows which happens.
  **State written before this still holds the first set of tokens**, so rotate
  them once this is applied. Needs Terraform 1.11 or later. Proved against a
  local emulator only; it needs testing in AWS.
- **The IAM role and instance profile come from the shared module library,**
  at v0.7.0, under the names they already have. `moved` blocks carry both
  across. The plan adds the stack's tags to the instance profile, changes the
  role's `Name` tag to the role's own name, and gives the trust statement the ID
  `TrustServices`; what the role may do does not change. The permission policy
  stays in this configuration, because inside the module it would form a
  dependency loop with the KMS key. Proved against a local emulator only; it
  needs testing in AWS.
- **Every library module is pinned at v0.7.0**, by commit.
- **The log file is opened when a command runs, not when the package is
  imported.** `healthbot --help`, `healthbot --version` and anything importing
  HealthBot as a library no longer create `HB_LOG_DIR` on the way past. Every
  console script still writes the same file to the same place as before.
- **The KMS key and its alias come from the shared module library.** `moved`
  blocks carry an existing key across, so a plan shows its `Name` tag changing
  and nothing else: the key keeps its id, its policy and its fifteen-day
  deletion window. The policy is written out as the one AWS attaches by default,
  so nobody's access changes. Proved against a local emulator only; we need more
  testing before an apply against a real account.
- **`make tf-local` refuses an emulator that is not MiniStack.** The LocalStack
  community image answers the same health path and then fails the seeding with
  a 501 on the RDS cluster, far from anything naming the emulator. The harness
  now says which emulator it found before it starts.
- **The Secrets Manager secret comes from the shared module library too.** Its
  first version is still written once and never overwritten afterwards. A plan
  moves the secret and its version, changes the secret's `Name` tag to the
  secret's own name, and keeps its ARN, so the bot reads the same secret
  throughout. Proved against a local emulator only; we need more testing.
- **The local stack's stub ports can move.** Set `HB_LOCAL_STORE_PORT` and
  `HB_LOCAL_API_PORT` before `make up` when 8080 or 8081 is taken. The
  `healthbot-local` commands and the integration suite read the same two, and
  `run-env` points the bot at a moved storefront through a generated
  `local.d/config/site.yml`. Unset, everything stays on 8080 and 8081.
- **The test suite refuses a first-boot setting the deploy would drop.** Every
  key cloud-init writes into `/etc/healthbot.env` has to be rendered from
  `healthbot_env` or refused by the playbook when missing. A key added to the
  first-boot payload without either now fails `make test`.
- **The two EC2 alarms come from the shared module library.** They keep every
  setting and change only their `Name` tag. No `moved` block can follow an alarm
  keyed by a name that carries the environment, so the next apply replaces both.
  It is the same apply that renames them away from the instance id, so they are
  replaced once, not twice. Planned against a local emulator only, which cannot
  launch the instance the alarms watch; we need more testing.
- **The four SSM parameters come from the shared module library, and every
  module call is pinned to its 0.6.0 release.** `moved` blocks carry the
  parameters across at the same paths, so a plan shows each one's `Name` tag
  changing and nothing replaced. The KMS key, the secret and the alarms plan no
  change from the new pin. Proved against a local emulator only; we need more
  testing.
- **Vendor tokens are rotated by hand, every 90 days.** `SECURITY.md` and the
  *Day to day* section of `docs/on-aws.md` now say which tokens, how often and
  in what order. There is no rotation function and none is planned.
- **The three unused AWS provider aliases are gone.** Nothing referenced them,
  and a plan is unchanged without them. The `profile`, `production_profile` and
  `region` variables they read are still accepted but no longer used.
- **The KMS key has an explicit policy.** The role running the deploy
  administers the key, with any others listed in the new optional
  `kms_admin_arns`, and only the instance role may use it. Before, any IAM
  principal in the account with a permissive enough policy could. **List every
  role that will ever deploy this stack in `kms_admin_arns`**, or a later deploy
  from another role cannot change the key. Proved against a local emulator only;
  we need more testing.
- **`make checkov` scans the infrastructure with the library modules included,**
  and `make check` runs it, so CI does too. Without the downloaded modules checkov
  scored the root alone and passed on nothing. Each finding that does not apply
  here carries a skip with its reason on the module call it belongs to. The first
  run fetches checkov and the modules, which needs the network.
- **The DORA dashboard shows trends, not tiers.** The Elite, High, Medium and Low
  colouring is gone, because its thresholds had no source anybody could check,
  and each stat now carries a sparkline. *Mean time to restore* is renamed
  *failed deployment recovery time*, DORA's current name for it, and a panel says
  that deployment rework rate, DORA's fifth metric, is not collected. Each panel
  says where its number comes from.

## [0.1.0]: 2026-09-21

The first release.

### Added

- **`terraform.tfvars.example` lists every variable a plan needs.** Every
  `*.tfvars` file is gitignored, so a clone had nothing to copy and no way to
  learn what the twenty-four required variables were short of reading
  `variables.tf`. Copy it, replace the values it marks, and a plan runs.

- **`make terraform` refuses a tfvars file that disagrees with `variables.tf`.**
  In both directions: a required variable the example fails to supply, and a
  name in the example that nothing declares. Terraform errors on the first and
  only warns on the second, which is how `ga_view_id` survived the rename to
  `ga_property_id` and left a plan that could not run.
- **The alert says why it fired.** A new section lists every failing signal with
  its reading beside its limit, so nobody compares a table of numbers against a
  threshold file by eye.
- **`healthbot --help` and `healthbot --version`.** Both answer without reading
  config, opening a connection or needing credentials. An argument the command
  doesn't know is now refused rather than ignored.
- **`HB_LOG_LEVEL`**, which defaults to `INFO`. A healthy run is now quiet on the
  console, which is what the guides have always claimed. The log file still
  keeps every `DEBUG` line, so nothing is lost for diagnosing a failed run. Set
  `HB_LOG_LEVEL=DEBUG` for the old behaviour.
- **A drift between an objective and the alert guarding it is reported.**
  `slo.yml` restates `site.yml`'s latency numbers on purpose; when the two stop
  agreeing, each run says so once. Silent while they agree.
- **`HB_CONFIG_DIR` now reaches `slo.yml`.** It was the one config file the
  override could not replace, so the documented way to change a threshold
  guaranteed the drift above on the first edit anybody made.

- **`make tf-local` plans the infrastructure against a local AWS emulator.** It
  needs no AWS account and no credentials: point a LocalStack-compatible
  emulator at `172.17.0.1:4566`, or set `HB_LOCAL_AWS_ENDPOINT` to wherever
  yours listens, then run it. It proves the configuration is coherent and that
  every data source resolves. **It does not prove anything about real AWS** —
  the plan is against an emulator, and that difference is real.

- **A plain statement that the machine image is not scanned.** `SECURITY.md`
  and Step 5 of `docs/on-aws.md` now say that nothing in this repository runs a
  vulnerability scanner over the AMI and that no software bill of materials is
  produced, so you can decide for yourself whether to scan it before you boot
  it. The build has not changed. What changed is that you no longer have to
  assume something is already checking the image.
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
  included. An integration suite drives it.
- **A test suite** where there had been one assertion, covering the AWS,
  canary, notification and telemetry boundaries.
- **Two CI workflows**, path-gated: the Python gate builds and uploads the wheel,
  and the infrastructure gate validates Terraform and the playbook without
  credentials.

### Changed

- **A plan refuses a first-boot payload the instance could not read.** The EC2
  instance now asserts that its `user_data` decodes, in one step, to a
  cloud-config that writes `/etc/healthbot.env`. Nothing was wrong with the
  payload; what was missing was anything that would say so if a future edit
  broke it, because a machine that boots without its environment file looks
  healthy from Terraform and from AWS alike. The assertion reads an
  uncompressed payload, so turning `gzip` on in `data.cloudinit_config.this`
  means changing it too.

- **The first-boot config declares its own content type.** The cloud-init part
  went out as `text/plain` and was handled correctly only because cloud-init
  re-reads the type off the first line of the body. It now says
  `text/cloud-config`, so the right handler is chosen rather than guessed.

- **A deploy refuses to run without `HB_PARAM_PREFIX`.** The playbook renders
  `/etc/healthbot.env` from `healthbot_env`, replacing the whole file including
  the two lines cloud-init wrote at first boot. With the prefix missing from
  `group_vars`, every run afterwards read the packaged `site.yml` prefix instead
  of the one Terraform created, and failed on a parameter that was never going
  to be there. The play now stops before the file is written and says which key
  is missing.

- **The DORA journal's location is a deploy setting, and the repository says
  what is at stake.** Set `healthbot_dora_events` in `group_vars/all.yml`. It
  keeps the old path, so nothing moves unless you move it. The journal is
  written on whichever machine runs `make deploy`, never on the instance, so
  replacing the instance does not touch it; what ends the history is losing that
  path, or two people deploying from two laptops and each keeping half of it.
  `README.md`, `docs/on-aws.md` and `healthbot/dora.py` now all say so where you
  would meet the journal.
- **Every metric changes shape. Read this before you next open your own
  dashboard.** The bot used to export one set of counters per run, each under a
  random `instance` label, holding the single number that run measured. It now
  exports what each run measured as a delta under a stable `instance` label, and
  the collector adds the deltas together, so one counter per machine climbs the
  way a counter is supposed to. No metric is renamed and no label is removed.
  What changes is how you read them:

    - `rate()` and `increase()` work. They returned zero or NaN on everything
      before, which is the defect underneath both of the fixes below.
    - `instance` is now the hostname, not a fresh UUID per run. Set
      `HB_OTEL_INSTANCE_ID` if two bots watch different sites from one host.
    - **`count(healthbot_heartbeat_total)` no longer counts runs.** It was the
      number of live per-run series and it is now 1, because there is one
      series. Counting runs is `increase(healthbot_heartbeat_total[...])`, and
      the same goes for any panel of yours that counted or summed series to
      mean *events in the collector's window*. The four dashboards here are
      already converted.
    - Absence is unchanged, so `HealthBotSilent` and everything else that reads
      liveness still behaves. A series still disappears one `metric_expiration`
      after the last run that touched it, measured at eleven minutes for a ten
      minute setting.
    - Telemetry that is off stays off. None of this happens without
      `HB_OTEL_ENABLED=1` and an endpoint.

  **History is not converted.** The old per-run series stay in Prometheus with
  their old shape, so a window spanning the change reads across both until the
  old data ages out.

- **`make check` refuses a tracked Terraform state file, and the repository says
  why that matters.** State records every value Terraform manages in plaintext,
  and this configuration builds a Secrets Manager secret out of your vendor
  tokens, so a state file from this tree is as sensitive as the tokens in it.
  `.gitignore` has always kept state out of an ordinary `git add`; `make
  tfstate` now refuses a forced one, in CI as well as locally. `SECURITY.md` and
  `IT/terraform/README.md` say what to do about a local copy you find, which is
  to rotate what is in it rather than to quietly delete the file.

- **The repository no longer declares checks that nobody runs.**
  `.pre-commit-config.yaml` listed sixteen hooks and not one had ever run: no
  hook was installed, so the file described work nothing performed. Five of the
  sixteen duplicated `make check`, one ran tfsec, which this project had already
  dropped for being set to never fail, seven were whitespace and file hygiene,
  two were Terraform static analysis nothing here invoked, and one,
  `terraform_docs`, was the only thing keeping the generated table in
  `IT/terraform/README.md` current. That is why the table sat four years stale,
  advertising a variable that no longer exists. Both the config and the
  `.pre-commit-hooks.yaml` beside it are gone, and `pre-commit` has left the dev
  group with it, so `uv sync` installs seven fewer packages.

- **`make check` runs the two checks that were worth keeping.** `terraform-docs`
  now verifies the generated table and fails when it no longer matches
  `variables.tf`, with `make tf-docs` to regenerate it. `shellcheck` runs over
  every tracked file whose shebang says it is shell, which is four scripts that
  nothing was reading before. CI installs `terraform-docs` pinned to a version
  and a checksum, because the check compares generated output byte for byte.

- **`CONTRIBUTING.md` describes what actually happens on a commit.** It said
  `make check` was what the pre-commit hook ran. Nothing ran. It now says the
  repository installs no hook, shows you how to wire one that calls the gate,
  and names the four tools the gate needs on your `PATH`.
- **Two settings in `site.yml` have been renamed, and a run refuses to start
  until you rename them too.** `ping_urls` is now `canary_urls`, and
  `alert_limit` is now `active_users_alert`. Edit your own `site.yml`, or the
  one under `HB_CONFIG_DIR`, and change those two key names; nothing else about
  them changed. `alert_limit` said neither what it limited nor in which
  direction, and the sweep it guards is called a canary everywhere else. A run
  that meets the old name names the new one and stops rather than monitoring
  nothing quietly.

- **One name per thing, across the code, the config, the alerts, the dashboards
  and the docs.** The canary sweep was `pings`, `ping_ok`, `ping_urls`, "All
  configured URLs are running", "Some pings didn't complete",
  `canary_availability` and "Canary probes"; it is **canary** now. The two
  latency objectives were `storefront_latency` and `application_latency`, which
  matched neither the settings that page on them nor each other, and
  *storefront* was also the name of the local stub serving the whole site. They
  are `web_latency` and `app_latency`, matching `web_response_time` and
  `app_response_time`. **Two things outside the repository read these names:**
  the telemetry counter `healthbot.probe.http.status` is now
  `healthbot.canary.http.status` (`healthbot_canary_http_status_total` in
  Prometheus), and the `slo` and `check` label values changed with the names
  above. The shipped dashboards and rules are updated; a dashboard or alert of
  your own that queries the old metric or label keeps reading the old series,
  which stops receiving data. The local stack's chaos switch `pings_down` is now
  `canary_down`.

- **A failing canary sweep now pages.** It never did. The decision to alert was
  a chain of branches beside the table that names every signal, and it had no
  branch for the canary sweep, so every canary URL could answer 503 while the
  `canary_availability` objective burned and no message went anywhere. The two
  are one table now, so they cannot disagree again.

- **The push notification says what is failing.** It looked at the checkout
  journey and the canary sweep only, so a run paging on response time, on a
  traffic surge, or because a signal could not be collected at all arrived on a
  locked phone reading **"all checks passed"**. It now names every failing
  signal with its value and its limit, which is also what a screen reader gets.
  The message header is shorter and carries no emoji shortcode, because that
  text is cut off on a phone and `:robot_face:` renders literally there.

- **An untagged EC2 instance is headed by its instance id.** The alert used to
  carry a heading reading `*NAME TAG NOT ASSIGNED*`, which was a sentence being
  shouted as a title. `metrics.yml`'s `label` is now what heads a shared
  namespace such as RDS; nothing read it before.

- **A missing setting says which one and what to do about it.** A parameter that
  does not exist in Parameter Store failed with `IndexError: list index out of
  range` and a traceback naming no parameter, because SSM returns a missing name
  rather than raising. A missing secret was logged twice, once as a botocore
  exception and again with a traceback. Both now print one line naming the thing
  and the next action, and the run exits 1.

- **A `base_url` written without a trailing slash works.** It used to be joined
  to each path by plain concatenation, so the sweep asked for
  `https://store.example.comcheckout`, got nothing, and paged.

- **The log file is named for a date you can read.** `healthbot_2111326.log` was
  22 November 2021: the format string used loguru's `DDDD`, which is the day of
  the year. It is now `healthbot_2026-09-19.log`.

- **Four settings that did nothing are gone from the deployed environment file.**
  `HB_TAG_NAME`, `HB_DB_IDENTIFIER`, `HB_SECRETS_NAME` and `HB_AWS_PROFILE` were
  written into `/etc/healthbot.env` and read by nothing, while the comment above
  them said they selected the fleet. Which fleet, which database and which
  secret a run uses come from Parameter Store, where Terraform writes them, and
  that is now the only place they live. Anything that set those variables was
  already having no effect. `HB_LOG_LEVEL` joins the file in their place.

- **`product_url` and the four `test.*` keys are gone from `site.yml`.** Nothing
  read any of them, and both guides told you to set `product_url`.

- **`make demo` works with no arguments.** It needed `HB_OTEL_ENABLED` and
  `OTEL_EXPORTER_OTLP_ENDPOINT` set by hand and refused without them, while
  `make up` had just started the collector it wanted. The target now carries the
  endpoint; `make demo OTEL_ENDPOINT=...` points it elsewhere.

- **The onboarding guide's first command no longer starts a production run.** It
  was `healthbot --help`, and nothing parsed arguments, so a brand new reader's
  first command opened Redis, read config and called AWS, then printed a cache
  warning and a traceback.

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
- **The local emulator is MiniStack, and three documents said otherwise.** They
  gave a command creating a container named `ministack` that ran LocalStack
  Community, so every reader who followed them believed they were on one
  emulator and were on another. The free tier of that image does not implement
  RDS, which this tree reads, so `CreateDBCluster` returns 501 and names a
  licence plan, several steps from anything mentioning a database. Two people
  working from the same tree reached opposite conclusions about whether it could
  plan locally, and both were reporting honestly.


- **The burn-rate alerts can fire.** `HealthBotSLOFastBurn` and
  `HealthBotSLOSlowBurn` never could. In production the bot is a systemd
  oneshot, so every run was a separate process exporting its own series with a
  single sample in it, and every SLO rule is a `rate()` or an `increase()` over
  those counters. All five rates were zero, the error ratio, the burn rate and
  the 30-day compliance were all NaN, and NaN is not greater than a threshold,
  so both alerts stayed silent through a bot that was alive and failing every
  check. **That is the case these alerts exist for**: a crashing run still sends
  a heartbeat, so the dead-man's switch is correctly quiet and nothing else was
  watching. Runs now accumulate into one series and the rules read what they
  were always meant to read.
- **The incident dashboard no longer reports a dead monitor as a healthy one.**
  *Store, or the monitor?* asked for a count of bad monitor runs and treated an
  empty answer as zero, so a bot that had stopped reporting read **Monitor
  healthy, look at the store**, which is the opposite of what had happened. The
  worst-burn dial read 0.0 in the same state, and the two failing-check tiles
  read *None*. All four now tell no data apart from no failures and say **NOT
  REPORTING**, using the same liveness test the operations dashboard already
  used, so the two screens cannot disagree about whether the bot is alive.
- **`make tf-local` reseeds the emulator instead of trusting a stale state
  file.** The emulator is a container and loses its resources when it restarts,
  while the harness kept a state file claiming they were still there. The next
  plan then failed on five data sources, and nothing in the message pointed at
  the seeding. `ACTION=clean` now destroys what it created before deleting the
  state, so a later run cannot collide with resources left behind.

- **`make tf-local` plans against the providers the deployment uses.** It copied
  the committed lock file from a path that does not exist, so `init` silently
  resolved its own versions and the plan ran against cloudinit 2.4.1 and random
  3.9.1 where the lock pins 2.4.0 and 3.9.0.
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
  printing a metric key and leaving the colour to carry the verdict. It shows
  how far the objective is above or below its own target, so the sign is the
  verdict and one threshold is right for all five; the panel used to colour
  every objective against a hardcoded 99%, which was wrong for two of them.
  The `healthbot_slo_target` gauge now carries `description` and `objective`
  labels to make that possible.
- **The DORA panels can show what they plot.** Four metrics spanning six
  orders of magnitude shared one linear axis, so three of them were a flat
  line on the floor. They are now two panels, one per unit, and the four
  headline stats carry the published performance bands so a number arrives
  with a scale attached.
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
