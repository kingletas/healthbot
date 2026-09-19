# From nothing to a working HealthBot

By the end of this you'll have HealthBot checking a storefront on your own
laptop: a real browser walking a checkout, a canary sweep, metrics from three
APIs, and an alert landing in a chat client. It needs no AWS account and no
credentials of any kind.

Budget about twenty minutes, most of it waiting for Docker.

## Contents

- [What this is](#what-this-is)
- [Step 1: install it](#step-1-install-it)
- [Step 2: bring up the world it watches](#step-2-bring-up-the-world-it-watches)
- [Step 3: run it](#step-3-run-it)
- [Step 4: break something](#step-4-break-something)
- [Pointing it at a real store](#pointing-it-at-a-real-store)
- [What you get for free](#what-you-get-for-free)
- [Where to go next](#where-to-go-next)

## What this is

HealthBot answers one question every five minutes: **can a customer actually buy
something right now?**

Most monitoring answers a different question: is the server up, is CPU high, did
the health endpoint return 200. All of those can be green while checkout is
broken.

So HealthBot checks from the outside, the way a customer would. It opens a real
browser, searches for a product, adds it to the cart and loads the checkout page.
Then it folds in what the other tools already know, which is response times
from New Relic, active users from Google Analytics, and instance and database
metrics from CloudWatch. From all of that it decides whether anyone needs
waking up.

The hard part of running something like this isn't the checks. It's that you
can't develop against production, and a monitor you can't test is a monitor you
can't trust. So HealthBot ships the whole world it watches: a stub storefront, a
chat server, and an AWS emulator. That is what you are about to start.

## Step 1: install it

You need [uv](https://docs.astral.sh/uv/) and Docker. uv installs its own Python,
so you don't need one.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
git clone https://github.com/kingletas/healthbot && cd healthbot && make install
```

`make install` builds the virtualenv from the lockfile and downloads the Chromium
that drives the checkout journey. The browser download is the slow part.

Check that worked. This reads no config, opens no connection and needs no
credentials, so it answers before anything else exists:

```bash
uv run healthbot --version
```

`uv run healthbot --help` lists every setting you can change.

## Step 2: bring up the world it watches

Two stacks, and they want these ports to themselves: 4566, 8080, 8081, 8065,
3000, 9090 and 4318. If something else on your machine holds one, stop it first,
or Docker refuses the whole stack with `port is already allocated`.

The first stack is the AWS emulator. It has to be MiniStack, and a substitute
that merely answers the same API will not do:

```bash
docker run -d --name ministack -p 4566:4566 ministackorg/ministack:1.5.8
```

MiniStack speaks the LocalStack API on the same port and health path, so it is a
drop-in for anything expecting one. What is not interchangeable is the coverage.
This tree reads an RDS cluster, and the free tier of the emulator it replaced
does not implement RDS at all: `CreateDBCluster` returns 501 and names a licence
plan, several steps away from anything that mentions a database. Pin a version
rather than taking `latest`, so an image change never arrives in the middle of a
debugging session.

The second is HealthBot's own: a stub storefront, a stub for New Relic and
Google Analytics, Mattermost standing in for Slack, and the observability stack
that catches the telemetry:

```bash
make up
```

Give Mattermost a minute on its first start, because it migrates its own schema before
it answers. Then fill the emulator with the parameters, secrets, an EC2 instance and
an alert topic that a real run expects to find:

```bash
make seed
```

## Step 3: run it

`make run-env` prints the run command with every seam spelled out: which stub
stands in for which service, and nothing hidden:

```bash
make run-env
```

Copy what it prints and run it. On a healthy stack the run exits 0 and **says
nothing**. That surprises people, and it's the point: a monitor that speaks when
everything is fine trains you to ignore it. Check the exit status rather than
looking for output:

```bash
echo $?
```

Open <http://localhost:3000> for Grafana, where the provisioned dashboards show
what the run emitted. If you'd rather see the whole pipeline move without
waiting for real runs, `make demo` drives it with synthetic ones through the same
production code path.

## Step 4: break something

A green run proves the quiet path. It proves nothing about the alarm, and both
directions matter. The stub storefront has chaos switches:

```bash
curl -s -X POST http://localhost:8081/control -d '{"checkout_down": true}'
```

Run the bot again. It still exits 0, because the run itself worked, and that
is the distinction that matters: a non-zero exit means HealthBot broke, not that your
store did. What changes is that an alert is now waiting in Mattermost's
`~town-square` at <http://localhost:8065> (`sre@local.test` /
`SuperSecret-123`). It opens with the line a locked phone would show, which
names what is failing, and the limit it passed where the signal has one.

A failed checkout journey also leaves evidence in the log directory: a
screenshot, the page HTML, and a Playwright trace you can replay. `make run-env`
points `HB_LOG_DIR` at `local.d/evidence` for this walkthrough:

```bash
ls -t local.d/evidence | head -3
```

Set `HB_LOG_DIR` yourself to put it somewhere else. Unset, it is
`~/.local/state/healthbot/logs`, and the deployed host uses `/var/log/healthbot`.

Turn it back on with `{"checkout_down": false}`, and confirm the next run is
quiet again. Recovery has to be proved too. The other switches are
`canary_down`, `ga_surge` and `nr_slow`; `IT/local/README.md` says what each one
breaks and which alert it should reach.

When you're done:

```bash
make down
```

## Pointing it at a real store

The shipped `healthbot/config/site.yml` describes `store.example.com`. Rather
than editing it, put your own `site.yml` in a directory of your choosing and set
`HB_CONFIG_DIR` to that directory. Anything your file does not carry falls back
to the packaged one, so an override is usually just the top few values:

```yaml
base_url: https://your-store.example/
search_term: "something your search finds"
canary_urls:
    - checkout
    - checkout/cart
```

The thresholds below those decide when a run is worth waking somebody for.
Each is an upper bound and they do not share a unit: `active_users_alert` is a
count of realtime users, `app_response_alert` is milliseconds and
`web_response_alert` is seconds. Start with
the shipped numbers, watch for a couple of weeks, then move them once you know
what normal looks like on your own store. A threshold that fires when nothing is
wrong is worse than no threshold, because it teaches everybody to ignore the
channel.

Everything else, meaning New Relic keys, Google Analytics credentials and the
Slack and Twilio tokens, comes from AWS Secrets Manager at run time and is
never cached. The
Terraform under `IT/terraform` provisions that, and `IT/ansible` puts the bot on
a host with a systemd timer. Neither is required to run it locally.

## What you get for free

Things you'd otherwise build yourself:

- **Evidence when it fails.** A screenshot, the page HTML and a replayable trace
  in the log directory, so you can see what the browser saw instead of
  guessing.
- **Honest exit codes.** A crashed run exits non-zero and charges only the
  monitor's own objective. A run that died says nothing about your store, so it
  never counts against it.
- **A signal that cannot be collected is treated as a failure**, not as a pass.
- **Objectives and burn-rate alerting.** Five SLOs, multi-window burn rates, and a
  dead-man's switch that fires when HealthBot itself goes quiet.
- **DORA metrics** from an append-only journal, joined to real commit times.
- **The whole local environment**, which is what lets you change any of this
  without pointing a half-finished monitor at a live store.

## Where to go next

- [README](../README.md): what each check reads and how it is configured
- [IT/local/README.md](../IT/local/README.md): the seams, and the gotchas
- [IT/observability/README.md](../IT/observability/README.md): the telemetry stack
- [CONTRIBUTING.md](../CONTRIBUTING.md): the shape a change should arrive in
