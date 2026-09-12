"""A traceback must carry the frames and never the values in them."""

import sys

from loguru import logger

from healthbot.logs import TRACEBACK_SETTINGS

FAKE_TOKEN = "xoxb-not-a-real-token-0123456789"  # pragma: allowlist secret


def _send_with(slack_token):
    # Shaped like the real thing: a credential is a local on the line that
    # fails, which is exactly when loguru's diagnose prints its value.
    return slack_token.post_to_slack()


def test_a_traceback_never_prints_the_values_of_locals(capsys):
    # diagnose=True is loguru's default. One uncaught error below the Secrets
    # Manager read would put every vendor token in the journal and the log.
    logger.remove()
    logger.add(sys.stderr, format="{message}", **TRACEBACK_SETTINGS)

    try:
        _send_with(FAKE_TOKEN)
    except AttributeError:
        logger.exception("run failed")

    written = capsys.readouterr().err
    assert "_send_with" in written, "the frames must survive"
    assert "post_to_slack" in written, "the failing line must survive"
    assert FAKE_TOKEN not in written, "diagnose leaked a credential into the log"
