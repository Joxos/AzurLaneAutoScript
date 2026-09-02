"""`alas build` implementation: frontend / sidecar / installer."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from module.logger import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WEBAPP_DIR = REPO_ROOT / "webapp-tauri"


def _run(cmd: list[str], cwd: Path) -> int:
    logger.info(f"$ {' '.join(cmd)}  (cwd={cwd})")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(cmd)} (exit {result.returncode})")
    return result.returncode


def frontend() -> None:
    """Build the Svelte SPA (pnpm build) into webapp-tauri/dist.

    The FastAPI backend serves that dist directory directly, so after this
    command `alas run web` serves the UI without any other packaging step.
    """
    if not WEBAPP_DIR.is_dir():
        logger.error(f"webapp-tauri not found at {WEBAPP_DIR}")
        raise SystemExit(1)
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        logger.error("pnpm not found in PATH (install Node.js + pnpm)")
        raise SystemExit(1)
    _run([pnpm, "install"], WEBAPP_DIR)
    _run([pnpm, "build"], WEBAPP_DIR)
    logger.info(f"frontend built: {WEBAPP_DIR / 'dist'}")


def sidecar() -> None:
    """Build the PyInstaller onedir backend (deploy/packaging/alas_backend.spec)."""
    spec = REPO_ROOT / "deploy" / "packaging" / "alas_backend.spec"
    if not spec.is_file():
        logger.error(f"packaging spec not found: {spec} (alas_backend.spec 仍为 DRAFT?)")
        raise SystemExit(1)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        logger.error("PyInstaller not installed (`uv sync --extra dev` 或 pip install pyinstaller)")
        raise SystemExit(1)
    _run([sys.executable, "-m", "PyInstaller", str(spec)], REPO_ROOT)
    logger.info(f"sidecar built: {REPO_ROOT / 'dist' / 'alas-backend'}")


def installer() -> None:
    """Build the NSIS installer (P0.5 scope, see design doc §2.4/§6)."""
    logger.warning("NSIS installer 尚未实现(P0.5 范围);当前请使用 `alas build frontend` + `alas build sidecar` 产物")
