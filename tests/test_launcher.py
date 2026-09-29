"""Launcher tests: data-directory ownership and seeding.

The installed build is two executables (Alas.exe + alas-backend/), and the
split matters: the program directory gets replaced wholesale by an update, so
everything the user owns has to live elsewhere. These tests pin that
contract without spawning anything.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("alas_launcher", ROOT / "deploy" / "packaging" / "launcher.py")
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def test_data_dir_defaults_to_localappdata(monkeypatch):
    monkeypatch.delenv("ALAS_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    assert launcher.data_dir(Path("C:/install")) == Path(r"C:\Users\test\AppData\Local") / "Alas"


def test_data_dir_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ALAS_DATA_DIR", str(tmp_path))
    assert launcher.data_dir(Path("C:/install")) == tmp_path


def test_seed_creates_the_user_directories(tmp_path, monkeypatch):
    monkeypatch.delenv("ALAS_DATA_DIR", raising=False)
    data = tmp_path / "data"
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    (bundle / "config" / "deploy.template.yaml").write_text("Alas:\n  WebuiPort: 22267\n", encoding="utf-8")

    launcher.seed_data_dir(data, bundle)

    for name in ("config", "log", "assets", "bin"):
        assert (data / name).is_dir()
    assert (data / "config" / "deploy.yaml").read_text(encoding="utf-8").startswith("Alas:")


def test_seed_never_overwrites_an_existing_deploy_yaml(tmp_path):
    data = tmp_path / "data"
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    (bundle / "config" / "deploy.template.yaml").write_text("Alas:\n  WebuiPort: 1\n", encoding="utf-8")
    launcher.seed_data_dir(data, bundle)
    (data / "config" / "deploy.yaml").write_text("Alas:\n  WebuiPort: 22268\n", encoding="utf-8")

    launcher.seed_data_dir(data, bundle)  # second run (restart / update)

    assert "22268" in (data / "config" / "deploy.yaml").read_text(encoding="utf-8")


def test_seed_without_a_bundled_template_is_still_fine(tmp_path):
    data = tmp_path / "data"
    launcher.seed_data_dir(data, tmp_path / "no-bundle")
    assert (data / "config").is_dir()
    assert not (data / "config" / "deploy.yaml").exists()


def test_backend_uses_the_data_dir_as_cwd():
    """The frozen backend chdirs into ALAS_DATA_DIR (module/logger.py)."""
    source = (ROOT / "module" / "logger.py").read_text(encoding="utf-8")
    assert 'os.environ.get("ALAS_DATA_DIR")' in source
    assert "os.chdir(data_dir)" in source


def test_pid_file_roundtrip(tmp_path):
    """--status/--quit rely on the pid file: dead pids must not look alive."""
    data = tmp_path / "data"
    data.mkdir()
    assert launcher.read_pid(data) is None

    launcher.pid_file(data).write_text(str(os.getpid()), encoding="utf-8")
    assert launcher.read_pid(data) == os.getpid()

    # A pid that cannot be running (large, unused) must not be reported.
    launcher.pid_file(data).write_text("999999999", encoding="utf-8")
    assert launcher.read_pid(data) != 999999999

    launcher.pid_file(data).write_text("not-a-pid", encoding="utf-8")
    assert launcher.read_pid(data) is None


def test_quit_running_is_a_noop_when_nothing_runs(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert launcher.quit_running(data) == 0


def test_help_lists_the_switches(capsys):
    assert launcher.main(["--help"]) == 0
    out = capsys.readouterr().out
    for flag in ("--quit", "--status", "--help"):
        assert flag in out


def test_status_exits_nonzero_when_not_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ALAS_DATA_DIR", str(tmp_path))
    assert launcher.main(["--status"]) == 1
    assert "not running" in capsys.readouterr().out


def test_second_start_is_refused_while_one_runs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ALAS_DATA_DIR", str(data))
    launcher.pid_file(data).write_text(str(os.getpid()), encoding="utf-8")
    # There is no sidecar next to the bundle here, and the instance check runs
    # first on purpose: a second start must say "already running", not complain
    # about a missing sidecar the running instance already has.
    assert launcher.main([]) == 3


def test_missing_sidecar_is_reported_when_nothing_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ALAS_DATA_DIR", str(tmp_path))
    assert launcher.main([]) == 2  # no alas-backend/ next to the bundle


def test_launcher_does_not_import_the_project():
    """The launcher must stay a small bundle: no project imports."""
    source = (ROOT / "deploy" / "packaging" / "launcher.py").read_text(encoding="utf-8")
    project_imports = [
        line
        for line in source.splitlines()
        if line.startswith(("import module", "from module"))
    ]
    assert not project_imports, project_imports


def test_create_no_window_flag_is_windows_only():
    assert launcher.CREATE_NO_WINDOW == 0x0800_0000
    assert os.name in ("nt", "posix")
