"""
The suite never resolves a real runtime default.

healthbot.logs builds its file sink from settings, and log_dir defaults to the
directory a real run logs to, alongside the captures a failed checkout leaves
behind. A test that reaches that path writes into someone's evidence, so the
harness hands every test a directory of its own instead.
"""

# Standard library imports
import os
import shutil
import tempfile

# Set at import rather than in a fixture: pytest imports this file before it
# imports any test module, and healthbot.logs reads log_dir as it is imported.
# A fixture runs too late to redirect anything.
_STATE_DIR = tempfile.mkdtemp(prefix="healthbot-tests-")

os.environ["HB_LOG_DIR"] = os.path.join(_STATE_DIR, "logs")
os.environ["HB_DORA_EVENTS"] = os.path.join(_STATE_DIR, "dora-events.jsonl")


def pytest_sessionfinish(session, exitstatus):
    """Drop the run's state directory, open file sinks and all."""
    shutil.rmtree(_STATE_DIR, ignore_errors=True)
