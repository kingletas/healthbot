#!/usr/bin/env python3

"""
The package's own invariants. Asserting the literal version string only ever
failed on the release that changed it, which told nobody anything.
"""

# Standard imports
import importlib
import tomllib
from pathlib import Path

import healthbot

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def project() -> dict:
    with open(PYPROJECT, "rb") as fp:
        return tomllib.load(fp)["project"]


def test_version_matches_pyproject():
    # Two files declare it, and telemetry stamps __init__'s value on every
    # span as service.version — so drift mislabels the exported data.
    assert healthbot.__version__ == project()["version"]


def test_every_console_script_resolves():
    # A wheel whose entry points do not import is one the deploy installs
    # happily and the timer then fails on, five minutes at a time.
    for entry in project()["scripts"].values():
        module_name, _, function_name = entry.partition(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name)), entry
