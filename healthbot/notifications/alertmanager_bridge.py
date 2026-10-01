"""
Alertmanager webhook -> Slack, through HealthBot's own chat.postMessage
sender and its own secret.

Prometheus alerting rules (IT/observability/prometheus/rules/*.yml) decide
what is wrong; Alertmanager decides who to tell and how often
(alertmanager/alertmanager.yml's group_interval/repeat_interval -- a standing
alert backs off and a change in the group speaks); this is the "who": its
webhook receiver posts each firing/resolved group here, and this turns it
into one Slack message sent through SlackNotifier, the same client class a
real healthbot run uses.

The token and channel are read the same way healthbot.py's own main flow
reads them -- Parameter Store's secret_name pointer, then Secrets Manager --
not from a bridge-specific file or setting. There is exactly one place the
estate manages this credential rather than two, and a rotated token or a
changed channel takes effect on the next alert with no restart of this
process, for the same reason SecretsManager.get_secret never caches the
decrypted blob.

This does not go through healthbot.notifications.manager.send_notifications:
that function also checks a per-run "send_slack" flag from the bot's own
config, which is a decision about a health-check run, not about whether an
Alertmanager webhook should be delivered. Every alert this receives is
already something Alertmanager decided to route here, so this always
attempts to send.

Runs as its own tiny HTTP server. Nothing here needed a web framework, so
nothing pulled one in.

Usage:
    healthbot-alertmanager-bridge

Environment (beyond what a real healthbot run already needs against the
target AWS endpoint -- AWS_ENDPOINT_URL, AWS credentials, HB_PARAM_PREFIX --
see `healthbot --help`):
    HB_ALERT_BRIDGE_HOST   bind address (default 172.17.0.1, the docker
                            bridge address -- reachable from the host and
                            from the alertmanager container, not from the LAN)
    HB_ALERT_BRIDGE_PORT   bind port (default 9095)
    HB_SLACK_API_URL       WebClient base_url override, same variable
                            healthbot itself reads (unset = real Slack)
"""

import http.server
import json
import os
import socketserver

from healthbot.aws.parameter_store import ParameterStore
from healthbot.aws.secrets_manager import SecretsManager
from healthbot.config_files import get_config
from healthbot.errors import ConfigurationError
from healthbot.logs import logger
from healthbot.notifications.base import Message
from healthbot.notifications.slack import SlackNotifier, mrkdwn
from healthbot.settings import get_settings

HOST = os.environ.get("HB_ALERT_BRIDGE_HOST", "172.17.0.1")
PORT = int(os.environ.get("HB_ALERT_BRIDGE_PORT", "9095"))


def read_slack_credentials() -> tuple[str, str] | None:
    """
    slack_token and slack_channel, fetched exactly the way healthbot.py's own
    main flow fetches them (healthbot/healthbot.py: param_store -> secret_name
    -> SecretsManager). None means not ready yet -- no SSM parameter, no
    secret, or a secret without both keys -- which is the state before the
    operator loads the token, not an error worth crashing the server over.
    """
    try:
        settings = get_settings()
        hb_prefix = settings.param_prefix
        if hb_prefix is None:
            site_config = get_config("site.yml")
            hb_prefix = site_config.get("secrets_namespace_prefix")
        secret_name = ParameterStore().get_parameter(f"{hb_prefix}secret_name")
        secrets = SecretsManager().get_secret(name=secret_name)
    except ConfigurationError as err:
        logger.warning(f"alert bridge: secret not ready yet: {err!r}")
        return None

    token = secrets.get("slack_token")
    channel = secrets.get("slack_channel")
    if not token or not channel:
        logger.warning("alert bridge: secret has no slack_token/slack_channel yet")
        return None
    return token, channel


def alert_line(alert: dict) -> str:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = alert.get("status", "unknown")
    mark = ":small_red_triangle_down:" if status == "firing" else ":white_check_mark:"
    name = labels.get("alertname", "alert")
    summary = annotations.get("summary") or annotations.get("description") or ""
    return f"{mark} *{name}* ({status}): {summary}"


class AlertmanagerMessage(Message):
    """One Slack message per Alertmanager webhook group."""

    def __init__(self, payload: dict, channel: str) -> None:
        self.channel = channel
        alerts = payload.get("alerts", [])
        lines = [alert_line(a) for a in alerts]
        status = payload.get("status", "unknown")
        alertname = payload.get("groupLabels", {}).get("alertname", "alert")
        header_text = f"{'Firing' if status == 'firing' else 'Resolved'}: {alertname}"
        self.blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True},
            },
            {"type": "section", "text": mrkdwn("\n".join(lines) or "no alerts in this group")},
        ]
        self.message = json.dumps(self.blocks)
        self.text = f"{header_text}: {'; '.join(lines)}" if lines else header_text


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args) -> None:  # route through loguru, not stderr
        logger.debug("alert bridge: " + (fmt % args))

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/alert":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        credentials = read_slack_credentials()
        if credentials is None:
            # Alertmanager retries a non-2xx, so the alert is not lost -- it
            # is held until the secret is in place, then delivered on the
            # next retry with no restart of this process.
            self.send_response(503)
            self.end_headers()
            return
        token, channel = credentials

        try:
            SlackNotifier(logger, token=token).send(AlertmanagerMessage(payload, channel))
        except Exception as err:  # Alertmanager needs a response either way, whatever broke
            logger.error(f"alert bridge: send failed: {err!r}")
            self.send_response(502)
            self.end_headers()
            return

        self.send_response(200)
        self.end_headers()


def main() -> int:
    with socketserver.TCPServer((HOST, PORT), Handler) as httpd:
        logger.info(f"alertmanager bridge listening on {HOST}:{PORT}")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
