# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the desktop launcher (Alas.exe).

The launcher is the user's entry point and a GUI-subsystem executable: it
starts the sidecar with CREATE_NO_WINDOW, owns the user data directory, and
will host the tray icon. It deliberately imports nothing from the project, so
this bundle stays small even though the sidecar next to it is ~200MB.

Build:
    pyinstaller --clean --noconfirm deploy/packaging/launcher.spec

Result: dist/Alas/Alas.exe (paired with dist/alas-backend/ in the installer).
"""

import os

from PyInstaller.config import CONF

# Repo root: spec lives in <root>/deploy/packaging/
root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

CONF["distpath"] = os.path.join(root, "dist")
CONF["workpath"] = os.path.join(root, "build", "launcher")

a = Analysis(
    [os.path.join(root, "deploy", "packaging", "launcher.py")],
    pathex=[root, os.path.join(root, ".venv", "Lib", "site-packages")],
    binaries=[],
    datas=[],
    # The tray (S4) is the only optional import; keep the failure visible
    # rather than silently shipping a console-less app with no way out.
    hiddenimports=["pystray", "PIL.Image", "PIL.ImageDraw"],
    hookspath=[],
    excludes=["tkinter", "matplotlib", "pandas", "PyQt5", "PySide6", "numpy", "cv2", "scipy", "onnxruntime"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Alas",
    console=False,  # GUI subsystem: no console window for the user to stare at
    disable_windowed_traceback=False,
    # The SPA's own app mark; PyInstaller converts the PNG to an .ico.
    icon=os.path.join(root, "build", "alas.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Alas",
)
