"""Alas desktop launcher (installed build).

The installed app is two executables:

    Alas.exe              <- this: GUI subsystem, no console window
    alas-backend/         <- the PyInstaller sidecar, console subsystem
        alas-backend.exe  <- `alas run desktop|web|headless`, the real bot

Why a launcher at all: `alas-backend.exe` must stay a console build, because
a windowed PyInstaller app routes an uncaught traceback into a modal dialog
that hangs invisibly (deploy/packaging/alas_backend.spec). The user, on the
other hand, must not get a black console window. When Tauri wrapped the
backend it used CREATE_NO_WINDOW; with Tauri gone (2026-09) nothing does that
any more, so the launcher took the job - plus the two things a launcher can do
better than the backend process:

- it owns the user data directory (`config/ log/ assets/ bin/`) and keeps it
  out of Program Files, so an update that replaces the program directory
  cannot touch user data;
- it can host the tray icon (see module/cli/tray.py) and the single-instance
  handshake, without the backend knowing about either.

The launcher imports nothing from the project on purpose: it must stay a
small bundle that can start (and outlive) the 200MB sidecar.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

# CREATE_NO_WINDOW: the sidecar keeps its console subsystem (so tracebacks go
# to stderr, which we mirror into backend.log) but no window appears.
CREATE_NO_WINDOW = 0x0800_0000
DETACHED_PROCESS = 0x0000_0008
CREATE_NEW_PROCESS_GROUP = 0x0000_0200


def bundle_dir() -> Path:
    """Directory holding the sidecar (the install root)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def data_dir(root: Path) -> Path:
    """The writable user data directory.

    Override with ALAS_DATA_DIR (used by the portable zip and by tests);
    otherwise %LOCALAPPDATA%\\Alas, so the program directory can be replaced
    wholesale during an update.
    """
    override = os.environ.get("ALAS_DATA_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Alas"


def seed_data_dir(target: Path, root: Path) -> None:
    """Create the user directories and seed the ones the app needs to exist.

    A fresh install has no `config/`: the app writes deploy.yaml and the
    per-config files on first run, but it expects the directory to be there.
    """
    for name in ("config", "log", "assets", "bin"):
        (target / name).mkdir(parents=True, exist_ok=True)
    # A bundled deploy.yaml is the template for a first run; copy it only when
    # the user has none, so re-running the launcher never overwrites settings.
    template = root / "config" / "deploy.template.yaml"
    user_deploy = target / "config" / "deploy.yaml"
    if template.is_file() and not user_deploy.exists():
        user_deploy.write_bytes(template.read_bytes())


def tail_to_log(stream, log_path: Path, stop: threading.Event) -> None:
    """Mirror the sidecar's stderr into <data>/log/backend.log.

    Without this, a crash in the frozen build is invisible: the console
    window is suppressed and the user has no other way to see the traceback.
    """
    with suppress(Exception):  # never let logging take the launcher down
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as sink:
            for raw in iter(stream.readline, ""):
                sink.write(f"[{time.strftime('%H:%M:%S')}] {raw}")
                sink.flush()
                if stop.is_set():
                    break
    with suppress(Exception):
        stream.close()


def pid_file(data: Path) -> Path:
    return data / "launcher.pid"


def read_pid(data: Path) -> int | None:
    """PID of a running launcher, if the file is there and the process is alive."""
    try:
        pid = int(pid_file(data).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if os.name == "nt":  # pragma: no cover - windows path, exercised on device
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return pid
        return None
    try:  # pragma: no cover - posix only
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def quit_running(data: Path, timeout: float = 15.0) -> int:
    """Ask a running instance to exit (the installer and the updater use this).

    Terminating the launcher takes the sidecar with it: the launcher owns the
    child process, and an installer that cannot stop the running copy cannot
    replace its files.
    """
    pid = read_pid(data)
    if pid is None:
        return 0
    if os.name == "nt":  # pragma: no cover - windows path
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
    else:  # pragma: no cover - posix only
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, 15)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if read_pid(data) is None:
            return 0
        time.sleep(0.3)
    return 1  # still there; the caller reports the failure


USAGE = """Alas desktop launcher

  Alas.exe              start the app (the common case; double-click it)
  Alas.exe --quit       stop a running instance (installer / updater use this)
  Alas.exe --status     print the running instance's pid, if any
  Alas.exe --help       this text
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = bundle_dir()
    data = data_dir(root)

    if "--help" in argv or "-h" in argv:
        sys.stdout.write(USAGE)
        return 0
    if "--quit" in argv:
        return quit_running(data)
    if "--status" in argv:
        pid = read_pid(data)
        sys.stdout.write(f"{pid}\n" if pid else "not running\n")
        return 0 if pid else 1

    seed_data_dir(data, root)

    # One instance per data directory: a second start would race the first for
    # the same port and the same config files. Checked before the sidecar, so
    # "already running" is the answer the user actually needs.
    if read_pid(data) is not None:
        sys.stderr.write("Alas is already running (check the window or the tray icon)\n")
        return 3

    sidecar = root / "alas-backend" / "alas-backend.exe"
    if not sidecar.is_file():
        sys.stderr.write(f"alas-backend.exe not found next to the launcher: {sidecar}\n")
        return 2

    env = dict(os.environ, ALAS_DATA_DIR=str(data))
    # The backend treats its CWD as the user data directory (module/base/paths.py).
    creationflags = CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(sidecar), "run", "desktop"],
        cwd=str(data),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )

    stop = threading.Event()
    if process.stderr is not None:
        threading.Thread(
            target=tail_to_log,
            args=(process.stderr, data / "log" / "backend.log", stop),
            daemon=True,
        ).start()
    pid_file(data).write_text(str(os.getpid()), encoding="utf-8")

    # The tray (S4) hooks in here; without it the launcher is a plain runner.
    try:
        from launcher_tray import run_tray  # bundled next to this file in the installed build
    except ImportError:
        run_tray = None
    if run_tray is not None:
        return int(run_tray(process, root, data, stop) or 0)

    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0
    finally:
        stop.set()
        with suppress(OSError):
            pid_file(data).unlink()


if __name__ == "__main__":
    raise SystemExit(main())
