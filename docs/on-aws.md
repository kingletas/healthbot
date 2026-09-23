# Running HealthBot on AWS

By the end of this you'll have HealthBot running in your own AWS account: a
small EC2 instance that wakes every five minutes, walks your storefront from
search to checkout in a real browser, folds in New Relic, Google Analytics and
CloudWatch, and speaks up on Slack, SMS and SNS only when something is wrong.

Budget about half a day the first time. Most of that is collecting credentials
from four vendors, not working with AWS.

If you have not seen HealthBot run yet, start with
[from-nothing.md](from-nothing.md) instead. It takes twenty minutes, needs no
AWS account, and ends with a real alert. Knowing what a healthy run looks like
makes the rest of this much easier to read.

## Contents

- [What HealthBot needs from AWS](#what-healthbot-needs-from-aws)
- [How the three tools fit together](#how-the-three-tools-fit-together)
- [Step 1: install the tools](#step-1-install-the-tools)
- [Step 2: what must already exist in your account](#step-2-what-must-already-exist-in-your-account)
- [Step 3: collect the vendor credentials](#step-3-collect-the-vendor-credentials)
- [Step 4: create the state bucket](#step-4-create-the-state-bucket)
- [Step 5: build the machine image](#step-5-build-the-machine-image)
- [Step 6: write your variables file](#step-6-write-your-variables-file)
- [Step 7: create the infrastructure](#step-7-create-the-infrastructure)
- [Step 8: install the bot](#step-8-install-the-bot)
- [Step 9: point it at your store](#step-9-point-it-at-your-store)
- [Step 10: check it works](#step-10-check-it-works)
- [Day to day](#day-to-day)
- [What it costs](#what-it-costs)

## What HealthBot needs from AWS

Six things. If any of the words are new, the sentence beside each one explains
it.

| It needs | What that means | Who creates it |
|---|---|---|
| A machine to run on | One small EC2 instance, which is a virtual server you rent by the hour | Terraform, in this repository |
| A machine image | An AMI, a snapshot of a disk that new instances are cloned from. This one is Ubuntu 24.04 | Packer, in this repository |
| Somewhere to keep credentials | Secrets Manager holds one JSON blob with every vendor token, encrypted under a key only this bot can use | Terraform, in this repository |
| Somewhere to keep settings | Parameter Store holds four plain values that are not secret, such as which database to look at | Terraform, in this repository |
| A network to sit in | A VPC, which is a private network inside AWS, and a subnet, which is one slice of it | You, beforehand |
| Things to measure | A database cluster and a fleet of web servers to read CloudWatch metrics from, and an SNS topic to publish alerts to | You, beforehand |

The last row is the one to plan for. **HealthBot reads your infrastructure, it
does not create it.** Terraform looks your database cluster and your alert topic
up by name, and stops at the first second if they are not there.

## How the three tools fit together

Three tools, in a fixed order, each handing something to the next.

```text
   Packer                Terraform                 Ansible
   IT/packer             IT/terraform              IT/ansible
      │                       │                        │
      │ builds                │ creates                │ installs
      ▼                       ▼                        ▼
   an AMI  ──────────▶  EC2 instance           /opt/healthbot venv
   Ubuntu 24.04         KMS key                Chromium browser
                        Secrets Manager        systemd timer, every 5 min
                        4 SSM parameters              │
                        IAM role                      │
                             ▲                        │
                             └── read on every run ───┘

   Your VPC, subnet, RDS cluster and SNS topic
   are looked up by Terraform, never created by it.
```

Read the arrow back from Ansible to Terraform carefully. The bot on the instance
carries no credentials of its own. Every five minutes it asks Parameter Store
which secret to open, opens it, and throws the values away when the run ends.
Nothing sensitive is ever written to the machine's disk.

## Step 1: install the tools

Four tools on your own machine, plus AWS access.

`uv` manages Python and builds the deployable package. It installs its own
Python 3.12, so you do not need one:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Terraform must be **1.11 or newer**: the write-only secret value needs 1.11, and
the state locking this repository uses needs 1.10. Install it from the
[HashiCorp guide](https://developer.hashicorp.com/terraform/install) and check:

```bash
terraform version
```

Packer, from the
[HashiCorp guide](https://developer.hashicorp.com/packer/install), and Ansible:

```bash
python -m pip install --user ansible
```

The AWS CLI, so Terraform and Packer can find your credentials. HealthBot itself
never uses it, because every AWS call in the bot goes through boto3:

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && sudo ./aws/install -u
```

Then create access keys in the IAM console under your own user, and enter them
at the prompt:

```bash
aws configure
```

The identity you configure needs to create and read EC2 instances, IAM roles and
policies, KMS keys, SSM parameters, Secrets Manager secrets, S3 objects and
CloudWatch alarms.

Finally, clone the repository and build the local environment:

```bash
git clone https://github.com/kingletas/healthbot && cd healthbot && make install
```

## Step 2: what must already exist in your account

Terraform reads these by name rather than creating them. Write their ids down
before you go further, because a missing one stops the run immediately with an
error about a data source.

| What | The variable that names it | Where to find it |
|---|---|---|
| A VPC | `vpc_id` | VPC console, or `aws ec2 describe-vpcs` |
| A subnet inside it | `subnet_id` | VPC console, under Subnets |
| An RDS or Aurora cluster | `db_cluster_identifier` | RDS console, the cluster identifier column |
| An SNS topic | `sns_name` | SNS console, the topic name, not its ARN |

You also need the web servers HealthBot will read CloudWatch metrics from, and
they have to carry two tags in a particular shape:

- **`Environment`** is your environment name in title case, a dash, then the
  suffix, which defaults to `FLEET`. An environment of `production` looks for
  `Production-FLEET`.
- **`Name`** contains your tag name in upper case. A tag name of `web` looks for
  anything matching `*WEB*`.

If the fleet is not tagged that way the metrics come back empty, and a signal
that cannot be collected is treated as a failure rather than a pass. That is
deliberate, and it means mis-tagged instances alert rather than going quiet.

## Step 3: collect the vendor credentials

This is the slow part and none of it is AWS. Gather all of it before you write
the variables file, because Terraform wants every value at once.

| Vendor | What to get | Where |
|---|---|---|
| New Relic | A User API key | New Relic, under API keys |
| Google Analytics | A service account JSON key file, and the numeric GA4 property id | Google Cloud console |
| Slack | A bot token, and the channel to post into | Slack app settings, OAuth and Permissions |
| Twilio | Account SID, auth token, the sending number, and the number to text | Twilio console |

The Google Analytics one has a second half that is easy to miss. Creating the
service account in Google Cloud is not enough: go into Google Analytics itself,
into **Admin, Property Access Management**, and add the service account's email
address as a Viewer. Without that, HealthBot authenticates successfully and then
reads nothing.

The property id must be a GA4 one, numeric or `properties/<id>`. The old
Universal Analytics view id has not worked since Google withdrew that API in
July 2024.

Save the Google JSON key outside the repository. You point at it by path, and
Terraform base64-encodes its contents into the secret for you.

## Step 4: create the state bucket

Terraform keeps a file recording everything it has created, so that next time it
knows what already exists. That file is called **state**, and it belongs in S3
rather than on your laptop.

Bucket names are global, so pick one nobody has used. Turn versioning on, so a
bad write can be rolled back:

```bash
aws s3api create-bucket --bucket your-unique-terraform-state --region us-east-2 --create-bucket-configuration LocationConstraint=us-east-2
```

```bash
aws s3api put-bucket-versioning --bucket your-unique-terraform-state --versioning-configuration Status=Enabled
```

Then tell Terraform about it. The bucket is yours rather than this
repository's, so the file naming it is not committed here:

```bash
cd IT/terraform && cp backend.hcl.example backend.hcl
```

Open `backend.hcl` and set `bucket`, `key` and `region`. The `key` is just the
path inside the bucket, so `production/healthbot/terraform.tfstate` is fine.

You do not need a DynamoDB table. Terraform 1.10 locks through S3 itself with
`use_lockfile`, which `backend.tf` already sets, so skip that step wherever you
read it.

## Step 5: build the machine image

Packer starts a temporary EC2 instance, lays down the base packages, takes a
picture of the disk, and throws the instance away. That picture is the AMI
Terraform boots.

The image carries the operating system and nothing else. HealthBot itself goes
on in Step 8, which means a new version of the bot never needs a new image.

> **Nothing here scans that image.** No step runs a vulnerability scanner over
> the AMI and no software bill of materials is produced, so the image is only as
> current as the packages on the day you built it and there is no inventory of
> what is on it. Scan it with your own tool before you boot it if that matters
> where you work, and rebuild when Ubuntu patches the base image.
> [SECURITY.md](../SECURITY.md) says it in full.

```bash
cd IT/packer && packer init .
```

Copy the tracked example and set your own values:

```bash
cp etc/example.hcl etc/dev.hcl
```

Change the names to suit you, but leave `tag_service` as `SRE`. Terraform finds
the image by that tag, and AWS tag filters match exactly, case included.

The AWS profile and subnet come from the environment rather than the file, so
nothing about your account is written down:

```bash
PACKER_AWS_PROFILE=default PACKER_SUBNET_ID=subnet-xxxxxxxx packer build -var-file=etc/dev.hcl .
```

The build prints an AMI id when it finishes. Terraform finds the image by tag
rather than by id, so you do not need to record it.

## Step 6: write your variables file

Terraform needs about twenty values. Create `IT/terraform/prod.tfvars`:

```hcl
name        = "healthbot"
environment = "production"
region      = "us-east-2"
profile     = "default"

# Looked up, never created. These must already exist.
vpc_id                = "vpc-xxxxxxxx"
subnet_id             = "subnet-xxxxxxxx"
db_cluster_identifier = "your-aurora-cluster"
sns_name              = "YourAlertTopic"

# Which fleet to pull CloudWatch metrics from.
app_environment_name     = "production"
app_environment_tag_name = "web"

# The instance itself.
instance_type = "t3.micro"
volume_type   = "gp3"
volume_size   = 20

# The bot reaches your storefront and four vendor APIs on every run, so in a
# public subnet it needs an address. In a private subnet, remove this and give
# the subnet a NAT gateway instead.
associate_public_ip_address = true

ssh_key = {
  "public"  = "~/.ssh/healthbot.pub",
  "private" = "~/.ssh/healthbot",
}

# Your own address, with /32 on the end. Nothing else needs to reach this host.
ingress_map = {
  ssh = {
    from_port   = 22,
    to_port     = 22,
    protocol    = "tcp",
    cidr_blocks = ["203.0.113.4/32"]
  }
}

egress_map = {
  from_port   = 0,
  to_port     = 0,
  protocol    = "-1",
  cidr_blocks = ["0.0.0.0/0"]
}

# The vendor credentials from Step 3.
new_relic_api    = "NRAK-..."
slack_token      = "xoxb-..."
user_slack_token = "xoxp-..."
king_slack_token = "xoxb-..."
slack_channel    = "#alerts"
twilio_account   = "AC..."
twilio_token     = "..."
twilio_from      = 15550001111
twilio_to        = 15550002222
ga_property_id   = "123456789"
secrets_path     = "~/.config/healthbot/ga-key.json"
```

Two things in that file to get right. **The SSH rule** should carry your own
address and nothing wider. **The file holds live credentials**, so keep it mode
600 and never commit it. It is already covered by `.gitignore`.

If you deploy outside `us-east-2`, set `alarm_actions` as well. It defaults to
an EC2 reboot ARN with the region written into it, and an ARN from the wrong
region names an action that cannot run:

```hcl
alarm_actions = ["arn:aws:automate:eu-west-1:ec2:reboot"]
```

## Step 7: create the infrastructure

Point Terraform at your backend. You only do this once:

```bash
cd IT/terraform && terraform init -backend-config=backend.hcl
```

Look at what it intends to do before it does anything:

```bash
terraform plan -var-file=prod.tfvars
```

You should see about fifteen resources to add: a KMS key and alias, a Secrets
Manager secret and its first version, four SSM parameters, an IAM role, instance
profile and policy, a security group, a key pair, the EC2 instance, and two
CloudWatch alarms. An error about a data source instead means something from
Step 2 is missing or named differently.

```bash
terraform apply -var-file=prod.tfvars
```

Terraform prints the instance's public DNS name and the Parameter Store prefix
it created. You need both in the next step.

The first apply writes your vendor credentials into Secrets Manager as a
write-only value, so they never reach Terraform state or a saved plan, and then
never touches them again. **Rotating a token is something you do in the Secrets
Manager console.** To push a whole new set from this file instead, raise
`secret_string_wo_version` in `IT/terraform/main.tf` and apply; nothing is
written while that number stays the same.

**Upgrading a stack that was seeded before this change:** the plan should show
the secret version changed in place. If the plan instead shows the secret
version being replaced, your tfvars differ from what the first apply wrote,
and applying makes them the current secret. How the module's
`ignore_changes = [secret_string]` acts in that case is not proved, so read the
plan before you apply it.

## Step 8: install the bot

Build the package. It is built fresh each time and never stored in the
repository:

```bash
make build
```

Write `IT/ansible/inventory` with the DNS name Terraform printed. An inventory
describes one deployment, so it is yours rather than the repository's:

```ini
[healthbot]
ec2-203-0-113-4.us-east-2.compute.amazonaws.com

[healthbot:vars]
ansible_user=ubuntu
ansible_ssh_private_key_file=~/.ssh/healthbot
```

Then tell the playbook about your deployment. Open
`IT/ansible/group_vars/all.yml` and set `healthbot_env` to match what Terraform
created:

```yaml
healthbot_env:
    HB_PARAM_PREFIX: "/healthbot-production-sm/manager/"
    HB_ENVIRONMENT: "production"
    HB_LOG_LEVEL: "INFO"
    HB_LOG_DIR: "/var/log/healthbot"
    PLAYWRIGHT_BROWSERS_PATH: "/opt/ms-playwright"
    HB_OTEL_ENABLED: "0"
```

`HB_PARAM_PREFIX` is the one to get exactly right: it is the Parameter Store
path the run reads its four settings from, and Terraform derives it from your
`name` and `environment`.

Which EC2 fleet, which RDS cluster and which secret the run uses are not in this
file. They are the four parameters under that prefix, which Terraform wrote, so
the deploy cannot disagree with them. Change a fleet by changing the parameter,
not the host.

Install the collections the playbook uses, then deploy:

```bash
make collections
```

```bash
make deploy
```

When it finishes, each host has fail2ban and Redis, the package in its own
virtual environment at `/opt/healthbot`, the Chromium the checkout journey
drives in `/opt/ms-playwright`, an unprivileged `healthbot` account with no
login shell, and `/etc/healthbot.env`. A systemd timer runs the bot every five
minutes, with up to a minute of jitter.

Run it a second time. A correct run reports `changed=0`.

The deploy also appends one line to the DORA journal, on the machine you ran
`make deploy` from rather than on the instance. That file is the whole deploy
history and nothing rebuilds it, so replacing the instance costs you nothing
and losing that path costs you everything. Set `healthbot_dora_events` in
`group_vars/all.yml` to somewhere shared and backed up if more than one person
deploys, or the history splits quietly between their home directories.

## Step 9: point it at your store

The shipped `healthbot/config/site.yml` describes `store.example.com`. Rather
than editing it, put your own `site.yml` on the instance and set `HB_CONFIG_DIR`
to its directory. Anything your file leaves out falls back to the packaged one,
so an override is usually the top few values:

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

## Step 10: check it works

SSH to the instance and look at the timer:

```bash
systemctl list-timers healthbot.timer
```

Force a run rather than waiting, and read what it did:

```bash
sudo systemctl start healthbot.service && sudo journalctl -u healthbot.service -n 50 --no-pager
```

A healthy run **says nothing**. That surprises people, and it is the point.
Check the exit status rather than looking for output. A non-zero exit means
HealthBot broke, not that your store did, and a run that died is charged to the
monitor's own objective rather than the site's.

Then prove the other direction, because a green run tells you nothing about
whether the alarm works. Point `base_url` at a path that does not exist, run it
once, and confirm the message arrives in Slack. Put it back, and confirm the
next run is quiet again. Recovery needs two consecutive clean runs before it
counts, so wait for the second one.

A failed checkout journey leaves evidence behind: a screenshot, the page HTML,
and a Playwright trace you can replay to see what the browser saw.

```bash
sudo ls -t /var/log/healthbot | head -5
```

## Day to day

**Shipping a change.** `make deploy` builds the wheel and installs the newest
one. The play is idempotent, so a deploy that changes nothing reports
`changed=0`.

**Rotating a credential.** Rotate every vendor token by hand at least every 90
days: the Twilio auth token, the three Slack tokens, the New Relic API key and
the Google service account key. Issue the new one at the vendor, edit the secret
in the Secrets Manager console, then revoke the old one. The next run picks it
up, because credentials are fetched fresh every run and never cached. Nothing
rotates them for you: the secret has no rotation function, on purpose.

**Changing a threshold.** Edit the `site.yml` your `HB_CONFIG_DIR` points at.
No deploy needed.

**Turning telemetry on.** Set `HB_OTEL_ENABLED` to `1` and
`OTEL_EXPORTER_OTLP_ENDPOINT` to your collector in `healthbot_env`, then deploy.
Without both, the telemetry layer is a no-op. The collector on the other end
needs a `deltatocumulative` processor in its metrics pipeline, because the bot
runs as a oneshot and exports each run as a delta; without it every run lands as
its own single-sample series and no burn-rate alert can fire.
`IT/observability/README.md` covers the stack that receives it.

**Reading the logs.** `journalctl -u healthbot.service` for the run,
`/var/log/healthbot` for the evidence a failed checkout leaves.

## What it costs

Prices move and vary by region, so check the current pricing pages. The rough
shape for the bot itself:

| Piece | Order of magnitude |
|---|---|
| One `t3.micro` instance, always on | A few dollars a month |
| 20 GB of encrypted disk | About two dollars a month |
| One KMS key | About one dollar a month |
| One Secrets Manager secret | Under a dollar a month |
| Four SSM parameters, standard tier | Free |
| Two CloudWatch alarms | Cents |
| S3 state bucket | Cents |

The expensive pieces are the ones HealthBot does not create: the database
cluster it reads, and a NAT gateway if you put the instance in a private subnet.
Twilio bills per message, which is a good reason to confirm the alert backoff is
working before leaving it running unattended.

## Where to go next

- [README](../README.md): what each check reads and how it is configured
- [from-nothing.md](from-nothing.md): the same bot on a laptop, in twenty minutes
- [IT/observability/README.md](../IT/observability/README.md): the telemetry stack
- [CONTRIBUTING.md](../CONTRIBUTING.md): the shape a change should arrive in
