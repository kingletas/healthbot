#!/usr/bin/env bash
#
# Run terraform against the local AWS emulator instead of a real account.
#
# Purpose: `terraform validate` only proves the configuration parses and that
# its references resolve. `plan` is the far stronger check -- it exercises
# provider-level argument validation, resolves data sources and propagates
# computed values -- and it normally needs a real account to do any of that.
#
# This cannot reach real AWS. The credentials are the literal string "test",
# every endpoint is redirected to a container on this machine, and the endpoint
# is refused unless it resolves to a local host. The same refusal the seeding
# command already applies, for the same reason.
#
# It runs in a generated root outside the repository, for two reasons.
# Terraform auto-loads terraform.tfvars from the working directory and that
# file holds real vendor credentials, so a generated root that symlinks the
# tracked HCL and supplies invented values of its own is a structural
# guarantee rather than an argument about variable precedence. And the
# security scanners in the commit gate walk the whole tree rather than the
# staged files, so generated HCL left anywhere inside it fails the gate.
#
# Usage:
#   tf-local.sh prereq          Create what the data sources read, then stop
#   tf-local.sh [plan]          Plan the configuration (the default)
#   tf-local.sh apply           Apply it
#   tf-local.sh destroy         Destroy it
#   tf-local.sh clean           Remove the generated root and its state
#   tf-local.sh <other> [args]  Any other terraform subcommand, passed through
#
# Environment overrides:
#   HB_LOCAL_AWS_ENDPOINT   emulator URL (default http://172.17.0.1:4566)
#   HB_LOCAL_TF_ROOT        generated root (default under XDG_STATE_HOME)

set -euo pipefail

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { sed -n '2,/^set -/p' "$0" | sed 's/^# \{0,1\}//;$d'; exit 0; }

ENDPOINT="${HB_LOCAL_AWS_ENDPOINT:-http://172.17.0.1:4566}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${HB_LOCAL_TF_ROOT:-${XDG_STATE_HOME:-${HOME}/.local/state}/healthbot/ministack}"

# The emulator binds to the docker bridge address, which is reachable from the
# host and from every container and not from the LAN. No public AWS endpoint
# resolves to any of these, so a typo cannot point this at a real account.
LOCAL_HOSTS=" localhost 127.0.0.1 ::1 172.17.0.1 ministack localstack "

require_local() {
    local host
    host="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).hostname or "")' "$ENDPOINT")"
    if [[ "$LOCAL_HOSTS" != *" $host "* ]]; then
        echo "refusing non-local AWS endpoint ${ENDPOINT} (host ${host})" >&2
        exit 1
    fi
}

# python3 rather than curl: the emulator image ships neither curl nor wget, so
# every probe against it in this repository is written this way.
require_up() {
    python3 - "$ENDPOINT" <<'PY' || {
import sys, urllib.request
try:
    with urllib.request.urlopen(f"{sys.argv[1]}/_localstack/health", timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
        echo "The local AWS emulator is not answering at ${ENDPOINT}." >&2
        echo "Start a LocalStack-compatible emulator on that endpoint first." >&2
        exit 1
    }
}

# Fake by construction. If the endpoint override ever failed to apply, these
# credentials cannot authenticate against real AWS: the request fails rather
# than succeeding somewhere it should not.
export_credentials() {
    unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ROLE_ARN AWS_WEB_IDENTITY_TOKEN_FILE
    unset AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
    export AWS_SHARED_CREDENTIALS_FILE=/dev/null
    export AWS_CONFIG_FILE=/dev/null
    export AWS_EC2_METADATA_DISABLED=true
    export AWS_ACCESS_KEY_ID=test
    export AWS_SECRET_ACCESS_KEY=test
    export AWS_SESSION_TOKEN=test
    export AWS_REGION=us-east-1
    export AWS_DEFAULT_REGION=us-east-1
    export AWS_SKIP_CREDENTIALS_VALIDATION=true
    export AWS_SKIP_REQUESTING_ACCOUNT_ID=true
    # The provider reads this, so the deployable configuration needs no
    # emulator-specific branch: it is redirected by URL, never by a code path.
    export AWS_ENDPOINT_URL="$ENDPOINT"
    export AWS_S3_USE_PATH_STYLE=true
}

# Symlinked rather than copied, and rebuilt on every run, so the generated root
# cannot drift from the configuration it is supposed to be proving.
build_root() {
    mkdir -p "${ROOT}/assets"
    find "$ROOT" -maxdepth 1 -name '*.tf' -type l -delete
    local file
    while read -r file; do
        ln -sf "${HERE}/${file}" "${ROOT}/${file}"
    done < <(cd "$HERE" && git ls-files '*.tf' | sed 's|^IT/terraform/||')

    # The committed lock comes too, or init resolves its own versions and the
    # run proves argument validation against providers the deployment will not use.
    ln -sf "${HERE}/IT/terraform/.terraform.lock.hcl" "${ROOT}/.terraform.lock.hcl"

    cat > "${ROOT}/zz_ministack_override.tf" <<'OVERRIDE'
# Generated by tf-local.sh. Local state for the emulator run: the committed
# backend is S3 and is never reached from here.
terraform {
  backend "local" {
    path = "ministack.tfstate"
  }
}
OVERRIDE
}

prereq() {
    mkdir -p "${ROOT}/prereq"
    cat > "${ROOT}/prereq/main.tf" <<'PREREQ'
# What the HealthBot root reads through data sources. Generated into local.d by
# tf-local.sh; never part of the deployable configuration.
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~>6.61.0"
    }
  }
}

provider "aws" {}

resource "aws_vpc" "this" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "healthbot-ministack" }
}

resource "aws_subnet" "this" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = "10.42.1.0/24"
  availability_zone = "us-east-1a"
  tags              = { Name = "healthbot-ministack" }
}

resource "aws_sns_topic" "this" {
  name = "healthbot-ministack-alerts"
}

resource "aws_rds_cluster" "this" {
  cluster_identifier  = "healthbot-ministack-aurora"
  engine              = "aurora-postgresql"
  master_username     = "example"
  master_password     = "example-not-a-real-password"
  skip_final_snapshot = true
}

# The root selects its AMI by owner and by the Service tag, so the emulator
# needs one carrying that tag before any plan can resolve it.
resource "aws_ebs_volume" "this" {
  availability_zone = "us-east-1a"
  size              = 8
}

resource "aws_ebs_snapshot" "this" {
  volume_id = aws_ebs_volume.this.id
}

resource "aws_ami" "this" {
  name                = "healthbot-ministack"
  virtualization_type = "hvm"
  root_device_name    = "/dev/xvda"

  ebs_block_device {
    device_name = "/dev/xvda"
    snapshot_id = aws_ebs_snapshot.this.id
    volume_size = 8
  }

  tags = {
    Name    = "healthbot-ministack"
    Service = "SRE"
  }
}

output "vpc_id" { value = aws_vpc.this.id }
output "subnet_id" { value = aws_subnet.this.id }
output "sns_name" { value = aws_sns_topic.this.name }
output "db_cluster_identifier" { value = aws_rds_cluster.this.cluster_identifier }
PREREQ

    (cd "${ROOT}/prereq" && terraform init -input=false -no-color >/dev/null && terraform apply -auto-approve -input=false -no-color)
}

# Every value here is invented and none of it resembles a real credential. The
# key pair and the service account file are generated throwaways: the
# configuration reads both off disk, so they have to exist before a plan runs.
write_variables() {
    local vpc subnet sns database
    vpc="$(cd "${ROOT}/prereq" && terraform output -raw vpc_id)"
    subnet="$(cd "${ROOT}/prereq" && terraform output -raw subnet_id)"
    sns="$(cd "${ROOT}/prereq" && terraform output -raw sns_name)"
    database="$(cd "${ROOT}/prereq" && terraform output -raw db_cluster_identifier)"

    [[ -f "${ROOT}/assets/ministack_key" ]] || ssh-keygen -q -t ed25519 -N '' -C healthbot-ministack -f "${ROOT}/assets/ministack_key"
    printf '{"type":"service_account","project_id":"healthbot-ministack"}\n' > "${ROOT}/assets/ga-service-account.json"

    cat > "${ROOT}/ministack.auto.tfvars" <<VARIABLES
# Invented values for the local emulator, generated by tf-local.sh.
name                     = "healthbot"
environment              = "local"
region                   = "us-east-1"
profile                  = null
app_environment_name     = "local"
app_environment_tag_name = "web"

vpc_id                = "${vpc}"
subnet_id             = "${subnet}"
sns_name              = "${sns}"
db_cluster_identifier = "${database}"

ssh_key      = { public = "${ROOT}/assets/ministack_key.pub" }
secrets_path = "${ROOT}/assets/ga-service-account.json"

ingress_map = {
  ssh = { from_port = 22, to_port = 22, protocol = "tcp", cidr_blocks = ["10.42.0.0/16"] }
}
egress_map = { from_port = 0, to_port = 0, protocol = "-1", cidr_blocks = ["0.0.0.0/0"] }

user_slack_token = "example-user-token"
slack_token      = "example-bot-token"
king_slack_token = "example-debug-token"
slack_channel    = "#healthbot-ministack"
twilio_to        = 15555550100
twilio_from      = 15555550101
twilio_token     = "example-twilio-token"
twilio_account   = "example-twilio-account"
ga_property_id   = "properties/000000000"
new_relic_api    = "example-new-relic-key"
VARIABLES
}

action="${1:-plan}"
[[ $# -gt 0 ]] && shift

if [[ "$action" == "clean" ]]; then
    rm -rf "$ROOT"
    echo "removed the generated root"
    exit 0
fi

require_local
require_up
export_credentials

if [[ "$action" == "prereq" ]]; then
    prereq
    exit 0
fi

build_root
[[ -d "${ROOT}/prereq" ]] || prereq
[[ -f "${ROOT}/ministack.auto.tfvars" ]] || write_variables

cd "$ROOT"
terraform init -reconfigure -input=false -no-color >/dev/null

# Nothing here can answer a prompt, so a write action approves itself. That is
# safe only because every path above has proved the endpoint is an emulator.
approve=()
case "$action" in
    apply | destroy) approve=(-auto-approve) ;;
esac

exec terraform "$action" -input=false "${approve[@]}" "$@"
