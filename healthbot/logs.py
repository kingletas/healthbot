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

# The file sink keeps every line for the person diagnosing a failed run. The
# console is what a person and journald actually read, so it stays at
# HB_LOG_LEVEL, which is INFO unless somebody asks for more.
FILE_LEVEL = "DEBUG"


def console_level() -> str:
    """HB_LOG_LEVEL, or INFO when it names a level loguru does not have."""
    wanted = (get_settings().log_level or "").upper()
    if wanted in logger._core.levels:
        return wanted
    print(
        f"HB_LOG_LEVEL={wanted!r} is not a log level, so this run logs at INFO. "
        "Use one of DEBUG, INFO, WARNING, ERROR.",
        file=sys.stderr,
    )
    return "INFO"


# One console sink and one file sink. Loguru installs a default stderr
# handler on import, so adding stderr *and* stdout on top of it had journald
# recording every line twice.
logger.remove()
logger.add(
    sys.stderr,
    format="{time} {level} {name} {message}",
    level=console_level(),
    enqueue=True,
    **TRACEBACK_SETTINGS,
)


def add_file_sink() -> str | None:
    """
    The rotating file sink, or None when its directory cannot be made.

    Call it from an entry point and never at import: it creates log_dir, and an
    importer gets no chance to say where that should be first. Logging is never
    the thing that takes a run down, so an unwritable path costs the file, says
    so on stderr, and leaves the console sink the run already has.
    """
    log_d = get_settings().log_dir
    try:
        os.makedirs(log_d, exist_ok=True)
    except OSError as err:
        logger.warning(f"no log file: cannot create {log_d!r} ({err!r}); stderr only")
        return None

    # A calendar date, not loguru's DDDD, which is the day of the year and
    # reads as a mistyped year.
    log_file = os.path.join(log_d, "healthbot_{time:YYYY-MM-DD}.log")
    logger.add(log_file, retention="7 days", level=FILE_LEVEL, enqueue=True, **TRACEBACK_SETTINGS)
    return log_file
