"""`alas` command definitions (thin; logic lives in run.py / build.py / doctor.py).

Console script: pyproject.toml `[project.scripts] alas = "module.cli:main"`.
It is the only runtime entry point; the legacy `alas.py` / `gui.py` scripts
have been removed. `python -m module.cli` stays available as a source
checkout equivalent.
"""

from __future__ import annotations

from typing import Annotated

import typer

from module.cli.args import resolve_web_args
from module.cli.version import version_string
from module.logger import logger

app = typer.Typer(
    name="alas",
    help="Alas unified launcher: one entry for headless/web/desktop and packaging.",
    no_args_is_help=True,
    add_completion=False,
)

run_app = typer.Typer(help="Run the bot.", no_args_is_help=True, add_completion=False)
app.add_typer(run_app, name="run")

build_app = typer.Typer(help="Build frontend / sidecar / installer.", no_args_is_help=True, add_completion=False)
app.add_typer(build_app, name="build")

@run_app.command("headless")
def run_headless(
    names: Annotated[
        list[str] | None, typer.Option("--name", "-n", help="Config name to run (single; default: alas).")
    ] = None,
) -> None:
    """Run the scheduler loop without any UI (the `alas run headless` flavor)."""
    names = names or ["alas"]
    if len(names) > 1:
        raise typer.BadParameter("headless 仅支持单个 --name,多个配置请用 `alas run web`")
    from module.cli.run import run_headless as _impl

    _impl(names[0])


@run_app.command("web")
def run_web(
    host: Annotated[str | None, typer.Option("--host", "-H", help="Bind host (default: deploy.yaml WebuiHost).")] = None,
    port: Annotated[int | None, typer.Option("--port", "-p", help="Bind port (default: deploy.yaml WebuiPort).")] = None,
    key: Annotated[str | None, typer.Option("--key", "-k", help="Webui password (persists to deploy.yaml).")] = None,
    ssl_key: Annotated[str | None, typer.Option("--ssl-key", help="SSL key file.")] = None,
    ssl_cert: Annotated[str | None, typer.Option("--ssl-cert", help="SSL certificate file.")] = None,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open the browser after startup.")] = False,
    _run: Annotated[
        list[str] | None, typer.Option("--run", help="[deprecated, ignored] Config names to start on launch.")
    ] = None,
) -> None:
    """Start the WebUI backend + SPA (the `alas run web` flavor)."""
    if _run:
        logger.warning("--run 已废弃并被忽略,请在 WebUI 中各配置自行启动")
    from module.cli.run import run_web as _impl

    args = resolve_web_args(host, port, key, ssl_key, ssl_cert, *_deploy_web_values())
    _impl(args, open_browser=not no_open, key=key)


@run_app.command("desktop")
def run_desktop(
    host: Annotated[str | None, typer.Option("--host", "-H", help="Bind host (default: deploy.yaml WebuiHost).")] = None,
    port: Annotated[int | None, typer.Option("--port", "-p", help="Bind port (default: deploy.yaml WebuiPort).")] = None,
    key: Annotated[str | None, typer.Option("--key", "-k", help="Webui password (persists to deploy.yaml).")] = None,
    ssl_key: Annotated[str | None, typer.Option("--ssl-key", help="SSL key file.")] = None,
    ssl_cert: Annotated[str | None, typer.Option("--ssl-cert", help="SSL certificate file.")] = None,
) -> None:
    """Start the WebUI backend and open a native desktop window (pywebview)."""
    from module.cli.run import run_desktop as _impl

    args = resolve_web_args(host, port, key, ssl_key, ssl_cert, *_deploy_web_values())
    _impl(args, key=key)


@build_app.command("frontend")
def build_frontend() -> None:
    """Build the Svelte SPA into webapp-tauri/dist."""
    from module.cli.build import frontend as _impl

    _impl()


@build_app.command("sidecar")
def build_sidecar() -> None:
    """Build the PyInstaller onedir backend (deploy/packaging spec)."""
    from module.cli.build import sidecar as _impl

    _impl()


@build_app.command("installer")
def build_installer() -> None:
    """Build the NSIS installer (P0.5 scope; not implemented yet)."""
    from module.cli.build import installer as _impl

    _impl()


@app.command()
def doctor() -> None:
    """Probe the environment (python/adb/node/pnpm/webview/backends)."""
    from module.cli.doctor import doctor as _impl

    _impl()


@app.command()
def version() -> None:
    """Print the installed Alas version."""
    typer.echo(version_string())


def _deploy_web_values() -> tuple[str | None, int | None, str | None]:
    """Read Webui section values from deploy.yaml (lazy: headless stays light)."""
    from module.webui.setting import State

    deploy = State.deploy_config
    return deploy.WebuiHost, deploy.WebuiPort, deploy.Password


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point."""
    import multiprocessing

    # Required when running frozen (PyInstaller sidecar): the EnableReload
    # watchdog spawns a child process on Windows.
    multiprocessing.freeze_support()
    app(argv)


if __name__ == "__main__":
    main()
