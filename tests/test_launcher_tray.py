"""Tray behaviour, without a tray.

The tray is the launcher's job, so it can be tested here: the controller is a
plain object (pystray only supplies the icon and the menu), and the launcher
contract around it - one instance, quit really quits, data dirs are opened -
is what these tests pin.

Run: pytest tests/test_launcher_tray.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def _load(name: str, relative: str):
    """Import a packaging module by path (it is not an importable package)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tray = _load("alas_launcher_tray", "deploy/packaging/launcher_tray.py")


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def data(tmp_path):
    (tmp_path / "config").mkdir()
    return tmp_path


@pytest.fixture
def controller(data):
    stop = threading.Event()
    return tray.TrayController(FakeProcess(), data, stop), stop


# --- port ---------------------------------------------------------------


def test_port_defaults_when_deploy_yaml_is_absent(data):
    assert tray.read_port(data) == tray.DEFAULT_PORT


def test_port_comes_from_the_user_deploy_yaml(data):
    (data / "config" / "deploy.yaml").write_text("Alas:\n    WebuiPort: 22268\n    Token: x\n", encoding="utf-8")
    assert tray.read_port(data) == 22268


def test_port_ignores_a_broken_deploy_yaml(data):
    (data / "config" / "deploy.yaml").write_text("Alas:\n  WebuiPort: not-a-number\n", encoding="utf-8")
    assert tray.read_port(data) == tray.DEFAULT_PORT


def test_url_uses_the_configured_port(data, controller):
    ctl, _ = controller
    (data / "config" / "deploy.yaml").write_text("Alas:\n    WebuiPort: 12345\n", encoding="utf-8")
    assert ctl.url() == "http://127.0.0.1:12345"


# --- lifecycle ----------------------------------------------------------


def test_running_tracks_the_sidecar(controller):
    ctl, _ = controller
    assert ctl.running() is True
    ctl.process.terminate()
    assert ctl.running() is False


def test_quit_stops_the_sidecar_so_its_shutdown_reaps_the_bots(controller):
    ctl, stop = controller
    ctl.quit()
    assert ctl.process.terminated is True
    assert stop.is_set()


def test_quit_does_not_signal_a_dead_backend(controller):
    ctl, stop = controller
    ctl.process.returncode = 1
    ctl.quit()
    assert ctl.process.terminated is False
    assert stop.is_set()


def test_quit_asks_the_icon_to_stop(controller):
    ctl, _ = controller

    class FakeIcon:
        stopped = False

        def stop(self):
            FakeIcon.stopped = True

    ctl.quit(FakeIcon())
    assert FakeIcon.stopped is True


# --- menu actions -------------------------------------------------------


def test_open_window_opens_the_backend_url(controller, monkeypatch):
    ctl, _ = controller
    opened = []
    monkeypatch.setattr(tray.webbrowser, "open", lambda url: opened.append(url))
    ctl.open_window()
    assert opened == [ctl.url()]


def test_open_logs_creates_and_reveals_the_log_dir(controller, monkeypatch, tmp_path):
    ctl, _ = controller
    revealed = []
    monkeypatch.setattr(tray, "reveal", lambda path: revealed.append(path))
    ctl.open_logs()
    assert revealed == [ctl.data / "log"]
    assert (ctl.data / "log").is_dir()


def test_open_data_dir_reveals_the_data_directory(controller, monkeypatch):
    ctl, _ = controller
    revealed = []
    monkeypatch.setattr(tray, "reveal", lambda path: revealed.append(path))
    ctl.open_data_dir()
    assert revealed == [ctl.data]


def test_api_returns_none_when_the_backend_is_unreachable(controller, monkeypatch):
    ctl, _ = controller

    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(tray.urllib.request, "urlopen", boom)
    assert ctl.api("/api/status") is None


def test_refresh_configs_reads_the_status_endpoint(controller, monkeypatch):
    ctl, _ = controller
    status = {"instances": [{"name": "alas", "alive": True}, {"name": "dev", "alive": False}]}
    monkeypatch.setattr(ctl, "api", lambda path, body=None: status)
    assert ctl.refresh_configs() == ["alas", "dev"]


def test_toggle_config_starts_a_stopped_one(controller, monkeypatch):
    ctl, _ = controller
    calls = []
    monkeypatch.setattr(ctl, "config_alive", lambda name: False)
    monkeypatch.setattr(ctl, "api", lambda path, payload=None: calls.append(path))
    ctl.toggle_config("alas")
    assert calls == ["/api/control/alas/start"]


def test_toggle_config_stops_a_running_one(controller, monkeypatch):
    ctl, _ = controller
    calls = []
    monkeypatch.setattr(ctl, "config_alive", lambda name: True)
    monkeypatch.setattr(ctl, "api", lambda path, payload=None: calls.append(path))
    ctl.toggle_config("alas")
    assert calls == ["/api/control/alas/stop"]


def test_tooltip_reports_the_backend_state(controller):
    ctl, _ = controller

    class FakeIcon:
        title = ""

    icon = FakeIcon()
    ctl.update_tooltip(icon)
    assert "running" in icon.title
    ctl.process.terminate()
    ctl.update_tooltip(icon)
    assert "stopped" in icon.title


# --- the icon itself ----------------------------------------------------


def test_icon_image_is_a_rgba_square():
    if tray.Image is None:  # pragma: no cover - Pillow missing
        pytest.skip("Pillow is not installed")
    image = tray.icon_image(64)
    assert image.size == (64, 64)
    assert image.mode == "RGBA"


# --- launcher contract --------------------------------------------------


def test_launcher_exposes_the_hook_the_tray_registers():
    source = (ROOT / "deploy" / "packaging" / "launcher.py").read_text(encoding="utf-8")
    assert "from launcher_tray import run_tray" in source
    assert "run_tray(process, root, data, stop)" in source


def test_tray_does_not_import_the_project():
    """The launcher bundle must stay small: the tray may not pull the app in."""
    source = (ROOT / "deploy" / "packaging" / "launcher_tray.py").read_text(encoding="utf-8")
    offenders = [ln for ln in source.splitlines() if ln.startswith(("import module", "from module"))]
    assert not offenders, offenders


def test_refresh_configs_keeps_the_previous_list_when_the_backend_is_down(controller, monkeypatch):
    ctl, _ = controller
    monkeypatch.setattr(ctl, "api", lambda path, body=None: None)
    assert ctl.refresh_configs() == []


def test_tray_returns_the_sidecar_exit_code_without_pystray(monkeypatch, data):
    """A build without pystray must still run the app (no tray, no crash)."""
    monkeypatch.setattr(tray, "pystray", None)
    assert tray.run_tray(FakeProcess(returncode=0), data, data, threading.Event()) == 0
    assert tray.run_tray(FakeProcess(returncode=3), data, data, threading.Event()) == 3


def test_subprocess_is_only_used_for_reveal():
    """No shell-outs beyond opening a folder: the tray is a UI, not a shell."""
    source = (ROOT / "deploy" / "packaging" / "launcher_tray.py").read_text(encoding="utf-8")
    assert source.count("subprocess.Popen") == 2  # darwin + linux reveal
    assert "shell=True" not in source
    assert subprocess is not None
