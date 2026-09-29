"""Render the app icon (webapp/public/alas.png) into a multi-size .ico.

NSIS only accepts .ico for MUI_ICON, the start-menu shortcut and the
uninstaller; the SPA ships a single PNG. Generating it here keeps the icon a
build product (same rule as everything else: no hand-made binaries) and gives
the desktop shell and the installer the same mark.

Usage:
    .venv\\Scripts\\python.exe dev_tools/gen_app_icon.py [out.ico]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "webapp" / "public" / "icon" / "alas.png"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else ROOT / "build" / "alas.ico"
    if not SOURCE.is_file():
        print(f"icon source missing: {SOURCE}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as image:
        image.convert("RGBA").save(out, format="ICO", sizes=SIZES)
    print(f"wrote {out} ({', '.join(f'{s[0]}x{s[1]}' for s in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
