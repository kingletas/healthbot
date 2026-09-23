#!/usr/bin/env python3

"""
The deploy replaces /etc/healthbot.env, so every key first boot writes has to
reach the template or be refused by the playbook before the file is written.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CLOUD_INIT = REPO / "IT" / "terraform" / "data.tf"
GROUP_VARS = REPO / "IT" / "ansible" / "group_vars" / "all.yml"
PLAYBOOK = REPO / "IT" / "ansible" / "playbook.yml"


def first_boot_keys(hcl: str) -> set[str]:
    """The KEY="..." lines inside the cloud-init heredoc."""
    heredoc = re.search(r"<<EOF\n(.*?)\nEOF", hcl, re.DOTALL)
    assert heredoc, "no cloud-init heredoc found"
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", heredoc.group(1), re.MULTILINE))


def asserted_keys(playbook: list) -> set[str]:
    """Keys a task refuses to deploy without, written as 'KEY' in healthbot_env."""
    keys = set()
    for play in playbook:
        for task in play.get("tasks", []):
            that = (task.get("ansible.builtin.assert") or {}).get("that", [])
            for condition in [that] if isinstance(that, str) else that:
                keys.update(re.findall(r"'([A-Z][A-Z0-9_]*)' in healthbot_env", condition))
    return keys


def dropped_keys(boot: set[str], rendered: set[str], asserted: set[str]) -> set[str]:
    return boot - rendered - asserted


def test_every_first_boot_key_survives_a_deploy():
    boot = first_boot_keys(CLOUD_INIT.read_text())
    rendered = set(yaml.safe_load(GROUP_VARS.read_text())["healthbot_env"])
    asserted = asserted_keys(yaml.safe_load(PLAYBOOK.read_text()))

    assert boot, "found no keys in the first-boot payload, so this test checks nothing"
    assert dropped_keys(boot, rendered, asserted) == set()


def test_a_key_neither_rendered_nor_asserted_is_reported():
    hcl = 'content = <<EOF\nwrite_files:\n    HB_PARAM_PREFIX="/p/"\n    HB_NEW="x"\nEOF\n'
    playbook = [
        {"tasks": [{"ansible.builtin.assert": {"that": "'HB_PARAM_PREFIX' in healthbot_env"}}]}
    ]

    boot = first_boot_keys(hcl)

    assert boot == {"HB_PARAM_PREFIX", "HB_NEW"}
    assert dropped_keys(boot, {"HB_LOG_LEVEL"}, asserted_keys(playbook)) == {"HB_NEW"}
