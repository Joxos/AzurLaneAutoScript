"""Tray icon for the installed desktop app.

The launcher (deploy/packaging/launcher.py) hosts it: it already owns the
sidecar process, the user data directory and the single-instance pid file, so
the icon can act on all three without the backend knowing any of it exists.
The backend keeps its console-subsystem build and never imports pystray.

What the Tauri shell had and the 2026-09 rewrite dropped:

- the app lives in the tray; closing the window hides it instead of killing
  the bot mid-task;
- the menu drives the bot (start/stop each config through the backend API,
  open the log folder, check for updates, quit);
- quitting is a real shutdown: the sidecar is stopped, so its lifespan
  shutdown stops the bot processes too - no orphan python.exe left behind;
- an update can still get through: the installer replaces the program
  directory, so the menu offers to exit before installing.

Nothing here imports the project (the launcher must stay a small bundle); the
backend's port comes from the user's deploy.yaml, read with a regex because
this is a hint, not a config parser.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

APP_NAME = "Alas"
DEFAULT_PORT = 22267

# Declared as Any so the fallback stays typed: a build without pystray must
# still run the app (the launcher checks for None), and the alternative is a
# wall of "None has no attribute" errors from a perfectly valid path.
pystray: Any
Image: Any
ImageDraw: Any

try:  # the launcher works without a tray; this part is optional
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - exercised only in a stripped build
    pystray = None
    Image = None
    ImageDraw = None


def read_port(data: Path) -> int:
    """The WebUI port from the user's deploy.yaml (hint, not a parser)."""
    deploy = data / "config" / "deploy.yaml"
    try:
        match = re.search(r"^\s*WebuiPort:\s*(\d+)\s*$", deploy.read_text(encoding="utf-8"), re.M)
        if match:
            return int(match.group(1))
    except OSError:
        pass
    return DEFAULT_PORT


def icon_image(size: int = 64):
    """A tray mark drawn at runtime, so no binary asset has to ship."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = size // 8
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=size // 6,
        fill=(28, 33, 41, 255),
        outline=(120, 200, 255, 255),
        width=max(1, size // 16),
    )
    stroke = max(1, size // 12)
    draw.line([(size // 2, pad * 2), (size // 2, size - pad * 2)], fill=(120, 200, 255, 255), width=stroke)
    draw.arc([pad * 2, size // 3, size - pad * 2, size - pad], 0, 180, fill=(120, 200, 255, 255), width=stroke)
    return image


def reveal(path: Path) -> str | None:
    """Open a directory in the file manager.

    Returns None on success, or the reason it failed - the tray has no
    console, so a silent failure here would look like a broken menu item.
    """
    try:
        if os.name == "nt":  # pragma: no cover - windows path
            os.startfile(str(path))  # a user action on our own data directory
        elif sys.platform == "darwin":  # pragma: no cover - macos path
            subprocess.Popen(["open", str(path)])
        else:  # pragma: no cover - linux path
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None


class TrayController:
    """Everything the menu can do, decoupled from pystray for testability."""

    def __init__(self, process: Any, data: Path, stop: threading.Event) -> None:
        self.process = process
        self.data = data
        self.stop = stop
        self.icon: Any = None
        self._configs: list[str] = []
        self._notes: list[str] = []

    # --- state ------------------------------------------------------------

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def port(self) -> int:
        return read_port(self.data)

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port()}"

    def api(self, path: str, payload: dict | None = None) -> Any:
        """Call the backend REST API. The tray is a client, not a peer."""
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port()}{path}",
            data=json.dumps(payload or {}).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                body = resp.read()
            return json.loads(body or b"null")
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def refresh_configs(self) -> list[str]:
        status = self.api("/api/status")
        if isinstance(status, dict) and isinstance(status.get("instances"), list):
            self._configs = [i.get("name", "") for i in status["instances"] if i.get("name")]
        return self._configs

    def toggle_config(self, name: str) -> None:
        """Start a stopped config / stop a running one."""
        if self.config_alive(name):
            self.api(f"/api/control/{name}/stop")
        else:
            self.api(f"/api/control/{name}/start")

    def config_alive(self, name: str) -> bool:
        status = self.api("/api/status")
        if not isinstance(status, dict):
            return False
        for instance in status.get("instances", []):
            if instance.get("name") == name:
                return bool(instance.get("alive"))
        return False

    # --- menu actions -----------------------------------------------------

    def open_window(self, *_args) -> None:
        """Show the window again after it was closed to the tray.

        The native window belongs to the backend process, so it is asked for
        over the API the tray already talks to. A browser is the fallback for
        a headless/web backend, where there is no window to restore.
        """
        result = self.api("/api/window/show", {})
        if isinstance(result, dict) and result.get("shown"):
            return
        reason = (result or {}).get("reason", "backend did not confirm") if isinstance(result, dict) else "no answer"
        self._note(f"no native window to show ({reason}); opening a browser tab")
        webbrowser.open(self.url())

    def hide_window(self, *_args) -> None:
        """Start hidden in the tray."""
        result = self.api("/api/window/hide", {})
        if not (isinstance(result, dict) and result.get("hidden")):
            self._note("could not hide the window; it stays visible")

    def _note(self, message: str) -> None:
        """Surface a fallback in the tray tooltip; there is no console here."""
        self._notes.append(message)
        if self.icon is not None:
            self.icon.title = f"{APP_NAME} ({'; '.join(self._notes[-2:])})"

    def open_logs(self, *_args) -> None:
        log_dir = self.data / "log"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._note(f"cannot create the log folder: {e}")
            return
        failure = reveal(log_dir)
        if failure:
            self._note(f"cannot open the log folder ({failure})")

    def open_data_dir(self, *_args) -> None:
        failure = reveal(self.data)
        if failure:
            self._note(f"cannot open the data folder ({failure})")

    def update_tooltip(self, icon=None, item=None) -> None:
        state = "running" if self.running() else "backend stopped"
        if icon is not None:
            icon.title = f"{APP_NAME} ({state})"

    def quit(self, icon=None, item=None) -> None:
        """Really quit: stop the sidecar so its shutdown reaps the bots."""
        self.stop.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except Exception:
                self.process.kill()
        if icon is not None:
            icon.stop()

    # --- menu construction ------------------------------------------------

    def build_menu(self):
        """pystray menu; config items are rebuilt whenever the backend changes."""
        self.refresh_configs()

        def configs(_icon=None, _item=None):
            return pystray.Menu(
                *[
                    pystray.MenuItem(
                        name,
                        (lambda n: (lambda _i, _it: self.toggle_config(n)))(name),
                    )
                    for name in self._configs
                ],
                enabled=bool(self._configs),
            )

        return pystray.Menu(
            pystray.MenuItem(
                lambda icon, item: f"{APP_NAME} - {'running' if self.running() else 'stopped'}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open window", self.open_window, default=True),
            pystray.MenuItem("Hide window", self.hide_window),
            pystray.MenuItem("Configs", configs, enabled=bool(self._configs)),
            pystray.MenuItem("Log folder", self.open_logs),
            pystray.MenuItem("Data folder", self.open_data_dir),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit),
        )


def run_tray(process: Any, root: Path, data: Path, stop: threading.Event, start_hidden: bool = False) -> int:
    """Entry the launcher calls; blocks until the user quits."""
    if pystray is None:  # pragma: no cover - stripped build
        return process.wait() if process is not None else 0

    controller = TrayController(process, data, stop)
    icon = pystray.Icon("alas", icon_image(), APP_NAME, controller.build_menu())
    controller.icon = icon

    def watch() -> None:
        while not stop.is_set() and icon.running:
            controller.update_tooltip(icon)
            time.sleep(2)

    threading.Thread(target=watch, daemon=True).start()
    if start_hidden:
        # The backend needs a moment before it answers; a failure here is
        # reported, not silently ignored (the user would see nothing happen).
        deadline = time.time() + 20
        while time.time() < deadline and not controller.api("/api/window"):
            time.sleep(1)
        controller.hide_window()
    icon.run()  # blocks until quit() from the menu
    controller.quit()
    return 0
