"""Runtime flavors of `alas run`: headless / web / desktop.

Entry points were consolidated here from the legacy `alas.py` / `gui.py`
scripts (both removed). See .qoder/doc/reorg-cli-flow-2026.md §2 (P0).
"""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from typing import Any

from module.cli.args import WebArgs
from module.logger import logger

# ---------------------------------------------------------------------------
# headless
# ---------------------------------------------------------------------------


def run_headless(name: str) -> None:
    """Run the scheduler loop for one config without any UI (legacy `python alas.py` equivalent)."""
    # The automation loop runs many small image ops (screenshot, template
    # matching, preprocessing). OpenCV's default thread pool (one per core)
    # creates a thread storm on many-core machines and contends with the
    # desktop; a small pool is faster and keeps the system smooth.
    # (moved from alas.py import time)
    import cv2

    cv2.setNumThreads(2)

    from module.alas import AzurLaneAutoScript

    bot = AzurLaneAutoScript(config_name=name)
    bot.loop()


# ---------------------------------------------------------------------------
# web / desktop
# ---------------------------------------------------------------------------


def _apply_password(key: str | None) -> None:
    """Persist an explicit `--key` into deploy.yaml (Password gate reads it)."""
    if key is None:
        return
    from module.webui.setting import State

    State.deploy_config.Password = key


def _wait_until_ready(port: int, timeout: float = 60.0) -> bool:
    """Block (in the caller's thread) until 127.0.0.1:port accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _open_browser_when_ready(host: str, port: int, open_browser: bool) -> None:
    """Open the browser once the server answers (daemon thread, best effort)."""
    if not open_browser:
        return
    url = f"http://127.0.0.1:{port}"

    def _open() -> None:
        if _wait_until_ready(port):
            webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def _serve(ev: threading.Event | None, args: WebArgs, open_browser: bool, key: str | None) -> None:
    """Run uvicorn + the FastAPI app (legacy `python gui.py` body, now `alas run web`)."""
    import asyncio
    import sys

    import uvicorn

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    from module.webui.api import create_api_app
    from module.webui.setting import State

    State.restart_event = ev
    _apply_password(key)

    app = create_api_app()

    logger.hr("Launcher config")
    logger.attr("Host", args.host)
    logger.attr("Port", args.port)
    logger.attr("SSL", args.ssl)
    logger.attr("Reload", ev is not None)

    if args.ssl_key is None and args.ssl_cert is not None:
        logger.error("SSL certificate provided without key. Please provide both SSL key and certificate.")
    elif args.ssl_cert is None and args.ssl_key is not None:
        logger.error("SSL key provided without certificate. Please provide both SSL key and certificate.")

    _open_browser_when_ready(args.host, args.port, open_browser)

    # log_level="warning" silences uvicorn's per-request access logs; the
    # application logs go through the rich console handler (stdout) and the
    # startup marker still goes to stderr.
    if args.ssl:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            ssl_keyfile=args.ssl_key,
            ssl_certfile=args.ssl_cert,
            log_level="warning",
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def run_web(args: WebArgs, open_browser: bool = True, key: str | None = None) -> None:
    """Start the webui backend (legacy `python gui.py`, now `alas run web`).

    When deploy.yaml's EnableReload is on, the parent process supervises a
    child process and restarts it when the updater signals a reload (the
    legacy gui.py watchdog semantics).
    """
    from multiprocessing import Event, Process

    from module.webui.setting import State

    if not State.deploy_config.EnableReload:
        _serve(ev=None, args=args, open_browser=open_browser, key=key)
        return

    process: Any = None
    try:
        should_exit = False
        while not should_exit:
            event = Event()
            process = Process(target=_serve, args=(event, args, open_browser, key))
            process.start()
            while not should_exit:
                try:
                    b = event.wait(1)
                except KeyboardInterrupt:
                    should_exit = True
                    break
                else:
                    if b:
                        # Reload requested (updater): stop the child and start a fresh one.
                        process.terminate()
                        process.join()
                        break
                    elif not process.is_alive():
                        # Backend died unexpectedly; no point waiting for a
                        # reload event that will never come.
                        logger.critical("Webui backend exited unexpectedly")
                        should_exit = True
                        break
    finally:
        # Ctrl+C or any other exit path must not leave the uvicorn child
        # orphaned.
        if process is not None and process.is_alive():
            process.terminate()
            process.join()


def run_desktop(args: WebArgs, key: str | None = None) -> None:
    """Start the webui backend in a thread and open a native window (pywebview).

    Falls back to the default browser when pywebview is not installed (e.g.
    fresh source checkout without the optional dependency).
    """
    try:
        import webview  # probe only; imported again below after the server is up
    except ImportError:
        logger.warning("pywebview not installed, falling back to browser window")
        run_web(args, open_browser=True, key=key)
        return

    import uvicorn

    from module.webui.api import create_api_app
    from module.webui.setting import State

    State.restart_event = None
    _apply_password(key)

    server = uvicorn.Server(
        uvicorn.Config(create_api_app(), host=args.host, port=args.port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    logger.hr("Desktop window")
    logger.attr("Host", args.host)
    logger.attr("Port", args.port)

    if not _wait_until_ready(args.port):
        logger.critical("Backend did not become ready in time, exiting")
        server.should_exit = True
        thread.join(timeout=10)
        return

    import webview

    window = webview.create_window(
        "Alas", f"http://127.0.0.1:{args.port}", width=1280, height=800, min_size=(960, 600)
    )
    window.events.closed += lambda: setattr(server, "should_exit", True)
    webview.start()

    # Closing the window stops the server; its lifespan shutdown then kills
    # the bot processes (State.clearup / ProcessManager.stop), so nothing is
    # left orphaned (previously handled by Tauri's kill-on-close job object).
    thread.join(timeout=10)
