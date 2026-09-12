# Standard library imports
import os
import sys

# Third party imports
from loguru import logger

# Local imports
from healthbot.settings import get_settings

# diagnose=False is the load-bearing one. Loguru turns it on by default, and
# it prints the value of every local variable in every frame of a traceback,
# so one uncaught error anywhere below the Secrets Manager read would write
# the Slack token, the Twilio token, the New Relic key and the Google service
# account key into the journal and into the log file. backtrace stays on:
# the frames are what makes a failed run diagnosable, the values are not.
TRACEBACK_SETTINGS = {"backtrace": True, "diagnose": False}

# One console sink and one file sink. Loguru installs a default stderr
# handler on import, so adding stderr *and* stdout on top of it had journald
# recording every line twice.
logger.remove()
logger.add(
    sys.stderr,
    format="{time} {level} {name} {message}",
    level="DEBUG",
    enqueue=True,
    **TRACEBACK_SETTINGS,
)


def add_file_sink() -> str | None:
    """
    The rotating file sink, or None when its directory cannot be made.

    Importing this module used to create the directory, so a process that
    could not write there, such as a container running as a system account
    with no home or a read-only install, died on the import rather than on
    anything it was asked to do. Logging is never the thing that takes a run down:
    an unwritable path costs the file, says so on stderr, and the run
    continues with the console sink it already has.
    """
    log_d = get_settings().log_dir
    try:
        os.makedirs(log_d, exist_ok=True)
    except OSError as err:
        logger.warning(f"no log file: cannot create {log_d!r} ({err!r}); stderr only")
        return None

    log_file = os.path.join(log_d, "healthbot_{time:YYMMDDDD}.log")
    logger.add(log_file, retention="7 days", enqueue=True, **TRACEBACK_SETTINGS)
    return log_file


log_file = add_file_sink()
