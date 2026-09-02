"""CLI argument resolution: CLI flags > deploy.yaml values > built-in defaults.

Kept as a pure function (no State/DeployConfig import) so precedence rules
are unit-testable without touching config files. Callers pass the deploy
values obtained from `State.deploy_config` (or a stand-in in tests).
"""

from __future__ import annotations

from dataclasses import dataclass

# Built-in defaults used when neither the flag nor deploy.yaml provides a value.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 22267


@dataclass(frozen=True)
class WebArgs:
    """Merged web-server options (flags > deploy.yaml > defaults)."""

    host: str
    port: int
    password: str | None
    ssl_key: str | None
    ssl_cert: str | None
    ssl: bool


def resolve_web_args(
    host: str | None = None,
    port: int | None = None,
    key: str | None = None,
    ssl_key: str | None = None,
    ssl_cert: str | None = None,
    deploy_host: str | None = None,
    deploy_port: int | None = None,
    deploy_password: str | None = None,
) -> WebArgs:
    """Merge explicit CLI flags over deploy.yaml values over defaults.

    Args:
        host/port/key/ssl_key/ssl_cert: values given on the command line (None = not given).
        deploy_*: values from config/deploy.yaml's Webui section.

    Returns:
        WebArgs: merged options. `ssl` is True only when both key and cert
        are present (matching the legacy gui.py behavior of logging an error
        and continuing without TLS when only one side is provided).
    """
    merged_host = host or deploy_host or DEFAULT_HOST
    merged_port = port or deploy_port or DEFAULT_PORT
    merged_password = key or deploy_password
    ssl = bool(ssl_key and ssl_cert)
    return WebArgs(
        host=merged_host,
        port=merged_port,
        password=merged_password,
        ssl_key=ssl_key,
        ssl_cert=ssl_cert,
        ssl=ssl,
    )
