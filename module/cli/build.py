"""`alas build` implementation: frontend / sidecar / installer."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from module.logger import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WEBAPP_DIR = REPO_ROOT / "webapp"


def _run(cmd: list[str], cwd: Path) -> int:
    logger.info(f"$ {' '.join(cmd)}  (cwd={cwd})")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(cmd)} (exit {result.returncode})")
    return result.returncode


def frontend() -> None:
    """Build the Svelte SPA (pnpm build) into webapp/dist.

    The FastAPI backend serves that dist directory directly, so after this
    command `alas run web` serves the UI without any other packaging step.
    """
    if not WEBAPP_DIR.is_dir():
        logger.error(f"webapp not found at {WEBAPP_DIR}")
        raise SystemExit(1)
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        logger.error("pnpm not found in PATH (install Node.js + pnpm)")
        raise SystemExit(1)
    _run([pnpm, "install"], WEBAPP_DIR)
    _run([pnpm, "build"], WEBAPP_DIR)
    logger.info(f"frontend built: {WEBAPP_DIR / 'dist'}")


def _pyinstaller(spec: Path, what: str) -> None:
    if not spec.is_file():
        logger.error(f"packaging spec not found: {spec}")
        raise SystemExit(1)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        logger.error("PyInstaller not installed (`uv sync --extra dev` 或 pip install pyinstaller)")
        raise SystemExit(1)
    _run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec)], REPO_ROOT)
    logger.info(f"{what} built")


def sidecar() -> None:
    """Build the PyInstaller onedir backend (deploy/packaging/alas_backend.spec)."""
    _pyinstaller(REPO_ROOT / "deploy" / "packaging" / "alas_backend.spec", "sidecar")
    logger.info(f"sidecar built: {REPO_ROOT / 'dist' / 'alas-backend'}")


def launcher() -> None:
    """Build the desktop launcher (deploy/packaging/launcher.spec)."""
    # The installer takes an .ico; the SPA ships a PNG, so render it first.
    _run([sys.executable, str(REPO_ROOT / "dev_tools" / "gen_app_icon.py")], REPO_ROOT)
    _pyinstaller(REPO_ROOT / "deploy" / "packaging" / "launcher.spec", "launcher")
    logger.info(f"launcher built: {REPO_ROOT / 'dist' / 'Alas'}")


def installer() -> None:
    """Build the NSIS installer (deploy/packaging/alas_installer.nsi)."""
    makensis = shutil.which("makensis")
    if makensis is None:
        logger.error("makensis not found in PATH (install NSIS, or let the release workflow build it)")
        raise SystemExit(1)
    version = os.environ.get("ALAS_VERSION", "dev")
    _run([makensis, f"/DVERSION={version}", str(REPO_ROOT / "deploy" / "packaging" / "alas_installer.nsi")], REPO_ROOT)
    logger.info(f"installer built: Alas_{version}_x64-setup.exe")
