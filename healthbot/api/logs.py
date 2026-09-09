#!/usr/bin/env python3

# Standard Library imports
import os
import sys

# Third party imports
from loguru import logger

# Local imports
from healthbot import log_d

# One console sink and one file sink. Loguru installs a default stderr
# handler on import, so adding stderr *and* stdout on top of it had journald
# recording every line twice.
logger.remove()
logger.add(
    sys.stderr,
    format="{time} {level} {name} {message}",
    level="DEBUG",
    enqueue=True,
)

os.makedirs(log_d, exist_ok=True)

log_file = os.path.join(log_d, "healthbot_{time:YYMMDDDD}.log")

logger.add(log_file, retention="7 days", enqueue=True)
