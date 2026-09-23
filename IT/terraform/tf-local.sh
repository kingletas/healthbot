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
health_answers() {
    python3 - "${ENDPOINT}/$1" <<'PY'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

# Any LocalStack-compatible emulator answers this path.
emulator_answering() {
    health_answers _localstack/health
}

# Only MiniStack answers its own path. The LocalStack community image answers the
# shared one too, and then fails the prereq seeding with a 501 on the RDS cluster.
require_up() {
    health_answers _ministack/health && return 0
    if emulator_answering; then
        echo "Something answers at ${ENDPOINT}, but it is not MiniStack." >&2
        echo "This tree reads an RDS cluster, and the LocalStack community image does not implement RDS." >&2
    else
        echo "The local AWS emulator is not answering at ${ENDPOINT}." >&2
    fi
    echo "Start MiniStack on that endpoint first: ministackorg/ministack." >&2
    exit 1
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
    done < <(cd "$HERE" && git ls-files '*.tf')

    # The committed lock comes too, or init resolves its own versions and the
    # run proves argument validation against providers the deployment will not
    # use. Copied rather than symlinked, unlike the HCL above: init writes to
    # this file, and a symlink would let a local run edit the committed pin.
    cp -f "${HERE}/.terraform.lock.hcl" "${ROOT}/.terraform.lock.hcl"

    # The tracked example is the deployable list of values, so planning with it
    # is what keeps it able to plan. It holds nothing but invented placeholders.
    ln -sf "${HERE}/terraform.tfvars.example" "${ROOT}/example.auto.tfvars"

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

  # Two attributes the emulator answers with values this resource never set:
  # SriovNetSupport comes back null so the provider plans its own default, which
  # forces replacement, and a description is invented that ModifyImageAttribute
  # then refuses to clear. Left alone the AMI never converges and the instance
  # launches against an id the same run deregistered.
  lifecycle {
    ignore_changes = [sriov_net_support, description]
  }
}

output "vpc_id" { value = aws_vpc.this.id }
output "subnet_id" { value = aws_subnet.this.id }
output "sns_name" { value = aws_sns_topic.this.name }
output "db_cluster_identifier" { value = aws_rds_cluster.this.cluster_identifier }
PREREQ

    # Applied on every run rather than once. The emulator is a container, so its
    # resources go when it restarts while this root's state file stays behind
    # claiming they are still there. A plan then fails five data sources deep in
    # data.tf with nothing in the message pointing back here.
    local log="${ROOT}/prereq/last-apply.log"
    if ! (cd "${ROOT}/prereq" && terraform init -input=false -no-color >/dev/null && terraform apply -auto-approve -input=false -no-color >"$log" 2>&1); then
        echo "seeding the emulator failed:" >&2
        cat "$log" >&2
        exit 1
    fi
    grep -E '^Apply complete' "$log" || true
}

# Only what the emulator decides, so the tracked example supplies everything
# else and the plan is what proves the example can still plan. The ids change
# whenever the emulator is reseeded, so this is rewritten on every run.
#
# The key pair and the service account file are generated throwaways: the
# configuration reads both off disk, so they have to exist before a plan runs.
write_variables() {
    local vpc subnet sns database
    vpc="$(cd "${ROOT}/prereq" && terraform output -raw vpc_id)"
    subnet="$(cd "${ROOT}/prereq" && terraform output -raw subnet_id)"
    sns="$(cd "${ROOT}/prereq" && terraform output -raw sns_name)"
    database="$(cd "${ROOT}/prereq" && terraform output -raw db_cluster_identifier)"

    [[ -f "${ROOT}/assets/ministack_key" ]] || ssh-keygen -q -t ed25519 -N '' -C healthbot-ministack -f "${ROOT}/assets/ministack_key"
    printf '{"type":"service_account","project_id":"healthbot-ministack"}\n' > "${ROOT}/assets/ga-service-account.json"

    # Sorts after example.auto.tfvars, and terraform loads auto tfvars in
    # lexical order with the later file winning, so these override the example.
    cat > "${ROOT}/ministack.auto.tfvars" <<VARIABLES
# Generated by tf-local.sh: the values only a running emulator can supply.
environment = "local"
profile     = null

vpc_id                = "${vpc}"
subnet_id             = "${subnet}"
sns_name              = "${sns}"
db_cluster_identifier = "${database}"

ssh_key      = { public = "${ROOT}/assets/ministack_key.pub" }
secrets_path = "${ROOT}/assets/ga-service-account.json"
VARIABLES
}

# Destroying before deleting the state, because the emulator outlives this root:
# removing the state alone leaves the resources behind, and the next seeding run
# then fails on a duplicate cluster identifier and a duplicate AMI name.
# Best effort, so an emulator that is already gone still leaves a clean tree.
clean() {
    local root
    if [[ -d "$ROOT" ]] && emulator_answering; then
        export_credentials
        for root in "$ROOT" "${ROOT}/prereq"; do
            [[ -f "${root}/terraform.tfstate" || -f "${root}/ministack.tfstate" ]] || continue
            (cd "$root" && terraform destroy -auto-approve -input=false -no-color >/dev/null 2>&1) \
                || echo "could not destroy everything in ${root}; restart the emulator to clear it" >&2
        done
    fi
    rm -rf "$ROOT"
    echo "removed the generated root"
}

action="${1:-plan}"
[[ $# -gt 0 ]] && shift

if [[ "$action" == "clean" ]]; then
    require_local
    clean
    exit 0
fi

require_local
require_up
export_credentials

if [[ "$action" == "prereq" ]]; then
    prereq
    exit 0
fi

"${HERE}/tf-vars-check.sh"

build_root
prereq
write_variables

cd "$ROOT"
terraform init -reconfigure -input=false -no-color >/dev/null

# Nothing here can answer a prompt, so a write action approves itself. That is
# safe only because every path above has proved the endpoint is an emulator.
approve=()
case "$action" in
    apply | destroy) approve=(-auto-approve) ;;
esac

exec terraform "$action" -input=false "${approve[@]}" "$@"
