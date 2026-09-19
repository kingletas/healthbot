"""
Typed runtime settings: every HB_* environment variable in one validated
object instead of scattered environ.get calls. Thresholds and site
configuration deliberately stay in site.yml/slo.yml, because those are declared
contracts, not per-host runtime knobs.
"""

# Standard library imports
from os import environ, path

# Third party imports
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HB_", extra="ignore")

    # SSM prefix for the run parameters; falls back to site.yml's
    # secrets_namespace_prefix when unset (the load-bearing default L11
    # documented: production has only ever used the fallback)
    param_prefix: str | None = None

    # Stamped on telemetry as deployment.environment
    environment: str = "local"

    # Tri-state: True/False forces, None defers to whether an OTLP endpoint
    # is configured
    otel_enabled: bool | None = None

    # Who this monitor reports as, stamped as service.instance.id and exported
    # as the Prometheus instance label. It defaults to the hostname, which is
    # the identity every run on one machine shares; set it when two bots watch
    # different sites from the same host.
    otel_instance_id: str | None = None

    # How much the console says. INFO keeps a healthy run quiet, which is what
    # every document promises; the log file stays at DEBUG either way.
    log_level: str = "INFO"

    # Where run logs and failed-checkout evidence are written. The default is
    # outside the installed package: a wheel install put both inside
    # site-packages, which a read-only install refuses and nobody thinks to
    # look in. The systemd unit points this at its own LogsDirectory.
    log_dir: str = path.join(
        environ.get("XDG_STATE_HOME") or path.expanduser("~/.local/state"),
        "healthbot",
        "logs",
    )

    # DORA event journal and the repo lead time is computed against
    dora_events: str = path.expanduser("~/.local/share/healthbot/dora-events.jsonl")
    dora_repo: str = "."

    # Local-stack seams. Each one redirects a single external dependency at
    # a stand-in (IT/local's Mattermost shim and API stubs, and MiniStack) and
    # is a no-op when unset, which is the production state. AWS needs no seam
    # here: boto3 honours AWS_ENDPOINT_URL natively.
    #
    # Alternate config directory; files missing there fall back to the
    # packaged healthbot/config so a local override dir carries only the
    # files whose values actually differ (site.yml, mostly).
    config_dir: str | None = None
    # New Relic API base URL (the stub's /nr/v2/ endpoint locally)
    nr_api_url: str | None = None
    # slack_sdk WebClient base_url, locally the shim that relays
    # chat.postMessage into Mattermost
    slack_api_url: str | None = None
    # googleapiclient discovery document URL; setting it also disables the
    # bundled static discovery, or the override would silently not apply
    ga_discovery_url: str | None = None


def get_settings() -> Settings:
    # Deliberately uncached: a five-minute batch process constructs this a
    # handful of times, and caching would make tests and long-lived callers
    # see stale environments
    return Settings()
