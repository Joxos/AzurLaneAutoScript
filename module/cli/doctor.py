"""`alas doctor`: environment probes for a source checkout."""

from __future__ import annotations

import importlib
import platform
import shutil
import sys
from pathlib import Path

from module.cli.version import version_string
from module.logger import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _probe(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    return True


def doctor() -> None:
    """Print a small environment report and exit 0/1 (non-zero when broken)."""
    logger.info("Alas doctor")
    logger.attr("Version", version_string())
    logger.attr("Python", sys.version.split()[0])
    logger.attr("Platform", platform.platform())

    ok = True

    def check(label: str, value: bool, hint: str = "") -> None:
        nonlocal ok
        status = "OK" if value else "MISSING"
        ok = ok and value
        logger.info(f"[{status}] {label} {hint}")

    for tool in ["adb", "node", "pnpm", "git"]:
        found = shutil.which(tool)
        check(f"tool.{tool}", bool(found), f"-> {found}" if found else "")

    for mod in ["fastapi", "uvicorn", "onnxruntime", "cv2", "adbutils", "uiautomator2", "webview"]:
        check(f"module.{mod}", _probe(mod))

    assets = REPO_ROOT / "assets"
    webapp = REPO_ROOT / "webapp"
    check("dir.assets", assets.is_dir())
    check("dir.webapp", webapp.is_dir())
    check("dir.frontend-dist", (webapp / "dist").is_dir(), "(build with `alas build frontend`)")

    if not ok:
        logger.warning("Some environment components are missing; see [MISSING] lines above")
        raise SystemExit(1)
