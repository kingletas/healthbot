#!/usr/bin/env bash
#
# Refuse a tfvars file that disagrees with variables.tf, in either direction.
#
# Purpose: every tfvars file is gitignored, so terraform.tfvars.example is the
# only tracked statement of what a plan needs. Nothing checked it, and terraform
# itself only half can: a required variable with no value is an error, but a
# value for a variable nothing declares is a *warning*. That asymmetry is how
# ga_view_id survived the GA4 rename to ga_property_id, leaving the value
# supplied under a name that reached nothing and a plan that could not run.
#
# Two assertions, and both have to hold:
#
#   missing   a variable declared with no default, absent from the file, so
#             somebody copying it cannot plan
#   orphan    a name in the file that variables.tf does not declare, so the
#             value is silently ignored
#
# Silent when they agree. Needs no credentials, no state and no emulator, so it
# runs in the commit gate beside fmt and validate.
#
# Usage:
#   tf-vars-check.sh [file ...]   Check these files (default: the example)
#
# Environment overrides:
#   HB_TF_DIR   directory holding variables.tf (default: this script's own)

set -euo pipefail

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { sed -n '2,/^set -/p' "$0" | sed 's/^# \{0,1\}//;$d'; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${HB_TF_DIR:-$HERE}"

files=("$@")
[[ ${#files[@]} -gt 0 ]] || files=("${TF_DIR}/terraform.tfvars.example")

python3 - "${TF_DIR}/variables.tf" "${files[@]}" <<'PY'
import re
import sys

variables_file, *tfvars_files = sys.argv[1:]

# A declaration is `variable "name" {` down to the closing brace in column one.
# A default anywhere in that block makes the variable optional.
source = open(variables_file, encoding="utf-8").read()
blocks = re.findall(r'variable\s+"([A-Za-z0-9_]+)"\s*\{(.*?)\n\}', source, re.S)
if not blocks:
    sys.exit(f"no variable declarations found in {variables_file}")

declared = {name for name, _ in blocks}
required = {name for name, body in blocks if not re.search(r"^\s*default\s*=", body, re.M)}

failed = False
for path in tfvars_files:
    try:
        content = open(path, encoding="utf-8").read()
    except OSError as error:
        sys.exit(f"cannot read {path}: {error}")

    # An assignment starts in column one. Anything indented belongs to a map or
    # object value and is not a variable name.
    assigned = set(re.findall(r"^([A-Za-z0-9_]+)\s*=", content, re.M))

    missing = sorted(required - assigned)
    orphaned = sorted(assigned - declared)

    for name in missing:
        print(f"{path}: missing required variable {name}")
    for name in orphaned:
        print(f"{path}: {name} is not declared in {variables_file}")

    failed = failed or bool(missing or orphaned)

sys.exit(1 if failed else 0)
PY
